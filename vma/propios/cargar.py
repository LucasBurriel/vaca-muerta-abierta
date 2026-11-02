"""Read the user's file, normalise it, compute its indicators with the published rules, register it in the session.

The output is a :class:`MisPozos`: three DataFrames (``produccion`` per well-month, ``pozos`` per well,
``indicadores`` per well with the same column names as the published ``indicadores`` where the rule applies) and
a ``meta`` dict (path, rows, wells, whether the file declares itself synthetic, the validation notes). ``registrar``
exposes them to the tools as DuckDB views ``mis_produccion``, ``mis_pozos``, ``mis_indicadores`` on the same
connection as the published tables, so a comparison is one join. Nothing is persisted (ADR-030).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from vma import units
from vma.indicadores import (
    ACUM_MESES,
    IP_DIAS,
    RAMA_MIN_M,
    SEP,
    acum_months,
    ip_at,
    months_between,
    ratio,
    ventana,
)
from vma.normalize import formation_key, sigla_l2
from vma.propios import esquema as E

FORMACION_DEFAULT = "Vaca Muerta"
MAX_FILAS_ARCHIVO = 2_000_000


@dataclass
class MisPozos:
    produccion: pd.DataFrame
    pozos: pd.DataFrame
    indicadores: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def n_pozos(self) -> int:
        return int(len(self.pozos))

    @property
    def siglas(self) -> list[str]:
        return self.pozos.sigla.tolist()


# --- reading ----------------------------------------------------------------------------------------------------


def leer_archivo(ruta: Path) -> pd.DataFrame:
    """CSV (auto-detected separator and encoding) or Parquet into a DataFrame, via DuckDB."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"no existe {ruta}")
    con = duckdb.connect()
    p = ruta.as_posix().replace("'", "''")
    if ruta.suffix.lower() in (".parquet", ".pq"):
        sql = f"SELECT * FROM read_parquet('{p}')"
    elif ruta.suffix.lower() in (".csv", ".txt", ".tsv"):
        sql = f"SELECT * FROM read_csv_auto('{p}', header=true, sample_size=-1, all_varchar=false)"
    else:
        raise ValueError(f"formato no soportado {ruta.suffix!r}: usá .csv o .parquet")
    try:
        df = con.execute(sql).df()
    except duckdb.Error as e:
        raise ValueError(f"no pude leer {ruta.name}: {e}") from e
    finally:
        con.close()
    if len(df) > MAX_FILAS_ARCHIVO:
        raise ValueError(f"{ruta.name} tiene {len(df)} filas; el máximo es {MAX_FILAS_ARCHIVO}")
    return df


def leer_meta_lateral(ruta: Path) -> dict:
    """``<archivo>.meta.json`` next to the data file, if present (the synthetic generator writes one)."""
    ruta = Path(ruta)
    cand = ruta.with_suffix(ruta.suffix + ".meta.json")
    if cand.exists():
        try:
            return json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


# --- normalising -------------------------------------------------------------------------------------------------


def _mes_fecha(df: pd.DataFrame, m: dict[str, str]) -> pd.Series:
    if "fecha" in m:
        f = df[m["fecha"]]
        if pd.api.types.is_datetime64_any_dtype(f):
            ts = pd.to_datetime(f, errors="coerce")
        else:
            s = f.astype(str).str.strip()
            s = s.where(~s.str.fullmatch(r"\d{4}-\d{2}"), s + "-01")
            s = s.where(~s.str.fullmatch(r"\d{4}\d{2}"), s.str[:4] + "-" + s.str[4:] + "-01")
            ts = pd.to_datetime(s, errors="coerce", format="mixed")
        return ts.dt.to_period("M").dt.to_timestamp()
    anio = pd.to_numeric(df[m["anio"]], errors="coerce")
    mes = pd.to_numeric(df[m["mes"]], errors="coerce")
    ok = anio.notna() & mes.notna() & mes.between(1, 12)
    out = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    out[ok] = pd.to_datetime(
        {"year": anio[ok].astype(int), "month": mes[ok].astype(int), "day": 1}, errors="coerce"
    )
    return out


