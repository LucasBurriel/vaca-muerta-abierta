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
