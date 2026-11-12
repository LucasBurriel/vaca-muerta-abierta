"""``site/data/simulador.json`` (ADR-036): what the browser Monte Carlo samples.

Schema, the quantile order P10 >= P50 >= P90, the continuity of the extension at the splice, the size cap, the
default prices, and that the file carries exactly what the Python simulator's own extension gives.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import test_site as TS

from vma import curvas as C
from vma import site as S
from vma import units
from vma.simulacion import campania as SC
from vma.simulacion import declinacion as DC

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "site" / "data" / "simulador.json"
CLAVES_CURVA = {
    "p10",
    "p50",
    "p90",
    "publicados",
    "ultimo_mes",
    "validos",
    "acotados",
    "descartados",
    "n_ultimo",
}


def _hiperbolica(mes, qi, b, d):
    return qi * np.power(1.0 + b * d * (mes + 0.5), -1.0 / b)


def _curvas(
    meses: int = 40, grupos=((2022, "Vaca Muerta", "petroleo"),), cruzar: bool = False
) -> pd.DataFrame:
    """A curvas_tipo table with one publishable group per key: oil, gas and their per-metre versions.
    ``cruzar`` flattens the P90 in its last published months, so its fitted tail crosses the P50's when extended."""
    filas = []
    mes = np.arange(meses)
    p50 = _hiperbolica(mes, 120.0, 1.1, 0.25)
    p10 = 1.7 * p50
    p90 = 0.45 * p50
    if (
        cruzar
    ):  # below the P50 in every published month, but almost flat from month 12 on while the P50 keeps falling
        p90 = np.maximum(0.3 * p50, 10.5 * np.exp(-0.002 * mes))
    for cohorte, formacion, ventana in grupos:
        for inc in (True, False):
            for i in range(meses):
                fila = {
                    "nivel": S.SIM_NIVEL,
                    "cohorte": cohorte,
                    "formacion": formacion,
                    "ventana": ventana,
                    "operadora": None,
                    "incluye_outliers": inc,
                    "mes": i,
                    "n_pozos": 40 - i // 2,
                    "n_pozos_por_m": 30 - i // 2,
                    "publicable": True,
                }
                for col, k in (
                    ("petroleo_m3_d", 1.0),
                    ("gas_mil_m3_d", 0.2),
                    ("petroleo_m3_d_por_m", 1 / 2500),
                    ("gas_mil_m3_d_por_m", 0.2 / 2500),
                ):
                    fila[f"{col}_p10"], fila[f"{col}_p50"], fila[f"{col}_p90"] = (
                        k * p10[i],
                        k * p50[i],
                        k * p90[i],
                    )
                filas.append(fila)
    c = pd.DataFrame(filas)
    for col in C.COLUMNS:
        if col not in c:
            c[col] = None
    return c[C.COLUMNS]


