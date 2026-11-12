# Decisions (ADR, short form)

Each entry: context → decision → consequences. Dates are when the decision was taken. Anything marked
*provisional* is expected to be revisited with evidence from the next phase.

## ADR-001 · Name: `vaca-muerta-abierta` (2026-10-30, provisional)

**Context.** The brief suggested `vaca-muerta-abierta`, `observatorio-vm` and `cuenca-abierta`. The data covers
all Argentine basins; the first phases cover only the Neuquina basin, unconventional wells.

**Decision.** `vaca-muerta-abierta` ("open Vaca Muerta"). It is the term people search for, it says *open* in the
name, and the scope note in the README handles the "but it also has Austral/Golfo San Jorge" objection. The Python
package is `vma` to keep imports short. The author can rename before the first release; nothing else depends on it.

**Consequences.** If scope grows to the whole country the name becomes a brand rather than a description. Acceptable.

## ADR-002 · Scope of F0-F2: Neuquina basin, unconventional (2026-10-30)

**Context.** The unconventional file is one 149 MB CSV with every SHALE/TIGHT well since 2006; conventional
production is one 240-330 MB file per year. Fracture data (Adjunto IV) is 80 % Neuquina unconventional.

**Decision.** Start with `produccion_nc` ∩ `cuenca = 'NEUQUINA'` (4,937 well-formations, 95 % of the file).
Catalogue the conventional yearly files but do not download them. Keep the other basins in the raw data and in the
quality report, filter at the indicator stage.

**Consequences.** A laptop can rerun everything in minutes. Extending to Austral tight gas later is a filter change.

## ADR-003 · Well key: physical well = normalised sigla; `idpozo` = well × formation (2026-10-30)

**Context.** F0 measured it: `idpozo` is unique in every dataset and consistent across them (production, register,
padrón, fracture all join on it with 0 sigla disagreements), **but** 6,167 siglas in the register map to more than
one `idpozo`, and in 6,019 of them the rows differ in `formacion`. The operator register has a
`unique_sigla_formprod` column that says the same thing. Sigla normalisation levels L1-L4 changed cross-dataset
matches by < 0.3 %: spelling is not the problem, grain is.

**Decision.** Two keys, both kept:
- `idpozo` is the **well-formation** key, used as-is for joins between the Secretaría's own datasets.
- The **physical well** key for the master table (F1) is the sigla at level L2 (`trim + upper + single spaces`)
  of `vma/normalize.py`. L3 (dropping the `(h)`/`(d)` suffix) merges 365 siglas in the register that are
  different wells (a vertical pilot and its horizontal sidetrack share the number) and is therefore rejected as a key;
  it stays available as a *blocking* key for review.
- Spaces inside siglas (166 rows with leading/trailing blanks) are a cleaning step, not an identity change.

**Consequences.** Indicators that are per physical well (lateral length, stages, first production, cycle time)
aggregate the formations of a sigla; indicators that are per reservoir (type curves by formation) stay on `idpozo`.
Both grains are published.

## ADR-004 · Units: store as published, convert in one module (2026-10-30)

**Context.** The Secretaría publishes oil and water in m³, gas in thousands of m³, proppant in tonnes, lengths in
metres. Industry readers also expect bbl, Mcf, lb/ft.

**Decision.** Storage and all computations use the published units. `vma/units.py` is the only place that converts
(bbl, Mcf/MMscf, ft, lb/ft, bbl/ft, oil equivalent) and its factors are frozen by tests. Oil equivalent uses the
Secretaría's own convention (1 m³ oil ≡ 1,000 m³ gas), stated next to every number that uses it.

**Consequences.** No silent double conversion; a change in the source's units breaks a test instead of a chart.

## ADR-005 · Raw data is re-downloaded whole, dated, hashed, never versioned (2026-10-30)

**Context.** The files are revised backwards (operators rectify months later; `rectificado` is a column), so
appending is wrong. CKAN sometimes re-uploads a resource under a new id.

**Decision.** `pipeline.py download` writes `data/raw/<YYYY-MM-DD>/` with a `manifest.json` (URL, bytes, SHA-256,
timestamp, CKAN `last_modified`). `data/` is git-ignored. Resource ids are pinned in `vma/sources.py` and the
downloader warns when CKAN reports a different file name. Comparing two manifests/raw folders is the F1 "diff
between downloads" indicator.

## ADR-006 · Stack: Python + DuckDB over CSV, pandas only at the edges, matplotlib for static charts (2026-10-30)

**Context.** 1.2 M rows in the biggest file; everything fits in memory on a laptop; CI must run without the data.

**Decision.** DuckDB reads the CSVs directly (`read_csv`, all columns as text for the schema dump, inferred types
for analysis). pandas only to render tables and feed matplotlib. No Parquet yet: F1 will decide the published format.
`ruff` with E501 ignored (format handles code width; long SQL strings stay on one line on purpose).

## ADR-007 · Relationship with `capiv` (2026-10-30)

**Context.** The author's earlier project [`LucasBurriel/capiv`](https://github.com/LucasBurriel/capiv) (same
day) loads the same unconventional production file into DuckDB and gives a Claude agent a closed set of benchmark
tools (type curves, percentiles, operator rankings). It knows nothing about fracture data, the well register or
entity resolution.

**Decision.** Separate projects, different jobs:
- **capiv** answers "how do *my* wells compare with the public ones" for a company that has its own CSV. It stays
  as is and keeps its own data loading.
- **vaca-muerta-abierta** builds the public side: quality, master well table, cross-dataset indicators, a site.
- No code is copied either way. What was reused is knowledge: the production dataset's URL, resource ids and
  column list, read from capiv's README and re-verified against the real schema here (`docs/esquemas/`).
- When F1 publishes the master well table and F2 the per-metre indicators, capiv can consume them as an optional
  input (lateral length is exactly what its *Limitations* section says it lacks). That would be a capiv change,
  tracked there.

**Consequences.** Two repositories to maintain; one clear story per repository.

## ADR-008 · Drilling datasets are aggregates; cycle time comes from the register (2026-10-30)

**Context.** F0 found that "Pozos terminados" and "Pozos en perforación" are monthly counts per company × area
× concept with no well identifier. Per-well drilling and completion dates exist only in `pozos`
(`adjiv_fecha_*`, 40 % empty, with `1900-01-01` placeholders).

**Decision.** Use `pozos` for per-well cycle time (drilling end → fracture start → first production), treating dates
before 1950 as missing. Use the aggregate drilling files only for basin/operator activity series.

**Consequences.** Cycle-time coverage will be partial and must be reported as such ("sin dato con motivo").

## ADR-009 · README in English, `LEEME.md` in Spanish, code and columns keep their Spanish names (2026-10-30)

The data's public reads Spanish; a portfolio's public reads English. Column names are the Secretaría's and are
never translated in code, so that `docs/esquemas/` and the SQL match the source one-to-one.

## ADR-010 · Lateral length: explicit precedence, never zero (2026-10-31)

