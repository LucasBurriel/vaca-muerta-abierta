"""F6: the price parsers on fixtures with the real layout, the published table on both sources, the valuation with
hand-computed figures, the tools with and without ``valorizar``, and the views. No network, no model, no real data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vma import units
from vma.consulta import datos as D
from vma.precios import cuenca_gas_canonica, provincia_canonica
from vma.precios import fuentes as F
from vma.precios import valorizar as V

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "precios"


# --- parsers ----------------------------------------------------------------------------------------------------------


def test_regalias_workbook_is_read_by_content_not_by_row_number():
    r, meta = F.leer_regalias_crudo(FIX / "regalias_crudo.zip")
    assert meta["fecha_realizacion"] == "2026-10-06" and meta["ultimo_mes"] == "2026-08"
    assert "provisori" in meta["nota_provisorio"].lower()
    # 4 provinces with data (Santa Cruz is all zeros -> dropped) × 20 reported months
    assert set(r.region) == {"Chubut", "Neuquén", "Río Negro", "Total Provincia"}
    assert len(r) == 4 * 20
    nq = r[r.region == "Neuquén"].set_index(["anio", "mes"])
    assert nq.loc[(2026, 8), "precio_usd_m3"] == 508.0  # 500 + month, from the fixture generator
    assert (
        nq.loc[(2026, 8), "produccion_m3"] == 3_000_000.0
        and nq.loc[(2026, 8), "regalias_usd"] == 180_000_000.0
    )
    # the three sheets have their header on different rows; the join is by province × month
    assert r.produccion_m3.notna().all() and r.regalias_usd.notna().all()
    # zeros are "nothing reported", never a price: 2026-09..12 are absent
    assert (2026, 9) not in nq.index
    # the last two reported months are provisional, the rest are not
    assert set(r[r.provisorio].apply(lambda x: (x.anio, x.mes), axis=1)) == {(2026, 7), (2026, 8)}
    assert not r[(r.anio == 2026) & (r.mes == 6)].provisorio.any()


def test_regalias_rejects_a_workbook_without_the_price_sheet(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "otra cosa"
    p = tmp_path / "x.xlsx"
    wb.save(p)
    with pytest.raises(F.ErrorFuente, match="Tabla precios"):
        F.leer_regalias_crudo(p)


def test_gas_csv_goes_long_and_drops_zeros():
    g = F.leer_precios_gas(FIX / "precios_gas.csv")
    assert set(g.columns) == {"cuenca", "anio", "mes", "contrato", "segmento", "precio_usd_mmbtu"}
    assert set(g.contrato) == {"firme", "interrumpible", "total"}
    assert "otros" not in set(g.segmento)  # 0.00 in every row of the fixture -> no sales -> dropped
    nq = g[(g.cuenca == "Neuquina") & (g.contrato == "total") & (g.segmento == "ppp")].set_index(
        ["anio", "mes"]
    )
    assert nq.loc[(2026, 8), "precio_usd_mmbtu"] == pytest.approx(4.0 + 0.1 + 0.08)
    with pytest.raises(F.ErrorFuente, match="faltan columnas"):
        F.leer_precios_gas(b"a,b\n1,2\n")


def test_table_grain_units_and_conversions():
    r, meta = F.leer_regalias_crudo(FIX / "regalias_crudo.zip")
    g = F.leer_precios_gas(FIX / "precios_gas.csv")
    t = F.construir(
        r, g, fecha_descarga="2026-11-02", version="2026-10-31", fecha_realizacion=meta["fecha_realizacion"]
    )
    assert list(t.columns) == F.COLUMNAS
    assert not t.duplicated(["producto", "region", "anio", "mes", "segmento", "contrato"]).any()
    oil = t[t.producto == "petroleo"]
    assert (oil.unidad_dataset == "USD/m³").all() and (oil.segmento == "promedio_venta").all()
    assert oil.contrato.isna().all() and (oil.precio_usd_mil_m3 == oil.precio_usd_m3 * 1000).all()
    assert (oil.fecha_realizacion == "2026-10-06").all() and (oil.tipo_region == "provincia").all()
    gas = t[t.producto == "gas"]
    assert (gas.unidad_dataset == "USD/MMBTU").all() and (gas.tipo_region == "cuenca").all()
    fila = gas[
        (gas.region == "Neuquina")
        & (gas.segmento == "ppp")
        & (gas.contrato == "total")
        & (gas.anio == 2026)
        & (gas.mes == 8)
    ].iloc[0]
    # 4.18 USD/MMBTU × 36.905 MMBTU per mil m³ (9,300 kcal/m³, 252,000 kcal/MMBTU)
    assert units.MMBTU_PER_THOUSAND_M3 == pytest.approx(36.9048, abs=1e-4)
    assert fila.precio_usd_mil_m3 == pytest.approx(4.18 * 36.9048, rel=1e-4)
    assert fila.precio_usd_m3 == pytest.approx(fila.precio_usd_mil_m3 / 1000)
    assert gas.produccion_m3.isna().all() and gas.fecha_realizacion.isna().all()
    assert str(t.mes_fecha.iloc[0]) == f"{t.anio.iloc[0]}-{t.mes.iloc[0]:02d}-01"
    # the empty schema has the same columns, so a source without the table still answers every query
    assert list(F.tabla_vacia().columns) == F.COLUMNAS and len(F.tabla_vacia()) == 0


def test_snapshot_round_trip_keeps_oil_from_2006_and_gas_total_only():
    r, meta = F.leer_regalias_crudo(FIX / "regalias_crudo.zip")
    g = F.leer_precios_gas(FIX / "precios_gas.csv")
    t = F.construir(
        r, g, fecha_descarga="2026-11-02", version="2026-10-31", fecha_realizacion=meta["fecha_realizacion"]
    )
    doc = json.loads(json.dumps(F.snapshot_json(t), allow_nan=False))
    assert (
        doc["ultimo_mes"] == {"petroleo": "2026-08", "gas": "2026-08"}
        and doc["fecha_realizacion"] == "2026-10-06"
    )
    back = F.desde_json(doc)
    assert list(back.columns) == F.COLUMNAS
    assert set(back[back.producto == "gas"].contrato) == {"total"}
    assert len(back[back.producto == "petroleo"]) == len(
        t[t.producto == "petroleo"]
    )  # fixture is 2025-26, all kept
    a = t[(t.producto == "petroleo") | ((t.producto == "gas") & (t.contrato == "total"))].reset_index(
        drop=True
    )
    assert back.precio_usd_mil_m3.to_numpy() == pytest.approx(a.precio_usd_mil_m3.to_numpy(), rel=1e-3)
    assert back.provisorio.sum() == a.provisorio.sum()
    assert len(F.desde_json({"columnas": {}})) == 0


def test_region_names_resolve_loosely():
    assert (
        provincia_canonica("NEUQUEN")
        == "Neuquén"
        == provincia_canonica("neuquén")
        == provincia_canonica("Neuquen")
    )
    assert provincia_canonica("Rio Negro") == "Río Negro" and provincia_canonica("Marte") is None
    assert cuenca_gas_canonica("NEUQUINA") == "Neuquina"
    assert cuenca_gas_canonica("GOLFO SAN JORGE") == "Golfo de San Jorge"
    assert cuenca_gas_canonica("AUSTRAL", "Santa Cruz") == "Austral Santa Cruz"
    assert cuenca_gas_canonica("AUSTRAL", "Tierra del Fuego") == "Austral Tierra del Fuego"
    assert cuenca_gas_canonica("CUYANA") is None


# --- the table through the data layer, on both sources -----------------------------------------------------------------


def test_precios_is_an_optional_fourth_table(d_precios, d_sin_precios):
    d, d_sin = d_precios, d_sin_precios
    assert D.TABLAS == ("pozos", "indicadores", "curvas_tipo") and D.TABLAS_OPCIONALES == ("precios",)
    assert d.tiene_precios() and d.tiene("precios", "precio_usd_mil_m3")
    n_gas_total = d.con.execute(
        "SELECT count(*) FROM precios WHERE producto = 'gas' AND contrato = 'total'"
    ).fetchone()[0]
    assert n_gas_total == 3 * 20 * 6  # 3 basins × 20 months × 6 segments with sales
    if d.fuente == "parquet":
        assert d.con.execute("SELECT count(*) FROM precios WHERE contrato = 'firme'").fetchone()[0] > 0
    else:
        assert (
            d.con.execute("SELECT count(*) FROM precios WHERE contrato = 'firme'").fetchone()[0] == 0
        )  # snapshot cut
    # without the table the source still has the schema, empty
    assert (
        not d_sin.tiene_precios()
        and d_sin.tiene("precios", "precio_usd_m3")
        and d_sin.n_filas("precios") == 0
    )
    with pytest.raises(KeyError):
        d.columnas("regalias")


# --- the valuation, with figures computed by hand ----------------------------------------------------------------------


def _series():
    oil = V.SeriePrecio(
        "petroleo",
        "Neuquén",
        "USD/m³",
        {"2024-01": 500.0, "2024-02": 510.0, "2024-03": 520.0},
        "regalias_crudo",
        "promedio_venta",
        None,
        {"2024-03"},
    )
    gas = V.SeriePrecio(
        "gas",
        "Neuquina",
        "USD/mil m³",
        {"2024-01": 100.0, "2024-02": 110.0, "2024-03": 120.0},
        "precios_gas",
        "ppp",
        "total",
    )
    return oil, gas


def test_historico_prices_each_calendar_month_then_holds_the_last_one():
    oil, gas = _series()
    r = V.valorizar(
        [100, 80, 60, 50],
        [10, 8, 6, 5],
        modo="historico",
        precio_petroleo=oil,
        precio_gas=gas,
        mes0="2024-02",
        tasa_anual=0.12,
        regalia=0.12,
    )
    m = r["por_mes"]
    # month 0 = 2024-02: 100 × 510 + 10 × 110 = 52,100 gross; 12 % royalty = 6,252; 45,848 net, undiscounted
    assert m[0]["mes_calendario"] == "2024-02" and m[0]["bruto_usd"] == 52_100.0
    assert m[0]["regalia_usd"] == pytest.approx(6_252.0) and m[0]["ingreso_usd"] == pytest.approx(45_848.0)
    assert m[0]["descontado_usd"] == pytest.approx(45_848.0)
    # month 1 = 2024-03 (provisional): 80 × 520 + 8 × 120 = 42,560
    assert m[1]["bruto_usd"] == pytest.approx(42_560.0)
    # months 2 and 3 are after the last published month: last price held (520 / 120)
    assert m[2]["precio_petroleo_usd_m3"] == 520.0 and m[3]["precio_gas_usd_mil_m3"] == 120.0
    assert m[3]["bruto_usd"] == pytest.approx(50 * 520 + 5 * 120)
    t = r["total"]
    bruto = 52_100 + 42_560 + (60 * 520 + 6 * 120) + (50 * 520 + 5 * 120)
    assert t["bruto_usd"] == pytest.approx(bruto) and t["regalia_usd"] == pytest.approx(0.12 * bruto)
    assert t["ingreso_usd"] == pytest.approx(0.88 * bruto) and t["petroleo_usd"] == pytest.approx(
        100 * 510 + 80 * 520 + 60 * 520 + 50 * 520
    )
    van = sum(
        0.88 * b * 1.12 ** (-k / 12)
        for k, b in enumerate([52_100, 42_560, 60 * 520 + 6 * 120, 50 * 520 + 5 * 120])
    )
    assert t["van_usd"] == pytest.approx(van)
    assert t["meses_con_ultimo_precio"] == 2 and t["meses_sin_precio"] == 0
    assert r["precios"]["petroleo"]["min"] == 510.0 and r["precios"]["petroleo"]["max"] == 520.0
    assert any("2 mes(es) posteriores" in n for n in r["notas"]) and any(
        "provisorio" in n for n in r["notas"]
    )
    assert any("BRUTO" in n for n in r["notas"]) and any("9.300 kcal" in n for n in r["notas"])


def test_months_before_the_first_price_have_no_usd_and_do_not_count():
    oil, _ = _series()
    r = V.valorizar(
        [100, 100, 100], None, modo="historico", precio_petroleo=oil, mes0="2023-12", tasa_anual=0.0
    )
    assert r["por_mes"][0]["ingreso_usd"] is None and r["por_mes"][0]["acumulado_usd"] is None
    assert r["total"]["meses_sin_precio"] == 1 and r["total"]["ingreso_usd"] == 100 * 500 + 100 * 510
    assert r["total"]["van_usd"] == r["total"]["ingreso_usd"]  # 0 % rate: NPV = sum
    assert r["precios"]["gas"] is None


def test_flat_accepts_bbl_and_mmbtu_and_converts():
    r = V.valorizar(
        [100, 80], [10, 8], modo="flat", flat={"petroleo_usd_bbl": 70, "gas_usd_mmbtu": 4.0}, tasa_anual=0.10
    )
    p_m3 = 70 * units.BBL_PER_M3  # 440.29 USD/m³
    g_mil = 4.0 * units.MMBTU_PER_THOUSAND_M3  # 147.62 USD per mil m³
    assert r["precios"]["petroleo"]["precio"] == pytest.approx(p_m3) and r["precios"]["gas"][
        "precio"
    ] == pytest.approx(g_mil)
    assert r["total"]["bruto_usd"] == pytest.approx(180 * p_m3 + 18 * g_mil)
    assert r["total"]["van_usd"] == pytest.approx(
        (100 * p_m3 + 10 * g_mil) + (80 * p_m3 + 8 * g_mil) * 1.1 ** (-1 / 12)
    )
    assert r["mes0"] is None and r["por_mes"][1]["mes_calendario"] is None
    with pytest.raises(V.ErrorValorizacion, match="falta precio_flat"):
        V.valorizar([1], [1], modo="flat", flat={"petroleo_usd_m3": 500})
    with pytest.raises(V.ErrorValorizacion, match="claves desconocidas"):
        V.valorizar([1], None, modo="flat", flat={"usd_bbl": 70})


def test_ultimo_holds_the_last_published_price_and_compacto_gives_lists():
    oil, _ = _series()
    r = V.valorizar([100, 80], None, modo="ultimo", precio_petroleo=oil, compacto=True)
    assert r["series"]["ingreso_usd"] == [52_000.0, 41_600.0] and r["series"]["acumulado_usd"] == [
        52_000.0,
        93_600.0,
    ]
    assert r["total"]["van_usd"] == pytest.approx(52_000 + 41_600 * 1.1 ** (-1 / 12))
    assert r["precios"]["petroleo"]["ultimo_mes_publicado"] == "2024-03" and "por_mes" not in r


def test_valuation_arguments_are_checked():
    oil, _ = _series()
    with pytest.raises(V.ErrorValorizacion, match="modo"):
        V.valorizar([1], None, modo="spot", precio_petroleo=oil)
    with pytest.raises(V.ErrorValorizacion, match="mes0"):
        V.valorizar([1], None, modo="historico", precio_petroleo=oil)
    with pytest.raises(V.ErrorValorizacion, match="YYYY-MM"):
        V.valorizar([1], None, modo="historico", precio_petroleo=oil, mes0="2024/13")
    with pytest.raises(V.ErrorValorizacion, match="regalia"):
        V.valorizar([1], None, modo="ultimo", precio_petroleo=oil, regalia=1.5)
    with pytest.raises(V.ErrorValorizacion, match="no hay serie de precio de gas"):
        V.valorizar(None, [1], modo="ultimo", precio_petroleo=oil)
    with pytest.raises(V.ErrorValorizacion, match="no hay volúmenes"):
        V.valorizar([], [], modo="ultimo")
    assert V.mes_mas("2024-11", 3) == "2025-02" and V.mes_mas("2024-01", -1) == "2023-12"
    assert V.volumenes_desde_tasas([10.0, None], uptime=1.0) == [pytest.approx(10 * 365.25 / 12), None]
    assert V.volumenes_desde_acumulado([100.0, 150.0, None, 180.0]) == [100.0, 50.0, None, 30.0]
