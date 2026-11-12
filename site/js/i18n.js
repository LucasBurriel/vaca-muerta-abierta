// English for the whole site (ADR-037). Spanish is the source language and lives where it is used: in the HTML
// (elements marked data-i18n="key") and in the JavaScript (second argument of t()). This module holds the English
// of every key, the t() helper, and the code that swaps the static text when the page language is English.
//
// The language is decided by js/idioma.js before the first paint (?lang=, then the saved choice, then the browser).
// Column names of the tables (ip90_petroleo_m3_d, ...), ADR numbers and operator / formation names are never
// translated: they are identifiers. Units stay the source's metric ones; "mil m³" reads "thousand m³".

export const LANG = globalThis.__VMA_LANG === "en" ? "en" : "es";
export const LOCALE = LANG === "en" ? "en-US" : "es-AR";
const EXPLICITO = Boolean(globalThis.__VMA_LANG_EXPLICITO);

export const EN = {
  // --- header, footer, shared controls
  "nav.inicio": "Home",
  "nav.explorador": "Well explorer",
  "nav.curvas": "Type curves",
  "nav.simulador": "Simulator",
  "nav.mapa": "Map",
  "nav.metodo": "Method and sources",
  "cab.fecha": "data downloaded <b>{descarga}</b> · well master <b>{maestro}</b>",
  "cab.pie": "Data: {licencia} (Argentina's energy secretariat); downloaded {descarga}, tables published in <code>data/publicado/{maestro}/</code>. Code: MIT. Generated {generado}.",
  "filtro.operadora": "Operator",
  "filtro.formacion": "Formation",
  "filtro.cohorte": "Vintage",
  "filtro.ventana": "Fluid window",
  "sel.todas": "all",
  "sel.elegir": "choose…",
  "si": "yes",
  "no": "no",
  "error.datos": "The data could not be loaded: {mensaje}",
  "nulo.corto": "no data",
  "nulo.fuente": "no data: the source does not carry it",
  "nulo.fuente.corto": "the source does not carry it",
  "nulo.porque": "no data because: {razon}",

  // --- home
  "inicio.title": "Vaca Muerta abierta · open well data from Argentina's shale play",
  "inicio.desc": "Open observatory of Argentina's public well-by-well oil and gas data (Capítulo IV, Secretaría de Energía): wells, indicators per metre of lateral, type curves, a campaign simulator and a map.",
  "inicio.h1": "Argentina's public well-by-well data, cleaned and comparable",
  "inicio.lead": "Argentina's Secretaría de Energía publishes monthly production, frac jobs, coordinates and dates for every well in the country. This site downloads them, measures them, cross-references them and publishes the result with its lineage in view. Every number says which table and column it comes from: <span class=\"cita\" title=\"this is what a citation looks like\">table.column</span>. Code and method on <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta\">GitHub</a>.",
  "inicio.probar.titulo": "Try it: simulate a drilling campaign",
  "inicio.probar.texto": "Pick a formation, a fluid window and a vintage. Your browser draws 500 campaigns from the published type curve and returns production, gross revenue and NPV with a P10–P90 band. Nothing to install; every number carries its source.",
  "inicio.probar.boton": "Open the simulator →",
  "inicio.h2.fases": "What each phase found",
  "inicio.h2.grafico": "Vaca Muerta, oil window: laterals doubled and IP90 per metre held",
  "inicio.lead.grafico": "Medians by vintage (year of first production) for in-scope wells in the <code>petroleo</code> (oil) window. Rates are per <b>producing day</b>, not per calendar day (ADR-016). Vintages with fewer than 5 wells with a known lateral are shown faded.",
  "inicio.t.maestro": "physical wells in the well master",
  "inicio.t.alcance": "in scope: Neuquén Basin, unconventional",
  "inicio.t.productores": "with a first production month",
  "inicio.t.rama": "comparable per metre of lateral",
  "inicio.t.outliers": "IP90/m outliers out of {n} screened",
  "inicio.t.operadoras": "operators (aliases merged)",
  "inicio.t.formaciones": "formations",
  "inicio.t.ultima": "last month with production",
  "regla.pozos_maestro": "one row per physical well (ADR-003, ADR-011)",
  "regla.pozos_en_alcance": "cuenca = NEUQUINA and tipo_recurso = NO CONVENCIONAL (ADR-002)",
  "regla.pozos_productores": "in scope, with primera_produccion (ADR-013)",
  "regla.pozos_con_rama": "in scope, rama_m known and >= 500 m (ADR-019)",
  "regla.outliers": "= True (ADR-018)",
  "regla.operadoras": "distinct, in scope (alias/operadoras.csv, ADR-012)",
  "regla.formaciones": "distinct, in scope",
  "regla.ultima_produccion": "maximum",
  "regla.vaca_muerta_petroleo_por_cohorte": "in scope, formacion = Vaca Muerta, ventana = petroleo; medians by vintage",
  "inicio.f0": "<b>F0 · Measure the dirt.</b> <code>idpozo</code> is not a well but a well × formation; the drilling datasets are aggregates; 41 % of the frac records carry a lateral length of 0. <a href=\"{url}\">Data-quality report</a> (in Spanish).",
  "inicio.f1": "<b>F1 · Well master.</b> {n} physical wells {cita}, every spelling of the well name kept as an alias, operator and formation normalised with versioned alias tables, coordinates validated, lateral length with an explicit order of precedence. <a href=\"{url}\">Well-master report</a> (in Spanish).",
  "inicio.f2": "<b>F2 · Indicators.</b> IP30/90/180 in producing days, cumulatives, everything per metre of lateral where the lateral is known ({conRama} of {enAlcance} in scope {citaRama}), a fluid window per well ({petroleo} oil · {volatil} volatile oil / condensate · {gas} gas {citaVentana}), publishable type curves for {g1} vintage × formation groups, {g2} with fluid window and {g3} with operator {citaCurvas}. <a href=\"{url}\">Indicators report</a> (in Spanish).",
  "inicio.f3": "<b>F3 · This site.</b> Static, rebuilt every month by CI from the published tables (data date at the top right). <a href=\"{metodo}\">Method and sources</a>.",
  "inicio.f5": "<b>F5 · F6 · Simulate and value.</b> Decline fits, a campaign Monte Carlo drawn from the published type curves, and public prices to go from m³ to gross dollars. On this site, the <a href=\"{simulador}\">campaign simulator</a>; with your own wells, the local MCP server (<a href=\"{url}\">README</a>).",
  "inicio.tooltip": "<b>vintage {cohorte}</b> · n = {n} ({nIp} with IP90/m)<br>median lateral: {rama} m<br>median oil IP90/m: {ip} m³/d per m",
  "inicio.eje.rama": "median lateral length (m)",
  "inicio.eje.ip": "oil IP90 / m (m³/d per m)",
  "inicio.serie.rama": "rama_m (median)",
  "inicio.serie.ip": "ip90_petroleo_m3_d_por_m (median)",
  "inicio.cita.grafico": "Source: {citas} — {regla}. Faded bars: fewer than 5 wells with IP90/m (the line is omitted).",

  // --- well explorer
  "explorador.title": "Well explorer · Vaca Muerta abierta",
  "explorador.desc": "One row per physical well of the unconventional Neuquén Basin: lateral length, stages, IP90 and cumulatives per metre, GOR and water cut, with the reason for every missing value.",
  "explorador.h1": "Well explorer",
  "explorador.lead": "One row per physical well from the <code>indicadores</code> table (coordinates and status from <code>pozos</code>). Per-metre values exist only when the lateral length is known and is 500 m or more; where a value is missing, the cell says <b>why</b> (hover over it). Rates are per producing day, not per calendar day.",
  "explorador.buscar": "Search well name",
  "explorador.alcance": "in scope only (Neuquén Basin, unconventional)",
  "explorador.con_rama": "only wells with per-metre values",
  "explorador.descargar": "Download filtered CSV",
  "explorador.pie": "Columns and rules: <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/indicadores.md\">docs/indicadores.md</a> · <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/maestro.md\">docs/maestro.md</a>. Rows in colour are IP90/m outliers (ADR-018): they are kept, never deleted.",
  "explorador.pagina": "{desde}–{hasta} of {total}",
  "explorador.sin_filas": "no rows",
  "explorador.resumen": "{n} wells; {conPm} with IP90 per metre {cita}. Sorted by <code>{col}</code>, {sentido}; nulls go last.",
  "explorador.orden.desc": "descending",
  "explorador.orden.asc": "ascending",

  // --- type curves
  "curvas.title": "Type curves · Vaca Muerta abierta",
  "curvas.desc": "P10/P50/P90 type curves by vintage, formation, fluid window and operator, as rate per producing day and per metre of lateral, with the well count of every month.",
  "curvas.h1": "Type curves",
  "curvas.lead": "Month by month since first production, the distribution of the rate of every well in the group: P50 with a P10–P90 band (oilfield convention: P10 is the high case). Table <code>curvas_tipo</code>; nothing is published with fewer than 5 wells (ADR-017).",
  "curvas.nota": "<b>Rates are per producing day</b> (<code>volume / tef</code>, where <code>tef</code> is the days on production in the month), not per calendar day: a month with downtime gives the rate of the days the well produced. They are higher than a calendar-day rate by the downtime factor (ADR-016).",
  "curvas.nivel": "Level",
  "curvas.nivel.cf": "vintage × formation",
  "curvas.nivel.cfv": "vintage × formation × fluid window",
  "curvas.nivel.cfo": "vintage × formation × operator",
  "curvas.cohortes": "Vintages",
  "curvas.tasa": "Rate",
  "curvas.outliers": "include outliers (ADR-018)",
  "curvas.banda": "P10–P90 band",
  "curvas.log": "log axis",
  "curvas.leyenda": "Top: P50 (line) and P10–P90 (band) of the chosen rate. Bottom: <code>n_pozos</code>, the well count per month (wells with producing days that month; shut-in wells do not count). Up to month 60 (ADR-023). To project a campaign from these curves: <a href=\"simulador.html\">simulator</a>.",
  "curvas.pie": "Definitions: <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/indicadores.md\">docs/indicadores.md</a> (section <code>curvas_tipo</code>). Decisions: ADR-015 to ADR-020, ADR-023.",
  "curvas.tooltip": "<b>month {m}</b> since first production",
  "curvas.eje.x": "months since first production",
  "curvas.quien.ventana": "{v} window",
  "curvas.resumen": "{quien} — {n} vintages with publishable data for <code>{tasa}</code> {citas}; <code>incluye_outliers = {inc}</code> {citaInc}. Rates per producing day (ADR-016).",
  "curvas.th.cohorte": "vintage",
  "curvas.th.mes": "month {m}",
  "curvas.sin_mes": "the group has not reached this month yet",
  "curvas.n_bajo": "n = {n} < 5: not published (ADR-017)",
  "curvas.sin_grupos": "No publishable groups for this selection.",

  // --- map
  "mapa.title": "Map · Vaca Muerta abierta",
  "mapa.desc": "Map of the unconventional wells of the Neuquén Basin, coloured by IP90 per metre of lateral, operator, formation or fluid window.",
  "mapa.h1": "Well map",
  "mapa.lead": "Coordinates from the well register (<code>pozos.longitud</code>, <code>pozos.latitud</code>, validated in the well master). One dot per physical well. Wells without IP90 per metre are drawn grey when colouring by that value: they are there, with no data and with the reason.",
  "mapa.colorear": "Colour by",
  "mapa.color.eq": "IP90 oil equivalent per metre",
  "mapa.color.pet": "IP90 oil per metre",
  "mapa.color.gas": "IP90 gas per metre",
  "mapa.color.ventana": "Fluid window",
  "mapa.alcance": "in scope only",
  "mapa.pie": "Base map: © <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors. Coordinate rules: <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/maestro.md\">docs/maestro.md</a>.",
  "mapa.popup.pie": "coordinates {lon} {lat}; values {val}",
  "mapa.escala": "scale clipped at the P5–P95 of the filtered wells",
  "mapa.resumen": "{n} wells drawn {lon} {lat}; {sin} wells of the well master have no coordinates (flag <code>sin_coordenadas</code>).",

  // --- method and sources
  "metodo.title": "Method and sources · Vaca Muerta abierta",
  "metodo.desc": "Where every number comes from: public datasets of Argentina's Secretaría de Energía with date and hash, published tables, calculation rules, decisions and licences.",
  "metodo.h1": "Method and sources",
  "metodo.lead": "Everything on this site comes from the tables published by the repository's pipeline, which in turn come from the public datasets of Argentina's Secretaría de Energía. The site reads pre-aggregated JSON files that copy values from those tables, with the table and column name next to every number. One page computes in the browser: the <a href=\"simulador.html\">campaign simulator</a>, which samples wells from the published type curves and values them with the <code>precios</code> (prices) table; every result says so.",
  "metodo.h2.fuentes": "Sources (dated download, with hash)",
  "metodo.fuentes.p": "Portal <a href=\"https://datos.energia.gob.ar\">datos.energia.gob.ar</a>, licence <b>CC-BY 4.0</b>, Secretaría de Energía de la Nación Argentina. Download date and manifest of the run that generated this site:",
  "metodo.th.archivo": "file",
  "metodo.fuentes.detalle": "Details of every dataset (URL, grain, units, publication lag): <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/fuentes.md\">docs/fuentes.md</a>. Prices (crude by province, gas by basin) are two more datasets of the same portal: <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/precios.md\">docs/precios.md</a> (in Spanish).",
  "metodo.h2.tablas": "Published tables",
  "metodo.th.tabla": "table",
  "metodo.th.filas": "rows",
  "metodo.th.columnas": "columns",
  "metodo.th.que": "what it is",
  "metodo.th.def": "column definitions",
  "metodo.que.pozos": "well master: one row per physical well, aliases, operator and formation normalised, coordinates, lateral length, dates",
  "metodo.que.indicadores": "one row per well: IP30/90/180 in producing days, cumulatives, per-metre values, GOR, water cut, fluid window, outliers, flags, lineage",
  "metodo.que.curvas_tipo": "one row per level × group × incluye_outliers × month: P10/P50/P90/mean of the rate per producing day, n_pozos, publicable",
  "metodo.que.precios": "public monthly prices: crude in USD/m³ by province (royalties report) and gas in USD/MMBTU by basin, segment and contract, converted to the observatory's volume units",
  "metodo.tablas.p": "They are rebuilt with <code>python pipeline.py download · master · indicadores · curvas · site</code>; the tables are not versioned, they are regenerated (ADR-005, ADR-014). This site is rebuilt on the 5th of every month by GitHub Actions (ADR-024).",
  "metodo.meta": "Downloaded {descarga} (manifest generated {manifiesto}); well master and tables published in data/publicado/{maestro}/; site JSON generated {generado} ({utc}).",
  "metodo.error": "meta.json could not be loaded: {mensaje}",
  "metodo.h2.reglas": "Rules you need to know to read the numbers",
  "metodo.regla.pozo": "<b>Physical well = normalised well name (sigla)</b>; <code>idpozo</code> is a well × formation (ADR-003). The indicators add up the idpozo of a well (ADR-015).",
  "metodo.regla.tef": "<b>Rates per producing day</b> (<code>tef</code>, days on production), not per calendar day; IP30/90/180 are windows of producing days, with the month where the window closes prorated (ADR-016).",
  "metodo.regla.metro": "<b>Per-metre values only with a known lateral of 500 m or more</b> (ADR-010, ADR-019). If the source says the lateral is 0, the value is null with a reason, never 0.",
  "metodo.regla.n": "<b>At least 5 wells</b> to publish a percentile; P10 is the high case (ADR-017).",
  "metodo.regla.outliers": "<b>Outliers are flagged, not deleted</b>: robust z-score on log10(IP90/m) by formation, |z| &gt; 3.5; the curves are published with and without them (ADR-018).",
  "metodo.regla.ventana": "<b>Fluid window</b> derived from the well's own GOR (oil &lt; 180 m³/m³, volatile oil / condensate 180–1,800, gas ≥ 1,800); it classifies the data, not the reservoir (ADR-020).",
  "metodo.regla.operadora": "<b>Operator</b> = the one of the last production month, with versioned aliases; asset sales are not merged (ADR-012).",
  "metodo.regla.falta": "<b>What is missing is stated</b>: every null carries a flag with the reason (<code>flags</code>), and the explorer shows it.",
  "metodo.regla.simulador": "<b>The simulator is not a forecast</b>: it samples the well-to-well dispersion of a published type curve, extrapolates with a hyperbolic fit beyond the last published month and returns <b>gross</b> revenue, with no costs (ADR-031, ADR-035, ADR-036).",
  "metodo.h2.docs": "Documentation and reports",
  "metodo.doc.decisiones": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/decisiones.md\">docs/decisiones.md</a> — decisions (ADR-001 onwards)",
  "metodo.doc.maestro": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/maestro.md\">docs/maestro.md</a> — every column of the well master and every flag",
  "metodo.doc.indicadores": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/indicadores.md\">docs/indicadores.md</a> — every column of <code>indicadores</code> and <code>curvas_tipo</code>: formula, units, rule",
  "metodo.doc.fuentes": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/fuentes.md\">docs/fuentes.md</a> — every dataset: URL, licence, grain, size",
  "metodo.doc.simulacion": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/simulacion.md\">docs/simulacion.md</a> · <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/precios.md\">docs/precios.md</a> — decline fits, campaign Monte Carlo, public prices and valuation",
  "metodo.doc.esquemas": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/tree/main/docs/esquemas\">docs/esquemas/</a> — the real schema of every downloaded file",
  "metodo.doc.informes": "<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/tree/main/informes\">informes/</a> — dated reports: data quality (F0), well master (F1), indicators (F2), diff between downloads",
  "metodo.docs.idioma": "In the repository, the <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta#readme\">README</a>, the decisions (ADR), the well master, the indicators and the sources are in English; simulation and prices are in Spanish.",
  "metodo.h2.licencias": "Licences",
  "metodo.licencias.p": "Code: <b>MIT</b> (<a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/LICENSE\">LICENSE</a>). Data: <b>CC-BY 4.0</b>, Secretaría de Energía de la Nación Argentina; when reusing what you see here, cite the original source and the download date. Base map: © OpenStreetMap contributors (ODbL).",

  // --- campaign simulator
  "sim.title": "Campaign simulator · Vaca Muerta abierta",
  "sim.desc": "Monte Carlo of a campaign of new wells from the public P10/P50/P90 type curves of Vaca Muerta: aggregated rate, cumulative production, gross revenue and NPV with a band, in your browser.",
  "sim.h1": "Campaign simulator",
  "sim.lead": "How much a campaign of new wells would produce, and what it would gross, if every well behaved like one of the wells in the group you choose. Your browser draws the campaigns from the published P10/P50/P90 type curve (table <code>curvas_tipo</code>) and values them with the public prices (table <code>precios</code>). Everything runs on your machine: nothing is sent anywhere.",
  "sim.limites.titulo": "What it is and what it is not",
  "sim.limites.p10": "<b>P10 is the high case</b> (oilfield convention): one in ten of the campaigns drawn ends above it; P90 is the low case.",
  "sim.limites.tef": "<b>Rates are per producing day</b>, not per calendar day (ADR-016). The calendar comes in through the uptime factor.",
  "sim.limites.sin": "<b>No interference between wells, no facility constraints, no costs.</b> Revenue is <b>gross</b> (volume × price) and the NPV is the NPV of gross revenue: it is not profit and not an economic evaluation (ADR-035).",
  "sim.limites.banda": "<b>The band is only the well-to-well dispersion that the published type curve shows.</b> It carries no price, geological or execution uncertainty.",
  "sim.limites.extrapolacion": "<b>Beyond the last published month the curve is a hyperbolic extrapolation</b> of each quantile, with a terminal decline of 6 % per year (ADR-031, ADR-036). The cards say how many months that is, and the chart marks where they start.",
  "sim.limites.grupo": "<b>It is a statistical group of public wells</b>, not a forecast of any operator's plan and not a reservoir simulation.",
  "sim.c.ventana": "Fluid window",
  "sim.c.cohorte": "Reference vintage",
  "sim.c.pozos": "Wells",
  "sim.c.ritmo": "Wells per month",
  "sim.c.rama": "Lateral length (m)",
  "sim.c.rama.ph": "the group's own",
  "sim.c.meses": "Horizon (months)",
  "sim.c.uptime": "Uptime (%)",
  "sim.c.precio_pet": "Oil (USD/bbl)",
  "sim.c.precio_gas": "Gas (USD/MMBTU)",
  "sim.c.tasa": "Discount rate (% per year)",
  "sim.c.regalia": "Royalty (%)",
  "sim.c.fluido": "Fluid shown in the charts",
  "sim.fluido.petroleo": "oil",
  "sim.fluido.gas": "gas",
  "sim.c.unidades": "Units",
  "sim.unidades.metrico": "m³ (as in the source)",
  "sim.unidades.campo": "bbl · MMscf (converted)",
  "sim.c.nsim": "Simulations",
  "sim.c.semilla": "Seed",
  "sim.c.correr": "Run",
  "sim.c.precios": "Public prices",
  "sim.leyenda": "In every chart: P50 (line) and P10–P90 (band) across the campaigns drawn, by campaign month (month 0 = first well on production). The dashed vertical line marks the first month in which some well is on the extrapolated part of the curve.",
  "sim.h2.notas": "What you need to know about this run",
  "sim.h2.como": "How it is computed",
  "sim.como.1": "Every simulated well draws a position in the group (a uniform percentile) and keeps it for life, with a monthly noise of 8 percentile points: a good well stays a good well.",
  "sim.como.2": "Its rate each month is read from the published P90/P50/P10 of that month on production, by log-linear interpolation. With a lateral length and a per-metre curve, the per-metre rate is sampled and multiplied by the lateral. Oil and gas of a well share the same position.",
  "sim.como.3": "Wells come on at <i>wells per month</i> from month 0. Monthly volume = rate × 30.44 days × uptime.",
  "sim.como.4": "Gross revenue = oil × price + gas × price, less the royalty if one is given. NPV = Σ revenue × (1 + rate)<sup>−month/12</sup>, month 0 undiscounted.",
  "sim.como.5": "This is repeated for every simulation; for each month the P10, P50 and P90 across simulations are reported. The seed makes the result reproducible.",
  "sim.pie": "Method: <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/simulacion.md\">docs/simulacion.md</a> · <a href=\"https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/docs/precios.md\">docs/precios.md</a> (in Spanish). Decisions: ADR-017, ADR-031, ADR-034, ADR-035, ADR-036. The same Monte Carlo exists in Python (<code>vma.simulacion.campania</code>) and as the MCP tool <code>simular_campania</code>; a test compares the two.",
  "ventana.petroleo": "oil",
  "ventana.volatil_condensado": "volatile oil / condensate",
  "ventana.gas": "gas",
  "u.usd_millones": "USD {v} million",
  "u.mil_m3": "thousand m³",
  "u.mil_m3_d": "thousand m³/d",
  "u.millones_m3": "million m³",
  "u.mil_m3_eq": "thousand m³ of oil equivalent",
  "u.musd_mes": "USD million / month",
  "u.musd": "USD million",
  "sim.factor.petroleo": "conversion: 1 m³ = {f} bbl",
  "sim.factor.gas": "conversion: 1 m³ = {f} ft³",
  "sim.cohorte.opcion": "{c} · {n} wells · {m} months published",
  "sim.err.pozos": "Wells: a whole number between 1 and {max}.",
  "sim.err.ritmo": "Wells per month: a whole number of 1 or more (empty = all in month 0).",
  "sim.err.meses": "Horizon: a whole number between 1 and {max} months.",
  "sim.err.uptime": "Uptime: between 50 and 100 %.",
  "sim.err.rama": "Lateral length: a number of metres above 0, or empty.",
  "sim.err.precio": "Prices: 0 or more.",
  "sim.err.tasa": "Discount rate: between 0 and 100 % per year.",
  "sim.err.regalia": "Royalty: between 0 and 99 %.",
  "sim.err.nsim": "Simulations: a whole number between 10 and {max}.",
  "sim.err.semilla": "Seed: a whole number of 0 or more.",
  "sim.err.grupo": "There is no publishable curve for that combination.",
  "sim.estado.corriendo": "Simulating… {hechas} / {total}",
  "sim.estado.listo": "Done: {n} simulations of {pozos} wells in {ms} ms · seed {semilla} (the same seed repeats the result).",
  "sim.sin_precios": "This snapshot carries no public prices: enter your own to see dollars.",
  "sim.g.extrapolado": "extrapolated →",
  "sim.g.pozos": "wells on line",
  "sim.g.mes": "campaign month {m}",
  "sim.g.con_extrapolacion": "includes extrapolated months",
  "sim.g.eje_x": "campaign month",
  "sim.g.t.tasa": "Aggregated {fluido} rate ({u}), per producing day, and wells on line",
  "sim.g.t.acum": "Cumulative {fluido} ({u})",
  "sim.g.t.ingreso": "Gross revenue per month (USD million), oil + gas",
  "sim.g.t.ingreso_acum": "Cumulative gross revenue (USD million)",
  "sim.t.rango": "P10 {a} · P90 {b} {u}",
  "sim.t.igual": "= {v} {u}",
  "sim.t.acum": "cumulative {fluido} at {meses} months · P50",
  "sim.t.por_pozo": "per well to the horizon · P50",
  "sim.t.por_pozo.nota": "EUR to the {meses}-month horizon: the volume the curve implies, not a reserve",
  "sim.t.pico": "peak campaign rate · P50",
  "sim.t.pico.nota": "in campaign month {m}, per producing day",
  "sim.t.ingreso": "cumulative gross revenue · P50",
  "sim.t.ingreso.neto": "gross revenue less a {r} % royalty · P50",
  "sim.t.ingreso.nota": "volume × price; no capex, opex, transport or taxes",
  "sim.t.van": "NPV of gross revenue at {tasa} % per year · P50",
  "sim.t.van.nota": "not profit: there are no costs in this number",
  "sim.t.meses": "months published + extrapolated",
  "sim.t.meses.nota": "the published curve is used up to month {u} on production; the rest is a hyperbolic extrapolation",
  "sim.t.boe": "oil + gas at {meses} months · P50",
  "sim.t.boe.nota": "converted with the Secretaría's factor: 1,000 m³ of gas = 1 m³ of oil ({mcf} Mcf per boe, not the usual 6)",
  "sim.resumen": "{formacion} · <code>{ventana}</code> window · vintage {cohorte}: {n} wells in the group {citaN}. Curve <code>{col}</code> {citas}, <code>incluye_outliers = false</code> {citaInc}. Campaign: {pozos} wells, {ritmo} per month, {meses} months, {uptime} % uptime.",
  "sim.n.sin_curva": "The group publishes no {fluido} curve with at least {min} months: that fluid is left out of the simulation and of the revenue.",
  "sim.n.meses": "{fluido}: curve <code>{col}</code> {cita}, {pub} published months inside the horizon and {ext} extrapolated.",
  "sim.n.por_metro": "Per-metre rate × a {rama} m lateral; the per-metre curve comes from the {n} wells of the group with a known lateral of 500 m or more {cita}.",
  "sim.n.rama_ignorada": "The lateral length you gave is not used: the group publishes no per-metre curve for this fluid, so the absolute curve is used.",
  "sim.n.absoluta": "No lateral length given: absolute curve, that is, wells with the laterals the group actually had.",
  "sim.n.ancla": "{fluido}: the extrapolated tail is spliced at month {u}, the last one with at least half of the group's wells ({n} wells) {cita}; later published months are not used.",
  "sim.n.ancla_debil": "<b>With so few wells that level is noisy, and the whole extrapolation follows it</b>: try an older vintage to compare.",
  "sim.n.base_corta": "<b>Short basis</b> ({fluido}): the curve has {n} published months; everything from there to month {meses} rests on very little data.",
  "sim.n.acotados": "{fluido}: in {n} of the extrapolated months the P10 or P90 tail met the P50 tail and follows it (ADR-036). The band narrows there by construction, not because the data say so.",
  "sim.n.sin_extension": "{fluido}: {n} months of the horizon have no curve (unpublished months, or a tail that could not be fitted); in those months on production a well adds nothing.",
  "sim.n.sin_entrar": "{n} wells do not come on production inside the horizon at this pace.",
  "sim.n.precio_pet": "Oil price: {bbl} USD/bbl = {m3} USD/m³ {cita}, average realised sale price in {region}, {mes}{prov}. Held constant over the whole horizon.",
  "sim.n.provisorio": " (provisional)",
  "sim.n.precio_pet_usuario": "Oil price: {bbl} USD/bbl = {m3} USD/m³, typed in by you: it is not public data. Held constant over the whole horizon.",
  "sim.n.gas_conv": "USD/MMBTU becomes USD per thousand m³ at 9,300 kcal/m³ ({f} MMBTU per thousand m³); richer gas is worth more per m³ (ADR-034).",
  "sim.n.precio_gas": "Gas price: {mmbtu} USD/MMBTU = {km3} USD per thousand m³ {cita}, {region} basin, weighted average of all segments, {mes}.",
  "sim.n.precio_gas_usuario": "Gas price: {mmbtu} USD/MMBTU = {km3} USD per thousand m³, typed in by you: it is not public data.",
  "sim.n.regalia": "A {r} % royalty is deducted from gross revenue. Argentina's statutory base rate is 12 %; effective rates vary by province and concession.",
  "sim.n.fuente_precios": "Prices: crude royalties report (issued {f}) and Res. 1/2018 gas prices, Secretaría de Energía, CC-BY 4.0; downloaded {d}.",

  // --- column labels (keys are the tables' column names) and their units
  "etq.sigla": "Well name (sigla)",
  "etq.operadora": "Operator",
  "etq.formacion": "Formation",
  "etq.area": "Block",
  "etq.cohorte": "Vintage",
  "etq.cohorte.u": "year of first production",
  "etq.ventana": "Fluid window",
  "etq.ventana.u": "from the well's own GOR",
  "etq.rama_m": "Lateral length",
  "etq.rama_m.u": "m",
  "etq.etapas": "Stages",
  "etq.etapas_por_100m": "Stages / 100 m",
  "etq.arena_tn_por_m": "Proppant",
  "etq.arena_tn_por_m.u": "t/m",
  "etq.agua_fractura_m3_por_m": "Frac water",
  "etq.agua_fractura_m3_por_m.u": "m³/m",
  "etq.dias_efectivos_total": "Producing days",
  "etq.dias_efectivos_total.u": "d",
  "etq.ip90_petroleo_m3_d": "IP90 oil",
  "etq.ip90_petroleo_m3_d.u": "m³/d",
  "etq.ip90_gas_mil_m3_d": "IP90 gas",
  "etq.ip90_gas_mil_m3_d.u": "thousand m³/d",
  "etq.ip90_equivalente_m3_d": "IP90 oil equivalent",
  "etq.ip90_equivalente_m3_d.u": "m³/d",
  "etq.ip90_petroleo_m3_d_por_m": "IP90 oil / m",
  "etq.ip90_petroleo_m3_d_por_m.u": "m³/d per m",
  "etq.ip90_gas_mil_m3_d_por_m": "IP90 gas / m",
  "etq.ip90_gas_mil_m3_d_por_m.u": "thousand m³/d per m",
  "etq.ip90_equivalente_m3_d_por_m": "IP90 oil eq. / m",
  "etq.ip90_equivalente_m3_d_por_m.u": "m³/d per m",
  "etq.acum12_petroleo_m3_por_m": "12-month cum. oil / m",
  "etq.acum12_petroleo_m3_por_m.u": "m³/m",
  "etq.acum12_gas_mil_m3_por_m": "12-month cum. gas / m",
  "etq.acum12_gas_mil_m3_por_m.u": "thousand m³/m",
  "etq.acum12_equivalente_m3_por_m": "12-month cum. oil eq. / m",
  "etq.acum12_equivalente_m3_por_m.u": "m³/m",
  "etq.gor12_m3_m3": "GOR, 12 months",
  "etq.gor12_m3_m3.u": "m³/m³",
  "etq.corte_agua12": "Water cut, 12 months",
  "etq.corte_agua12.u": "fraction",
  "etq.outlier_ip90_m": "IP90/m outlier",
  "etq.outlier_ip90_m.u": "ADR-018",
  "etq.estado": "Status",
  "etq.tipo_pozo": "Well type",
  "etq.primera_produccion": "First production",
  "etq.primera_produccion.u": "month",
  "tasa.equivalente_m3_d_por_m": "Oil equivalent per metre",
  "tasa.equivalente_m3_d_por_m.u": "m³ oe/d per m of lateral",
  "tasa.petroleo_m3_d_por_m": "Oil per metre",
  "tasa.petroleo_m3_d_por_m.u": "m³/d per m of lateral",
  "tasa.gas_mil_m3_d_por_m": "Gas per metre",
  "tasa.gas_mil_m3_d_por_m.u": "thousand m³/d per m of lateral",
  "tasa.equivalente_m3_d": "Oil equivalent",
  "tasa.equivalente_m3_d.u": "m³ oe/d",
  "tasa.petroleo_m3_d": "Oil",
  "tasa.petroleo_m3_d.u": "m³/d",
  "tasa.gas_mil_m3_d": "Gas",
  "tasa.gas_mil_m3_d.u": "thousand m³/d",

  // --- why a value is null (keys are the flags of the tables)
  "flag.fuera_alcance": "out of scope (not Neuquén Basin unconventional, ADR-002)",
  "flag.sin_produccion": "no production record (a well with a frac record only)",
  "flag.nunca_produjo": "there are records, but oil and gas are always 0",
  "flag.sin_rama_sin_fractura": "no frac record: there is no lateral length",
  "flag.sin_rama_faltante": "horizontal well (≥ 10 stages) with a lateral of 0 in the source: length not reported",
  "flag.sin_rama_cero": "lateral of 0 in the source, with few stages",
  "flag.sin_rama": "no lateral length, for another reason",
  "flag.rama_corta": "lateral under 500 m: not normalised per metre (ADR-019)",
  "flag.tef_cero_con_produccion": "a month with production and 0 producing days: the whole month was taken",
  "flag.tef_mayor_mes": "a month with more producing days than days in the month: capped",
  "flag.primer_mes_parcial": "first month with fewer than 15 producing days (for information)",
  "flag.produccion_suma_idpozo": "two or more idpozo of the well added up in a month",
  "flag.volumen_negativo": "a negative monthly volume in the source (a correction)",
  "flag.ip30_dias_insuficientes": "fewer than 30 producing days: IP30 is null",
  "flag.ip90_dias_insuficientes": "fewer than 90 producing days: IP90 is null",
  "flag.ip180_dias_insuficientes": "fewer than 180 producing days: IP180 is null",
  "flag.acum6_historia_corta": "the source does not cover 6 months yet",
  "flag.acum12_historia_corta": "the source does not cover 12 months yet",
  "flag.acum24_historia_corta": "the source does not cover 24 months yet",
  "flag.acum6_meses_faltantes": "months with no record inside the 6-month window, counted as 0",
  "flag.acum12_meses_faltantes": "months with no record inside the 12-month window, counted as 0",
  "flag.acum24_meses_faltantes": "months with no record inside the 24-month window, counted as 0",
  "flag.gor6_sin_petroleo": "no oil in 6 months: GOR undefined (gas well)",
  "flag.gor12_sin_petroleo": "no oil in 12 months: GOR undefined (gas well)",
  "flag.corte_agua6_sin_liquido": "neither oil nor water in 6 months",
  "flag.corte_agua12_sin_liquido": "neither oil nor water in 12 months",
  "flag.ventana_provisoria": "fluid window classified with gor6 or the whole history, not with gor12",
  "flag.outlier_ip90_m_alto": "high IP90/m outlier within its formation (ADR-018)",
  "flag.outlier_ip90_m_bajo": "low IP90/m outlier within its formation (ADR-018)",
  "flag.outlier_no_evaluado": "not screened for outliers (no IP90/m, or a small formation)",
};

