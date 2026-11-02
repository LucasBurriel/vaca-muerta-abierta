"""Phase 5: the user's own wells, compared with the published tables (ADR-030).

The user points the agent at a CSV or Parquet file with monthly production per well (and, optionally, lateral
length, stages, proppant, formation, coordinates). The file is read into the session's in-memory DuckDB, the
same indicators as ``vma/indicadores.py`` are computed with the same rules (producing-day rates, IP windows,
cumulatives, GOR window), and the comparison tools put each well against the type curve of its cohort,
formation and fluid window. Nothing is written to disk and nothing leaves the machine: the data lives in the
process that loaded it and dies with it.

- :mod:`vma.propios.esquema`   the minimum schema, the column aliases, the validation with plain messages.
- :mod:`vma.propios.cargar`    read, map, normalise, compute indicators, register as DuckDB views.
- :mod:`vma.propios.comparar`  one well against its type curve; a campaign against its cohort; the gaps.
- :mod:`vma.propios.sintetico` a synthetic dataset derived from public wells with noise, for tests and demos.
"""
