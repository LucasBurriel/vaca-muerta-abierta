// The campaign simulator page (ADR-036). The Monte Carlo itself is in montecarlo.js (DOM-free, tested under Node
// against the Python simulator); this file reads the controls, runs it in chunks so the page stays responsive,
// and draws cards and charts. Every number shown carries the table and column it came from.

import { cabecera, cargar, cita, distintos, entero, esc, num } from "./comun.js";
import { LOCALE, t } from "./i18n.js";
import { MESES_MAX, N_POZOS_MAX, N_SIM_MAX, iniciar } from "./montecarlo.js";

const $ = (id) => document.getElementById(id);
const COL = { petroleo: "petroleo_m3_d", gas: "gas_mil_m3_d" };
const COLOR = { petroleo: "#b5451b", gas: "#2b6cb0", usd: "#2f7a4a", pozos: "#8a8f98" };
const FLUIDOS = { petroleo: t("sim.fluido.petroleo", "petróleo"), gas: t("sim.fluido.gas", "gas") };
const VENTANAS = {
  petroleo: t("ventana.petroleo", "petróleo"),
  volatil_condensado: t("ventana.volatil_condensado", "volátil / condensado"),
  gas: t("ventana.gas", "gas"),
};
const ANCLA_FIRME = 20; // wells in the splice month below which the splice level is called noisy
const MESES_MIN_BASE = 24; // a cohort needs this many published months to be the default (as in the Python tool)

let D = null; // simulador.json
let R = null; // last result
let C = null; // context of the last result: parameters, group, curves used
let corrida = 0; // token: a newer run cancels the one in flight
const graficos = {};

const fmt3 = new Intl.NumberFormat(LOCALE, { maximumSignificantDigits: 3 });
const fmtEje = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });
const pct = (v) => fmtEje.format(v * 100); // 0.1 -> "10", 0.925 -> "92.5"
const sig3 = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : fmt3.format(v));
const usdM = (v) => t("u.usd_millones", "USD {v} millones", { v: sig3(v / 1e6) });

// --- units: the source's metric ones, or field units as a declared conversion ------------------------------------------

function unidades(fluido, sistema) {
  if (fluido === "petroleo") {
    return sistema === "campo"
      ? { fT: D.bbl_por_m3, uT: "bbl/d", fA: D.bbl_por_m3 / 1e6, uA: "MMbbl" }
      : { fT: 1, uT: "m³/d", fA: 1e-3, uA: t("u.mil_m3", "mil m³") };
  }
  return sistema === "campo"
    ? { fT: D.ft3_por_m3 / 1e3, uT: "MMscf/d", fA: D.ft3_por_m3 / 1e6, uA: "Bcf" }
    : { fT: 1, uT: t("u.mil_m3_d", "mil m³/d"), fA: 1e-3, uA: t("u.millones_m3", "millones de m³") };
}

function factorTexto(fluido) {
  return fluido === "petroleo"
    ? t("sim.factor.petroleo", "conversión: 1 m³ = {f} bbl", { f: num(D.bbl_por_m3, 4) })
    : t("sim.factor.gas", "conversión: 1 m³ = {f} ft³", { f: num(D.ft3_por_m3, 2) });
}

// --- controls ----------------------------------------------------------------------------------------------------------

function grupos(fm, ve) {
  return D.grupos.filter((g) => g.formacion === fm && (ve === undefined || g.ventana === ve));
}

function fluidoPorDefecto(ve) {
  return ve === "gas" ? "gas" : "petroleo";
}

function opciones(sel, valores, etiqueta = (v) => v) {
  const prev = sel.value;
  sel.innerHTML = valores.map((v) => `<option value="${esc(v)}">${esc(etiqueta(v))}</option>`).join("");
  if (valores.map(String).includes(prev)) sel.value = prev;
  return sel.value === prev && prev !== "";
}

function llenarVentanas() {
  const fm = $("s-formacion").value;
  const orden = ["petroleo", "volatil_condensado", "gas"];
  const vs = distintos(grupos(fm).map((g) => g.ventana)).sort((a, b) => orden.indexOf(a) - orden.indexOf(b));
  const conservada = opciones($("s-ventana"), vs, (v) => (VENTANAS[v] ? `${VENTANAS[v]} (${v})` : v));
  if (!conservada) $("s-ventana").value = vs.includes("petroleo") ? "petroleo" : vs[0];
  llenarCohortes(true);
}

