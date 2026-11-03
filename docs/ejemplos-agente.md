# Agent transcripts (F4)

Five questions run on 2026-11-01 against the published tables of `data/publicado/2026-10-31/` (Parquet, downloaded
2026-10-30) with `python agente.py --proveedor mock`. **No model was involved**: the machine that built this phase had
no `ANTHROPIC_API_KEY`, so the transcripts show the *mock* provider, a scripted planner that picks the tool from
keywords and writes its answer only from the tool results (ADR-028). The tools, their citations, the validator and the
numbers are the real ones; what Claude adds is the question understanding and the prose. With a key, the same command
runs `claude-opus-5-5` under the system prompt in `vma/consulta/agente.py` and prints the model's answer in the same
shape (every number followed by its `[tabla.columna; filtros; n]`).

Each transcript lists the tool calls the loop made (`->`), the answer, and the validator's verdict.

## ¿Qué operadora tiene la mejor mediana de IP90 de petróleo por metro en Vaca Muerta, ventana de petróleo, cohorte 2024?

```
-> ranking({"filtros": {"formacion": "Vaca Muerta", "ventana": "petroleo", "cohorte": 2024}, "top": 5})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- ranking de ip90_petroleo_m3_d_por_m (m³/d por m de rama, primeros 90 días efectivos) [indicadores: ip90_petroleo_m3_d_por_m, operadora, en_alcance, flags; formacion = Vaca Muerta, ventana = petroleo, cohorte = 2024, en_alcance = True, incluye_outliers = True, n_min = 5]:
  · PHOENIX GLOBAL RESOURCES S.A.: mediana 0.06645, P25 0.0516, P75 0.08425, n = 10 de 10
  · VISTA ENERGY ARGENTINA SAU: mediana 0.06231, P25 0.0548, P75 0.07547, n = 48 de 50
  · SHELL ARGENTINA S.A.: mediana 0.04888, P25 0.03063, P75 0.06415, n = 22 de 22
  · YPF S.A.: mediana 0.04557, P25 0.03618, P75 0.05695, n = 111 de 128
  · PAN AMERICAN ENERGY SL: mediana 0.03058, P25 0.0266, P75 0.03817, n = 16 de 19
  Sin dato porque: flags sin_rama_sin_fractura: 25; flags rama_corta: 1
  Exclusión: 3 grupo(s) con menos de 5 pozos con dato quedan fuera del ranking (ADR-017)
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 2, reintentos 0.

## Ficha del pozo YPF.Nq.LACh-125(h)

```
-> buscar_pozo({"texto": "YPF.Nq.LACh-125(h)"})
-> ficha_pozo({"sigla_clave": "YPF.NQ.LACH-125(H)"})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- buscar_pozo: 1 coincidencia(s) [pozos: sigla, sigla_clave, operadora, formacion; texto = YPF.Nq.LACh-125(h)]
- Pozo YPF.Nq.LACh-125(h) (YPF S.A., Vaca Muerta, cohorte 2024, ventana petroleo): rama_m = 4147, etapas = 71, ip90_petroleo_m3_d = 288.8 m³/d por día efectivo, ip90_petroleo_m3_d_por_m = 0.06964, gor12_m3_m3 = 146.2 [pozos + indicadores: acum12_agua_m3, acum12_equivalente_m3, acum12_equivalente_m3_por_m, acum12_gas_mil_m3; sigla_clave = YPF.NQ.LACH-125(H)]
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 3, reintentos 0.

## Compará la rama lateral de Vaca Muerta cohorte 2024 por ventana de fluido

