"""Indicators and type curves on tiny in-memory frames and on the master fixture. No network, no data."""

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from vma import curvas as C
from vma import indicadores as I
from vma import master as M
from vma.alias import load_aliases

ROOT = Path(__file__).resolve().parents[1]
TABLES = ["pozos", "produccion_nc", "fractura", "padron_pozos", "listado_pozos_operadoras"]


# --- pure rules -------------------------------------------------------------------------------------


def test_ip_prorates_the_crossing_month():
    # month 1: 10 days at 10/d, month 2: 31 days at 20/d -> first 30 days = 100 + 20 days * 20/d = 500
    assert I.ip_at([10, 31], [100, 620], 30) == pytest.approx(500 / 30)
    # exactly on a month boundary: no proration
    assert I.ip_at([10, 20, 31], [100, 400, 620], 30) == pytest.approx(500 / 30)
    # a month with 0 producing days and 0 volume is skipped by the cumulative axis
    assert I.ip_at([10, 0, 31], [100, 0, 620], 30) == pytest.approx(500 / 30)


def test_ip_is_null_when_producing_days_are_short():
    assert I.ip_at([10, 15], [100, 150], 30) is None  # 25 days < 30: never extrapolated
    assert I.ip_at([], [], 30) is None
    assert I.ip_at([30], [300], 30) == pytest.approx(10.0)


def test_acum_with_gaps_counts_zero_and_reports_missing_months():
    k = np.array([0, 1, 3, 4, 5])  # month 2 missing
    v = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
    assert I.acum_months(k, v, 6, meses_disponibles=6) == (50.0, 1)
    assert I.acum_months(k, v, 6, meses_disponibles=5) == (None, 0)  # window not yet covered by the source
    assert I.acum_months(k, v, 3, meses_disponibles=12) == (20.0, 1)


def test_months_between_and_ratio():
    assert I.months_between(date(2024, 1, 1), date(2024, 1, 1)) == 1
    assert I.months_between(date(2024, 1, 1), date(2024, 12, 1)) == 12
    assert I.ratio(10, 0) is None and I.ratio(None, 2) is None and I.ratio(10, 4) == 2.5


def test_rama_reason_and_window():
    assert I.rama_reason(None, "sin_fractura") == (False, "sin_rama_sin_fractura")
    assert I.rama_reason(None, "rama_cero|rama_faltante") == (False, "sin_rama_faltante")
    assert I.rama_reason(None, "rama_cero") == (False, "sin_rama_cero")
    assert I.rama_reason(None, "") == (False, "sin_rama")
    assert I.rama_reason(300.0, "") == (False, "rama_corta")
    assert I.rama_reason(2500.0, "") == (True, None)
    assert I.ventana(50) == "petroleo" and I.ventana(500) == "volatil_condensado" and I.ventana(5000) == "gas"
    assert I.ventana(None) is None and I.ventana(np.inf) == "gas"


# --- build on synthetic monthly rows -------------------------------------------------------------------------


def _master_row(sigla, rama, flags="", etapas=30, **kw):
    r = {
        "sigla": sigla,
        "sigla_clave": sigla.upper(),
        "idpozos": kw.get("idpozos", "1"),
        "idpozo_principal": 1,
        "operadora": kw.get("operadora", "OP A"),
        "formacion_principal": kw.get("formacion", "Vaca Muerta"),
        "area": "AREA",
        "cuenca": kw.get("cuenca", "NEUQUINA"),
        "tipo_recurso": kw.get("tipo_recurso", "NO CONVENCIONAL"),
        "sub_tipo_recurso": "SHALE",
        "primera_produccion": pd.Timestamp(kw.get("first", "2024-01-01"))
        if kw.get("first", "2024-01-01")
        else pd.NaT,
        "rama_m": rama,
        "etapas": etapas,
        "arena_tn": 3000.0,
        "agua_fractura_m3": 40000.0,
        "flags": flags,
        "fecha_descarga": "2026-10-30",
    }
    return r


def _monthly(sigla, start, months):
    """months = list of (petroleo, gas, agua, tef)."""
    rows = []
    y, m = start
    for k, (p, g, a, t) in enumerate(months):
        yy, mm = y + (m - 1 + k) // 12, (m - 1 + k) % 12 + 1
        rows.append(
            {
                "sigla_clave": sigla.upper(),
                "anio": yy,
                "mes": mm,
                "petroleo_m3": p,
                "gas_mil_m3": g,
                "agua_m3": a,
                "tef_informado": t,
                "n_idpozo": 1,
            }
        )
    return rows


