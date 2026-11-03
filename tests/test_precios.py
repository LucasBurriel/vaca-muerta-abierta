"""F6: the price parsers on fixtures with the real layout, the published table on both sources, the valuation with
hand-computed figures, the tools with and without ``valorizar``, and the views. No network, no model, no real data."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import test_consulta as TC

from vma import units
from vma.consulta import datos as D
from vma.precios import cuenca_gas_canonica, provincia_canonica
from vma.precios import fuentes as F

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


def _tabla_fixture() -> pd.DataFrame:
    r, meta = F.leer_regalias_crudo(FIX / "regalias_crudo.zip")
    g = F.leer_precios_gas(FIX / "precios_gas.csv")
    return F.construir(
        r, g, fecha_descarga="2026-11-02", version="2026-10-31", fecha_realizacion=meta["fecha_realizacion"]
    )


@pytest.fixture(scope="module")
def raiz_precios(tmp_path_factory) -> Path:
    """The F4 fake repo (tests/test_consulta.py) plus the prices table in both sources."""
    from vma import site as S

    root = tmp_path_factory.mktemp("repo_precios")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    t = _tabla_fixture()
    for name, df in (
        ("pozos", TC._master()),
        ("indicadores", TC._ind()),
        ("curvas_tipo", TC._curvas()),
        ("precios", t),
    ):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    S.build_site_data(
        root / "site" / "data",
        TC._master(),
        TC._ind(),
        TC._curvas(),
        TC.MANIFEST,
        "2026-10-31",
        today=date(2026, 10, 31),
        precios=t,
    )
    return root


@pytest.fixture(scope="module")
def raiz_sin_precios(tmp_path_factory) -> Path:
    from vma import site as S

    root = tmp_path_factory.mktemp("repo_sin_precios")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    for name, df in (("pozos", TC._master()), ("indicadores", TC._ind()), ("curvas_tipo", TC._curvas())):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    S.build_site_data(
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
def d(raiz_precios, request) -> D.Datos:
    return D.abrir(raiz_precios, request.param)


@pytest.fixture(params=["parquet", "json"])
def d_sin(raiz_sin_precios, request) -> D.Datos:
    return D.abrir(raiz_sin_precios, request.param)


def test_precios_is_an_optional_fourth_table(d, d_sin):
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
