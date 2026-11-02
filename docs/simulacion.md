# Simulación: declinación y campañas sobre datos públicos (F5, `vma/simulacion/`)

Primero el límite, porque define todo lo demás: **esto no es simulación de reservorio**. El Capítulo IV publica
volúmenes mensuales por pozo y días efectivos; no publica presiones, PVT, permeabilidades, espaciamiento ni
geomecánica. Con eso se puede hacer una sola cosa con rigor: ajustar la **forma** de la declinación de un pozo o de
una curva tipo y proyectarla, y muestrear la **dispersión entre pozos** que la curva tipo publicada ya muestra. Las
tres herramientas lo dicen en cada resultado (`notas`), y el EUR que devuelven es *el volumen que implica la curva
ajustada*, no una reserva: sin precio, sin costo, sin operaciones.

## Modelos (`vma/simulacion/declinacion.py`)

`t` en meses desde la primera producción, tomado a mitad de mes (`t = mes + 0.5`); `q` tasa por **día efectivo**
(ADR-016), así los meses con paradas no deforman la curva.

| modelo | ecuación | parámetros | uso |
|---|---|---|---|
| exponencial | `q = qi · e^(−D t)` | `qi`, `D` (1/mes) | pozos maduros, cola |
| hiperbólico | `q = qi · (1 + b D t)^(−1/b)` | `qi`, `D`, `b` ∈ (0, 2] | Arps clásico; con `b > 1` el volumen diverge, por eso: |
| terminal `d_min` | cuando la declinación instantánea baja de `d_min_anual` (6 %/año por defecto) la curva sigue exponencial a esa tasa | `d_min_anual` | Arps modificado, estándar de la industria |
| armónico | hiperbólico con `b = 1` | `qi`, `D` | caso límite, se reporta aparte |
| Duong | `q = q1 · t^(−m) · exp( a/(1−m) · (t^(1−m) − 1) )` | `q1`, `a`, `m` | flujo transitorio largo (shale); también capado por `d_min` |

**Ajuste**: mínimos cuadrados sobre `ln q` (los primeros meses no dominan), resuelto con álgebra lineal sobre una
grilla del parámetro no lineal: para `b` fijo, `q^(−b)` es lineal en `t`; para `m` fijo, `ln q` es lineal en
`(1, ln t, g(t))`. Sin optimizador, sin SciPy, determinista. Se omiten los primeros `omitir_meses` (2) meses
(limpieza, flowback) y hacen falta al menos 6 meses con tasa > 0. Con `modelo = auto` se ajustan los cuatro y gana
el menor AIC sobre los residuos logarítmicos; la tabla `comparacion_modelos` muestra los cuatro con AIC y RMSE.

**EUR**: la curva se integra mes a mes hasta el horizonte (10-30 años) con `uptime` = días efectivos / días
calendario observados en el pozo (o el valor dado), y se corta en `q_min` si se pasa (`mes_limite_economico`). Los
meses con historia conservan el volumen observado; la curva reemplaza desde el último mes con dato. `eur_restante`
= EUR − acumulado observado.

**Banda**: bootstrap de residuos. Se remuestrean con reposición los residuos logarítmicos del ajuste, se suman a la
curva ajustada, se reajusta el mismo modelo y se recalcula el EUR, `n_bootstrap` (200) veces; se informan P10/P50/
P90 del EUR con la convención petrolera (P10 alto) y la mediana de los parámetros. Mide la incertidumbre del ajuste
*a esta historia*; no mide un cambio de régimen (interferencia con un pozo hijo, rebaje, cierre por instalaciones),
y la nota lo dice.

## Herramientas

### `pronosticar_pozo(sigla, mio?, tasa?, modelo?, horizonte_anios?, omitir_meses?, n_bootstrap?, d_min_anual?, q_min?, uptime?)`

Un pozo público (`sigla_clave`, de `buscar_pozo`) o uno mío (`mio = true`, tras `cargar_mis_pozos`). La serie de un
pozo público no está en las tablas publicadas (ADR-022): se arma desde `data/raw/<fecha>/produccion_nc.csv` sumando
sus `idpozo` como hace `vma/indicadores.py`; necesita la fuente Parquet y el crudo descargado (la primera llamada
carga las columnas necesarias en la conexión, unos segundos; las siguientes son inmediatas). En un clon fresco la
herramienta dice qué falta y remite a `pronosticar_curva_tipo`. Devuelve modelo y parámetros, comparación de
modelos, `historia` (meses, ajustados, última tasa, uptime observado), EUR, EUR restante, acumulado por año y la
banda bootstrap.

### `pronosticar_curva_tipo(nivel, claves, tasa?, modelo?, horizonte_anios?, incluye_outliers?, omitir_meses?, d_min_anual?, uptime?, q_min?)`