def normalizar(
    crudo: pd.DataFrame, mapeo: dict[str, str] | None = None, pozos_crudo: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, E.Validacion]:
    """Raw frame(s) -> (produccion, pozos) with canonical columns, plus the validation (errors raise)."""
    val = E.validar_columnas(list(crudo.columns), mapeo)
    if not val.ok:
        raise ValueError(val.mensaje())
    m = val.mapeo
    prod = pd.DataFrame({"sigla_original": crudo[m["sigla"]].astype(str).str.strip()})
    prod["sigla"] = prod.sigla_original.map(sigla_l2)
    prod["mes_fecha"] = _mes_fecha(crudo, m)
    for c in ("petroleo_m3", "gas_mil_m3", "agua_m3", "tef"):
        prod[c] = pd.to_numeric(crudo[m[c]], errors="coerce") if c in m else np.nan
    prod["dias_mes"] = prod.mes_fecha.dt.days_in_month.astype(float)
    v2 = E.validar_valores(prod)
    if not v2.ok:
        raise ValueError(v2.mensaje())
    avisos = val.avisos + v2.avisos

    # well attributes: from the second file if given, else from the first row of each well in the production file
    fuente_pozos = pozos_crudo if pozos_crudo is not None else crudo
    mp = E.resolver_mapeo(list(fuente_pozos.columns), mapeo if pozos_crudo is None else None)
    if pozos_crudo is not None and "sigla" not in mp:
        raise ValueError("el archivo de pozos necesita una columna sigla (o alias)")
    atributos = pd.DataFrame({"sigla": fuente_pozos[mp["sigla"]].astype(str).str.strip().map(sigla_l2)})
    for c in E.POZOS_OPCIONALES:
        if c in mp:
            col = fuente_pozos[mp[c]]
            if c in ("rama_m", "etapas", "arena_tn", "agua_fractura_m3", "longitud", "latitud"):
                atributos[c] = pd.to_numeric(col, errors="coerce")
            else:
                atributos[c] = col.astype("string").str.strip()
        else:
            atributos[c] = None
    atributos = atributos.groupby("sigla", as_index=False).first()
    if "formacion" in mp:
        atributos["formacion"] = atributos.formacion.where(atributos.formacion.notna(), FORMACION_DEFAULT)
    else:
        atributos["formacion"] = FORMACION_DEFAULT
    if "ventana" in mp:
        v = atributos.ventana.astype("string").str.lower().str.replace(" ", "_", regex=False)
        malas = v.dropna()[~v.dropna().isin(E.VENTANAS)]
        if len(malas):
            avisos.append(
                f"ventana con valores fuera de {', '.join(E.VENTANAS)} en {len(malas)} pozo(s): se ignoran y se computa del GOR"
            )
        atributos["ventana"] = v.where(v.isin(E.VENTANAS), None)

    # one row per well × month: duplicates summed, tef = max (as the portal with several idpozo)
    g = prod.groupby(["sigla", "mes_fecha"], as_index=False).agg(
        sigla_original=("sigla_original", "first"),
        petroleo_m3=("petroleo_m3", "sum"),
        gas_mil_m3=("gas_mil_m3", "sum"),
        agua_m3=("agua_m3", "sum"),
        tef=("tef", "max"),
        dias_mes=("dias_mes", "first"),
        n_filas=("sigla", "size"),
    )
    pozos = pd.DataFrame({"sigla": sorted(g.sigla.unique())}).merge(atributos, on="sigla", how="left")
    pozos["formacion"] = pozos.formacion.fillna(FORMACION_DEFAULT)
    sin_atrib = set(atributos.sigla) - set(pozos.sigla)
    if sin_atrib:
        avisos.append(f"{len(sin_atrib)} pozo(s) del archivo de pozos sin producción: se ignoran")
    return g, pozos, E.Validacion(ok=True, avisos=avisos, mapeo=m)


# --- indicators with the published rules -----------------------------------------------------------------------


