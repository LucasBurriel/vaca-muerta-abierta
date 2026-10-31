"""Phase 0: measure how dirty the public data is, before building anything on it.

Produces ``informes/calidad-<date>.md`` with tables and ``docs/*.png`` charts:
wells per dataset and how many cross between datasets (by ``idpozo`` and by sigla at
several normalisation levels), operator and formation spelling variants, nulls,
duplicates, impossible ranges, publication lag. Also writes the alias drafts
``alias/operadoras.csv`` and ``alias/formaciones.csv`` for phase 1 to curate.

Everything is computed with DuckDB over the raw CSVs of the latest download; no row is
modified. Charts use a single hue for magnitude and a fixed categorical order.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .download import latest_raw_dir, read_manifest
from .normalize import SIGLA_LEVELS, formation_key, operator_key

# --- palette (single hue for magnitude; fixed categorical order) ------------------------
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
INK = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW]

# Datasets that carry one row per well (or per well-month) and an ``idpozo``.
WELL_TABLES = ["produccion_nc", "pozos", "padron_pozos", "listado_pozos_operadoras", "fractura"]


def connect_raw(root: Path) -> tuple[duckdb.DuckDBPyConnection, dict[str, Any]]:
    raw = latest_raw_dir(root)
    manifest = read_manifest(root)
    con = duckdb.connect(":memory:")
    for m in manifest["sources"]:
        p = raw / m["file"]
        if p.exists():
            con.execute(
                f"CREATE VIEW {m['key']} AS SELECT * FROM read_csv('{p.as_posix()}', header=true, "
                f"ignore_errors=true, sample_size=-1)"
            )
    return con, manifest


def df(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).fetchdf()


def md_table(frame: pd.DataFrame, floatfmt: str = "{:,.2f}") -> str:
    if frame.empty:
        return "_(empty)_"
    cols = list(frame.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in frame.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA:
                cells.append("")
            elif isinstance(v, bool):
                cells.append(str(v))
            elif isinstance(v, float):
                cells.append(floatfmt.format(v) if abs(v - round(v)) > 1e-9 else f"{int(round(v)):,}")
            elif isinstance(v, int):
                cells.append(f"{v:,}")
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# --- 1. wells per dataset ---------------------------------------------------------------


def wells_per_dataset(con: duckdb.DuckDBPyConnection, tables: list[str]) -> pd.DataFrame:
    rows = []
    for t in tables:
        cols = {r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()}
        has_sigla = "sigla" in cols
        n, idp, sig = con.execute(
            f"SELECT count(*), count(DISTINCT idpozo), {'count(DISTINCT sigla)' if has_sigla else 'NULL'} FROM {t}"
        ).fetchone()
        rows.append({"dataset": t, "rows": n, "distinct idpozo": idp, "distinct sigla (raw)": sig})
    return pd.DataFrame(rows)


# --- 2. cross-matching -----------------------------------------------------------------


def well_ids(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    cols = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
    sigla = "sigla" if "sigla" in cols else "NULL::VARCHAR AS sigla"
    return df(con, f"SELECT DISTINCT idpozo, {sigla} FROM {table} WHERE idpozo IS NOT NULL")


def cross_match(con: duckdb.DuckDBPyConnection, base: str, others: list[str]) -> pd.DataFrame:
    """Wells of ``base`` found in each other dataset, by idpozo and by sigla at each level."""
    b = well_ids(con, base)
    rows = []
    for o in others:
        od = well_ids(con, o)
        row = {"dataset": o, "by idpozo": int(b.idpozo.isin(od.idpozo).sum())}
        for name, fn in SIGLA_LEVELS.items():
            bs = set(b.sigla.dropna().map(fn))
            os_ = set(od.sigla.dropna().map(fn))
            row[f"by sigla {name}"] = len(bs & os_) if os_ else None
        rows.append(row)
    out = pd.DataFrame(rows)
    out.insert(1, f"wells in {base}", b.idpozo.nunique())
    return out


def sigla_collisions(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    """At each normalisation level: how many distinct siglas remain and how many map to >1 idpozo."""
    w = well_ids(con, table)
    rows = []
    for name, fn in SIGLA_LEVELS.items():
        k = w.sigla.map(fn)
        g = w.assign(k=k).groupby("k").idpozo.nunique()
        rows.append(
            {"level": name, "distinct siglas": int(g.size), "siglas with >1 idpozo": int((g > 1).sum())}
        )
    return pd.DataFrame(rows)


def sigla_multiplicity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """What differs between rows of ``pozos`` that share a sigla but have different idpozo."""
    return df(
        con,
        "WITH d AS (SELECT sigla FROM pozos GROUP BY sigla HAVING count(DISTINCT idpozo) > 1), "
        "g AS (SELECT p.sigla, count(DISTINCT idpozo) ids, count(DISTINCT formacion) nf, count(DISTINCT empresa) ne, "
        "count(DISTINCT yacimiento) ny FROM pozos p JOIN d USING (sigla) GROUP BY 1) "
        'SELECT count(*) AS "siglas with >1 idpozo", sum(ids) AS "idpozo involved", '
        'count(*) FILTER (WHERE nf > 1) AS "differ in formacion", '
        'count(*) FILTER (WHERE ne > 1) AS "differ in empresa", '
        'count(*) FILTER (WHERE ny > 1) AS "differ in yacimiento" FROM g',
    )


def idpozo_sigla_consistency(con: duckdb.DuckDBPyConnection, a: str, b: str) -> dict[str, int]:
    m = well_ids(con, a).merge(well_ids(con, b), on="idpozo", suffixes=("_a", "_b"))
    return {
        "shared idpozo": len(m),
        "different raw sigla": int((m.sigla_a != m.sigla_b).sum()),
        "different after trim+upper": int(
            (m.sigla_a.str.strip().str.upper() != m.sigla_b.str.strip().str.upper()).sum()
        ),
    }


# --- 3. spelling variants ---------------------------------------------------------------


def operator_variants(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    ops = df(
        con,
        "SELECT 'produccion_nc' ds, empresa name FROM produccion_nc UNION "
        "SELECT 'pozos', empresa FROM pozos UNION "
        "SELECT 'fractura', empresa_informante FROM fractura UNION "
        "SELECT 'pozos_terminados', empresa FROM pozos_terminados",
    ).dropna()
    ops["key"] = ops.name.map(operator_key)
    g = ops.groupby("key").agg(
        variants=("name", lambda s: sorted(set(s))), datasets=("ds", lambda s: sorted(set(s)))
    )
    g["n_variants"] = g.variants.map(len)
    return g.reset_index().sort_values(["n_variants", "key"], ascending=[False, True])


def formation_variants(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    fm = df(
        con,
        "SELECT 'produccion_nc' ds, formacion name, count(DISTINCT idpozo) wells FROM produccion_nc GROUP BY 1,2 UNION ALL "
        "SELECT 'pozos', formacion, count(DISTINCT idpozo) FROM pozos GROUP BY 1,2 UNION ALL "
        "SELECT 'fractura', formacion_productiva, count(DISTINCT idpozo) FROM fractura GROUP BY 1,2",
    ).dropna(subset=["name"])
    fm["key"] = fm.name.map(formation_key)
    g = fm.groupby("key").agg(
        variants=("name", lambda s: sorted(set(s))),
        datasets=("ds", lambda s: sorted(set(s))),
        wells=("wells", "sum"),
    )
    g["n_variants"] = g.variants.map(len)
    return g.reset_index().sort_values(["n_variants", "wells"], ascending=[False, False])


def write_alias_drafts(root: Path, ops: pd.DataFrame, fms: pd.DataFrame) -> None:
    alias = root / "alias"
    alias.mkdir(exist_ok=True)
    with (alias / "operadoras.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "canonical", "key", "datasets", "status"])
        for _, r in ops.iterrows():
            canonical = max(r.variants, key=len)
            for v in r.variants:
                w.writerow(
                    [v, canonical, r.key, ";".join(r.datasets), "draft" if r.n_variants > 1 else "single"]
                )
    with (alias / "formaciones.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["alias", "canonical", "key", "datasets", "wells", "status"])
        for _, r in fms.iterrows():
            canonical = max(r.variants, key=len).title()  # keep accents (ñ, í) of the published spelling
            for v in r.variants:
                w.writerow(
                    [
                        v,
                        canonical,
                        r.key,
                        ";".join(r.datasets),
                        int(r.wells),
                        "draft" if r.n_variants > 1 else "single",
                    ]
                )


# --- 4. nulls, duplicates, impossible ranges -------------------------------------------


def top_nulls(con: duckdb.DuckDBPyConnection, table: str, top: int = 8) -> pd.DataFrame:
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    parts = ", ".join(
        f'count(*) FILTER (WHERE "{c}" IS NULL OR trim(CAST("{c}" AS VARCHAR)) = \'\') AS "{c}"' for c in cols
    )
    r = con.execute(f"SELECT {parts} FROM {table}").fetchdf().T.reset_index()
    r.columns = ["column", "nulls"]
    r["null %"] = (100 * r.nulls / n).round(2)
    r = r[r.nulls > 0].sort_values("nulls", ascending=False).head(top)
    r.insert(0, "dataset", table)
    return r


def duplicates(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    checks = {
        "produccion_nc: (idpozo, anio, mes)": "SELECT count(*) - count(DISTINCT (idpozo, anio, mes)) FROM produccion_nc",
        "produccion_nc: sigla -> >1 idpozo": (
            "SELECT count(*) FROM (SELECT sigla FROM (SELECT DISTINCT sigla, idpozo FROM produccion_nc) "
            "GROUP BY sigla HAVING count(*) > 1)"
        ),
        "pozos: idpozo": "SELECT count(*) - count(DISTINCT idpozo) FROM pozos",
        "pozos: sigla -> >1 idpozo": (
            "SELECT count(*) FROM (SELECT sigla FROM pozos GROUP BY sigla HAVING count(DISTINCT idpozo) > 1)"
        ),
        "pozos: sigla trim+upper -> >1 idpozo": (
            "SELECT count(*) FROM (SELECT upper(trim(sigla)) s FROM pozos GROUP BY s HAVING count(DISTINCT idpozo) > 1)"
        ),
        "padron_pozos: idpozo": "SELECT count(*) - count(DISTINCT idpozo) FROM padron_pozos",
        "listado_pozos_operadoras: idpozo": "SELECT count(*) - count(DISTINCT idpozo) FROM listado_pozos_operadoras",
        "fractura: idpozo (wells with >1 fracture record)": (
            "SELECT count(*) FROM (SELECT idpozo FROM fractura GROUP BY idpozo HAVING count(*) > 1)"
        ),
        "fractura: exact duplicate rows (all columns but id)": (
            "SELECT count(*) - count(DISTINCT (idpozo, fecha_inicio_fractura, fecha_fin_fractura, cantidad_fracturas, "
            "longitud_rama_horizontal_m, arena_bombeada_nacional_tn, arena_bombeada_importada_tn, agua_inyectada_m3)) FROM fractura"
        ),
    }
    return pd.DataFrame([{"check": k, "count": con.execute(q).fetchone()[0]} for k, q in checks.items()])


def impossible_ranges(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    checks = [
        ("produccion_nc", "prod_pet < 0", "negative oil"),
        ("produccion_nc", "prod_gas < 0", "negative gas"),
        ("produccion_nc", "prod_agua < 0", "negative water"),
        ("produccion_nc", "tef > 31", "producing days > 31"),
        ("produccion_nc", "tef = 0 AND (prod_pet > 0 OR prod_gas > 0)", "production with 0 producing days"),
        ("produccion_nc", "profundidad > 8000", "depth > 8,000 m"),
        ("produccion_nc", "profundidad = 0", "depth = 0"),
        ("produccion_nc", "coordenadax > -50", "coordenadax looks like a latitude (x/y swapped?)"),
        ("produccion_nc", "coordenaday < -56 OR coordenaday > -21", "latitude outside Argentina"),
        ("produccion_nc", "make_date(anio, mes, 1) > current_date", "month in the future"),
        (
            "pozos",
            "adjiv_fecha_inicio_perf < DATE '1950-01-01'",
            "drilling start before 1950 (incl. 1900-01-01 placeholders)",
        ),
        ("pozos", "adjiv_fecha_fin_perf < adjiv_fecha_inicio_perf", "drilling end before start"),
        ("pozos", "adjiv_fecha_inicio_term < adjiv_fecha_fin_perf", "completion start before drilling end"),
        ("pozos", "profundidad = 0", "depth = 0"),
        ("pozos", "profundidad > 8000", "depth > 8,000 m"),
        ("pozos", "cota < -100 OR cota > 5000", "elevation outside [-100, 5000] m"),
        ("pozos", "sigla <> trim(sigla)", "sigla with leading/trailing spaces"),
        ("fractura", "fecha_inicio_fractura > current_date", "fracture start in the future"),
        ("fractura", "fecha_fin_fractura < fecha_inicio_fractura", "fracture end before start"),
        ("fractura", "longitud_rama_horizontal_m = 0", "lateral length = 0"),
        (
            "fractura",
            "longitud_rama_horizontal_m = 0 AND cantidad_fracturas >= 10",
            "lateral = 0 with >= 10 stages (horizontal well, missing length)",
        ),
        ("fractura", "longitud_rama_horizontal_m > 5000", "lateral > 5,000 m"),
        ("fractura", "cantidad_fracturas > 100", "> 100 stages"),
        (
            "fractura",
            "arena_bombeada_nacional_tn + arena_bombeada_importada_tn = 0 AND cantidad_fracturas > 0",
            "stages but 0 proppant",
        ),
        ("fractura", "agua_inyectada_m3 = 0 AND cantidad_fracturas > 0", "stages but 0 water"),
        (
            "fractura",
            "longitud_rama_horizontal_m > 0 AND (arena_bombeada_nacional_tn + arena_bombeada_importada_tn) / longitud_rama_horizontal_m > 10",
            "proppant intensity > 10 t/m",
        ),
        ("fractura", "presion_maxima_psi > 20000", "max pressure > 20,000 psi"),
    ]
    rows = []
    for t, cond, label in checks:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        c = con.execute(f"SELECT count(*) FROM {t} WHERE {cond}").fetchone()[0]
        rows.append(
            {"dataset": t, "rule": label, "rows": c, "% of dataset": round(100 * c / n, 3), "sql": cond}
        )
    return pd.DataFrame(rows)


# --- 5. publication lag -----------------------------------------------------------------


def publication_lag(con: duckdb.DuckDBPyConnection, manifest: dict[str, Any], today: date) -> pd.DataFrame:
    last_month = {
        "produccion_nc": "SELECT max(make_date(anio, mes, 1)) FROM produccion_nc",
        "padron_pozos": "SELECT max(make_date(anio, mes, 1)) FROM padron_pozos",
        "fractura": "SELECT max(date_trunc('month', fecha_inicio_fractura)) FROM fractura WHERE fecha_inicio_fractura <= current_date",
        "pozos": "SELECT max(date_trunc('month', adjiv_fecha_fin_term)) FROM pozos WHERE adjiv_fecha_fin_term <= current_date",
        "pozos_terminados": "SELECT max(make_date(anio, mes, 1)) FROM pozos_terminados",
        "pozos_en_perforacion": "SELECT max(make_date(anio, mes, 1)) FROM pozos_en_perforacion",
        "listado_pozos_operadoras": "SELECT max(CAST(fechadeingreso AS DATE)) FROM listado_pozos_operadoras",
    }
    meta = {m["key"]: m for m in manifest["sources"]}
    rows = []
    for k, q in last_month.items():
        if k not in meta:
            continue
        last = con.execute(q).fetchone()[0]
        last = pd.Timestamp(last).date() if last is not None else None
        lag_months = None
        if last:
            lag_months = (today.year - last.year) * 12 + today.month - last.month
        rows.append(
            {
                "dataset": k,
                "last month with data": last.strftime("%Y-%m") if last else None,
                "lag (months)": lag_months,
                "CKAN last_modified": (meta[k].get("ckan_last_modified") or "")[:10],
            }
        )
    return pd.DataFrame(rows)


def monthly_counts(con: duckdb.DuckDBPyConnection, months: int = 36) -> pd.DataFrame:
    return df(
        con,
        f"SELECT make_date(anio, mes, 1) AS month, count(DISTINCT idpozo) AS wells, "
        f"count(*) FILTER (WHERE prod_pet > 0 OR prod_gas > 0) AS producing FROM produccion_nc "
        f"GROUP BY 1 ORDER BY 1 DESC LIMIT {months}",
    ).sort_values("month")


def fracture_monthly(con: duckdb.DuckDBPyConnection, months: int = 36) -> pd.DataFrame:
    return df(
        con,
        f"SELECT date_trunc('month', fecha_inicio_fractura) AS month, count(DISTINCT idpozo) AS wells FROM fractura "
        f"WHERE fecha_inicio_fractura <= current_date AND cuenca = 'NEUQUINA' GROUP BY 1 ORDER BY 1 DESC LIMIT {months}",
    ).sort_values("month")


# --- charts -----------------------------------------------------------------------------


def _style(ax, title: str, ylabel: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b", pad=10)
    ax.set_ylabel(ylabel, color=INK, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_facecolor(SURFACE)


def make_charts(
    docs: Path,
    wells: pd.DataFrame,
    cross: pd.DataFrame,
    nulls: pd.DataFrame,
    monthly: pd.DataFrame,
    frac_monthly: pd.DataFrame,
    con: duckdb.DuckDBPyConnection,
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})
    out = []

    # 1. wells per dataset
    fig, ax = plt.subplots(figsize=(8, 3.6))
    w = wells.sort_values("distinct idpozo", ascending=True)
    ax.barh(w.dataset, w["distinct idpozo"], color=BLUE, height=0.55)
    for y, v in enumerate(w["distinct idpozo"]):
        ax.text(v, y, f" {v:,}", va="center", fontsize=8, color=INK)
    _style(ax, "Distinct wells (idpozo) per dataset")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    ax.set_xlim(0, w["distinct idpozo"].max() * 1.18)
    fig.tight_layout()
    p = docs / "calidad-pozos-por-dataset.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 2. cross-match of production wells against fractura / pozos: idpozo vs sigla levels
    fig, ax = plt.subplots(figsize=(8, 3.8))
    sub = cross[cross.dataset.isin(["pozos", "fractura", "listado_pozos_operadoras"])]
    levels = ["by idpozo"] + [c for c in cross.columns if c.startswith("by sigla")]
    labels = ["idpozo"] + [c.replace("by sigla ", "") for c in levels[1:]]
    x = range(len(levels))
    width = 0.26
    for i, (_, r) in enumerate(sub.iterrows()):
        ax.bar(
            [xx + (i - 1) * width for xx in x],
            [r[c] for c in levels],
            width=width * 0.92,
            color=CATEGORICAL[i],
            label=r.dataset,
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=0, fontsize=7.5)
    _style(ax, "Unconventional production wells matched in other datasets, by join key", "wells")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout()
    p = docs / "calidad-cruce-por-clave.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 3. active wells per month (36 months) + fractured wells per month
    fig, axes = plt.subplots(2, 1, figsize=(8, 5.2), sharex=False)
    ax = axes[0]
    ax.plot(monthly.month, monthly.wells, color=BLUE, linewidth=2, label="wells with a monthly record")
    ax.plot(
        monthly.month,
        monthly.producing,
        color=ORANGE,
        linewidth=2,
        label="of which producing (oil or gas > 0)",
    )
    _style(ax, "Unconventional wells reported per month (last 36 months)", "wells")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax = axes[1]
    ax.bar(frac_monthly.month, frac_monthly.wells, width=20, color=BLUE)
    _style(ax, "Wells with a fracture start in the month, Neuquina basin (last 36 months)", "wells")
    fig.tight_layout()
    p = docs / "calidad-atraso-publicacion.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 4. top null columns
    fig, ax = plt.subplots(figsize=(8, 4.6))
    nn = nulls.sort_values("null %", ascending=True).tail(16)
    lab = nn.dataset + " · " + nn.column
    ax.barh(lab, nn["null %"], color=BLUE, height=0.6)
    for y, v in enumerate(nn["null %"]):
        ax.text(v, y, f" {v:.1f}%", va="center", fontsize=7.5, color=INK)
    _style(ax, "Columns with the most empty values (NULL or blank)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    ax.set_xlim(0, 118)
    ax.tick_params(axis="y", labelsize=7.5)
    fig.tight_layout()
    p = docs / "calidad-nulos.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 5. lateral length and proppant intensity distributions (fracture, unconventional Neuquina)
    fr = df(
        con,
        "SELECT longitud_rama_horizontal_m AS lat, "
        "(arena_bombeada_nacional_tn + arena_bombeada_importada_tn) AS arena, cantidad_fracturas AS etapas "
        "FROM fractura WHERE cuenca = 'NEUQUINA' AND tipo_reservorio = 'NO CONVENCIONAL'",
    )
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.6))
    ax = axes[0]
    ax.hist(fr.lat, bins=60, color=BLUE)
    _style(ax, "Lateral length (m), unconventional Neuquina", "fracture records")
    n0 = int((fr.lat == 0).sum())
    ax.annotate(
        f"{n0:,} records with length = 0",
        xy=(0.12, 0.92),
        xycoords="axes fraction",
        fontsize=8,
        color=INK,
        va="top",
    )
    ax = axes[1]
    ok = fr[fr.lat > 0]
    inten = ok.arena / ok.lat
    ax.hist(inten.clip(upper=8), bins=60, color=BLUE)
    _style(ax, "Proppant intensity (t/m), length > 0", "")
    ax.annotate(
        f"{int((inten > 5).sum()):,} records > 5 t/m (clipped at 8)",
        xy=(0.98, 0.92),
        xycoords="axes fraction",
        fontsize=8,
        color=INK,
        va="top",
        ha="right",
    )
    fig.tight_layout()
    p = docs / "calidad-fractura-distribuciones.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)
    return out


# --- report -----------------------------------------------------------------------------


def build_report(root: Path, today: date | None = None) -> Path:
    today = today or date.today()
    con, manifest = connect_raw(root)
    raw = latest_raw_dir(root)
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    informes = root / "informes"
    informes.mkdir(exist_ok=True)
    present = [t for t in WELL_TABLES if t in {m["key"] for m in manifest["sources"]}]

    wells = wells_per_dataset(con, present)
    cross = cross_match(con, "produccion_nc", [t for t in present if t != "produccion_nc"])
    cross_f = cross_match(con, "fractura", ["produccion_nc", "pozos"])
    coll = sigla_collisions(con, "pozos")
    mult = sigla_multiplicity(con)
    cons = idpozo_sigla_consistency(con, "produccion_nc", "pozos")
    cons_f = idpozo_sigla_consistency(con, "fractura", "pozos")
    ops = operator_variants(con)
    fms = formation_variants(con)
    write_alias_drafts(root, ops, fms)
    nulls = pd.concat(
        [
            top_nulls(con, t)
            for t in present + ["pozos_terminados", "pozos_en_perforacion"]
            if t in {m["key"] for m in manifest["sources"]}
        ]
    )
    dups = duplicates(con)
    ranges = impossible_ranges(con)
    lag = publication_lag(con, manifest, today)
    monthly = monthly_counts(con)
    frac_m = fracture_monthly(con)
    make_charts(docs, wells, cross, nulls, monthly, frac_m, con)

    basin = df(
        con,
        'SELECT cuenca, sub_tipo_recurso, count(DISTINCT idpozo) wells, count(*) "well-months" FROM produccion_nc '
        "GROUP BY 1,2 ORDER BY 3 DESC",
    )
    frac_basin = df(
        con,
        "SELECT cuenca, tipo_reservorio, subtipo_reservorio, count(*) records, count(DISTINCT idpozo) wells FROM fractura "
        "GROUP BY 1,2,3 ORDER BY 4 DESC",
    )
    perf_shape = df(con, "SELECT concepto, count(*) rows FROM pozos_terminados GROUP BY 1 ORDER BY 2 DESC")
    multi_ops = ops[ops.n_variants > 1][["key", "variants", "datasets"]].copy()
    multi_ops["variants"] = multi_ops.variants.map(lambda v: " · ".join(v))
    multi_ops["datasets"] = multi_ops.datasets.map(lambda v: ", ".join(v))
    top_fm = fms.head(15)[["key", "variants", "datasets", "wells"]].copy()
    top_fm["variants"] = top_fm.variants.map(lambda v: " · ".join(v))
    top_fm["datasets"] = top_fm.datasets.map(lambda v: ", ".join(v))

    man_rows = pd.DataFrame(
        [
            {
                "key": m["key"],
                "bytes": m["bytes"],
                "sha256": m["sha256"][:12] + "…",
                "CKAN last_modified": (m.get("ckan_last_modified") or "")[:10],
            }
            for m in manifest["sources"]
        ]
    )

    L: list[str] = []
    L += [f"# Data quality report — {today.isoformat()}", ""]
    L += [
        "Phase 0 of the observatory: *measure the dirt before building on it*. Every number below is",
        f"computed by `vma/quality.py` over the raw files in `data/raw/{raw.name}/` (never modified).",
        "Scope of this first pass: the Neuquina basin, unconventional wells; conventional yearly files were not downloaded.",
        "",
        "## 0. What was downloaded",
        "",
        md_table(man_rows),
        "",
        "## 1. Wells per dataset",
        "",
        md_table(wells),
        "",
        "![wells per dataset](../docs/calidad-pozos-por-dataset.png)",
        "",
        "Unconventional production by basin and resource sub-type:",
        "",
        md_table(basin),
        "",
        "Fracture records (Adjunto IV) by basin and reservoir type:",
        "",
        md_table(frac_basin),
        "",
        "**The drilling datasets are not per well.** `pozos_terminados` and `pozos_en_perforacion` are monthly",
        "counts (`cantidad`) by company × area × concept, with no `idpozo` or `sigla`:",
        "",
        md_table(perf_shape),
        "",
        "Per-well drilling and completion dates exist only in `pozos` (`adjiv_fecha_inicio_perf`, `adjiv_fecha_fin_perf`,",
        "`adjiv_fecha_inicio_term`, `adjiv_fecha_fin_term`), 40 % empty. Cycle-time indicators will depend on that table.",
        "",
        "## 2. Cross-matching between datasets",
        "",
        "Wells of `produccion_nc` found in each other dataset. `by idpozo` joins on the numeric id; the `by sigla` columns",
        "join on the well code after each normalisation level of `vma/normalize.py` (L0 raw → L4 letters and digits only).",
        "",
        md_table(cross),
        "",
        "Same thing from the fracture dataset's point of view:",
        "",
        md_table(cross_f),
        "",
        "![cross-match](../docs/calidad-cruce-por-clave.png)",
        "",
        f"Consistency of the two keys: for the {cons['shared idpozo']:,} wells shared by `produccion_nc` and `pozos`,",
        f"{cons['different raw sigla']:,} have a different raw sigla ({cons['different after trim+upper']:,} after trim+upper);",
        f"for the {cons_f['shared idpozo']:,} shared by `fractura` and `pozos`, {cons_f['different raw sigla']:,} differ raw",
        f"({cons_f['different after trim+upper']:,} after trim+upper).",
        "",
        "Siglas are *not* unique per well. In `pozos`, at each normalisation level:",
        "",
        md_table(coll),
        "",
        "Why: `idpozo` identifies a **well x productive formation**, not a physical well. The same sigla gets a new",
        "`idpozo` for each formation it is reported on (the operator register even has a `unique_sigla_formprod` flag):",
        "",
        md_table(mult),
        "",
        "## 3. Spelling variants",
        "",
        f"### Operators — {len(ops):,} distinct blocking keys, {len(multi_ops):,} with more than one spelling",
        "",
        "Blocking key: accents removed, upper-case, legal forms (S.A., S.R.L., SAU, LLC, Sucursal Argentina…) and",
        "punctuation stripped. Inside `produccion_nc` the pair `idempresa → empresa` is one-to-one; variants appear",
        "*between* datasets. Full draft in `alias/operadoras.csv`.",
        "",
        md_table(multi_ops),
        "",
        f"### Formations — {len(fms):,} distinct keys, {int((fms.n_variants > 1).sum()):,} with more than one spelling",
        "",
        "Formation names are already lower-case and consistent across the three datasets that carry them; the real",
        "problem is granularity (`vaca muerta` has no landing level) and the `formprod` 4-letter code that only",
        "`produccion_nc` has. Top 15 by wells; full draft in `alias/formaciones.csv`.",
        "",
        md_table(top_fm),
        "",
        "## 4. Nulls, duplicates, impossible values",
        "",
        "### Columns with most empty values (top 8 per dataset)",
        "",
        md_table(nulls[["dataset", "column", "nulls", "null %"]]),
        "",
        "![nulls](../docs/calidad-nulos.png)",
        "",
        "### Duplicates",
        "",
        md_table(dups),
        "",
        "### Impossible or suspicious values",
        "",
        "Each rule is a SQL predicate over the raw table; rows are counted, not removed (outliers are shown, not deleted).",
        "",
        md_table(ranges[["dataset", "rule", "rows", "% of dataset"]]),
        "",
        "![fracture distributions](../docs/calidad-fractura-distribuciones.png)",
        "",
        "## 5. Publication lag",
        "",
        f"Download date: {today.isoformat()}.",
        "",
        md_table(lag),
        "",
        "![publication lag](../docs/calidad-atraso-publicacion.png)",
        "",
        "The monthly series of wells with a production record keeps growing to the last month: the unconventional file",
        "is published complete up to its last month (no trailing partial month) and revised backwards instead. The",
        "fracture dataset is the opposite: the last 3-4 months are visibly incomplete even though CKAN calls it a",
        "daily update, so fracture-based indicators must exclude a trailing window.",
        "",
        "## 6. Rules used",
        "",
        "Impossible-value predicates, verbatim:",
        "",
        md_table(ranges[["dataset", "rule", "sql"]]),
        "",
    ]
    report = informes / f"calidad-{today.isoformat()}.md"
    report.write_text("\n".join(L), encoding="utf-8")
    return report
