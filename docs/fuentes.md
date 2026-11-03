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

## Catálogo ampliado (leído de la API CKAN el 2026-11-02)

The portal lists 178 datasets; 40 touch upstream. This table is the ones not downloaded by default that an
engineer or a manager comparing wells could use, with the grain, period and size the CKAN metadata and a header
peek gave on 2026-11-02 (`package_search`, `resource_show`, first bytes of each file). Everything is **CC-BY 4.0**.
**F5** = catalogued now in `vma/sources.py` as opt-in (`python pipeline.py download reservas precios_gas …`);
**later** = known, documented, not catalogued; **no** = out of scope and why. Criterion: ADR-029.

| dataset / resource | id (CKAN resource) | format, size | grain | period | use for an engineer or manager | when |
|---|---|---|---|---|---|---|
| [Reservas de Petróleo y Gas](https://datos.energia.gob.ar/dataset/reservas-de-petroleo-y-gas) · Reservas al 31/12/2025 | `4833d5e4-…a300` (file on energia.gob.ar) | ZIP → XLSX, 0.3 MB | operator × basin × province × concession × field; P1/P2/P3 and contingent resources, conventional and unconventional, oil Mm³, gas MMm³; two sheets (end of concession / end of field life) | yearly snapshots 2004-2025, one resource per year | value a field or a comparison: EUR of a type curve against booked reserves per field; reserves-to-production | **F5** (`reservas`) |
| [Precios de Gas Natural](https://datos.energia.gob.ar/dataset/precios-de-gas-natural) · Res 1/2018 | `d87ca6ab-…b217` | CSV, 0.15 MB | basin × month × contract type (firm / interruptible); USD/MMBTU by segment (distributor, CNG, power plant, industry, PPP, export) | 2019-01 → current month | price a gas-window type curve or a simulated campaign in USD | **F5** (`precios_gas`); **parsed in F6** into the `precios` table ([precios.md](precios.md)) |
| [Regalías de Petróleo Crudo…](https://datos.energia.gob.ar/dataset/regalias-de-petroleo-crudo-gas-natural-glp-gasolina-y-condensado) · Regalías de Petróleo Crudo | `a43e6f07-…d1de` (file on energia.gob.ar) | ZIP → XLSX (pivot-style sheets), 1.3 MB | province × month: average sale price USD/m³, royalty-computable production, royalties USD; a sheet lists the crude types (Medanito = Neuquina) | 1991-01 → month-1; the last two months are provisional | the realised domestic crude price by province, to value oil type curves; royalty 12 % context | **F5** (`regalias_crudo`); **parsed in F6** into the `precios` table ([precios.md](precios.md)) |
| Same dataset · Regalías de Gas Natural / GLP / Gasolina y condensado | `451ef089-…`, `cc3e2beb-…`, `d68cb9aa-…` | ZIP → XLSX | as above, per product | 1991 → | gas price realised at the wellhead by province | later (same loader as crude) |
| [Producción de Petróleo y Gas (SESCO)](https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-tablas-dinamicas) · Producción de Capítulo IV agrupada por yacimiento y formación productiva | `2f2834f4-…c10cd` | CSV, 125 MB | company × field × formation × month; oil m³, gas mil m³, water m³, injection, tef; all basins and resource types | 2006-01 → 2026-09 | context for a well or a campaign: what its field and formation produce as a whole, conventional included; field-level decline | **F5** (`produccion_yacimiento_formacion`) |
| Same · Producción de petróleo / gas por yacimiento | `745facdc-…`, `ce479c85-…` | CSV, 462 + 277 MB | field × month, SESCO (all wells, with conventional) | 2009 → | heavier version of the above without formation | no: superseded by the formation-level file |
| Same · Producción promedio diaria por yacimiento (petróleo / gas) | `e7102ae1-…`, `2f939eee-…` | CSV, 28 + 27 MB | company × concession × field × month, m³/d | 2009-01 → 2026-03 | quick field ranking in m³/d | later (derivable from the F5 file) |
| Same · Producción petróleo / gas SESCO + Tight y Shale Capítulo IV por empresa / cuenca / provincia | `4cc61040-…` etc. | CSV, 0.3-2.2 MB | company (or basin, province) × month × concept (conventional, tight, shale) | 2009 → | market share by operator and resource type; a manager's one-slide context | later (small; one loader for the six files) |
| Same · Balance de gas desde 2009 | `11614a62-…` | CSV, 269 MB | company × field × month: gas produced, consumed, vented, injected, delivered | 2009 → | flaring and own consumption per field; gas commercialisation | later (gas module) |
| Same · Gas recibido, retenido, aventado por plantas | `a4fafdd4-…` | CSV, 1.3 MB | plant × month | 2009 → 2025-10 | processing-plant view of gas | no: midstream, not per well |
| [Pronósticos de Producción](https://datos.energia.gob.ar/dataset/pronosticos-de-produccion-de-petroleo-y-gas-tablas-dinamicas) · Pronóstico de producción de petróleo / gas natural | `9817510c-…`, `1f9412c3-…` | CSV, 14 + 32 MB | company × concession × month of report × forecast year × concept | 2008 → 2025-10 | the operator's own declared forecast per concession against what happened: backtest material | later (F6: "pronóstico declarado vs real") |
| [Inversiones upstream (Res. 2057)](https://datos.energia.gob.ar/dataset/inversiones-en-mercado-de-hidrocarburos-upstream) · Inversiones realizadas mensual | `c0a6f94a-…` | CSV, 10.6 MB | company × concession × field × month × concept (drilling producers, workover, facilities…), USD millions, conventional / unconventional | 2013 → 2026 | capex per well drilled by concession; cost context a manager asks for first | later (needs the concession ↔ area alias) |
| Same · Inversiones previstas año actual / realizadas año anterior / fin de concesión | `8ab4098a-…`, `285d45e5-…`, `c0bb56ec-…` | CSV, 3-6 MB | company × concession × year | yearly | planned vs realised capex | later |
| [Perforación](https://datos.energia.gob.ar/dataset/perforacion-de-pozos-de-petroleo-y-gas) · Trabajos geofísicos y perforación de pozos | `1b71a662-…` | CSV, 95 MB | company × concession × month × concept (seismic km, wells completed, metres…), realised vs committed | 2009 → | activity committed vs done per concession | later |
| Same · Pozos terminados / en perforación / metros perforados por empresa, cuenca, provincia, concepto | 12 small CSVs, 0.2-1.1 MB each | CSV | month × company (or basin, province) × concept | 2009 → | the activity series the site's home page could show without the 192 MB file | later (replace the `pozos_terminados` download by these) |
| Same · Pozos y Metros Perforados (Tablas Dinámicas), pre-2009 files | ZIP, CSV | | | ≤ 2008 | history | no |
| [Concesiones de Explotación](https://datos.energia.gob.ar/dataset/produccion-hidrocarburos-concesiones-de-explotacion) · CSV + SHP | `b6af0c0e-…`, `48a306a3-…` | CSV 0.06 MB, SHP 0.6 MB (EPSG:4326) | one row per concession: name, SESCO code, operator, consortium shares; polygons in the SHP | current (updated monthly) | draw the user's wells inside their concession; join production by concession | **F5** (`concesiones`, attributes) |
| [Yacimientos](https://datos.energia.gob.ar/dataset/produccion-hidrocarburos-yacimientos) · CSV with GeoJSON | `6130ac5d-…` | CSV, 8.2 MB (MultiPolygon GeoJSON inline) | one row per field with polygon | current | field polygons for the map | later (map layer) |
| [Lotes de Explotación](https://datos.energia.gob.ar/dataset/produccion-hidrocarburos-lotes-de-explotacion) | `2fa87f4e-…` | CSV 0.3 MB + SHP | one row per lot | current | unconventional lot boundaries | later (map layer) |
| [Permisos de Exploración](https://datos.energia.gob.ar/dataset/exploracion-hidrocarburos-permisos-de-exploracion) | `c33b6176-…` | CSV 0.2 MB (GeoJSON inline) + SHP | one row per permit with polygon | current | where exploration is allowed | later (map layer) |
| [Sísmicas 3D](https://datos.energia.gob.ar/dataset/exploracion-hidrocarburos-sismicas-3d) / [Líneas 2D](https://datos.energia.gob.ar/dataset/exploracion-hidrocarburos-lineas-sismicas-2d) | `dae27747-…`, `fb01c3ae-…` | CSV 0.8 MB / 180 MB | survey inventory with geometry | current | seismic coverage of an area | no for now (geology module, not comparisons) |
| [Trayectorias de Pozo Vaca Muerta](https://datos.energia.gob.ar/dataset/trayectoria-de-pozos) | `94741ac7-…` | CSV, 40 MB | directional surveys with navigation levels | current | landing zone, true lateral length | already opt-in (`trayectorias_vm`) |
| [Puntos de Venteo Declarados](https://datos.energia.gob.ar/dataset/produccion-hidrocarburos-puntos-de-venteo-declarados) · [Detección Satelital de Venteos](https://datos.energia.gob.ar/dataset/deteccion-satelital-de-venteos) | `c3812323-…`, `a094f5c6-…` | CSV 0.3 MB / 5.7 MB | declared flare points; VIIRS detections with date, hour, lat/lon | current / 2021 → 2026-10 | flaring near the user's wells | later (ESG module) |
| [Instalaciones Res. 319/93](https://datos.energia.gob.ar/dataset/instalaciones-hidrocarburos-instalaciones-res-319-93-) · [Ductos Res. 319/93](https://datos.energia.gob.ar/dataset/instalaciones-hidrocarburos-ductos-res--319-93) | `44614bdf-…`, `857bd3ad-…` | CSV 27 MB / 277 MB (GeoJSON inline) | one row per facility (tank, battery, plant) / per pipeline segment | current | evacuation and facilities around a pad | later (map layer, big) |
| [Registro de empresas upstream](https://datos.energia.gob.ar/dataset/registro-de-empresas-de-hidrocarburos-del-upstream) · Conformación de consorcios | `4f417d63-…` | CSV, 0.4 MB | concession × company × share × date | current | who holds what; alias source for operators | later (alias evidence, ADR-012) |
| [Actividad ambiental](https://datos.energia.gob.ar/dataset/actividad-ambiental-petroleo-y-gas) · Listado de Estudios Ambientales | `7b8583fe-…` | CSV, 2.4 MB | one row per environmental study (concession, field, company, object) | 1990s → | permitting context | no |
| [Medición (Res. 318/557)](https://datos.energia.gob.ar/dataset/medicion-de-petroleo-y-gas) · medidores, auditorías | 4 CSVs, ≤ 0.8 MB | CSV | meters and audits per facility | current | fiscal metering | no |
| [Mediciones (Res. 557)](https://datos.energia.gob.ar/dataset/producciones) · Exportaciones de crudo / gas, Importaciones de gas | `57a8b670-…`, `80a592ad-…`, `438b2ef7-…` | CSV, 0.2-1.1 MB | meter × day: exported volume (m³, bbl) | 2025 → | daily crude exports by pipeline | later (market context) |
| [Disponibilidad de petróleo a fin de mes](https://datos.energia.gob.ar/dataset/disponibilidad-de-petroleo-a-fin-de-mes) · [Distribución de petróleo](https://datos.energia.gob.ar/dataset/distribucion-de-petroleo) | `899f9397-…`, `d9948c4a-…` | CSV, 11 + 14 MB | company × month: stocks, deliveries to refineries and export | 2009 → | where the crude goes | no: downstream |
| [Refinación y comercialización (SESCO downstream)](https://datos.energia.gob.ar/dataset/refinacion-y-comercializacion-de-petroleo-gas-y-derivados-tablas-dinamicas) | 38 resources, up to 769 MB | CSV / ZIP | refinery × product × month | 1994 → | downstream | no: out of the per-well scope |
| [Precio Internacional del petróleo crudo](https://datos.energia.gob.ar/dataset/precio-internacional-pi-del-petroleo-crudo) · [Precio de exportación](https://datos.energia.gob.ar/dataset/precio-de-exportacion-de-petroleo-crudo) · [Precios de Escalante](https://datos.energia.gob.ar/dataset/precios-de-escalante) | XLS 2020, no resource, ZIP 2016 | | | stale | international reference price | no: stale; `regalias_crudo` carries the realised price monthly |
| [Canon hidrocarburífero](https://datos.energia.gob.ar/dataset/canon-hidrocarburifero) | 9 resources (PDF/XLSX) | | | | fees per hectare | no |
| Producción de Pozos de Gas y Petróleo - *year* (incl. the new "con identificador" 2024/2025 files, and the "DDJJ abiertas y cerradas" variants) | 21 + 21 resources, 240-330 MB each | CSV | well × formation × month, conventional included | 2006 → 2026 | conventional wells; the new "con identificador" files carry a well id usable for the master | later (one year is one line in `vma/sources.py`; the id variant deserves a look in F6) |
| Producción (Capítulo IV) por yacimiento y antigüedad de pozo productivo | `adf793e7-…` | CSV, 75 MB | company × field × formation × month × first-production year/month | 2010 → 2026-02 | field-level vintage analysis without the per-well file | later (cross-check for `curvas_tipo`) |

What was **not** found on the portal on 2026-11-02: per-well reserves (reserves stop at the field), well costs,
pressures or PVT, exploration well results as such (exploration shows up only as concept counts in the drilling
files and as permits/polygons).

## Reading the two XLSX sources

`reservas` and `regalias_crudo` are ZIP files with one workbook each (the portal links them from CKAN but hosts
them on `energia.gob.ar`). F5 catalogued and documented them; F6 parses `regalias_crudo` (`vma/precios/fuentes.py`,
header found by content, see [precios.md](precios.md)); `reservas` still has no loader:

- **reservas** · sheets `fin de concesión` and `fin de vida util`, header on rows 3-7 (two levels: conventional /
  unconventional → reserves / contingent resources → proved / probable / possible → PET (Mm³) / GAS (MMm³)),
  data from row 8: operator, basin, province, concession, field and 24 numeric columns.
- **regalias_crudo** · pivot-style sheets `Tabla precios` (USD/m³, header row 13, year/month rows, one column per
  province), `Tabla producción`, `Tabla regalías` (USD), `detalle de tipos de crudo` (crude type → basin → province;
  Medanito is the Neuquina reference). Realisation date and next update are in the first two rows.
