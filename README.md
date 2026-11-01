# vaca-muerta-abierta

**Argentina's public per-well oil & gas data (Capítulo IV), downloaded, measured, cleaned and cross-referenced.
Open code, open data, visible lineage.**

*Versión en español: [LEEME.md](LEEME.md).*

The Secretaría de Energía publishes, for every well in the country, monthly production, fracture jobs
(lateral length, stages, proppant, water), a well register with coordinates and drilling dates, and drilling
activity. It is the same data the paid aggregators resell, and it is dirty: three identities written in free
text, two different well keys, placeholder dates, zero-length laterals, a "daily" dataset that lags three months.

This repository builds an **open observatory** on top of it, in phases that each end with something published:

| phase | what | status |
|---|---|---|
| **F0 · Measure the dirt** | dated, hashed download of every dataset; real schema of each file; a data-quality report with numbers and charts; alias drafts; decisions | **done** → [`informes/calidad-2026-10-30.md`](informes/calidad-2026-10-30.md) |
| **F1 · Well master** | one row per physical well, every spelling of its sigla as alias, operator and formation normalised with versioned alias tables, coordinates validated, lateral length with explicit precedence, first production computed; published as CSV + Parquet with per-row lineage and flags | **done** → [`informes/maestro-2026-10-31.md`](informes/maestro-2026-10-31.md) |
| F2 · Indicators | per-metre intensities, IP30/90/180, type curves by cohort with lineage, outliers flagged not deleted | next |
| F3 · Site | interactive explorer + map, rebuilt monthly by CI | |
| F4 · Questions in natural language | an agent with read-only tools over the published tables; no number without its query | later |

## What F1 found (2026-10-31)

Full report: [`informes/maestro-2026-10-31.md`](informes/maestro-2026-10-31.md); columns and rules:
[`docs/maestro.md`](docs/maestro.md). Headlines:

1. **5,960 `idpozo` are 5,750 physical wells.** 189 wells carry two or more `idpozo` (188 because they are
   reported on two formations); only **one** sigla in the whole universe has two raw spellings
   (`APA.NQ.Gu-1160` / `APA.Nq.Gu-1160`). Identity in this data is about grain and about *names of companies*,
   not about well codes.
2. **The padrón's "first production month" is a year.** 99.4 % of its rows say January; computed from the
   production file (first month with oil or gas > 0), the month differs for 74 % of wells. The master publishes
   both and flags the difference.
3. **Operator history matters more than operator spelling.** Six names merge into others (renames evidenced by
   the same wells changing name in one month: Vista Oil & Gas → Vista Energy, PAE LLC → SL, GeoPark Ltd. → S.A.,
   two pure spellings); 714 wells (12 %) changed hands in the production history — asset sales that are kept as
   `operadoras_historicas`, never merged.
4. **Lateral length is known for 2,735 of 5,050 Neuquina wells.** 1,001 have no fracture record; 1,314 have
   records whose length is 0, 181 of them with ≥ 10 stages (horizontal wells, length missing → null, never 0).
   Median lateral where known: 2,550 m, 41 stages. Coverage by year is in the chart below: before 2015 almost
   nothing, since 2021 above 75 %.
5. **The rest is small and corrected, not deleted**: 1 well with longitude/latitude swapped (the 70 rows of F0
   were one well × 70 months), 65 wells with placeholder drilling dates (1902/1910) nulled, 175 with depth 0,
   4 with depth above 8,000 m kept and flagged, 0 wells outside their basin's bounding box.

![wells per operator](docs/maestro-pozos-por-operadora.png)
![first production per year](docs/maestro-primera-produccion-por-anio.png)

## What F0 found (2026-10-30)

Full report: [`informes/calidad-2026-10-30.md`](informes/calidad-2026-10-30.md). Headlines:

1. **`idpozo` is not a well.** It is a *well × productive formation*: 6,167 siglas in the register have more than
   one `idpozo`, 6,019 of them because the formation differs. Every cross-dataset join on `idpozo` is clean
   (0 sigla disagreements across 5,164 production wells); the entity-resolution problem is grain, not spelling.
   Sigla normalisation (trim / upper / drop `(h)` / alphanumerics) moves cross-matches by < 0.3 %.
2. **The drilling datasets are aggregates**, not per-well: monthly counts by company × area × concept. Per-well
   drilling/completion dates live only in the register, 40 % empty, with `1900-01-01` placeholders (3,922 rows).
3. **Fracture data: 41 % of records have lateral length = 0** (1,071 of 3,821 unconventional Neuquina records),
   177 of them with ≥ 10 stages, i.e. horizontal wells with the length missing. 1,169 Neuquina production wells
   have no fracture record at all. The "daily update" file is visibly incomplete for its last 3-4 months.
