"""Well master on tiny fixtures: alias resolution, idpozo -> sigla collapse, lateral precedence,
coordinate correction, placeholder dates, first production, publication. No network, no data."""

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from vma import master as M
from vma.alias import AliasTable, load_aliases, read_alias, update_siglas, write_alias
from vma.normalize import operator_key, sigla_l2

ROOT = Path(__file__).resolve().parents[1]
TABLES = ["pozos", "produccion_nc", "fractura", "padron_pozos", "listado_pozos_operadoras"]


def _con(fixtures_dir: Path, tables=TABLES) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for t in tables:
        p = fixtures_dir / "maestro" / f"{t}.csv"
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv('{p.as_posix()}', header=true)")
    return con


@pytest.fixture(scope="module")
def master() -> pd.DataFrame:
    con = _con(ROOT / "tests" / "fixtures")
    return M.build_master(con, load_aliases(ROOT / "alias"), "2026-10-30")


def row(master, sigla_clave):
    r = master[master.sigla_clave == sigla_clave]
    assert len(r) == 1, sigla_clave
    return r.iloc[0]


# --- alias tables --------------------------------------------------------------------------------


def test_alias_tables_have_the_versioned_layout():
    for name in ("operadoras", "formaciones", "siglas"):
        head = (ROOT / "alias" / f"{name}.csv").read_text(encoding="utf-8").splitlines()[0]
        assert head == "variante,canonico,fuente,desde,nota"


def test_operator_alias_resolves_exact_key_and_missing():
    al = load_aliases(ROOT / "alias")
    assert al.operadora("VISTA OIL & GAS ARGENTINA SAU") == ("VISTA ENERGY ARGENTINA SAU", "exact")
    assert al.operadora("Vista Oil & Gas Argentina SA") == ("VISTA ENERGY ARGENTINA SAU", "exact")
    assert al.operadora("PAN AMERICAN ENERGY (SUCURSAL ARGENTINA) LLC") == ("PAN AMERICAN ENERGY SL", "exact")
    assert al.operadora("  YPF S.A. ") == ("YPF S.A.", "exact")  # trimmed before lookup
    assert al.operadora("ypf s.a.") == ("YPF S.A.", "key")  # case-insensitive blocking key
    assert al.operadora("EMPRESA INEXISTENTE S.A.") == ("EMPRESA INEXISTENTE S.A.", "missing")
    assert al.operadora(None) == (None, "null")
    assert al.formacion("vaca muerta") == ("Vaca Muerta", "exact")
    assert al.formacion("VACA MUERTA") == ("Vaca Muerta", "key")


def test_every_canonical_operator_is_also_a_variant_of_itself():
    al = load_aliases(ROOT / "alias")
    variants = {r["variante"] for r in al.operadoras.rows}
    assert {r["canonico"] for r in al.operadoras.rows} <= variants


def test_update_siglas_appends_once_and_keeps_desde(tmp_path):
    path = tmp_path / "siglas.csv"
    write_alias(
        path,
        [{"variante": " A.B-1 ", "canonico": "A.B-1", "fuente": "pozos", "desde": "2026-01-01", "nota": "x"}],
    )
    t = read_alias(path, sigla_l2)
    rows, added = update_siglas(
        t,
        [(" A.B-1 ", "A.B-1", "pozos"), ("a.b-2", "A.B-2", "fractura"), ("A.B-2", "A.B-2", "pozos")],
        date(2026, 10, 31),
    )
    assert added == 1  # the existing one is kept, the identical spelling is not a variant
    assert [r["desde"] for r in rows] == ["2026-01-01", "2026-10-31"]
    write_alias(path, rows)
    assert read_alias(path, sigla_l2).exact["a.b-2"] == "A.B-2"


def test_alias_table_missing_file_is_empty(tmp_path):
    t = read_alias(tmp_path / "nope.csv", operator_key)
    assert isinstance(t, AliasTable) and t.rows == [] and t.resolve("X", operator_key) == ("X", "missing")


# --- identity -------------------------------------------------------------------------------------


def test_one_row_per_physical_well_and_idpozo_collapse(master):
    assert len(master) == 6  # 1+2 collapse, 3, 4, 5, 9 and the fracture-only 7
    r = row(master, "OP.NQ.AA-1(H)")
    assert r.idpozos == "1|2" and r.n_idpozo == 2 and r.idpozo_principal == 1  # 1 has the production
    assert r.sigla == "OP.Nq.AA-1(h)"  # the register spelling is published, the L2 key is kept apart
    assert r.formaciones == "1:Vaca Muerta|2:Quintuco" and r.formacion_principal == "Vaca Muerta"
    assert {"multi_idpozo", "multi_formacion"} <= set(r["flags"].split("|"))
    assert r.nombre_propio == "AA-0001h"
    assert r.fuentes == "pozos|produccion_nc|fractura|padron_pozos|listado_pozos_operadoras"