def _verificar(D: dict) -> dict:
    """The invariants every simulador.json must hold; returns a few counts for the caller's own asserts."""
    assert D["tabla"] == "curvas_tipo" and D["nivel"] == S.SIM_NIVEL and D["incluye_outliers"] is False
    assert (
        D["meses"] == S.SIM_MESES
        and D["tasas"] == S.SIM_CURVAS
        and D["estadisticos"] == ["p10", "p50", "p90"]
    )
    assert D["min_puntos"] == DC.MIN_PUNTOS and D["d_min_anual"] == DC.D_MIN_ANUAL
    assert (
        D["dias_mes"] == pytest.approx(365.25 / 12) and D["jitter_percentil"] == 8.0 and D["uptime"] == 0.92
    )
    assert D["bbl_por_m3"] == pytest.approx(6.2898, abs=1e-4) and D["mmbtu_por_mil_m3"] == pytest.approx(
        36.905, abs=1e-3
    )
    assert D["ft3_por_m3"] == pytest.approx(35.3147, abs=1e-4)
    assert "día efectivo" in D["nota"] and "extrapolación" in D["nota"]
    assert D["n_grupos"] == len(D["grupos"]) > 0
    claves = set()
    n = {"curvas": 0, "acotadas": 0, "empalmes": 0}
    for g in D["grupos"]:
        assert set(g) == {"cohorte", "formacion", "ventana", "n_pozos", "n_pozos_por_m", "curvas"}
        assert isinstance(g["cohorte"], int) and g["ventana"] in ("petroleo", "volatil_condensado", "gas")
        claves.add((g["cohorte"], g["formacion"], g["ventana"]))
        assert g["curvas"] and set(g["curvas"]) <= set(
            S.SIM_CURVAS
        )  # a group with nothing to simulate is dropped
        for col, c in g["curvas"].items():
            n["curvas"] += 1
            assert set(c) == CLAVES_CURVA, col
            largo = len(c["p50"])
            assert len(c["p10"]) == len(c["p90"]) == largo <= D["meses"]
            assert (
                c["p50"][-1] is not None
            )  # trailing months without a curve are trimmed, not shipped as nulls
            validos = 0
            for k in range(largo):
                a, b, d = c["p10"][k], c["p50"][k], c["p90"][k]
                if b is None:  # a month without a curve is null in the three quantiles, never a zero
                    assert a is None and d is None
                    continue
                validos += 1
                assert a >= b >= d > 0, (
                    f"{g['cohorte']} {g['formacion']} {g['ventana']} {col} month {k}: {a} {b} {d}"
                )
            assert validos == c["validos"] >= DC.MIN_PUNTOS
            u = c["ultimo_mes"]
            assert 0 <= u < D["meses"] and c["p50"][min(u, largo - 1)] is not None
            assert 0 < c["publicados"] <= u + 1 and c["publicados"] <= c["validos"]
            assert 0 <= c["acotados"] <= max(0, largo - 1 - u)
            n["acotadas"] += c["acotados"] > 0
            if u + 1 < largo and c["p50"][u + 1] is not None:
                # the extension starts at the last published value and declines from there: no step at the splice
                n["empalmes"] += 1
                for s in ("p10", "p50", "p90"):
                    paso = c[s][u + 1] / c[s][u]
                    assert 0.5 < paso <= 1.0005, (
                        f"{g['cohorte']} {g['formacion']} {col} {s}: step {paso:.3f} at the splice"
                    )
                # and it keeps declining (4 significant digits of rounding allowed)
                cola = [v for v in c["p50"][u + 1 :] if v is not None]
                assert all(y <= x * 1.0005 for x, y in zip(cola, cola[1:], strict=False))
    assert len(claves) == len(D["grupos"])  # one entry per cohort × formation × window
    return n


# --- built from synthetic tables ------------------------------------------------------------------------------------


def test_simulador_json_schema_order_and_splice():
    D = S.build_simulador(_curvas())
    n = _verificar(D)
    assert D["n_grupos"] == 1 and n["curvas"] == 4 and n["empalmes"] == 4 and n["acotadas"] == 0
    g = D["grupos"][0]
    assert (g["cohorte"], g["formacion"], g["ventana"]) == (2022, "Vaca Muerta", "petroleo")
    assert g["n_pozos"] == 40 and g["n_pozos_por_m"] == 30
    c = g["curvas"]["petroleo_m3_d"]
    assert len(c["p50"]) == S.SIM_MESES and c["validos"] == S.SIM_MESES
    assert c["publicados"] == 40 and c["ultimo_mes"] == 39
    assert c["n_ultimo"] == 40 - 39 // 2 and c["descartados"] == 0  # month 39 still has 21 of 40 wells
    # per metre the count falls below half of 30 after month 31: the tail is spliced there (ADR-038)
    cm = g["curvas"]["petroleo_m3_d_por_m"]
    assert (cm["ultimo_mes"], cm["n_ultimo"], cm["descartados"], cm["publicados"]) == (31, 15, 8, 32)
    assert c["p50"][0] == S.sig(
        float(_hiperbolica(np.arange(1), 120.0, 1.1, 0.25)[0])
    )  # published months: a copy
    assert D["precios"] is None  # no prices table given
    json.dumps(D, allow_nan=False)


