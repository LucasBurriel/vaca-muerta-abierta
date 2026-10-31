# Sources

All data comes from the open-data portal of Argentina's Secretaría de Energía,
<https://datos.energia.gob.ar>, published under **CC-BY 4.0** (attribution: *Secretaría de Energía de la
Nación Argentina*). Operators report these datasets monthly under the regime known as **Capítulo IV**
(Res. SE 319/93 and successors) and its **Adjunto IV** (drilling/completion annex).

The machine-readable version of this table is `vma/sources.py`; the exact bytes, hashes and timestamps of
each download are in `data/raw/<date>/manifest.json` (not versioned; regenerate with `python pipeline.py download`).
Last download used for the quality report: **2026-10-30**.

## Downloaded by default

| key | dataset (CKAN) | resource | size | rows × cols | grain | last data (2026-10-30) |
|---|---|---|--:|---|---|---|
| `produccion_nc` | [produccion-de-petroleo-y-gas-por-pozo](https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo) | Producción de Pozos de Gas y Petróleo No Convencional | 149 MB | 431,322 × 40 | well-formation × month, all years, SHALE/TIGHT only | 2026-09 |
| `pozos` | same | Capítulo IV - Pozos | 34 MB | 85,858 × 26 | one row per `idpozo`, all basins and resource types, with coordinates (GeoJSON point) and Adjunto IV drilling/completion dates | 2026-10 |
| `padron_pozos` | same | Padrón de Pozos de Capítulo IV con fecha de primera producción | 1.2 MB | 86,330 × 3 | `idpozo` → first production month | 2026-09 |
| `listado_pozos_operadoras` | same | Listado de pozos cargados por empresas operadoras | 27 MB | 84,242 × 51 | operator-side well register (initial volumes, rig, reservoir type, abandonment date) | stale: CKAN last modified 2025-10-20 |
| `fractura` | [datos-de-fractura-de-pozos-adjunto-iv](https://datos.energia.gob.ar/dataset/datos-de-fractura-de-pozos-adjunto-iv) | Datos de fractura de pozos de hidrocarburos (Adjunto IV) - Actualización diaria | 1.3 MB | 4,999 × 30 | one row per fracture job (a well can have several): lateral length, stages, proppant national/imported (t), water (m³), CO₂, max pressure, HP, start/end dates | 2026-10 (last 3-4 months incomplete) |
| `pozos_terminados` | [perforacion-de-pozos-de-petroleo-y-gas](https://datos.energia.gob.ar/dataset/perforacion-de-pozos-de-petroleo-y-gas) | Pozos terminados | 192 MB | 1,189,600 × 22 | **aggregate**: count of wells completed per month × company × area × type × concept (no well id) | 2026-09 |
| `pozos_en_perforacion` | same | Pozos en Perforación | 68 MB | 482,654 × 20 | **aggregate**: count of wells being drilled per month × company × area × concept | 2026-09 |

## Catalogued, opt-in (`python pipeline.py download metros_perforados trayectorias_vm`)

| key | dataset | resource | size | why opt-in |
|---|---|---|--:|---|
| `metros_perforados` | perforacion-de-pozos-de-petroleo-y-gas | Metros Perforados desde 2009 | 70 MB | aggregate metres per month × company × area; useful for activity, not per well |
| `trayectorias_vm` | [trayectoria-de-pozos](https://datos.energia.gob.ar/dataset/trayectoria-de-pozos) | Trayectorias de Pozo Vaca Muerta | 40 MB | directional surveys with navigation levels for Vaca Muerta wells; candidate for landing-zone and lateral-length definitions in F1/F2 |

## Known but not downloaded

- **Conventional production**, "Producción de Pozos de Gas y Petróleo - *year*" (2006…2026, 240-330 MB each,
  plus "DDJJ abiertas y cerradas" variants). Out of the initial scope (Neuquina basin, unconventional).
  Adding a year is a one-line change in `vma/sources.py`.
- Aggregated series under the same CKAN dataset (by basin, by field and formation, by well age) are derived
  from the per-well files and not needed.
- *Producción de Petróleo y Gas (SESCO)* and *Producción de hidrocarburos - Concesiones de Explotación* are
  concession-level, not per well.

## Field documentation

The Secretaría's instructions for the Capítulo IV / Adjunto IV forms:
<https://apps.energia.gob.ar/upload/planosb/instructivo/instructivo_319.pdf> (linked from the CKAN
"Documentación" resource of the trajectories dataset). Column meanings used in this repository come from
that document and from the real schema dumps in `docs/esquemas/`, never from assumptions.

## Units as published

| quantity | unit | column(s) |
|---|---|---|
| oil, water, injected water | m³ / month | `prod_pet`, `prod_agua`, `iny_agua` |
| gas | thousands of m³ / month | `prod_gas`, `iny_gas` |
| producing days | days (`tef`, "tiempo efectivo") | `tef` |
| lateral length, depth | m | `longitud_rama_horizontal_m`, `profundidad` |
| proppant | t | `arena_bombeada_nacional_tn`, `arena_bombeada_importada_tn` |
| fracture water, CO₂ | m³ | `agua_inyectada_m3`, `co2_inyectado_m3` |
| max pressure | psi | `presion_maxima_psi` |
| coordinates | WGS84 lon/lat (`coordenadax` = longitude) | `coordenadax`, `coordenaday`, `geojson` |
