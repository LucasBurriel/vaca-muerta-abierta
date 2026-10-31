# `listado_pozos_operadoras` — Listado de pozos cargados por empresas operadoras

- Source: <https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo> (CC-BY 4.0), file `listado_pozos_operadoras.csv`
- Downloaded: 2026-10-31T00:16:34+00:00 · 27,071,868 bytes · sha256 `7ef1c43bf49098a7…`
- CKAN last_modified: 2025-10-20T05:12:58.170306
- Rows: **84,242** · Columns: **51**

Types are DuckDB's inference over the whole file; `null %` counts NULL plus empty strings;
`samples` are the three most frequent non-empty values.

| # | column | inferred type | null % | distinct | min | max | samples |
|--:|---|---|--:|--:|---|---|---|
| 1 | `idpozo` | BIGINT | 0.0 | 84,242 | 212.0 | 166844.0 | 67099; 67144; 52341 |
| 2 | `sigla` | VARCHAR | 0.0 | 77,061 |  PLU.LP.PP-1078 |  SJ.Md.NRSe.x-1 | YPF.Nq.EL-11; YPF.MdN.LoAl.x-1; YPF.MdN.CAm.a-95 |
| 3 | `formprod` | VARCHAR | 3.18 | 79 | AGRI | YACO | BBAR; CORI; CSEC |
| 4 | `idempresa` | VARCHAR | 0.0 | 93 |  | Z001 | YPF; PAE; VOA |
| 5 | `idareapermisoconcesion` | VARCHAR | 0.0 | 370 | AAB | ZNI | ANG; PER; CCC |
| 6 | `idareayacimiento` | VARCHAR | 0.0 | 1,196 | 4908 | ÑIRI | HER; BEH; PER |
| 7 | `idcuenca` | VARCHAR | 0.0 | 10 | % | NOR | GSJ; NEU; CCB |
| 8 | `idprovincia` | VARCHAR | 0.0 | 11 | 0 | Z | Z; U; Q |
| 9 | `codigopropio` | VARCHAR | 9.49 | 62,510 |   | ÑaCo-1 | VOA; OXY; 0 |
| 10 | `nombrepropio` | VARCHAR | 5.4 | 72,260 |  ADIS-20(d) | ÑaCo-1 | FOMICRUZ S.E; EL JABALI; EL CALDEN |
| 11 | `coordenadax` | DOUBLE | 0.0 | 74,827 | -72.1059 | 55.37631 | -68.311399; -68.252159; -68.384549 |
| 12 | `coordenaday` | DOUBLE | 0.0 | 73,386 | -69.41577 | -22.00255 | -37.3074; -45.822; -45.823 |
| 13 | `cota` | DOUBLE | 0.0 | 34,876 | -100.0 | 5543.41 | 317; 0; 318 |
| 14 | `profundidad` | DOUBLE | 0.0 | 6,493 | 0.0 | 378939.0 | 0; 1500; 1200 |
| 15 | `pet_inicial` | DOUBLE | 0.0 | 42,784 | 0.0 | 1912394.2 | 0; 0.00; 0.0 |
| 16 | `gas_inicial` | DOUBLE | 0.0 | 35,590 | 0.0 | 7901910.515 | 0; 0.00; 0.0 |
| 17 | `agua_inicial` | DOUBLE | 0.0 | 38,259 | 0.0 | 4835205.317 | 0; 0.00; 0.0 |
| 18 | `iny_agua_inicial` | DOUBLE | 0.0 | 3,703 | -3180821.0 | 10136596.35 | 0; 0.00; 0.0 |
| 19 | `iny_gas_inicial` | DOUBLE | 0.0 | 94 | -18885.503 | 2439485.55 | 0; 0.0; 0.00 |
| 20 | `iny_otros_inicial` | DOUBLE | 0.0 | 23 | 0.0 | 2501940.5 | 0; 0.00; 0.0 |
| 21 | `iny_co2_inicial` | DOUBLE | 0.0 | 3 | 0.0 | 0.0 | 0; 0.00; 0.0 |
| 22 | `vida_util_inicial` | DOUBLE | 0.0 | 15,932 | 0.0 | 257813.0 | 0; 0.00; 0.0 |
| 23 | `adjiv_fecha_inicio` | DATE | 39.74 | 18,851 | 1900-01-01 | 2025-09-08 | 1910-01-01; 2004-01-01; 1902-01-01 |
| 24 | `adjiv_equipo_utilizar` | VARCHAR | 39.77 | 2,010 |  H-104 H-202 | xx | 0; S/D - S/D; 0 - YPF |
| 25 | `adjiv_capacidad_perf` | DOUBLE | 40.25 | 175 | -9.123e+19 | 36000.0 | 0; 3000; 2000 |
| 26 | `adjiv_tipo_reservorio` | BIGINT | 25.54 | 4 | 1.0 | 4.0 | 2; 3; 1 |
| 27 | `adjiv_subtipo_reservorio` | BIGINT | 94.4 | 3 | 0.0 | 2.0 | 1; 2; 0 |
| 28 | `adjiv_fecha_fin` | DATE | 39.91 | 18,952 | 1900-01-01 | 2025-10-13 | 1910-01-02; 2004-01-31; 1902-01-01 |
| 29 | `adjiv_fecha_inicio_term` | DATE | 42.58 | 18,148 | 1900-01-01 | 2025-09-22 | 1910-01-03; 2004-02-01; 1902-01-12 |
| 30 | `adjiv_fecha_fin_term` | DATE | 42.58 | 18,189 | 1900-01-01 | 2025-10-01 | 1910-01-04; 2004-02-28; 1902-01-22 |
| 31 | `adjiv_fecha_abandono` | DATE | 95.08 | 2,767 | 1900-01-01 | 2025-07-17 | 2009-03-31; 2009-02-28; 2009-07-31 |
| 32 | `adjiv_clasificacion` | BIGINT | 21.28 | 5 | 0.0 | 4.0 | 1; 2; 3 |
| 33 | `adjiv_subclasificacion` | VARCHAR | 21.29 | 16 | 0 | XS | D; A; X |
| 34 | `fechadeingreso` | TIMESTAMP | 81.61 | 5,477 | 2013-08-01 16:04:50… | 2025-10-16 09:10:19… | 2014-08-14 18:23:16.995912; 2014-02-25 15:31:04.999948; 201… |
| 35 | `adjiv_comp_perf` | BIGINT | 39.92 | 30 | 0.0 | 29.0 | 0; 26; 16 |
| 36 | `unique_sigla_formprod` | BOOLEAN | 0.18 | 2 | f | t | t; f |
| 37 | `areapermisoconcesion` | VARCHAR | 0.0 | 370 | 25 DE MAYO - MEDANI… | VOLCAN AUCA MAHUIDA | ANTICLINAL GRANDE - CERRO DRAGON; LOS PERALES - LAS MESETAS… |
| 38 | `areayacimiento` | VARCHAR | 0.0 | 1,082 | 25 DE MAYO - MEDANI… | ÑIRIHUAU | PUESTO HERNANDEZ; MANANTIALES BEHR; LOS PERALES |
| 39 | `cuenca` | VARCHAR | 0.0 | 9 | ARGENTINA NORTE | ÑIRIHUAU | GOLFO SAN JORGE; NEUQUINA; CUYANA |
| 40 | `provincia` | VARCHAR | 0.0 | 11 | Chubut | Tierra del Fuego | Santa Cruz; Chubut; Neuquén |
| 41 | `petroleo` | DOUBLE | 0.0 | 66,519 | -0.002 | 1912394.2 | 0; 0.00; 0.000 |
| 42 | `gas` | DOUBLE | 0.0 | 57,272 | 0.0 | 16859305.7 | 0; 0.00; 0.000 |
| 43 | `agua` | DOUBLE | 0.0 | 62,738 | 0.0 | 7457034.709 | 0; 0.00; 0.000 |
| 44 | `periodo` | DOUBLE | 0.0 | 57,287 | 0.0 | 260512.52263 | 0; 0.00; 0.000 |
| 45 | `clasificacion` | VARCHAR | 21.29 | 4 | ALMACENAMIENTO | SERVICIO | EXPLOTACION; EXPLORACION; SERVICIO |
| 46 | `subclasificacion` | VARCHAR | 21.29 | 15 | ALMACENAMIENTO DE G… | SUMIDERO | DESARROLLO; AVANZADA; EXPLORACION |
| 47 | `tipo_reservorio` | VARCHAR | 25.54 | 4 | CONVENCIONAL | SIN RESERVORIO | CONVENCIONAL; NO CONVENCIONAL; SIN RESERVORIO |
| 48 | `subtipo_reservorio` | VARCHAR | 94.5 | 2 | SHALE | TIGHT | SHALE; TIGHT |
| 49 | `comp_perf` | VARCHAR | 39.92 | 29 | Almea Austral | YPF | SIN DATO; YPF; Pride International |
| 50 | `gasplus` | VARCHAR | 0.0 | 2 | no | si | no; si |
| 51 | `fecha_data` | TIMESTAMP | 81.61 | 5,477 | 2013-08-01 16:04:50… | 2025-10-16 09:10:19… | 2014-08-14 18:23:16.995912; 2014-02-25 15:31:04.999948; 201… |