**Context.** 41 % of fracture records carry `longitud_rama_horizontal_m = 0`; 177 of them have ≥ 10 stages, which
no vertical well has. Wells with several fracture records (refractures, one row per stage in old conventional
jobs) sometimes carry different positive lengths. Industry readers use "lateral length" with several meanings
(landing to toe, first to last perforation, stimulated length); the source gives one number without a definition.

**Decision.** `rama_m` in the master is the **maximum `longitud_rama_horizontal_m` among the well's fracture
records with length > 0** (`rama_multiple` when several positive values differ). If every record is 0 the
column is **null**, flagged `rama_cero`, and additionally `rama_faltante` when the summed stages are ≥ 10: that is
a horizontal well whose length was not loaded, not a 0 m well. Stages are the sum of `cantidad_fracturas` over all
records. No fracture record at all → null + `sin_fractura`. The definition is written next to the column
(`docs/maestro.md`) and F2 normalises per metre only where `rama_m` is not null, publishing the exclusion count.

**Consequences.** Per-metre indicators cover ~2,700 of the ~4,750 unconventional Neuquina wells today; the
coverage is a published number, not a silent denominator. A future length source (e.g. a provincial dataset)
enters as a new precedence step, not a replacement.

## ADR-011 · Master universe: production ∪ fracture, every basin; one row per L2 sigla (2026-10-31)

**Context.** The register has 85,858 `idpozo` (≈ 78,500 physical wells), most of them conventional wells with no
production file downloaded here (ADR-002). The observatory's questions need wells that produce unconventionally
or were fractured.

**Decision.** The master covers every `idpozo` in `produccion_nc` or `fractura` (5,960 → 5,750 physical wells on
2026-10-30), all basins, with `cuenca` and `tipo_recurso` as columns so that F2 filters instead of the master
deciding. The physical well is the L2 sigla (ADR-003); the published `sigla` is the register's spelling and the
key `sigla_clave` is kept alongside. Register attributes come from the **principal `idpozo`** (most oil-equivalent
production, then most stages, then lowest id); disagreements inside a well are flagged, never averaged.

**Consequences.** Extending to the conventional production files later is a universe change in one query. The
other 70,000+ register wells are not lost: they are one `pipeline.py` option away when a map of the whole
country is wanted.

## ADR-012 · Alias policy: three versioned tables, merges only with evidence, nothing deleted (2026-10-31)

**Context.** F0 found 5 operator keys with two spellings and no formation variants. Looking at the production
history well by well showed the real pattern: the same `idpozo` passes from one name to the other in a single
month, without overlap, which is either a rename (Vista Oil & Gas → Vista Energy, 2022-05; Pan American
Energy LLC → SL, 2019-02; GeoPark Ltd. → S.A., 2026-02) or an asset sale (YPF → Quintana, Petrobras → Pampa).

**Decision.** `alias/operadoras.csv`, `alias/formaciones.csv` and `alias/siglas.csv` share one layout
(`variante, canonico, fuente, desde, nota`). Rules:
- A merge needs **evidence in the data** (same wells, hand-over month, no overlap) **and** a common root in the
  name; it is written in `nota`. Spelling variants of one legal name merge without a note. Asset sales between
  different companies are **not** merged: they appear as `operadoras_historicas` + `cambio_operadora`.
- The canonical name is the most recent legal name that reports production.
- Rows are appended, never deleted; `desde` is the date the row entered. Operators and formations are curated by
  hand; siglas are appended by the master build (spellings that differ once trimmed; blanks are cleaning, ADR-003).
- Every operator in the basin is treated the same: the table lists all 122 of them, not only the merged ones.
- Unknown names are **not** dropped: they pass through trimmed with `operadora_sin_alias` / `formacion_sin_alias`.

**Consequences.** Six operator rows merge into others today; the history of why is in the CSV and in `git log`.
Anyone who disagrees with the Vista merge edits one line and rebuilds.

## ADR-013 · Placeholder dates: before 1950 is null; first production is computed, the padrón is kept (2026-10-31)

**Context.** The register's drilling/completion dates contain `1900-01-01`, `1902-01-01`, `1910-01-01` as
fillers (3,922 rows in the whole register, 65 in the master's universe). The padrón "con fecha de primera
producción" has month = 1 in 99.4 % of its rows: it is a year, not a month.

**Decision.** Any of the four `adjiv_fecha_*` before 1950-01-01 becomes null + `fecha_placeholder`; the
threshold is a constant (`PLACEHOLDER_BEFORE`) because the oldest real unconventional/fractured well is decades
later. `primera_produccion` is **computed** as the first month with oil or gas > 0 in the production file (a
month with a record and zero volumes is not production); the padrón's value is kept as
`primera_produccion_padron` with `primera_produccion_difiere_padron` when they differ, so the disagreement is a
published number (74 % of wells) rather than a hidden choice.

**Consequences.** Cycle-time indicators (F2) can use the computed date with confidence and must report the
coverage of the drilling dates (40 % empty in the register) as "sin dato con motivo".

## ADR-014 · Publication format: CSV + Parquet per build date, never committed; the repo ships the recipe (2026-10-31)

**Context.** The master is 5,750 rows × 52 columns (6.6 MB CSV, 0.7 MB Parquet). Industry readers open CSV;
tools (DuckDB, pandas, Observable) prefer Parquet with types. The source is revised backwards (ADR-005).

**Decision.** `python pipeline.py master` writes `data/publicado/<date>/pozos.csv` (UTF-8, ISO dates) and
`pozos.parquet` (ZSTD, typed dates and nullable integers), identical columns, written by DuckDB without extra
dependencies. `data/` stays git-ignored; the repository versions the code, the alias tables, the column
documentation and the dated report with the numbers, so that two people running the same commit on the same
download get byte-identical outputs. Releases (GitHub) are the distribution channel for the files themselves.
`python pipeline.py diff --a <date> --b <date>` compares two raw downloads and writes `informes/diff-<a>-<b>.md`:
new wells, rectified well-months, operator changes, laterals filled in.

**Consequences.** No large files in git history; the published artefact is reproducible rather than archived.

## ADR-015 · Indicators and type curves are per physical well; formation = `formacion_principal` (2026-10-31)

**Context.** ADR-003 left two grains open: physical well (sigla L2) and `idpozo` (well × formation). 189 wells
carry more than one `idpozo`; in practice the secondary one is a second formation with marginal volumes reported
under the same wellbore. A type curve per `idpozo` would split one lateral's production in two and count the well
twice in `n_pozos`.

**Decision.** `indicadores` has one row per master well and `curvas_tipo` counts physical wells. The production of
every `idpozo` of the well is summed month by month; the formation is the master's `formacion_principal` (the
`idpozo` with most oil-equivalent production); `rama_m` and `etapas` are the master's. Wells whose idpozo were
summed in one month carry `produccion_suma_idpozo`. Type-curve groups are *cohort × formation*, *cohort ×
formation × fluid window* (ADR-020) and *cohort × formation × operator*, where cohort is the year of the computed
`primera_produccion` (ADR-013) and operator the master's current operator (asset sales are not re-attributed:
the curve belongs to the well, the operator column says who holds it today).

