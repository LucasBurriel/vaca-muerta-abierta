"""F6: the tools with and without ``valorizar`` (the rest of the result must not change), the ``precios`` tool, the
source without the table, the views, the MCP server and the mock agent. Fixtures from tests/test_precios.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_consulta as TC

from vma import apps as APPS
from vma import units
from vma.consulta import agente as A
from vma.consulta import datos as D
from vma.consulta import herramientas as H

ROOT = Path(__file__).resolve().parents[1]
SINT = ROOT / "tests" / "fixtures" / "sintetico"
CURVA = {"nivel": "cohorte_formacion", "claves": {"cohorte": 2024, "formacion": "Vaca Muerta"}, "mes_max": 2}
ULTIMO_CRUDO_NQN = 508.0  # fixture: 500 + month, 2026-08
ULTIMO_GAS_NQN = (4.0 + 0.1 + 0.08) * units.MMBTU_PER_THOUSAND_M3  # ppp, total, 2026-08, per mil m³


def _cargar(d_precios):
    d = d_precios
    H.ejecutar(
        d,
        "cargar_mis_pozos",
        {"ruta": str(SINT / "mis_pozos_produccion.csv"), "ruta_pozos": str(SINT / "mis_pozos_atributos.csv")},
    )


def _sin_usd(r: dict) -> dict:
    r = json.loads(json.dumps(r))
    r["datos"].pop("usd", None)
    r["notas"] = [n for n in r["notas"] if not n.startswith("usd:")]
    return r


def test_without_valorizar_nothing_changes(d_precios):
    d = d_precios
    _cargar(d)
    llamadas = [
        ("curva_tipo", CURVA),
        ("comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 3}),
        ("comparar_mi_campania", {"filtros": {"cohorte": 2024}, "metrica": "ip90_petroleo_m3_d"}),
        ("pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "n_bootstrap": 0}),
        ("simular_campania", {"formacion": "Vaca Muerta", "n_pozos": 3, "meses": 12, "n_sim": 20}),
    ]
    for nombre, entrada in llamadas:
        sin = H.ejecutar(d, nombre, entrada)
        assert "usd" not in sin["datos"] and not any("usd" in n for n in sin["notas"])
        con = H.ejecutar(d, nombre, {**entrada, "valorizar": {"modo": "ultimo"}})
        assert "usd" in con["datos"] and con["datos"]["usd"].get("sin_dato_porque") is None, nombre
        assert _sin_usd(con) == sin, nombre  # the rest of the result is byte-for-byte the same
        assert con["cita"] == sin["cita"]  # the data citation is untouched; the price one lives in usd.cita
        assert con["datos"]["usd"]["cita"]["tabla"] == "precios"
        TC._cita_ok(con)
    d.propios = None


def test_curva_tipo_values_oil_and_gas_quantiles_at_the_last_price(d_precios):
    d = d_precios
    r = H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"modo": "ultimo", "uptime": 1.0}})
    u = r["datos"]["usd"]
    assert (
        u["modo"] == "ultimo" and u["mes0"] == "2024-01" and set(u) >= {"p10", "p50", "p90", "cita", "notas"}
    )
    # fixture curve: oil 100/(mes+1) m³/d and gas 100/(mes+1) mil m³/d (P50); month 0 volume = 100 × 30.4375 d
    vol0 = 100 * 365.25 / 12
    esperado0 = vol0 * ULTIMO_CRUDO_NQN + vol0 * ULTIMO_GAS_NQN
    assert u["p50"]["series"]["ingreso_usd"][0] == pytest.approx(esperado0, rel=2e-3)  # 4 significant digits
    assert u["p10"]["series"]["ingreso_usd"][0] == pytest.approx(1.5 * esperado0, rel=2e-3)
    assert u["p50"]["total"]["meses"] == 3 and u["p50"]["total"]["van_usd"] < u["p50"]["total"]["ingreso_usd"]
    assert u["p50"]["precios"]["petroleo"]["region"] == "Neuquén"
    assert u["p50"]["precios"]["gas"]["region"] == "Neuquina"
    assert u["p50"]["precios"]["gas"]["ultimo_precio"] == pytest.approx(ULTIMO_GAS_NQN, rel=1e-3)
    assert u["cita"]["filtros"]["gas"] == {"region": "Neuquina", "segmento": "ppp", "contrato": "total"}
    assert any("sin provincia conocida" in n for n in u["notas"]) and any("BRUTO" in n for n in u["notas"])
    assert any(n.startswith("usd:") for n in r["notas"])
    # historico: mes0 = January of the cohort; 2024 is before the fixture's first price (2025-01) -> no USD
    h = H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"modo": "historico"}})["datos"]["usd"]
    assert h["p50"]["total"]["meses_sin_precio"] == 3 and h["p50"]["total"]["ingreso_usd"] == 0
    h2 = H.ejecutar(
        d, "curva_tipo", {**CURVA, "valorizar": {"modo": "historico", "mes0": "2026-07", "regalia": 0.12}}
    )["datos"]["usd"]
    assert h2["p50"]["total"]["meses_con_ultimo_precio"] == 1 and h2["p50"]["total"]["regalia_usd"] > 0
    assert h2["p50"]["series"]["mes_calendario"] == ["2026-07", "2026-08", "2026-09"]


def test_comparar_mi_pozo_values_me_and_the_type_well_in_my_calendar_months(d_precios):
    d = d_precios
    _cargar(d)
    r = H.ejecutar(d, "comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 24, "valorizar": {}})
    u = r["datos"]["usd"]
    assert u["modo"] == "historico" and u["mes0"] == "2024-07"  # my first month with production
    assert set(u) >= {"mio", "grupo_p10", "grupo_p50", "grupo_p90", "cita"}
    assert u["mio"]["total"]["meses_sin_precio"] == 6  # 2024-07..2024-12 are before the fixture's first price
    assert u["mio"]["total"]["ingreso_usd"] > 0
    assert u["grupo_p50"]["total"]["meses"] == u["mio"]["total"]["meses"]
    assert any("observado en mi pozo" in n for n in u["notas"])
    flat = H.ejecutar(
        d,
        "comparar_mi_pozo",
        {
            "sigla": "MIO-003",
            "mes_max": 2,
            "valorizar": {"modo": "flat", "precio_flat": {"petroleo_usd_bbl": 70, "gas_usd_mmbtu": 3}},
        },
    )
    uf = flat["datos"]["usd"]
    assert uf["cita"]["tabla"] == "precio_flat (del usuario)" and uf["mio"]["total"]["meses_sin_precio"] == 0
    with pytest.raises(H.ErrorHerramienta, match="falta precio_flat"):
        H.ejecutar(
            d,
            "comparar_mi_pozo",
            {
                "sigla": "MIO-003",
                "mes_max": 2,
                "valorizar": {"modo": "flat", "precio_flat": {"petroleo_usd_bbl": 70}},
            },
        )
    d.propios = None


def test_comparar_mi_campania_values_the_first_twelve_months_per_well(d_precios):
    d = d_precios
    _cargar(d)
    r = H.ejecutar(
        d,
        "comparar_mi_campania",
        {
            "filtros": {"cohorte": 2024},
            "metrica": "ip90_petroleo_m3_d",
            "valorizar": {"modo": "ultimo", "regalia": 0.12},
        },
    )
    u = r["datos"]["usd"]
    assert u["meses_por_pozo"] == 12 and u["modo"] == "ultimo" and u["regalia"] == 0.12
    con = [p for p in u["pozos"] if "ingreso_usd" in p]
    assert len(u["pozos"]) == len(r["datos"]["pozos"]) and all(p["meses_valorizados"] <= 12 for p in con)
    assert u["resumen"]["n_pozos"] >= 10
    assert u["resumen"]["ingreso_usd_total"] == pytest.approx(sum(p["ingreso_usd"] for p in con), rel=1e-3)
    # the fake indicadores carry no acum12 oil/gas, so the public median in USD says why
    assert all(p.get("mediana_publica_acum12_usd") is None for p in u["pozos"])
    assert any("primeros 12 meses" in n for n in u["notas"])
    d.propios = None


def test_pronosticar_pozo_values_the_p50_path_of_one_fluid(d_precios):
    d = d_precios
    _cargar(d)
    r = H.ejecutar(
        d, "pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "n_bootstrap": 0, "valorizar": {}}
    )
    u = r["datos"]["usd"]
    assert u["modo"] == "historico" and u["mes0"] == "2022-12" and u["pronostico"]["total"]["meses"] == 240
    assert (
        u["pronostico"]["total"]["meses_con_ultimo_precio"] == 240 - 45  # 2022-12 .. 2026-08 are published
        and u["pronostico"]["total"]["meses_sin_precio"] == 25  # 2022-12 .. 2024-12 precede the fixture
        and u["pronostico"]["precios"]["gas"] is None
    )
    assert u["pronostico"]["total"]["ingreso_usd"] == pytest.approx(
        u["pronostico"]["total"]["petroleo_usd"], rel=1e-3
    )
    g = H.ejecutar(
        d,
        "pronosticar_pozo",
        {
            "sigla": "MIO-002",
            "mio": True,
            "n_bootstrap": 0,
            "tasa": "gas_mil_m3_d",
            "valorizar": {"modo": "ultimo"},
        },
    )["datos"]["usd"]["pronostico"]
    assert g["precios"]["petroleo"] is None and g["precios"]["gas"]["region"] == "Neuquina"
    with pytest.raises(H.ErrorHerramienta, match="equivalente"):
        H.ejecutar(
            d,
            "pronosticar_pozo",
            {"sigla": "MIO-002", "mio": True, "n_bootstrap": 0, "tasa": "equivalente_m3_d", "valorizar": {}},
        )
    d.propios = None


def test_simular_campania_values_each_quantile_of_the_cumulative_band(d_precios):
    d = d_precios
    base = {"formacion": "Vaca Muerta", "n_pozos": 3, "meses": 12, "n_sim": 20}
    r = H.ejecutar(
        d,
        "simular_campania",
        {**base, "valorizar": {"modo": "flat", "precio_flat": {"petroleo_usd_bbl": 65}}},
    )
    u = r["datos"]["usd"]
    p_m3 = 65 * units.BBL_PER_M3
    # the valued volume is the cumulative band month by month, so the total equals the final cumulative × price
    assert u["p50"]["total"]["bruto_usd"] == pytest.approx(
        r["datos"]["final"]["acumulado_p50"] * p_m3, rel=2e-3
    )
    assert u["p10"]["total"]["bruto_usd"] > u["p50"]["total"]["bruto_usd"] > u["p90"]["total"]["bruto_usd"]
    assert len(u["p50"]["series"]["ingreso_usd"]) == 12
    assert u["cita"]["filtros"]["precio_flat"] == {"petroleo_usd_bbl": 65}
    ult = H.ejecutar(d, "simular_campania", {**base, "valorizar": {"modo": "ultimo"}})["datos"]["usd"]
    assert (
        ult["p50"]["precios"]["petroleo"]["ultimo_precio"] == ULTIMO_CRUDO_NQN
        and ult["cita"]["tabla"] == "precios"
    )
    with pytest.raises(H.ErrorHerramienta, match="mes0"):
        H.ejecutar(d, "simular_campania", {**base, "valorizar": {"modo": "historico"}})
    with pytest.raises(H.ErrorHerramienta, match="equivalente"):
        H.ejecutar(d, "simular_campania", {**base, "tasa": "equivalente_m3_d", "valorizar": {}})


def test_regions_resolve_loosely_or_fail_with_the_list(d_precios):
    d = d_precios
    r = H.ejecutar(
        d,
        "curva_tipo",
        {
            **CURVA,
            "valorizar": {
                "modo": "ultimo",
                "region_petroleo": "rio negro",
                "region_gas": "golfo de san jorge",
            },
        },
    )
    f = r["datos"]["usd"]["cita"]["filtros"]
    assert f["petroleo"]["region"] == "Río Negro" and f["gas"]["region"] == "Golfo de San Jorge"
    assert not any("sin provincia conocida" in n for n in r["datos"]["usd"]["notas"])
    with pytest.raises(H.ErrorHerramienta, match="Chubut"):
        H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"modo": "ultimo", "region_petroleo": "Marte"}})
    with pytest.raises(H.ErrorHerramienta, match="claves desconocidas"):
        H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"precio": 70}})
    with pytest.raises(H.ErrorHerramienta, match="modo"):
        H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"modo": "spot"}})
    with pytest.raises(H.ErrorHerramienta, match="segmento_gas"):
        H.ejecutar(d, "curva_tipo", {**CURVA, "valorizar": {"segmento_gas": "retail"}})


def test_without_the_table_the_block_says_why_and_flat_still_works(d_sin_precios):
    d_sin = d_sin_precios
    r = H.ejecutar(d_sin, "curva_tipo", {**CURVA, "valorizar": {"modo": "ultimo"}})
    assert "pipeline.py precios" in r["datos"]["usd"]["sin_dato_porque"]
    assert any(n.startswith("usd:") for n in r["notas"])
    p = H.ejecutar(d_sin, "precios", {"producto": "petroleo"})
    TC._cita_ok(p)
    assert p["datos"]["meses"] == [] and "pipeline.py precios" in p["datos"]["sin_dato_porque"]
    f = H.ejecutar(
        d_sin,
        "curva_tipo",
        {
            **CURVA,
            "valorizar": {"modo": "flat", "precio_flat": {"petroleo_usd_m3": 500, "gas_usd_mil_m3": 100}},
        },
    )
    assert f["datos"]["usd"]["p50"]["total"]["ingreso_usd"] > 0
    m = H.ejecutar(d_sin, "metadatos", {})["datos"]["tablas"]["precios"]
    assert m["filas"] == 0 and "sin_dato_porque" in m
    t = H.ejecutar(d_sin, "describir_tabla", {"tabla": "precios"})["datos"]
    assert "sin_dato_porque" in t and t["regiones"] == {"petroleo": [], "gas": []}


def test_precios_tool_series_defaults_and_cuts(d_precios):
    d = d_precios
    r = H.ejecutar(d, "precios", {"producto": "petroleo"})
    TC._cita_ok(r)
    x = r["datos"]
    assert (
        x["region"] == "Neuquén"
        and x["unidad_dataset"] == "USD/m³"
        and x["ultimo_mes_publicado"] == "2026-08"
    )
    assert (
        x["desde"] == "2024-09" and x["hasta"] == "2026-08" and x["n_meses"] == 20
    )  # fixture starts 2025-01
    assert x["meses"][-1] == {
        "mes": "2026-08",
        "precio_dataset": 508.0,
        "precio_usd_m3": 508.0,
        "precio_usd_mil_m3": 508000.0,
        "provisorio": True,
        "produccion_m3": 3000000.0,
        "regalias_usd": 180000000.0,
    }
    assert (
        x["meses"][-3]["provisorio"] is False
        and x["resumen"]["ultimo"] == 508.0
        and x["resumen"]["max"] == 512.0
    )
    assert "Río Negro" in x["regiones_disponibles"] and r["cita"]["tabla"] == "precios"
    g = H.ejecutar(
        d,
        "precios",
        {
            "producto": "gas",
            "region": "golfo de san jorge",
            "segmento": "expo",
            "contrato": "firme",
            "desde": "2026-07",
            "hasta": "2026-08",
        },
    )["datos"]
    assert g["region"] == "Golfo de San Jorge" and g["mmbtu_por_mil_m3"] == pytest.approx(36.9, abs=0.01)
    if d.fuente == "parquet":
        assert [m["mes"] for m in g["meses"]] == ["2026-07", "2026-08"]
        assert g["meses"][-1]["precio_dataset"] == pytest.approx(4.5 + 0.08 + 0.7)
    else:
        assert g["meses"] == []  # the firme contract is cut from the snapshot (ADR-034)
    with pytest.raises(H.ErrorHerramienta, match="producto"):
        H.ejecutar(d, "precios", {"producto": "agua"})
    with pytest.raises(H.ErrorHerramienta, match="YYYY-MM"):
        H.ejecutar(d, "precios", {"producto": "gas", "desde": "ayer"})
    with pytest.raises(H.ErrorHerramienta, match="Chubut"):
        H.ejecutar(d, "precios", {"producto": "petroleo", "region": "Marte"})
    defs = {t["name"]: t for t in H.definiciones()}
    assert "precios" in defs
    for nombre in (
        "curva_tipo",
        "comparar_mi_pozo",
        "comparar_mi_campania",
        "pronosticar_pozo",
        "simular_campania",
    ):
        schema = defs[nombre]["input_schema"]["properties"]["valorizar"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["modo"]["enum"] == ["historico", "flat", "ultimo"]


def test_sql_allowlist_knows_the_fourth_table(d_precios):
    d = d_precios
    r = H.sql_solo_lectura(d, "select producto, count(*) as n from precios group by 1 order by 1")
    assert {f["producto"] for f in r["datos"]["filas"]} == {"gas", "petroleo"}


# --- the views and the MCP server -----------------------------------------------------------------------------------------


def test_views_carry_the_usd_switch_only_where_it_belongs():
    for archivo in ("curva_mia.html", "simulador_campania.html"):
        doc = APPS.html(archivo)
        assert (
            'data-u="usd"' in doc and "van_usd" in doc and "sin_dato_porque" in doc and ".conmutador" in doc
        )
    assert "valorizar" in APPS.html("simulador_campania.html")  # the form sends it on the re-run
    for archivo in ("mapa_vecinos.html", "ranking_posicion.html"):
        assert 'data-u="usd"' not in APPS.html(archivo)


def test_mcp_server_exposes_precios_and_valorizar(raiz_precios):
    import asyncio

    from mcp.shared.memory import create_connected_server_and_client_session as connect

    import mcp_server

    srv = mcp_server.construir(D.abrir(raiz_precios, "parquet"), con_sql=False)

    async def go():
        async with connect(srv._mcp_server) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert "precios" in tools and "valorizar" in tools["simular_campania"].inputSchema["properties"]
            r = await c.call_tool("precios", {"producto": "gas", "desde": "2026-08"})
            env = json.loads(r.content[0].text)
            assert env["cita"]["tabla"] == "precios" and env["datos"]["meses"][0]["mes"] == "2026-08"
            r = await c.call_tool("curva_tipo", {**CURVA, "valorizar": {"modo": "ultimo"}})
            env = json.loads(r.content[0].text)
            assert env["datos"]["usd"]["p50"]["total"]["van_usd"] > 0

    asyncio.run(go())


def test_mock_agent_answers_money_questions_with_the_price_citation(d_precios):
    d = d_precios
    r = A.responder(
        "Simulá una campaña de 3 pozos en Vaca Muerta cohorte 2024 y decime cuánto vale en dólares neto de regalías",
        d,
        A.ProveedorMock(),
    )
    assert r.llamadas[0].herramienta == "simular_campania"
    assert r.llamadas[0].entrada["valorizar"] == {"modo": "ultimo", "regalia": 0.12}
    assert r.validacion is not None and r.validacion.ok and "USD p50" in r.texto and "[precios:" in r.texto
    p = A.responder("¿A cuánto está el precio del gas?", d, A.ProveedorMock())
    assert p.llamadas[0].herramienta == "precios" and p.llamadas[0].entrada == {"producto": "gas"}
    assert p.validacion is not None and p.validacion.ok and "USD/MMBTU" in p.texto
    assert "precios" in A.SYSTEM and "BRUTO" in A.SYSTEM
