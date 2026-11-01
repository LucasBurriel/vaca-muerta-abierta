# Asking the tables questions (F4: `agente.py` · `mcp_server.py` · `vma/consulta/`)

Phase 4 puts an agent in front of the published tables. It runs **locally** (a CLI and an MCP server over stdio;
no hosting, no backend behind the site), it never writes SQL against the data unless you opt in, and every number
it says comes with the tool call that produced it. The brief's rule is the design: *sin cita no hay número*.

```
question ──> Claude (or the mock) ──> tool call ──> vma/consulta/herramientas.py ──> DuckDB over Parquet | JSON
                 ▲                                          │  {datos, cita, exclusiones, notas, fecha_datos, ...}
                 └── validator: every number in the answer must be in a tool result of the turn (one retry) ◀──┘
```

## The three layers

| layer | module | what it is | depends on a model |
|---|---|---|---|
| data | `vma/consulta/datos.py` | the three tables as DuckDB views, from `data/publicado/<date>/*.parquet` if built, else from the committed `site/data/*.json` snapshot (ADR-026). Declares which columns the source carries | no |
| tools | `vma/consulta/herramientas.py` | the closed set below; pure functions `tool(datos, **args) -> envelope`, parametrised SQL built from allowlists | no |
| loop | `vma/consulta/agente.py` | system prompt, tool loop, providers (`anthropic`, `mock`), transcript | only with `anthropic` |
| guard | `vma/consulta/validador.py` | numbers in the answer vs numbers in the tool results (ADR-027) | no |

`agente.py` (CLI, single question or `--chat`) and `mcp_server.py` (MCP stdio) are thin shells over the same registry
(`H.HERRAMIENTAS`), so a tool added once appears in both.

## The tools

Every tool returns the same envelope, and the model is told to quote `cita` next to each number:

```json
{"datos": "...",
 "cita": {"tabla": "indicadores", "columnas": ["ip90_petroleo_m3_d_por_m", "operadora", "en_alcance", "flags"],
          "filtros": {"formacion": "Vaca Muerta", "ventana": "petroleo", "cohorte": 2024, "en_alcance": true,
                      "incluye_outliers": true, "n_min": 5},
          "regla_doc": "docs/indicadores.md (ip90_petroleo_m3_d_por_m); mediana por operadora; ADR-017, ADR-018, ADR-020"},
 "exclusiones": ["3 grupo(s) con menos de 5 pozos con dato quedan fuera del ranking (ADR-017)"],
 "notas": ["las tasas (ip*, curvas tipo) son por día efectivo de producción (tef), no por día calendario (ADR-016); ..."],
 "fecha_datos": "2026-10-30", "version_maestro": "2026-10-31", "fuente": "parquet"}
```

| tool | arguments | answers | cites |
|---|---|---|---|
| `metadatos` | — | Qué datos hay: fecha de descarga, versión del maestro, fuente (parquet o json), tablas con filas y columnas, hashes SHA-256 del manifiesto | `meta.json` / `manifest.json` |
| `describir_tabla` | `tabla` ∈ pozos, indicadores, curvas_tipo | Columnas y tipos de una tabla publicada, filas, y la documentación donde está la regla de cada columna; for `indicadores`, the aggregable metrics; for `curvas_tipo`, levels and rates | `docs/maestro.md`, `docs/indicadores.md` |
| `buscar_pozo` | `texto`, `maximo` | Busca pozos por sigla con los niveles de normalización de `vma/normalize.py` (L2 upper + single spaces, L3 without `(h)`, L4 alphanumerics only, then substring); returns sigla, sigla_clave, operadora, formación and the level that matched | `pozos` |
| `ficha_pozo` | `sigla_clave` | Todo lo publicado de un pozo: maestro + indicadores, the flags, and for each null indicator its reason (`sin_dato_porque`: the flag that explains it, e.g. `ip90_petroleo_m3_d_por_m: flags sin_rama_sin_fractura`) | `pozos + indicadores` |
| `comparar_grupo` | `formacion`, `cohorte?`, `dimension` ∈ operadora, ventana, cohorte, area, formacion; `metrica`, `n_min` (5), `incluye_outliers`, `ventana?` | Compara una métrica de indicadores entre grupos de una formación: median, P25, P75, `n_pozos`, `n_con_dato` per group; groups under `n_min` listed apart with null statistics; how many wells have no value and by which flag | `indicadores` |
| `ranking` | `metrica`, `filtros` {formacion, cohorte, cohorte_desde, cohorte_hasta, ventana, operadora, area}, `n_min`, `por`, `orden`, `top`, `incluye_outliers` | Ordena grupos (por = operadora \| area \| formacion \| cohorte \| ventana) por la mediana de una métrica, with `n_pozos` and `n_con_dato`; warns when the ranking mixes fluid windows or formations | `indicadores` |
| `curva_tipo` | `nivel`, `claves` {cohorte, formacion[, ventana \| operadora]}, `incluye_outliers`, `tasa`, `mes_max` | Curva tipo publicada de un grupo: P10/P50/P90 (petroleum convention) per month since first production with `n_pozos`; months under 5 wells come with null statistics and the reason (ADR-017) | `curvas_tipo` |
| `sql_solo_lectura` | `sql`, `limite` | **Opt-in (`--sql`).** SELECT libre sobre pozos, indicadores y curvas_tipo: only SELECT/WITH, only those three tables, no file or system functions, no `;`, LIMIT forced (200), 10 s timeout. The citation is the query itself; the risk (a subtly wrong query that looks right) is documented in ADR-025 | the query |