function llenarCohortes(cambioVentana) {
  const fm = $("s-formacion").value, ve = $("s-ventana").value;
  const gs = grupos(fm, ve).sort((a, b) => a.cohorte - b.cohorte);
  const fl = fluidoPorDefecto(ve);
  const pub = (g) => (g.curvas[COL[fl]] ?? Object.values(g.curvas)[0]).publicados;
  const conservada = opciones(
    $("s-cohorte"),
    gs.map((g) => g.cohorte),
    (c) => {
      const g = gs.find((x) => x.cohorte === Number(c));
      return t("sim.cohorte.opcion", "{c} · {n} pozos · {m} meses publicados", { c, n: entero(g.n_pozos), m: pub(g) });
    },
  );
  if (!conservada && gs.length) {
    const firmes = gs.filter((g) => pub(g) >= MESES_MIN_BASE);
    $("s-cohorte").value = String((firmes.length ? firmes : gs).at(-1).cohorte);
  }
  if (cambioVentana) $("s-fluido").value = fl;
}

function preciosPublicos() {
  const p = D.precios;
  $("s-precio-pet").value = p?.petroleo ? p.petroleo.usd_bbl.toFixed(2) : "";
  $("s-precio-gas").value = p?.gas ? p.gas.usd_mmbtu.toFixed(2) : "";
}

function leer() {
  const n = (id) => {
    const v = $(id).value.trim();
    return v === "" ? null : Number(v);
  };
  const p = {
    formacion: $("s-formacion").value, ventana: $("s-ventana").value, cohorte: Number($("s-cohorte").value),
    nPozos: n("s-pozos"), ritmo: n("s-ritmo"), rama: n("s-rama"), meses: n("s-meses"),
    uptime: (n("s-uptime") ?? NaN) / 100, usdBbl: n("s-precio-pet"), usdMmbtu: n("s-precio-gas"),
    tasaAnual: (n("s-tasa") ?? NaN) / 100, regalia: (n("s-regalia") ?? 0) / 100, nSim: n("s-nsim"), semilla: n("s-semilla") ?? 0,
  };
  const errores = [];
  const entre = (v, a, b) => Number.isFinite(v) && v >= a && v <= b;
  if (!Number.isInteger(p.nPozos) || !entre(p.nPozos, 1, N_POZOS_MAX)) errores.push(t("sim.err.pozos", "Pozos: un entero entre 1 y {max}.", { max: N_POZOS_MAX }));
  if (p.ritmo !== null && (!Number.isInteger(p.ritmo) || p.ritmo < 1)) errores.push(t("sim.err.ritmo", "Pozos por mes: un entero de 1 o más (vacío = todos en el mes 0)."));
  if (!Number.isInteger(p.meses) || !entre(p.meses, 1, Math.min(MESES_MAX, D.meses))) errores.push(t("sim.err.meses", "Horizonte: un entero entre 1 y {max} meses.", { max: Math.min(MESES_MAX, D.meses) }));
  if (!entre(p.uptime, 0.5, 1)) errores.push(t("sim.err.uptime", "Uptime: entre 50 y 100 %."));
  if (p.rama !== null && !(p.rama > 0)) errores.push(t("sim.err.rama", "Rama: un número de metros mayor que 0, o vacío."));
  if ((p.usdBbl !== null && !(p.usdBbl >= 0)) || (p.usdMmbtu !== null && !(p.usdMmbtu >= 0))) errores.push(t("sim.err.precio", "Precios: 0 o más."));
  if (!entre(p.tasaAnual, 0, 1)) errores.push(t("sim.err.tasa", "Tasa de descuento: entre 0 y 100 % anual."));
  if (!entre(p.regalia, 0, 0.99)) errores.push(t("sim.err.regalia", "Regalía: entre 0 y 99 %."));
  if (!Number.isInteger(p.nSim) || !entre(p.nSim, 10, N_SIM_MAX)) errores.push(t("sim.err.nsim", "Simulaciones: un entero entre 10 y {max}.", { max: N_SIM_MAX }));
  if (!Number.isInteger(p.semilla) || p.semilla < 0) errores.push(t("sim.err.semilla", "Semilla: un entero de 0 o más."));
  return { p, errores };
}