**Consequences.** A second formation never gets its own curve; that is 188 wells today and is visible in the
master's `multi_formacion`. If a reader needs the `idpozo` grain, the monthly table behind the curves is one
function (`vma/indicadores.py::monthly_by_well`) away.

## ADR-016 · Rates are per producing day; IP windows are producing-day windows with the crossing month prorated (2026-10-31)

**Context.** The source gives monthly volumes and `tef` (effective producing days). 46 % of the wells start in a
partial month; 129 in-scope wells have a month with volumes and `tef = 0`; 52 have a `tef` above the days of the
month. A calendar-day IP30 would depend on the day of the month the well came on stream.

**Decision.** Every rate is `volume / tef_d`, where `tef_d` is the max `tef` among the well's idpozo in that
month, capped at the days of the month (`tef_mayor_mes`); a month with volumes and `tef = 0` takes the whole month
(`tef_cero_con_produccion`: under-estimating a rate is preferable to inventing one or dropping the volume).
IP30/90/180 = volume in the first 30/90/180 **producing** days ÷ that many days, on the axis `cumsum(tef_d)`; the
month in which the axis crosses the horizon contributes proportionally at its own daily rate. Fewer producing days
than the horizon → null + `ip{N}_dias_insuficientes`, never extrapolated. Cumulatives (6/12/24) are calendar
months from month 0, computable only when the source already covers the window (`acum{N}_historia_corta`);
missing months inside the window count as 0 and are flagged (`acum{N}_meses_faltantes`). Type curves are the
distribution of the monthly producing-day rate at each calendar month since first production.

**Consequences.** IP is comparable across wells that started on the 3rd or the 28th; a long shut-in inside the
window stretches it in calendar time, which `dias_efectivos_total` exposes. Rates are higher than calendar-day
rates by the downtime factor; anyone comparing with a calendar-day source must know this, and the column
documentation says it.

## ADR-017 · Type curves publish nothing under 5 wells; P10 is the high case (2026-10-31)

**Context.** The brief asks for cohort statistics with a reliability mark (n < 5 attenuated). Some
cohort × formation × operator groups have 1-4 wells, and publishing their P10 would publish a single operator's
single well under a statistical name.

**Decision.** `MIN_POZOS = 5`. A group-month with fewer wells keeps its row and its `n_pozos` (so a reader sees
the group exists) but every percentile and mean is null; per-metre statistics apply the same threshold to
`n_pozos_por_m`. The column `publicable` says which rows passed. Percentiles follow the petroleum convention:
`p10` is the value exceeded by 10 % of the wells (numpy quantile 0.9), `p90` the one exceeded by 90 %; the
convention is in the column documentation and frozen by a test.

**Consequences.** 68 of 129 cohort × formation groups and 161 of 372 with operator publish statistics at
month 0 today; the rest are counted, not shown. A site can raise the threshold, never lower it below 5 without
changing this decision.

## ADR-018 · Outliers: robust z on log IP90 per metre, by formation; marked, published twice (2026-10-31)

**Context.** Per-metre indicators amplify two kinds of errors: a mis-loaded short lateral (the numerator is
fine, the denominator is tiny) and a well that barely flowed (tests, early shut-ins, volumes reported under
another idpozo). Both distort a type curve; neither should be deleted from a public table.

**Decision.** Within each formation (in-scope wells with `ip90_equivalente_m3_d_por_m > 0`, at least 20 of them),
robust z = `(log10(x) − median) / (1.4826 · MAD)`; `|z| > 3.5` marks the well `outlier_ip90_m = True` with
`outlier_ip90_m_alto` / `_bajo` and the z in `outlier_z_ip90_m`. The log transform makes the rule symmetric for a
ratio; the MAD makes it insensitive to the outliers themselves; the formation grouping avoids calling every Vaca
Muerta well an outlier of Lajas. Wells that cannot be screened keep null + `outlier_no_evaluado`. Nothing is
removed: `curvas_tipo` is published with `incluye_outliers = True` and `False`, and the report lists the most
extreme wells so the rule can be judged.

**Consequences.** 17 of 2,592 screened wells are marked today, all low (IP90 under 20 m³/d over a 2,000 m
lateral); no high outlier passes 3.5 on the log scale. The threshold and the minimum group size are constants
with their ADR number next to them; changing them is a one-line, visible decision.

## ADR-019 · Per metre only with a lateral of at least 500 m (2026-10-31)

**Context.** ADR-010 made `rama_m` null (never 0) when the source says 0. Positive values under 500 m exist (27
in-scope wells): deviated or pilot wells, or a loaded value that is not a lateral. Dividing an IP by 73 m produces
the biggest numbers of the table.

**Decision.** `rama_normalizable = rama_m >= 500`. Below it, and when `rama_m` is null, every per-metre column is
null and the row says why: `rama_corta`, `sin_rama_sin_fractura`, `sin_rama_faltante`, `sin_rama_cero`. The raw
(not per metre) indicators are still computed for those wells, so a short well is compared as a whole well, not
hidden. The threshold is a constant (`RAMA_MIN_M`) and the exclusion count is in every report.

**Consequences.** Per-metre coverage is 2,689 of 4,625 producing in-scope wells (58 %) today. When a provincial
length source enters (ADR-010), coverage rises without touching this rule.

## ADR-020 · Fluid window from the well's own GOR, three classes, provisional when early (2026-10-31)

**Context.** Vaca Muerta spans oil, volatile/condensate and gas windows and the source does not say which one a
well is in (`tipopozo` is the operator's label, `formacion` has no landing). Oil-equivalent per metre ranks gas
wells above oil wells by construction; the 2018 cohort looked exceptional until it turned out to be 54 % gas
window.

**Decision.** `ventana` is derived from the cumulative GOR of the first 12 months (`gor12`; else `gor6`; else the
whole available history, both with `ventana_provisoria`): `petroleo` below 180 m³/m³, `volatil_condensado`
between 180 and 1,800, `gas` at or above 1,800 (≈ 1,000 and 10,000 scf/bbl, the usual black-oil / volatile /
gas-condensate cut-offs, converted and rounded). It is a classification of the *data*, not of the reservoir:
`ventana_fuente` says which GOR produced it. Type curves add a *cohort × formation × window* level; operator
rankings in the report are split by window and use the window's own fluid (oil per metre in the oil window, gas
per metre in the gas window).

**Consequences.** Comparisons stop mixing windows without needing a landing map the source does not have. A
well's window can change between builds as its GOR history grows; that is the data revising itself, and it is
dated by `version_maestro`.

## ADR-021 · Site stack: static HTML + ES modules, ECharts and Leaflet from a CDN, no build step (2026-10-31)

**Context.** The brief asks for a public explorer (filters, type curves, map, download) hosted for free and rebuilt
monthly by CI, and prefers static "until it hurts". Observable Framework and Evidence would add a Node toolchain
and a build to a repository that is otherwise `pip install` and `python pipeline.py`.