def _mensual(g: pd.DataFrame) -> pd.DataFrame:
    """Add k (month index from first production), tef_d, equivalente_m3 and the producing-day rates."""
    g = g.sort_values(["sigla", "mes_fecha"]).reset_index(drop=True)
    produce = (g.petroleo_m3.fillna(0) > 0) | (g.gas_mil_m3.fillna(0) > 0)
    first = g[produce].groupby("sigla").mes_fecha.min()
    pf = g.sigla.map(first)
    g["k"] = ((g.mes_fecha.dt.year - pf.dt.year) * 12 + (g.mes_fecha.dt.month - pf.dt.month)).astype("Int64")
    g["equivalente_m3"] = g.petroleo_m3.fillna(0) + g.gas_mil_m3.fillna(0).map(
        units.gas_thousand_m3_to_m3_oil_eq
    )
    tef = pd.to_numeric(g.tef, errors="coerce")
    sin_tef = tef.isna()
    tef = tef.fillna(0.0).clip(lower=0.0)
    g["tef_cero_con_produccion"] = (tef == 0) & produce & ~sin_tef
    g["tef_mayor_mes"] = tef > g.dias_mes
    g["tef_d"] = tef.where(~(sin_tef | g.tef_cero_con_produccion), g.dias_mes).clip(upper=g.dias_mes)
    g.loc[~produce & sin_tef, "tef_d"] = 0.0
    g["mes"] = g.k
    for f, r in (
        ("petroleo_m3", "petroleo_m3_d"),
        ("gas_mil_m3", "gas_mil_m3_d"),
        ("equivalente_m3", "equivalente_m3_d"),
    ):
        g[r] = np.where(g.tef_d > 0, g[f].fillna(0) / g.tef_d.replace(0, np.nan), np.nan)
    return g