function elegirCurva(g, fluido, rama) {
  const col = COL[fluido];
  const abs = g.curvas[col], pm = g.curvas[`${col}_por_m`];
  if (rama && pm) return { curva: pm, col: `${col}_por_m`, escala: rama, porMetro: true, ramaIgnorada: false };
  if (abs) return { curva: abs, col, escala: 1, porMetro: false, ramaIgnorada: Boolean(rama) };
  return null;
}

// --- run ---------------------------------------------------------------------------------------------------------------

function estado(html, error = false) {
  $("estado").innerHTML = error ? `<span class="error">${html}</span>` : html;
}

async function correr() {
  const id = ++corrida;
  const { p, errores } = leer();
  if (errores.length) {
    estado(errores.map(esc).join(" "), true);
    return;
  }
  const g = D.grupos.find((x) => x.formacion === p.formacion && x.ventana === p.ventana && x.cohorte === p.cohorte);
  if (!g) {
    estado(t("sim.err.grupo", "No hay curva publicable para esa combinación."), true);
    return;
  }
  const sel = { petroleo: elegirCurva(g, "petroleo", p.rama), gas: elegirCurva(g, "gas", p.rama) };
  const pub = D.precios ?? {};
  // a price left as prefilled is the public one, taken at full precision; an edited one is the reader's
  const publico = {
    petroleo: Boolean(pub.petroleo) && p.usdBbl !== null && p.usdBbl.toFixed(2) === pub.petroleo.usd_bbl.toFixed(2),
    gas: Boolean(pub.gas) && p.usdMmbtu !== null && p.usdMmbtu.toFixed(2) === pub.gas.usd_mmbtu.toFixed(2),
  };
  const precio = {
    petroleo: publico.petroleo ? pub.petroleo.usd_m3 : (p.usdBbl ?? 0) * D.bbl_por_m3,
    gas: publico.gas ? pub.gas.usd_mil_m3 : (p.usdMmbtu ?? 0) * D.mmbtu_por_mil_m3,
  };
  let sim;
  try {
    sim = iniciar({
      petroleo: sel.petroleo?.curva ?? null, gas: sel.gas?.curva ?? null,
      escalaPetroleo: sel.petroleo?.escala ?? 1, escalaGas: sel.gas?.escala ?? 1,
      nPozos: p.nPozos, meses: p.meses, ritmo: p.ritmo, nSim: p.nSim, semilla: p.semilla, uptime: p.uptime,
      jitter: D.jitter_percentil, diasMes: D.dias_mes,
      precioPetroleo: precio.petroleo, precioGas: precio.gas, tasaAnual: p.tasaAnual, regalia: p.regalia,
    });
  } catch (e) {
    estado(esc(e.message), true);
    return;
  }
  const t0 = performance.now();
  const lote = Math.max(1, Math.floor(150000 / (p.nPozos * p.meses))); // ~10-20 ms of work between yields
  $("s-correr").disabled = true;
  while (sim.hechas() < sim.total) {
    sim.correr(lote);
    estado(t("sim.estado.corriendo", "Simulando… {hechas} / {total}", { hechas: entero(sim.hechas()), total: entero(sim.total) }));
    await new Promise((r) => setTimeout(r));
    if (id !== corrida) return; // a newer run took over
  }
  R = sim.resultado();
  C = { p, g, sel, precio, publico, ms: performance.now() - t0 };
  $("s-correr").disabled = false;
  estado(
    t("sim.estado.listo", "Listo: {n} simulaciones de {pozos} pozos en {ms} ms · semilla {semilla} (la misma semilla repite el resultado).", {
      n: entero(p.nSim), pozos: entero(p.nPozos), ms: entero(Math.round(C.ms)), semilla: p.semilla,
    }),
  );
  dibujar();
}

let espera = null;
function correrPronto() {
  clearTimeout(espera);
  espera = setTimeout(correr, 300);
}

// --- draw --------------------------------------------------------------------------------------------------------------