def test_sigla_spelling_variants_become_aliases(master):
    r = row(master, "OP.NQ.BB-2")
    assert r.sigla == "op.nq.bb-2"  # the register's own spelling, trimmed
    assert set(r.alias_sigla.split("|")) == {"  op.nq.bb-2  ", "OP.Nq.BB-2"}
    variants = master.attrs["sigla_variants"]
    # blanks are cleaning, not identity (ADR-003): only spellings that differ once trimmed are aliases
    assert ("  op.nq.bb-2  ", "op.nq.bb-2", "pozos") not in variants
    assert ("OP.Nq.BB-2", "op.nq.bb-2", "listado_pozos_operadoras;produccion_nc") in variants
    assert all(v[0] != v[1] for v in variants)


def test_fracture_only_well_is_kept_with_sin_produccion(master):
    r = row(master, "OP.NQ.GG-7")
    assert r.cuenca == "GOLFO SAN JORGE" and r.tipo_recurso == "CONVENCIONAL"
    assert {"sin_padron_pozos", "sin_produccion"} <= set(r["flags"].split("|"))
    assert pd.isna(r.primera_produccion) and r.meses_registrados == 0


# --- operator ---------------------------------------------------------------------------------------


def test_operator_is_latest_production_month_through_alias_with_history(master):
    r = row(master, "OP.NQ.BB-2")
    assert r.operadora == "VISTA ENERGY ARGENTINA SAU"
    assert r.operadoras_historicas == "VISTA ENERGY ARGENTINA SAU"  # rename merged: no spurious change
    assert "cambio_operadora" not in r["flags"]
    assert "operadora=produccion_nc@2022-05" in r.linaje
    r4 = row(master, "OP.NQ.CC-3")
    assert r4.operadora == "PAN AMERICAN ENERGY SL" and "operadora=pozos.empresa" in r4.linaje


# --- coordinates, depth, dates -------------------------------------------------------------------------


def test_validate_coordinates_rules():
    assert M.validate_coordinates(-38.5, -68.9, "NEUQUINA") == (-68.9, -38.5, ["coordenadas_invertidas"])
    assert M.validate_coordinates(-68.9, -38.5, "NEUQUINA") == (-68.9, -38.5, [])
    assert M.validate_coordinates(0, 0, "NEUQUINA") == (None, None, ["sin_coordenadas"])
    assert M.validate_coordinates(None, -38.5, "NEUQUINA") == (None, None, ["sin_coordenadas"])
    assert M.validate_coordinates(-60.0, -38.6, "NEUQUINA")[2] == ["coordenadas_fuera_cuenca"]
    assert M.validate_coordinates(-30.0, -38.6, "NEUQUINA")[2] == ["coordenadas_fuera_argentina"]
    assert M.validate_coordinates(-60.0, -38.6, "OTRA")[2] == []  # unknown basin: only the country box


def test_swapped_coordinates_are_corrected_in_the_master(master):
    r = row(master, "OP.NQ.BB-2")
    assert (r.longitud, r.latitud) == (-68.9, -38.5) and "coordenadas_invertidas" in r["flags"]
    r5 = row(master, "OP.NQ.DD-4")
    assert "coordenadas_fuera_cuenca" in r5["flags"] and r5.longitud == -60.0  # kept, flagged


def test_parse_point():
    assert M.parse_point('{"type":"Point","coordinates":[-68.252159000000006,-52.5705]}') == (
        -68.252159000000006,
        -52.5705,
    )
    assert M.parse_point(None) == (None, None) and M.parse_point("garbage") == (None, None)


def test_depth_zero_is_null_and_group_takes_max(master):
    assert row(master, "OP.NQ.AA-1(H)").profundidad_m == 3000.0  # 3000 and 0 -> 3000, no flag
    assert "profundidad_cero" not in row(master, "OP.NQ.AA-1(H)")["flags"]
    r5 = row(master, "OP.NQ.DD-4")
    assert r5.profundidad_m == 9000.0 and "profundidad_sospechosa" in r5["flags"]


def test_placeholder_dates_become_null_with_flag(master):
    r = row(master, "OP.NQ.BB-2")
    assert pd.isna(r.fecha_inicio_perforacion) and pd.isna(r.fecha_fin_terminacion)
    assert "fecha_placeholder" in r["flags"]
    r1 = row(master, "OP.NQ.AA-1(H)")
    assert (
        r1.fecha_inicio_perforacion == pd.Timestamp("2020-01-10") and "fecha_placeholder" not in r1["flags"]
    )
    assert M.clean_date(pd.Timestamp("1910-01-01"), []) is None
    assert M.clean_date(pd.Timestamp("1951-01-01"), []) == date(1951, 1, 1)


