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
