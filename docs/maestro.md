# The well master (`data/publicado/<date>/pozos.csv` · `pozos.parquet`)

One row per **physical well**. Built by `vma/master.py` (`python pipeline.py master`) from the raw download in
`data/raw/<date>/`; the latest build is summarised in `informes/maestro-<date>.md`. Column names are in Spanish,
like the source; units are the published ones (ADR-004). Both files hold the same columns; the Parquet carries
proper types (dates, nullable integers), the CSV is UTF-8 with ISO dates. Neither is committed; rebuild or take
the release.

**Grain (ADR-003, ADR-011).** The physical well is the sigla at normalisation level L2 (`trim`, upper-case,
single spaces). Every `idpozo` of the Secretaría is a *well × productive formation* and is listed inside its well.
The universe is every `idpozo` that appears in the unconventional production file **or** in the fracture file,
whatever the basin; the register (`pozos`), the padrón of first production and the operators' listing enrich it.
Multi-valued columns are `|`-separated.

## Columns

### Identity

| column | rule |
|---|---|
| `sigla` | published spelling: the register's (`pozos.sigla`) trimmed to single spaces; if the well is not in the register, the most frequent spelling in the other datasets |
| `sigla_clave` | the physical-well key: `sigla` at level L2 (`vma/normalize.py::sigla_l2`). Unique in the table |
| `alias_sigla` | every raw spelling of the sigla seen in `pozos`, `produccion_nc`, `fractura`, `listado_pozos_operadoras` (trailing spaces included). Spellings that differ from `sigla` are also appended to `alias/siglas.csv` with the date first seen |
| `idpozos` | all `idpozo` of the well, ascending |
| `n_idpozo` | how many |
| `idpozo_principal` | the `idpozo` with most oil-equivalent production (1 m³ oil ≡ 1,000 m³ gas); ties → most fracture stages → lowest id. Register attributes below come from this row |
| `nombre_propio` | the operator's own name for the well (`listado_pozos_operadoras.nombrepropio` of the principal idpozo), when listed |

### Operator and formation (alias tables, ADR-012)

| column | rule |
|---|---|
| `operadora` | the `empresa` of the **latest production month** of the well (any of its idpozo), resolved through `alias/operadoras.csv`; wells without production take `pozos.empresa`, then `fractura.empresa_informante`. The source is written in `linaje` |
| `operadoras_historicas` | distinct canonical operators in the production history, in chronological order. A rename merged by the alias table does not count as a change; an asset sale does |
| `formacion_principal` | canonical formation (`alias/formaciones.csv`) of the principal idpozo, from `pozos.formacion` (falls back to the production or fracture formation) |
| `formaciones` | `idpozo:formation` for every idpozo of the well |

### Register attributes (`pozos`, principal idpozo)

| column | rule |
|---|---|
| `area` · `yacimiento` · `cuenca` · `provincia` | as published |
| `tipo_recurso` | `CONVENCIONAL` / `NO CONVENCIONAL` / … as published; when the idpozo of one well disagree, `NO CONVENCIONAL` wins and `tipo_recurso_mixto` is set |
| `sub_tipo_recurso` | `SHALE` / `TIGHT`; `No informado` becomes null |
| `tipo_pozo` · `clasificacion` · `estado` | `tipopozo`, `clasificacion`, `tipoestado` as published |

### Coordinates, depth

| column | rule |
|---|---|
| `longitud` · `latitud` | WGS-84 point parsed from `pozos.geojson` of the principal idpozo (fallback: `produccion_nc.coordenadax/y`). Rules, in order: missing or (0, 0) → null + `sin_coordenadas`; longitude > −50 with latitude < −50 → the pair is swapped + `coordenadas_invertidas`; outside Argentina's box → kept + `coordenadas_fuera_argentina`; outside the basin's box → kept + `coordenadas_fuera_cuenca`. Boxes in `vma/master.py` (`ARGENTINA_BBOX`, `BASIN_BBOX`) |
| `cota_m` | `pozos.cota`, first non-null of the group |
| `profundidad_m` | max of `pozos.profundidad` over the idpozo of the well, counting only values > 0; 0 → null + `profundidad_cero`; > 8,000 m kept + `profundidad_sospechosa` |

### Dates (ADR-013)

| column | rule |
|---|---|
| `fecha_inicio_perforacion` · `fecha_fin_perforacion` | `pozos.adjiv_fecha_inicio_perf` (min over the group) · `adjiv_fecha_fin_perf` (max) |
| `fecha_inicio_terminacion` · `fecha_fin_terminacion` | `adjiv_fecha_inicio_term` (min) · `adjiv_fecha_fin_term` (max) |
| | any of the four before 1950-01-01 is a placeholder (`1900-01-01`, `1902-01-01`, `1910-01-01` in the source) → null + `fecha_placeholder` |
| `fecha_inicio_fractura` · `fecha_fin_fractura` | min `fecha_inicio_fractura` · max `fecha_fin_fractura` over the well's fracture records |