def test_simulador_json_is_the_python_simulators_extension():
    """Both sides share ``cuantiles_extendidos``: the file is that output rounded, month by month."""
    curvas = _curvas()
    D = S.build_simulador(curvas)
    g = curvas[(curvas.nivel == S.SIM_NIVEL) & ~curvas.incluye_outliers]
    for col in S.SIM_CURVAS:
        n_col = "n_pozos_por_m" if col.endswith("_por_m") else "n_pozos"
        cu = g[["mes", f"{col}_p10", f"{col}_p50", f"{col}_p90", n_col]].set_axis(
            ["mes", "p10", "p50", "p90", "n"], axis=1
        )
        e = SC.cuantiles_extendidos(cu, S.SIM_MESES)
        for s in ("p10", "p50", "p90"):
            assert D["grupos"][0]["curvas"][col][s] == [S.sig(float(v)) for v in e[s]]
    # and the simulator run on a longer horizon uses the same extension (its first 120 months)
    cu = g[["mes", "petroleo_m3_d_p10", "petroleo_m3_d_p50", "petroleo_m3_d_p90"]].set_axis(
        ["mes", "p10", "p50", "p90"], axis=1
    )
    largo = SC.cuantiles_extendidos(cu, 200)
    assert np.allclose(largo["p50"][:120], SC.cuantiles_extendidos(cu, 120)["p50"])
    r = SC.simular(cu, n_pozos=3, meses=120, n_sim=20, semilla=0)
    assert r["meses_curva_publicados"] == 40 and r["meses_extrapolados"] == 80 and r["meses_acotados"] == 0


def test_crossing_tails_are_held_on_the_p50():
    """Tails fitted one by one can cross far from the data; the shared extension keeps P10 >= P50 >= P90."""
    curvas = _curvas(cruzar=True)
    g = curvas[(curvas.nivel == S.SIM_NIVEL) & ~curvas.incluye_outliers]
    cu = g[["mes", "petroleo_m3_d_p10", "petroleo_m3_d_p50", "petroleo_m3_d_p90"]].set_axis(
        ["mes", "p10", "p50", "p90"], axis=1
    )
    q50 = SC._extender_cuantil(cu.mes.to_numpy(), cu.p50.to_numpy(), 120, DC.D_MIN_ANUAL)
    q90 = SC._extender_cuantil(cu.mes.to_numpy(), cu.p90.to_numpy(), 120, DC.D_MIN_ANUAL)
    assert (q90 > q50).any(), "the fixture must make the raw tails cross"
    e = SC.cuantiles_extendidos(cu, 120)
    assert e["meses_acotados"] == int((q90 > q50).sum()) > 0
    assert (e["p10"] >= e["p50"]).all() and (e["p50"] >= e["p90"]).all()
    assert np.array_equal(e["p90"][:40], cu.p90.to_numpy())  # published months are never touched
    D = S.build_simulador(curvas)
    n = _verificar(D)
    assert n["acotadas"] == 4 and D["grupos"][0]["curvas"]["petroleo_m3_d"]["acotados"] == e["meses_acotados"]
    r = SC.simular(cu, n_pozos=5, meses=120, n_sim=30, semilla=0)
    assert r["meses_acotados"] == e["meses_acotados"]
    assert r["final"]["acumulado_p90"] <= r["final"]["acumulado_p50"] <= r["final"]["acumulado_p10"]


def test_groups_that_cannot_be_simulated_are_dropped():
    corto = _curvas(meses=DC.MIN_PUNTOS - 1, grupos=((2026, "Vaca Muerta", "gas"),))  # too few months to fit
    largo = _curvas(grupos=((2021, "Vaca Muerta", "gas"), (2022, "Lajas", "gas")))
    sin_ventana = largo.assign(
        nivel="cohorte_formacion", ventana=None
    )  # another level: not this file's grain
    lejos = _curvas(meses=30, grupos=((2006, "Agrio", "petroleo"),)).assign(mes=lambda d: d.mes + 200)
    D = S.build_simulador(pd.concat([corto, largo, sin_ventana, lejos], ignore_index=True))
    _verificar(D)
    assert [(g["cohorte"], g["formacion"]) for g in D["grupos"]] == [(2021, "Vaca Muerta"), (2022, "Lajas")]
    # a curve with a quantile that is not positive is left out, the rest of the group stays
    c = _curvas()
    c["gas_mil_m3_d_p90"] = 0.0
    c["gas_mil_m3_d_por_m_p50"] = None
    D = S.build_simulador(c)
    assert set(D["grupos"][0]["curvas"]) == {"petroleo_m3_d", "petroleo_m3_d_por_m"}


