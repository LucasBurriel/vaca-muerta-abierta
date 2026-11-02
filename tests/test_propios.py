"""F5: the user's own wells. Schema and mapping, validation messages, indicators with the published rules, the
synthetic generator, the three comparisons against fake published tables, the tools' envelope on both sources.
No network, no model, no real data: the public side is the synthetic tables of test_consulta, the user side is
built here from the same monthly shape (p50 = 100 / (mes + 1)) so the expected percentiles are known."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import test_consulta as TC

from vma.consulta import datos as D
from vma.consulta import herramientas as H
from vma.propios import cargar as C
from vma.propios import comparar as K
from vma.propios import esquema as E
from vma.propios import sintetico as S

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "sintetico"


@pytest.fixture(params=["parquet", "json"])
def d(TC_raiz, request) -> D.Datos:
    return D.abrir(TC_raiz, request.param)


@pytest.fixture(scope="module")
def TC_raiz(tmp_path_factory) -> Path:
    """The same fake repo root test_consulta builds (16 wells, curves for cohort 2024 Vaca Muerta only)."""
    from datetime import date

    import duckdb

    from vma import site as SITE

    root = tmp_path_factory.mktemp("repo_propios")
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


def _mi_csv(tmp_path: Path, factor: float = 0.5, meses: int = 14, tef: float | None = 28.0, **cols) -> Path:
    """A user's well whose producing-day oil rate is ``factor`` × the fake curve's P50 (100 / (mes + 1)).
    ``tef`` 28 so no month (February included) caps it."""
    rows = []
    for k in range(meses):
        fecha = pd.Timestamp("2024-03-01") + pd.DateOffset(months=k)
        dias = tef if tef is not None else fecha.days_in_month
        rate = factor * 100.0 / (k + 1)
        rows.append(
            {
                "Pozo": "mio.nq.x-1(h)",
                "Periodo": fecha.strftime("%Y-%m"),
                "Oil (m3)": rate * dias,
                "Gas (km3)": rate * dias * 0.1,  # GOR 100 m3/m3: oil window
                "Agua": rate * dias * 0.2,
                **({"Dias": tef} if tef is not None else {}),
                "Rama": 2000,
                "Etapas": 40,
                "Formacion": "VACA MUERTA",
                "Pad": "PAD-1",
                **cols,
            }
        )
    p = tmp_path / "mios.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


# --- schema and validation ------------------------------------------------------------------------------------------


def test_aliases_and_explicit_mapping():
    m = E.resolver_mapeo(
        ["Pozo", "Periodo", "Oil (m3)", "Gas (km3)", "Agua", "Dias", "Rama"],
        {"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"},
    )
    assert m["sigla"] == "Pozo" and m["fecha"] == "Periodo" and m["tef"] == "Dias" and m["rama_m"] == "Rama"
    assert m["petroleo_m3"] == "Oil (m3)" and m["agua_m3"] == "Agua"
    assert E.resolver_mapeo(["SIGLA", "AÑO", "MES", "PROD_PET", "PROD_GAS", "Formación"]) == {
        "sigla": "SIGLA",
        "anio": "AÑO",
        "mes": "MES",
        "petroleo_m3": "PROD_PET",
        "gas_mil_m3": "PROD_GAS",
        "formacion": "Formación",
    }
    with pytest.raises(ValueError, match="no es una columna canónica"):
        E.resolver_mapeo(["a"], {"inventada": "a"})
    with pytest.raises(ValueError, match="no está en el archivo"):
        E.resolver_mapeo(["a"], {"sigla": "b"})


def test_validation_messages_name_what_is_missing():
    v = E.validar_columnas(["pozo", "fecha", "oil"])
    assert not v.ok
    assert any("gas_mil_m3" in e and "mapeo=" in e for e in v.errores)
    v = E.validar_columnas(["pozo", "oil", "gas"])
    assert any("falta el mes" in e for e in v.errores)
    v = E.validar_columnas(["pozo", "anio", "mes", "oil", "gas"])
    assert v.ok and any("tef" in a for a in v.avisos) and any("rama_m" in a for a in v.avisos)


def test_load_errors_are_readable(tmp_path):
    with pytest.raises(FileNotFoundError):
        C.cargar(tmp_path / "nada.csv")
    p = tmp_path / "x.csv"
    p.write_text("pozo,fecha,oil,gas\nA,no-es-fecha,1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fecha ilegible"):
        C.cargar(p)
    p.write_text("pozo,oil,gas\nA,1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="falta el mes"):
        C.cargar(p)
    (tmp_path / "x.xlsx").write_bytes(b"")
    with pytest.raises(ValueError, match="formato no soportado"):
        C.cargar(tmp_path / "x.xlsx")


# --- indicators with the published rules ------------------------------------------------------------------------------


def test_indicators_follow_published_rules(tmp_path):
    mis = C.cargar(
        _mi_csv(tmp_path, factor=1.0), mapeo={"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"}
    )
    assert mis.n_pozos == 1 and mis.siglas == ["MIO.NQ.X-1(H)"]
    i = mis.indicadores.iloc[0]
    assert i.cohorte == 2024 and i.formacion == "VACA MUERTA" and i.campania == "PAD-1"
    # first 90 producing days = months 0, 1, 2 at 30 days each: (100 + 50 + 33.33) * 30 / 90
    assert i.ip90_petroleo_m3_d == pytest.approx((100 + 50 + 100 / 3) * 28 / 90 + 100 / 4 * 6 / 90)
    assert i.ip90_petroleo_m3_d_por_m == pytest.approx(i.ip90_petroleo_m3_d / 2000)
    assert i.acum12_petroleo_m3 == pytest.approx(sum(100 / (k + 1) * 28 for k in range(12)))
    assert i.ventana == "petroleo" and i.ventana_fuente == "gor12"
    assert i.gor12_m3_m3 == pytest.approx(100.0)
    assert i.corte_agua12 == pytest.approx(0.2 / 1.2)
    assert i.etapas_por_100m == pytest.approx(2.0)
    assert "sin_tef_dias_calendario" not in i["flags"]
    assert mis.meta["sintetico"] is False and mis.meta["mapeo"]["tef"] == "Dias"


def test_without_tef_whole_month_counts_and_is_flagged(tmp_path):
    mis = C.cargar(_mi_csv(tmp_path, tef=None), mapeo={"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"})
    i = mis.indicadores.iloc[0]
    assert "sin_tef_dias_calendario" in i["flags"]
    assert any("sin 'tef'" in a for a in mis.meta["avisos"])
    assert mis.produccion.tef_d.iloc[0] == 31  # March 2024, calendar days


def test_short_lateral_and_declared_window(tmp_path):
    p = _mi_csv(tmp_path, Rama=300, Ventana="gas")
    mis = C.cargar(p, mapeo={"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"})
    i = mis.indicadores.iloc[0]
    assert "rama_corta" in i["flags"] and not i.rama_normalizable and pd.isna(i.ip90_petroleo_m3_d_por_m)
    assert i.ventana == "gas" and i.ventana_fuente == "declarada"


def test_duplicates_summed_and_two_files(tmp_path):
    prod = pd.DataFrame(
        {
            "sigla": ["A", "A", "A", "B"],
            "anio": [2024, 2024, 2024, 2024],
            "mes": [1, 1, 2, 1],
            "petroleo_m3": [10, 5, 20, 7],
            "gas_mil_m3": [1, 1, 2, 1],
            "tef": [31, 31, 29, 10],
        }
    )
    pozos = pd.DataFrame(
        {"sigla": ["A", "B", "C"], "rama_m": [2500, None, 2000], "campania": ["P1", "P2", "P3"]}
    )
    prod.to_csv(tmp_path / "p.csv", index=False)
    pozos.to_parquet(tmp_path / "w.parquet", index=False)
    mis = C.cargar(tmp_path / "p.csv", ruta_pozos=tmp_path / "w.parquet")
    assert mis.n_pozos == 2
    a = mis.produccion[mis.produccion.sigla == "A"]
    assert a.petroleo_m3.tolist() == [15, 20] and a.tef_d.tolist() == [31, 29]
    assert "produccion_suma_filas" in mis.indicadores.set_index("sigla").loc["A", "flags"]
    assert any("repetidas" in a for a in mis.meta["avisos"]) and any(
        "sin producción" in a for a in mis.meta["avisos"]
    )
    assert mis.pozos.set_index("sigla").loc["B", "campania"] == "P2"


# --- synthetic generator ----------------------------------------------------------------------------------------------


def test_synthetic_generator_is_noisy_renamed_and_marked():
    rng = np.random.default_rng(1)
    mensual = pd.concat(
        [
            pd.DataFrame(
                {
                    "sigla_clave": f"PUB-{i}",
                    "mes_fecha": pd.date_range("2023-01-01", periods=15, freq="MS"),
                    "petroleo_m3": 3000.0 / np.arange(1, 16),
                    "gas_mil_m3": 300.0 / np.arange(1, 16),
                    "agua_m3": 500.0,
                    "tef_d": 30.0,
                }
            )
            for i in range(6)
        ]
    )
    pozos = pd.DataFrame(
        {
            "sigla_clave": [f"PUB-{i}" for i in range(6)],
            "formacion": "Vaca Muerta",
            "cohorte": 2023,
            "rama_m": [2000.0 + 100 * i for i in range(6)],
            "etapas": [30 + i for i in range(6)],
            "longitud": -68.5,
            "latitud": -38.3,
        }
    )
    prod, out, receta = S.generar(mensual, pozos, n=4, semilla=3)
    assert (
        set(out.sigla) == {"MIO-001", "MIO-002", "MIO-003", "MIO-004"} and (out.origen == "sintetico").all()
    )
    assert not set(prod.sigla) & set(mensual.sigla_clave)  # no public sigla survives
    assert receta["sintetico"] is True and receta["n_pozos"] == 4 and receta["semilla"] == 3
    ratio = prod.groupby("sigla").petroleo_m3.sum() / (3000.0 / np.arange(1, 16)).sum()
    assert ((ratio > 0.6) & (ratio < 1.6)).all() and not np.allclose(ratio, 1.0)  # noise, not a copy
    assert (out.rama_m.between(1900, 2625)).all()
    _ = rng  # determinism: same seed, same output
    prod2, out2, _ = S.generar(mensual, pozos, n=4, semilla=3)
    pd.testing.assert_frame_equal(prod, prod2)
    pd.testing.assert_frame_equal(out, out2)
    with pytest.raises(ValueError, match="menos de 2 pozos"):
        S.generar(mensual.iloc[:5], pozos, n=2)


def test_committed_fixture_is_synthetic_and_loads():
    mis = C.cargar(FIX / "mis_pozos_produccion.csv", ruta_pozos=FIX / "mis_pozos_atributos.csv")
    meta = json.loads((FIX / "mis_pozos_produccion.csv.meta.json").read_text(encoding="utf-8"))
    assert meta["sintetico"] is True and mis.meta["sintetico"] is True
    assert 20 <= mis.n_pozos <= 50 and set(mis.pozos.campania) == {"PAD-A", "PAD-B", "PAD-C"}
    atributos = pd.read_csv(FIX / "mis_pozos_atributos.csv")
    assert (atributos.origen == "sintetico").all()
    assert mis.indicadores.sigla.str.startswith("MIO-").all()


# --- comparisons against the fake published tables --------------------------------------------------------------------


def test_percentil_en_curva():
    assert K.percentil_en_curva(150, 150, 100, 50) == 10
    assert K.percentil_en_curva(100, 150, 100, 50) == 50
    assert K.percentil_en_curva(50, 150, 100, 50) == 90
    mid = K.percentil_en_curva(np.sqrt(150 * 100), 150, 100, 50)
    assert mid == pytest.approx(30)  # log-linear between P50 and P10
    assert K.percentil_en_curva(1000, 150, 100, 50) == 1 and K.percentil_en_curva(0.01, 150, 100, 50) == 99
    assert K.percentil_en_curva(None, 150, 100, 50) is None and K.percentil_en_curva(1, None, 100, 50) is None
    assert K.percentil_en_curva(1, 50, 100, 150) is None  # not ordered: not a curve


@pytest.fixture
def d_con_mio(d, tmp_path):
    mis = C.cargar(
        _mi_csv(tmp_path, factor=0.5), mapeo={"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"}
    )
    C.registrar(d.con, mis)
    d.propios = mis
    yield d, mis
    d.propios = None


def test_comparar_pozo_places_the_well(d_con_mio):
    d, mis = d_con_mio
    r = K.comparar_pozo(d, mis, "mio.nq.x-1(h)", mes_max=12)
    assert r["grupo"]["nivel"] == "cohorte_formacion_ventana" and r["grupo"]["ventana"] == "petroleo"
    assert r["grupo"]["cohorte"] == 2024 and r["grupo"]["formacion"] == "Vaca Muerta"
    assert r["resumen"]["n_meses_comparados"] == 13 and r["resumen"]["meses_sobre_p50"] == 0
    for m in r["meses"]:
        assert m["ratio_p50"] == pytest.approx(0.5, rel=1e-3)  # json: 4 significant digits
        assert m["percentil"] == pytest.approx(90.0, abs=0.1)  # my rate is exactly the fake P90 (0.5 × P50)
    ip90 = r["indicadores_vs_grupo"]["ip90"]
    assert ip90["n_publico"] >= 5 and 0 <= ip90["supera_pct_publicos"] <= 100
    assert r["pozo"]["campania"] == "PAD-1"
    # another cohort on request, and a missing one explained
    r2 = K.comparar_pozo(d, mis, "MIO.NQ.X-1(H)", cohorte_ref=2024)
    assert r2["grupo"]["cohorte_del_pozo"] == 2024
    with pytest.raises(K.ErrorComparacion, match="no hay curva tipo publicada para cohorte 2019"):
        K.comparar_pozo(d, mis, "MIO.NQ.X-1(H)", cohorte_ref=2019)
    with pytest.raises(K.ErrorComparacion, match="no está entre mis pozos"):
        K.comparar_pozo(d, mis, "OTRO-1")


def test_comparar_pozo_por_metro_needs_lateral(d_con_mio, tmp_path):
    d, mis = d_con_mio
    r = K.comparar_pozo(d, mis, "MIO.NQ.X-1(H)", tasa="petroleo_m3_d_por_m", mes_max=3)
    assert r["meses"][0]["mio"] == pytest.approx(0.5 * 100 / 2000)
    corto = C.cargar(
        _mi_csv(tmp_path, Rama=100), mapeo={"petroleo_m3": "Oil (m3)", "gas_mil_m3": "Gas (km3)"}
    )
    with pytest.raises(K.ErrorComparacion, match="ADR-019"):
        K.comparar_pozo(d, corto, "MIO.NQ.X-1(H)", tasa="petroleo_m3_d_por_m")


def test_comparar_campania_and_brechas(d_con_mio):
    d, mis = d_con_mio
    r = K.comparar_campania(d, mis, {"campania": "PAD-1"}, metrica="ip90_petroleo_m3_d")
    assert r["resumen"]["n_mios"] == 1 and r["resumen"]["n_comparados"] == 1
    fila = r["pozos"][0]
    assert fila["grupo"].startswith("cohorte_formacion_ventana:2024/Vaca Muerta/petroleo")
    assert fila["mediana_publica"] > 0 and fila["ratio_vs_mediana"] == pytest.approx(
        fila["mio"] / fila["mediana_publica"]
    )
    with pytest.raises(K.ErrorComparacion, match="ningún pozo mío cumple"):
        K.comparar_campania(d, mis, {"campania": "PAD-9"})
    with pytest.raises(K.ErrorComparacion, match="filtros desconocidos"):
        K.comparar_campania(d, mis, {"operadora": "x"})

    b = K.brechas(d, mis, sigla="MIO.NQ.X-1(H)", mes_max=11)
    assert b["n_pozos"] == 1
    w = b["pozos"][0]
    assert w["meses_comparados"] == 12 and w["meses_debajo_p50"] == 12
    assert w["tramos_debajo"] == {"meses_0_5": 6, "meses_6_11": 6, "meses_12_mas": 0}
    assert w["brecha_acum_pct"] == pytest.approx(-50.0, abs=0.1)
    assert w["acum_mio"] == pytest.approx(sum(0.5 * 100 / (k + 1) * 28 for k in range(12)))
    assert b["total"]["brecha_acum"] == pytest.approx(w["brecha_acum"])
    assert all(m["ratio"] == pytest.approx(0.5, rel=1e-3) for m in w["meses"])


# --- the tools ------------------------------------------------------------------------------------------------------


def test_tools_require_a_loaded_file_and_say_so(d):
    for nombre, entrada in (
        ("comparar_mi_pozo", {"sigla": "X"}),
        ("comparar_mi_campania", {}),
        ("brechas", {}),
    ):
        with pytest.raises(H.ErrorHerramienta, match="cargar_mis_pozos"):
            H.ejecutar(d, nombre, entrada)
    with pytest.raises(H.ErrorHerramienta, match="no existe"):
        H.ejecutar(d, "cargar_mis_pozos", {"ruta": "no/existe.csv"})


def test_tools_envelope_notes_and_synthetic_flag(d):
    r = H.ejecutar(
        d,
        "cargar_mis_pozos",
        {"ruta": str(FIX / "mis_pozos_produccion.csv"), "ruta_pozos": str(FIX / "mis_pozos_atributos.csv")},
    )
    TC._cita_ok(r)
    assert r["datos"]["sintetico"] is True and r["datos"]["n_pozos"] == 30
    assert any("SINTÉTICOS" in n for n in r["notas"]) and any(
        "no se escriben a disco" in n for n in r["notas"]
    )
    assert d.propios is not None and {"mis_produccion", "mis_pozos", "mis_indicadores"} <= C._registrados(
        d.con
    )

    r = H.ejecutar(d, "comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 4})
    TC._cita_ok(r)
    assert r["cita"]["filtros"]["grupo_cohorte"] == 2024 and "mis_produccion" in r["cita"]["tabla"]
    assert all(isinstance(m["mes"], int) for m in r["datos"]["meses"])
    json.dumps(r, allow_nan=False)

    r = H.ejecutar(
        d,
        "comparar_mi_campania",
        {"filtros": {"campania": "PAD-A", "cohorte": 2024}, "metrica": "ip90_petroleo_m3_d_por_m"},
    )
    TC._cita_ok(r)
    assert r["datos"]["resumen"]["n_mios"] >= 1
    assert any("ADR-019" in n for n in r["notas"])

    r = H.ejecutar(d, "brechas", {"filtros": {"cohorte": 2024}, "mes_max": 6, "incluye_outliers": False})
    TC._cita_ok(r)
    assert any("ADR-018" in e for e in r["exclusiones"])
    assert r["datos"]["n_pozos"] >= 1 and "brecha_acum_pct" in r["datos"]["total"]

    # a 2022 well has no fake curve: the error names the cohort and the way out
    with pytest.raises(H.ErrorHerramienta, match="cohorte_ref"):
        H.ejecutar(d, "comparar_mi_pozo", {"sigla": "MIO-002"})
    r = H.ejecutar(d, "comparar_mi_pozo", {"sigla": "MIO-002", "cohorte_ref": 2024, "mes_max": 2})
    assert any("cohorte_ref" in n for n in r["notas"])
    d.propios = None


def test_tools_are_in_the_registry_and_documented():
    nombres = {"cargar_mis_pozos", "comparar_mi_pozo", "comparar_mi_campania", "brechas"}
    assert nombres <= set(H.HERRAMIENTAS)
    defs = {t["name"]: t for t in H.definiciones()}
    assert defs["cargar_mis_pozos"]["input_schema"]["required"] == ["ruta"]
    assert defs["comparar_mi_pozo"]["input_schema"]["properties"]["tasa"]["enum"] == list(H.TASAS)
    doc = (ROOT / "docs" / "mis-datos.md").read_text(encoding="utf-8")
    for n in nombres:
        assert f"`{n}(" in doc
    assert "never leaves the machine" in doc or "no salen de la máquina" in doc
