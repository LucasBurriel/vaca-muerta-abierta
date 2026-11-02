"""F4: the data layer (Parquet and JSON), every tool with its citation, the validator, the mock agent loop,
the opt-in SQL allowlist, and the tool docs contract. No network, no model, no real data."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from vma import curvas as C
from vma import indicadores as I
from vma import master as M
from vma import site as S
from vma.consulta import agente as A
from vma.consulta import datos as D
from vma.consulta import herramientas as H
from vma.consulta import validador as V

ROOT = Path(__file__).resolve().parents[1]

# --- synthetic tables ----------------------------------------------------------------------------------------------
# 14 in-scope Vaca Muerta wells (two operators, two cohorts, two windows) + 1 Lajas + 1 out of scope.

WELLS = []
for i in range(16):
    op = "OPERADORA A" if i % 3 else "OPERADORA B"
    coh = 2024 if i < 8 else 2023
    ventana = "gas" if i in (6, 7) else "petroleo"
    WELLS.append(
        {
            "i": i,
            "sigla": f"OP.Nq.VM-{100 + i}(h)",
            "sigla_clave": f"OP.NQ.VM-{100 + i}(H)",
            "operadora": op,
            "formacion": "Vaca Muerta" if i < 14 else ("Lajas" if i == 14 else "Comodoro Rivadavia"),
            "cuenca": "NEUQUINA" if i < 15 else "GOLFO SAN JORGE",
            "en_alcance": i < 15,
            "cohorte": coh,
            "ventana": ventana,
            "rama_m": None if i in (3, 11) else 2000.0 + 100 * i,
            "etapas": None if i == 3 else 30 + i,
            "ip90": 100.0 + 10 * i,
            "flags": "sin_rama_sin_fractura" if i in (3, 11) else ("outlier_ip90_m_bajo" if i == 5 else ""),
            "outlier": True if i == 5 else (False if i < 15 else None),
        }
    )


def _master() -> pd.DataFrame:
    rows = []
    for w in WELLS:
        rows.append(
            {
                "sigla": w["sigla"],
                "sigla_clave": w["sigla_clave"],
                "alias_sigla": w["sigla"],
                "idpozos": str(1000 + w["i"]),
                "n_idpozo": 1,
                "idpozo_principal": 1000 + w["i"],
                "operadora": w["operadora"],
                "formacion_principal": w["formacion"],
                "area": "AREA X",
                "cuenca": w["cuenca"],
                "tipo_recurso": "NO CONVENCIONAL",
                "sub_tipo_recurso": "SHALE",
                "tipo_pozo": "Petrolífero",
                "estado": "Extracción Efectiva",
                "longitud": -68.5 + w["i"] * 0.01,
                "latitud": -38.2,
                "primera_produccion": pd.Timestamp(f"{w['cohorte']}-03-01"),
                "ultima_produccion": pd.Timestamp("2026-09-01"),
                "rama_m": w["rama_m"],
                "etapas": w["etapas"],
                "flags": w["flags"],
                "linaje": "operadora=produccion_nc 2026-09",
                "fecha_descarga": "2026-10-30",
                "version_alias": "2026-10-31",
            }
        )
    m = pd.DataFrame(rows)
    for c in M.COLUMNS:
        if c not in m:
            m[c] = None
    return m[M.COLUMNS]


def _ind() -> pd.DataFrame:
    rows = []
    for w in WELLS:
        por_m = w["ip90"] / w["rama_m"] if w["rama_m"] else None
        rows.append(
            {
                "sigla": w["sigla"],
                "sigla_clave": w["sigla_clave"],
                "operadora": w["operadora"],
                "formacion": w["formacion"],
                "area": "AREA X",
                "cuenca": w["cuenca"],
                "en_alcance": w["en_alcance"],
                "cohorte": w["cohorte"],
                "ventana": w["ventana"],
                "ventana_fuente": "gor12",
                "rama_m": w["rama_m"],
                "rama_normalizable": w["rama_m"] is not None,
                "etapas": w["etapas"],
                "etapas_por_100m": (w["etapas"] / w["rama_m"] * 100)
                if (w["rama_m"] and w["etapas"])
                else None,
                "dias_efectivos_total": 400.0,
                "ip90_petroleo_m3_d": w["ip90"],
                "ip90_equivalente_m3_d": w["ip90"] * 1.1,
                "ip90_petroleo_m3_d_por_m": por_m,
                "ip90_equivalente_m3_d_por_m": por_m * 1.1 if por_m else None,
                "acum12_petroleo_m3_por_m": por_m * 300 if por_m else None,
                "gor12_m3_m3": 150.0 if w["ventana"] == "petroleo" else 5000.0,
                "corte_agua12": 0.12,
                "outlier_ip90_m": w["outlier"],
                "flags": w["flags"] + ("" if w["en_alcance"] else "|fuera_alcance|outlier_no_evaluado"),
                "linaje": "maestro 2026-10-31; ip por dias efectivos",
                "fecha_descarga": "2026-10-30",
                "version_maestro": "2026-10-31",
            }
        )
    d = pd.DataFrame(rows)
    for c in I.COLUMNS:
        if c not in d:
            d[c] = None
    return d[I.COLUMNS]


def _curvas() -> pd.DataFrame:
    rows = []
    for inc in (True, False):
        for nivel in S.NIVELES:
            for mes in range(0, 70):
                n = 8 if mes < 65 else 3
                rows.append(
                    {
                        "nivel": nivel,
                        "cohorte": 2024,
                        "formacion": "Vaca Muerta",
                        "ventana": "petroleo" if nivel.endswith("ventana") else None,
                        "operadora": "OPERADORA A" if nivel.endswith("operadora") else None,
                        "incluye_outliers": inc,
                        "mes": mes,
                        "n_pozos": n,
                        "n_pozos_por_m": n,
                        "publicable": n >= 5,
                        **{
                            f"{r}_{s}": (
                                100.0 / (mes + 1) * (1.5 if s == "p10" else 0.5 if s == "p90" else 1.0)
                            )
                            if n >= 5
                            else None
                            for r in C.RATES + C.RATES_M
                            for s in C.STATS
                        },
                        "fecha_descarga": "2026-10-30",
                        "version_maestro": "2026-10-31",
                    }
                )
    c = pd.DataFrame(rows)
    for col in C.COLUMNS:
        if col not in c:
            c[col] = None
    return c[C.COLUMNS]


MANIFEST = {
    "generated_at": "2026-10-31T00:16:47+00:00",
    "sources": [
        {
            "key": "produccion_nc",
            "file": "produccion_nc.csv",
            "bytes": 10,
            "sha256": "ab" * 32,
            "ckan_last_modified": "2026-10-22",
            "url": "https://example.invalid/x.csv",
            "license": "CC-BY-4.0",
        }
    ],
}


@pytest.fixture(scope="module")
def raiz(tmp_path_factory) -> Path:
    """A fake repo root with both sources: data/publicado/<date>/*.parquet and site/data/*.json."""
    root = tmp_path_factory.mktemp("repo")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    for name, df in (("pozos", _master()), ("indicadores", _ind()), ("curvas_tipo", _curvas())):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    S.build_site_data(
        root / "site" / "data", _master(), _ind(), _curvas(), MANIFEST, "2026-10-31", today=date(2026, 10, 31)
    )
    return root


@pytest.fixture(params=["parquet", "json"])
def d(raiz, request) -> D.Datos:
    return D.abrir(raiz, request.param)


def _cita_ok(r: dict) -> None:
    assert set(r) >= {"datos", "cita", "exclusiones", "notas", "fecha_datos", "version_maestro", "fuente"}
    assert set(r["cita"]) == {"tabla", "columnas", "filtros", "regla_doc"}
    assert r["cita"]["tabla"] and r["cita"]["columnas"] and r["cita"]["regla_doc"]
    assert r["fecha_datos"] == "2026-10-30" and r["version_maestro"] == "2026-10-31"
    json.dumps(r, allow_nan=False)  # JSON-safe, no NaN


# --- data layer -----------------------------------------------------------------------------------------------------


def test_abrir_auto_prefers_parquet_and_falls_back_to_json(raiz, tmp_path):
    assert D.abrir(raiz).fuente == "parquet"
    solo_json = tmp_path / "clon"
    (solo_json / "site").mkdir(parents=True)
    (solo_json / "site" / "data").symlink_to(
        raiz / "site" / "data", target_is_directory=True
    ) if False else None
    import shutil

    shutil.copytree(raiz / "site" / "data", solo_json / "site" / "data")
    assert D.abrir(solo_json).fuente == "json"
    with pytest.raises(FileNotFoundError):
        D.abrir(solo_json, "parquet")
    with pytest.raises(FileNotFoundError):
        D.abrir(tmp_path / "vacio")


def test_same_views_on_both_sources(d):
    assert {t for t in D.TABLAS} == {"pozos", "indicadores", "curvas_tipo"}
    assert d.n_filas("pozos") == 16 and d.n_filas("indicadores") == 16
    assert d.tiene("indicadores", "ip90_petroleo_m3_d_por_m")
    if d.fuente == "parquet":
        assert d.faltantes("pozos", ["linaje", "alias_sigla"]) == []
        assert d.tiene("curvas_tipo", "petroleo_m3_d_media")
    else:
        assert d.faltantes("pozos", ["linaje", "alias_sigla"]) == ["linaje", "alias_sigla"]
        assert not d.tiene("curvas_tipo", "petroleo_m3_d_media")  # the snapshot ships percentiles only
        assert d.n_filas("curvas_tipo") == 2 * 3 * 61  # month 60 cut (ADR-023)


# --- tools ----------------------------------------------------------------------------------------------------------


def test_metadatos(d):
    r = H.metadatos(d)
    _cita_ok(r)
    assert r["datos"]["tablas"]["indicadores"]["filas"] == 16
    assert r["datos"]["manifiesto"][0]["sha256"] == "ab" * 32
    assert r["datos"]["fuente"] == d.fuente


def test_describir_tabla(d):
    r = H.describir_tabla(d, "indicadores")
    _cita_ok(r)
    nombres = {c["nombre"] for c in r["datos"]["columnas"]}
    assert "ip90_petroleo_m3_d_por_m" in nombres and "flags" in nombres
    assert "ip90_petroleo_m3_d_por_m" in r["datos"]["metricas_agregables"]
    with pytest.raises(H.ErrorHerramienta):
        H.describir_tabla(d, "pozos_claves")


def test_buscar_pozo_levels(d):
    r = H.buscar_pozo(d, "op.nq.vm-105(h)")  # L2: case + spaces
    _cita_ok(r)
    assert r["datos"]["pozos"][0]["sigla_clave"] == "OP.NQ.VM-105(H)"
    assert r["datos"]["pozos"][0]["nivel_coincidencia"] == "L2"
    assert H.buscar_pozo(d, "OP.Nq.VM-105")["datos"]["pozos"][0]["nivel_coincidencia"] == "L3"  # no (h)
    assert H.buscar_pozo(d, "opnqvm105")["datos"]["pozos"][0]["nivel_coincidencia"] == "L4"  # alnum only
    sub = H.buscar_pozo(d, "VM-10")
    assert sub["datos"]["n"] == 10 and all(
        p["nivel_coincidencia"] == "subcadena" for p in sub["datos"]["pozos"]
    )
    nada = H.buscar_pozo(d, "ZZZ.XX.YY-1")
    assert nada["datos"]["n"] == 0 and any("ningún pozo" in n for n in nada["notas"])
    with pytest.raises(H.ErrorHerramienta):
        H.buscar_pozo(d, "ab")


def test_ficha_pozo_explains_every_null(d):
    r = H.ficha_pozo(d, "op.nq.vm-103(h)")  # the well without a lateral
    _cita_ok(r)
    i = r["datos"]["indicadores"]
    assert i["rama_m"] is None and i["ip90_petroleo_m3_d_por_m"] is None and i["ip90_petroleo_m3_d"] == 130
    sin = r["datos"]["sin_dato_porque"]
    assert "sin_rama_sin_fractura" in sin["ip90_petroleo_m3_d_por_m"]
    assert "sin_rama_sin_fractura" in sin["rama_m"]
    assert "ip90_petroleo_m3_d" not in sin  # it has a value
    assert "sin_rama_sin_fractura" in r["datos"]["flags"]
    full = H.ficha_pozo(d, "OP.NQ.VM-105(H)")
    assert any("outlier" in n for n in full["notas"])
    with pytest.raises(H.ErrorHerramienta):
        H.ficha_pozo(d, "OP.NQ.NADA-1(H)")


def test_comparar_grupo_medians_n_and_exclusions(d):
    r = H.comparar_grupo(
        d, "vaca muerta", cohorte=2024, dimension="operadora", metrica="ip90_petroleo_m3_d", n_min=2
    )
    _cita_ok(r)
    assert r["cita"]["filtros"]["formacion"] == "Vaca Muerta"  # loose spelling resolved
    grupos = {g["grupo"]: g for g in r["datos"]["grupos"]}
    # cohort 2024 = wells 0..7; B = i % 3 == 0 -> 0, 3, 6 ; A = 1,2,4,5,7
    assert grupos["OPERADORA A"]["n_pozos"] == 5 and grupos["OPERADORA B"]["n_pozos"] == 3
    assert grupos["OPERADORA A"]["mediana"] == 140 and grupos["OPERADORA B"]["mediana"] == 130
    assert r["datos"]["n_pozos_filtrados"] == 8 and r["datos"]["n_con_dato"] == 8
    # per metre: well 3 has no lateral -> counted with its reason, not as zero
    pm = H.comparar_grupo(d, "Vaca Muerta", cohorte=2024, metrica="ip90_petroleo_m3_d_por_m", n_min=2)
    assert pm["datos"]["n_con_dato"] == 7 and pm["datos"]["sin_dato_porque"] == {
        "flags sin_rama_sin_fractura": 1
    }
    assert any("500 m" in n for n in pm["notas"])
    # n_min: with the default 5, OPERADORA B (3 wells) goes to grupos_chicos with null statistics
    chico = H.comparar_grupo(d, "Vaca Muerta", cohorte=2024, metrica="ip90_petroleo_m3_d")
    assert [g["grupo"] for g in chico["datos"]["grupos_chicos"]] == ["OPERADORA B"]
    assert chico["datos"]["grupos_chicos"][0]["mediana"] is None and chico["exclusiones"]
    # excluding outliers removes well 5 and says so
    sin_out = H.comparar_grupo(
        d, "Vaca Muerta", cohorte=2024, metrica="ip90_petroleo_m3_d", n_min=2, incluye_outliers=False
    )
    assert {g["grupo"]: g["n_pozos"] for g in sin_out["datos"]["grupos"]}["OPERADORA A"] == 4
    assert any("ADR-018" in e for e in sin_out["exclusiones"])
    with pytest.raises(H.ErrorHerramienta):
        H.comparar_grupo(d, "Formación Inventada")
    with pytest.raises(H.ErrorHerramienta):
        H.comparar_grupo(d, "Vaca Muerta", metrica="sigla")  # not an aggregable metric
    with pytest.raises(H.ErrorHerramienta):
        H.comparar_grupo(d, "Vaca Muerta", dimension="linaje")


def test_ranking_orders_and_warns(d):
    r = H.ranking(
        d, metrica="ip90_petroleo_m3_d", filtros={"formacion": "Vaca Muerta", "ventana": "petroleo"}, n_min=2
    )
    _cita_ok(r)
    rk = r["datos"]["ranking"]
    assert [g["grupo"] for g in rk] == ["OPERADORA A", "OPERADORA B"] and rk[0][
        "puesto"
    ] == 1  # medians 165 vs 160
    assert rk[0]["mediana"] > rk[1]["mediana"]
    asc = H.ranking(
        d, metrica="ip90_petroleo_m3_d", filtros={"formacion": "Vaca Muerta"}, n_min=2, orden="asc"
    )
    assert asc["datos"]["ranking"][0]["mediana"] <= asc["datos"]["ranking"][-1]["mediana"]
    assert any("mezcla ventanas" in n for n in asc["notas"])
    assert not any("mezcla ventanas" in n for n in r["notas"])
    por_coh = H.ranking(d, metrica="rama_m", por="cohorte", filtros={"formacion": "Vaca Muerta"}, n_min=2)
    assert {g["grupo"] for g in por_coh["datos"]["ranking"]} == {2023, 2024}
    with pytest.raises(H.ErrorHerramienta):
        H.ranking(d, filtros={"operadora": "NO EXISTE S.A."})
    with pytest.raises(H.ErrorHerramienta):
        H.ranking(d, filtros={"sigla": "x"})
    with pytest.raises(H.ErrorHerramienta):
        H.ranking(d, filtros={"ventana": "agua"})


def test_curva_tipo_months_and_small_n(d):
    r = H.curva_tipo(d, "cohorte_formacion", {"cohorte": 2024, "formacion": "vaca muerta"}, mes_max=3)
    _cita_ok(r)
    meses = r["datos"]["meses"]
    assert [m["mes"] for m in meses] == [0, 1, 2, 3]
    assert (
        meses[0]["p50"] == 100
        and meses[0]["p10"] == 150
        and meses[0]["p90"] == 50
        and meses[0]["n_pozos"] == 8
    )
    assert ("media" in meses[0]) == (d.fuente == "parquet")
    assert any("día efectivo" in n for n in r["notas"])
    # months 65..69 have 3 wells: null statistics with the reason (Parquet keeps them; the snapshot stops at 60)
    if d.fuente == "parquet":
        largo = H.curva_tipo(
            d, "cohorte_formacion", {"cohorte": 2024, "formacion": "Vaca Muerta"}, mes_max=69
        )
        ult = largo["datos"]["meses"][-1]
        assert ult["p50"] is None and "ADR-017" in ult["sin_dato_porque"] and largo["exclusiones"]
    v = H.curva_tipo(
        d,
        "cohorte_formacion_ventana",
        {"cohorte": 2024, "formacion": "Vaca Muerta", "ventana": "petroleo"},
        mes_max=1,
    )
    assert v["cita"]["filtros"]["ventana"] == "petroleo" and len(v["datos"]["meses"]) == 2
    o = H.curva_tipo(
        d,
        "cohorte_formacion_operadora",
        {"cohorte": 2024, "formacion": "Vaca Muerta", "operadora": "operadora a"},
        tasa="petroleo_m3_d_por_m",
        mes_max=0,
    )
    assert o["cita"]["filtros"]["operadora"] == "OPERADORA A"
    vacio = H.curva_tipo(d, "cohorte_formacion", {"cohorte": 2010, "formacion": "Vaca Muerta"})
    assert vacio["datos"]["n_meses"] == 0 and any("ningún mes" in n for n in vacio["notas"])
    with pytest.raises(H.ErrorHerramienta):
        H.curva_tipo(d, "cohorte_formacion_ventana", {"cohorte": 2024, "formacion": "Vaca Muerta"})
    with pytest.raises(H.ErrorHerramienta):
        H.curva_tipo(d, "otro_nivel", {"cohorte": 2024, "formacion": "Vaca Muerta"})


def test_every_tool_result_carries_a_citation(d):
    llamadas = [
        ("metadatos", {}),
        ("describir_tabla", {"tabla": "curvas_tipo"}),
        ("buscar_pozo", {"texto": "VM-101"}),
        ("ficha_pozo", {"sigla_clave": "OP.NQ.VM-101(H)"}),
        ("comparar_grupo", {"formacion": "Vaca Muerta", "n_min": 1}),
        ("ranking", {"n_min": 1}),
        (
            "curva_tipo",
            {
                "nivel": "cohorte_formacion",
                "claves": {"cohorte": 2024, "formacion": "Vaca Muerta"},
                "mes_max": 2,
            },
        ),
        # F5: the user's wells (the committed synthetic fixture, cohorts 2022-2024; the fake curves are 2024 only)
        (
            "cargar_mis_pozos",
            {
                "ruta": str(ROOT / "tests" / "fixtures" / "sintetico" / "mis_pozos_produccion.csv"),
                "ruta_pozos": str(ROOT / "tests" / "fixtures" / "sintetico" / "mis_pozos_atributos.csv"),
            },
        ),
        ("comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 3}),
        ("comparar_mi_campania", {"filtros": {"cohorte": 2024}, "metrica": "ip90_petroleo_m3_d"}),
        ("brechas", {"filtros": {"cohorte": 2024}, "mes_max": 3}),
    ]
    assert {n for n, _ in llamadas} == set(H.HERRAMIENTAS)
    for nombre, entrada in llamadas:
        r = H.ejecutar(d, nombre, entrada)
        _cita_ok(r)
        assert r["fuente"] == d.fuente
    d.propios = None
    with pytest.raises(H.ErrorHerramienta):
        H.ejecutar(d, "sql_solo_lectura", {"sql": "select 1"})  # not exposed without con_sql
    with pytest.raises(H.ErrorHerramienta):
        H.ejecutar(d, "ranking", {"metrica": "rama_m", "inventado": 1})
    with pytest.raises(H.ErrorHerramienta):
        H.ejecutar(d, "borrar_todo", {})


def test_definitions_are_strict_schemas():
    defs = H.definiciones()
    assert [t["name"] for t in defs] == list(H.HERRAMIENTAS)
    for t in defs:
        assert t["strict"] is True and t["description"]
        assert t["input_schema"]["additionalProperties"] is False and "required" in t["input_schema"]
    assert "sql_solo_lectura" in {t["name"] for t in H.definiciones(con_sql=True)}


# --- opt-in SQL ---------------------------------------------------------------------------------------------------------


def test_sql_solo_lectura_allowlist(d):
    r = H.sql_solo_lectura(
        d, "select operadora, count(*) as n from indicadores where en_alcance group by 1 order by 2 desc"
    )
    _cita_ok(r)
    assert r["datos"]["filas"][0] == {"operadora": "OPERADORA A", "n": 10}
    assert r["cita"]["filtros"]["sql"].startswith("select operadora")
    cte = H.sql_solo_lectura(
        d,
        "with vm as (select * from indicadores where formacion = 'Vaca Muerta') select count(*) as n from vm",
    )
    assert cte["datos"]["filas"] == [{"n": 14}]
    assert H.sql_solo_lectura(d, "select sigla from pozos", limite=3)["datos"]["n"] == 3
    for malo in (
        "drop table pozos",
        "select 1; select 2",
        "select * from read_parquet('x.parquet')",
        "select * from pozos_claves",
        "select * from information_schema.tables",
        "copy pozos to 'x.csv'",
        "select getenv('HOME')",
        "insert into pozos values (1)",
        "select * from pozos join indicadores using (sigla_clave) join otra using (x)",
    ):
        with pytest.raises(H.ErrorHerramienta):
            H.sql_solo_lectura(d, malo)
    with pytest.raises(H.ErrorHerramienta, match="DuckDB"):
        H.sql_solo_lectura(d, "select columna_que_no_existe from pozos")


# --- validator ------------------------------------------------------------------------------------------------------------


RESULTADO = {
    "datos": {
        "grupos": [
            {"grupo": "OPERADORA A", "mediana": 0.06231, "n_pozos": 48},
            {"grupo": "B", "mediana": 1206.0},
        ]
    },
    "cita": {
        "tabla": "indicadores",
        "columnas": ["ip90_petroleo_m3_d_por_m"],
        "filtros": {"cohorte": 2024},
        "regla_doc": "x",
    },
    "fecha_datos": "2026-10-30",
    "version_maestro": "2026-10-31",
    "fuente": "parquet",
    "notas": ["corte_agua12 0.09"],
    "exclusiones": [],
}


def test_validador_accepts_cited_numbers_in_any_format():
    texto = (
        "La mediana de OPERADORA A es 0,062 m³/d por m (n = 48) y la de B es 1.206 m; también 0.0623 y 1,206. "
        "Cohorte 2024, datos del 2026-10-30, maestro 2026-10-31. El corte de agua es 9 %. IP90, ADR-016 y P50 no cuentan."
    )
    v = V.validar(texto, [RESULTADO])
    assert v.ok, v.sin_cita
    assert v.n_numeros >= 8


def test_validador_rejects_uncited_numbers_and_tolerates_rounding():
    v = V.validar("La mediana es 0,062 y el total 5.432 pozos.", [RESULTADO])
    assert not v.ok and v.sin_cita == ["5.432"]
    assert "número sin cita" in v.mensaje() and "5.432" in v.mensaje()
    assert V.validar("Son 0,0623 (redondeo de 0.06231).", [RESULTADO]).ok
    assert not V.validar("Son 0,0650.", [RESULTADO]).ok  # 4 % off is not rounding
    assert not V.validar("Fecha 2025-01-01.", [RESULTADO]).ok  # a date no result carries
    assert V.validar("Los 3 grupos, el 2do y 10 filas.", [RESULTADO]).ok  # small integers are free
    assert not V.validar("Hay 11 grupos.", [RESULTADO]).ok


def test_validador_allows_question_and_tool_inputs():
    assert V.validar("Para la cohorte 2019 no hay curva.", [RESULTADO], permitidos=["curva de 2019"]).ok
    assert not V.validar("Para la cohorte 2019 no hay curva.", [RESULTADO]).ok
    assert V.validar("Filtré rama >= 500 m.", [], permitidos=['{"rama_min": 500}']).ok


def test_candidatos():
    assert V._candidatos("1.206") == [1.206, 1206.0]
    assert V._candidatos("1,206") == [1.206, 1206.0]
    assert V._candidatos("1.234.567") == [1234567.0]
    assert V._candidatos("1.234,5") == [1234.5]
    assert V._candidatos("1,234.5") == [1234.5]
    assert V._candidatos("0,045") == [0.045]
    assert V._candidatos("-3.5") == [-3.5]
    assert [t for t, _ in V.numeros_en_texto("IP90 de 12.5 m3 en acum12, P50 y ADR-016 el 2024-01-01")] == [
        "12.5"
    ]


# --- the loop, with the mock provider ----------------------------------------------------------------------------------


def test_mock_agent_answers_with_citations_and_passes_validation(d):
    r = A.responder(
        "¿Qué operadora tiene el mejor IP90 por metro en Vaca Muerta, ventana de petróleo, cohorte 2024?",
        d,
        A.ProveedorMock(),
    )
    assert r.llamadas and r.llamadas[0].herramienta == "ranking"
    assert r.llamadas[0].entrada["filtros"] == {
        "formacion": "Vaca Muerta",
        "ventana": "petroleo",
        "cohorte": 2024,
    }
    assert r.validacion is not None and r.validacion.ok and r.reintentos == 0
    assert "indicadores" in r.texto and "Datos: descargados el 2026-10-30" in r.texto
    assert r.transcript()["herramientas"][0]["herramienta"] == "ranking"


def test_mock_agent_well_flow_and_sin_dato(d):
    r = A.responder("ficha del pozo OP.Nq.VM-103(h)", d, A.ProveedorMock())
    assert [c.herramienta for c in r.llamadas] == ["buscar_pozo", "ficha_pozo"]
    assert "Sin dato porque" in r.texto and "sin_rama_sin_fractura" in r.texto
    assert r.validacion.ok


def test_validator_retry_path(d):
    r = A.responder("curva tipo de Vaca Muerta 2024", d, A.ProveedorMock(con_numero_inventado=True))
    assert r.reintentos == 1 and r.validacion.ok and "123456" not in r.texto
    r2 = A.responder(
        "curva tipo de Vaca Muerta 2024",
        d,
        A.ProveedorMock(con_numero_inventado=True),
        reintentos_validador=0,
    )
    assert (
        r2.reintentos == 0
        and not r2.validacion.ok
        and r2.texto.startswith("ATENCION, número sin cita (123456,7)")
    )


def test_tool_errors_are_returned_to_the_model_not_raised(d):
    class Proveedor:
        nombre = modelo = "guion"
        paso = 0

        def crear(self, system, messages, tools):
            self.paso += 1
            if self.paso == 1:
                return {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "ranking",
                            "input": {"filtros": {"formacion": "Nada"}},
                        }
                    ],
                    "stop_reason": "tool_use",
                }
            ultimo = messages[-1]["content"][0]
            assert (
                ultimo["type"] == "tool_result"
                and ultimo["is_error"] is True
                and "no existe" in ultimo["content"]
            )
            return {
                "content": [{"type": "text", "text": "La formación no existe en la tabla."}],
                "stop_reason": "end_turn",
            }

    r = A.responder("ranking de Nada", d, Proveedor())
    assert r.llamadas[0].error and r.validacion.ok and r.texto == "La formación no existe en la tabla."


def test_chat_history_is_extended_in_place(d):
    hist: list[dict] = []
    A.responder("qué tablas hay", d, A.ProveedorMock(), historial=hist)
    n = len(hist)
    A.responder("describí la tabla curvas_tipo", d, A.ProveedorMock(), historial=hist)
    assert len(hist) > n and hist[0]["role"] == "user" and hist[-1]["role"] == "assistant"


def test_elegir_proveedor(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(A.elegir_proveedor("auto"), A.ProveedorMock)
    assert A.elegir_proveedor("mock-sin-cita").con_numero_inventado is True
    with pytest.raises(ValueError):
        A.elegir_proveedor("gpt")


def test_cli_mock_json(raiz, capsys):
    import agente

    code = agente.main(
        [
            "--proveedor",
            "mock",
            "--fuente",
            "json",
            "--datos",
            str(raiz),
            "--json",
            "ranking de rama en Vaca Muerta",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["proveedor"] == "mock" and out["herramientas"][0]["herramienta"] == "ranking"
    assert out["validacion"].startswith("ok")


# --- docs contract -------------------------------------------------------------------------------------------------------


def test_tools_are_documented():
    agente_md = (ROOT / "docs" / "agente.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for nombre in list(H.HERRAMIENTAS) + list(H.HERRAMIENTAS_OPT_IN):
        assert f"`{nombre}`" in agente_md, f"{nombre} missing in docs/agente.md"
        assert H.descripcion(nombre).split(".")[0][:25].strip() in agente_md.replace("\n", " "), nombre
    assert "mcp_server.py" in readme and "agente.py" in readme
    assert re.search(r"ADR-02[5-8]", (ROOT / "docs" / "decisiones.md").read_text(encoding="utf-8"))


def test_system_prompt_states_the_rules():
    s = A.SYSTEM
    for frase in ("Sin cita no hay número", "Sin dato porque", "día efectivo", "No inventás"):
        assert frase in s
    assert A.MODELO_DEFAULT == "claude-opus-5-5"