def test_months_without_a_curve_are_nulls_in_the_three_quantiles():
    c = _curvas()
    c.loc[c.mes == 10, ["petroleo_m3_d_p10"]] = None  # e.g. n < 5 that month
    D = S.build_simulador(c)
    _verificar(D)
    cu = D["grupos"][0]["curvas"]["petroleo_m3_d"]
    assert cu["p10"][10] is None and cu["p50"][10] is None and cu["p90"][10] is None
    assert cu["validos"] == S.SIM_MESES - 1 and cu["publicados"] == 39


def test_default_prices_from_the_precios_table():
    from conftest import _tabla_precios_fixture

    t = _tabla_precios_fixture()
    P = S.precios_simulador(t)
    pe = t[(t.producto == "petroleo") & (t.region == "Neuquén") & t.precio_dataset.notna()].sort_values(
        ["anio", "mes"]
    )
    ga = t[
        (t.producto == "gas") & (t.region == "Neuquina") & (t.segmento == "ppp") & (t.contrato == "total")
    ].sort_values(["anio", "mes"])
    assert len(pe) and len(ga), "the price fixture must carry Neuquén crude and Neuquina ppp/total gas"
    u = pe.iloc[-1]
    assert (
        P["petroleo"]["mes"] == f"{int(u.anio):04d}-{int(u.mes):02d}" and P["petroleo"]["region"] == "Neuquén"
    )
    assert P["petroleo"]["usd_m3"] == pytest.approx(float(u.precio_usd_m3), rel=1e-4)
    assert P["petroleo"]["usd_bbl"] == pytest.approx(float(u.precio_usd_m3) / units.BBL_PER_M3, rel=1e-4)
    assert P["petroleo"]["provisorio"] == bool(u.provisorio)
    assert (P["petroleo"]["tabla"], P["petroleo"]["columna"]) == ("precios", "precio_usd_m3")
    g = ga.iloc[-1]
    assert P["gas"]["usd_mmbtu"] == pytest.approx(float(g.precio_dataset), rel=1e-4)
    assert P["gas"]["usd_mil_m3"] == pytest.approx(
        float(g.precio_dataset) * units.MMBTU_PER_THOUSAND_M3, rel=1e-4
    )
    assert (P["gas"]["segmento"], P["gas"]["contrato"], P["gas"]["columna"]) == (
        "ppp",
        "total",
        "precio_usd_mil_m3",
    )
    assert "CC-BY" in P["licencia"] and P["fecha_descarga"] == "2026-11-02"
    assert S.precios_simulador(None) is None and S.precios_simulador(t.iloc[0:0]) is None
    assert S.build_simulador(_curvas(), t)["precios"] == P


def test_build_site_data_writes_it_and_falls_back_to_the_price_snapshot(tmp_path):
    from datetime import date

    from conftest import _tabla_precios_fixture

    from vma.precios import fuentes as F

    t = _tabla_precios_fixture()
    args = (TS._master(), TS._ind(), TS._curvas(), TS.MANIFEST, "2026-10-31")
    con = tmp_path / "con"
    meta = S.build_site_data(con, *args, today=date(2026, 10, 31), precios=t)
    D = json.loads((con / "simulador.json").read_text(encoding="utf-8"))
    _verificar(D)
    assert meta["archivos"]["simulador.json"] == len((con / "simulador.json").read_bytes()) < S.SIM_MAX_BYTES
    assert D["precios"]["petroleo"]["usd_bbl"] > 0 and meta["tablas"]["precios"]["filas"] == len(t)
    # without the table (the monthly workflow): the committed precios.json snapshot gives the same defaults
    sin = tmp_path / "sin"
    sin.mkdir()
    (sin / "precios.json").write_text(json.dumps(F.snapshot_json(t), allow_nan=False), encoding="utf-8")
    meta2 = S.build_site_data(sin, *args, today=date(2026, 10, 31))
    D2 = json.loads((sin / "simulador.json").read_text(encoding="utf-8"))
    assert D2["precios"]["petroleo"]["usd_m3"] == pytest.approx(D["precios"]["petroleo"]["usd_m3"], rel=1e-3)
    assert D2["precios"]["gas"]["usd_mmbtu"] == D["precios"]["gas"]["usd_mmbtu"]
    assert "precios" not in meta2["tablas"]
    # and with neither, the file is still written, without prices
    nada = tmp_path / "nada"
    S.build_site_data(nada, *args, today=date(2026, 10, 31))
    assert json.loads((nada / "simulador.json").read_text(encoding="utf-8"))["precios"] is None


