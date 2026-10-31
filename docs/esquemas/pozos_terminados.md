# `pozos_terminados` — Pozos terminados

- Source: <https://datos.energia.gob.ar/dataset/perforacion-de-pozos-de-petroleo-y-gas> (CC-BY 4.0), file `pozos_terminados.csv`
- Downloaded: 2026-10-31T00:16:36+00:00 · 191,872,641 bytes · sha256 `8eb684fa92537f45…`
- CKAN last_modified: 2026-10-24T06:01:42.193376
- Rows: **1,189,600** · Columns: **22**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `indice_tiempo` | VARCHAR | 0.0 | 213 | 2009-01 | 2026-09 | 2024-10; 2017-02; 2017-01 |
| 2 | `anio` | BIGINT | 0.0 | 18 | 2009.0 | 2026.0 | 2022; 2017; 2018 |
| 3 | `mes` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 2; 9; 8 |
| 4 | `idempresa` | VARCHAR | 0.0 | 92 | 2589 | YSUR | YPF; TPT; PAL |
| 5 | `empresa` | VARCHAR | 0.0 | 92 | ALIANZA PETROLERA A… | YSUR PETROLERA ARGE… | YPF S.A.; TECPETROL S.A.; PAN AMERICAN ENERGY SL |
| 6 | `idareapermisoconcesion` | VARCHAR | 0.0 | 485 | 123 | ZNI | CSN; ANG; VRG |
| 7 | `areapermisoconcesion` | VARCHAR | 0.0 | 462 | 25 DE MAYO - MEDANI… | ÑACATIMBAY | CHIHUIDO DE LA SIERRA NEGRA; ANTICLINAL GRANDE - CERRO DRAG… |
| 8 | `idareayacimiento` | VARCHAR | 0.0 | 1,292 | 1718 | ÑAC | PS16; HER; SPI |
| 9 | `areayacimiento` | VARCHAR | 0.0 | 1,170 | 25 DE MAYO - MEDANI… | ÑACATIMBAY | POZOS SIN YACIMIENTO; PATA MORA; PUESTO HERNANDEZ |
| 10 | `idcuenca` | VARCHAR | 0.0 | 12 | CAN | NOR | NEU; GSJ; CAU |
| 11 | `cuenca` | VARCHAR | 0.0 | 12 | ARGENTINA NORTE | NOROESTE | NEUQUINA; GOLFO SAN JORGE; AUSTRAL |
| 12 | `idprovincia` | VARCHAR | 0.0 | 13 | 0 | Z | Q; M; U |
| 13 | `provincia` | VARCHAR | 0.0 | 13 | Chubut | Tierra del Fuego | Neuquén; Mendoza; Chubut |
| 14 | `idubicacion` | BIGINT | 0.0 | 2 | 1.0 | 2.0 | 1; 2 |
| 15 | `ubicacion` | VARCHAR | 0.0 | 2 | Off Shore | On Shore | On Shore; Off Shore |
| 16 | `idtipodepozoterminado` | BIGINT | 0.0 | 4 | 1.0 | 4.0 | 3; 1; 2 |
| 17 | `tipodepozoterminado` | VARCHAR | 0.0 | 4 | Avanzada | Servicio | Explotación; Exploración; Avanzada |
| 18 | `idconcepto` | BIGINT | 0.0 | 4 | 1.0 | 4.0 | 1; 3; 2 |
| 19 | `concepto` | VARCHAR | 0.0 | 4 | Improductivos | Servicio | Productivos de Petróleo; Improductivos; Productivos de Gas |
| 20 | `cantidad` | DOUBLE | 0.0 | 35 | 0.0 | 20.0 | 0; 0.00; 1 |
| 21 | `observaciones` | VARCHAR | 99.1 | 1,482 |  AREA REVERTIDA | Área revertida . De… | -; PAE; SIN ACTIVIDAD |
| 22 | `fecha_data` | DATE | 0.0 | 213 | 2009-01-31 | 2026-09-30 | 2024-10-31; 2017-02-28; 2017-01-31 |
