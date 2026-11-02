"""F5: decline fits (Arps, Duong), EUR with band, campaign Monte Carlo, and the three tools on both sources.
Synthetic series with known parameters; no network, no model, no real data."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import test_consulta as TC

from vma.consulta import datos as D
from vma.consulta import herramientas as H
from vma.simulacion import campania as SC
from vma.simulacion import declinacion as DC
from vma.simulacion import series as SS

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "sintetico"


@pytest.fixture(scope="module")
def TC_raiz(tmp_path_factory) -> Path:
    from datetime import date

    import duckdb

    from vma import site as SITE

    root = tmp_path_factory.mktemp("repo_sim")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    for name, df in (("pozos", TC._master()), ("indicadores", TC._ind()), ("curvas_tipo", TC._curvas())):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    SITE.build_site_data(
        root / "site" / "data",
        TC._master(),
        TC._ind(),
        TC._curvas(),
        TC.MANIFEST,
        "2026-10-31",
        today=date(2026, 10, 31),
    )
    return root


@pytest.fixture(params=["parquet", "json"])
def d(TC_raiz, request) -> D.Datos:
    return D.abrir(TC_raiz, request.param)


# --- models and fits ----------------------------------------------------------------------------------------------------


def test_models_recover_their_own_parameters():
    t = np.arange(2, 40) + 0.5
    for modelo, p in (
        ("exponencial", {"qi": 200.0, "D": 0.03}),
        ("hiperbolico", {"qi": 300.0, "D": 0.08, "b": 0.9}),
        ("armonico", {"qi": 250.0, "D": 0.05, "b": 1.0}),
        ("duong", {"q1": 400.0, "a": 1.3, "m": 1.2}),
    ):
        q = DC.tasa_modelo(modelo, p, t)
        a = DC.ajustar(t, q, modelo)
        for k, v in p.items():
            assert a.parametros[k] == pytest.approx(v, rel=0.06), (modelo, k)
        assert a.rmse_log < 1e-3
    with pytest.raises(DC.ErrorAjuste, match="al menos 6 meses"):
        DC.ajustar(t[:4], q[:4], "exponencial")
    with pytest.raises(DC.ErrorAjuste, match="desconocido"):
        DC.ajustar(t, q, "logistico")


def test_auto_picks_the_generating_model_and_reports_the_table():
    rng = np.random.default_rng(0)
    t = np.arange(2, 48) + 0.5
    q = DC.tasa_modelo("hiperbolico", {"qi": 300.0, "D": 0.1, "b": 1.1}, t) * np.exp(
        rng.normal(0, 0.03, t.size)
    )
    mejor, tabla = DC.ajustar_auto(t, q)
    assert mejor.modelo in (
        "hiperbolico",
        "duong",
    )  # both are long-transient shapes; AIC decides on the noise
    assert sum(r.get("elegido", False) for r in tabla) == 1 and {r["modelo"] for r in tabla} == set(
        DC.MODELOS
    )
    q_exp = DC.tasa_modelo("exponencial", {"qi": 100.0, "D": 0.04}, t) * np.exp(rng.normal(0, 0.02, t.size))
    mejor, _ = DC.ajustar_auto(t, q_exp)
    # a hyperbolic with b at the bottom of the grid is the same curve; AIC may pick either on noise
    assert mejor.modelo == "exponencial" or (mejor.modelo == "hiperbolico" and mejor.parametros["b"] <= 0.1)
    assert mejor.parametros["qi"] == pytest.approx(100.0, rel=0.05)


def test_terminal_decline_caps_a_b_over_one_curve():
    t = np.arange(0, 360) + 0.5
    p = {"qi": 300.0, "D": 0.1, "b": 1.5}
    libre = DC.tasa_modelo("hiperbolico", p, t)
    d_min_mes = -np.log(1 - 0.06) / 12
    capada = DC.tasa_con_d_min("hiperbolico", p, t, d_min_mes)
    assert np.all(capada <= libre + 1e-9) and capada[-1] < libre[-1]
    # after the switch the curve declines at exactly d_min
    dec = DC.declinacion_instantanea("hiperbolico", p, t)
    i = int(np.where(dec < d_min_mes)[0][0])
    assert np.log(capada[i] / capada[i + 12]) == pytest.approx(d_min_mes * 12, rel=1e-6)


def test_forecast_integrates_history_then_curve_and_bootstrap_band():
    t = np.arange(0, 24) + 0.5
    q = DC.tasa_modelo("exponencial", {"qi": 100.0, "D": 0.05}, t)
    dias = DC.DIAS_MES
    vol = q * dias * 0.9
    aj = DC.ajustar(t[2:], q[2:], "exponencial")
    pr = DC.pronosticar(aj, np.arange(24), vol, uptime=0.9, horizonte_meses=240, q_min=None, d_min_anual=0.0)
    assert pr.meses.size == 240 and pr.historia_acum == pytest.approx(vol.sum())
    assert pr.volumen_mes[:24] == pytest.approx(vol)  # history kept as observed
    # analytic EUR of qi e^{-Dt} integrated to infinity is qi/D per month-unit -> close at 240 months
    analitico = 100.0 / 0.05 * dias * 0.9
    assert pr.eur == pytest.approx(analitico, rel=0.02)
    pr_lim = DC.pronosticar(aj, np.arange(24), vol, 0.9, 240, q_min=5.0, d_min_anual=0.0)
    assert pr_lim.mes_limite is not None and pr_lim.eur < pr.eur
    assert pr_lim.volumen_mes[pr_lim.mes_limite :].sum() == 0
    rng_q = q[2:] * np.exp(np.random.default_rng(1).normal(0, 0.05, q.size - 2))
    aj2 = DC.ajustar(t[2:], rng_q, "exponencial")
    b = DC.bootstrap_eur(aj2, np.arange(24), vol, 0.9, 240, None, 0.0, n=60, semilla=2)
    assert b["n"] == 60 and b["eur_p90"] <= b["eur_p50"] <= b["eur_p10"]
    assert abs(b["eur_p50"] / analitico - 1) < 0.1
    res = DC.resumen_pronostico(pr)
    assert (
        res["modelo"] == "exponencial"
        and len(res["por_anio"]) == 20
        and res["eur_restante"] == pytest.approx(pr.eur - vol.sum())
    )
    assert res["declinacion_efectiva_anual_inicial"] == pytest.approx(1 - np.exp(-0.05 * 12))


# --- campaign -------------------------------------------------------------------------------------------------------------


def _curva(meses: int = 36) -> pd.DataFrame:
    mes = np.arange(meses)
    p50 = 100.0 / (mes + 1)
    return pd.DataFrame({"mes": mes, "p10": 1.5 * p50, "p50": p50, "p90": 0.5 * p50})


def test_percentile_inverse_matches_forward():
    from vma.propios.comparar import percentil_en_curva

    q = SC._tasa_desde_percentil(
        np.array([10.0, 50.0, 90.0, 30.0]), np.full(4, 150.0), np.full(4, 100.0), np.full(4, 50.0)
    )
    assert q[:3] == pytest.approx([150.0, 100.0, 50.0])
    assert percentil_en_curva(float(q[3]), 150.0, 100.0, 50.0) == pytest.approx(30.0)


def test_campaign_bands_scale_and_stagger():
    r = SC.simular(_curva(), n_pozos=10, meses=24, n_sim=200, semilla=1, uptime=1.0, jitter_percentil=0.0)
    assert r["pozos_en_linea"] == [10] * 24 and r["meses_extrapolados"] == 0
    p50_mes0 = r["tasa_agregada"]["p50"][0]
    assert 10 * 100 * 0.8 < p50_mes0 < 10 * 100 * 1.25  # ten wells around the P50 of 100
    assert r["tasa_agregada"]["p90"][0] < p50_mes0 < r["tasa_agregada"]["p10"][0]
    assert r["final"]["acumulado_p90"] < r["final"]["acumulado_p50"] < r["final"]["acumulado_p10"]
    assert r["final"]["acumulado_p50"] == pytest.approx(r["acumulado"]["p50"][-1])
    # staggered: 2 wells a month -> 5 months to fill
    r2 = SC.simular(_curva(), n_pozos=10, meses=24, ritmo=2, n_sim=100, semilla=1, uptime=1.0)
    assert r2["pozos_en_linea"][:6] == [2, 4, 6, 8, 10, 10]
    assert r2["tasa_agregada"]["p50"][0] < r["tasa_agregada"]["p50"][0]
    # per metre: rate scales with the lateral
    por_m = _curva()
    por_m[["p10", "p50", "p90"]] = por_m[["p10", "p50", "p90"]] / 2000.0
    r3 = SC.simular(
        por_m,
        n_pozos=10,
        meses=24,
        rama_m=2000,
        por_metro=True,
        n_sim=200,
        semilla=1,
        uptime=1.0,
        jitter_percentil=0.0,
    )
    assert r3["escala_por_metro"] is True
    assert r3["tasa_agregada"]["p50"][0] == pytest.approx(r["tasa_agregada"]["p50"][0], rel=1e-6)
    # extrapolation beyond the published months is said and declines
    r4 = SC.simular(_curva(36), n_pozos=4, meses=120, n_sim=50, semilla=0)
    assert (
        r4["meses_extrapolados"] == 120 - 36
        and r4["tasa_agregada"]["p50"][-1] < r4["tasa_agregada"]["p50"][35]
    )
    with pytest.raises(SC.ErrorSimulacion, match="n_pozos"):
        SC.simular(_curva(), n_pozos=0, meses=12)
    with pytest.raises(SC.ErrorSimulacion, match="meses publicables"):
        SC.simular(_curva(4), n_pozos=3, meses=12)


# --- series and tools -------------------------------------------------------------------------------------------------------


def test_public_series_needs_parquet_and_raw(d):
    if d.fuente == "json":
        with pytest.raises(SS.SinSerie, match="idpozos"):
            SS.serie_publica(d, "OP.NQ.VM-101(H)")
    else:
        with pytest.raises(SS.SinSerie, match="produccion_nc.csv"):
            SS.serie_publica(d, "OP.NQ.VM-101(H)")
        with pytest.raises(SS.SinSerie, match="buscar_pozo"):
            SS.serie_publica(d, "NO-EXISTE")
    with pytest.raises(SS.SinSerie, match="cargar_mis_pozos"):
        SS.serie_mia(d, "MIO-001")


def test_pronosticar_pozo_mio_and_curva_tipo_tools(d):
    H.ejecutar(
        d,
        "cargar_mis_pozos",
        {"ruta": str(FIX / "mis_pozos_produccion.csv"), "ruta_pozos": str(FIX / "mis_pozos_atributos.csv")},
    )
    r = H.ejecutar(
        d, "pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "n_bootstrap": 40, "horizonte_anios": 20}
    )
    TC._cita_ok(r)
    dd = r["datos"]
    assert dd["modelo"] in DC.MODELOS and dd["eur"] > dd["historia_acumulada"] > 0
    assert dd["banda_bootstrap"]["n"] == 40 and dd["pozo"]["sintetico"] is True
    assert len(dd["por_anio"]) == 20 and dd["historia"]["omitidos"] == 2
    assert any("SINTÉTICOS" in n for n in r["notas"]) and any(
        "no simulación de reservorio" in n for n in r["notas"]
    )
    assert sum(x.get("elegido", False) for x in dd["comparacion_modelos"]) == 1
    json.dumps(r, allow_nan=False)
    r2 = H.ejecutar(
        d,
        "pronosticar_pozo",
        {
            "sigla": "MIO-002",
            "mio": True,
            "modelo": "exponencial",
            "n_bootstrap": 0,
            "q_min": 50.0,
            "uptime": 0.8,
        },
    )
    assert (
        r2["datos"]["modelo"] == "exponencial"
        and r2["datos"]["uptime"] == 0.8
        and r2["datos"]["banda_bootstrap"] == {}
    )
    assert r2["datos"]["mes_limite_economico"] is not None
    with pytest.raises(H.ErrorHerramienta, match="horizonte_anios"):
        H.ejecutar(d, "pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "horizonte_anios": 7})
    with pytest.raises(H.ErrorHerramienta, match="modelo debe ser"):
        H.ejecutar(d, "pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "modelo": "logistico"})
    with pytest.raises(H.ErrorHerramienta):
        H.ejecutar(
            d, "pronosticar_pozo", {"sigla": "OP.NQ.VM-101(H)"}
        )  # public well: no raw CSV in the fake repo
    d.propios = None

    r = H.ejecutar(
        d,
        "pronosticar_curva_tipo",
        {
            "nivel": "cohorte_formacion",
            "claves": {"cohorte": 2024, "formacion": "Vaca Muerta"},
            "horizonte_anios": 30,
        },
    )
    TC._cita_ok(r)
    e = r["datos"]["eur_pozo_tipo"]
    assert e["p90"] < e["p50"] < e["p10"] and e["meses_publicados"] >= 60
    assert r["datos"]["cuantiles"]["p50"]["modelo"] in DC.MODELOS
    if d.fuente == "json":
        assert any("ADR-023" in n for n in r["notas"])


def test_simular_campania_tool(d):
    r = H.ejecutar(
        d,
        "simular_campania",
        {
            "formacion": "vaca muerta",
            "n_pozos": 6,
            "meses": 36,
            "ventana": "petroleo",
            "cohorte_ref": 2024,
            "n_sim": 50,
            "semilla": 3,
        },
    )
    TC._cita_ok(r)
    dd = r["datos"]
    assert dd["grupo"]["nivel"] == "cohorte_formacion_ventana" and dd["grupo"]["formacion"] == "Vaca Muerta"
    assert len(dd["tasa_agregada"]["p50"]) == 36 and dd["pozos_en_linea"][0] == 6
    assert dd["final"]["acumulado_p90"] < dd["final"]["acumulado_p50"] < dd["final"]["acumulado_p10"]
    assert r["cita"]["filtros"]["cohorte_ref"] == 2024
    # default cohort: the newest with 12 publishable months (2024 in the fake tables)
    r2 = H.ejecutar(
        d, "simular_campania", {"formacion": "Vaca Muerta", "n_pozos": 3, "meses": 12, "n_sim": 20}
    )
    assert r2["datos"]["grupo"]["cohorte_ref"] == 2024 and any("mezcla ventanas" in n for n in r2["notas"])
    # lateral: the fake per-metre curves exist, so the rate scales
    r3 = H.ejecutar(
        d,
        "simular_campania",
        {
            "formacion": "Vaca Muerta",
            "n_pozos": 3,
            "meses": 12,
            "ventana": "petroleo",
            "cohorte_ref": 2024,
            "rama_m": 3000,
            "n_sim": 20,
            "semilla": 3,
        },
    )
    assert r3["datos"]["escala_por_metro"] is True and r3["cita"]["columnas"][1].endswith("_por_m_p10")
    r4 = H.ejecutar(
        d,
        "simular_campania",
        {
            "formacion": "Vaca Muerta",
            "n_pozos": 3,
            "meses": 12,
            "ventana": "petroleo",
            "cohorte_ref": 2024,
            "n_sim": 20,
            "incluye_outliers": False,
        },
    )
    assert any("ADR-018" in e for e in r4["exclusiones"])
    with pytest.raises(H.ErrorHerramienta, match="menos de 6 meses publicables|cohorte"):
        H.ejecutar(
            d,
            "simular_campania",
            {"formacion": "Vaca Muerta", "n_pozos": 3, "meses": 12, "cohorte_ref": 2019, "n_sim": 20},
        )
    with pytest.raises(H.ErrorHerramienta, match="n_pozos"):
        H.ejecutar(
            d, "simular_campania", {"formacion": "Vaca Muerta", "n_pozos": 0, "meses": 12, "n_sim": 20}
        )


def test_simulation_tools_are_registered_and_documented():
    nombres = {"pronosticar_pozo", "pronosticar_curva_tipo", "simular_campania"}
    assert nombres <= set(H.HERRAMIENTAS)
    defs = {t["name"]: t for t in H.definiciones()}
    assert defs["simular_campania"]["input_schema"]["required"] == ["formacion", "n_pozos"]
    assert defs["pronosticar_pozo"]["input_schema"]["properties"]["modelo"]["enum"] == list(H.MODELOS_TOOL)
    doc = (ROOT / "docs" / "simulacion.md").read_text(encoding="utf-8")
    for n in nombres:
        assert f"`{n}(" in doc
    for palabra in ("Arps", "Duong", "bootstrap", "no es simulación de reservorio", "PVT"):
        assert palabra in doc
