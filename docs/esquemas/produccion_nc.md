# `produccion_nc` — Producción de Pozos de Gas y Petróleo No Convencional

- Source: <https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo> (CC-BY 4.0), file `produccion_nc.csv`
- Downloaded: 2026-10-31T00:16:25+00:00 · 148,923,474 bytes · sha256 `61cecc31c8dd81fd…`
- CKAN last_modified: 2026-10-22T21:00:55.998494
- Rows: **431,322** · Columns: **40**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `idempresa` | VARCHAR | 0.0 | 55 | ACO | YSUR | YPF; APS; PLU |
| 2 | `anio` | BIGINT | 0.0 | 21 | 2006.0 | 2026.0 | 2025; 2024; 2026 |
| 3 | `mes` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 9; 8; 7 |
| 4 | `idpozo` | BIGINT | 0.0 | 5,164 | 3640.0 | 167626.0 | 114867; 116076; 96651 |
| 5 | `prod_pet` | DOUBLE | 0.0 | 154,991 | -0.001 | 26593.261 | 0; 0.00; 0.000 |
| 6 | `prod_gas` | DOUBLE | 0.0 | 201,821 | -12.267 | 40086.8 | 0; 0.00; 0.000 |
| 7 | `prod_agua` | DOUBLE | 0.0 | 143,814 | 0.0 | 34792.95 | 0; 0.00; 0.000 |
| 8 | `iny_agua` | DOUBLE | 0.0 | 667 | 0.0 | 70278.85 | 0; 0.00; 0.000 |
| 9 | `iny_gas` | DOUBLE | 0.0 | 598 | 0.0 | 3569000.0 | 0; 0.00; 0.000 |
| 10 | `iny_co2` | DOUBLE | 0.0 | 9 | 0.0 | 0.0 | 0; 0.00; 0.000 |
| 11 | `iny_otro` | DOUBLE | 0.0 | 8 | 0.0 | 0.0 | 0; 0.00; 0.000 |
| 12 | `tef` | DOUBLE | 0.0 | 21,975 | 0.0 | 79.34 | 0; 31; 30 |
| 13 | `vida_util` | DOUBLE | 97.87 | 466 | 0.0 | 11415.21 | 0; 455; 2342 |
| 14 | `tipoextraccion` | VARCHAR | 0.14 | 11 | Bombeo Hidráulico | Surgencia Natural | Surgencia Natural; Plunger Lift; Bombeo Mecánico |
| 15 | `tipoestado` | VARCHAR | 0.14 | 16 | A Abandonar | Parado Transitoriam… | Extracción Efectiva; Parado Transitoriamente; En Estudio |
| 16 | `tipopozo` | VARCHAR | 0.14 | 7 | Acuífero | Sumidero | Gasífero; Petrolífero; Otro tipo |
| 17 | `observaciones` | VARCHAR | 94.29 | 220 | - | Participación (Wor… | En Extraccion Efectiva; Cargado automáticamente como [Sin m… |
| 18 | `fechaingreso` | TIMESTAMP | 0.0 | 10,222 | 2006-11-13 13:57:53… | 2026-10-20 12:53:14… | 2026-10-14 16:03:00.624335; 2026-09-15 11:09:47.767458; 202… |
| 19 | `rectificado` | BOOLEAN | 0.0 | 2 | f | t | f; t |
| 20 | `habilitado` | BOOLEAN | 0.0 | 1 | t | t | t |
| 21 | `idusuario` | BIGINT | 0.0 | 55 | 3.0 | 498.0 | 334; 383; 381 |
| 22 | `empresa` | VARCHAR | 0.0 | 55 | AMERICAS PETROGAS A… | YSUR ENERGÍA ARGENT… | YPF S.A.; CAPEX S.A.; PLUSPETROL S.A. |
| 23 | `sigla` | VARCHAR | 0.0 | 4,979 |  TPT.Nq.FP-1024(h) | YSR.RN.EFON.x-1(d) | YPF.Nq.RN.xp-58; YPF.Nq.CuM.a-16; YPF.Nq.CuM.a-8 |
| 24 | `formprod` | VARCHAR | 0.0 | 29 | AGRI | YACO | VMUT; LAJA; MULI |
| 25 | `profundidad` | DOUBLE | 0.0 | 2,946 | 0.0 | 378939.0 | 0; 4200; 1600 |
| 26 | `formacion` | VARCHAR | 0.0 | 29 | ANITA | yacoraite | vaca muerta; lajas; mulichinco |
| 27 | `idareapermisoconcesion` | VARCHAR | 0.0 | 117 | AAMA | ZNI | LCAM; LDL; FEO |
| 28 | `areapermisoconcesion` | VARCHAR | 0.0 | 117 | AGUA DEL CAJON | VEGA GRANDE | LOMA CAMPANA; LOMA LA LATA - SIERRA BARROSA; ESTACION FERNA… |
| 29 | `idareayacimiento` | VARCHAR | 0.0 | 157 | ACO | Z350 | LCLL; Z116; Z155 |
| 30 | `areayacimiento` | VARCHAR | 0.0 | 156 | AGUA DE AFUERA | VEGA GRANDE | LOMA CAMPANA-LLL; CUPEN MAHUIDA; ESTACION FERNANDEZ ORO |
| 31 | `cuenca` | VARCHAR | 0.0 | 4 | AUSTRAL | NOROESTE | NEUQUINA; AUSTRAL; GOLFO SAN JORGE |
| 32 | `provincia` | VARCHAR | 0.0 | 6 | Chubut | Santa Cruz | Neuquén; Rio Negro; Santa Cruz |
| 33 | `coordenadax` | DOUBLE | 0.0 | 4,922 | -71.99831 | -38.59007 | -68.8084; -68.2089123233049; -68.8267 |
| 34 | `coordenaday` | DOUBLE | 0.0 | 4,625 | -69.41577 | -24.11656 | -38.7158312799252; -38.3217; -38.3306 |
| 35 | `tipo_de_recurso` | VARCHAR | 0.0 | 1 | NO CONVENCIONAL | NO CONVENCIONAL | NO CONVENCIONAL |
| 36 | `proyecto` | VARCHAR | 0.0 | 2 | GAS PLUS | Sin Proyecto | Sin Proyecto; GAS PLUS |
| 37 | `clasificacion` | VARCHAR | 0.22 | 3 | EXPLORACION | SERVICIO | EXPLOTACION; EXPLORACION; SERVICIO |
| 38 | `subclasificacion` | VARCHAR | 0.22 | 8 | AVANZADA | SUMIDERO | DESARROLLO; EXPLORACION; AVANZADA |
| 39 | `sub_tipo_recurso` | VARCHAR | 0.11 | 2 | SHALE | TIGHT | SHALE; TIGHT |
| 40 | `fecha_data` | DATE | 0.0 | 249 | 2006-01-31 | 2026-09-30 | 2026-09-30; 2026-08-31; 2026-07-31 |