```
-> comparar_grupo({"formacion": "Vaca Muerta", "cohorte": 2024, "dimension": "ventana", "metrica": "rama_m"})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- comparar_grupo de rama_m (m de rama lateral) [indicadores: rama_m, ventana, en_alcance, flags; formacion = Vaca Muerta, cohorte = 2024, en_alcance = True, incluye_outliers = True, n_min = 5]:
  · volatil_condensado: mediana 2888.0, P25 2438.0, P75 3083.0, n = 96 de 102
  · petroleo: mediana 2845.0, P25 2460, P75 3154.0, n = 212 de 237
  · gas: mediana 2800, P25 2499, P75 3026.0, n = 66 de 67
  Sin dato porque: flags sin_rama_sin_fractura: 32
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 2, reintentos 0.

## ¿Cómo es la curva tipo de Vaca Muerta 2022 en la ventana de petróleo?

```
-> curva_tipo({"nivel": "cohorte_formacion_ventana", "claves": {"cohorte": 2022, "formacion": "Vaca Muerta", "ventana": "petroleo"}, "mes_max": 12})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- Curva tipo de petroleo_m3_d por día efectivo [curvas_tipo: mes, n_pozos, n_pozos_por_m, publicable; nivel = cohorte_formacion_ventana, cohorte = 2022, formacion = Vaca Muerta, ventana = petroleo, incluye_outliers = True, mes_max = 12]:
  · mes 0: P50 48.55 (P10 99.75, P90 0.7989), n = 175
  · mes 1: P50 124.5 (P10 210.1, P90 56.21), n = 173
  · mes 2: P50 160.9 (P10 261.7, P90 82.8), n = 172
  · mes 3: P50 165.2 (P10 266.4, P90 96.11), n = 174
  · mes 4: P50 151.7 (P10 236.2, P90 83.07), n = 173
  · mes 5: P50 133.6 (P10 217.0, P90 72.28), n = 173
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 2, reintentos 0.

## ¿De qué fecha son los datos y qué tablas hay?

```
-> metadatos({})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- Datos: pozos 5750 filas, indicadores 5750 filas, curvas_tipo 151412 filas [meta: fecha_descarga, version_maestro, manifiesto.sha256]
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 2, reintentos 0.

## The validator at work (`--proveedor mock-sin-cita`)

The same question with a provider that adds an invented number (`123456,7 m³/d`) to its first answer. The validator
(`vma/consulta/validador.py`) finds no tool result containing it, sends one correction message, and the second answer
passes:

```
Validador: ok: todos los números de la respuesta salen de una herramienta · turnos 3, reintentos 1
```

With `reintentos_validador=0` the answer is shown prefixed with `ATENCION, número sin cita (123456,7); respuesta no verificada`.

A second, unplanned catch while writing this document: an earlier mock computed `len(columnas)` itself and wrote
"31 columnas"; the validator flagged `31` because no tool had returned it. The fix was in the tool, not in the
validator: `describir_tabla` now returns `n_columnas`. That is the intended division of labour: tools compute, the
model quotes.


# F5 · Comparar mis pozos (datos sintéticos)

Four questions run on 2026-11-02 against the same Parquet tables with `python agente.py --proveedor mock`, after
loading the **synthetic** "my wells" dataset committed in `tests/fixtures/sintetico/` (30 wells derived from public
Vaca Muerta wells with noise and new siglas, `python pipeline.py sintetico`; ADR-030). They are not anyone's wells:
every result says `DATOS SINTÉTICOS`. The mock plans from keywords (a path ending in `.csv`/`.parquet` loads it;
`MIO-nnn` names a well; "campaña PAD-x", "brecha", "pronóstico", "simulá … pozos" pick the tool) and writes only from
the tool results. With a key, Claude does the understanding; the tools, citations and numbers are the same.

## Cargá mis pozos de … y decime cómo está mi campaña PAD-B contra su grupo público

```
-> cargar_mis_pozos({"ruta": "tests/fixtures/sintetico/mis_pozos_produccion.csv", "ruta_pozos": "tests/fixtures/sintetico/mis_pozos_atributos.csv"})
-> comparar_mi_campania({"filtros": {"campania": "PAD-B"}})

(respuesta del proveedor mock: sin modelo, armada sólo con los resultados de las herramientas)
- Mis pozos cargados: 30 pozos, 1097 filas pozo-mes, período ['2022-05', '2026-09'], cohortes {'2022': 8, '2023': 8, '2024': 14} — DATOS SINTÉTICOS [mis_produccion + mis_pozos (sesión): sigla, fecha, petroleo_m3, gas_mil_m3; ruta = tests/fixtures/sintetico/mis_pozos_produccion.csv, ruta_pozos = tests/fixtures/sintetico/mis_pozos_atributos.csv]
- Mi campaña (ip90_petroleo_m3_d_por_m, filtros {'campania': 'PAD-B'}): 10 de 10 pozos comparados; mediana mía 0.05199 vs mediana de medianas públicas 0.05168; 5 pozos sobre la mediana pública; supera % mediano 54.27 [mis_indicadores (sesión) × indicadores: ip90_petroleo_m3_d_por_m, cohorte, formacion, ventana; filtros = {'campania': 'PAD-B'}, metrica = ip90_petroleo_m3_d_por_m, incluye_outliers = True]
  · MIO-029 (cohorte_formacion_ventana:2022/Vaca Muerta/petroleo): mío 0.1018, mediana pública 0.05278, supera 98.22 %
  · MIO-026 (cohorte_formacion_ventana:2023/Vaca Muerta/petroleo): mío 0.07239, mediana pública 0.05169, supera 87.91 %
  · MIO-017 (cohorte_formacion_ventana:2024/Vaca Muerta/petroleo): mío 0.06956, mediana pública 0.05166, supera 84.83 %
  · MIO-008 (cohorte_formacion_ventana:2024/Vaca Muerta/petroleo): mío 0.06015, mediana pública 0.05166, supera 70.62 %
  Nota: las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); los acumulados (acum*) son por meses calendario desde el mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok · turnos 2, reintentos 0. Each well is compared with the public median of *its own* cohort × formation
