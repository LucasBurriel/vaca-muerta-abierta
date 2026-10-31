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
