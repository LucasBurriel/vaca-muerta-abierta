# Mis datos: comparar pozos propios con el Capítulo IV (F5, `vma/propios/`)

The observatory publishes what the Secretaría publishes. An engineer or a manager in an operating company has
something the portal does not: their own wells, often with better days-on data, the real lateral and the real
completion. F5 lets them put that file next to the published tables and ask, in the agent or through MCP, *how does
my well compare with its cohort*, *where is my campaign against the basin*, *where and how much am I below P50*.

**The data never leaves the machine.** The file is read into the in-memory DuckDB of the process that runs the
agent or the MCP server, registered as views, used for the comparison, and gone when the process ends. Nothing is
written under `data/`, nothing is cached, nothing is sent anywhere: the only network call the agent makes is to the
model provider, and it sends the tool results the model asked for (the comparison, not the file). With the `mock`
provider there is no network at all. ADR-030.

## The file

CSV (any separator DuckDB detects, UTF-8 or Latin-1) or Parquet. One row per **well × month**; well attributes can
repeat on every row or live in a second file (`ruta_pozos`) with one row per well.

| canonical column | required | unit | aliases recognised (case and accents ignored) |
|---|---|---|---|
| `sigla` | yes | text | pozo, well, well_name, nombre_pozo, uwi |
| `fecha` **or** `anio` + `mes` | yes | `YYYY-MM`, `YYYY-MM-DD`, `YYYYMM`; or year + month 1-12 | periodo, period, date, fecha_data; ano, year; month |
| `petroleo_m3` | yes | m³ in the month | prod_pet, petroleo, oil_m3, oil, crudo_m3 |
| `gas_mil_m3` | yes | **thousands** of m³ in the month | prod_gas, gas, gas_km3, gas_mm3 |
| `agua_m3` | no | m³ in the month | prod_agua, agua, water_m3 |
| `tef` | no | producing days in the month | dias, dias_produccion, dias_efectivos, days_on |
| `rama_m` | no | m | rama, longitud_rama_horizontal_m, lateral_m |
| `etapas` | no | count | cantidad_fracturas, stages, n_etapas |
| `arena_tn` | no | t | arena, arena_bombeada_tn, proppant_t |
| `agua_fractura_m3` | no | m³ | agua_inyectada_m3, frac_water_m3 |
| `formacion` | no (default Vaca Muerta) | text, loose spelling | formation, fm |
| `longitud`, `latitud` | no | WGS84 degrees | lon, lng, x, coordenadax; lat, y, coordenaday |
| `campania` | no | text | campana, pad, campaign, proyecto, lote |
| `ventana` | no | petroleo \| volatil_condensado \| gas | fluido, window |
| `operadora` | no | text | empresa, operator |

Any other name: `mapeo={"petroleo_m3": "Oil (m3)", "sigla": "WELL"}`. Units are the portal's; the loader does not
convert (a gas column in m³ instead of thousands of m³ will make every GOR 1,000× too high and the window `gas`;
the comparison will show it immediately).

### Validation

Errors stop the load with a message that says what is missing and how to map it: no `sigla`, no month, no oil or
gas column, unreadable dates, empty file, more than 2,000,000 rows. Warnings load and are repeated in the `notas`
of every tool result: no `tef` (every month counts its calendar days, so producing-day rates are **underestimated**
whenever the well was shut in), no `agua_m3` (no water cut), no `rama_m` (nothing per metre), no `formacion` (Vaca
Muerta assumed), negative volumes (kept, flagged `volumen_negativo`), duplicated well × month rows (summed, like
the portal with several `idpozo`), `tef` above the days of the month (capped).

### What is computed

`mis_indicadores` has the same column names as the published `indicadores` wherever the rule applies, computed by
the same functions (`vma/indicadores.py`): month 0 = first month with oil or gas > 0; cohort = its year;
`tef_d` = `tef` capped at the days of the month, the whole month when `tef` is missing or 0 with production;
IP30/90/180 over producing days with the crossing month prorated (ADR-016); cumulatives at 6/12/24 calendar
months; GOR and water cut at 6 and 12 months; per-metre values only with `rama_m` ≥ 500 m (ADR-019); fluid window
from GOR12, else GOR6, else the whole history (`ventana_provisoria`), unless the file declares `ventana`
(`ventana_fuente = declarada`). `flags` carries the same names plus `sin_tef_dias_calendario` and
`produccion_suma_filas`. Outliers are **not** evaluated on the user's wells: that rule needs the formation's
population (ADR-018).

## The tools