function tarjeta(valor, titulo, detalle) {
  return `<div class="tarjeta"><div class="valor">${valor}</div><div class="titulo">${titulo}</div><div class="regla">${detalle}</div></div>`;
}

function mesesDe(curva, meses) {
  // published and extrapolated months of a curve inside the horizon, and months it could not be extended to
  const publicados = Math.min(meses, curva.ultimo_mes + 1);
  let sinCurva = 0;
  for (let k = 0; k < meses; k++) if (!(curva.p50[k] > 0)) sinCurva++;
  return { publicados, extrapolados: Math.max(0, meses - 1 - curva.ultimo_mes), sinCurva };
}

function serieBanda(b, factor, color, nombre) {
  // the P10-P90 band as one polygon under the P50 line (a custom series, as in curvas.js)
  const puntos = [...b.p10.map((v, i) => [i, v * factor]), ...b.p90.map((v, i) => [i, v * factor]).reverse()];
  return [
    {
      name: `${nombre} P10–P90`, type: "custom", silent: true, tooltip: { show: false }, z: 1, data: [0],
      renderItem: (params, api) => ({ type: "polygon", shape: { points: puntos.map((pt) => api.coord(pt)) }, style: { fill: color, opacity: 0.2 } }),
    },
    { name: `${nombre} P50`, type: "line", data: b.p50.map((v, i) => [i, v * factor]), showSymbol: false, lineStyle: { width: 2.5, color }, itemStyle: { color }, z: 3 },
  ];
}

function graficar(id, { banda, factor, unidad, color, nombre, mesExtra, pozos }) {
  const el = $(id);
  const oscuro = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  graficos[id] ??= echarts.init(el, oscuro ? "dark" : null);
  const meses = banda.p50.length;
  const series = serieBanda(banda, factor, color, nombre);
  if (mesExtra !== null && mesExtra < meses) {
    series[1].markLine = {
      silent: true, symbol: "none", lineStyle: { type: "dashed", color: COLOR.pozos },
      label: { formatter: t("sim.g.extrapolado", "extrapolado →"), position: "end", rotate: 0, align: "left", distance: 2, color: COLOR.pozos, fontSize: 11 },
      data: [{ xAxis: mesExtra }],
    };
  }
  // a custom series does not drive the axis extent: an invisible P10 line does, and keeps the ticks round
  series.push({
    name: "P10", type: "line", data: banda.p10.map((v, i) => [i, v * factor]), showSymbol: false, silent: true,
    lineStyle: { opacity: 0 }, itemStyle: { opacity: 0 }, tooltip: { show: false }, z: 0,
  });
  const ejes = [{ type: "value", name: unidad, nameTextStyle: { align: "left" }, min: 0, axisLabel: { formatter: (v) => fmtEje.format(v) } }];
  if (pozos) {
    ejes.push({ type: "value", name: t("sim.g.pozos", "pozos en línea"), nameTextStyle: { align: "right" }, min: 0, minInterval: 1, splitLine: { show: false } });
    series.push({
      name: t("sim.g.pozos", "pozos en línea"), type: "line", step: "end", yAxisIndex: 1, data: pozos.map((v, i) => [i, v]), showSymbol: false,
      lineStyle: { width: 1.2, type: "dotted", color: COLOR.pozos }, itemStyle: { color: COLOR.pozos }, z: 2,
    });
  }
  graficos[id].setOption(
    {
      backgroundColor: "transparent",
      animation: false,
      grid: { left: 8, right: pozos ? 8 : 16, top: 34, bottom: 34, containLabel: true },
      tooltip: {
        trigger: "axis",
        formatter: (ps) => {
          const m = ps.find((x) => Array.isArray(x.value))?.value[0];
          if (m === undefined) return "";
          const v = (x) => `${sig3(x * factor)} ${esc(unidad)}`;
          const lineas = [
            `<b>${t("sim.g.mes", "mes {m} de campaña", { m })}</b>`,
            `P10 ${v(banda.p10[m])}`, `<b>P50 ${v(banda.p50[m])}</b>`, `P90 ${v(banda.p90[m])}`,
          ];
          if (pozos) lineas.push(`${t("sim.g.pozos", "pozos en línea")}: ${pozos[m]}`);
          if (mesExtra !== null && m >= mesExtra) lineas.push(`<i>${t("sim.g.con_extrapolacion", "incluye meses extrapolados")}</i>`);
          return lineas.join("<br>");
        },
      },
      xAxis: { type: "value", name: t("sim.g.eje_x", "mes de campaña"), nameLocation: "middle", nameGap: 22, min: 0, max: meses - 1, minInterval: 1 },
      yAxis: ejes,
      series,
    },
    true,
  );
}