// --- t(): Spanish in the call, English from the dictionary ---------------------------------------------------------------

function interpolar(texto, vars) {
  return vars ? texto.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : texto;
}

/** t("key", "texto en español con {variable}", { variable }) -> the string in the page language. */
export function t(clave, es, vars) {
  const texto = LANG === "en" && EN[clave] !== undefined ? EN[clave] : es;
  return interpolar(texto ?? clave, vars);
}

/** An internal link that keeps the language when it was chosen in the URL (so a shared English link stays English). */
export function enlace(href) {
  if (!EXPLICITO || /^(https?:|mailto:|#)/.test(href) || /[?&]lang=/.test(href)) return href;
  const [sinHash, hash] = href.split("#");
  return `${sinHash}${sinHash.includes("?") ? "&" : "?"}lang=${LANG}${hash ? `#${hash}` : ""}`;
}

// --- static text: swap every data-i18n element, wire the ES | EN switch, keep ?lang= on internal links -------------------

export function aplicar(doc = globalThis.document) {
  if (!doc) return;
  doc.documentElement.lang = LANG;
  if (LANG === "en") {
    for (const el of doc.querySelectorAll("[data-i18n]")) {
      const texto = EN[el.dataset.i18n];
      if (texto === undefined) console.warn(`i18n: no English for "${el.dataset.i18n}"`);
      else el.innerHTML = texto;
    }
    for (const el of doc.querySelectorAll("[data-i18n-attr]")) {
      for (const par of el.dataset.i18nAttr.split(";")) {
        const [attr, clave] = par.split(":").map((x) => x.trim());
        if (EN[clave] !== undefined) el.setAttribute(attr, EN[clave]);
        else console.warn(`i18n: no English for "${clave}"`);
      }
    }
  }
  const aqui = new URL(globalThis.location.href);
  for (const a of doc.querySelectorAll("a[data-lang]")) {
    const u = new URL(aqui);
    u.searchParams.set("lang", a.dataset.lang);
    a.href = u.toString();
    a.classList.toggle("activa", a.dataset.lang === LANG);
    if (a.dataset.lang === LANG) a.setAttribute("aria-current", "true");
    a.addEventListener("click", () => {
      try {
        globalThis.localStorage.setItem("vma-lang", a.dataset.lang);
      } catch { /* storage blocked: the URL still carries the choice */ }
    });
  }
  for (const a of doc.querySelectorAll("a[href]")) {
    if (a.dataset.lang) continue;
    const href = a.getAttribute("href");
    if (/^[\w-]+\.html([?#]|$)/.test(href)) a.setAttribute("href", enlace(href));
  }
  doc.documentElement.classList.remove("traduciendo");
}

if (globalThis.document) aplicar();