Metrics (`metrica`) are the numeric columns of `indicadores` listed in `H.METRICAS` with their unit: laterals and
completion intensities, IP30/90/180 (per fluid, total and per metre), cumulatives at 6/12/24 months, GOR and water
cut. Formation and operator names are resolved loosely (`vaca muerta`, `operadora a`) to the canonical spelling and
the citation shows the resolved value. Everything is **in-scope only** (`en_alcance`, ADR-002) and **flagged outliers
stay in** unless `incluye_outliers=false`, in which case the exclusion is listed (ADR-018).

### Parquet vs JSON

The JSON snapshot ships what the site needs: 35 of the 72 indicator columns, 6 master columns, percentiles only, type
curves to month 60, 4 significant digits (ADR-022, ADR-023). A tool asked for a column the snapshot lacks does not
guess: `comparar_grupo(..., metrica="acum24_petroleo_m3")` answers *la fuente json no trae indicadores.acum24_petroleo_m3*
and lists what is available; `ficha_pozo` marks the missing master columns as *la fuente no lo trae*; `metadatos` and
`describir_tabla` say which source is open. To get everything: `python pipeline.py download master indicadores curvas`
(≈ 460 MB download) and the agent picks the Parquet up automatically.

## The validator (ADR-027)

`vma/consulta/validador.py` extracts every number the model wrote (Spanish and English formats: `0,062`, `1.206`,
`1,234.5`, `9 %`, ISO dates) and looks for each among the numbers any tool returned in the turn, accepting the rounding
the token shows (same significant digits, or half a unit of its last decimal). Numbers in the question or in the tool
arguments the model chose are free (it is restating the filter), so are integers up to 10 (ordinals) and numbers glued
to a word (`IP90`, `ADR-016`, `P50`). A number from nowhere is a *número sin cita*: the loop sends the model one
correction message with the offending tokens; if the second answer still fails, it is printed prefixed with
`ATENCION, número sin cita (...)`, never silently. Exit code 2 in that case.

The check is deliberately dumb: it cannot tell a right citation from a wrong one, only a number that exists in the
results from one that does not. That is enough to catch the failure mode that matters most (an invented or
"estimated" figure) and cheap enough to run on every answer.

## Providers

- `anthropic` (default when `ANTHROPIC_API_KEY` is set): `claude-opus-5-5`, streaming, adaptive thinking, effort
  `medium` (`--esfuerzo`), the system prompt cached. Thinking blocks are passed back unchanged. `stop_reason = refusal`
  is reported, not retried.
- `mock` (default otherwise, and the only one CI uses): a scripted planner that picks the tool from keywords (a sigla
  → `buscar_pozo` + `ficha_pozo`; "curva" → `curva_tipo`; "ranking/mejor/peor" → `ranking`; "compará/ventana/rama" →
  `comparar_grupo`; else `metadatos`) and writes an answer only from the results. `mock-sin-cita` adds an invented
  number to exercise the retry path. Transcripts in [`ejemplos-agente.md`](ejemplos-agente.md).

## Run it

```bash
pip install -e ".[dev,agente]"          # agente = anthropic + mcp; the tools and tests need neither
python agente.py "¿Qué operadora tiene la mejor mediana de IP90 por metro en Vaca Muerta, ventana de petróleo, cohorte 2024?"
python agente.py --chat
python agente.py --proveedor mock --fuente json "ficha del pozo YPF.Nq.LACh-125(h)"
python agente.py --sql --json "..."     # opt-in SQL, transcript as JSON
```

### MCP server (Claude Desktop, Claude Code, any MCP client)

```bash
python mcp_server.py            # Parquet if built, else site/data/; add --sql to expose sql_solo_lectura
```

`claude_desktop_config.json` (Claude Desktop) or `.mcp.json` in a project (Claude Code):

```json
{
  "mcpServers": {
    "vaca-muerta-abierta": {
      "command": "python",
      "args": ["C:/ruta/al/repo/vaca-muerta-abierta/mcp_server.py", "--fuente", "auto"]
    }
  }
}
```

On Linux/macOS use the absolute path of the clone and, if needed, the Python of the virtualenv as `command`. The
server has no tool that writes; it opens the tables read-only and exposes exactly the registry above.

## Tests

`tests/test_consulta.py`: both sources on synthetic tables (16 wells, two operators, two cohorts, two windows, one
without lateral, one outlier, one out of scope, one in Lajas), every tool with Parquet and with JSON, the envelope and
citation on every result, loose name resolution, `n_min` and outlier exclusions, nulls explained, the SQL allowlist
(nine rejected statements), the validator (accepts formats and rounding, rejects invented numbers and dates, frees the
question's numbers), the loop with the mock (citations, well flow, retry, tool errors returned as `is_error`, chat
history), the CLI with `--json`, and this document naming every tool. No network, no model, no real data.
