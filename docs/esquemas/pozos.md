# `pozos` — Capítulo IV - Pozos

- Source: <https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo> (CC-BY 4.0), file `pozos.csv`
- Downloaded: 2026-10-31T00:16:31+00:00 · 34,216,363 bytes · sha256 `a8a7c757a6167f4e…`
- CKAN last_modified: 2026-10-21T14:20:04.407884
- Rows: **85,858** · Columns: **26**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `sigla` | VARCHAR | 0.0 | 78,592 |  CSJ.LRa.x-1 |  SJ.Md.NRSe.x-1 | APCO.Ch.CR.x-7; YPF.Nq.EL-11; YPF.Nq.EL-3 |
| 2 | `idpozo` | BIGINT | 0.0 | 85,858 | 212.0 | 167626.0 | 161785; 161803; 161834 |
| 3 | `area` | VARCHAR | 0.0 | 457 | 25 DE MAYO - MEDANI… | ÑACATIMBAY | ANTICLINAL GRANDE - CERRO DRAGON; CAMPAMENTO CENTRAL - CAÑA… |
| 4 | `cod_area` | VARCHAR | 0.0 | 464 | 17BR | ZNI | ANG; CCC; PER |
| 5 | `empresa` | VARCHAR | 1.26 | 79 | ALIANZA PETROLERA A… | YPF S.A. | YPF S.A.; PAN AMERICAN ENERGY SL; PECOM SERVICIOS ENERGIA S… |
| 6 | `yacimiento` | VARCHAR | 0.0 | 1,184 | 25 DE MAYO - MEDANI… | ÑIRIHUAU | PUESTO HERNANDEZ; MANANTIALES BEHR; LOS PERALES |
| 7 | `cod_yacimiento` | VARCHAR | 0.0 | 1,316 | 17BR | ÑIRI | HER; BEH; PER |
| 8 | `formacion` | VARCHAR | 3.28 | 78 | ANITA | yacoraite | bajo barreal; comodoro rivadavia; cañadon seco |
| 9 | `cuenca` | VARCHAR | 0.0 | 10 | AUSTRAL | ÑIRIHUAU | GOLFO SAN JORGE; NEUQUINA; CUYANA |
| 10 | `provincia` | VARCHAR | 0.0 | 13 | Chubut | Tierra del Fuego | Santa Cruz; Chubut; Neuquén |
| 11 | `cota` | DOUBLE | 0.0 | 35,351 | -100.0 | 5543.41 | 0; 317; 321 |
| 12 | `profundidad` | DOUBLE | 0.0 | 6,780 | 0.0 | 378939.0 | 0; 1500; 1200 |
| 13 | `clasificacion` | VARCHAR | 0.0 | 5 | ALMACENAMIENTO | SERVICIO | EXPLOTACION; No informado; EXPLORACION |
| 14 | `subclasificacion` | VARCHAR | 0.0 | 16 | ALMACENAMIENTO DE G… | SUMIDERO | DESARROLLO; No informado; AVANZADA |
| 15 | `tipo_recurso` | VARCHAR | 0.0 | 5 | CONVENCIONAL | SIN RESERVORIO | CONVENCIONAL; No informado; NO CONVENCIONAL |
| 16 | `sub_tipo_recurso` | VARCHAR | 0.0 | 3 | No informado | TIGHT | No informado; SHALE; TIGHT |
| 17 | `gasplus` | VARCHAR | 0.0 | 2 | no | si | no; si |
| 18 | `tipopozo` | VARCHAR | 0.0 | 10 | Acuífero | Sumidero | Petrolífero; Otro tipo; Inyección de Agua |
| 19 | `tipoextraccion` | VARCHAR | 0.0 | 12 | Bombeo Hidráulico | Surgencia Natural | Sin Sistema de Extracción; Bombeo Mecánico; Electrosumergib… |
| 20 | `tipoestado` | VARCHAR | 0.0 | 17 | A Abandonar | Parado Transitoriam… | Extracción Efectiva; Abandonado; En Reserva para Recup. Sec… |
| 21 | `adjiv_fecha_inicio_perf` | DATE | 39.6 | 19,278 | 1900-01-01 | 2026-09-04 | 1910-01-01; 2004-01-01; 1902-01-01 |
| 22 | `adjiv_fecha_fin_perf` | DATE | 39.77 | 19,408 | 1900-01-01 | 2026-09-17 | 1910-01-02; 2004-01-31; 1902-01-01 |
| 23 | `adjiv_fecha_inicio_term` | DATE | 42.46 | 18,527 | 1900-01-01 | 2026-09-23 | 1910-01-03; 2004-02-01; 1902-01-12 |
| 24 | `adjiv_fecha_fin_term` | DATE | 42.46 | 18,577 | 1900-01-01 | 2026-10-12 | 1910-01-04; 2004-02-28; 1902-01-22 |
| 25 | `geojson` | VARCHAR | 0.0 | 79,294 | {"type":"Point","co… | {"type":"Point","co… | {"type":"Point","coordinates":[-68.252159000000006,-52.5705… |
| 26 | `geom` | VARCHAR | 0.0 | 79,294 | 0101000020E61000000… | 0101000020E6100000F… | 0101000020E6100000744012F6ED1351C0B8019F1F46464AC0; 0101000… |
