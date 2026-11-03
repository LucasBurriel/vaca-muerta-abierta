# Precios públicos y valorización en dólares (F6, `vma/precios/`)

Hasta F5 el observatorio hablaba en m³/d. Un ingeniero compara así; un gerente pregunta cuánto vale. F6 agrega lo
mínimo para contestar con la misma disciplina: **precios públicos** del portal, publicados como una tabla más con su
cita, y una **valorización** que multiplica volúmenes por precio y descuenta. Primero el límite, como en la
simulación: lo que sale es **ingreso bruto** (volumen × precio). No hay capex, ni opex, ni transporte, ni impuestos;
las regalías se restan sólo si se pide. No es una evaluación económica y cada bloque lo dice en sus `notas`
(ADR-035).

## Fuentes (ADR-034)

Dos datasets opt-in del catálogo ampliado ([fuentes.md](fuentes.md)), ambos CC-BY 4.0 de la Secretaría de Energía:

| fuente (`vma/sources.py`) | qué trae | grano | desde | se descarga con |
|---|---|---|---|---|
| `regalias_crudo` | *Informe Regalías CRUDO.xlsx* dentro de un ZIP: hoja `Tabla precios` = **precio promedio de venta realizado del crudo en USD/m³**, el que las provincias informan para liquidar regalías; `Tabla producción` = producción computable (m³); `Tabla regalías` = regalías pagadas (USD) | provincia × mes | 1991-01 | `python pipeline.py download regalias_crudo` |
| `precios_gas` | CSV Res. 1/2018: **USD/MMBTU** por cuenca, mes, tipo de contrato (`firme`, `interrumpible`, `total`) y segmento (`distribuidora`, `gnc`, `usina`, `industria`, `otros`, `ppp`, `expo`) | cuenca × mes × contrato × segmento | 2019-01 | `python pipeline.py download precios_gas` |

Lo que el portal **no** tiene y por eso no está: un precio de gas por provincia (las regalías de gas son otro ZIP del
mismo dataset, catalogado como *later*), el precio de boca de pozo por operadora, precios de condensado y GLP por
separado, un precio forward o un índice internacional al día (los datasets de precio internacional y de Escalante
están sin actualizar desde 2016-2020).

### Cómo se lee el XLSX

Las tres hojas `Tabla …` son tablas dinámicas con la misma forma: una fila de encabezado `AÑO | MES | CHUBUT |
ESTADO NACIONAL | FORMOSA | JUJUY | LA PAMPA | MENDOZA | NEUQUEN | RIO NEGRO | SALTA | SANTA CRUZ | TIERRA DEL FUEGO |
TOTAL PROVINCIA`, y debajo una fila por mes con el año escrito sólo en enero. La fila del encabezado cambia de
posición entre hojas (13, 11 y 10 en el archivo del 2026-10-06), así que el parser (`vma/precios/fuentes.py`) la
busca por contenido, no por número de fila. Las celdas valen **0 donde no hay nada que informar** (meses todavía no
reportados, provincias sin producción): un 0 se lee como *sin precio*, nunca como precio. La fila 1 trae la fecha
de realización del informe y la fila 2 avisa que los dos últimos períodos son provisorios; la tabla los marca con
`provisorio = true`. La hoja `detalle de tipos de crudo` dice qué crudo representa a cada cuenca (Medanito = Neuquina)
y se documenta, no se carga.

## La tabla `precios`

`python pipeline.py precios` parsea el último `data/raw/<fecha>/` que tenga cada archivo y publica
`data/publicado/<fecha>/precios.{csv,parquet}` al lado de las otras tablas (en la carpeta de la última publicación
con `pozos`, `indicadores` y `curvas_tipo`, para que `vma.consulta.datos` las abra juntas) y el snapshot
`site/data/precios.json`. Grano: **producto × región × mes × segmento × contrato**.