**Decision.** `site/` is five HTML pages and a handful of ES modules served as-is (GitHub Pages, or
`python -m http.server` locally). Charts: ECharts 5.5.0; map: Leaflet 1.9.4 with OpenStreetMap tiles; both loaded
from cdnjs with a pinned version and an SRI hash. No framework, no bundler, no Node. The UI is in Spanish (the data's
public, ADR-009); column names on screen are the tables' own, never translated, and every number carries a
`tabla.columna` chip ("sin cita no hay número"). A test (`tests/test_site.py`) reads every column name the
JavaScript uses and checks it exists in the published tables and in `docs/*.md`.

**Consequences.** Anyone can open the site from a clone with one Python command; the libraries are the only
external dependency and they are version-pinned. The price is hand-written DOM code instead of a component model;
at five pages that is cheaper than a toolchain.

## ADR-022 · Site data: pre-aggregated JSON written by the pipeline, not Parquet in the browser (2026-10-31)

**Context.** The published tables are 0.7 MB (`pozos`), 1.2 MB (`indicadores`) and 5.4 MB (`curvas_tipo`,
151 k rows) as Parquet. Reading them in the browser needs either DuckDB-WASM (tens of MB of runtime) or
hyparquet (small, but the full `curvas_tipo` would still travel and be filtered client-side).

**Decision.** `python pipeline.py site` (`vma/site.py`) copies what the pages need into `site/data/` as JSON:
`pozos.json` (one entry per master well, columnar, flags as a dictionary + indices), one
`curvas_<nivel>.json` per type-curve level (loaded on demand), `resumen.json` (home-page counts, each with its
table, column and rule) and `meta.json` (download date, master version, last production month, manifest hashes,
file sizes). Values are rounded to 4 significant digits for transport; the Parquet keeps full precision. Nothing is
computed in the browser beyond filtering and sorting. Total 5.3 MB uncompressed; a page loads at most ~1.8 MB of
data plus ~1 MB of ECharts. `site/data/` **is committed** (it is small, it is the dated snapshot the site shows, and
it lets a clone open the site without the 460 MB download); CI regenerates it on every publish.

**Consequences.** Adding a column to the site means adding it to a list in `vma/site.py`, where the contract test
checks it against the tables and the docs. If the tables grow by an order of magnitude, hyparquet over the published
Parquet is the next step, not a backend.

## ADR-023 · What the site cuts: type curves to month 60, groups with at least one publishable month (2026-10-31)

**Context.** `curvas_tipo` runs to month 248 for the oldest cohorts, where `n_pozos` is a handful; 2/3 of the
groups at the operator level never reach 5 wells (ADR-017) and carry only counts.

**Decision.** The site ships months 0-60 of every group that has at least one `publicable` month; months under 5
wells inside that range stay as `n_pozos` with null statistics (visible as "n=3" in the table). The explorer shows
IP90 and 12-month cumulatives per metre, GOR12 and water cut 12; IP30/IP180, 6/24-month cumulatives and the raw
(non per-metre) cumulatives are in the Parquet, not on screen. Constants: `MES_MAX` in `vma/site.py`.

**Consequences.** The site is a view, the tables are the product. Anyone needing month 61+ or IP180 takes the
release or runs the pipeline.

## ADR-024 · Publish cadence: monthly on day 5, 09:00 UTC, plus manual; Pages built by the workflow (2026-10-31)

**Context.** The source lags one to three months and is revised backwards (ADR-005); the production file's last
month appears early in the following month. Tests must keep running on every push without data.

**Decision.** `.github/workflows/publish.yml` runs on `workflow_dispatch` and on `schedule` (`0 9 5 * *`):
`download` → `master` → `indicadores` → `curvas` → `site`, then `upload-pages-artifact` + `deploy-pages`
(GitHub Pages with `build_type = workflow`). The published tables, reports and charts of that run are kept as a
run artifact for 90 days; nothing is committed back by CI (the repo stays the recipe, ADR-014). The `tests` workflow
stays separate and data-free.

**Consequences.** The site's "datos descargados el" date moves once a month without anyone touching the repo. A
failed download leaves the previous deployment in place.

*Observed on the first runs (2026-11-01):* `datos.energia.gob.ar` did not accept TCP connections from GitHub-hosted
runners (HEAD and GET both timed out, three attempts). The workflow therefore deploys the **committed `site/data/`
snapshot** when the pipeline fails and says so in the run summary, so the site is always up with dated data. Until
the portal answers from GitHub's network, a refresh is `python pipeline.py download master indicadores curvas site`
on a machine that reaches the portal, then a commit of `site/data/` (which triggers nothing; run `publish` by hand), or
a self-hosted runner. This is a limitation of the source's network policy, not of the pipeline.

## ADR-025 · F4 runs locally: CLI + MCP stdio, typed read-only tools, no free SQL by default (2026-11-01)

**Context.** The brief's F4 is "questions in natural language with the query and the source cited". The site is static
on GitHub Pages (ADR-021) with no backend to host a model behind, and the author's pattern for putting an agent on
organisational data is a read-only MCP server per source with bounded, typed tools, never the model on the database.

**Decision.** F4 is a local CLI (`agente.py`) and an MCP server over stdio (`mcp_server.py`) over one tool registry
(`vma/consulta/herramientas.py`): `metadatos`, `describir_tabla`, `buscar_pozo`, `ficha_pozo`, `comparar_grupo`,
`ranking`, `curva_tipo`. Each tool builds its own parametrised DuckDB query from allowlists (tables, metrics,
dimensions, filters), applies the published rules (in scope only, `n_min = 5`, outliers in unless excluded) and
returns `{datos, cita: {tabla, columnas, filtros, regla_doc}, exclusiones, notas, fecha_datos, version_maestro, fuente}`.
The model never writes SQL unless the user starts the agent with `--sql`, which adds `sql_solo_lectura`: SELECT/WITH
only, only the three published tables, no file/system functions, no `;`, LIMIT 200 forced, 10 s timeout, the query
quoted as the citation. No hosting, no site chat: the site stays static.

**Consequences.** Anyone can run the agent on a clone with their own key; nothing runs on the author's account. The
answer space is bounded by seven tools, which is the point: a question the tools cannot answer gets "no se puede con
las herramientas" rather than an improvised query. The cost is that new kinds of questions need a new tool, with its
test and its row in `docs/agente.md`. The SQL risk is documented rather than denied: a `SELECT` that forgets
`en_alcance` or `rama_normalizable` looks right and is wrong, which is why it is opt-in and the tools exist.

## ADR-026 · Two data sources, one set of views: Parquet if built, else the committed JSON snapshot (2026-11-01)

**Context.** The published tables are Parquet in `data/publicado/<date>/` and are not committed (ADR-014); building
them means a ≈ 460 MB download that the portal does not even serve to GitHub runners (ADR-024). The site's snapshot in
`site/data/` is committed and small (ADR-022) but carries a subset of columns, 4 significant digits and curves to
month 60.

