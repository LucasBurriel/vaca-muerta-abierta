# vaca-muerta-abierta

**Los datos públicos por pozo de la Secretaría de Energía (Capítulo IV), bajados, medidos, limpiados y cruzados.
Código abierto, datos abiertos, linaje a la vista.**

*English version: [README.md](README.md).*

La Secretaría de Energía publica, para cada pozo del país, la producción mensual, las fracturas (longitud de rama,
etapas, arena, agua), un padrón con coordenadas y fechas de perforación, y la actividad de perforación. Es el mismo
dato que revenden los agregadores pagos, y viene sucio: tres identidades en texto libre, dos claves de pozo
distintas, fechas de relleno, ramas de longitud cero y un dataset "diario" que atrasa tres meses.

Este repositorio construye un **observatorio abierto** sobre eso, por fases que terminan cada una en algo publicado:

| fase | qué | estado |
|---|---|---|
| **F0 · Medir la suciedad** | descarga fechada y con hash de cada dataset; esquema real de cada archivo; informe de calidad con números y gráficos; borradores de alias; decisiones | **hecha** → [`informes/calidad-2026-10-30.md`](informes/calidad-2026-10-30.md) |
| F1 · Maestro de pozos | una fila por pozo físico, todas las grafías de su sigla como alias, operadora y formación normalizadas con tablas versionadas, coordenadas validadas; publicado como CSV/Parquet | siguiente |
| F2 · Indicadores | intensidades por metro, IP30/90/180, curvas tipo por cohorte con linaje, outliers marcados y no borrados | |
| F3 · Sitio | explorador interactivo + mapa, regenerado cada mes por CI | |
| F4 · Preguntas en lenguaje natural | un agente con herramientas de solo lectura sobre las tablas publicadas; ningún número sin su consulta | después |

## Qué encontró F0 (30-10-2026)

Informe completo: [`informes/calidad-2026-10-30.md`](informes/calidad-2026-10-30.md) (en inglés). Lo principal:

1. **`idpozo` no es un pozo.** Es *pozo × formación productiva*: 6.167 siglas del padrón tienen más de un
   `idpozo`, 6.019 porque cambia la formación. Los cruces entre datasets por `idpozo` son limpios (0 desacuerdos
   de sigla en 5.164 pozos de producción): el problema de identidad es de grano, no de grafía. Normalizar la sigla
   (trim / mayúsculas / quitar `(h)` / solo alfanuméricos) mueve los cruces menos de 0,3 %.
2. **Los datasets de perforación son agregados**, no por pozo: conteos mensuales por empresa × área × concepto.
   Las fechas de perforación y terminación por pozo están solo en el padrón, 40 % vacías, con `1900-01-01` de
   relleno (3.922 filas).
3. **Fractura: 41 % de los registros tienen longitud de rama = 0** (1.071 de 3.821 registros no convencionales de
   la Neuquina), 177 de ellos con ≥ 10 etapas, o sea horizontales con la longitud sin cargar. 1.169 pozos de
   producción de la Neuquina no tienen ningún registro de fractura. El archivo "de actualización diaria" está
   visiblemente incompleto en sus últimos 3-4 meses.
4. **Operadoras casi limpias, formaciones ya limpias.** 123 claves de operadora, 5 con dos grafías
   (`VISTA OIL & GAS ARGENTINA SAU` / `Vista Oil & Gas Argentina SA`, `PAN AMERICAN ENERGY (SUCURSAL ARGENTINA)
   LLC` / `PAN AMERICAN ENERGY SL`, …); dentro del archivo de producción `idempresa → empresa` es uno a uno.
   78 nombres de formación, cero variantes; el hueco real es que `vaca muerta` no trae nivel de navegación.
5. **La producción se publica completa y se revisa hacia atrás**: la cantidad de pozos con registro crece cada mes
   hasta el último (2026-09, un mes de atraso), sin mes parcial al final; `rectificado` marca las revisiones.
   Valores sospechosos hay pocos pero hay: 70 filas con longitud y latitud invertidas, 384 pozo-mes con producción
   y cero días efectivos, 15 con más de 31 días, 160 con profundidad > 8.000 m.

## Cómo correrlo

```bash
git clone https://github.com/LucasBurriel/vaca-muerta-abierta && cd vaca-muerta-abierta
pip install -e ".[dev]"
python -m pytest -q            # 41 tests, sin red, sin datos

python pipeline.py sources     # el catálogo (vma/sources.py)
python pipeline.py download    # ~460 MB -> data/raw/<hoy>/ + manifest.json (URL, bytes, sha256, last_modified de CKAN)
python pipeline.py schema      # esquema real de cada archivo -> docs/esquemas/*.md
python pipeline.py quality     # informes/calidad-<hoy>.md + docs/calidad-*.png + alias/*.csv  (~2 min)
```

Python 3.11+. Dependencias: `duckdb`, `pandas`, `matplotlib`. Los datos crudos nunca se versionan; el manifiesto
es lo que hace comparables dos descargas.

## Reglas del repositorio

- **Solo datos públicos**, citados con URL, licencia y fecha de descarga ([docs/fuentes.md](docs/fuentes.md)).
- **Código escrito de cero**; no se nombra ni se usa a ningún empleador, cliente o colega. Cada operadora de la
  cuenca es una fila de un dataset público y se trata igual.
- **Reproducible**: un comando por etapa, el mismo resultado en cualquier laptop, CI corre los tests en cada push.
- **El linaje es parte del dato**: cada regla de calidad es un predicado SQL impreso en el informe; cada indicador
  futuro lleva las columnas y la regla de las que sale.
- **Los outliers se marcan, no se borran. Lo que falta es "sin dato, porque…", nunca cero.**

Las decisiones (nombre, alcance, clave de pozo, unidades, relación con `capiv`) están en
[docs/decisiones.md](docs/decisiones.md).

## Licencia

Código: MIT. Datos: CC-BY 4.0, Secretaría de Energía de la Nación Argentina.