function dibujar() {
  if (!R) return;
  const { p, g, sel, precio, publico } = C;
  let fluido = $("s-fluido").value;
  if (!R.fluidos[fluido]) {
    fluido = Object.keys(R.fluidos)[0];
    $("s-fluido").value = fluido;
  }
  const sistema = $("s-unidades").value, otroSistema = sistema === "campo" ? "metrico" : "campo";
  const U = unidades(fluido, sistema), O = unidades(fluido, otroSistema);
  const F = R.fluidos[fluido], fin = F.final, s = sel[fluido];
  const nombre = FLUIDOS[fluido];
  const M = mesesDe(s.curva, p.meses);
  const citas3 = `${cita("curvas_tipo", `${s.col}_p50`)} ${cita("curvas_tipo", `${s.col}_p10`)} ${cita("curvas_tipo", `${s.col}_p90`)}`;
  const rango = (o, f, u) => t("sim.t.rango", "P10 {a} · P90 {b} {u}", { a: sig3(o.p10 * f), b: sig3(o.p90 * f), u });
  const tambien = (v) => `${t("sim.t.igual", "= {v} {u}", { v: sig3(v * O.fA), u: O.uA })} (${factorTexto(fluido)})`;

  // --- cards
  const tarjetas = [
    tarjeta(
      `${sig3(fin.acumulado.p50 * U.fA)} ${U.uA}`,
      t("sim.t.acum", "{fluido} acumulado a {meses} meses · P50", { fluido: nombre, meses: p.meses }),
      `${rango(fin.acumulado, U.fA, U.uA)}<br>${tambien(fin.acumulado.p50)}<br>${citas3}`,
    ),
    tarjeta(
      `${sig3(fin.por_pozo.p50 * U.fA)} ${U.uA}`,
      t("sim.t.por_pozo", "por pozo al horizonte · P50"),
      `${rango(fin.por_pozo, U.fA, U.uA)}<br>${t("sim.t.por_pozo.nota", "EUR al horizonte de {meses} meses: el volumen que implica la curva, no una reserva", { meses: p.meses })}`,
    ),
    tarjeta(
      `${sig3(fin.tasa_pico_p50 * U.fT)} ${U.uT}`,
      t("sim.t.pico", "tasa pico de la campaña · P50"),
      `${t("sim.t.pico.nota", "en el mes {m} de campaña, por día efectivo", { m: fin.mes_pico_p50 })}<br>${t("sim.t.igual", "= {v} {u}", { v: sig3(fin.tasa_pico_p50 * O.fT), u: O.uT })}`,
    ),
    tarjeta(
      usdM(R.usd.final.ingreso.p50),
      p.regalia > 0
        ? t("sim.t.ingreso.neto", "ingreso bruto menos regalía de {r} % · P50", { r: pct(p.regalia) })
        : t("sim.t.ingreso", "ingreso bruto acumulado · P50"),
      `P10 ${usdM(R.usd.final.ingreso.p10)} · P90 ${usdM(R.usd.final.ingreso.p90)}<br>${t("sim.t.ingreso.nota", "volumen × precio; sin capex, opex, transporte ni impuestos")}`,
    ),
    tarjeta(
      usdM(R.usd.final.van.p50),
      t("sim.t.van", "VAN del ingreso bruto al {tasa} % anual · P50", { tasa: pct(p.tasaAnual) }),
      `P10 ${usdM(R.usd.final.van.p10)} · P90 ${usdM(R.usd.final.van.p90)}<br>${t("sim.t.van.nota", "no es ganancia: no hay costos en este número")}`,
    ),
    tarjeta(
      `${M.publicados} + ${M.extrapolados}`,
      t("sim.t.meses", "meses publicados + extrapolados"),
      `${t("sim.t.meses.nota", "se usa la curva publicada hasta el mes {u} de vida del pozo; lo demás es extrapolación hiperbólica", { u: s.curva.ultimo_mes })} ${cita("curvas_tipo", "mes")}`,
    ),
  ];
  if (R.fluidos.petroleo && R.fluidos.gas) {
    const eq = R.equivalente_final;
    tarjetas.push(
      tarjeta(
        `${sig3((eq.p50 * D.bbl_por_m3) / 1e6)} MMboe`,
        t("sim.t.boe", "petróleo + gas a {meses} meses · P50", { meses: p.meses }),
        `${t("sim.t.igual", "= {v} {u}", { v: sig3(eq.p50 / 1e3), u: t("u.mil_m3_eq", "mil m³ equivalentes") })}<br>${t(
          "sim.t.boe.nota",
          "conversión con el factor de la Secretaría: 1.000 m³ de gas = 1 m³ de petróleo ({mcf} Mcf por boe)",
          { mcf: num(D.ft3_por_m3 / D.bbl_por_m3, 2) },
        )}`,
      ),
    );
  }
  $("tarjetas").innerHTML = tarjetas.join("");

  // --- the line that says what was simulated
  $("resumen-filtro").innerHTML = t(
    "sim.resumen",
    "{formacion} · ventana <code>{ventana}</code> · cohorte {cohorte}: {n} pozos en el grupo {citaN}. Curva <code>{col}</code> {citas}, <code>incluye_outliers = false</code> {citaInc}. Campaña: {pozos} pozos, {ritmo} por mes, {meses} meses, uptime {uptime} %.",
    {
      formacion: esc(g.formacion), ventana: esc(g.ventana), cohorte: g.cohorte,
      n: entero(s.porMetro ? g.n_pozos_por_m : g.n_pozos), citaN: cita("curvas_tipo", s.porMetro ? "n_pozos_por_m" : "n_pozos"),
      col: esc(s.col), citas: citas3, citaInc: cita("curvas_tipo", "incluye_outliers"),
      pozos: entero(R.n_pozos), ritmo: entero(R.ritmo_pozos_por_mes), meses: R.meses, uptime: pct(p.uptime),
    },
  );

  // --- charts
  const mesExtra = (c) => (c && c.curva.ultimo_mes + 1 < p.meses ? c.curva.ultimo_mes + 1 : null);
  const extraUsd = [sel.petroleo, sel.gas].map(mesExtra).filter((x) => x !== null);
  const mesExtraUsd = extraUsd.length ? Math.min(...extraUsd) : null;
  $("t-tasa").innerHTML = t("sim.g.t.tasa", "Tasa agregada de {fluido} ({u}), por día efectivo, y pozos en línea", { fluido: nombre, u: U.uT });
  $("t-acum").innerHTML = t("sim.g.t.acum", "{fluido} acumulado ({u})", { fluido: nombre, u: U.uA });
  $("t-ingreso").innerHTML = t("sim.g.t.ingreso", "Ingreso bruto por mes (millones de USD), petróleo + gas");
  $("t-ingreso-acum").innerHTML = t("sim.g.t.ingreso_acum", "Ingreso bruto acumulado (millones de USD)");
  graficar("g-tasa", { banda: F.tasa_agregada, factor: U.fT, unidad: U.uT, color: COLOR[fluido], nombre, mesExtra: mesExtra(s), pozos: R.pozos_en_linea });
  graficar("g-acum", { banda: F.acumulado, factor: U.fA, unidad: U.uA, color: COLOR[fluido], nombre, mesExtra: mesExtra(s) });
  const uUsd = t("u.musd_mes", "millones de USD/mes"), uUsdA = t("u.musd", "millones de USD");
  graficar("g-ingreso", { banda: R.usd.ingreso_mes, factor: 1e-6, unidad: uUsd, color: COLOR.usd, nombre: "USD", mesExtra: mesExtraUsd });
  graficar("g-ingreso-acum", { banda: R.usd.ingreso_acumulado, factor: 1e-6, unidad: uUsdA, color: COLOR.usd, nombre: "USD", mesExtra: mesExtraUsd });

  // --- notes of this run
  const pub = D.precios ?? {};
  const notas = [];
  for (const f of ["petroleo", "gas"]) {
    const c = sel[f];
    if (!c) {
      notas.push(t("sim.n.sin_curva", "El grupo no publica una curva de {fluido} con al menos {min} meses: ese fluido no entra en la simulación ni en el ingreso.", { fluido: FLUIDOS[f], min: D.min_puntos }));
      continue;
    }
    const m = mesesDe(c.curva, p.meses);
    notas.push(
      t("sim.n.meses", "{fluido}: curva <code>{col}</code> {cita}, {pub} meses publicados dentro del horizonte y {ext} extrapolados.", {
        fluido: FLUIDOS[f], col: esc(c.col), cita: cita("curvas_tipo", `${c.col}_p50`), pub: m.publicados, ext: m.extrapolados,
      }) +
        (c.porMetro
          ? " " + t("sim.n.por_metro", "Tasa por metro × rama de {rama} m; la curva por metro sale de los {n} pozos del grupo con rama conocida de 500 m o más {cita}.", {
              rama: entero(p.rama), n: entero(g.n_pozos_por_m), cita: cita("curvas_tipo", "n_pozos_por_m"),
            })
          : c.ramaIgnorada
            ? " " + t("sim.n.rama_ignorada", "La rama indicada no se usa: el grupo no publica curva por metro para este fluido; se usa la curva absoluta.")
            : " " + t("sim.n.absoluta", "Sin rama indicada: curva absoluta, es decir pozos con las ramas que tuvo el grupo.")),
    );
    if (m.extrapolados > 0 && c.curva.n_ultimo !== null && c.curva.n_ultimo !== undefined) {
      notas.push(
        t("sim.n.ancla", "{fluido}: la cola extrapolada se empalma en el mes {u}, el último con al menos la mitad de los pozos del grupo ({n} pozos) {cita}; los meses publicados posteriores no se usan.", {
          fluido: FLUIDOS[f], u: c.curva.ultimo_mes, n: entero(c.curva.n_ultimo), cita: cita("curvas_tipo", c.porMetro ? "n_pozos_por_m" : "n_pozos"),
        }) + (c.curva.n_ultimo < ANCLA_FIRME ? " " + t("sim.n.ancla_debil", "<b>Con tan pocos pozos ese nivel es ruidoso y arrastra a toda la extrapolación</b>: probá una cohorte más vieja para comparar.") : ""),
      );
    }
    if (c.curva.publicados < MESES_MIN_BASE && m.extrapolados > 0) {
      notas.push(t("sim.n.base_corta", "<b>Base corta</b> ({fluido}): la curva tiene {n} meses publicados; lo que sigue hasta el mes {meses} descansa en muy poco dato.", { fluido: FLUIDOS[f], n: c.curva.publicados, meses: p.meses }));
    }
    if (c.curva.acotados > 0 && m.extrapolados > 0) {
      notas.push(t("sim.n.acotados", "{fluido}: en {n} de los meses extrapolados la cola del P10 o del P90 alcanzó a la del P50 y la sigue (ADR-036). La banda se angosta ahí por construcción, no por dato.", { fluido: FLUIDOS[f], n: c.curva.acotados }));
    }
    if (m.sinCurva > 0) {
      notas.push(t("sim.n.sin_extension", "{fluido}: {n} meses del horizonte no tienen curva (meses sin publicar o cola que no se pudo ajustar); en esos meses de vida el pozo no suma.", { fluido: FLUIDOS[f], n: m.sinCurva }));
    }
  }
  const sinEntrar = R.n_pozos - R.pozos_en_linea[R.meses - 1];
  if (sinEntrar > 0) notas.push(t("sim.n.sin_entrar", "{n} pozos no llegan a entrar en producción dentro del horizonte con este ritmo.", { n: entero(sinEntrar) }));
  if (sel.petroleo) {
    notas.push(
      publico.petroleo
        ? t("sim.n.precio_pet", "Precio del petróleo: {bbl} USD/bbl = {m3} USD/m³ {cita}, promedio de venta de {region}, {mes}{prov}. Constante en todo el horizonte.", {
            bbl: num(pub.petroleo.usd_bbl, 2), m3: num(pub.petroleo.usd_m3, 1), cita: cita("precios", "precio_usd_m3"), region: esc(pub.petroleo.region), mes: esc(pub.petroleo.mes),
            prov: pub.petroleo.provisorio ? t("sim.n.provisorio", " (provisorio)") : "",
          })
        : t("sim.n.precio_pet_usuario", "Precio del petróleo: {bbl} USD/bbl = {m3} USD/m³, ingresado a mano: no es un dato público. Constante en todo el horizonte.", {
            bbl: num(p.usdBbl ?? 0, 2), m3: num(precio.petroleo, 1),
          }),
    );
  }
  if (sel.gas) {
    const conv = t("sim.n.gas_conv", "USD/MMBTU pasa a USD por mil m³ con 9.300 kcal/m³ ({f} MMBTU por mil m³); un gas más rico vale más por m³ (ADR-034).", { f: num(D.mmbtu_por_mil_m3, 3) });
    notas.push(
      (publico.gas
        ? t("sim.n.precio_gas", "Precio del gas: {mmbtu} USD/MMBTU = {km3} USD por mil m³ {cita}, cuenca {region}, promedio ponderado de todos los segmentos, {mes}.", {
            mmbtu: num(pub.gas.usd_mmbtu, 2), km3: num(pub.gas.usd_mil_m3, 1), cita: cita("precios", "precio_usd_mil_m3"), region: esc(pub.gas.region), mes: esc(pub.gas.mes),
          })
        : t("sim.n.precio_gas_usuario", "Precio del gas: {mmbtu} USD/MMBTU = {km3} USD por mil m³, ingresado a mano: no es un dato público.", {
            mmbtu: num(p.usdMmbtu ?? 0, 2), km3: num(precio.gas, 1),
          })) +
        " " + conv,
    );
  }
  if (p.regalia > 0) notas.push(t("sim.n.regalia", "Regalía de {r} % restada del bruto. La alícuota base argentina es 12 %; las efectivas cambian por provincia y concesión.", { r: pct(p.regalia) }));
  if (pub.fecha_realizacion) notas.push(t("sim.n.fuente_precios", "Precios: informe de regalías de crudo (realizado el {f}) y precios de gas Res. 1/2018, Secretaría de Energía, CC-BY 4.0; descargados el {d}.", { f: esc(pub.fecha_realizacion), d: esc(pub.fecha_descarga) }));
  $("notas").innerHTML = notas.map((n) => `<li>${n}</li>`).join("");
}