4. **Operators are nearly clean, formations are already clean.** 123 operator keys, 5 with two spellings
   (`VISTA OIL & GAS ARGENTINA SAU` / `Vista Oil & Gas Argentina SA`, `PAN AMERICAN ENERGY (SUCURSAL ARGENTINA)
   LLC` / `PAN AMERICAN ENERGY SL`, …); inside the production file `idempresa → empresa` is one-to-one.
   78 formation names, zero spelling variants; the real gap is that `vaca muerta` carries no landing level.
5. **Production is published complete and revised backwards**: the number of wells with a record grows every
   month to the last one (2026-09, one month lag), no trailing partial month, `rectificado` flags revisions.
   Suspicious values are rare but present: 70 rows with longitude/latitude swapped, 384 well-months with
   production and zero producing days, 15 with more than 31 producing days, 160 with depth > 8,000 m.

![wells per dataset](docs/calidad-pozos-por-dataset.png)
![publication lag](docs/calidad-atraso-publicacion.png)

## Run it

```bash
git clone https://github.com/LucasBurriel/vaca-muerta-abierta && cd vaca-muerta-abierta
pip install -e ".[dev]"
python -m pytest -q            # 67 tests, no network, no data needed

python pipeline.py sources     # the catalogue (vma/sources.py)
python pipeline.py download    # ~460 MB -> data/raw/<today>/ + manifest.json (URL, bytes, sha256, CKAN last_modified)
python pipeline.py schema      # real schema of every file -> docs/esquemas/*.md
python pipeline.py quality     # informes/calidad-<today>.md + docs/calidad-*.png + alias/borradores/  (~2 min)
python pipeline.py master      # data/publicado/<today>/pozos.{csv,parquet} + informes/maestro-<today>.md  (~1 min)
python pipeline.py diff        # informes/diff-<a>-<b>.md between the last two downloads (or --a/--b)
```

Python 3.11+. Dependencies: `duckdb`, `pandas`, `matplotlib`. Raw data is never committed; the manifest is what
makes two downloads comparable.

## Layout

```
pipeline.py           sources | download | schema | quality | master | diff
vma/
  sources.py          catalogue of CKAN datasets/resources (ids, URLs, sizes, default vs opt-in)
  download.py         dated download with manifest; network isolated behind an injectable opener
  schema.py           real schema dump: types, null %, cardinality, min/max, top values
  normalize.py        sigla levels L0-L4, operator and formation blocking keys
  units.py            the only place that converts units (bbl, Mcf, ft, lb/ft, oil equivalent)
  quality.py          the F0 report: cross-matching, variants, nulls, duplicates, ranges, lag, charts
  alias.py            the three versioned alias tables (variante, canonico, fuente, desde, nota)
  master.py           the F1 well master: one row per physical well, rules, flags, lineage, CSV + Parquet, report
  diff.py             differences between two dated downloads (new wells, rectified months, operator changes)
docs/
  fuentes.md          every dataset: URL, licence, grain, size, last data, units as published
  decisiones.md       ADRs 001-014: name, scope, well key, units, raw-data policy, stack, capiv, lateral
                      precedence, master universe, alias policy, placeholder dates, publication format
  maestro.md          every column of the master with its rule, and every flag
  esquemas/           one markdown per dataset with its real columns
  calidad-*.png       charts of the quality report · maestro-*.png  charts of the master report
informes/             dated reports: calidad-<date>.md (F0), maestro-<date>.md (F1), diff-<a>-<b>.md
alias/                operadoras.csv, formaciones.csv (curated), siglas.csv (appended by the build); borradores/
data/publicado/       <date>/pozos.csv + pozos.parquet — the master (git-ignored, rebuild or take the release)
tests/                pytest, tiny CSV fixtures (master, diff), fake network
```

## Rules this repository follows

- **Only public data**, cited with URL, licence and download date ([docs/fuentes.md](docs/fuentes.md)).
- **Code written from scratch**; no employer, client or colleague is named or used. Every operator in the
  basin is a row of a public dataset and is treated the same.
- **Reproducible**: one command per stage, same result on any laptop, CI runs the tests on every push.
- **Lineage is part of the data**: every quality rule is a SQL predicate printed in the report; every future
  indicator will carry the columns and rule it came from.
- **Outliers are flagged, never deleted. Missing data is "no data, because…", never zero.**

## Related

[`capiv`](https://github.com/LucasBurriel/capiv) (same author) benchmarks a company's own wells against the
public production file with a Claude agent choosing among fixed comparisons. The two projects share a data
source and nothing else; see [ADR-007](docs/decisiones.md#adr-007--relationship-with-capiv-2026-10-30).

## Licence

Code: MIT. Data: CC-BY 4.0, Secretaría de Energía de la Nación Argentina.
