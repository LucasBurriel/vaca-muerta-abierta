"""F5: MCP Apps (ADR-032). The protocol as a client sees it (in-memory session against the real server): tools
carry _meta.ui.resourceUri, the ui:// resources are listed and read with the mcp-app MIME type and a CSP that names
only the pinned CDN hosts, the tool results stay plain text (fallback), and the views are well-formed documents
that speak the ui/* methods. No network, no browser, no model."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
import test_consulta as TC

from vma import apps as APPS
from vma.consulta import datos as D

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "sintetico"


@pytest.fixture(scope="module")
def raiz(tmp_path_factory) -> Path:
    from datetime import date

    import duckdb

    from vma import site as SITE

    root = tmp_path_factory.mktemp("repo_apps")
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


def _server(raiz: Path, con_apps: bool = True):
    import mcp_server

    d = D.abrir(raiz, "parquet")
    return mcp_server.construir(d, con_sql=False, con_apps=con_apps)


def _run(coro):
    return asyncio.run(coro)


def test_views_are_documents_that_speak_the_protocol():
    assert set(APPS.VISTAS) == {
        "curva_mia.html",
        "mapa_vecinos.html",
        "ranking_posicion.html",
        "simulador_campania.html",
    }
    for archivo in APPS.VISTAS:
        doc = APPS.html(archivo)
        assert doc.lstrip().lower().startswith("<!doctype html>") and '<meta charset="utf-8">' in doc
        assert "<!--PUENTE-->" not in doc and "<!--BASE_CSS-->" not in doc
        for metodo in (
            "ui/initialize",
            "ui/notifications/initialized",
            "ui/notifications/tool-result",
            "ui/notifications/size-changed",
            "ui/resource-teardown",
        ):
            assert metodo in doc, (archivo, metodo)
        assert '"2026-01-26"' in doc
        # pinned CDN versions with integrity, the same as the static site (ADR-021)
        for src in re.findall(r'src="(https?://[^"]+)"', doc) + re.findall(r'href="(https?://[^"]+)"', doc):
            assert src.startswith("https://cdnjs.cloudflare.com/ajax/libs/"), src
            assert re.search(r"/\d+\.\d+\.\d+/", src), src
        assert doc.count("integrity=") == len(re.findall(r"<(?:script|link)[^>]+https://cdnjs", doc))
        assert APPS.uri(archivo).startswith("ui://vaca-muerta/")
    assert "tools/call" in APPS.html("simulador_campania.html")  # the simulator re-runs the tool
    assert "tile.openstreetmap.org" in APPS.html("mapa_vecinos.html")
    with pytest.raises(KeyError):
        APPS.html("otra.html")


def test_tool_meta_points_to_an_existing_resource():
    for archivo, v in APPS.VISTAS.items():
        m = APPS.tool_meta(v["tool"])
        assert m == {"ui": {"resourceUri": APPS.uri(archivo), "visibility": ["model", "app"]}}
    assert APPS.tool_meta("metadatos") is None
    for archivo in APPS.VISTAS:
        csp = APPS.resource_meta(archivo)["ui"]["csp"]
        assert "https://cdnjs.cloudflare.com" in csp["resourceDomains"] and csp["connectDomains"] == []
        if archivo == "mapa_vecinos.html":
            assert any("openstreetmap" in x for x in csp["resourceDomains"])
        else:
            assert not any("openstreetmap" in x for x in csp["resourceDomains"])


def test_protocol_as_a_client_sees_it(raiz):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    mcp = _server(raiz)

    async def go():
        async with connect(mcp._mcp_server) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert (
                "comparar_mi_pozo" in tools
                and "simular_campania" in tools
                and "vecinos_de_mis_pozos" in tools
            )
            for archivo, v in APPS.VISTAS.items():
                assert tools[v["tool"]].meta == {
                    "ui": {"resourceUri": APPS.uri(archivo), "visibility": ["model", "app"]}
                }
            assert tools["metadatos"].meta is None and tools["brechas"].meta is None
            res = (await c.list_resources()).resources
            uris = {str(r.uri): r for r in res}
            for archivo in APPS.VISTAS:
                r = uris[APPS.uri(archivo)]
                assert r.mimeType == APPS.MIME == "text/html;profile=mcp-app"
                assert r.title == APPS.VISTAS[archivo]["titulo"]
            rd = await c.read_resource(APPS.uri("curva_mia.html"))
            (c0,) = rd.contents
            assert c0.mimeType == APPS.MIME and c0.text.lstrip().lower().startswith("<!doctype html>")
            assert c0.meta == APPS.resource_meta("curva_mia.html")
            wire = rd.model_dump(by_alias=True, exclude_none=True)
            assert wire["contents"][0]["_meta"]["ui"]["csp"]["resourceDomains"] == [
                "https://cdnjs.cloudflare.com"
            ]
            # the tools still answer plain text (fallback for hosts without the extension)
            r = await c.call_tool(
                "cargar_mis_pozos",
                {
                    "ruta": str(FIX / "mis_pozos_produccion.csv"),
                    "ruta_pozos": str(FIX / "mis_pozos_atributos.csv"),
                },
            )
            env = json.loads(r.content[0].text)
            assert env["datos"]["n_pozos"] == 30 and env["cita"]["regla_doc"].startswith("docs/mis-datos.md")
            r = await c.call_tool("comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 3})
            env = json.loads(r.content[0].text)
            assert env["datos"]["grupo"]["cohorte"] == 2024 and r.content[0].type == "text"
            r = await c.call_tool("vecinos_de_mis_pozos", {"radio_km": 50, "metrica": "ip90_petroleo_m3_d"})
            env = json.loads(r.content[0].text)
            assert (
                env["datos"]["n_mios"] >= 1
                and "vecinos" in env["datos"]
                and env["cita"]["columnas"][0] == "longitud"
            )
            r = await c.call_tool(
                "simular_campania", {"formacion": "Vaca Muerta", "n_pozos": 3, "meses": 12, "n_sim": 20}
            )
            env = json.loads(r.content[0].text)
            assert len(env["datos"]["tasa_agregada"]["p50"]) == 12

    _run(go())


def test_without_apps_nothing_is_advertised(raiz):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    mcp = _server(raiz, con_apps=False)

    async def go():
        async with connect(mcp._mcp_server) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert all(t.meta is None for t in tools.values())
            assert (await c.list_resources()).resources == []

    _run(go())


def test_demo_host_is_generated_from_the_synthetic_data(tmp_path, monkeypatch, raiz):
    from vma.apps import demo

    monkeypatch.setattr(demo, "ROOT", raiz)
    host = demo.generar(tmp_path / "demo", fuente="parquet")
    assert host.exists()
    txt = host.read_text(encoding="utf-8")
    assert "ui/initialize" in txt and "ui/notifications/tool-result" in txt and "tools/call" in txt
    for archivo in APPS.VISTAS:
        assert (tmp_path / "demo" / archivo).exists()
        assert f'"{archivo}"' in txt
    resultados = json.loads(re.search(r"const RESULTADOS = (\{.*?\});\nconst SERVIR", txt, re.S).group(1))
    curva = json.loads(resultados["curva_mia.html"]["content"][0]["text"])
    assert curva["datos"]["pozo"]["sigla"] == "MIO-003"
    assert any("SINT" in n for n in curva["notas"])
    for archivo, r in resultados.items():
        assert r["isError"] is False, (archivo, r["content"][0]["text"][:200])


def test_docs_name_the_apps():
    doc = (ROOT / "docs" / "mcp-apps.md").read_text(encoding="utf-8")
    for archivo, v in APPS.VISTAS.items():
        assert APPS.uri(archivo) in doc and f"`{v['tool']}`" in doc
    for palabra in (
        "_meta.ui.resourceUri",
        "text/html;profile=mcp-app",
        "resourceDomains",
        "2026-01-26",
        "fallback",
    ):
        assert palabra in doc
    assert re.search(r"ADR-032", (ROOT / "docs" / "decisiones.md").read_text(encoding="utf-8"))