// --- start -------------------------------------------------------------------------------------------------------------

async function main() {
  [, D] = await Promise.all([cabecera("simulador"), cargar("simulador.json")]);
  const formaciones = distintos(D.grupos.map((g) => g.formacion));
  opciones($("s-formacion"), formaciones);
  $("s-formacion").value = formaciones.includes("Vaca Muerta") ? "Vaca Muerta" : formaciones[0];
  $("s-meses").max = String(D.meses);
  $("s-meses").value = String(D.meses);
  $("s-uptime").value = String(Math.round(D.uptime * 100));
  llenarVentanas();
  preciosPublicos();
  if (!D.precios) estado(t("sim.sin_precios", "Este snapshot no trae precios públicos: ingresá los tuyos para ver dólares."));

  $("s-formacion").addEventListener("change", () => { llenarVentanas(); correr(); });
  $("s-ventana").addEventListener("change", () => { llenarCohortes(true); correr(); });
  $("s-cohorte").addEventListener("change", correr);
  for (const id of ["s-pozos", "s-ritmo", "s-rama", "s-meses", "s-uptime", "s-precio-pet", "s-precio-gas", "s-tasa", "s-regalia", "s-nsim", "s-semilla"]) {
    $(id).addEventListener("input", correrPronto);
  }
  for (const id of ["s-fluido", "s-unidades"]) $(id).addEventListener("change", dibujar);
  $("s-correr").addEventListener("click", correr);
  $("s-precios").addEventListener("click", () => { preciosPublicos(); correr(); });
  window.addEventListener("resize", () => Object.values(graficos).forEach((c) => c.resize()));
  await correr();
  console.info(`simulador: ${entero(D.n_grupos)} grupos, ${D.meses} meses`);
}

main().catch((e) => {
  estado(t("error.datos", "No se pudieron cargar los datos: {mensaje}", { mensaje: esc(e.message) }), true);
  console.error(e);
});