def _prepare(rows):
    g = pd.DataFrame(rows)
    g["mes_fecha"] = pd.to_datetime({"year": g.anio, "month": g.mes, "day": 1})
    g["dias_mes"] = g.mes_fecha.dt.days_in_month.astype(float)
    g["equivalente_m3"] = g.petroleo_m3 + g.gas_mil_m3
    produce = (g.petroleo_m3 > 0) | (g.gas_mil_m3 > 0)
    tef = g.tef_informado.astype(float)
    g["tef_cero_con_produccion"] = (tef == 0) & produce
    g["tef_mayor_mes"] = tef > g.dias_mes
    g["tef_d"] = tef.where(~g.tef_cero_con_produccion, g.dias_mes).clip(upper=g.dias_mes)
    return g


@pytest.fixture(scope="module")
def synthetic():
    master = pd.DataFrame(
        [
            _master_row("W.A-1", 2000.0, first="2024-03-01"),  # full well: 13 months, partial first month
            _master_row("W.B-2", None, flags="rama_cero|rama_faltante"),  # per metre impossible
            _master_row("W.C-3", 2000.0, first="2025-08-01"),  # short history: 2 months
            _master_row("W.D-4", 2000.0, cuenca="AUSTRAL"),  # out of scope
            _master_row("W.E-5", 2000.0, first=None, flags="sin_produccion"),  # no production
        ]
    )
    rows = []
    # A: first month 10 days at 10/d, then 28-day months at 20/d; month 2 (k=2) missing; gas 1 per oil 10
    rows += _monthly("W.A-1", (2024, 3), [(100, 10, 50, 10), (560, 56, 100, 28)])
    rows += _monthly("W.A-1", (2024, 6), [(560, 56, 100, 28)] * 11)
    rows += _monthly("W.B-2", (2024, 1), [(300, 30, 0, 28)] * 14)
    rows += _monthly("W.C-3", (2025, 8), [(300, 30, 0, 28), (300, 30, 0, 28)])
    rows += _monthly("W.D-4", (2024, 1), [(300, 30, 0, 28)] * 14)
    monthly = _prepare(rows)
    first = master.set_index("sigla_clave").primera_produccion
    pf = monthly.sigla_clave.map(first)
    monthly["k"] = ((monthly.anio - pf.dt.year) * 12 + (monthly.mes - pf.dt.month)).astype("Int64")
    ind = I.build_indicadores(monthly, master, pd.Timestamp("2025-09-01"), "2026-10-31")
    return master, monthly, ind


def _row(ind, sigla):
    r = ind[ind.sigla_clave == sigla.upper()]
    assert len(r) == 1
    return r.iloc[0]


def test_ip_with_incomplete_first_month(synthetic):
    _, _, ind = synthetic
    a = _row(ind, "W.A-1")
    assert a.ip30_petroleo_m3_d == pytest.approx(500 / 30)  # 10 days + 20 days of the next month
    assert a.ip90_petroleo_m3_d == pytest.approx((100 + 560 + 560 + 560 * 24 / 28) / 90)
    assert "primer_mes_parcial" in a["flags"] and "ip30_dias_insuficientes" not in a["flags"]
    assert a.ip30_petroleo_m3_d_por_m == pytest.approx(a.ip30_petroleo_m3_d / 2000)
    assert a.cohorte == 2024 and a.meses_disponibles == 19 and a.en_alcance
    assert "tef_mayor_mes" not in a["flags"] and "tef_cero_con_produccion" not in a["flags"]


def test_acum_with_gap_is_flagged_not_dropped(synthetic):
    _, _, ind = synthetic
    a = _row(ind, "W.A-1")
    assert a.acum6_petroleo_m3 == pytest.approx(100 + 560 + 560 * 3)  # k=2 missing -> 0
    assert "acum6_meses_faltantes" in a["flags"] and "acum12_meses_faltantes" in a["flags"]
    assert a.acum12_petroleo_m3 == pytest.approx(100 + 560 + 560 * 9)
    assert pd.isna(a.acum24_petroleo_m3) and "acum24_historia_corta" in a["flags"]
    assert a.gor12_m3_m3 == pytest.approx(1000 * a.acum12_gas_mil_m3 / a.acum12_petroleo_m3)
    assert a.corte_agua6 == pytest.approx((50 + 100 + 100 * 3) / (50 + 100 + 100 * 3 + a.acum6_petroleo_m3))
    assert a.ventana == "petroleo" and a.ventana_fuente == "gor12" and "ventana_provisoria" not in a["flags"]


def test_per_metre_null_with_reason_when_lateral_missing(synthetic):
    _, _, ind = synthetic
    b = _row(ind, "W.B-2")
    assert b.ip90_petroleo_m3_d == pytest.approx(300 / 28)  # raw indicator still computed
    assert (
        pd.isna(b.ip90_petroleo_m3_d_por_m)
        and pd.isna(b.acum12_petroleo_m3_por_m)
        and pd.isna(b.etapas_por_100m)
    )
    assert not b.rama_normalizable and "sin_rama_faltante" in b["flags"]


