# Indicators and type curves (`data/publicado/<date>/indicadores.*` · `curvas_tipo.*`)

Phase 2 derives, from the well master ([`docs/maestro.md`](maestro.md)) and the raw monthly production, two
tables with their own lineage: **`indicadores`**, one row per physical well, and **`curvas_tipo`**, one row per
group × month since first production. Built by `vma/indicadores.py` (`python pipeline.py indicadores`) and
`vma/curvas.py` (`python pipeline.py curvas`); the latest build is summarised in `informes/indicadores-<date>.md`.
Column names are in Spanish, like the source; units are the published ones (ADR-004): oil and water in m³, gas in
thousands of m³, lengths in metres, rates per producing day. Neither file is committed; rebuild or take the release.

## Rules shared by every indicator

- **Grain (ADR-015).** The physical well of the master (`sigla_clave`). The production of every `idpozo` of the
  well is summed month by month; the formation is the master's `formacion_principal`; the lateral is `rama_m`.
- **Scope (ADR-002).** `en_alcance` = `cuenca = NEUQUINA` and `tipo_recurso = NO CONVENCIONAL`. Wells outside the
  scope keep their row with `fuera_alcance`; they get indicators but no outlier screening and no type curve.
- **Producing days (ADR-016).** `tef_d` of a well-month is the max `tef` among its idpozo (one well has one
  calendar), capped at the days of the month (`tef_mayor_mes`); a month with production and `tef = 0` takes the
  whole month (`tef_cero_con_produccion`: the rate is under-estimated rather than undefined). A month with no
  production and `tef = 0` has no rate and is not a producing month.
- **Month 0** is the master's `primera_produccion` (first month with oil or gas > 0). Records before it (zero
  volumes) are ignored. `k` is the calendar month index from month 0.
- **Per metre (ADR-019).** Only when `rama_m` is known and `>= 500 m` (`rama_normalizable`); otherwise null and
  a flag with the reason (`sin_rama_*`, `rama_corta`). Never 0.
- **Oil equivalent.** `equivalente_m3 = petroleo_m3 + gas_mil_m3` (1,000 m³ gas ≡ 1 m³ oil, the Secretaría's
  convention, `vma/units.py`).
- **Missing is null with a reason, never 0.** Every null indicator has a flag that says why.

## `indicadores` — columns

### Identity and context (copied from the master)

| column | rule |
|---|---|
| `sigla` · `sigla_clave` · `idpozo_principal` | as in the master |
| `operadora` · `formacion` · `area` · `cuenca` · `tipo_recurso` · `sub_tipo_recurso` | master's `operadora`, `formacion_principal`, `area`, `cuenca`, `tipo_recurso`, `sub_tipo_recurso` |
| `en_alcance` | `cuenca = NEUQUINA` and `tipo_recurso = NO CONVENCIONAL` (ADR-002) |
| `cohorte` | year of `primera_produccion`; null without production |
| `primera_produccion` | master's computed first month with oil or gas > 0 |
| `meses_disponibles` | calendar months from `primera_produccion` to the last month present in the production file, inclusive. Sets which cumulatives are computable |
| `meses_con_registro` | well-months with a record from month 0 on |
| `dias_efectivos_total` | sum of `tef_d` from month 0 on |
| `rama_m` · `etapas` | master's lateral length and stage count (ADR-010) |
| `rama_normalizable` | `rama_m` not null and `>= 500` (ADR-019) |

### Completion intensity (per metre of `rama_m`, only when `rama_normalizable`)

| column | formula | units |
|---|---|---|
| `etapas_por_100m` | `etapas / rama_m × 100` | stages per 100 m |
| `arena_tn_por_m` | master's `arena_tn / rama_m` | t/m |
| `agua_fractura_m3_por_m` | master's `agua_fractura_m3 / rama_m` | m³/m |

### Initial rates IP30 / IP90 / IP180 (ADR-016)

For horizon `N` in {30, 90, 180} producing days and fluid `f` in {`petroleo_m3`, `gas_mil_m3`, `equivalente_m3`}:

| column | formula | units |
|---|---|---|
| `ip{N}_petroleo_m3_d` · `ip{N}_gas_mil_m3_d` · `ip{N}_equivalente_m3_d` | volume produced in the first `N` **producing days** ÷ `N`. The producing-day axis is `cumsum(tef_d)` over the months from month 0; the month in which it crosses `N` contributes `volume × (N − days before it) / tef_d`, i.e. it is prorated at its own daily rate (`vma/indicadores.py::ip_at`). Null + `ip{N}_dias_insuficientes` when the well has fewer than `N` producing days (never extrapolated) | m³/d · thousand m³/d · m³ oil-eq/d |
| `ip{N}_*_por_m` | the same ÷ `rama_m` when `rama_normalizable` | per metre of lateral |