# --- lateral length precedence (ADR-010) --------------------------------------------------------------


def _fr(*rows):
    return pd.DataFrame(rows, columns=["longitud_rama_horizontal_m", "cantidad_fracturas"])


def test_lateral_precedence():
    assert M.lateral_length(_fr()) == (None, 0, ["sin_fractura"])
    assert M.lateral_length(_fr((2500, 35))) == (2500.0, 35, [])
    assert M.lateral_length(_fr((0, 20))) == (None, 20, ["rama_cero", "rama_faltante"])
    assert M.lateral_length(_fr((0, 3))) == (None, 3, ["rama_cero"])
    rama, etapas, flags = M.lateral_length(_fr((2500, 30), (2600, 5)))
    assert (rama, etapas) == (2600.0, 35) and flags == ["fractura_multiples_registros", "rama_multiple"]
    rama, etapas, flags = M.lateral_length(_fr((0, 30), (2600, 5)))
    assert (rama, etapas) == (2600.0, 35) and "rama_cero" not in flags


def test_lateral_in_master(master):
    assert row(master, "OP.NQ.AA-1(H)").rama_m == 2500.0
    r4 = row(master, "OP.NQ.CC-3")
    assert pd.isna(r4.rama_m) and r4.etapas == 20 and "rama_faltante" in r4["flags"]
    r5 = row(master, "OP.NQ.DD-4")
    assert r5.rama_m == 2600.0 and r5.etapas == 35 and r5.n_registros_fractura == 2
    assert r5.arena_tn == 2800.0 and r5.fecha_inicio_fractura == pd.Timestamp("2022-02-05")
    assert pd.isna(row(master, "OP.NQ.ZZ-9").etapas)


# --- first production ----------------------------------------------------------------------------------


def test_first_production_skips_zero_months_and_sums_idpozo(master):
    r = row(master, "OP.NQ.AA-1(H)")
    assert r.primera_produccion == pd.Timestamp("2020-04-01") and r.ultima_produccion == pd.Timestamp(
        "2020-06-01"
    )
    assert r.meses_registrados == 3 and r.meses_con_produccion == 3
    assert r.acum_petroleo_m3 == pytest.approx(310.5) and r.acum_gas_mil_m3 == pytest.approx(61.0)
    assert r.acum_petroleo_bbl == pytest.approx(310.5 / 0.158987294928)
    assert r.acum_equivalente_m3 == pytest.approx(310.5 + 61.0)
    r5 = row(master, "OP.NQ.DD-4")
    assert r5.primera_produccion == pd.Timestamp("2022-05-01")  # 2022-04 has a record with zero production
    assert (
        r5.primera_produccion_padron == pd.Timestamp("2022-01-01")
        and "primera_produccion_difiere_padron" in r5["flags"]
    )
    r9 = row(master, "OP.NQ.ZZ-9")
    assert pd.isna(r9.primera_produccion) and "nunca_produjo" in r9["flags"] and r9.meses_registrados == 1


def test_first_production_function_empty():
    out = M.first_production(pd.DataFrame(columns=["anio", "mes", "prod_pet", "prod_gas", "prod_agua"]))
    assert out["primera_produccion"] is None and out["flags"] == ["sin_produccion"]


# --- publication --------------------------------------------------------------------------------------------


def test_publish_csv_and_parquet_round_trip(master, tmp_path):
    csv_path, pq_path = M.publish(tmp_path, master, date(2026, 10, 31))
    assert csv_path == tmp_path / "data" / "publicado" / "2026-10-31" / "pozos.csv" and pq_path.exists()
    back = duckdb.connect().execute(f"SELECT * FROM read_parquet('{pq_path.as_posix()}')").fetchdf()
    assert len(back) == len(master) and list(back.columns) == M.COLUMNS
    csv_back = pd.read_csv(csv_path)
    assert csv_back.primera_produccion.dropna().iloc[0] == "2020-04-01"  # ISO dates, no time part
    assert csv_back.etapas.dropna().astype(int).tolist() == [35, 20, 35, 2]


def test_columns_are_documented(master):
    doc = (ROOT / "docs" / "maestro.md").read_text(encoding="utf-8")
    for c in M.COLUMNS:
        assert f"`{c}`" in doc, c
    for flag in master["flags"].str.split("|").explode().dropna().unique():
        if flag:
            assert f"`{flag}`" in doc, flag


def test_without_padron_and_listado(fixtures_dir):
    con = _con(fixtures_dir, ["pozos", "produccion_nc", "fractura"])
    m = M.build_master(con, load_aliases(ROOT / "alias"), "2026-10-30")
    assert len(m) == 6 and m.primera_produccion_padron.isna().all() and m.nombre_propio.isna().all()
    assert "sin_padron_primera_produccion" not in "|".join(m["flags"])
