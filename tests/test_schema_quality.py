"""Schema profiling and quality helpers on tiny fixtures, without network."""

from datetime import date

import duckdb

from vma import quality as q
from vma import schema as sc


def _con(fixtures_dir):
    con = duckdb.connect(":memory:")
    for t in ("produccion_nc", "fractura"):
        con.execute(
            f"CREATE VIEW {t} AS SELECT * FROM read_csv('{(fixtures_dir / t).as_posix()}.csv', header=true)"
        )
    return con


def test_profile_table_reports_real_columns(fixtures_dir):
    con = duckdb.connect(":memory:")
    prof = sc.profile_table(con, "p", fixtures_dir / "produccion_nc.csv")
    assert prof["rows"] == 3
    cols = {c["column"]: c for c in prof["columns"]}
    assert set(cols) >= {"idpozo", "sigla", "prod_pet"}
    assert cols["idpozo"]["distinct"] == 2
    assert cols["prod_pet"]["inferred_type"] == "DOUBLE"
    assert cols["prod_pet"]["min"] == 50.0 and cols["prod_pet"]["max"] == 100.5  # numeric, not lexicographic
    assert cols["sigla"]["null_pct"] == 0.0


def test_render_markdown_has_one_row_per_column(fixtures_dir):
    con = duckdb.connect(":memory:")
    prof = sc.profile_table(con, "p", fixtures_dir / "produccion_nc.csv")
    meta = {
        "title": "t",
        "landing_page": "u",
        "file": "f",
        "downloaded_at": "d",
        "bytes": 1,
        "sha256": "x" * 64,
    }
    md = sc.render_markdown("p", meta, prof)
    assert md.count("\n| ") == len(prof["columns"]) + 1  # header row + one row per column


def test_cross_match_by_idpozo_and_sigla_levels(fixtures_dir):
    con = _con(fixtures_dir)
    out = q.cross_match(con, "produccion_nc", ["fractura"])
    row = out.iloc[0]
    assert row["by idpozo"] == 2
    # raw siglas differ in case, spaces and suffix: only normalisation recovers them
    assert row["by sigla L0 raw"] == 0
    assert row["by sigla L2 trim+upper"] == 1
    assert row["by sigla L3 +drop (h)/(d) suffix"] == 2


def test_wells_per_dataset_and_md_table(fixtures_dir):
    con = _con(fixtures_dir)
    w = q.wells_per_dataset(con, ["produccion_nc", "fractura"])
    assert list(w["distinct idpozo"]) == [2, 2]
    md = q.md_table(w)
    assert md.startswith("| dataset |") and "produccion_nc" in md


def test_operator_variants_group_spellings(fixtures_dir):
    con = _con(fixtures_dir)
    con.execute("CREATE VIEW pozos AS SELECT NULL::VARCHAR empresa WHERE false")
    con.execute("CREATE VIEW pozos_terminados AS SELECT NULL::VARCHAR empresa WHERE false")
    ops = q.operator_variants(con)
    vista = ops[ops.key == "VISTA OIL Y GAS"].iloc[0]
    assert vista.n_variants == 2
    assert set(vista.datasets) == {"produccion_nc", "fractura"}


def test_publication_lag_counts_months(fixtures_dir):
    con = _con(fixtures_dir)
    manifest = {
        "sources": [
            {"key": "produccion_nc", "ckan_last_modified": "2025-03-10T00:00:00"},
            {"key": "fractura", "ckan_last_modified": None},
        ]
    }
    lag = q.publication_lag(con, manifest, today=date(2025, 4, 15))
    by = lag.set_index("dataset")
    assert by.loc["produccion_nc", "last month with data"] == "2025-02"
    assert by.loc["produccion_nc", "lag (months)"] == 2
    assert by.loc["fractura", "last month with data"] == "2024-12"