| columna | qué es |
|---|---|
| `producto` | `petroleo` \| `gas` |
| `region`, `tipo_region` | provincia (petróleo: `Neuquén`, `Río Negro`, `Mendoza`, `La Pampa`, `Chubut`, `Santa Cruz`, `Tierra del Fuego`, `Salta`, `Jujuy`, `Formosa`, `Estado Nacional`, `Total Provincia`) o cuenca (gas: `Neuquina`, `Golfo de San Jorge`, `Austral Santa Cruz`, `Austral Tierra del Fuego`, `Noroeste`, `Total Cuenca`) |
| `anio`, `mes`, `mes_fecha` | mes calendario |
| `fuente` | `regalias_crudo` \| `precios_gas` |
| `segmento`, `contrato` | petróleo: `promedio_venta`, sin contrato; gas: los siete segmentos × tres contratos |
| `unidad_dataset`, `precio_dataset` | el número tal cual lo publica la fuente: USD/m³ o USD/MMBTU |
| `precio_usd_m3`, `precio_usd_mil_m3` | el mismo precio en las unidades en que el observatorio guarda volúmenes (petróleo m³, gas mil m³) |
| `provisorio` | petróleo: los dos últimos meses informados; gas: siempre `false` (la fuente no lo marca) |
| `produccion_m3`, `regalias_usd` | sólo petróleo: producción computable y regalías pagadas por la provincia ese mes |
| `fecha_realizacion`, `fecha_descarga`, `version` | linaje: fecha del informe (fila 1 del XLSX), fecha de la descarga, carpeta de publicación |

El snapshot JSON del sitio (lo único que tiene un clon fresco, ADR-023) recorta: petróleo desde 2006 (primera
producción del Capítulo IV) y gas sólo con `contrato = total`; `describir_tabla("precios")` lo dice. Si la tabla no
está publicada en la fuente (ni Parquet ni JSON), existe igual con cero filas: las herramientas contestan
`sin_dato_porque` y dicen qué correr, nunca fallan.

### Conversión MMBTU → mil m³ (una decisión a revisar)

El gas del Capítulo IV se publica en miles de m³; el precio, en USD/MMBTU. La conversión usa el **poder calorífico
de referencia argentino, 9.300 kcal/m³** (la base en que se declaran los volúmenes de gas según la Res. 319/93 y en
que ENARGAS expresa los m³ "de 9.300") y **1 MMBTU = 252.000 kcal** (1 BTU = 0,252 kcal, el redondeo habitual):

```
1 mil m³ = 1.000 × 9.300 / 252.000 = 36,905 MMBTU
precio_usd_mil_m3 = precio_usd_mmbtu × 36,905
```

Está en `vma/units.py` (`MMBTU_PER_THOUSAND_M3`) y en cada nota del bloque `usd`. Por qué es una aproximación: el
gas rico de la ventana de petróleo de Vaca Muerta puede superar las 10.000 kcal/m³; si los volúmenes publicados son
físicos y no "de 9.300", ese gas vale más por m³ de lo que esta conversión dice. El sentido del error es conocido
(subestima) y se declara; la alternativa, un poder calorífico por pozo, no está en los datos públicos.

### Qué precio de gas se usa por defecto

`ppp` con contrato `total`: el **precio promedio ponderado** de todos los segmentos, firme más interrumpible, de la
cuenca. Es el más parecido a "lo que se cobra en promedio"; `valorizar.segmento_gas` / `contrato_gas` eligen otro
(por ejemplo `expo` o `usina firme`). Para el petróleo hay un solo precio por provincia.

## La herramienta `precios`

`precios(producto, region?, desde?, hasta?, segmento?, contrato?)` devuelve la serie mensual con su cita
(`cita.tabla = precios`), el último mes publicado, si es provisorio, el resumen (último, promedio, mín, máx) y las
regiones disponibles. Por defecto `Neuquén` para petróleo y `Neuquina` para gas, los últimos 24 meses, hasta 240
filas. Los nombres de región se resuelven sin acentos ni mayúsculas (`rio negro` → `Río Negro`).

