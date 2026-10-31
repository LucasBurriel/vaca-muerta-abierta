# `fractura` — Datos de fractura de pozos de hidrocarburos (Adjunto IV) - Actualización diaria

- Source: <https://datos.energia.gob.ar/dataset/datos-de-fractura-de-pozos-adjunto-iv> (CC-BY 4.0), file `fractura.csv`
- Downloaded: 2026-10-31T00:16:35+00:00 · 1,254,362 bytes · sha256 `af87ed4dfe35ab47…`
- CKAN last_modified: 2026-10-30T04:00:05.481563
- Rows: **4,999** · Columns: **30**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `id_base_fractura_adjiv` | BIGINT | 0.0 | 4,999 | 30.0 | 5790.0 | 41; 72; 98 |
| 2 | `idpozo` | BIGINT | 0.0 | 4,755 | 458.0 | 167596.0 | 159341; 136856; 133431 |
| 3 | `sigla` | VARCHAR | 0.0 | 4,713 |  TPT.Ch.S-2766(d) | YSR.RN.EFON.x-1(d) | APS.Nq.Sa-1238; APA.Nq.RCo-1052(d); TPT.RN.LA-2 |
| 4 | `cuenca` | VARCHAR | 0.0 | 3 | AUSTRAL | NEUQUINA | NEUQUINA; GOLFO SAN JORGE; AUSTRAL |
| 5 | `areapermisoconcesion` | VARCHAR | 0.0 | 105 | AGUA DEL CAJON | TAPI AIKE | LOMA CAMPANA; EL TORDILLO; LA AMARGA CHICA |
| 6 | `yacimiento` | VARCHAR | 0.0 | 140 | AGUA DEL CAJON | SUR RIO CHICO - ASGN | LOMA CAMPANA-LLL; EL TORDILLO; LA AMARGA CHICA |
| 7 | `formacion_productiva` | VARCHAR | 0.0 | 28 | ANITA | vaca muerta | vaca muerta; lajas; mina el carmen |
| 8 | `tipo_reservorio` | VARCHAR | 0.7 | 3 | CONVENCIONAL | NO DISCRIMINADO | NO CONVENCIONAL; CONVENCIONAL; NO DISCRIMINADO |
| 9 | `subtipo_reservorio` | VARCHAR | 19.46 | 2 | SHALE | TIGHT | SHALE; TIGHT |
| 10 | `longitud_rama_horizontal_m` | DOUBLE | 0.0 | 2,008 | 0.0 | 5114.11 | 0; 3; 0.00 |
| 11 | `cantidad_fracturas` | BIGINT | 0.0 | 98 | 1.0 | 105.0 | 1; 5; 2 |
| 12 | `tipo_terminacion` | VARCHAR | 0.0 | 5 | Camisas deslizables | Tapón disparo | Tapón disparo; Punzado; Camisas y punzados |
| 13 | `arena_bombeada_nacional_tn` | DOUBLE | 0.0 | 3,349 | 0.0 | 20834.0 | 0; 0.00; 1.5 |
| 14 | `arena_bombeada_importada_tn` | DOUBLE | 0.0 | 2,193 | 0.0 | 80652.0 | 0; 0.00; 0.0 |
| 15 | `agua_inyectada_m3` | DOUBLE | 0.0 | 4,367 | 0.0 | 537184.6 | 0; 585.63; 1171.26 |
| 16 | `co2_inyectado_m3` | DOUBLE | 0.0 | 134 | 0.0 | 560.0 | 0; 0.00; 0.0 |
| 17 | `presion_maxima_psi` | DOUBLE | 0.0 | 3,610 | 0.0 | 209640.559333927 | 0; 11500; 8000 |
| 18 | `potencia_equipos_fractura_hp` | DOUBLE | 1.02 | 1,889 | 0.0 | 236451.0 | 40000; 44000; 18000 |
| 19 | `fecha_inicio_fractura` | DATE | 0.0 | 2,800 | 2006-05-19 | 2026-12-05 | 2024-02-10; 2026-01-31; 2017-09-26 |
| 20 | `fecha_fin_fractura` | DATE | 0.0 | 2,720 | 2006-05-24 | 2026-09-19 | 2025-11-16; 2025-04-01; 2025-09-08 |
| 21 | `fecha_data` | TIMESTAMP | 0.0 | 980 | 2019-06-14 17:13:03… | 2026-10-19 10:23:10… | 2019-06-27 13:46:21.14935; 2019-10-16 16:10:23.217318; 2019… |
| 22 | `anio_if` | BIGINT | 0.0 | 19 | 2006.0 | 2026.0 | 2025; 2022; 2023 |
| 23 | `mes_if` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 5; 1; 4 |
| 24 | `anio_ff` | BIGINT | 0.0 | 19 | 2006.0 | 2026.0 | 2025; 2022; 2023 |
| 25 | `mes_ff` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 5; 8; 6 |
| 26 | `anio_carga` | BIGINT | 0.0 | 8 | 2019.0 | 2026.0 | 2019; 2025; 2026 |
| 27 | `mes_carga` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 6; 9; 10 |
| 28 | `empresa_informante` | VARCHAR | 0.0 | 23 | CAPEX S.A. | YPF S.A. | YPF S.A.; TECPETROL S.A.; CHEVRON ARGENTINA S.R.L. |
| 29 | `mes` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 5; 1; 4 |
| 30 | `anio` | BIGINT | 0.0 | 19 | 2006.0 | 2026.0 | 2025; 2022; 2023 |
