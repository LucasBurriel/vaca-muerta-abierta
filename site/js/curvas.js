import { TASAS, cabecera, cargar, cita, distintos, entero, esc, llenarSelect, num, paleta } from "./comun.js";

const $ = (id) => document.getElementById(id);
let D = null; // curvas_<nivel>.json currently loaded
let chart, chartN;

function nivel() {
  return $("f-nivel").value;
}

async function cargarNivel() {
  D = await cargar(`curvas_${nivel()}.json`);
  const conVentana = nivel() === "cohorte_formacion_ventana", conOperadora = nivel() === "cohorte_formacion_operadora";
  $("l-ventana").hidden = !conVentana;
  $("l-operadora").hidden = !conOperadora;
  llenarSelect($("f-formacion"), distintos(D.grupos.map((g) => g.formacion)), { todo: "elegir…" });
  if (!$("f-formacion").value) $("f-formacion").value = D.grupos.some((g) => g.formacion === "Vaca Muerta") ? "Vaca Muerta" : D.grupos[0]?.formacion ?? "";
  if (conVentana) llenarSelect($("f-ventana"), distintos(D.grupos.map((g) => g.ventana)), { todo: "elegir…" });
  if (conOperadora) llenarSelect($("f-operadora"), distintos(D.grupos.map((g) => g.operadora)), { todo: "elegir…" });
  if (conVentana && !$("f-ventana").value) $("f-ventana").value = "petroleo";
  if (conOperadora && !$("f-operadora").value) $("f-operadora").value = $("f-operadora").options[1]?.value ?? "";
  actualizarCohortes();
}

function gruposBase() {
  const fm = $("f-formacion").value, inc = $("f-outliers").checked;
  const ve = nivel() === "cohorte_formacion_ventana" ? $("f-ventana").value : null;
  const op = nivel() === "cohorte_formacion_operadora" ? $("f-operadora").value : null;
  return D.grupos.filter(
    (g) => g.formacion === fm && g.incluye_outliers === inc && (ve === null || g.ventana === ve) && (op === null || g.operadora === op),
  );
}

function actualizarCohortes() {
  const sel = $("f-cohorte");
  const prev = new Set([...sel.selectedOptions].map((o) => o.value));
  const cohortes = distintos(gruposBase().map((g) => g.cohorte));
  sel.innerHTML = cohortes.map((c) => `<option value="${c}">${c}</option>`).join("");
  let marcadas = 0;
  for (const o of sel.options) if (prev.has(o.value)) { o.selected = true; marcadas++; }
  if (!marcadas) {
    const ultimas = cohortes.slice(-4);
    for (const o of sel.options) o.selected = ultimas.includes(Number(o.value));
  }
  dibujar();
}