## Valorización: el parámetro `valorizar` (ADR-035)

Cinco herramientas aceptan `valorizar = {modo, precio_flat?, tasa_anual?, regalia?, mes0?, region_petroleo?,
region_gas?, segmento_gas?, contrato_gas?, uptime?}` y agregan al resultado un bloque `usd`. **Sin el parámetro el
resultado es exactamente el de antes.** `vma/precios/valorizar.py` es una función pura: recibe petróleo m³ y gas
mil m³ por mes (mes 0 primero) y una serie de precio por producto, y devuelve USD por mes, acumulado y VAN.

### Modos de precio

| modo | precio de cada mes | mes0 | cuándo usarlo |
|---|---|---|---|
| `historico` | el publicado para el mes calendario (`mes0 + k`) en la provincia / cuenca; después del último publicado se mantiene el último (y se cuenta en `meses_con_ultimo_precio`); antes del primero no hay USD (`meses_sin_precio`) | obligatorio; cada herramienta propone uno (abajo) | pozos reales: lo que de verdad se cobró mes a mes |
| `flat` | uno por producto, dado por el usuario en `precio_flat`: `petroleo_usd_m3` o `petroleo_usd_bbl` (× 6,2898 bbl/m³), `gas_usd_mil_m3` o `gas_usd_mmbtu` (× 36,905) | opcional | sensibilidad: "¿y a 65 USD/bbl?" |
| `ultimo` | el último publicado de cada producto en la región, constante | opcional | campañas futuras y curvas tipo sin calendario |

### VAN y regalía

`van_usd = Σ ingreso_usd(k) × (1 + tasa_anual)^(-k/12)`, mes 0 sin descontar, `tasa_anual` **10 % por defecto** (una
tasa real en dólares usual para ordenar escenarios; no es una recomendación). `regalia` (fracción, 0 por defecto)
resta esa parte del bruto antes de acumular y descontar: `regalia = 0.12` es la **alícuota base** de la ley de
hidrocarburos; las alícuotas efectivas por provincia y concesión difieren (hay reducciones y recargos) y no están
en los datos. `bruto_usd`, `regalia_usd` e `ingreso_usd` vienen por separado.

### Qué valoriza cada herramienta

| herramienta | series del bloque `usd` | modo por defecto | mes0 por defecto | región por defecto |
|---|---|---|---|---|
| `curva_tipo` | `p10`, `p50`, `p90`: las curvas absolutas de **petróleo y gas** del grupo (aunque se haya pedido otra `tasa`), volumen = tasa × 30,44 d × `uptime` (0,92) | `ultimo` | enero de la cohorte | Neuquén / Neuquina |
| `comparar_mi_pozo` | `mio`: mis volúmenes reales; `grupo_p10/p50/p90`: el pozo tipo en los mismos meses calendario, con mi uptime observado | `historico` | mi primer mes con producción | Neuquén / Neuquina (mis datos no traen provincia) |
| `comparar_mi_campania` | por pozo: ingreso y VAN de sus **primeros 12 meses**; `mediana_publica_acum12_usd` = mediana del acum12 público del grupo × el precio promedio que usó mi pozo; resumen de la campaña | `historico` | el primer mes de cada pozo | ídem |
| `pronosticar_pozo` | `pronostico`: el volumen mensual del P50 (historia observada + curva ajustada), petróleo **o** gas según `tasa`; la banda bootstrap del EUR no se valoriza | `historico` | primer mes de la serie | pozo público: su provincia y cuenca del maestro; mío: Neuquén / Neuquina |
| `simular_campania` | `p10`, `p50`, `p90`: la banda del acumulado convertida a volumen mensual, petróleo **o** gas según `tasa` | `ultimo` | ninguno (`historico` exige `mes0`) | Neuquén / Neuquina |

Cuando una región cae al default, la nota lo dice y `valorizar.region_petroleo` / `region_gas` la cambian; una
región que no existe en la tabla es un error, con la lista de las que hay. En `curva_tipo` los P10 de petróleo y
de gas no son los mismos pozos: la banda en USD es una envolvente, no la distribución del ingreso por pozo.