**Decision.** `vma/consulta/datos.py` opens either source as the same three DuckDB views (`pozos`, `indicadores`,
`curvas_tipo`): Parquet through `read_parquet` when the folder exists, otherwise the JSON files reshaped (the columnar
`pozos.json` split back into `indicadores` + master columns, the three `curvas_*.json` into long rows). The `Datos`
object declares which columns the open source has; a tool asked for a missing one answers "la fuente json no trae
…" with the list of what it does have, instead of a null that looks like data. `metadatos` and every envelope say
which source answered.

**Consequences.** A fresh clone can ask questions immediately (CI does, with the mock). The same tests run on both
sources against the same synthetic tables, so a divergence between the site's JSON and the Parquet contract fails a
test. The degradation is per column and explicit, in line with "lo que la fuente no tiene se dice".

## ADR-027 · The citation validator: every number in an answer must exist in a tool result of the turn (2026-11-01)

**Context.** A system prompt that says "cite every number" is a request, not a guarantee. The failure that matters is
an invented, averaged or "estimated" figure stated with the same confidence as a cited one.

**Decision.** `vma/consulta/validador.py` extracts the numbers the model wrote (Spanish and English formats,
percentages, ISO dates) and checks each against the set of numbers in the turn's tool results, accepting the rounding
the token shows (same significant digits or half a unit of its last decimal; a fraction may be quoted as a
percentage). Free of citation: numbers in the question or in the tool arguments the model chose, integers up to 10,
tokens glued to a word (`IP90`, `ADR-016`). On failure the loop sends one correction message naming the tokens; a second
failure is shown with an explicit warning and exit code 2, never hidden. The validator is tested on its own (accept /
reject / rounding / formats) and end to end with a mock provider that invents a number.

**Consequences.** The check cannot tell a right citation from a wrong one, only existence; it also rejects legitimate
arithmetic the model does itself (a difference, a share), which is intended: the tools return `n_con_dato`,
`sin_dato_porque` and medians so the model does not have to compute, and anything else is a tool to add. It costs one
extra model call only when it fires.

## ADR-028 · Model: `claude-opus-5-5` through the Anthropic SDK with a manual tool loop; a mock provider for tests and CI (2026-11-01)

**Context.** The SDK offers a tool runner that drives the loop; the loop here needs three things it does not expose:
every tool result of the turn (for the validator), a user message injected between turns (the correction), and a
provider that is not a model at all (CI and tests must run without a key, without network).

**Decision.** `vma/consulta/agente.py` owns the loop over a one-method `Proveedor` protocol: `ProveedorAnthropic`
calls `messages.stream(...).get_final_message()` with `claude-opus-5-5`, adaptive thinking, effort `medium` by
default, the system prompt as a cached block, tools with `strict: true`, thinking blocks passed back unchanged;
`ProveedorMock` plans from keywords and writes only from tool results, with a `mock-sin-cita` variant that invents a
number. `anthropic` and `mcp` are an optional extra (`pip install -e ".[agente]"`): the tools, the validator and the
tests import neither. The default provider is `anthropic` when `ANTHROPIC_API_KEY` is set and `mock` otherwise, said
out loud on stderr. The `tests` workflow runs the mock agent on the committed snapshot on every push.

**Consequences.** The repo never needs a key to be tested or demonstrated; `docs/ejemplos-agente.md` is honest about
which provider produced each transcript. Swapping the model is one argument (`--modelo`), swapping the SDK's loop for
the tool runner later would touch one class. Refusals (`stop_reason = refusal`) are reported, not retried on another
model; the questions are about public well data and a refusal would be worth reading.

## ADR-029 · The extended catalogue: documented whole, catalogued as opt-in by one criterion, parsed only when a tool needs it (2026-11-02)

**Context.** The portal publishes 178 datasets, 40 of them upstream; the observatory used 9. F5 turns the agent
towards people in operating companies who compare their own wells with the Capítulo IV, and the obvious questions
after "how does my well compare" are "what is that worth" (prices, reserves) and "what does the rest of the field
do" (production by field). Downloading everything is neither reproducible (several files are 200-770 MB, two are
XLSX inside ZIP hosted outside CKAN) nor honest: a dataset nobody reads is a maintenance cost.

**Decision.** Three tiers, all written down in `docs/fuentes.md` ("Catálogo ampliado") with id, grain, period,
size, licence and one line of use. (1) **Catalogued, opt-in** in `vma/sources.py` when a dataset feeds a planned
comparison and is small or indispensable: `reservas` (field-level P1/P2/P3, to confront an EUR with what is
booked), `precios_gas` and `regalias_crudo` (the realised prices that turn m³ into USD), `produccion_yacimiento_formacion`
(the field × formation context of a well, conventional included), `concesiones` (attributes of the polygon a user's
wells sit in). `Source` gains `formato`, `url_fija` and `grano`; `download` keeps the real extension and records the
format in the manifest, nothing else changes. (2) **Later**: documented with the module that would use them
(forecasts declared by operators, capex by concession, gas balance, map layers, the "con identificador" yearly
production files). (3) **No**: downstream, metering, environmental filings, stale price files, with the reason.
No loader is written for a source until a tool consumes it: F5 catalogues and downloads the five, and documents
the XLSX layouts, but the F5 tools work on the three published tables plus the user's own data.

**Consequences.** The default download is unchanged, so CI, the site and the agent behave as before. Someone who
wants to value a curve downloads two files of 1.5 MB in total and reads one documented layout. The catalogue is a
dated reading of the portal, not a promise: resource ids and file names are pinned and the download warns when
CKAN moves them (ADR-005). The per-well reserves, costs and pressures an engineer would want do not exist on the
portal, and the document says so rather than leaving the gap implicit.

## ADR-030 · The user's own wells: loaded per session, compared with the same rules, never persisted; synthetic data for everything public (2026-11-02)

**Context.** F5 aims the agent at people in operating companies who want to compare their wells with the Capítulo
IV. Their data is confidential; the observatory is public and bring-your-own-key (ADR-025, ADR-028). The author's
other project does a similar comparison for one company; the observatory absorbs the *pattern*, not the code or
the data (ADR-007), and must be demonstrable and testable without anyone's real wells.

**Decision.** `vma/propios/` reads a CSV or Parquet the user names (`cargar_mis_pozos`), validates it against a
minimum schema with aliases and an explicit mapping, computes the user's indicators with the *same functions* the
published tables use (`ip_at`, `acum_months`, `ventana`, the 500 m lateral rule), and registers three views on the
session's in-memory DuckDB next to the published ones. Nothing is written under `data/`, no cache, no upload: the
data lives in the process and dies with it; the tool results (comparisons, not rows) are the only thing a model
provider sees, and the `mock` provider sees nothing. Three comparison tools return the usual envelope:
`comparar_mi_pozo` (month by month against P10/P50/P90 of the well's cohort × formation × window, with an
interpolated percentile and an exact rank of IP90, IP90/m and acum12 among the public wells), `comparar_mi_campania`
(each well against its own group's median, then the campaign summary) and `brechas` (where and how much below P50,
in rate and in volume on the user's own producing days). The percentile is declared an estimate from the three
published quantiles, because per-well public monthly series are not published (ADR-022). Everything public that
needs "my data" (tests, examples, docs, the MCP App demos) uses a **synthetic** dataset: public wells with
multiplicative noise, jittered attributes and new siglas, generated by `python pipeline.py sintetico`, marked
`sintetico: true` in a side file and in a column, and said in every tool result. The recipe is in the file; the
source siglas are not.

**Consequences.** A user can compare without trusting anyone with their file, and can read in one document what
the loader does to it. Units are not converted and outliers are not flagged on the user's wells (that rule needs a
population); both are limits written in `docs/mis-datos.md`. The synthetic dataset keeps the repo honest: no
transcript or screenshot in the repo shows a real operator's private well. A second `cargar_mis_pozos` replaces the
first; multi-dataset sessions are a later need.

