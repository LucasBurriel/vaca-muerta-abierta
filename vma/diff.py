"""Differences between two dated downloads (ADR-005: the source is revised backwards).

``python pipeline.py diff --a 2026-10-30 --b 2026-11-30`` compares ``data/raw/<a>/`` with
``data/raw/<b>/`` dataset by dataset and writes ``informes/diff-<a>-<b>.md``:

- ``pozos``           new / removed ``idpozo``; wells whose sigla, operator or formation changed
- ``produccion_nc``   new wells; new well-months; well-months whose volumes or days changed
                      (rectifications), with the share of rows affected per month
- ``fractura``        new / removed records; records whose lateral length or stage count changed

The diff is itself a quality indicator of the public data: how much of what was published
last time is still what is published now. Datasets missing from either folder are listed and
skipped. With a single download there is nothing to compare: say so and exit 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from .quality import md_table


@dataclass
class DiffResult:
    a: str
    b: str
    sections: dict[str, pd.DataFrame] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name, frame in self.sections.items():
            if {"measure", "value"} <= set(frame.columns):
                for r in frame.itertuples():
                    out[f"{name}: {r.measure}"] = int(r.value)
        return out


def list_downloads(root: Path) -> list[str]:
    base = root / "data" / "raw"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []


def _attach(con: duckdb.DuckDBPyConnection, folder: Path, key: str, alias: str) -> bool:
    p = folder / f"{key}.csv"
    if not p.exists():
        return False
    con.execute(
        f"CREATE VIEW {alias} AS SELECT * FROM read_csv('{p.as_posix()}', header=true, ignore_errors=true, sample_size=-1)"
    )
    return True


def _rows(con, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"measure": m, "value": con.execute(q).fetchone()[0]} for m, q in pairs])


def diff_pozos(con) -> pd.DataFrame:
    return _rows(
        con,
        [
            ("idpozo in a", "SELECT count(DISTINCT idpozo) FROM a_pozos"),
            ("idpozo in b", "SELECT count(DISTINCT idpozo) FROM b_pozos"),
            (
                "new idpozo in b",
                "SELECT count(*) FROM (SELECT idpozo FROM b_pozos EXCEPT SELECT idpozo FROM a_pozos)",
            ),
            (
                "idpozo removed in b",
                "SELECT count(*) FROM (SELECT idpozo FROM a_pozos EXCEPT SELECT idpozo FROM b_pozos)",
            ),
            (
                "sigla changed",
                "SELECT count(*) FROM a_pozos a JOIN b_pozos b USING (idpozo) WHERE trim(a.sigla) IS DISTINCT FROM trim(b.sigla)",
            ),
            (
                "operator changed",
                "SELECT count(*) FROM a_pozos a JOIN b_pozos b USING (idpozo) WHERE a.empresa IS DISTINCT FROM b.empresa",
            ),
            (
                "formation changed",
                "SELECT count(*) FROM a_pozos a JOIN b_pozos b USING (idpozo) WHERE a.formacion IS DISTINCT FROM b.formacion",
            ),
            (
                "coordinates changed",
                "SELECT count(*) FROM a_pozos a JOIN b_pozos b USING (idpozo) WHERE a.geojson IS DISTINCT FROM b.geojson",
            ),
        ],
    )


def operator_changes(con) -> pd.DataFrame:
    return con.execute(
        "SELECT a.empresa AS before, b.empresa AS after, count(*) AS wells FROM a_pozos a JOIN b_pozos b USING (idpozo) "
        "WHERE a.empresa IS DISTINCT FROM b.empresa GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20"
    ).fetchdf()


def diff_produccion(con) -> pd.DataFrame:
    changed = (
        "a_prod a JOIN b_prod b USING (idpozo, anio, mes) WHERE a.prod_pet IS DISTINCT FROM b.prod_pet "
        "OR a.prod_gas IS DISTINCT FROM b.prod_gas OR a.prod_agua IS DISTINCT FROM b.prod_agua OR a.tef IS DISTINCT FROM b.tef"
    )
    return _rows(
        con,
        [
            ("wells in a", "SELECT count(DISTINCT idpozo) FROM a_prod"),
            ("wells in b", "SELECT count(DISTINCT idpozo) FROM b_prod"),
            (
                "new wells in b",
                "SELECT count(*) FROM (SELECT idpozo FROM b_prod EXCEPT SELECT idpozo FROM a_prod)",
            ),
            ("well-months in a", "SELECT count(*) FROM a_prod"),
            ("well-months in b", "SELECT count(*) FROM b_prod"),
            (
                "new well-months in b",
                "SELECT count(*) FROM (SELECT idpozo, anio, mes FROM b_prod EXCEPT SELECT idpozo, anio, mes FROM a_prod)",
            ),
            (
                "well-months removed in b",
                "SELECT count(*) FROM (SELECT idpozo, anio, mes FROM a_prod EXCEPT SELECT idpozo, anio, mes FROM b_prod)",
            ),
            ("well-months rectified (volumes or days changed)", f"SELECT count(*) FROM {changed}"),
            (
                "of which flagged rectificado in b",
                f"SELECT count(*) FROM {changed} AND CAST(b.rectificado AS BOOLEAN)",
            ),
        ],
    )


def rectified_by_month(con) -> pd.DataFrame:
    return con.execute(
        "WITH r AS (SELECT a.anio, a.mes, count(*) AS rectified FROM a_prod a JOIN b_prod b USING (idpozo, anio, mes) "
        "WHERE a.prod_pet IS DISTINCT FROM b.prod_pet OR a.prod_gas IS DISTINCT FROM b.prod_gas "
        "OR a.prod_agua IS DISTINCT FROM b.prod_agua OR a.tef IS DISTINCT FROM b.tef GROUP BY 1, 2), "
        "t AS (SELECT anio, mes, count(*) AS total FROM b_prod GROUP BY 1, 2) "
        "SELECT make_date(r.anio, r.mes, 1) AS month, r.rectified, round(100.0 * r.rectified / t.total, 2) AS pct_of_month "
        "FROM r JOIN t USING (anio, mes) ORDER BY 1 DESC LIMIT 24"
    ).fetchdf()


def diff_fractura(con) -> pd.DataFrame:
    return _rows(
        con,
        [
            ("records in a", "SELECT count(*) FROM a_frac"),
            ("records in b", "SELECT count(*) FROM b_frac"),
            (
                "new records in b",
                "SELECT count(*) FROM (SELECT id_base_fractura_adjiv FROM b_frac EXCEPT SELECT id_base_fractura_adjiv FROM a_frac)",
            ),
            (
                "records removed in b",
                "SELECT count(*) FROM (SELECT id_base_fractura_adjiv FROM a_frac EXCEPT SELECT id_base_fractura_adjiv FROM b_frac)",
            ),
            (
                "new wells in b",
                "SELECT count(*) FROM (SELECT idpozo FROM b_frac EXCEPT SELECT idpozo FROM a_frac)",
            ),
            (
                "lateral length changed",
                "SELECT count(*) FROM a_frac a JOIN b_frac b USING (id_base_fractura_adjiv) WHERE a.longitud_rama_horizontal_m IS DISTINCT FROM b.longitud_rama_horizontal_m",
            ),
            (
                "stage count changed",
                "SELECT count(*) FROM a_frac a JOIN b_frac b USING (id_base_fractura_adjiv) WHERE a.cantidad_fracturas IS DISTINCT FROM b.cantidad_fracturas",
            ),
            (
                "lateral length filled in (0 -> > 0)",
                "SELECT count(*) FROM a_frac a JOIN b_frac b USING (id_base_fractura_adjiv) WHERE a.longitud_rama_horizontal_m = 0 AND b.longitud_rama_horizontal_m > 0",
            ),
        ],
    )


def diff_downloads(root: Path, a: str, b: str) -> DiffResult:
    fa, fb = root / "data" / "raw" / a, root / "data" / "raw" / b
    for f in (fa, fb):
        if not f.is_dir():
            raise SystemExit(f"no download at {f}")
    con = duckdb.connect(":memory:")
    res = DiffResult(a=a, b=b)
    if _attach(con, fa, "pozos", "a_pozos") and _attach(con, fb, "pozos", "b_pozos"):
        res.sections["pozos"] = diff_pozos(con)
        res.sections["pozos: operator changes"] = operator_changes(con)
    else:
        res.notes.append("`pozos` missing from one of the folders: skipped")
    if _attach(con, fa, "produccion_nc", "a_prod") and _attach(con, fb, "produccion_nc", "b_prod"):
        res.sections["produccion_nc"] = diff_produccion(con)
        res.sections["produccion_nc: rectified well-months by month"] = rectified_by_month(con)
    else:
        res.notes.append("`produccion_nc` missing from one of the folders: skipped")
    if _attach(con, fa, "fractura", "a_frac") and _attach(con, fb, "fractura", "b_frac"):
        res.sections["fractura"] = diff_fractura(con)
    else:
        res.notes.append("`fractura` missing from one of the folders: skipped")
    return res


def render(res: DiffResult) -> str:
    L = [f"# Download diff — {res.a} → {res.b}\n"]
    L.append(
        "What changed between two complete downloads of the public data (`vma/diff.py`). New rows are growth; "
        "changed rows are backward revisions, which is why the raw data is re-downloaded whole and never appended (ADR-005).\n"
    )
    for name, frame in res.sections.items():
        L.append(f"## {name}\n")
        L.append(md_table(frame))
        L.append("")
    for n in res.notes:
        L.append(f"- {n}")
    return "\n".join(L)


def run(root: Path, a: str | None, b: str | None) -> int:
    days = list_downloads(root)
    if a is None or b is None:
        if len(days) < 2:
            print(
                f"only {len(days)} download(s) in data/raw ({', '.join(days) or 'none'}): nothing to compare yet"
            )
            return 0
        a, b = days[-2], days[-1]
    res = diff_downloads(root, a, b)
    out = root / "informes" / f"diff-{a}-{b}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(res), encoding="utf-8")
    for k, v in res.summary().items():
        print(f"{k:60} {v:>12,}")
    print(f"report: {out}")
    return 0