× window (the campaign mixes 2022, 2023 and 2024 wells), which is why the ranking view (MCP App) draws one bar per
well with its group named.

## Cargá mis pozos de …: ¿dónde está la brecha de mi pozo MIO-011 contra el P50?

```
-> cargar_mis_pozos({...})
-> brechas({"mes_max": 12, "sigla": "MIO-011"})

- Brechas contra P50 (petroleo_m3_d, hasta el mes 12): acumulado mío 25160.0 m³ vs 41340.0 a P50, brecha -16180.0 (-39.13 %); 1 de 1 pozos por debajo [mis_produccion (sesión) × curvas_tipo: mes, tef_d, petroleo_m3_d, petroleo_m3_d_p50; sigla = MIO-011, filtros = {}, tasa = petroleo_m3_d, incluye_outliers = True, mes_max = 12]
  · MIO-011: 12 de 13 meses debajo de P50 (0-5: 5, 6-11: 6, 12+: 1), brecha acumulada -16180.0 (-39.13 %), peor mes 0
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok · turnos 2, reintentos 0. The gap is "what the P50 would have produced on my producing days", not a
loss: the note in the full envelope says so, and the months below are split by stretch (0-5, 6-11, 12+) so an
engineer sees whether the well started weak or faded.

## Cargá mis pozos de … y hacé el pronóstico de EUR de mi pozo MIO-002

```
-> cargar_mis_pozos({...})
-> pronosticar_pozo({"sigla": "MIO-002", "mio": true, "n_bootstrap": 100})

- Pronóstico de MIO-002 (petroleo_m3_d): modelo exponencial {'qi': 287.9, 'D': 0.05882}, 43 meses ajustados, EUR a 240 meses 138200.0 m³ (histórico 128500.0, restante 9702.0); banda bootstrap P90 136000.0 / P50 138400.0 / P10 141800.0 (100 réplicas) [mis_produccion (sesión): mes, tef_d, petroleo_m3; sigla = MIO-002, mio = True, tasa = petroleo_m3_d, modelo = auto, horizonte_anios = 20, omitir_meses = 2, n_bootstrap = 100, d_min_anual = 0.06, uptime = 0.8577]
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok · turnos 2, reintentos 0. The AIC chose the exponential over hyperbolic, harmonic and Duong for this
(synthetic) 2022 well; the full envelope carries the four fits, the yearly cumulatives and the note that this is
decline-curve analysis, not reservoir simulation (ADR-031).

## Simulá una campaña de 12 pozos en Vaca Muerta, ventana de petróleo, cohorte 2022, con rama de 2800 m

```
-> simular_campania({"formacion": "Vaca Muerta", "n_pozos": 12, "meses": 120, "n_sim": 300, "ventana": "petroleo", "cohorte_ref": 2022, "rama_m": 2800.0})

- Campaña simulada de 12 pozos (Vaca Muerta 2022, petroleo, 300 corridas): acumulado a 120 meses P90 1154000.0 / P50 1365000.0 / P10 1581000.0 m³; por pozo P50 113800.0; tasa pico P50 2215.0 en el mes 3 [curvas_tipo: mes, petroleo_m3_d_por_m_p10, petroleo_m3_d_por_m_p50, petroleo_m3_d_por_m_p90; formacion = Vaca Muerta, cohorte_ref = 2022, ventana = petroleo, n_pozos = 12, meses = 120, rama_m = 2800.0, tasa = petroleo_m3_d, n_sim = 300, semilla = 0, uptime = 0.92, incluye_outliers = True]
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok · turnos 2, reintentos 0. Public data only (no "my wells" here): the per-metre curve of the 2022 oil
window scaled by a 2,800 m lateral, 12 wells starting together, the band being the published dispersion between
wells and nothing else (`docs/simulacion.md`). In Claude Desktop the same call opens the simulator view with sliders.

## ¿Cuánto vale en dólares, al último precio y neto de regalías, esa campaña de 12 pozos? (F6, 2026-11-02)

Run on 2026-11-02 with the `precios` table built from the two sources downloaded that day (crude prices realised
to 2026-08, gas to 2026-08).

```
-> simular_campania({"formacion": "Vaca Muerta", "n_pozos": 12, "meses": 120, "n_sim": 300, "ventana": "petroleo", "cohorte_ref": 2022, "rama_m": 2800.0, "valorizar": {"modo": "ultimo", "regalia": 0.12}})