function dibujar() {
  const tasa = $("f-tasa").value, banda = $("f-banda").checked, log = $("f-log").checked;
  const elegidas = new Set([...$("f-cohorte").selectedOptions].map((o) => Number(o.value)));
  const grupos = gruposBase().filter((g) => elegidas.has(g.cohorte) && g.series[tasa]);
  const colores = paleta(grupos.length);
  const [etq, unidad] = TASAS[tasa];
  const porM = tasa.endsWith("_por_m");
  const series = [], seriesN = [];
  grupos.forEach((g, k) => {
    const s = g.series[tasa], color = colores[k];
    const nombre = `${g.cohorte}`;
    const nCol = porM ? g.n_pozos_por_m : g.n_pozos;
    if (banda) {
      // P10-P90 band as polygons (one per run of months with both percentiles), drawn under the P50 line
      const polys = [];
      let run = [];
      const cerrar = () => {
        if (run.length > 1) polys.push([...run.map(([m, , hi]) => [m, hi]), ...run.slice().reverse().map(([m, lo]) => [m, lo])]);
        run = [];
      };
      g.mes.forEach((m, i) => {
        if (s.p10[i] === null || s.p90[i] === null) cerrar();
        else run.push([m, s.p90[i], s.p10[i]]);
      });
      cerrar();
      series.push({
        name: nombre, type: "custom", color, silent: true, tooltip: { show: false }, z: 1,
        data: polys.map((_, j) => j),
        renderItem: (params, api) => ({
          type: "polygon",
          shape: { points: polys[params.dataIndex].map((pt) => api.coord(pt)) },
          style: { fill: color, opacity: 0.14 },
        }),
      });
    }
    series.push({
      name: nombre, type: "line", color, symbol: "circle", symbolSize: 4, lineStyle: { width: 2.2 },
      data: g.mes.map((m, i) => [m, s.p50[i]]), z: 3,
    });
    seriesN.push({ name: nombre, type: "bar", color, data: g.mes.map((m, i) => [m, nCol[i]]), barGap: "10%" });
  });
  // custom (band) series do not drive the axis extent: compute it from the data shown
  let ymax = 0;
  for (const g of grupos) for (const v of banda ? g.series[tasa].p10 : g.series[tasa].p50) if (v !== null && v > ymax) ymax = v;
  const ejeY = {
    type: log ? "log" : "value", name: `${etq} (${unidad})`, nameLocation: "middle", nameGap: 60,
    min: log ? "dataMin" : 0, max: log ? undefined : ymax ? Number((ymax * 1.05).toPrecision(2)) : undefined,
  };
  chart.setOption(
    {
      animation: false,
      legend: { top: 0, data: grupos.map((g) => `${g.cohorte}`) },
      grid: { left: 85, right: 30, top: 40, bottom: 50 },
      tooltip: {
        trigger: "axis",
        formatter: (ps) => {
          const m = ps[0]?.value?.[0];
          const filas = grupos
            .map((g, k) => {
              const i = g.mes.indexOf(m);
              if (i < 0) return "";
              const s = g.series[tasa], n = porM ? g.n_pozos_por_m[i] : g.n_pozos[i];
              const v = (x) => (x === null ? "—" : num(x, porM ? 4 : 1));
              return `<span style="color:${colores[k]}">●</span> <b>${g.cohorte}</b> n=${n}: P50 ${v(s.p50[i])} · P10 ${v(s.p10[i])} · P90 ${v(s.p90[i])}`;
            })
            .filter(Boolean);
          return `<b>mes ${m}</b> desde la primera producción<br>${filas.join("<br>")}`;
        },
      },
      xAxis: { type: "value", name: "meses desde la primera producción", nameLocation: "middle", nameGap: 30, min: 0, max: D.mes_max },
      yAxis: ejeY,
      series,
    },
    true,
  );
  chartN.setOption(
    {
      animation: false,
      grid: { left: 85, right: 30, top: 10, bottom: 30 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "value", min: 0, max: D.mes_max, axisLabel: { show: false } },
      yAxis: { type: "value", name: porM ? "n_pozos_por_m" : "n_pozos", nameLocation: "middle", nameGap: 60 },
      series: seriesN,
    },
    true,
  );
  const quien = [$("f-formacion").value, nivel() === "cohorte_formacion_ventana" ? `ventana ${$("f-ventana").value}` : "", nivel() === "cohorte_formacion_operadora" ? $("f-operadora").value : ""]
    .filter(Boolean)
    .join(" · ");
  $("resumen-filtro").innerHTML =
    `${esc(quien)} — ${grupos.length} cohortes con datos publicables para <code>${esc(tasa)}</code> ` +
    `${cita("curvas_tipo", `${tasa}_p50`)} ${cita("curvas_tipo", `${tasa}_p10`)} ${cita("curvas_tipo", `${tasa}_p90`)} ${cita("curvas_tipo", porM ? "n_pozos_por_m" : "n_pozos")}; ` +
    `<code>incluye_outliers = ${$("f-outliers").checked}</code> ${cita("curvas_tipo", "incluye_outliers")}. Tasas por día efectivo (ADR-016).`;
  tabla(grupos, tasa, porM);
}

function tabla(grupos, tasa, porM) {
  const meses = [0, 1, 3, 6, 12, 24, 36, 60];
  const thead = `<tr><th>cohorte</th>${meses.map((m) => `<th>mes ${m}<br><small>P50 (n)</small></th>`).join("")}</tr>`;
  const filas = grupos.map((g) => {
    const s = g.series[tasa];
    const celdas = meses.map((m) => {
      const i = g.mes.indexOf(m);
      if (i < 0) return `<td class="nulo" title="el grupo no llega a este mes todavía"><abbr>—</abbr></td>`;
      const n = porM ? g.n_pozos_por_m[i] : g.n_pozos[i];
      if (s.p50[i] === null) return `<td class="nulo" title="n = ${n} < 5: no se publica (ADR-017)"><abbr>n=${n}</abbr></td>`;
      return `<td class="num">${num(s.p50[i], porM ? 4 : 1)} <small>(${n})</small></td>`;
    });
    return `<tr><td>${g.cohorte}</td>${celdas.join("")}</tr>`;
  });
  document.querySelector("#tabla thead").innerHTML = thead;
  document.querySelector("#tabla tbody").innerHTML = filas.join("") || `<tr><td colspan="${meses.length + 1}">Sin grupos publicables con esta selección.</td></tr>`;
}

async function main() {
  await cabecera("curvas");
  $("f-tasa").innerHTML = Object.entries(TASAS).map(([k, [e, u]]) => `<option value="${k}">${esc(e)} (${esc(u)})</option>`).join("");
  chart = echarts.init($("grafico"));
  chartN = echarts.init($("grafico-n"));
  window.addEventListener("resize", () => { chart.resize(); chartN.resize(); });
  $("f-nivel").addEventListener("change", cargarNivel);
  for (const id of ["f-formacion", "f-ventana", "f-operadora", "f-outliers"]) $(id).addEventListener("change", actualizarCohortes);
  for (const id of ["f-cohorte", "f-tasa", "f-banda", "f-log"]) $(id).addEventListener("change", dibujar);
  await cargarNivel();
  console.info(`curvas: ${entero(D.n_grupos)} grupos en ${nivel()}`);
}

main().catch((e) => {
  $("resumen-filtro").innerHTML = `<span class="error">No se pudieron cargar los datos: ${esc(e.message)}</span>`;
  console.error(e);
});
