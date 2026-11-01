"""Phase 2a: per-well indicators with lineage.

One row per **physical well** of the master (ADR-015): the production of every ``idpozo`` of the
well is summed month by month, the formation is the master's ``formacion_principal`` and the
lateral length is the master's ``rama_m`` (ADR-010). Every indicator has one rule, written in
``docs/indicadores.md`` and applied here; every row carries ``flags`` (which rule fired, why a
value is null) and ``linaje`` (which columns and which master build fed it).

Time is measured in **effective producing days** (``tef``), not calendar days (ADR-016): the
initial rates IP30/IP90/IP180 are the volume produced in the first 30/90/180 producing days
divided by that many days, with the month in which the threshold falls prorated at its own
daily rate. Cumulatives at 6/12/24 months are calendar months counted from the first month with
oil or gas > 0 (month 0). Per-metre values use ``rama_m`` only when it is known and at least
``RAMA_MIN_M`` (ADR-019); otherwise they are null with the reason in ``flags``. Outliers on
IP90 per metre are detected by a declared rule (ADR-018) and **marked**, never removed.

Published as ``data/publicado/<date>/indicadores.csv`` and ``indicadores.parquet``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import units
from .download import latest_raw_dir
from .quality import connect_raw, df

SEP = "|"
RAMA_MIN_M = 500.0  # ADR-019: below this a "lateral" is a vertical/deviated well, not a horizontal one
IP_DIAS = (30, 90, 180)
ACUM_MESES = (6, 12, 24)
GOR_MESES = (6, 12)
MES_PARCIAL_DIAS = 15  # a first month with fewer producing days is flagged (brief §4)
OUTLIER_Z = 3.5  # ADR-018: robust z (median / MAD) on log10(IP90 per metre), by formation
OUTLIER_N_MIN = 20  # a formation with fewer evaluable wells is not screened
SCOPE_CUENCA = "NEUQUINA"  # ADR-002
SCOPE_TIPO = "NO CONVENCIONAL"
VENTANA_GOR_M3_M3 = (180.0, 1800.0)  # ADR-020: ~1,000 and ~10,000 scf/bbl; below = oil, above = gas

FLUIDOS = {"petroleo_m3": "petroleo_m3", "gas_mil_m3": "gas_mil_m3", "equivalente_m3": "equivalente_m3"}

COLUMNS = [
    "sigla",
    "sigla_clave",
    "idpozo_principal",
    "operadora",
    "formacion",
    "area",
    "cuenca",
    "tipo_recurso",
    "sub_tipo_recurso",
    "en_alcance",
    "cohorte",
    "primera_produccion",
    "meses_disponibles",
    "meses_con_registro",
    "dias_efectivos_total",
    "rama_m",
    "rama_normalizable",
    "etapas",
    "etapas_por_100m",
    "arena_tn_por_m",
    "agua_fractura_m3_por_m",
    "ip30_petroleo_m3_d",
    "ip30_gas_mil_m3_d",
    "ip30_equivalente_m3_d",
    "ip90_petroleo_m3_d",
    "ip90_gas_mil_m3_d",
    "ip90_equivalente_m3_d",
    "ip180_petroleo_m3_d",
    "ip180_gas_mil_m3_d",
    "ip180_equivalente_m3_d",
    "ip30_petroleo_m3_d_por_m",
    "ip30_gas_mil_m3_d_por_m",
    "ip30_equivalente_m3_d_por_m",
    "ip90_petroleo_m3_d_por_m",
    "ip90_gas_mil_m3_d_por_m",
    "ip90_equivalente_m3_d_por_m",
    "ip180_petroleo_m3_d_por_m",
    "ip180_gas_mil_m3_d_por_m",
    "ip180_equivalente_m3_d_por_m",
    "acum6_petroleo_m3",
    "acum6_gas_mil_m3",
    "acum6_agua_m3",
    "acum6_equivalente_m3",
    "acum12_petroleo_m3",
    "acum12_gas_mil_m3",
    "acum12_agua_m3",
    "acum12_equivalente_m3",
    "acum24_petroleo_m3",
    "acum24_gas_mil_m3",
    "acum24_agua_m3",
    "acum24_equivalente_m3",
    "acum6_petroleo_m3_por_m",
    "acum6_gas_mil_m3_por_m",
    "acum6_equivalente_m3_por_m",
    "acum12_petroleo_m3_por_m",
    "acum12_gas_mil_m3_por_m",
    "acum12_equivalente_m3_por_m",
    "acum24_petroleo_m3_por_m",
    "acum24_gas_mil_m3_por_m",
    "acum24_equivalente_m3_por_m",
    "gor6_m3_m3",
    "gor12_m3_m3",
    "corte_agua6",
    "corte_agua12",
    "ventana",
    "ventana_fuente",
    "outlier_ip90_m",
    "outlier_z_ip90_m",
    "flags",
    "linaje",
    "fecha_descarga",
    "version_maestro",
]

OUTLIER_COL = "ip90_equivalente_m3_d_por_m"


# --- published master -------------------------------------------------------------------------


def latest_published_dir(root: Path) -> Path:
    base = root / "data" / "publicado"
    days = (
        sorted(p for p in base.iterdir() if p.is_dir() and (p / "pozos.parquet").exists())
        if base.exists()
        else []
    )
    if not days:
        raise SystemExit("no master yet: run `python pipeline.py master`")
    return days[-1]


def load_master(root: Path) -> tuple[pd.DataFrame, str]:
    d = latest_published_dir(root)
    con = duckdb.connect(":memory:")
    m = con.execute(f"SELECT * FROM read_parquet('{(d / 'pozos.parquet').as_posix()}')").fetchdf()
    return m, d.name


# --- monthly production per physical well -------------------------------------------------------


def monthly_by_well(con: duckdb.DuckDBPyConnection, master: pd.DataFrame) -> pd.DataFrame:
    """Monthly production per physical well, every ``idpozo`` of the well summed.

    Columns: ``sigla_clave, anio, mes, mes_fecha, k, n_idpozo, petroleo_m3, gas_mil_m3, agua_m3,
    equivalente_m3, dias_mes, tef_informado, tef_d, tef_cero_con_produccion, tef_mayor_mes``.

    ``k`` is the calendar month index from the master's ``primera_produccion`` (0 = first month
    with oil or gas > 0; negative = records before it). ``tef_d`` is the effective producing days
    used downstream: the max ``tef`` among the well's idpozo in that month (one well has one
    calendar), capped at the days of the month (``tef_mayor_mes``); a month with production and
    ``tef = 0`` takes the whole month (``tef_cero_con_produccion``, a conservative rate).
    """
    ids = master[["sigla_clave", "idpozos", "primera_produccion"]].copy()
    ids["idpozo"] = ids.idpozos.astype(str).str.split(SEP)
    ids = ids.explode("idpozo")
    ids["idpozo"] = ids.idpozo.astype(int)
    prod = df(con, "SELECT idpozo, anio, mes, prod_pet, prod_gas, prod_agua, tef FROM produccion_nc")
    m = prod.merge(ids[["idpozo", "sigla_clave"]], on="idpozo", how="inner")
    g = m.groupby(["sigla_clave", "anio", "mes"], as_index=False).agg(
        petroleo_m3=("prod_pet", "sum"),
        gas_mil_m3=("prod_gas", "sum"),
        agua_m3=("prod_agua", "sum"),
        tef_informado=("tef", "max"),
        n_idpozo=("idpozo", "nunique"),
    )
    g["anio"] = g.anio.astype(int)
    g["mes"] = g.mes.astype(int)
    g["mes_fecha"] = pd.to_datetime({"year": g.anio, "month": g.mes, "day": 1})
    g["dias_mes"] = g.mes_fecha.dt.days_in_month.astype(float)
    first = pd.to_datetime(master.set_index("sigla_clave").primera_produccion)
    pf = g.sigla_clave.map(first)
    g["k"] = ((g.anio - pf.dt.year) * 12 + (g.mes - pf.dt.month)).astype("Int64")
    g["equivalente_m3"] = g.petroleo_m3 + g.gas_mil_m3.map(units.gas_thousand_m3_to_m3_oil_eq)
    produce = (g.petroleo_m3 > 0) | (g.gas_mil_m3 > 0)
    tef = pd.to_numeric(g.tef_informado, errors="coerce").fillna(0.0).clip(lower=0.0)
    g["tef_cero_con_produccion"] = (tef == 0) & produce
    g["tef_mayor_mes"] = tef > g.dias_mes
    g["tef_d"] = tef.where(~g.tef_cero_con_produccion, g.dias_mes).clip(upper=g.dias_mes)
    return g.sort_values(["sigla_clave", "mes_fecha"]).reset_index(drop=True)


# --- pure rules -------------------------------------------------------------------------------------


def ip_at(days: np.ndarray, volumes: np.ndarray, horizon: float) -> float | None:
    """Average daily rate over the first ``horizon`` producing days (ADR-016).

    ``days`` are the effective producing days of consecutive months from month 0, ``volumes``
    the volumes of those months. The cumulative-days axis is ``cumsum(days)``; the month in
    which it crosses ``horizon`` contributes ``volume * (remaining days / its days)``, i.e. it is
    prorated at its own daily rate. Returns None when the well has fewer producing days than
    ``horizon`` (the indicator is not computable, never extrapolated)."""
    days = np.asarray(days, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    if days.size == 0:
        return None
    cum = np.cumsum(days)
    if cum[-1] < horizon:
        return None
    i = int(np.searchsorted(cum, horizon, side="left"))
    before = cum[i - 1] if i > 0 else 0.0
    partial = volumes[i] * (horizon - before) / days[i] if days[i] > 0 else 0.0
    return float((volumes[:i].sum() + partial) / horizon)


def acum_months(
    k: np.ndarray, volumes: np.ndarray, n_months: int, meses_disponibles: int
) -> tuple[float | None, int]:
    """Cumulative volume over calendar months ``0 .. n_months-1`` since first production.

    Returns ``(value, missing_months)``. ``value`` is None when the data does not yet cover
    ``n_months`` (``meses_disponibles < n_months``). Months without a record inside the window
    count as zero and are returned as ``missing_months`` so the caller can flag them."""
    if meses_disponibles < n_months:
        return None, 0
    k = np.asarray(k)
    sel = (k >= 0) & (k < n_months)
    return float(np.asarray(volumes, dtype=float)[sel].sum()), int(n_months - sel.sum())


def months_between(first: date | pd.Timestamp, last: date | pd.Timestamp) -> int:
    """Calendar months from ``first`` to ``last`` inclusive (same month = 1)."""
    a, b = pd.Timestamp(first), pd.Timestamp(last)
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or pd.isna(num) or pd.isna(den) or den == 0:
        return None
    return float(num / den)


def ventana(gor_m3_m3: float | None) -> str | None:
    """Fluid window from a cumulative GOR in m³/m³ (ADR-020): ``petroleo`` below 180,
    ``volatil_condensado`` between 180 and 1,800, ``gas`` at or above 1,800; None without a GOR."""
    if gor_m3_m3 is None or pd.isna(gor_m3_m3):
        return None
    lo, hi = VENTANA_GOR_M3_M3
    if gor_m3_m3 < lo:
        return "petroleo"
    if gor_m3_m3 < hi:
        return "volatil_condensado"
    return "gas"


def rama_reason(rama_m, master_flags: str) -> tuple[bool, str | None]:
    """Whether ``rama_m`` can normalise per metre, and the flag that says why not (ADR-019)."""
    if rama_m is None or pd.isna(rama_m):
        fl = set((master_flags or "").split(SEP))
        if "sin_fractura" in fl:
            return False, "sin_rama_sin_fractura"
        if "rama_faltante" in fl:
            return False, "sin_rama_faltante"
        if "rama_cero" in fl:
            return False, "sin_rama_cero"
        return False, "sin_rama"
    if float(rama_m) < RAMA_MIN_M:
        return False, "rama_corta"
    return True, None


# --- build ----------------------------------------------------------------------------------------------


def build_indicadores(
    monthly: pd.DataFrame, master: pd.DataFrame, ultimo_mes, version_maestro: str
) -> pd.DataFrame:
    """One row per master well. ``monthly`` is ``monthly_by_well``'s output, ``ultimo_mes`` the
    last month present in the production file (sets ``meses_disponibles``)."""
    monthly = monthly[monthly.k.notna()]
    by_well = {s: g for s, g in monthly[monthly.k >= 0].groupby("sigla_clave", sort=False)}
    rows = []
    for w in master.itertuples(index=False):
        flags: list[str] = []
        lin: list[str] = []
        mflags = set((w.flags or "").split(SEP))
        en_alcance = w.cuenca == SCOPE_CUENCA and w.tipo_recurso == SCOPE_TIPO
        if not en_alcance:
            flags.append("fuera_alcance")
        rama_ok, why = rama_reason(w.rama_m, w.flags)
        if why:
            flags.append(why)
        rama = float(w.rama_m) if rama_ok else None
        etapas = int(w.etapas) if pd.notna(w.etapas) else None
        row: dict = {
            "sigla": w.sigla,
            "sigla_clave": w.sigla_clave,
            "idpozo_principal": w.idpozo_principal,
            "operadora": w.operadora,
            "formacion": w.formacion_principal,
            "area": w.area,
            "cuenca": w.cuenca,
            "tipo_recurso": w.tipo_recurso,
            "sub_tipo_recurso": w.sub_tipo_recurso,
            "en_alcance": bool(en_alcance),
            "cohorte": None,
            "primera_produccion": w.primera_produccion if pd.notna(w.primera_produccion) else None,
            "meses_disponibles": None,
            "meses_con_registro": 0,
            "dias_efectivos_total": None,
            "rama_m": float(w.rama_m) if pd.notna(w.rama_m) else None,
            "rama_normalizable": bool(rama_ok),
            "etapas": etapas,
            "etapas_por_100m": ratio(etapas, rama) * 100 if rama and etapas is not None else None,
            "arena_tn_por_m": ratio(w.arena_tn, rama) if rama else None,
            "agua_fractura_m3_por_m": ratio(w.agua_fractura_m3, rama) if rama else None,
            "outlier_ip90_m": None,
            "outlier_z_ip90_m": None,
        }
        for c in COLUMNS:
            row.setdefault(c, None)
        lin.append(
            f"maestro=data/publicado/{version_maestro}/pozos.parquet (formacion_principal, rama_m, etapas)"
        )
        lin.append(f"por_metro=rama_m del maestro si >= {RAMA_MIN_M:.0f} m")

        g = by_well.get(w.sigla_clave)
        if g is None or g.empty or pd.isna(w.primera_produccion):
            flags.append("nunca_produjo" if "nunca_produjo" in mflags else "sin_produccion")
            row["flags"] = SEP.join(dict.fromkeys(flags))
            row["linaje"] = "; ".join(lin)
            row["fecha_descarga"] = w.fecha_descarga
            row["version_maestro"] = version_maestro
            rows.append(row)
            continue

        first = pd.Timestamp(w.primera_produccion)
        disp = months_between(first, ultimo_mes)
        row["cohorte"] = int(first.year)
        row["meses_disponibles"] = disp
        row["meses_con_registro"] = int(len(g))
        row["dias_efectivos_total"] = float(g.tef_d.sum())
        if g.tef_cero_con_produccion.any():
            flags.append("tef_cero_con_produccion")
        if g.tef_mayor_mes.any():
            flags.append("tef_mayor_mes")
        if g.n_idpozo.max() > 1:
            flags.append("produccion_suma_idpozo")
        if ((g.petroleo_m3 < 0) | (g.gas_mil_m3 < 0) | (g.agua_m3 < 0)).any():
            flags.append("volumen_negativo")
        if float(g.tef_d.iloc[0]) < MES_PARCIAL_DIAS:
            flags.append("primer_mes_parcial")
        lin.append(
            f"produccion=produccion_nc suma de {int(g.n_idpozo.max())} idpozo por mes; dias=tef max entre idpozo, tope dias del mes"
        )
        lin.append(
            "ip=volumen de los primeros N dias efectivos / N, mes de corte prorrateado a su tasa diaria"
        )
        lin.append("acum=meses calendario 0..N-1 desde primera_produccion; cohorte=anio(primera_produccion)")

        days = g.tef_d.to_numpy(dtype=float)
        kk = g.k.to_numpy(dtype=int)
        for horizon in IP_DIAS:
            vals = {f: ip_at(days, g[f].to_numpy(dtype=float), horizon) for f in FLUIDOS}
            if vals["petroleo_m3"] is None:
                flags.append(f"ip{horizon}_dias_insuficientes")
            for f, suffix in (
                ("petroleo_m3", "petroleo_m3_d"),
                ("gas_mil_m3", "gas_mil_m3_d"),
                ("equivalente_m3", "equivalente_m3_d"),
            ):
                row[f"ip{horizon}_{suffix}"] = vals[f]
                row[f"ip{horizon}_{suffix}_por_m"] = ratio(vals[f], rama) if rama else None

        for n in ACUM_MESES:
            vals = {}
            missing = 0
            for f in ("petroleo_m3", "gas_mil_m3", "agua_m3", "equivalente_m3"):
                vals[f], missing = acum_months(kk, g[f].to_numpy(dtype=float), n, disp)
            if vals["petroleo_m3"] is None:
                flags.append(f"acum{n}_historia_corta")
            elif missing:
                flags.append(f"acum{n}_meses_faltantes")
            for f in vals:
                row[f"acum{n}_{f}"] = vals[f]
                if f != "agua_m3":
                    row[f"acum{n}_{f}_por_m"] = ratio(vals[f], rama) if rama else None

        for n in GOR_MESES:
            oil, gas, water = row[f"acum{n}_petroleo_m3"], row[f"acum{n}_gas_mil_m3"], row[f"acum{n}_agua_m3"]
            if oil is not None:
                if oil > 0:
                    row[f"gor{n}_m3_m3"] = units.gas_thousand_m3_to_m3_gas(gas) / oil
                else:
                    flags.append(f"gor{n}_sin_petroleo")
                if (oil + water) > 0:
                    row[f"corte_agua{n}"] = water / (oil + water)
                else:
                    flags.append(f"corte_agua{n}_sin_liquido")

        # fluid window: GOR at 12 months, else at 6, else over the whole history (provisional)
        gor_ref, src = None, None
        for n in (12, 6):
            if row[f"acum{n}_petroleo_m3"] is not None:
                oil, gas = row[f"acum{n}_petroleo_m3"], row[f"acum{n}_gas_mil_m3"]
                gor_ref, src = (
                    (
                        units.gas_thousand_m3_to_m3_gas(gas) / oil
                        if oil > 0
                        else (np.inf if gas > 0 else None)
                    ),
                    f"gor{n}",
                )
                break
        if src is None:
            oil, gas = float(g.petroleo_m3.sum()), float(g.gas_mil_m3.sum())
            gor_ref, src = (
                (units.gas_thousand_m3_to_m3_gas(gas) / oil if oil > 0 else (np.inf if gas > 0 else None)),
                "gor_total",
            )
        row["ventana"] = ventana(gor_ref)
        row["ventana_fuente"] = src if row["ventana"] else None
        if row["ventana"] and src != "gor12":
            flags.append("ventana_provisoria")
        lin.append(
            f"ventana=GOR acumulado ({src}) contra {VENTANA_GOR_M3_M3[0]:.0f} y {VENTANA_GOR_M3_M3[1]:.0f} m3/m3"
        )

        row["flags"] = SEP.join(dict.fromkeys(flags))
        row["linaje"] = "; ".join(lin)
        row["fecha_descarga"] = w.fecha_descarga
        row["version_maestro"] = version_maestro
        rows.append(row)

    out = pd.DataFrame(rows, columns=COLUMNS)
    out["primera_produccion"] = pd.to_datetime(out.primera_produccion, errors="coerce")
    for c in ("cohorte", "meses_disponibles", "etapas", "idpozo_principal"):
        out[c] = out[c].astype("Int64")
    out["outlier_ip90_m"] = out.outlier_ip90_m.astype("boolean")
    return mark_outliers(out)


# --- outliers ---------------------------------------------------------------------------------------------


def robust_z(values: pd.Series) -> pd.Series | None:
    """Robust z-score: (x - median) / (1.4826 * MAD) on log10(x). None when MAD is 0."""
    x = np.log10(values.astype(float))
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return None
    return (x - med) / (1.4826 * mad)


def mark_outliers(ind: pd.DataFrame, col: str = OUTLIER_COL, by: str = "formacion") -> pd.DataFrame:
    """ADR-018: within each formation (in-scope wells with a positive ``col``), a well whose
    robust z on log10(col) exceeds ``OUTLIER_Z`` in absolute value is marked ``outlier_ip90_m``
    (True/False); wells that could not be screened keep null + ``outlier_no_evaluado``.
    Nothing is removed: ``vma/curvas.py`` publishes the curves with and without them."""
    ind = ind.copy()
    z = pd.Series(np.nan, index=ind.index, dtype=float)
    verdict = pd.Series(pd.NA, index=ind.index, dtype="boolean")
    evaluable = ind.en_alcance & ind[col].notna() & (ind[col] > 0) & ind[by].notna()
    for _, idx in ind[evaluable].groupby(by).groups.items():
        if len(idx) < OUTLIER_N_MIN:
            continue
        zz = robust_z(ind.loc[idx, col])
        if zz is None:
            continue
        z.loc[idx] = zz
        verdict.loc[idx] = zz.abs() > OUTLIER_Z
    ind["outlier_z_ip90_m"] = z.round(3).where(z.notna(), None)
    ind["outlier_ip90_m"] = verdict

    def add(flags: str, extra: str) -> str:
        parts = [f for f in (flags or "").split(SEP) if f]
        if extra not in parts:
            parts.append(extra)
        return SEP.join(parts)

    hi = verdict.fillna(False) & (z > 0)
    lo = verdict.fillna(False) & (z < 0)
    ne = verdict.isna()
    ind.loc[hi, "flags"] = ind.loc[hi, "flags"].map(lambda f: add(f, "outlier_ip90_m_alto"))
    ind.loc[lo, "flags"] = ind.loc[lo, "flags"].map(lambda f: add(f, "outlier_ip90_m_bajo"))
    ind.loc[ne, "flags"] = ind.loc[ne, "flags"].map(lambda f: add(f, "outlier_no_evaluado"))
    ind["linaje"] = ind.linaje + (
        f"; outlier=|z robusto| > {OUTLIER_Z} sobre log10({col}) por {by}, n >= {OUTLIER_N_MIN}"
    )
    return ind


# --- publish / run ---------------------------------------------------------------------------------------------


def publish(root: Path, table: pd.DataFrame, day: date, name: str) -> tuple[Path, Path]:
    out_dir = root / "data" / "publicado" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{name}.csv"
    pq_path = out_dir / f"{name}.parquet"
    table.to_csv(csv_path, index=False, encoding="utf-8", date_format="%Y-%m-%d")
    con = duckdb.connect(":memory:")
    con.register("t", table)
    con.execute(f"COPY t TO '{pq_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    return csv_path, pq_path


def build_all(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """Load the latest master and raw production and return ``(master, monthly, indicadores, version)``."""
    con, _ = connect_raw(root)
    master, version = load_master(root)
    monthly = monthly_by_well(con, master)
    ultimo = monthly.mes_fecha.max()
    ind = build_indicadores(monthly, master, ultimo, version)
    return master, monthly, ind, version


def run(root: Path, today: date | None = None) -> tuple[Path, Path]:
    today = today or date.today()
    latest_raw_dir(root)  # fail early with the same message as the other stages
    _, _, ind, _ = build_all(root)
    paths = publish(root, ind, today, "indicadores")
    n_scope = int(ind.en_alcance.sum())
    n_ip90 = int(ind.ip90_petroleo_m3_d.notna().sum())
    n_pm = int(ind[OUTLIER_COL].notna().sum())
    n_out = int(ind.outlier_ip90_m.fillna(False).sum())
    print(
        f"{len(ind):,} wells ({n_scope:,} in scope) -> {paths[0]}  {paths[1]}\n"
        f"IP90: {n_ip90:,} wells · IP90 per metre: {n_pm:,} · outliers marked: {n_out:,}"
    )
    return paths


if __name__ == "__main__":  # pragma: no cover
    run(Path(__file__).resolve().parents[1])
