"""The F2 report: ``informes/indicadores-<date>.md`` with charts in ``docs/indicadores-*.png``.

Numbers come from the indicators and type-curve tables just built; every table says which
column and which filter produced it. Nothing here changes the data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .indicadores import ACUM_MESES, IP_DIAS, OUTLIER_COL, OUTLIER_N_MIN, OUTLIER_Z, RAMA_MIN_M, SEP
from .quality import BLUE, GRID, INK, MUTED, ORANGE, SURFACE, md_table

VM = "Vaca Muerta"
IP90_M = OUTLIER_COL


def _count_flag(table: pd.DataFrame, flag: str) -> int:
    return int(table["flags"].fillna("").str.split(SEP).map(lambda fs: flag in fs).sum())


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}" if d else ""


# --- charts -------------------------------------------------------------------------------------------


def make_charts(docs: Path, ind: pd.DataFrame, curvas: pd.DataFrame) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import colormaps

    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})
    out: list[Path] = []

    def style(ax, title, ylabel=""):
        ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b", pad=10)
        ax.set_ylabel(ylabel, color=INK, fontsize=9)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.set_axisbelow(True)
        ax.set_facecolor(SURFACE)
        ax.yaxis.grid(True, color=GRID, linewidth=0.8)

    vm = ind[ind.en_alcance & (ind.formacion == VM)]

    # 1. type curve: P50 oil rate per metre, Vaca Muerta oil window, by cohort (without outliers)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    c = curvas[
        (curvas.nivel == "cohorte_formacion_ventana")
        & (curvas.formacion == VM)
        & (curvas.ventana == "petroleo")
        & (~curvas.incluye_outliers)
        & (curvas.mes <= 36)
        & curvas.publicable
    ]
    cohorts = sorted(int(x) for x in c.cohorte.dropna().unique() if 2016 <= int(x) <= 2025)
    cmap = colormaps["viridis"]
    for i, co in enumerate(cohorts):
        s = c[c.cohorte == co].sort_values("mes")
        s = s[s.petroleo_m3_d_por_m_p50.notna()]
        if s.empty:
            continue
        n0 = int(s.n_pozos_por_m.iloc[0])
        ax.plot(
            s.mes,
            s.petroleo_m3_d_por_m_p50,
            color=cmap(i / max(1, len(cohorts) - 1)),
            linewidth=1.6,
            label=f"{co} (n={n0})",
        )
    style(ax, f"{VM}, oil window: P50 oil rate per metre of lateral, by cohort", "m³/d per m")
    ax.set_xlabel("months since first production", color=INK, fontsize=9)
    ax.legend(
        frameon=False,
        fontsize=7.5,
        ncol=2,
        title="first-production year (wells at month 0)",
        title_fontsize=7.5,
    )
    fig.tight_layout()
    p = docs / "indicadores-curva-tipo-vaca-muerta.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 2. IP90 per metre by operator, Vaca Muerta, median with n
    fig, ax = plt.subplots(figsize=(8, 4.4))
    s = vm[
        vm.ip90_petroleo_m3_d_por_m.notna()
        & (vm.ventana == "petroleo")
        & ~vm.outlier_ip90_m.fillna(False).astype(bool)
    ]
    g = s.groupby("operadora").ip90_petroleo_m3_d_por_m.agg(["median", "size"])
    g = g[g["size"] >= 5].sort_values("median").tail(14)
    ax.barh(g.index, g["median"], color=BLUE, height=0.62)
    for y, (med, n) in enumerate(zip(g["median"], g["size"], strict=True)):
        ax.text(med, y, f"  {med:.3f}  (n={int(n)})", va="center", fontsize=7.5, color=INK)
    style(ax, f"{VM}, oil window: median IP90 oil per metre by operator (n >= 5)")
    ax.set_xlabel("m³/d per m", color=INK, fontsize=9)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlim(0, g["median"].max() * 1.35)
    fig.tight_layout()
    p = docs / "indicadores-ip90-por-operadora.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 3. lateral length by cohort, Vaca Muerta
    fig, ax = plt.subplots(figsize=(8, 3.9))
    r = vm[vm.rama_normalizable & vm.cohorte.notna()]
    cohorts = sorted(int(x) for x in r.cohorte.unique() if int(x) >= 2013)
    data = [r[r.cohorte == co].rama_m.to_numpy() for co in cohorts]
    bp = ax.boxplot(
        data, tick_labels=[str(c) for c in cohorts], showfliers=False, patch_artist=True, widths=0.6
    )
    for box in bp["boxes"]:
        box.set(facecolor=BLUE, alpha=0.75, edgecolor=BLUE)
    for k in ("whiskers", "caps", "medians"):
        for line in bp[k]:
            line.set(color=INK if k != "medians" else ORANGE, linewidth=1.2)
    for i, d in enumerate(data):
        ax.text(i + 1, 0, f"n={len(d)}", ha="center", va="bottom", fontsize=7, color=MUTED)
    style(
        ax, f"{VM}: lateral length by first-production year (rama_m >= {RAMA_MIN_M:.0f} m; box P25-P75)", "m"
    )
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    p = docs / "indicadores-rama-por-cohorte.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)

    # 4. GOR at 12 months by cohort, Vaca Muerta: median with P25-P75 band
    fig, ax = plt.subplots(figsize=(8, 3.9))
    gg = vm[vm.gor12_m3_m3.notna() & vm.cohorte.notna()]
    q = gg.groupby("cohorte").gor12_m3_m3.quantile([0.25, 0.5, 0.75]).unstack()
    q["n"] = gg.groupby("cohorte").size()
    q = q[(q.n >= 5) & (q.index >= 2013)]
    x = q.index.astype(int)
    ax.fill_between(x, q[0.25], q[0.75], color=BLUE, alpha=0.18, linewidth=0, label="P25-P75")
    ax.plot(x, q[0.5], color=BLUE, linewidth=1.8, marker="o", markersize=3.5, label="median")
    for xi, med, n in zip(x, q[0.5], q.n, strict=True):
        ax.text(xi, med, f" n={int(n)}", fontsize=6.5, color=MUTED, va="bottom", ha="left")
    ax.set_yscale("log")
    style(ax, f"{VM}: GOR at 12 months by first-production year (all windows, log scale)", "m³/m³")
    ax.set_xticks(list(x))
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    p = docs / "indicadores-gor-por-cohorte.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)
    return out


# --- report -----------------------------------------------------------------------------------------------


def build_report(
    root: Path,
    ind: pd.DataFrame,
    curvas: pd.DataFrame,
    monthly: pd.DataFrame,
    day: date,
    version_maestro: str,
) -> Path:
    informes = root / "informes"
    informes.mkdir(exist_ok=True)
    docs = root / "docs"
    make_charts(docs, ind, curvas)

    scope = ind[ind.en_alcance]
    prod = scope[scope.primera_produccion.notna()]
    n_scope, n_prod = len(scope), len(prod)
    vm = scope[scope.formacion == VM]
    raw_day = ind.fecha_descarga.iloc[0] if len(ind) else ""

    L: list[str] = []
    L.append(f"# Indicators and type curves report — {day.isoformat()}\n")
    L.append(
        "Phase 2 of the observatory: *per-well indicators with lineage, type curves by cohort, outliers marked*. Built by "
        f"`vma/indicadores.py` and `vma/curvas.py` from the master `data/publicado/{version_maestro}/pozos.parquet` and the raw "
        f"production of `data/raw/{raw_day}/`, published as `data/publicado/{day.isoformat()}/indicadores.{{csv,parquet}}` and "
        f"`curvas_tipo.{{csv,parquet}}` (not versioned; rebuild with `python pipeline.py indicadores` and `python pipeline.py curvas`). "
        "Column definitions, formulas and rules: [`docs/indicadores.md`](../docs/indicadores.md). Decisions: ADR-015 to ADR-020 in "
        "[`docs/decisiones.md`](../docs/decisiones.md).\n"
    )
    L.append(
        f"Scope (ADR-002): `cuenca = NEUQUINA` and `tipo_recurso = NO CONVENCIONAL` → **{n_scope:,}** of {len(ind):,} master wells "
        f"(`en_alcance`); the other {len(ind) - n_scope:,} stay in the table with `fuera_alcance` and no outlier screening. "
        f"{n_prod:,} in-scope wells have a first production month (the rest: `sin_produccion` / `nunca_produjo`).\n"
    )

    # 1. coverage
    L.append("## 1. Coverage: how many in-scope wells have each indicator\n")
    rows = []
    for h in IP_DIAS:
        rows.append(
            {
                "indicator": f"`ip{h}_*` (needs >= {h} producing days)",
                "wells": int(scope[f"ip{h}_petroleo_m3_d"].notna().sum()),
                "% of producing": _pct(int(scope[f"ip{h}_petroleo_m3_d"].notna().sum()), n_prod),
            }
        )
    for n in ACUM_MESES:
        rows.append(
            {
                "indicator": f"`acum{n}_*` (needs {n} months of history)",
                "wells": int(scope[f"acum{n}_petroleo_m3"].notna().sum()),
                "% of producing": _pct(int(scope[f"acum{n}_petroleo_m3"].notna().sum()), n_prod),
            }
        )
    rows.append(
        {
            "indicator": f"per-metre values (`rama_normalizable`: rama_m >= {RAMA_MIN_M:.0f} m)",
            "wells": int(scope.rama_normalizable.sum()),
            "% of producing": _pct(int(scope.rama_normalizable.sum()), n_prod),
        }
    )
    rows.append(
        {
            "indicator": "`ip90_*_por_m`",
            "wells": int(scope[IP90_M].notna().sum()),
            "% of producing": _pct(int(scope[IP90_M].notna().sum()), n_prod),
        }
    )
    rows.append(
        {
            "indicator": "`acum12_*_por_m`",
            "wells": int(scope.acum12_equivalente_m3_por_m.notna().sum()),
            "% of producing": _pct(int(scope.acum12_equivalente_m3_por_m.notna().sum()), n_prod),
        }
    )
    rows.append(
        {
            "indicator": "`gor12_m3_m3` (oil > 0 in the first 12 months)",
            "wells": int(scope.gor12_m3_m3.notna().sum()),
            "% of producing": _pct(int(scope.gor12_m3_m3.notna().sum()), n_prod),
        }
    )
    rows.append(
        {
            "indicator": "`ventana` (fluid window from GOR; `ventana_provisoria` when not from GOR12)",
            "wells": int(scope.ventana.notna().sum()),
            "% of producing": _pct(int(scope.ventana.notna().sum()), n_prod),
        }
    )
    rows.append(
        {
            "indicator": "`corte_agua12`",
            "wells": int(scope.corte_agua12.notna().sum()),
            "% of producing": _pct(int(scope.corte_agua12.notna().sum()), n_prod),
        }
    )
    L.append(md_table(pd.DataFrame(rows)))
    L.append("\nWhy per-metre values are null (in-scope wells, one reason per well):\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {"flag": f"`{f}`", "wells": _count_flag(scope, f)}
                    for f in (
                        "sin_rama_sin_fractura",
                        "sin_rama_faltante",
                        "sin_rama_cero",
                        "sin_rama",
                        "rama_corta",
                    )
                ]
            )
        )
    )
    L.append("\nEffective-days anomalies handled by rule (in-scope wells with at least one such month):\n")
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {
                        "flag": "`tef_cero_con_produccion` (production with 0 days → whole month assumed)",
                        "wells": _count_flag(scope, "tef_cero_con_produccion"),
                    },
                    {
                        "flag": "`tef_mayor_mes` (more days than the month → capped)",
                        "wells": _count_flag(scope, "tef_mayor_mes"),
                    },
                    {
                        "flag": f"`primer_mes_parcial` (first month with < {15} producing days)",
                        "wells": _count_flag(scope, "primer_mes_parcial"),
                    },
                    {
                        "flag": "`produccion_suma_idpozo` (two or more idpozo summed in one month)",
                        "wells": _count_flag(scope, "produccion_suma_idpozo"),
                    },
                    {"flag": "`volumen_negativo`", "wells": _count_flag(scope, "volumen_negativo")},
                    {
                        "flag": "`acum12_meses_faltantes` (gap months counted as zero)",
                        "wells": _count_flag(scope, "acum12_meses_faltantes"),
                    },
                ]
            )
        )
    )

    # 2. medians by formation
    L.append("\n## 2. Medians by formation (in-scope, outliers excluded from the per-metre columns)\n")
    clean = scope[~scope.outlier_ip90_m.fillna(False).astype(bool)]
    fm = (
        clean.groupby("formacion")
        .agg(
            wells=("sigla_clave", "size"),
            with_ip90_m=(IP90_M, "count"),
            rama_m=("rama_m", "median"),
            etapas_por_100m=("etapas_por_100m", "median"),
            ip90_eq_m3_d=("ip90_equivalente_m3_d", "median"),
            ip90_eq_por_m=(IP90_M, "median"),
            acum12_eq_por_m=("acum12_equivalente_m3_por_m", "median"),
            gor12=("gor12_m3_m3", "median"),
            corte_agua12=("corte_agua12", "median"),
        )
        .sort_values("wells", ascending=False)
        .head(8)
        .reset_index()
    )
    fm["rama_m"] = fm.rama_m.round(0)
    fm.columns = [
        "formacion",
        "wells",
        "with ip90/m",
        "median rama_m",
        "median etapas/100 m",
        "median IP90 eq (m³/d)",
        "median IP90 eq per m",
        "median acum12 eq per m (m³/m)",
        "median GOR12 (m³/m³)",
        "median water cut 12",
    ]
    L.append(md_table(fm, floatfmt="{:,.3f}"))

    # 3. by cohort, Vaca Muerta
    L.append(f"\n## 3. {VM} by cohort (first-production year; outliers excluded)\n")
    vmc = vm[~vm.outlier_ip90_m.fillna(False).astype(bool) & vm.cohorte.notna()]
    co = (
        vmc.groupby("cohorte")
        .agg(
            wells=("sigla_clave", "size"),
            with_ip90_m=(IP90_M, "count"),
            rama_m=("rama_m", "median"),
            etapas_por_100m=("etapas_por_100m", "median"),
            ip90_eq_por_m=(IP90_M, "median"),
            ip90_oil_por_m=("ip90_petroleo_m3_d_por_m", "median"),
            acum12_eq_por_m=("acum12_equivalente_m3_por_m", "median"),
            gor12=("gor12_m3_m3", "median"),
        )
        .reset_index()
    )
    co = co[co.cohorte >= 2012]
    co["rama_m"] = co.rama_m.round(0)
    share_gas = vmc[vmc.ventana.notna()].groupby("cohorte").ventana.apply(lambda v: 100 * (v == "gas").mean())
    co["% gas window"] = co.cohorte.map(share_gas).round(0)
    co["cohorte"] = co.cohorte.astype(str)
    co.columns = [
        "cohorte",
        "wells",
        "with ip90/m",
        "median rama_m",
        "median etapas/100 m",
        "median IP90 eq per m",
        "median IP90 oil per m",
        "median acum12 eq per m",
        "median GOR12",
        "% gas window",
    ]
    L.append(md_table(co, floatfmt="{:,.3f}"))
    L.append(
        "\nThe 2018 cohort stands out because most of its wells are in the gas window (`ventana`, ADR-020): oil-equivalent "
        "per metre is not comparable across windows, which is why the rankings below are split by window.\n"
    )

    # 4. operators, by fluid window
    L.append(
        f"\n## 4. Operators by IP90 per metre, {VM} (median, n >= 5, outliers excluded, split by fluid window)\n"
    )
    for win, col, label in (
        ("petroleo", "ip90_petroleo_m3_d_por_m", "oil, m³/d per m"),
        ("gas", "ip90_gas_mil_m3_d_por_m", "gas, thousand m³/d per m"),
    ):
        sub = vmc[vmc[col].notna() & (vmc.ventana == win)]
        op = (
            sub.groupby("operadora")
            .agg(
                n=("sigla_clave", "size"),
                ip90=(col, "median"),
                rama_m=("rama_m", "median"),
                cohorte=("cohorte", "median"),
            )
            .reset_index()
        )
        op = op[op.n >= 5].sort_values("ip90", ascending=False)
        op["rama_m"] = op.rama_m.round(0)
        op["cohorte"] = op.cohorte.round(0).astype(int).astype(str)
        op.columns = ["operadora", "n", f"median IP90 ({label})", "median rama_m", "median cohort"]
        L.append(f"`ventana = {win}` ({len(sub):,} wells with the indicator):\n")
        L.append(md_table(op, floatfmt="{:,.3f}"))
        L.append("")
    L.append(
        "Read with care: the window is itself derived from the well's GOR (ADR-020), landing levels are not published by the "
        "source, and cohorts differ (`median cohort`). It is a comparison of the published data, not of operators' skill.\n"
    )

    # 5. outliers
    L.append("## 5. Outliers\n")
    evaluated = scope[scope.outlier_ip90_m.notna()]
    hi, lo = _count_flag(scope, "outlier_ip90_m_alto"), _count_flag(scope, "outlier_ip90_m_bajo")
    L.append(
        f"Rule (ADR-018): within each formation, robust z = (log10(`{IP90_M}`) − median) / (1.4826 · MAD); |z| > {OUTLIER_Z} is an outlier; "
        f"formations with fewer than {OUTLIER_N_MIN} evaluable wells are not screened. {len(evaluated):,} in-scope wells were screened, "
        f"**{hi + lo:,} marked** ({hi:,} high, {lo:,} low); {_count_flag(scope, 'outlier_no_evaluado'):,} could not be (no IP90 per metre, "
        "or a small formation). They stay in `indicadores` with `outlier_ip90_m = True` and are excluded only from the "
        "`incluye_outliers = False` type curves.\n"
    )
    ob = scope[scope.outlier_ip90_m.fillna(False).astype(bool)]
    if not ob.empty:
        ob_t = (
            ob.groupby("formacion")
            .agg(
                outliers=("sigla_clave", "size"),
                high=("outlier_z_ip90_m", lambda z: int((z > 0).sum())),
                low=("outlier_z_ip90_m", lambda z: int((z < 0).sum())),
                min_rama=("rama_m", "min"),
                median_rama=("rama_m", "median"),
            )
            .reset_index()
        )
        L.append(md_table(ob_t))
        L.append("\nThe most extreme ten (what they look like, so the rule can be judged):\n")
        ex = (
            ob.assign(absz=ob.outlier_z_ip90_m.abs(), cohorte=ob.cohorte.astype(str))
            .sort_values("absz", ascending=False)
            .head(10)
        )
        L.append(
            md_table(
                ex[
                    [
                        "sigla",
                        "operadora",
                        "formacion",
                        "cohorte",
                        "rama_m",
                        "etapas",
                        "ip90_equivalente_m3_d",
                        IP90_M,
                        "outlier_z_ip90_m",
                        "dias_efectivos_total",
                    ]
                ],
                floatfmt="{:,.3f}",
            )
        )
        short = int((ob.rama_m < 1000).sum())
        barely = int((ob.ip90_equivalente_m3_d < 20).sum())
        L.append(
            f"\nWhat the rule caught: {barely:,} of the {len(ob):,} have an IP90 under 20 m³/d of oil equivalent (wells that barely flowed in "
            f"their first 90 producing days: tests, early shut-ins, or volumes reported under another idpozo) and {short:,} have a lateral "
            "under 1,000 m (a short or mis-loaded `rama_m` inflates every per-metre value). They are marked, not fixed: a reader can "
            "look at them in `indicadores` and decide.\n"
        )

    # 6. type curves
    L.append("## 6. Type curves\n")
    cv = curvas[curvas.incluye_outliers]
    gcols = ["cohorte", "formacion", "ventana", "operadora"]
    grp_counts = cv.groupby("nivel")[gcols].apply(lambda d: len(d.drop_duplicates()))
    pub = cv[cv.publicable].groupby("nivel")[gcols].apply(lambda d: len(d.drop_duplicates()))
    L.append(
        md_table(
            pd.DataFrame(
                [
                    {
                        "level": n,
                        "groups": int(grp_counts.get(n, 0)),
                        "groups with >= 5 wells at month 0": int(pub.get(n, 0)),
                        "rows (with and without outliers)": int((curvas.nivel == n).sum()),
                    }
                    for n in grp_counts.index
                ]
            )
        )
    )
    vmcv = cv[(cv.nivel == "cohorte_formacion") & (cv.formacion == VM) & (cv.mes == 0)].sort_values("cohorte")
    vmcv12 = cv[(cv.nivel == "cohorte_formacion") & (cv.formacion == VM) & (cv.mes == 12)].set_index(
        "cohorte"
    )
    t = vmcv[
        ["cohorte", "n_pozos", "n_pozos_por_m", "equivalente_m3_d_p50", "equivalente_m3_d_por_m_p50"]
    ].copy()
    t["eq per m P50 at month 12"] = t.cohorte.map(vmcv12.equivalente_m3_d_por_m_p50)
    t["n at month 12"] = t.cohorte.map(vmcv12.n_pozos)
    t = t[t.cohorte >= 2012]
    t["cohorte"] = t.cohorte.astype(str)
    t.columns = [
        "cohorte",
        "n wells month 0",
        "n with rama",
        "P50 eq rate month 0 (m³/d)",
        "P50 eq per m month 0",
        "P50 eq per m month 12",
        "n at month 12",
    ]
    L.append(f"\n{VM} × cohort, month 0 and month 12 (`incluye_outliers = True`):\n")
    L.append(md_table(t, floatfmt="{:,.3f}"))
    L.append(
        "\n![type curve](../docs/indicadores-curva-tipo-vaca-muerta.png)\n![IP90 per metre by operator](../docs/indicadores-ip90-por-operadora.png)\n"
        "![lateral by cohort](../docs/indicadores-rama-por-cohorte.png)\n![GOR by cohort](../docs/indicadores-gor-por-cohorte.png)\n"
    )

    # 7. flags
    L.append("## 7. Flags\n")
    L.append(
        "Every rule that fired, counted over the whole indicators table (definitions in `docs/indicadores.md`):\n"
    )
    fc = (
        ind["flags"]
        .fillna("")
        .str.split(SEP)
        .explode()
        .replace("", pd.NA)
        .dropna()
        .value_counts()
        .rename_axis("flag")
        .reset_index(name="wells")
    )
    fc["%"] = (100 * fc.wells / len(ind)).map(lambda v: f"{v:.1f}")
    L.append(md_table(fc))
    L.append(
        f"\nProduction months used: {len(monthly):,} well-months, last month in the file `{monthly.mes_fecha.max():%Y-%m}`.\n"
    )

    path = informes / f"indicadores-{day.isoformat()}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