def indicadores_propios(g: pd.DataFrame, pozos: pd.DataFrame) -> pd.DataFrame:
    """One row per well with the published indicator names (docs/indicadores.md), computed from the user's data."""
    rows = []
    ultimo = g.mes_fecha.max()
    attrs = pozos.set_index("sigla")
    for sigla, w in g.groupby("sigla", sort=True):
        a = attrs.loc[sigla]
        w = w[w.k.notna() & (w.k >= 0)]
        flags: list[str] = []
        row: dict = {"sigla": sigla, "sigla_original": w.sigla_original.iloc[0] if len(w) else sigla}
        for c in (
            "formacion",
            "campania",
            "operadora",
            "longitud",
            "latitud",
            "etapas",
            "arena_tn",
            "agua_fractura_m3",
        ):
            v = a.get(c)
            row[c] = None if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA else v
        rama = a.get("rama_m")
        rama = None if rama is None or pd.isna(rama) else float(rama)
        if rama is None:
            flags.append("sin_rama")
            normalizable = False
        elif rama < RAMA_MIN_M:
            flags.append("rama_corta")
            normalizable = False
        else:
            normalizable = True
        row["rama_m"] = rama
        row["rama_normalizable"] = normalizable
        if normalizable:
            row["etapas_por_100m"] = ratio(row["etapas"], rama) * 100 if row["etapas"] is not None else None
            row["arena_tn_por_m"] = ratio(row["arena_tn"], rama)
            row["agua_fractura_m3_por_m"] = ratio(row["agua_fractura_m3"], rama)
        if w.empty:
            flags.append("nunca_produjo")
            row.update({"cohorte": None, "primera_produccion": None, "meses_disponibles": 0})
            row["flags"] = SEP.join(flags)
            rows.append(row)
            continue
        first = w.mes_fecha.iloc[0]
        row["cohorte"] = int(first.year)
        row["primera_produccion"] = first
        row["meses_disponibles"] = months_between(first, ultimo)
        row["meses_con_registro"] = int(len(w))
        row["dias_efectivos_total"] = float(w.tef_d.sum())
        if w.tef.isna().all():
            flags.append("sin_tef_dias_calendario")
        if w.tef_cero_con_produccion.any():
            flags.append("tef_cero_con_produccion")
        if w.tef_mayor_mes.any():
            flags.append("tef_mayor_mes")
        if ((w.petroleo_m3 < 0) | (w.gas_mil_m3 < 0) | (w.agua_m3 < 0)).any():
            flags.append("volumen_negativo")
        if (w.n_filas > 1).any():
            flags.append("produccion_suma_filas")
        days = w.tef_d.to_numpy(dtype=float)
        kk = w.k.to_numpy(dtype=int)
        for h in IP_DIAS:
            vals = {
                f: ip_at(days, w[f].fillna(0).to_numpy(dtype=float), h)
                for f in ("petroleo_m3", "gas_mil_m3", "equivalente_m3")
            }
            if vals["petroleo_m3"] is None:
                flags.append(f"ip{h}_dias_insuficientes")
            for f, suf in (
                ("petroleo_m3", "petroleo_m3_d"),
                ("gas_mil_m3", "gas_mil_m3_d"),
                ("equivalente_m3", "equivalente_m3_d"),
            ):
                row[f"ip{h}_{suf}"] = vals[f]
                row[f"ip{h}_{suf}_por_m"] = ratio(vals[f], rama) if normalizable else None
        disp = row["meses_disponibles"]
        for n in ACUM_MESES:
            vals = {}
            for f in ("petroleo_m3", "gas_mil_m3", "agua_m3", "equivalente_m3"):
                vals[f], _ = acum_months(kk, w[f].fillna(0).to_numpy(dtype=float), n, disp)
            if vals["petroleo_m3"] is None:
                flags.append(f"acum{n}_historia_corta")
            for f in vals:
                row[f"acum{n}_{f}"] = vals[f]
                if f != "agua_m3":
                    row[f"acum{n}_{f}_por_m"] = ratio(vals[f], rama) if normalizable else None
        for n in (6, 12):
            oil, gas, water = row[f"acum{n}_petroleo_m3"], row[f"acum{n}_gas_mil_m3"], row[f"acum{n}_agua_m3"]
            if oil is not None:
                row[f"gor{n}_m3_m3"] = units.gas_thousand_m3_to_m3_gas(gas) / oil if oil > 0 else None
                if oil <= 0:
                    flags.append(f"gor{n}_sin_petroleo")
                if w.agua_m3.notna().any() and (oil + water) > 0:
                    row[f"corte_agua{n}"] = water / (oil + water)
        declarada = a.get("ventana")
        declarada = None if declarada is None or pd.isna(declarada) else str(declarada)
        gor_ref, src = None, None
        for n in (12, 6):
            if row.get(f"acum{n}_petroleo_m3") is not None:
                oil, gas = row[f"acum{n}_petroleo_m3"], row[f"acum{n}_gas_mil_m3"]
                gor_ref = (
                    units.gas_thousand_m3_to_m3_gas(gas) / oil if oil > 0 else (np.inf if gas > 0 else None)
                )
                src = f"gor{n}"
                break
        if src is None:
            oil, gas = float(w.petroleo_m3.fillna(0).sum()), float(w.gas_mil_m3.fillna(0).sum())
            gor_ref = units.gas_thousand_m3_to_m3_gas(gas) / oil if oil > 0 else (np.inf if gas > 0 else None)
            src = "gor_total"
        if declarada:
            row["ventana"], row["ventana_fuente"] = declarada, "declarada"
        else:
            row["ventana"] = ventana(gor_ref)
            row["ventana_fuente"] = src if row["ventana"] else None
            if row["ventana"] and src != "gor12":
                flags.append("ventana_provisoria")
        row["flags"] = SEP.join(dict.fromkeys(flags))
        rows.append(row)
    out = pd.DataFrame(rows)
    for c in ("cohorte", "meses_disponibles", "meses_con_registro"):
        if c in out:
            out[c] = out[c].astype("Int64")
    return out


# --- the public entry points ------------------------------------------------------------------------------------


ALIAS_SINTETICO = ("sintetico", "sintético", "demo")
_RAIZ_REPO = Path(__file__).resolve().parents[2]


def _elegir_en_carpeta(carpeta: Path) -> tuple[Path, Path | None]:
    """The production file (and the per-well attributes file, if any) inside a folder."""
    datos = sorted(
        p for p in carpeta.iterdir() if p.suffix.lower() in (".csv", ".parquet", ".pq", ".tsv", ".txt")
    )
    if not datos:
        raise FileNotFoundError(f"{carpeta} no tiene ningún .csv ni .parquet")
    prod = [p for p in datos if "produccion" in p.name.lower()] or [
        p for p in datos if not any(k in p.name.lower() for k in ("atributo", "pozos"))
    ]
    if len(prod) != 1:
        raise ValueError(
            f"{carpeta} tiene varios archivos de datos ({', '.join(p.name for p in datos)}): "
            "pasá la ruta del archivo de producción (y ruta_pozos si hay atributos aparte)"
        )
    attrs = [p for p in datos if p != prod[0] and any(k in p.name.lower() for k in ("atributo", "pozos"))]
    return prod[0], (attrs[0] if len(attrs) == 1 else None)


