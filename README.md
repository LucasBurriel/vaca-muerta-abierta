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
| F1 · Well master | one row per physical well, every spelling of its sigla as alias, operator and formation normalised with versioned alias tables, coordinates validated; published as CSV/Parquet | next |
| F2 · Indicators | per-metre intensities, IP30/90/180, type curves by cohort with lineage, outliers flagged not deleted | |
| F3 · Site | interactive explorer + map, rebuilt monthly by CI | |
| F4 · Questions in natural language | an agent with read-only tools over the published tables; no number without its query | later |

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
python -m pytest -q            # 41 tests, no network, no data needed

python pipeline.py sources     # the catalogue (vma/sources.py)
python pipeline.py download    # ~460 MB -> data/raw/<today>/ + manifest.json (URL, bytes, sha256, CKAN last_modified)
python pipeline.py schema      # real schema of every file -> docs/esquemas/*.md
python pipeline.py quality     # informes/calidad-<today>.md + docs/calidad-*.png + alias/*.csv  (~2 min)
```

Python 3.11+. Dependencies: `duckdb`, `pandas`, `matplotlib`. Raw data is never committed; the manifest is what
makes two downloads comparable.

## Layout

```
pipeline.py           sources | download | schema | quality
vma/
  sources.py          catalogue of CKAN datasets/resources (ids, URLs, sizes, default vs opt-in)
  download.py         dated download with manifest; network isolated behind an injectable opener
  schema.py           real schema dump: types, null %, cardinality, min/max, top values
  normalize.py        sigla levels L0-L4, operator and formation blocking keys
  units.py            the only place that converts units (bbl, Mcf, ft, lb/ft, oil equivalent)
  quality.py          the F0 report: cross-matching, variants, nulls, duplicates, ranges, lag, charts
docs/
  fuentes.md          every dataset: URL, licence, grain, size, last data, units as published
  decisiones.md       ADRs: name, scope, well key, units, raw-data policy, stack, relationship with capiv
  esquemas/           one markdown per dataset with its real columns
  calidad-*.png       charts of the quality report
informes/             dated quality reports
alias/                operadoras.csv, formaciones.csv — drafts for F1 to curate (status: draft | single)
tests/                pytest, tiny CSV fixtures, fake network
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