Why producing days and not calendar days: the first month is partial for 46 % of the wells (`primer_mes_parcial`)
and a calendar-day average would depend on the day of the month the well came on stream. The cost is that a shut-in
inside the first 90 days stretches the window in calendar time; `dias_efectivos_total` and `meses_con_registro`
let a reader see it.

### Cumulatives at 6 / 12 / 24 months

For `N` in {6, 12, 24} calendar months:

| column | formula | units |
|---|---|---|
| `acum{N}_petroleo_m3` · `acum{N}_gas_mil_m3` · `acum{N}_agua_m3` · `acum{N}_equivalente_m3` | sum of the volumes of months `k = 0 .. N−1`. Null + `acum{N}_historia_corta` when `meses_disponibles < N` (the window is not yet complete in the source). A month without a record inside the window counts as 0 and the row is flagged `acum{N}_meses_faltantes` | m³ · thousand m³ · m³ · m³ oil-eq |
| `acum{N}_*_por_m` (oil, gas, equivalent) | the same ÷ `rama_m` when `rama_normalizable` | per metre |

### Ratios

| column | formula | units |
|---|---|---|
| `gor6_m3_m3` · `gor12_m3_m3` | `acum{N}_gas_mil_m3 × 1,000 / acum{N}_petroleo_m3`; null + `gor{N}_sin_petroleo` when oil is 0 (a gas well), null when the cumulative is null | m³ gas / m³ oil (1 m³/m³ ≈ 5.6 scf/bbl) |
| `corte_agua6` · `corte_agua12` | `acum{N}_agua_m3 / (acum{N}_agua_m3 + acum{N}_petroleo_m3)`; null + `corte_agua{N}_sin_liquido` when both are 0 | fraction 0-1 |
| `ventana` | fluid window from the cumulative GOR (ADR-020): `petroleo` < 180 m³/m³, `volatil_condensado` 180-1,800, `gas` ≥ 1,800 (≈ 1,000 and 10,000 scf/bbl). Oil = 0 with gas > 0 is `gas`. Null when there is no GOR at all |
| `ventana_fuente` | which GOR classified the well: `gor12` (preferred), `gor6`, or `gor_total` (whole available history) — the last two add `ventana_provisoria` |

### Outliers (ADR-018)

| column | rule |
|---|---|
| `outlier_ip90_m` | `True`/`False` for in-scope wells screened; null + `outlier_no_evaluado` otherwise. Screened = in scope, `ip90_equivalente_m3_d_por_m > 0`, formation with at least 20 such wells. Rule: within the formation, robust z = `(log10(x) − median) / (1.4826 · MAD)`; `|z| > 3.5` ⇒ outlier (`outlier_ip90_m_alto` if above, `_bajo` if below). **Marked, never removed**: the row keeps every value; `curvas_tipo` publishes both versions |
| `outlier_z_ip90_m` | the robust z, rounded to 3 decimals |

### Lineage

| column | rule |
|---|---|
| `flags` | every rule that fired, `|`-separated (list below) |
| `linaje` | `;`-separated notes: which master build, which rule for days, IP, cumulatives, per metre, window, outliers |
| `fecha_descarga` | the `data/raw/<date>` folder the production came from (from the master row) |
| `version_maestro` | the `data/publicado/<date>` folder of the master used |

## `indicadores` — flags

