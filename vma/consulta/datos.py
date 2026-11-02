"""The published tables, in DuckDB, from either of two sources (ADR-026).

- **Parquet**: ``data/publicado/<date>/{pozos,indicadores,curvas_tipo}.parquet`` — every column, full precision.
  Never committed; produced by ``python pipeline.py master indicadores curvas``.
- **JSON**: ``site/data/*.json`` — the snapshot the static site serves, committed (ADR-022). A subset of columns,
  4 significant digits, type curves to month 60, percentiles only. It is what a fresh clone has.

Both end up as the same three DuckDB views, ``pozos``, ``indicadores`` and ``curvas_tipo``, so every tool in
:mod:`vma.consulta.herramientas` is written once. What the source lacks is declared, not guessed:
:meth:`Datos.columnas` says which columns exist, and a tool asked for a missing one answers "sin dato porque".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from vma.normalize import sigla_l2, sigla_l3, sigla_l4

TABLAS = ("pozos", "indicadores", "curvas_tipo")
NIVELES = ("cohorte_formacion", "cohorte_formacion_ventana", "cohorte_formacion_operadora")
DOCS = {
    "pozos": "docs/maestro.md",
    "indicadores": "docs/indicadores.md",
    "curvas_tipo": "docs/indicadores.md#curvas_tipo--columns",
}


@dataclass
class Datos:
    """A DuckDB connection with the three published tables as views, plus what is known about them."""

    con: duckdb.DuckDBPyConnection
    fuente: str  # "parquet" | "json"
    ruta: Path
    fecha_descarga: str | None
    version_maestro: str | None
    meta: dict = field(default_factory=dict)
    propios: Any = None  # the user's wells loaded this session (vma.propios.cargar.MisPozos), never persisted
    _columnas: dict[str, list[tuple[str, str]]] = field(default_factory=dict, repr=False)

    # --- schema -----------------------------------------------------------------------------------------

    def columnas(self, tabla: str) -> list[tuple[str, str]]:
        """``[(column, duckdb type), ...]`` of a table in this source."""
        if tabla not in TABLAS:
            raise KeyError(f"tabla desconocida: {tabla!r}; las tablas son {', '.join(TABLAS)}")
        if tabla not in self._columnas:
            rows = self.con.execute(f"DESCRIBE SELECT * FROM {tabla}").fetchall()
            self._columnas[tabla] = [(r[0], r[1]) for r in rows]
        return self._columnas[tabla]

    def tiene(self, tabla: str, columna: str) -> bool:
        return any(c == columna for c, _ in self.columnas(tabla))

    def faltantes(self, tabla: str, columnas: list[str]) -> list[str]:
        """The requested columns this source does not carry (empty with Parquet)."""
        return [c for c in columnas if not self.tiene(tabla, c)]

    def n_filas(self, tabla: str) -> int:
        return int(self.con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0])

    # --- queries ----------------------------------------------------------------------------------------

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def filas(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


# --- locating the source ----------------------------------------------------------------------------------------


def ultimo_publicado(root: Path) -> Path | None:
    """The newest ``data/publicado/<date>/`` with the three Parquet files, or None."""
    base = root / "data" / "publicado"
    if not base.exists():
        return None
    dias = sorted(
        p for p in base.iterdir() if p.is_dir() and all((p / f"{t}.parquet").exists() for t in TABLAS)
    )
    return dias[-1] if dias else None


def abrir(root: Path, fuente: str = "auto") -> Datos:
    """Open the published tables. ``fuente``: ``auto`` (Parquet if present, else JSON), ``parquet`` or ``json``."""
    root = Path(root)
    if fuente not in ("auto", "parquet", "json"):
        raise ValueError(f"fuente debe ser auto, parquet o json; recibí {fuente!r}")
    pub = ultimo_publicado(root)
    if fuente == "parquet" or (fuente == "auto" and pub is not None):
        if pub is None:
            raise FileNotFoundError(
                f"no hay tablas Parquet en {root / 'data' / 'publicado'}; "
                "corré `python pipeline.py master indicadores curvas` o usá --fuente json"
            )
        return abrir_parquet(pub, meta_json=root / "site" / "data" / "meta.json")
    site = root / "site" / "data"
    if not (site / "pozos.json").exists():
        raise FileNotFoundError(f"no hay snapshot JSON en {site} ni tablas Parquet; nada que consultar")
    return abrir_json(site)


# --- Parquet ----------------------------------------------------------------------------------------------------


def abrir_parquet(carpeta: Path, meta_json: Path | None = None) -> Datos:
    carpeta = Path(carpeta)
    con = duckdb.connect()
    for t in TABLAS:
        path = (carpeta / f"{t}.parquet").as_posix()
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{path}')")
    fecha, version = con.execute(
        "SELECT any_value(fecha_descarga), any_value(version_maestro) FROM indicadores"
    ).fetchone()
    meta = {}
    if meta_json is not None and Path(meta_json).exists():
        meta = json.loads(Path(meta_json).read_text(encoding="utf-8"))
    _registrar_claves(con)
    return Datos(
        con=con,
        fuente="parquet",
        ruta=carpeta,
        fecha_descarga=fecha,
        version_maestro=version or carpeta.name,
        meta=meta,
    )


# --- JSON snapshot ----------------------------------------------------------------------------------------------


def _leer(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pozos_json_a_tablas(P: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``pozos.json`` (indicadores + master join, columnar) -> (indicadores, pozos) DataFrames."""
    cols = P["columnas"]
    dic = P["flags_dic"]
    t = pd.DataFrame({k: v for k, v in cols.items() if k != "flags"})
    t["flags"] = ["|".join(dic[j] for j in idx) for idx in cols["flags"]]
    origen = P["origen"]
    ind_cols = [c for c, o in origen.items() if o.startswith("indicadores.")]
    maestro_cols = [c for c, o in origen.items() if o.startswith("pozos.")]
    ind = t[ind_cols].copy()
    pozos = t[["sigla", "sigla_clave", "operadora", "area", "cuenca", *maestro_cols]].copy()
    pozos = pozos.rename(columns={"formacion": "formacion_principal"})
    if "formacion" in t:
        pozos["formacion_principal"] = t["formacion"]
    pozos["flags"] = t[
        "flags"
    ]  # the snapshot carries one flag list (the indicator row's); say so in the docs
    for c in ("primera_produccion",):
        if c in pozos:
            pozos[c] = pd.to_datetime(pozos[c], errors="coerce")
        if c in ind:
            ind[c] = pd.to_datetime(ind[c], errors="coerce")
    return ind, pozos