## ADR-031 · Simulation is decline-curve analysis and published-dispersion Monte Carlo, declared as such; linear-algebra fits, no optimiser (2026-11-02)

**Context.** The author is drawn to visualisation and simulation, and operators asked "what would n wells like
these give". The public data has monthly volumes and producing days per well and nothing of the reservoir. A tool
called "simulation" that silently assumed pressures or PVT would be the kind of confident, uncited number the rest
of the project exists to avoid.

**Decision.** `vma/simulacion/` does two things and names them. (1) **Decline fits** of a single series (a public
well's months from the raw file, a user's well, or a published quantile curve): Arps exponential, hyperbolic with a
terminal decline, harmonic, and Duong, fitted by least squares on log rate with linear algebra on a grid of the
non-linear parameter (`b`, `m`); model chosen by AIC unless named; EUR by integrating to 10-30 years with the
observed uptime and an optional economic limit; a band from a residual bootstrap that refits the same model. No
SciPy, no optimiser: deterministic, dependency-free, and the grid resolution is documented as the precision. (2)
**Campaign Monte Carlo** that samples wells from a published type curve: a persistent percentile per well with
monthly jitter, rates read off P90/P50/P10 by log-linear interpolation (the inverse of the comparison percentile),
per-metre scaling when the per-metre curve exists, staggered starts, hyperbolic extension of each quantile beyond
the published months; aggregated P10/P50/P90 of rate and cumulative. Every result carries the note "no es
simulación de reservorio" and says what the band measures (fit uncertainty; published dispersion) and what it does
not (regime changes, interference, facilities, price).

**Consequences.** A manager gets orders of magnitude and comparable scenarios with the same yardstick, each
number cited to its curve and its parameters; an engineer can read the assumptions in one page
(`docs/simulacion.md`) and disagree with a parameter instead of a black box. A public well's own series needs the
Parquet source plus the raw download, so a fresh clone gets the type-curve variant and a message, not a guess. The
grid fits are coarser than a proper optimiser near the optimum and the i.i.d. bootstrap understates the band
under autocorrelation; both are written down as limits rather than hidden.

## ADR-032 · MCP Apps on the Python server: FastMCP for tools, a wrapped `resources/read` for the UI metadata, self-contained HTML with pinned CDNs, text fallback always (2026-11-02)

**Context.** The product direction for F5 is tools consumed from the terminals and chat clients of technical people
in operating companies, and, where the host allows it, the observatory's own visuals inside the chat. The MCP Apps
extension (`io.modelcontextprotocol/ui`, stable 2026-01-26) does exactly that with `ui://` resources rendered in an
iframe; its reference SDK is TypeScript and the Python `mcp` package knows nothing of it: `FastMCP.tool` takes
`meta` but `resources/read` has no place for the resource-level `_meta.ui` that carries the CSP.

**Decision.** Stay in Python (ADR-006, ADR-025): the four tools with a view declare `_meta.ui.resourceUri` and
`visibility: ["model", "app"]` through FastMCP; the four resources are registered with FastMCP under
`ui://vaca-muerta/` and MIME `text/html;profile=mcp-app`; `vma/apps/instalar` wraps the low-level
`ReadResourceRequest` handler and adds `_meta.ui` (CSP with only `cdnjs.cloudflare.com`, plus OpenStreetMap tiles
for the map; no `connectDomains`; `prefersBorder`) to the `ui://` contents. No TypeScript server, no second process.
The views are self-contained HTML5 documents (CSS and the postMessage bridge inlined; ECharts 5.5.0 and Leaflet
1.9.4 from cdnjs with the same pinned versions and integrity hashes as the site, ADR-021) that speak the `ui/*`
methods directly: `ui/initialize`, `initialized`, `tool-input`, `tool-result`, `size-changed`, `host-context-changed`,
`resource-teardown`, and `tools/call` for the simulator's controls. Every tool keeps returning text (the spec
requires it and ADR-025 already did), so Claude Code, the CLI agent and any host without the extension see the
cited JSON as before; `--sin-apps` removes the metadata entirely. Verification: protocol-level tests with an
in-memory client session against the real server, and a local test host (`python -m vma.apps.demo`) that plays
the host side with real tool results on the synthetic dataset; MCP Inspector and Claude Desktop are documented as
the owner's manual checks.

**Consequences.** One server, one registry, one envelope: the view is a rendering of the same cited result the
model reads. The cost is a small dependency on an undocumented FastMCP seam (replacing a request handler), which a
test pins; if the Python SDK gains first-class UI metadata, `instalar` shrinks to a loop. The CSP lists exactly the
origins the views use, so a host that honours it loads charts and maps and nothing else; a host that does not allow
external scripts shows the text fallback. Nothing of the user's leaves the machine through the views: they receive
the tool result from the host and send back only `tools/call` arguments.

## ADR-033 · Packaging: entry points `vma-mcp` / `vma-agente`, data resolved from the clone, an env var or a cached public snapshot; the Parquet tables as a GitHub release made by the owner (2026-11-02)

**Context.** F5's users are people in operating companies who want the tools in Claude Desktop, Claude Code or
Cursor without cloning a repository or running a pipeline. `pip install` / `uvx` of a package that ships only code
leaves the question of where the data is; the full tables are not committed (ADR-014) and the portal does not
answer CI runners (ADR-024).

**Decision.** `pyproject.toml` declares the top-level scripts as modules and three entry points (`vma-mcp`,
`vma-agente`, `vma-pipeline`), the views as package data and a `mcp` extra (server without the Anthropic SDK).
`vma/consulta/ubicacion.py` resolves the data root in a fixed order: `--datos`, `VMA_DATOS`, the clone the scripts
live in, the user cache `~/.vaca-muerta-abierta/`, and when none has data, it downloads the site's JSON snapshot
(the files GitHub Pages serves, about 5 MB, public) into that cache once. So `uvx --from git+… vma-mcp` works on a
machine with nothing else, with the JSON limits of ADR-023 declared in every result. The full Parquet tables remain
the owner's call: the README documents, as a manual step, publishing `data/publicado/<date>/` as a GitHub release so
users can point `VMA_DATOS` at it without the portal; this phase does not create the release.

