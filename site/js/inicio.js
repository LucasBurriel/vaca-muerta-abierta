import { cabecera, cargar, cita, entero, esc, num } from "./comun.js";

function tarjeta(c, titulo) {
  const v = typeof c.valor === "number" ? entero(c.valor) : esc(c.valor ?? "—");
  return `<div class="tarjeta"><div class="valor">${v}</div><div class="titulo">${esc(titulo)}</div>
    <div class="regla">${cita(c.tabla, c.columna, c.regla)}<br>${esc(c.regla)}</div></div>`;
}

async function main() {
  const [meta, R] = await Promise.all([cabecera("inicio"), cargar("resumen.json")]);
  const pct = (a, b) => (b ? ` (${num((100 * a) / b, 0)} %)` : "");
  document.getElementById("tarjetas").innerHTML = [
    tarjeta(R.pozos_maestro, "pozos físicos en el maestro"),
    tarjeta(R.pozos_en_alcance, "en alcance: Neuquina no convencional"),
    tarjeta(R.pozos_productores, "con primera producción"),
    tarjeta(R.pozos_con_rama, "comparables por metro de rama" + pct(R.pozos_con_rama.valor, R.pozos_en_alcance.valor)),
    tarjeta(R.outliers, `outliers de IP90/m sobre ${entero(R.pozos_evaluados_outlier.valor)} evaluados`),
    tarjeta(R.operadoras, "operadoras (alias unificados)"),
    tarjeta(R.formaciones, "formaciones"),
    tarjeta(R.ultima_produccion, "último mes con producción"),
  ].join("");

  const g = R.grupos_curvas_publicables;
  const v = R.ventanas;
  document.getElementById("titulares").innerHTML = `
    <ul class="compacta">
      <li><b>F0 · Medir la suciedad.</b> <code>idpozo</code> no es un pozo sino pozo × formación; los datasets de perforación son agregados;
        41 % de los registros de fractura traen rama 0. <a href="https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/informes/calidad-2026-10-30.md">Informe de calidad</a>.</li>
      <li><b>F1 · Maestro de pozos.</b> ${entero(R.pozos_maestro.valor)} pozos físicos ${cita("pozos", "sigla_clave")}, alias de sigla, operadora y
        formación normalizadas con tablas versionadas, coordenadas validadas, rama con precedencia explícita.
        <a href="https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/informes/maestro-2026-10-31.md">Informe del maestro</a>.</li>
      <li><b>F2 · Indicadores.</b> IP30/90/180 en días efectivos, acumulados, todo por metro de rama donde se puede
        (${entero(R.pozos_con_rama.valor)} de ${entero(R.pozos_en_alcance.valor)} en alcance ${cita(R.pozos_con_rama.tabla, R.pozos_con_rama.columna)}),
        ventana de fluido por pozo (${entero(v.petroleo?.valor ?? 0)} petróleo · ${entero(v.volatil_condensado?.valor ?? 0)} volátil · ${entero(v.gas?.valor ?? 0)} gas
        ${cita("indicadores", "ventana")}), curvas tipo publicables para ${entero(g.cohorte_formacion.valor)} grupos cohorte × formación,
        ${entero(g.cohorte_formacion_ventana.valor)} con ventana y ${entero(g.cohorte_formacion_operadora.valor)} con operadora ${cita("curvas_tipo", "publicable")}.
        <a href="https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/informes/indicadores-2026-10-31.md">Informe de indicadores</a>.</li>
      <li><b>F3 · Este sitio.</b> Estático, regenerado cada mes por CI desde las tablas publicadas (fecha de datos arriba a la derecha).
        <a href="metodo.html">Método y fuentes</a>.</li>
    </ul>`;

  const T = R.vaca_muerta_petroleo_por_cohorte;
  const filas = T.filas.filter((f) => f.cohorte >= 2012);
  const chart = echarts.init(document.getElementById("grafico-inicio"), null, { renderer: "canvas" });
  chart.setOption({
    animation: false,
    grid: { left: 70, right: 70, top: 40, bottom: 40 },
    legend: { top: 0 },
    tooltip: {
      trigger: "axis",
      formatter: (ps) => {
        const f = filas[ps[0].dataIndex];
        return `<b>cohorte ${f.cohorte}</b> · n = ${f.n} (${f.n_con_ip90_por_m} con IP90/m)<br>
          rama mediana: ${num(f.rama_m_mediana, 0)} m<br>IP90 petróleo/m mediana: ${num(f.ip90_petroleo_m3_d_por_m_mediana, 3)} m³/d por m`;
      },
    },
    xAxis: { type: "category", data: filas.map((f) => f.cohorte) },
    yAxis: [
      { type: "value", name: "rama mediana (m)", nameLocation: "middle", nameGap: 50 },
      { type: "value", name: "IP90 petróleo / m (m³/d por m)", nameLocation: "middle", nameGap: 50, min: 0 },
    ],
    series: [
      {
        name: "rama_m (mediana)",
        type: "bar",
        data: filas.map((f) => ({ value: f.rama_m_mediana, itemStyle: { opacity: f.n_con_ip90_por_m < 5 ? 0.35 : 0.85 } })),
        color: "#9aa5b1",
      },
      {
        name: "ip90_petroleo_m3_d_por_m (mediana)",
        type: "line",
        yAxisIndex: 1,
        data: filas.map((f) => (f.n_con_ip90_por_m < 5 ? null : f.ip90_petroleo_m3_d_por_m_mediana)),
        color: "#b5451b",
        symbolSize: 7,
        lineStyle: { width: 2.5 },
      },
    ],
  });
  window.addEventListener("resize", () => chart.resize());
  document.getElementById("cita-grafico").innerHTML =
    `Fuente: ${T.origen_columnas.map((c) => cita(T.tabla, c)).join(" ")} — ${esc(T.regla)}. Barras atenuadas: menos de 5 pozos con IP90/m (la línea se omite).`;
}

main().catch((e) => {
  document.getElementById("tarjetas").innerHTML = `<p class="error">No se pudieron cargar los datos: ${esc(e.message)}</p>`;
  console.error(e);
});