| flag | meaning |
|---|---|
| `fuera_alcance` | not Neuquina unconventional (ADR-002): kept, no outlier screening, no type curve |
| `sin_produccion` | no production record (fracture-only well): every production indicator is null |
| `nunca_produjo` | records exist but oil and gas are always 0: same |
| `sin_rama_sin_fractura` · `sin_rama_faltante` · `sin_rama_cero` · `sin_rama` | `rama_m` is null because the master has no fracture record / a horizontal well with length 0 / length 0 with few stages / any other reason: per-metre values are null |
| `rama_corta` | `rama_m < 500 m`: per-metre values are null (ADR-019) |
| `tef_cero_con_produccion` | at least one month with volumes and `tef = 0`: that month took the whole month as producing days |
| `tef_mayor_mes` | at least one month with `tef` above the days of the month: capped |
| `primer_mes_parcial` | month 0 has fewer than 15 producing days (the IP rule already corrects for it; informational) |
| `produccion_suma_idpozo` | two or more `idpozo` of the well reported in the same month and were summed |
| `volumen_negativo` | a negative monthly volume in the source (a correction); kept as published |
| `ip30_dias_insuficientes` · `ip90_dias_insuficientes` · `ip180_dias_insuficientes` | fewer producing days than the horizon: IP is null |
| `acum6_historia_corta` · `acum12_historia_corta` · `acum24_historia_corta` | the source does not yet cover the window: cumulative is null |
| `acum6_meses_faltantes` · `acum12_meses_faltantes` · `acum24_meses_faltantes` | months without a record inside the window counted as 0 |
| `gor6_sin_petroleo` · `gor12_sin_petroleo` | no oil in the window: GOR undefined (gas well) |
| `corte_agua6_sin_liquido` · `corte_agua12_sin_liquido` | neither oil nor water in the window |
| `ventana_provisoria` | the window was classified from `gor6` or from the whole history, not from `gor12` |
| `outlier_ip90_m_alto` · `outlier_ip90_m_bajo` · `outlier_no_evaluado` | see *Outliers* |

## `curvas_tipo` — columns

One row per `nivel` × group × `incluye_outliers` × `mes`. Rates are **producing-day rates** of each well-month
(`volume / tef_d`), so a month with no producing days does not count a well in `n_pozos`. Only in-scope wells
with a cohort and a formation enter.

| column | rule |
|---|---|
| `nivel` | `cohorte_formacion`, `cohorte_formacion_ventana` or `cohorte_formacion_operadora` (ADR-015) |
| `cohorte` · `formacion` · `ventana` · `operadora` | the group keys; `ventana` and `operadora` are null at the levels that do not use them. Wells without a `ventana` appear only in the levels that do not split by it |
| `incluye_outliers` | `True`: every well; `False`: without the wells with `outlier_ip90_m = True` (ADR-018). Both versions are published |
| `mes` | calendar months since first production (0 = first month with oil or gas > 0) |
| `n_pozos` | distinct wells with a producing-day rate in that month |
| `n_pozos_por_m` | of which with `rama_normalizable` (the denominator of the per-metre statistics) |
| `publicable` | `n_pozos >= 5` (ADR-017). Below it the row keeps `n_pozos` and every statistic is null; per-metre statistics are null when `n_pozos_por_m < 5` |
| `{rate}_p10` · `{rate}_p50` · `{rate}_p90` · `{rate}_media` for `rate` in `petroleo_m3_d`, `gas_mil_m3_d`, `equivalente_m3_d`, `petroleo_m3_d_por_m`, `gas_mil_m3_d_por_m`, `equivalente_m3_d_por_m` | percentiles across wells of the month's producing-day rate, **petroleum convention** (ADR-017): `p10` is the value exceeded by 10 % of the wells (the high case, numpy quantile 0.9), `p50` the median, `p90` the value exceeded by 90 % (quantile 0.1); `media` the arithmetic mean |
| `fecha_descarga` · `version_maestro` | as in `indicadores` |

Columns written in full: `petroleo_m3_d_p10`, `petroleo_m3_d_p50`, `petroleo_m3_d_p90`, `petroleo_m3_d_media`,
`gas_mil_m3_d_p10`, `gas_mil_m3_d_p50`, `gas_mil_m3_d_p90`, `gas_mil_m3_d_media`, `equivalente_m3_d_p10`,
`equivalente_m3_d_p50`, `equivalente_m3_d_p90`, `equivalente_m3_d_media`, `petroleo_m3_d_por_m_p10`,
`petroleo_m3_d_por_m_p50`, `petroleo_m3_d_por_m_p90`, `petroleo_m3_d_por_m_media`, `gas_mil_m3_d_por_m_p10`,
`gas_mil_m3_d_por_m_p50`, `gas_mil_m3_d_por_m_p90`, `gas_mil_m3_d_por_m_media`, `equivalente_m3_d_por_m_p10`,
`equivalente_m3_d_por_m_p50`, `equivalente_m3_d_por_m_p90`, `equivalente_m3_d_por_m_media`.

## Not in these tables (on purpose)

Arps fits, cycle times (drilling → fracture → first production), parent/child classification and activity series
are later indicators; each will carry its own rule and coverage number. Conversions to bbl/d, Mcf/d or bbl/ft are
presentation and go through `vma/units.py` at the site, not here.