### Production (`produccion_nc`, all idpozo of the well summed)

| column | rule |
|---|---|
| `primera_produccion` | first month with `prod_pet > 0` or `prod_gas > 0`. **Computed, not copied**: a month with a record and zero volumes is not production |
| `primera_produccion_padron` | the padrón's `(anio, mes)`, earliest over the idpozo of the well, kept for comparison (`primera_produccion_difiere_padron` when the two differ) |
| `ultima_produccion` | last month with oil or gas > 0 |
| `meses_registrados` | distinct months with any record |
| `meses_con_produccion` | distinct months with oil or gas > 0 |
| `acum_petroleo_m3` · `acum_gas_mil_m3` · `acum_agua_m3` | sums of `prod_pet` (m³), `prod_gas` (thousands of m³, the Argentine *Mm³*), `prod_agua` (m³) |
| `acum_petroleo_bbl` · `acum_gas_mmscf` · `acum_equivalente_m3` | presentation conversions through `vma/units.py` only (`m3_to_bbl`, `thousand_m3_to_mmscf`, `oil_eq_m3`) |

### Fracture (`fractura`, all records of the well; ADR-010)

| column | rule |
|---|---|
| `n_registros_fractura` | records over the idpozo of the well (0 = `sin_fractura`) |
| `etapas` | sum of `cantidad_fracturas` over the records (refractures add up); null without records |
| `rama_m` | lateral length with explicit precedence: the **max** `longitud_rama_horizontal_m` among records with length > 0; `rama_multiple` when several positive lengths differ. If every record has length 0: null + `rama_cero`, and additionally `rama_faltante` when `etapas >= 10` (a horizontal well whose length was not loaded; never 0) |
| `arena_tn` | sum of `arena_bombeada_nacional_tn + arena_bombeada_importada_tn` |
| `agua_fractura_m3` | sum of `agua_inyectada_m3` |
| `tipo_terminacion` | most frequent `tipo_terminacion` among the records |

### Lineage and flags

| column | rule |
|---|---|
| `fuentes` | datasets where the well appears: `pozos`, `produccion_nc`, `fractura`, `padron_pozos`, `listado_pozos_operadoras` |
| `flags` | every rule that fired on the row, `|`-separated (list below) |
| `linaje` | `;`-separated `columns=source and rule` notes for the row: which dataset and month gave the operator, which idpozo gave the coordinates, how many idpozo were summed… |
| `fecha_descarga` | the `data/raw/<date>` folder the row was built from |
| `version_alias` | max `desde` across `alias/*.csv` at build time |

## Flags

| flag | meaning |
|---|---|
| `multi_idpozo` | the well has more than one `idpozo` |
| `multi_formacion` | …and they are reported on different formations |
| `sin_formacion` | no formation in any source for the principal idpozo |
| `formacion_sin_alias` | a formation name not in `alias/formaciones.csv` (kept trimmed) |
| `sin_padron_pozos` | the well is in production or fracture but not in the register `pozos` |
| `sin_produccion` | no row in `produccion_nc` (fracture-only well) |
| `nunca_produjo` | production rows exist but oil and gas are always 0 |
| `sin_padron_primera_produccion` | no row in `padron_pozos` |
| `primera_produccion_difiere_padron` | computed first production ≠ padrón month |
| `sin_operadora` | no operator in any source |
| `operadora_sin_alias` | operator name not in `alias/operadoras.csv` (kept trimmed) |
| `cambio_operadora` | more than one canonical operator in the production history |
| `operadora_difiere_pozos` | the register's operator (through the alias table) differs from the production one |
| `area_multiple` · `yacimiento_multiple` · `cuenca_multiple` | idpozo of the same well disagree on that attribute (principal wins) |
| `tipo_recurso_mixto` | idpozo of the same well disagree on resource type |
| `sin_coordenadas` · `coordenadas_invertidas` · `coordenadas_fuera_argentina` · `coordenadas_fuera_cuenca` | see *Coordinates* |
| `coordenadas_multiples` | idpozo of the same well have different points (principal wins) |
| `profundidad_cero` · `profundidad_sospechosa` · `profundidad_multiple` | see *Depth*; `_multiple` = different positive depths in the group (max wins) |
| `fecha_placeholder` | a drilling/completion date before 1950 was nulled |
| `fechas_inconsistentes` | drilling end before drilling start |
| `terminacion_antes_de_perforar` | completion start before drilling end |
| `fecha_futura` | a drilling/completion date after the build date |
| `sin_fractura` · `rama_cero` · `rama_faltante` · `rama_multiple` · `fractura_multiples_registros` | see *Fracture* |
| `fractura_fecha_futura` | fracture start after the build date |

## Not in this table (on purpose)

Per-metre intensities, IP30/90/180, GOR, cycle times and type curves are F2 indicators: they are derived from
these columns with their own rules and exclusions, and published with their own lineage.