All four are in `vma/consulta/herramientas.py`, exposed by the CLI agent and the MCP server, and return the same
citation envelope as the rest (`cita.tabla` names the session views, `regla_doc` points here).

### `cargar_mis_pozos(ruta, mapeo?, ruta_pozos?)`

Reads, validates, computes, registers `mis_produccion`, `mis_pozos`, `mis_indicadores` on the session connection
(replacing a previous load) and returns the load summary: wells, rows, period, mapping applied, wells per cohort
and per window, the warnings, and one row per well with its main indicators and flags. If the file is the
synthetic one (`<archivo>.meta.json` says `sintetico: true`) every result says so in `notas`.

### `comparar_mi_pozo(sigla, tasa?, cohorte_ref?, incluye_outliers?, mes_max?)`

The reference group is **cohort × formation × window** when that curve is published with at least one publishable
month for the rate, else **cohort × formation**; `grupo.nivel` says which, and a note says when windows are mixed.
`cohorte_ref` compares against another cohort (a 2026 well has no published curve yet, ADR-017).

Month by month (from month 0 to `mes_max`): my producing-day rate, the group's P10/P50/P90, `ratio_p50`, and
`percentil`, the estimated exceedance percentile of my value among the group's wells that month. It is
interpolated log-linearly between the three published quantiles (P90 → 90, P50 → 50, P10 → 10) and extrapolated
linearly outside, clipped to 1..99: **P10 is the high case**, so P25 means "better than 75 % of the group". It is an
estimate from three points, not a rank over the wells (the per-well monthly rates are not published, ADR-022).
Months the group does not publish (fewer than 5 wells) come with `sin_dato_porque`.

`indicadores_vs_grupo`: my IP90, IP90 per metre and 12-month cumulative against the public wells of the same
group in `indicadores`: median, P25, P75, `n_publico`, `ratio_vs_mediana` and `supera_pct_publicos` (share of
public wells below mine, an exact rank this time). Needs at least 5 public wells with the metric.

### `comparar_mi_campania(filtros?, metrica?, cohorte_ref?, incluye_outliers?)`

My wells selected by `campania`, `formacion`, `cohorte`, `ventana` or `siglas`, one row each: my value of
`metrica`, the public median of *its own* group (each well is compared with its cohort × formation × window, so a
mixed campaign is still compared fairly), `ratio_vs_mediana`, `supera_pct_publicos`, `n_publico`. The summary:
`mediana_mia`, `mediana_de_medianas_publicas`, `ratio_mediano`, `pozos_sobre_mediana_publica`,
`supera_pct_mediano` and its P25-P75. Wells without the metric are counted in `sin_dato_porque` by flag; wells
whose group is not published are listed in `sin_grupo`.

### `brechas(sigla? | filtros?, tasa?, cohorte_ref?, incluye_outliers?, mes_max?)`

Where and how much each well is below its group's P50. Per month: `brecha_tasa` = mine − P50,
`brecha_vol` = `brecha_tasa` × my producing days (what the P50 would have produced on my calendar), `ratio`.
Per well: months compared, months below P50 split into 0-5 / 6-11 / 12+, `acum_mio`, `acum_p50`, `brecha_acum`
and `brecha_acum_pct`, the worst month. Total over the selected wells. Only months with a published statistic
enter (ADR-017). It is a comparison of rates, not an accounting loss: no prices, no downtime model.

## The synthetic dataset

`python pipeline.py sintetico [--n 30] [--semilla 7] [--salida DIR]` derives a "my wells" dataset from public
wells (`vma/propios/sintetico.py`): in-scope Vaca Muerta wells of cohorts 2022-2024, oil window, not outliers,
with at least 12 months; each well's monthly volumes multiplied by a well factor (log-normal, σ 0.15) and a month
factor (σ 0.08); lateral ±5 %, stages ±2, coordinates ±0.02°; renamed `MIO-001`… and split into `PAD-A/B/C`.
Output: `mis_pozos_produccion.csv`, `mis_pozos_atributos.csv` and `mis_pozos_produccion.csv.meta.json` with the
recipe and `sintetico: true`. The public siglas are not kept. A 30-well copy is committed in
`tests/fixtures/sintetico/` for tests and for `docs/ejemplos-agente.md`; it is synthetic and says so in every
tool result. Never present it as real wells.

## Limits

- Comparisons are against **published** statistics: three quantiles per month and the in-scope well population.
  No per-well public monthly series is used, so the percentile is an interpolation (said above).
- No unit conversion, no currency, no normalisation beyond per metre of lateral.
- The user's outliers are not flagged; a well with a data error will look like a very good or very bad well.
- One dataset per session; a second `cargar_mis_pozos` replaces the first.