- Campaña simulada de 12 pozos (Vaca Muerta 2022, petroleo, 300 corridas): acumulado a 120 meses P90 1154000.0 / P50 1365000.0 / P10 1581000.0 m³; por pozo P50 113800.0; tasa pico P50 2215.0 en el mes 3 [curvas_tipo: mes, petroleo_m3_d_por_m_p10, petroleo_m3_d_por_m_p50, petroleo_m3_d_por_m_p90; formacion = Vaca Muerta, cohorte_ref = 2022, ventana = petroleo, n_pozos = 12, meses = 120, rama_m = 2800.0, tasa = petroleo_m3_d, n_sim = 300, semilla = 0, uptime = 0.92, incluye_outliers = True]
  · USD p50 (120 meses, precio ultimo): ingreso 598700000.0 USD (bruto 680300000.0, regalía 81630000.0), VAN 484900000.0 USD al 0.1 anual [precios: producto, region, anio; modo = ultimo, tasa_anual = 0.1, regalia = 0.12, petroleo = {'region': 'Neuquén', 'segmento': 'promedio_venta'}]
  · USD p10 (120 meses, precio ultimo): ingreso 693400000.0 USD (bruto 787900000.0, regalía 94550000.0), VAN 558500000.0 USD al 0.1 anual [precios: …]
  · USD p90 (120 meses, precio ultimo): ingreso 506100000.0 USD (bruto 575100000.0, regalía 69020000.0), VAN 412300000.0 USD al 0.1 anual [precios: …]
  Nota USD: p10/p50/p90 = la banda del acumulado de la campaña (petroleo_m3_d) convertida a volumen mensual; modo historico necesita valorizar.mes0 (mes calendario del mes 0 de la campaña)
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok · turnos 2, reintentos 0. The same simulation, now in dollars: the P50 cumulative of 1.365 million m³
at the last realised Neuquén crude price (498.4 USD/m³ for 2026-08, provisional) is 680 million USD gross, 599
million after the 12 % royalty the question asked for, 485 million discounted at 10 % per year. The mock asked for
`modo = ultimo` because the question said "último precio" and `regalia = 0.12` because it said "regalías"; the full
envelope carries the price citation (`precios`, region, segment, last published month), the note that this is
gross revenue with no capex, opex or taxes, and that the gas price conversion assumes 9,300 kcal/m³ (ADR-034,
ADR-035). In Claude Desktop the simulator view shows the same as a **USD/mes** band with an NPV card.

## ¿A cuánto está el precio del gas en la cuenca Neuquina? (F6)

```
-> precios({"producto": "gas"})

- Precio de gas en Neuquina (ppp, total), 2024-09 a 2026-08: último 3.94 USD/MMBTU (2026-08), promedio 3.027, mín 2.4, máx 4.01 [precios: producto, region, segmento, contrato; producto = gas, region = Neuquina, segmento = ppp, contrato = total, desde = 2024-09, hasta = 2026-08]
  · 2026-06: 3.98 USD/MMBTU = 146.9 USD/mil m³
  · 2026-07: 3.96 USD/MMBTU = 146.1 USD/mil m³
  · 2026-08: 3.94 USD/MMBTU = 145.4 USD/mil m³
  Nota: gas: sin cuenca conocida; se usa el precio de Neuquina (ADR-035); valorizar.region_gas lo cambia
Datos: descargados el 2026-10-30, maestro 2026-10-31, fuente parquet
```

Validador: ok. The weighted average (`ppp`) over every segment under the `total` contract, the default the
valuation uses; `segmento` and `contrato` pick another series (`expo`, `usina` under `firme`…) and `region`
another basin. The USD per mil m³ column is the 9,300 kcal/m³ conversion (`docs/precios.md`).