def test_short_history_and_out_of_scope_and_no_production(synthetic):
    _, _, ind = synthetic
    c = _row(ind, "W.C-3")
    assert (
        c.ip30_petroleo_m3_d is not None
        and pd.isna(c.ip90_petroleo_m3_d)
        and "ip90_dias_insuficientes" in c["flags"]
    )
    assert pd.isna(c.acum6_petroleo_m3) and "acum6_historia_corta" in c["flags"]
    assert c.ventana == "petroleo" and c.ventana_fuente == "gor_total" and "ventana_provisoria" in c["flags"]
    d = _row(ind, "W.D-4")
    assert (
        not d.en_alcance and "fuera_alcance" in d["flags"] and d.ip90_petroleo_m3_d == pytest.approx(300 / 28)
    )
    assert pd.isna(d.outlier_ip90_m) and "outlier_no_evaluado" in d["flags"]
    e = _row(ind, "W.E-5")
    assert "sin_produccion" in e["flags"] and pd.isna(e.cohorte) and pd.isna(e.ip30_petroleo_m3_d)
    assert len(ind) == 5 and list(ind.columns) == I.COLUMNS


# --- outliers -----------------------------------------------------------------------------------------------


def _ind_for_outliers(n=30, extreme=1e-6):
    rng = np.random.default_rng(0)
    vals = list(10 ** rng.normal(-1.2, 0.1, n - 1)) + [extreme]
    ind = pd.DataFrame(
        {
            "sigla_clave": [f"W-{i}" for i in range(n)],
            "en_alcance": True,
            "formacion": "Vaca Muerta",
            I.OUTLIER_COL: vals,
            "flags": "",
            "linaje": "x",
        }
    )
    ind["outlier_ip90_m"] = pd.Series([pd.NA] * n, dtype="boolean")
    ind["outlier_z_ip90_m"] = None
    return ind


def test_outlier_is_marked_and_kept():
    out = I.mark_outliers(_ind_for_outliers())
    assert len(out) == 30  # nothing removed
    marked = out[out.outlier_ip90_m.fillna(False).astype(bool)]
    assert list(marked.sigla_clave) == ["W-29"] and "outlier_ip90_m_bajo" in marked["flags"].iloc[0]
    assert marked.outlier_z_ip90_m.iloc[0] < -I.OUTLIER_Z
    assert out.outlier_ip90_m.notna().all() and "outlier_no_evaluado" not in "|".join(out["flags"])
    assert "outlier=" in out.linaje.iloc[0]


def test_outliers_not_evaluated_below_group_minimum():
    out = I.mark_outliers(_ind_for_outliers(n=I.OUTLIER_N_MIN - 1))
    assert out.outlier_ip90_m.isna().all() and all("outlier_no_evaluado" in f for f in out["flags"])


# --- type curves ---------------------------------------------------------------------------------------------


def _curve_inputs(n_wells, n_months=3, outlier_well=None):
    master_rows, rows = [], []
    for i in range(n_wells):
        s = f"T.W-{i}"
        master_rows.append(_master_row(s, 2000.0))
        rows += _monthly(s, (2024, 1), [(100 * (i + 1), 10, 0, 28)] * n_months)
    master = pd.DataFrame(master_rows)
    monthly = _prepare(rows)
    first = master.set_index("sigla_clave").primera_produccion
    pf = monthly.sigla_clave.map(first)
    monthly["k"] = ((monthly.anio - pf.dt.year) * 12 + (monthly.mes - pf.dt.month)).astype("Int64")
    ind = I.build_indicadores(monthly, master, pd.Timestamp("2025-09-01"), "2026-10-31")
    if outlier_well is not None:
        ind.loc[ind.sigla_clave == outlier_well.upper(), "outlier_ip90_m"] = True
    return monthly, ind


def test_curves_below_minimum_wells_keep_n_but_no_percentiles():
    monthly, ind = _curve_inputs(4)
    cv = C.build_curvas(monthly, ind, "2026-10-31")
    fm = cv[(cv.nivel == "cohorte_formacion") & cv.incluye_outliers]
    assert (fm.n_pozos == 4).all() and (~fm.publicable).all()
    assert fm.petroleo_m3_d_p50.isna().all() and fm.petroleo_m3_d_por_m_media.isna().all()
    assert list(cv.columns) == C.COLUMNS