**Consequences.** Three ways to run, one code path: a clone (everything), a package with the cached snapshot (the
site's subset), a package pointed at downloaded tables. The cache holds only public data; the user's own files stay
where they are (ADR-030). The snapshot download is one more network dependency, isolated behind an injectable
opener and tested without network, and it is skipped whenever any local data exists.

## ADR-034 · Prices: the realised crude price by province and the Res. 1/2018 gas price by basin, one table, gas converted at 9,300 kcal/m³ (2026-11-02)

**Context.** F6 wants the type curves, the user's wells and the campaign simulator expressed in dollars. The portal
has no per-well or per-operator price; what it has, catalogued opt-in in F5 (ADR-029), is the royalties report of
crude (*Informe Regalías CRUDO.xlsx* in a ZIP: the average realised sale price in USD/m³ that each province reports
to settle royalties, monthly since 1991, the last two months provisional) and the Res. 1/2018 gas prices (CSV,
USD/MMBTU by basin, month, contract type and segment since 2019). The international and Escalante price datasets
are stale (2016-2020). Volumes in the observatory are oil m³ and gas mil m³; the gas price is per MMBTU.

**Decision.** Both sources become one published table, `precios` (`producto × region × mes × segmento × contrato`),
with the price as published (`precio_dataset`, `unidad_dataset`) and converted to USD/m³ and USD per mil m³. The
XLSX is read by content (the header row `AÑO | MES | provinces` is searched, not assumed), 0 is read as "nothing
reported" and dropped, the last two reported months are flagged `provisorio`, and the production and royalties
sheets come along as two extra columns because they share the grain. The gas conversion assumes the Argentine
reference calorific value of **9,300 kcal/m³** (the base in which gas volumes are declared under Res. 319/93) and
**1 MMBTU = 252,000 kcal**, so 1 mil m³ = 36.905 MMBTU (`vma/units.py`); richer gas is worth more per m³ than this
says, and every USD block repeats it. The default gas price is the weighted average of all segments (`ppp`) under
the `total` contract; the default regions are Neuquén (oil) and Neuquina (gas). The table is published by its own
stage (`pipeline.py precios`) into the newest publication folder and as `site/data/precios.json` (oil from 2006,
gas `total` only, like the ADR-023 cut); the data layer registers it as an optional fourth table that exists empty
when a source lacks it, so tools say *sin dato porque* instead of failing, and the SQL allowlist includes it.
`openpyxl` becomes a dependency.

**Consequences.** Every USD figure in the observatory cites a public monthly price with its province or basin and
its provisional flag. The realised crude price is a provincial average for royalties, not a contract price; the
gas price is a basin average by segment; neither is per well, and the notes say so. The 9,300 kcal/m³ assumption,
the `ppp × total` default and the Neuquén / Neuquina fallback are the three choices to revisit; all three are one
constant each. Refreshing prices is a manual owner step (download the two opt-in sources, run the stage): the
monthly workflow does not fetch them, so the committed snapshot can lag the portal by months and
`ultimo_mes_publicado` says by how much.

## ADR-035 · Valuation: gross revenue only, three price modes, a monthly NPV at 10 % by default, royalty optional, no costs (2026-11-02)

**Context.** With prices in hand, the question is how far to go. An economic evaluation needs capex, opex,
transport, taxes, export duties, price decks and the fiscal terms of each concession; none of that is public per
well and most of it is the user's own. Going half-way (a guessed cost per barrel) would print numbers that look
like economics and are not.

**Decision.** `vma/precios/valorizar.py` computes **gross revenue** and nothing else: oil m³ and gas mil m³ per
month × a price, summed, cumulated and discounted. Three price modes, chosen by the caller: `historico` (the
published price of each calendar month in the well's province or basin, the last published price held beyond it and
the months counted), `flat` (one price per product given by the user, accepted in USD/m³ or USD/bbl and USD per mil
m³ or USD/MMBTU) and `ultimo` (the last published price held constant). The NPV discounts month k by
`(1 + tasa_anual)^(-k/12)` with month 0 undiscounted and **10 % per year by default**, a usual real-dollar rate for
ordering scenarios, documented as a default and not as advice. Royalties are **not** deducted unless the caller
passes `regalia` (a fraction; 0.12 is the statutory base rate, effective rates differ by province and concession);
`bruto_usd`, `regalia_usd` and `ingreso_usd` are returned apart. The block is attached to five tools through one
optional parameter, `valorizar`, and without it the results are byte-for-byte what they were; it carries its own
citation to the `precios` table (or `precio_flat (del usuario)`) and the caveats in `notas`. Each tool decides what
it values: the type curve values both oil and gas P10/P50/P90 of the group (an envelope, not the same wells); my
well values its real volumes and the type well in the same calendar months; the campaign values each well's first
12 months and the public median acum12 at the average price used (no public monthly series per well, ADR-022); the
forecast values the P50 path of the fitted fluid; the simulation values each quantile of the cumulative band.
Bands are valued quantile by quantile at a fixed price: there is no price uncertainty.

**Consequences.** Managers get an order of magnitude in dollars with the same citation discipline as the m³, and
every block says in words that it is gross revenue with no costs. What is deliberately missing is listed in
`docs/precios.md`; the user who has costs can subtract them from `ingreso_usd` knowing exactly what it contains.
The defaults to revisit are the 10 % rate, the "mes0 = January of the cohort" convention for a type curve under
the historical mode, and the Neuquén / Neuquina fallback for the user's own wells, which carry no province.
## ADR-036 · The campaign simulator in the browser: quantile curves extended by the pipeline, Monte Carlo in JavaScript (2026-11-12)

**Context.** The campaign Monte Carlo (ADR-031) lived only in Python, behind the MCP server: a reader of the site
could look at type curves but not ask "what would twelve of these wells do?". The site is static (ADR-021), reads
pre-aggregated JSON (ADR-022) and cuts the curves at month 60 (ADR-023). The simulator needs three things the
site did not have: the curves beyond month 60, the extension beyond the last published month (a least-squares
hyperbolic fit per quantile on a grid of `b`), and the sampling itself.

**Decision.** The fit stays in Python and the sampling moves to the browser.

- `python pipeline.py site` also writes `site/data/simulador.json`: for every cohort × formation × window group
  without outliers, the P10/P50/P90 of oil and gas, absolute and per metre where published, **already extended to
  120 months** by `vma.simulacion.campania.cuantiles_extendidos`. `simular()` was refactored to call the same
  function, so the browser samples exactly the curves the Python simulator samples; nothing is fitted in
  JavaScript. Values carry 4 significant digits; each curve says how many months are published, the last published
  month, how many wells are behind that month (`n_ultimo`), and how many extrapolated months the order guard
  touched. A curve with fewer than 6 usable months is left out and a group with no curve left is dropped. On the
  2026-10-31 tables: 98 groups, 240 curves, 0.62 MB (cap 1.5 MB, tested). The file also carries the default
  prices: the last published crude price of Neuquén and gas price of the Neuquina basin (`ppp` × `total`,
  ADR-034) from the `precios` table, in USD/m³ and USD per mil m³ as `valorizar.py` uses them and in USD/bbl and
  USD/MMBTU as a reader types them, with month, provisional flag and citation; without the table the committed
  `precios.json` snapshot gives the same numbers.
- `site/js/montecarlo.js` is a DOM-free ES module that mirrors `simular()` step by step: a uniform position per
  well, a monthly jitter of 8 percentile points, log-linear interpolation between the quantiles, staggered starts,
  the uptime factor, P10/P50/P90 across simulations with NumPy's linear percentile. The generator is seeded
  (mulberry32 + Box-Muller) and the page shows the seed: the same seed repeats the result. It is not NumPy's
  PCG64, so Python and JavaScript agree statistically, not draw by draw; `tests/test_simulador_js.py` runs the
  module under Node and checks the cumulative P50 within 3 % of `simular()` (skipped when Node is absent; the
  site itself still needs no Node).
- The page runs it in chunks on the main thread, yielding between chunks, instead of in a Web Worker: 500
  campaigns of 12 wells take well under a second, 2,000 of 500 wells a few seconds with the page responsive, and
  one module serves the page and the test.
- **Money differs from the MCP tool, on purpose.** There (ADR-035) each quantile of the cumulative band of one
  fluid is valued at a fixed price. Here oil and gas of a well share the well's position, and gross revenue and
  its NPV are computed **inside every simulation** and banded afterwards, so the revenue band is the band of the
  campaign and not an envelope. It is still gross revenue: no capex, no opex, no transport, no taxes, royalty only
  if the reader types one; the NPV is of gross revenue, not profit, and the page says so next to the number.
- **Units.** The source's metric units stay the default. A switch shows field units as a declared conversion
  (1 m³ = 6.2898 bbl, 1 m³ = 35.3147 ft³; MMbbl, MMscf/d, Bcf), and one card gives oil + gas in boe with the
  Secretaría's own factor (1,000 m³ of gas = 1 m³ of oil, 5.61 Mcf per boe), stated as such because it is not
  the usual 6.
- **The extended tails cannot cross.** The three quantiles are fitted one by one; far from the data the fits can
  cross (47 of the 240 curves do, somewhere before month 120), which would turn the band inside out. In the
  extrapolated months a P10 or P90 tail that meets the P50 tail follows it from there on; published months are
  never touched. This lives in the shared function, so it also changes the Python simulator and the MCP tool in
  those cases; the result reports `meses_acotados` and the page says the band narrows there by construction.

**Consequences.** The site has one page that computes, and it says so (method page, footer of the simulator). The
honesty rules are on the page, not in a tooltip: P10 is the high case; rates are per producing day; no
interference between wells, no facility constraints, no costs; the band is only the dispersion the published type
curve shows; months beyond the published curve are a hyperbolic extrapolation, counted on a card and marked on
the charts. It is a statistical group of public wells, not a forecast of any operator's plan. To revisit: (1) the
tail is spliced at the level of the **last published month**, which by construction is the month with the fewest
wells of a cohort (7 wells for Vaca Muerta oil 2024, whose P90 doubles in that month); the page prints that count
and warns below 20 wells, but the rule itself (ADR-031) deserves a sturdier anchor; (2) the order guard is the
smallest fix that keeps the documented method, and a constant log-spread around the P50 tail is the alternative;
(3) persistent percentile ranks with oil and gas fully correlated is an assumption, declared; (4) `pipeline.py
site` now reads the manifest of the newest download that carries the production file, because a later opt-in
price download writes its own dated folder and would otherwise replace the sources shown on the method page.

## ADR-037 · The site in two languages: one set of pages, Spanish in the markup, an English dictionary, `?lang=` (2026-11-12)

**Context.** The site was Spanish only. Readers outside Argentina do not read Spanish, and a second tree of pages
(`en/`) would double every page and drift.

**Decision.** One set of HTML pages. Spanish stays where it is used and is the default (`<html lang="es">`):
static text carries `data-i18n="key"` (attributes: `data-i18n-attr="content:key"`), and strings built in
JavaScript go through `t("key", "texto en español con {variable}", vars)`. `site/js/i18n.js` holds the English of
every key and nothing else: no build step, no library, no JSON to fetch. A small classic script in `<head>`
(`js/idioma.js`) picks the language before the first paint: `?lang=en|es`, then the choice saved by the header
switch (localStorage, in a try/catch), then `navigator.language` (anything that does not start with `es` reads
English); it sets `<html lang>` and hides the body until the English is in, with a timeout so a failure never
leaves a blank page. The ES | EN switch reloads the page with `?lang=`; `<title>` and the meta description are
translated like any other element; internal links keep `?lang=` when the language came from the URL, so a shared
English link stays English. Numbers follow the language (`es-AR` / `en-US`).

What is never translated: column and table names (`ip90_petroleo_m3_d`, `curvas_tipo`), flags, ADR numbers,
operator and formation names, and the values of the tables (`petroleo`, `volatil_condensado`). The English uses
the industry's terms (type curve, lateral length, stages, proppant, water cut, GOR, producing day, vintage, P10
high case) and keeps the source's metric units; `mil m³` reads `thousand m³`. `tests/test_i18n.py` checks that
every key used has its English and none is left over, that the English keeps the same `{variables}`, ADR numbers
and identifiers, that every page has the switch and the early script, and, with Node, `t()` and the links.