def test_site_run_keeps_the_manifest_of_the_download_the_tables_come_from(tmp_path):
    """A later opt-in download (prices only) writes its own dated folder; the method page must keep showing the
    manifest of the production download."""
    raw = tmp_path / "data" / "raw"
    for dia, claves in (("2026-10-30", ["pozos", "produccion_nc"]), ("2026-11-02", ["precios_gas"])):
        (raw / dia).mkdir(parents=True)
        (raw / dia / "manifest.json").write_text(
            json.dumps({"generated_at": dia, "sources": [{"key": k} for k in claves]}), encoding="utf-8"
        )
    m = S._manifest_de_las_tablas(tmp_path, raw / "2026-11-02")
    assert m["generated_at"] == "2026-10-30"
    (raw / "2026-10-30" / "manifest.json").unlink()
    assert S._manifest_de_las_tablas(tmp_path, raw / "2026-11-02")["generated_at"] == "2026-11-02"


# --- the committed file ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not REAL.exists(), reason="site/data/simulador.json is generated by `pipeline.py site`")
def test_committed_simulador_json():
    texto = REAL.read_text(encoding="utf-8")
    assert "NaN" not in texto and "Infinity" not in texto
    assert len(texto.encode("utf-8")) < S.SIM_MAX_BYTES, "simulador.json outgrew its cap (ADR-036)"
    D = json.loads(texto)
    n = _verificar(D)
    assert n["empalmes"] > 0
    meta = json.loads((REAL.parent / "meta.json").read_text(encoding="utf-8"))
    assert meta["archivos"]["simulador.json"] == len(REAL.read_bytes())
    # the page's default: Vaca Muerta, oil window, a cohort with 24 published months
    vm = [
        g
        for g in D["grupos"]
        if g["formacion"] == "Vaca Muerta" and g["ventana"] == "petroleo" and "petroleo_m3_d" in g["curvas"]
    ]
    assert any(g["curvas"]["petroleo_m3_d"]["publicados"] >= 24 for g in vm)
    if D["precios"]:
        for prod, col in (("petroleo", "precio_usd_m3"), ("gas", "precio_usd_mil_m3")):
            p = D["precios"][prod]
            assert p["tabla"] == "precios" and p["columna"] == col and len(p["mes"]) == 7
        assert D["precios"]["petroleo"]["usd_bbl"] == pytest.approx(
            D["precios"]["petroleo"]["usd_m3"] / D["bbl_por_m3"], rel=1e-4
        )
        assert D["precios"]["gas"]["usd_mil_m3"] == pytest.approx(
            D["precios"]["gas"]["usd_mmbtu"] * D["mmbtu_por_mil_m3"], rel=1e-3
        )


def test_tail_is_spliced_where_half_of_the_wells_remain():
    """A young cohort's last months are its few oldest wells: a jump there must not set the level of the tail."""
    mes = np.arange(33)
    p50 = _hiperbolica(mes, 120.0, 1.1, 0.25)
    n = np.where(mes <= 26, 300, 300 - (mes - 26) * 45).clip(min=7)
    cu = pd.DataFrame({"mes": mes, "p10": 1.7 * p50, "p50": p50.copy(), "p90": 0.45 * p50, "n": n})
    cu.loc[cu.mes == 32, ["p10", "p50", "p90"]] *= 2.0  # the survivors' month doubles
    e = SC.cuantiles_extendidos(cu, 120)
    assert e["ultimo_mes"] == 29 and e["meses_descartados"] == 3 and e["meses_publicados"] == 30
    assert np.all(np.diff(e["p50"][29:]) <= 0) and e["p50"][32] < p50[31]  # no step where the data thin out
    sin_n = SC.cuantiles_extendidos(cu.drop(columns="n"), 120)  # without counts nothing is discarded
    assert sin_n["ultimo_mes"] == 32 and sin_n["meses_descartados"] == 0 and sin_n["p50"][32] == cu.p50[32]
    r = SC.simular(cu, n_pozos=3, meses=60, n_sim=20, semilla=0)
    assert r["meses_descartados"] == 3 and r["meses_extrapolados"] == 30