### El bloque `usd`

```json
{"modo": "ultimo", "mes0": "2022-01", "tasa_anual": 0.1, "regalia": 0.12,
 "p50": {"precios": {"petroleo": {"region": "Neuquén", "unidad": "USD/m³", "ultimo_mes_publicado": "2026-08", "ultimo_precio": 498.4},
                     "gas": {"region": "Neuquina", "segmento": "ppp", "contrato": "total", "unidad": "USD/mil m³", "ultimo_precio": 145.4}},
         "series": {"mes": [0, 1, "..."], "ingreso_usd": ["..."], "acumulado_usd": ["..."]},
         "total": {"meses": 37, "petroleo_usd": 34350000, "gas_usd": 1078000, "bruto_usd": 35430000, "regalia_usd": 4252000,
                   "ingreso_usd": 31180000, "van_usd": 28260000, "meses_sin_precio": 0, "meses_con_ultimo_precio": 0}},
 "p10": "...", "p90": "...",
 "cita": {"tabla": "precios", "columnas": ["producto", "region", "anio", "mes", "precio_usd_m3", "precio_usd_mil_m3", "provisorio"],
          "filtros": {"modo": "ultimo", "petroleo": {"region": "Neuquén", "segmento": "promedio_venta"}, "gas": {"region": "Neuquina", "segmento": "ppp", "contrato": "total"}},
          "regla_doc": "docs/precios.md; ADR-034, ADR-035"},
 "notas": ["ingreso BRUTO = volumen × precio: sin capex, sin opex, ...", "gas: USD/MMBTU → USD/mil m³ con 9.300 kcal/m³ ...", "..."]}
```

Con `modo = flat` la cita dice `precio_flat (del usuario)`: ese número no es público y el agente debe decirlo.

## En las vistas MCP Apps

Las vistas de la curva tipo (`comparar_mi_pozo`) y del simulador tienen un conmutador **m³/d | USD/mes** y tarjetas
de VAN cuando el resultado trae `usd`; sin el bloque se ven como antes. El simulador suma al formulario el modo de
precio, el precio flat (USD/bbl o USD/MMBTU según el fluido), `mes0`, la tasa y la regalía, y los manda en
`valorizar` al re-simular ([mcp-apps.md](mcp-apps.md)).

## Límites, en una lista

- Ingreso bruto. Sin costos de ningún tipo, sin impuestos, sin retenciones a la exportación, sin diferencial de
  calidad por pozo, sin curva forward: el modo `ultimo` congela el último precio.
- El precio del crudo es el promedio provincial realizado para regalías, no el de un contrato ni el de un pozo; el
  del gas es un promedio de cuenca por segmento. Los dos últimos meses del crudo son provisorios.
- La conversión del gas asume 9.300 kcal/m³ (arriba): subestima el gas rico.
- Mis pozos no traen provincia ni cuenca: valen a precio de Neuquén / Neuquina salvo que se indique otra región.
- Sin series mensuales públicas por pozo (ADR-022), la mediana pública en USD de `comparar_mi_campania` es el
  acum12 público a un precio promedio, no una valorización mes a mes.
- La banda bootstrap del EUR y las bandas de campaña se valorizan cuantil por cuantil (un P10 de volumen a un
  precio fijo), no como distribución conjunta de precio y volumen: no hay incertidumbre de precio.

## Tests

`tests/test_precios.py`: los parsers sobre fixtures con el layout real (`tests/fixtures/precios/`, números
redondos), la tabla y su snapshot en las dos fuentes, la valorización con cifras calculadas a mano (modo histórico
con precio provisorio y último precio, flat con conversión de bbl y MMBTU, último, VAN a 0 % y 10 %, regalía), las
cinco herramientas con y sin `valorizar` (sin el parámetro, el resultado es idéntico), la fuente sin tabla y las
vistas con y sin el bloque.