**Consequences.** Adding a string means writing it twice, in two files, and the test fails if the English is
missing. The rule texts that `resumen.json` carries stay Spanish in the data and have their English in the
dictionary under `regla.<key>`. The reports and part of the documentation linked from the site are Spanish and the
English says so next to each link. Search engines see the Spanish markup; the English exists after JavaScript
runs, which is acceptable for a site whose pages need JavaScript to show any number.

## ADR-038 · The extrapolated tail is spliced where half of the group's wells remain (2026-11-12)

**Context.** The type curve of a young cohort is published while `n_pozos >= 5` (ADR-017), so its last months
are the few oldest wells of the vintage. Their quantiles are not comparable with the months before: in Vaca
Muerta 2024 the P50 of oil goes from 24 m³/d with 58 wells (month 31) to 49 m³/d with 16 (month 32). The
tail was spliced at the last published month, so that jump set the level of every extrapolated month and showed
as a step in the simulated campaign rate.

**Decision.** `cuantiles_extendidos` takes the well count per month (`n`) and samples the published curve only up
to the last month with at least `FRAC_BASE = 0.5` of the group's peak count; later published months are replaced
by the extrapolation and counted in `meses_descartados` (`descartados` in `simulador.json`). `ultimo_mes` is the
splice month and `n_ultimo` its well count. Without `n` nothing changes. The published curve itself
(`curvas_tipo`, the curves page) is untouched: this is a rule of the simulator, said in its notes.

**Consequences.** `simular_campania` and the browser simulator change in the same way: 165 of 240 curves of
`simulador.json` drop at least one month. The half-count rule is a common convention for type wells, not a
fitted threshold; jumps inside the kept months of small groups are published data and stay.

