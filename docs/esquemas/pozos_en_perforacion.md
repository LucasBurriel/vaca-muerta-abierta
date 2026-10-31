# `pozos_en_perforacion` — Pozos en Perforación

- Source: <https://datos.energia.gob.ar/dataset/perforacion-de-pozos-de-petroleo-y-gas> (CC-BY 4.0), file `pozos_en_perforacion.csv`
- Downloaded: 2026-10-31T00:16:44+00:00 · 68,256,503 bytes · sha256 `2a60a9044b52c826…`
- CKAN last_modified: 2026-10-20T05:01:10.624515
- Rows: **482,654** · Columns: **20**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `indice_tiempo` | VARCHAR | 0.0 | 213 | 2009-01 | 2026-09 | 2019-02; 2013-09; 2024-10 |
| 2 | `anio` | BIGINT | 0.0 | 18 | 2009.0 | 2026.0 | 2017; 2018; 2019 |
| 3 | `mes` | BIGINT | 0.0 | 12 | 1.0 | 12.0 | 9; 2; 1 |
| 4 | `idempresa` | VARCHAR | 0.0 | 98 | 2589 | YSUR | YPF; TPT; PAL |
| 5 | `empresa` | VARCHAR | 0.0 | 98 | ALIANZA PETROLERA A… | YSUR PETROLERA ARGE… | YPF S.A.; TECPETROL S.A.; PAN AMERICAN ENERGY SL |
| 6 | `idareapermisoconcesion` | VARCHAR | 0.0 | 499 | 123 | ZNI | CSN; ANG; VRG |
| 7 | `areapermisoconcesion` | VARCHAR | 0.0 | 479 | 25 DE MAYO - MEDANI… | ÑACATIMBAY | CHIHUIDO DE LA SIERRA NEGRA; ANTICLINAL GRANDE - CERRO DRAG… |
| 8 | `idareayacimiento` | VARCHAR | 0.0 | 1,301 | 1718 | ÑIRI | PS16; HER; SPI |
| 9 | `areayacimiento` | VARCHAR | 0.0 | 1,184 | 25 DE MAYO - MEDANI… | ÑIRIHUAU | POZOS SIN YACIMIENTO; PATA MORA; PUESTO HERNANDEZ |
| 10 | `idcuenca` | VARCHAR | 0.0 | 16 | CAN | NOR | NEU; GSJ; CAU |
| 11 | `cuenca` | VARCHAR | 0.0 | 16 | ARGENTINA NORTE | ÑIRIHUAU | NEUQUINA; GOLFO SAN JORGE; AUSTRAL |
| 12 | `idprovincia` | VARCHAR | 0.0 | 14 | 0 | Z | Q; M; U |
| 13 | `provincia` | VARCHAR | 0.0 | 14 | Chubut | Tierra del Fuego | Neuquén; Mendoza; Chubut |
| 14 | `idubicacion` | BIGINT | 0.0 | 2 | 1.0 | 2.0 | 1; 2 |
| 15 | `ubicacion` | VARCHAR | 0.0 | 2 | Off Shore | On Shore | On Shore; Off Shore |
| 16 | `idconcepto` | BIGINT | 0.0 | 4 | 1.0 | 4.0 | 3; 1; 2 |
| 17 | `concepto` | VARCHAR | 0.0 | 4 | Avanzada | Servicio | Explotación; Servicio; Exploración |
| 18 | `cantidad` | DOUBLE | 0.0 | 42 | 0.0 | 22.0 | 0; 0.00; 1 |
| 19 | `observaciones` | VARCHAR | 99.08 | 761 |   | Área revertida . De… | La empresa no opera este bloque; No operamos este bloque; S… |
| 20 | `fecha_data` | DATE | 0.0 | 213 | 2009-01-31 | 2026-09-30 | 2019-02-28; 2013-09-30; 2024-10-31 |