Ajusta por separado las curvas **P50, P10 y P90** publicadas de un grupo (`nivel`, `claves` como en `curva_tipo`) y
proyecta el *pozo tipo*: `eur_pozo_tipo` con P50 y la banda dada por los ajustes del P10 y del P90 (no es un intervalo
del P50: es lo que daría el pozo del decil alto y el del decil bajo). Funciona con el snapshot JSON (curvas hasta el
mes 60, ADR-023). Un cuantil que es 0 en más de la mitad de los meses (grupos que mezclan ventanas, ADR-020) no se
ajusta y lo dice. `uptime` por defecto 0.92 porque la curva tipo ya es por día efectivo y no trae calendario.

### `simular_campania(formacion, n_pozos, meses?, ventana?, cohorte_ref?, rama_m?, ritmo_pozos_por_mes?, tasa?, n_sim?, semilla?, uptime?, incluye_outliers?)`

Monte Carlo de `n_pozos` pozos nuevos (`vma/simulacion/campania.py`):

1. Se toma la curva tipo publicada de `formacion × cohorte_ref` (por defecto la cohorte más nueva con 24 meses
   publicables) `× ventana` si se da. Si se pasa `rama_m` y el grupo tiene curva **por metro** publicable, se
   muestrea la tasa por metro y se multiplica por la rama (la producción escala con el lateral); si no, se usa la
   curva absoluta y se avisa que la rama se ignoró.
2. Cada pozo simulado sortea una posición `u` uniforme en el grupo y la conserva toda su vida con un ruido mensual
   en espacio de percentil (σ 8 puntos); su tasa de cada mes se lee de los P90/P50/P10 publicados de ese mes por
   interpolación log-lineal (la inversa del percentil de `comparar_mi_pozo`).
3. Más allá del último mes publicado, cada cuantil se extiende con un ajuste hiperbólico de su cola (exponencial si
   no ajusta), empalmado al último valor y capado por `d_min` 6 %/año; `meses_extrapolados` lo cuenta.
4. Los pozos entran a `ritmo_pozos_por_mes` desde el mes 0 (por defecto todos juntos). Volumen mensual = tasa ×
   30.44 días × `uptime` (0.92).
5. `n_sim` (500) corridas; por mes de campaña P10/P50/P90 y media de la **tasa agregada** y del **acumulado**, pozos
   en línea, y el `final`: acumulado total con banda, acumulado por pozo con banda, tasa pico y mes del pico.

La banda es la dispersión publicada entre pozos y nada más. No hay interferencia padre-hijo, ni restricción de
instalaciones, ni curva de aprendizaje, ni precio, ni costo. Para una campaña homogénea hay que pasar `ventana`;
sin ella la curva mezcla fluidos (ADR-020) y la nota lo dice.

## Supuestos y límites, en una lista

- Tasas por día efectivo; el calendario entra por `uptime` (observado en el pozo, 0.92 en curvas y campañas).
- `t = mes + 0.5`; mes 0 = primer mes con petróleo o gas > 0 (igual que `indicadores`).
- Se omiten 2 meses iniciales y se exigen 6 puntos; con menos de 12 puntos ajustados la nota avisa que el
  pronóstico es débil.
- `b` ∈ (0, 2] en grilla de 0.05; `m` ∈ [0.5, 1.8] en grilla de 0.02; `a > 0`. Sin optimizador: el óptimo es el de
  la grilla.
- `d_min_anual` 6 % por defecto; con `b > 1` o Duong el EUR depende fuerte de ese valor y la nota lo dice.
- El bootstrap es i.i.d. sobre residuos logarítmicos; con autocorrelación fuerte subestima la banda.
- La campaña asume rangos de percentil persistentes (un buen pozo sigue bueno) con ruido mensual; no modela
  correlación espacial entre pozos de un pad ni degradación por hijos.
- Nada de esto reemplaza un modelo de reservorio ni un análisis económico; sirve para ordenar magnitudes y
  comparar escenarios con la misma vara, citando de dónde sale cada número.

## Tests

`tests/test_simulacion.py`: cada modelo recupera sus parámetros a partir de su propia curva; `auto` elige el
generador; la declinación terminal capa `b > 1`; el pronóstico conserva la historia, integra la curva (EUR
analítico del exponencial), corta en `q_min`, y la banda bootstrap está ordenada y centrada; la inversa del
percentil coincide con la directa; la campaña escala con la rama, escalona los pozos, ordena las bandas y extrapola
declinando; las tres herramientas en ambas fuentes con el sintético (`mio = true`) y las curvas falsas, con sus
errores explicados.
