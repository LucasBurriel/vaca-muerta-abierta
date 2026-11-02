"""F5 packaging: where the data comes from when the scripts are installed outside a clone (ADR-033), and the
mock planner on the F5 questions. No network: the snapshot download uses a fake opener."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from conftest import fake_opener_factory

from vma.consulta import agente as A
from vma.consulta import herramientas as H
from vma.consulta import ubicacion as U

ROOT = Path(__file__).resolve().parents[1]


def _snapshot_files() -> dict[str, bytes]:
    return {U.PAGES + n: json.dumps({"ok": n}).encode() for n in U.ARCHIVOS}


def test_resolution_order(tmp_path, monkeypatch):
    monkeypatch.delenv(U.ENV, raising=False)
    monkeypatch.setenv("VMA_CACHE", str(tmp_path / "cache"))
    clon = tmp_path / "clon"
    (clon / "site" / "data").mkdir(parents=True)
    (clon / "site" / "data" / "pozos.json").write_text("{}", encoding="utf-8")
    assert U.raiz_datos(Path("x"), clon) == Path("x")  # explicit wins
    monkeypatch.setenv(U.ENV, str(tmp_path / "env"))
    assert U.raiz_datos(None, clon) == tmp_path / "env"
    monkeypatch.delenv(U.ENV)
    assert U.raiz_datos(None, clon) == clon  # a clone
    # not a clone, empty cache, no download allowed -> a message that names the options
    with pytest.raises(FileNotFoundError, match="--datos"):
        U.raiz_datos(None, tmp_path / "site-packages", descargar=False)
    # not a clone -> download the snapshot into the cache, once
    opener = fake_opener_factory(_snapshot_files())
    logs: list[str] = []
    raiz = U.raiz_datos(None, tmp_path / "site-packages", opener=opener, log=logs.append)
    assert raiz == tmp_path / "cache" and (raiz / "site" / "data" / "pozos.json").exists()
    assert len(opener.calls) == len(U.ARCHIVOS) and any("sólo datos públicos" in x for x in logs)
    raiz2 = U.raiz_datos(None, tmp_path / "site-packages", opener=opener, log=logs.append)
    assert raiz2 == raiz and len(opener.calls) == len(U.ARCHIVOS)  # cached: nothing fetched again


def test_snapshot_download_rejects_non_json(tmp_path):
    files = _snapshot_files()
    files[U.PAGES + "pozos.json"] = b"<html>not json</html>"
    opener = fake_opener_factory(files)
    with pytest.raises(RuntimeError, match="no es JSON"):
        U.descargar_snapshot(tmp_path, opener=opener, log=lambda _: None)
    assert not (tmp_path / "site" / "data" / "pozos.json").exists()
    assert not list((tmp_path / "site" / "data").glob("*.part"))


def test_entry_points_and_extras():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["project"]["scripts"] == {
        "vma-mcp": "mcp_server:main",
        "vma-agente": "agente:main",
        "vma-pipeline": "pipeline:main",
    }
    assert set(cfg["project"]["optional-dependencies"]) >= {"dev", "mcp", "agente"}
    assert "mcp_server" in cfg["tool"]["setuptools"]["py-modules"]
    assert cfg["tool"]["setuptools"]["package-data"]["vma.apps"] == ["ui/*.html", "ui/*.js", "ui/*.css"]
    import agente
    import mcp_server

    assert callable(agente.main) and callable(mcp_server.main)


def test_mock_plans_the_f5_tools():
    tools = H.definiciones()
    plan = A.ProveedorMock._plan(
        "Cargá mis pozos de C:/datos/mios.csv y mis_pozos.parquet y compará mi pozo MIO-003", tools
    )
    assert plan == [
        ("cargar_mis_pozos", {"ruta": "C:/datos/mios.csv", "ruta_pozos": "mis_pozos.parquet"}),
        ("comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 12}),
    ]
    plan = A.ProveedorMock._plan("cómo está mi campaña PAD-B contra su grupo", tools)
    assert plan == [("comparar_mi_campania", {"filtros": {"campania": "PAD-B"}})]
    plan = A.ProveedorMock._plan("brecha de mi pozo MIO-011 contra el P50", tools)
    assert plan == [("brechas", {"mes_max": 12, "sigla": "MIO-011"})]
    plan = A.ProveedorMock._plan("pronóstico de EUR de mi pozo MIO-002", tools)
    assert plan == [("pronosticar_pozo", {"sigla": "MIO-002", "mio": True, "n_bootstrap": 100})]
    plan = A.ProveedorMock._plan(
        "Simulá una campaña de 12 pozos en Vaca Muerta, ventana de petróleo, cohorte 2022, con rama de 2800 m",
        tools,
    )
    assert plan == [
        (
            "simular_campania",
            {
                "formacion": "Vaca Muerta",
                "n_pozos": 12,
                "meses": 120,
                "n_sim": 300,
                "ventana": "petroleo",
                "cohorte_ref": 2022,
                "rama_m": 2800.0,
            },
        )
    ]
    # the F4 questions still plan as before
    assert A.ProveedorMock._plan("ranking de operadoras en Vaca Muerta 2024", tools)[0][0] == "ranking"
    assert A.ProveedorMock._plan("ficha del pozo YPF.Nq.LACh-125(h)", tools)[0][0] == "buscar_pozo"