def test_curves_percentile_convention_and_outlier_exclusion():
    monthly, ind = _curve_inputs(6, outlier_well="T.W-5")
    cv = C.build_curvas(monthly, ind, "2026-10-31")
    fm = cv[(cv.nivel == "cohorte_formacion") & (cv.mes == 0)].set_index("incluye_outliers")
    with_ = fm.loc[True]
    assert with_.n_pozos == 6 and with_.publicable
    rates = np.array([100, 200, 300, 400, 500, 600]) / 28.0
    assert with_.petroleo_m3_d_p50 == pytest.approx(np.median(rates))
    assert with_.petroleo_m3_d_p10 == pytest.approx(np.quantile(rates, 0.9))  # P10 = high case
    assert with_.petroleo_m3_d_p90 == pytest.approx(np.quantile(rates, 0.1))
    assert with_.petroleo_m3_d_por_m_media == pytest.approx(rates.mean() / 2000)
    without = fm.loc[False]
    assert without.n_pozos == 5 and without.petroleo_m3_d_p50 == pytest.approx(np.median(rates[:5]))
    assert set(cv.nivel.unique()) == set(C.NIVELES)
    op = cv[(cv.nivel == "cohorte_formacion_operadora") & cv.incluye_outliers & (cv.mes == 0)]
    assert len(op) == 1 and op.operadora.iloc[0] == "OP A" and op.ventana.isna().all()
    win = cv[(cv.nivel == "cohorte_formacion_ventana") & cv.incluye_outliers & (cv.mes == 0)]
    assert list(win.ventana) == ["petroleo"] and win.n_pozos.iloc[0] == 6


# --- from the master fixture through DuckDB -------------------------------------------------------------------


def test_monthly_by_well_from_fixture_sums_idpozo_and_caps_days(fixtures_dir):
    con = duckdb.connect(":memory:")
    for t in TABLES:
        p = fixtures_dir / "maestro" / f"{t}.csv"
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv('{p.as_posix()}', header=true)")
    master = M.build_master(con, load_aliases(ROOT / "alias"), "2026-10-30")
    monthly = I.monthly_by_well(con, master)
    a = monthly[monthly.sigla_clave == "OP.NQ.AA-1(H)"].sort_values("mes_fecha")
    assert a.k.tolist() == [0, 1, 2] and a.petroleo_m3.tolist() == [100.5, 200.0, 10.0]
    assert (monthly.tef_d <= monthly.dias_mes).all()
    ind = I.build_indicadores(monthly, master, monthly.mes_fecha.max(), "test")
    assert len(ind) == len(master) and ind.sigla_clave.is_unique
    cv = C.build_curvas(monthly, ind, "test")
    assert (cv.n_pozos >= 1).all()


def test_publish_round_trip(tmp_path):
    monthly, ind = _curve_inputs(2)
    csv_path, pq_path = I.publish(tmp_path, ind, date(2026, 10, 31), "indicadores")
    assert csv_path.name == "indicadores.csv" and pq_path.exists()
    back = duckdb.connect().execute(f"SELECT * FROM read_parquet('{pq_path.as_posix()}')").fetchdf()
    assert list(back.columns) == I.COLUMNS and len(back) == 2
    assert pd.read_csv(csv_path).primera_produccion.iloc[0] == "2024-01-01"


# --- documentation ------------------------------------------------------------------------------------------------


def test_every_column_and_flag_is_documented(synthetic):
    doc = (ROOT / "docs" / "indicadores.md").read_text(encoding="utf-8")
    for c in I.COLUMNS:
        assert f"`{c}`" in doc or _generic(c) in doc, c
    for c in C.COLUMNS:
        assert f"`{c}`" in doc, c
    _, _, ind = synthetic
    flags = set(ind["flags"].str.split("|").explode().dropna().unique()) - {""}
    flags |= {
        "outlier_ip90_m_alto",
        "outlier_ip90_m_bajo",
        "tef_cero_con_produccion",
        "tef_mayor_mes",
        "volumen_negativo",
        "produccion_suma_idpozo",
    }
    for flag in flags:
        assert f"`{flag}`" in doc, flag


def _generic(c: str) -> str:
    """ip30_petroleo_m3_d_por_m -> `ip{N}_*_por_m`; acum6_gas_mil_m3 -> `acum{N}_gas_mil_m3`; gor6 -> `gor6_m3_m3`."""
    for pre in ("ip30", "ip90", "ip180"):
        if c.startswith(pre + "_"):
            rest = c[len(pre) + 1 :]
            return "`ip{N}_*_por_m`" if rest.endswith("_por_m") else f"`ip{{N}}_{rest}`"
    for pre in ("acum6", "acum12", "acum24"):
        if c.startswith(pre + "_"):
            rest = c[len(pre) + 1 :]
            return "`acum{N}_*_por_m`" if rest.endswith("_por_m") else f"`acum{{N}}_{rest}`"
    return f"`{c}`"