def resolver_ruta(ruta: Path | str, ruta_pozos: Path | str | None = None) -> tuple[Path, Path | None]:
    """Turn what a user (or a model) typed into the files to read.

    Accepts the alias ``sintetico`` (the bundled fixture, else the latest ``data/sintetico/<date>/``), a folder
    (picks ``*produccion*`` and ``*atributos*``/``*pozos*`` inside it), or a file; relative paths that do not
    exist from the working directory are retried against the repo root, since MCP hosts start the server anywhere.
    """
    texto = str(ruta).strip()
    if texto.lower() in ALIAS_SINTETICO:
        cands = [_RAIZ_REPO / "tests" / "fixtures" / "sintetico"]
        gen = _RAIZ_REPO / "data" / "sintetico"
        if gen.is_dir():
            cands += sorted((p for p in gen.iterdir() if p.is_dir()), reverse=True)
        for c in cands:
            if c.is_dir():
                return _elegir_en_carpeta(c)
        raise FileNotFoundError("no hay dataset sintético: generalo con `vma-pipeline sintetico` (ADR-030)")
    p = Path(texto).expanduser()
    if not p.exists() and not p.is_absolute() and (_RAIZ_REPO / p).exists():
        p = _RAIZ_REPO / p
    if p.is_dir():
        prod, attrs = _elegir_en_carpeta(p)
        return prod, (Path(ruta_pozos) if ruta_pozos else attrs)
    return p, (Path(ruta_pozos) if ruta_pozos else None)


def cargar(
    ruta: Path | str,
    mapeo: dict[str, str] | None = None,
    ruta_pozos: Path | str | None = None,
) -> MisPozos:
    """Read, validate, normalise and compute. Raises ``ValueError`` with a readable message on a bad file."""
    ruta, ruta_pozos = resolver_ruta(ruta, ruta_pozos)
    crudo = leer_archivo(ruta)
    pozos_crudo = leer_archivo(Path(ruta_pozos)) if ruta_pozos else None
    return desde_frames(crudo, mapeo, pozos_crudo, meta={"ruta": str(ruta), **leer_meta_lateral(ruta)})


def desde_frames(
    crudo: pd.DataFrame,
    mapeo: dict[str, str] | None = None,
    pozos_crudo: pd.DataFrame | None = None,
    meta: dict | None = None,
) -> MisPozos:
    g, pozos, val = normalizar(crudo, mapeo, pozos_crudo)
    g = _mensual(g)
    ind = indicadores_propios(g, pozos)
    meta = dict(meta or {})
    meta.update(
        {
            "filas": int(len(g)),
            "n_pozos": int(len(pozos)),
            "mes_min": g.mes_fecha.min().strftime("%Y-%m"),
            "mes_max": g.mes_fecha.max().strftime("%Y-%m"),
            "sintetico": bool(meta.get("sintetico", False)),
            "avisos": val.avisos,
            "mapeo": val.mapeo,
            "formaciones": sorted({formation_key(f) and f for f in pozos.formacion.dropna().unique()}),
        }
    )
    return MisPozos(produccion=g, pozos=pozos, indicadores=ind, meta=meta)


VISTAS = ("mis_produccion", "mis_pozos", "mis_indicadores")


def registrar(con: duckdb.DuckDBPyConnection, mis: MisPozos) -> None:
    """Expose the three frames as views on ``con`` (replacing a previous load). In memory only."""
    for nombre, df in (
        ("mis_produccion", mis.produccion),
        ("mis_pozos", mis.pozos),
        ("mis_indicadores", mis.indicadores),
    ):
        con.execute(f"DROP VIEW IF EXISTS {nombre}")
        con.unregister(f"_{nombre}") if f"_{nombre}" in _registrados(con) else None
        con.register(f"_{nombre}", df)
        con.execute(f"CREATE VIEW {nombre} AS SELECT * FROM _{nombre}")


def _registrados(con: duckdb.DuckDBPyConnection) -> set[str]:
    try:
        return {
            r[0] for r in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()
        }
    except duckdb.Error:
        return set()
