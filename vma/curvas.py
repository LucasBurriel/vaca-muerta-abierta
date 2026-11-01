"""Phase 2b: type curves by cohort.

A type curve here is the distribution, month by month since first production, of the
**producing-day rate** of the wells of a group: P10 / P50 / P90 and mean of ``volume / tef``
for oil, gas and oil equivalent, and the same per metre of lateral for the wells whose
``rama_m`` can normalise (ADR-019). Groups are *cohort × formation* and *cohort × formation ×
operator* over the in-scope wells (ADR-015, ADR-002); ``mes`` is the calendar month index from
the master's ``primera_produccion`` (0 = first month with oil or gas > 0).

Percentiles follow the petroleum convention (ADR-017): ``p10`` is the value exceeded by 10 % of
the wells (the optimistic case), ``p90`` the value exceeded by 90 %. A month with fewer than
``MIN_POZOS`` wells keeps its ``n_pozos`` but publishes no percentiles or mean. Every group is
published twice: ``incluye_outliers = True`` with every well, ``False`` without the wells marked
``outlier_ip90_m`` in the indicators table (ADR-018) — nothing is deleted, the exclusion is a
column.

Published as ``data/publicado/<date>/curvas_tipo.csv`` and ``curvas_tipo.parquet``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .indicadores import SEP, build_all, publish

MIN_POZOS = 5  # ADR-017
P10_Q, P50_Q, P90_Q = 0.9, 0.5, 0.1  # petroleum convention: P10 is the high case
RATES = ["petroleo_m3_d", "gas_mil_m3_d", "equivalente_m3_d"]
RATES_M = [f"{r}_por_m" for r in RATES]
STATS = ["p10", "p50", "p90", "media"]
NIVELES = {
    "cohorte_formacion": ["cohorte", "formacion"],
    "cohorte_formacion_ventana": ["cohorte", "formacion", "ventana"],
    "cohorte_formacion_operadora": ["cohorte", "formacion", "operadora"],
}

COLUMNS = (
    [
        "nivel",
        "cohorte",
        "formacion",
        "ventana",
        "operadora",
        "incluye_outliers",
        "mes",
        "n_pozos",
        "n_pozos_por_m",
        "publicable",
    ]
    + [f"{r}_{s}" for r in RATES + RATES_M for s in STATS]
    + ["fecha_descarga", "version_maestro"]
)


def monthly_rates(monthly: pd.DataFrame, ind: pd.DataFrame) -> pd.DataFrame:
    """Per well-month producing-day rates for the in-scope wells, from month 0 on.
    Months with ``tef_d = 0`` (no producing days, nothing produced) are not a rate and are dropped,
    so a well is simply absent from that month's ``n_pozos``."""
    keys = [
        "sigla_clave",
        "en_alcance",
        "cohorte",
        "formacion",
        "ventana",
        "operadora",
        "rama_m",
        "rama_normalizable",
        "outlier_ip90_m",
    ]
    m = monthly[(monthly.k.notna()) & (monthly.k >= 0) & (monthly.tef_d > 0)].merge(
        ind[keys], on="sigla_clave", how="inner"
    )
    m = m[m.en_alcance & m.cohorte.notna() & m.formacion.notna()].copy()
    m["mes"] = m.k.astype(int)
    m["petroleo_m3_d"] = m.petroleo_m3 / m.tef_d
    m["gas_mil_m3_d"] = m.gas_mil_m3 / m.tef_d
    m["equivalente_m3_d"] = m.equivalente_m3 / m.tef_d
    rama = m.rama_m.where(m.rama_normalizable)
    for r in RATES:
        m[f"{r}_por_m"] = m[r] / rama
    return m


def _aggregate(sub: pd.DataFrame, keys: list[str], min_pozos: int) -> pd.DataFrame:
    grp = sub.groupby([*keys, "mes"], dropna=False, sort=True)
    out = grp.agg(n_pozos=("sigla_clave", "nunique")).reset_index()
    out["n_pozos_por_m"] = grp[RATES_M[0]].count().to_numpy()
    for q, s in ((P10_Q, "p10"), (P50_Q, "p50"), (P90_Q, "p90")):
        qq = grp[RATES + RATES_M].quantile(q).reset_index(drop=True)
        for r in RATES + RATES_M:
            out[f"{r}_{s}"] = qq[r].to_numpy()
    mean = grp[RATES + RATES_M].mean().reset_index(drop=True)
    for r in RATES + RATES_M:
        out[f"{r}_media"] = mean[r].to_numpy()
    out["publicable"] = out.n_pozos >= min_pozos
    low = out.n_pozos < min_pozos
    low_m = out.n_pozos_por_m < min_pozos
    for r in RATES:
        for s in STATS:
            out.loc[low, f"{r}_{s}"] = None
            out.loc[low_m, f"{r}_por_m_{s}"] = None
    return out


def build_curvas(
    monthly: pd.DataFrame, ind: pd.DataFrame, version_maestro: str, min_pozos: int = MIN_POZOS
) -> pd.DataFrame:
    rates = monthly_rates(monthly, ind)
    parts = []
    for incluye in (True, False):
        sub = rates if incluye else rates[~rates.outlier_ip90_m.fillna(False).astype(bool)]
        for nivel, keys in NIVELES.items():
            a = _aggregate(sub, keys, min_pozos)
            a["nivel"] = nivel
            a["incluye_outliers"] = incluye
            for k in ("operadora", "ventana"):
                if k not in keys:
                    a[k] = None
            if "ventana" in keys:
                a = a[a.ventana.notna()]  # wells without a window are in the formation-level curve only
            parts.append(a)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
    out["fecha_descarga"] = ind.fecha_descarga.iloc[0] if len(ind) else None
    out["version_maestro"] = version_maestro
    out = out.reindex(columns=COLUMNS)
    out["cohorte"] = out.cohorte.astype("Int64")
    out["mes"] = out.mes.astype("Int64")
    return out.sort_values(
        ["nivel", "incluye_outliers", "cohorte", "formacion", "ventana", "operadora", "mes"],
        na_position="first",
    ).reset_index(drop=True)


def run(root: Path, today: date | None = None) -> tuple[Path, Path]:
    from .informe_indicadores import build_report

    today = today or date.today()
    master, monthly, ind, version = build_all(root)
    curvas = build_curvas(monthly, ind, version)
    paths = publish(root, curvas, today, "curvas_tipo")
    groups = (
        curvas[curvas.incluye_outliers]
        .groupby("nivel")[["cohorte", "formacion", "ventana", "operadora"]]
        .apply(lambda d: len(d.drop_duplicates()))
    )
    print(f"{len(curvas):,} rows -> {paths[0]}  {paths[1]}")
    for nivel, n in groups.items():
        print(f"  {nivel}: {n:,} groups")
    report = build_report(root, ind, curvas, monthly, today, version)
    print(f"report: {report}")
    return paths


__all__ = ["COLUMNS", "MIN_POZOS", "SEP", "build_curvas", "monthly_rates", "run"]