def _curvas_json_a_tabla(C: dict, fecha: str | None, version: str | None) -> pd.DataFrame:
    rows = []
    for g in C["grupos"]:
        meses = g["mes"]
        for i, mes in enumerate(meses):
            row = {
                "nivel": C["nivel"],
                "cohorte": g["cohorte"],
                "formacion": g["formacion"],
                "ventana": g["ventana"],
                "operadora": g["operadora"],
                "incluye_outliers": g["incluye_outliers"],
                "mes": mes,
                "n_pozos": g["n_pozos"][i],
                "n_pozos_por_m": g["n_pozos_por_m"][i],
                "publicable": g["publicable"][i],
            }
            for tasa in C["tasas"]:
                serie = g["series"].get(tasa)
                for est in C["estadisticos"]:
                    row[f"{tasa}_{est}"] = serie[est][i] if serie else None
            row["fecha_descarga"] = fecha
            row["version_maestro"] = version
            rows.append(row)
    cols = (
        ["nivel", "cohorte", "formacion", "ventana", "operadora", "incluye_outliers", "mes"]
        + ["n_pozos", "n_pozos_por_m", "publicable"]
        + [f"{t}_{e}" for t in C["tasas"] for e in C["estadisticos"]]
        + ["fecha_descarga", "version_maestro"]
    )
    df = pd.DataFrame(rows, columns=cols)
    for c in ("cohorte", "mes", "n_pozos", "n_pozos_por_m"):
        df[c] = pd.to_numeric(df[c]).astype("Int64")
    return df


def abrir_json(site_data: Path) -> Datos:
    site_data = Path(site_data)
    meta = _leer(site_data / "meta.json") if (site_data / "meta.json").exists() else {}
    fecha = meta.get("fecha_descarga")
    version = meta.get("version_maestro")
    ind, pozos = _pozos_json_a_tablas(_leer(site_data / "pozos.json"))
    ind["fecha_descarga"] = fecha
    ind["version_maestro"] = version
    curvas = pd.concat(
        [
            _curvas_json_a_tabla(_leer(site_data / f"curvas_{n}.json"), fecha, version)
            for n in NIVELES
            if (site_data / f"curvas_{n}.json").exists()
        ],
        ignore_index=True,
    )
    con = duckdb.connect()
    con.register("_ind", ind)
    con.register("_pozos", pozos)
    con.register("_curvas", curvas)
    con.execute("CREATE TABLE indicadores AS SELECT * FROM _ind")
    con.execute("CREATE TABLE pozos AS SELECT * FROM _pozos")
    con.execute("CREATE TABLE curvas_tipo AS SELECT * FROM _curvas")
    _registrar_claves(con)
    return Datos(
        con=con,
        fuente="json",
        ruta=site_data,
        fecha_descarga=fecha,
        version_maestro=version,
        meta=meta,
    )


# --- sigla levels for buscar_pozo -----------------------------------------------------------------------------------


def _registrar_claves(con: duckdb.DuckDBPyConnection) -> None:
    """``pozos_claves``: one row per well with its sigla at levels L2, L3 and L4 (vma/normalize.py)."""
    base = con.execute("SELECT sigla, sigla_clave FROM pozos").df()
    base["l2"] = base["sigla_clave"].map(lambda s: sigla_l2(str(s)))
    base["l3"] = base["sigla_clave"].map(lambda s: sigla_l3(str(s)))
    base["l4"] = base["sigla_clave"].map(lambda s: sigla_l4(str(s)))
    con.register("_claves", base)
    con.execute("CREATE TABLE pozos_claves AS SELECT * FROM _claves")
