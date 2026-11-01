"""Phase 4: natural-language questions over the published tables.

Three layers, each usable without the one above it:

- :mod:`vma.consulta.datos`        the published tables in DuckDB, from Parquet or from the site's JSON snapshot.
- :mod:`vma.consulta.herramientas` the closed set of read-only, typed tools; every result carries its citation.
- :mod:`vma.consulta.validador`    "no number without a citation": every number in an answer must come from a tool.
- :mod:`vma.consulta.agente`       the tool loop (Claude or a model-free mock) that ties the three together.
"""
