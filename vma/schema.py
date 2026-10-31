"""Dump the *real* schema of each downloaded dataset: columns, inferred types, nulls,
cardinality, min/max and a few sample values. Nothing here assumes column names; the
point of phase 0 is to find out what the files actually contain before designing
anything on top of them.

Output: ``docs/esquemas/<key>.md`` (one per dataset, versioned) and
``docs/esquemas/README.md`` (index with row counts).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from .download import latest_raw_dir, read_manifest

SAMPLE_VALUES = 3


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def load_csv(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    """Register ``path`` as a view. All columns are read as text first so the schema
    dump reports what the file literally contains; type inference is a separate column."""
    con.execute(
        f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_csv("
        f"'{path.as_posix()}', header=true, all_varchar=true, ignore_errors=true, "
        f"union_by_name=false, encoding='utf-8')"
    )


def inferred_types(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, str]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_csv('{path.as_posix()}', header=true, ignore_errors=true, sample_size=-1)"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


NUMERIC = ("BIGINT", "DOUBLE", "INTEGER", "HUGEINT", "DECIMAL", "FLOAT", "SMALLINT", "TINYINT")
TEMPORAL = ("DATE", "TIMESTAMP")


def column_profile(
    con: duckdb.DuckDBPyConnection, table: str, col: str, n: int, inferred: str = "VARCHAR"
) -> dict[str, Any]:
    q = f'"{col}"'
    # min/max on the text column would be lexicographic ("9998" > "10073"); cast when the
    # inferred type says the column is numeric or temporal.
    if inferred.startswith(NUMERIC):
        mm = f"TRY_CAST({q} AS DOUBLE)"
    elif inferred.startswith(TEMPORAL):
        mm = f"TRY_CAST({q} AS {inferred.split('(')[0]})"
    else:
        mm = q
    nulls, empties, distinct, vmin, vmax = con.execute(
        f"SELECT count(*) FILTER (WHERE {q} IS NULL), "
        f"count(*) FILTER (WHERE trim({q}) = ''), "
        f"count(DISTINCT {q}), min({mm}), max({mm}) FROM {table}"
    ).fetchone()
    samples = [
        r[0]
        for r in con.execute(
            f"SELECT {q} FROM (SELECT {q}, count(*) c FROM {table} WHERE {q} IS NOT NULL AND trim({q}) <> '' "
            f"GROUP BY 1 ORDER BY c DESC LIMIT {SAMPLE_VALUES})"
        ).fetchall()
    ]
    return {
        "column": col,
        "nulls": nulls,
        "empties": empties,
        "null_pct": round(100 * (nulls + empties) / n, 2) if n else 0.0,
        "distinct": distinct,
        "min": vmin,
        "max": vmax,
        "samples": samples,
    }


def profile_table(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> dict[str, Any]:
    load_csv(con, table, path)
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    types = inferred_types(con, path)
    profile = []
    for c in cols:
        p = column_profile(con, table, c, n, types.get(c, "VARCHAR"))
        p["inferred_type"] = types.get(c, "?")
        profile.append(p)
    return {"table": table, "rows": n, "columns": profile}


def _fmt(v: Any, width: int = 28) -> str:
    s = "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= width else s[: width - 1] + "…"


def render_markdown(key: str, meta: dict[str, Any], prof: dict[str, Any]) -> str:
    lines = [
        f"# `{key}` — {meta['title']}",
        "",
        f"- Source: <{meta['landing_page']}> (CC-BY 4.0), file `{meta['file']}`",
        f"- Downloaded: {meta['downloaded_at']} · {meta['bytes']:,} bytes · sha256 `{meta['sha256'][:16]}…`",
        f"- CKAN last_modified: {meta.get('ckan_last_modified') or 'n/a'}",
        f"- Rows: **{prof['rows']:,}** · Columns: **{len(prof['columns'])}**",
        "",
        "Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;",
        "`samples` are the three most frequent non-empty values.",
        "",
        "| # | column | inferred type | null % | distinct | min | max | samples |",
        "|--:|---|---|--:|--:|---|---|---|",
    ]
    for i, c in enumerate(prof["columns"], 1):
        lines.append(
            f"| {i} | `{c['column']}` | {c['inferred_type']} | {c['null_pct']} | {c['distinct']:,} | "
            f"{_fmt(c['min'], 20)} | {_fmt(c['max'], 20)} | {_fmt('; '.join(map(str, c['samples'])), 60)} |"
        )
    return "\n".join(lines) + "\n"


def dump_schemas(root: Path, log: Callable[[str], None] = print) -> list[Path]:
    raw = latest_raw_dir(root)
    manifest = read_manifest(root)
    out_dir = root / "docs" / "esquemas"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect()
    written = []
    index = [
        "# Real schemas of the downloaded datasets",
        "",
        f"Raw folder: `data/raw/{raw.name}`.",
        "",
        "| key | title | rows | columns | file |",
        "|---|---|--:|--:|---|",
    ]
    for meta in manifest["sources"]:
        path = raw / meta["file"]
        if not path.exists():
            log(f"  {meta['key']}: file missing, skipping")
            continue
        log(f"  profiling {meta['key']} …")
        prof = profile_table(con, meta["key"], path)
        out = out_dir / f"{meta['key']}.md"
        out.write_text(render_markdown(meta["key"], meta, prof), encoding="utf-8")
        written.append(out)
        index.append(
            f"| [`{meta['key']}`]({meta['key']}.md) | {meta['title']} | {prof['rows']:,} | "
            f"{len(prof['columns'])} | `{meta['file']}` |"
        )
    (out_dir / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return written
