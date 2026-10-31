# `padron_pozos` — Padrón de Pozos de Capítulo IV con fecha de primera producción

- Source: <https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo> (CC-BY 4.0), file `padron_pozos.csv`
- Downloaded: 2026-10-31T00:16:33+00:00 · 1,171,351 bytes · sha256 `fc99e349313b9563…`
- CKAN last_modified: 2026-10-10T09:02:09.080582
- Rows: **86,330** · Columns: **3**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `idpozo` | BIGINT | 0.0 | 86,330 | 212.0 | 167600.0 | 251; 267; 365 |
| 2 | `anio` | BIGINT | 0.0 | 21 | 2006.0 | 2026.0 | 2006; 2008; 2014 |
| 3 | `mes` | BIGINT | 0.0 | 11 | 1.0 | 11.0 | 1; 5; 7 |
