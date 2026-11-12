import { cabecera, cargar, cita, entero, esc, num } from "./comun.js";
import { enlace, t } from "./i18n.js";

// `regla` arrives from resumen.json in Spanish (the pipeline's own wording); its English is under `regla.<clave>`.
function tarjeta(R, clave, titulo) {
  const c = R[clave];
  const v = typeof c.valor === "number" ? entero(c.valor) : esc(c.valor ?? "—");
  const regla = t(`regla.${clave}`, c.regla);
  return `<div class="tarjeta"><div class="valor">${v}</div><div class="titulo">${esc(titulo)}</div>
    <div class="regla">${cita(c.tabla, c.columna, regla)}<br>${esc(regla)}</div></div>`;
}

const GH = "https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/";

async function main() {
  const [, R] = await Promise.all([cabecera("inicio"), cargar("resumen.json")]);
  const pct = (a, b) => (b ? ` (${num((100 * a) / b, 0)} %)` : "");
  document.getElementById("tarjetas").innerHTML = [
    tarjeta(R, "pozos_maestro", t("inicio.t.maestro", "pozos físicos en el maestro")),
    tarjeta(R, "pozos_en_alcance", t("inicio.t.alcance", "en alcance: Neuquina no convencional")),
    tarjeta(R, "pozos_productores", t("inicio.t.productores", "con primera producción")),
    tarjeta(R, "pozos_con_rama", t("inicio.t.rama", "comparables por metro de rama") + pct(R.pozos_con_rama.valor, R.pozos_en_alcance.valor)),
    tarjeta(R, "outliers", t("inicio.t.outliers", "outliers de IP90/m sobre {n} evaluados", { n: entero(R.pozos_evaluados_outlier.valor) })),
    tarjeta(R, "operadoras", t("inicio.t.operadoras", "operadoras (alias unificados)")),
    tarjeta(R, "formaciones", t("inicio.t.formaciones", "formaciones")),
    tarjeta(R, "ultima_produccion", t("inicio.t.ultima", "último mes con producción")),
  ].join("");

  const g = R.grupos_curvas_publicables;
  const v = R.ventanas;
  const li = [
    t(
      "inicio.f0",
      '<b>F0 · Medir la suciedad.</b> <code>idpozo</code> no es un pozo sino pozo × formación; los datasets de perforación son agregados; 41 % de los registros de fractura traen rama 0. <a href="{url}">Informe de calidad</a>.',
      { url: `${GH}informes/calidad-2026-10-30.md` },
    ),
    t(
      "inicio.f1",
      '<b>F1 · Maestro de pozos.</b> {n} pozos físicos {cita}, alias de sigla, operadora y formación normalizadas con tablas versionadas, coordenadas validadas, rama con precedencia explícita. <a href="{url}">Informe del maestro</a>.',
      { n: entero(R.pozos_maestro.valor), cita: cita("pozos", "sigla_clave"), url: `${GH}informes/maestro-2026-10-31.md` },
    ),
    t(
      "inicio.f2",
      '<b>F2 · Indicadores.</b> IP30/90/180 en días efectivos, acumulados, todo por metro de rama donde se puede ({conRama} de {enAlcance} en alcance {citaRama}), ventana de fluido por pozo ({petroleo} petróleo · {volatil} volátil · {gas} gas {citaVentana}), curvas tipo publicables para {g1} grupos cohorte × formación, {g2} con ventana y {g3} con operadora {citaCurvas}. <a href="{url}">Informe de indicadores</a>.',
      {
        conRama: entero(R.pozos_con_rama.valor), enAlcance: entero(R.pozos_en_alcance.valor),
        citaRama: cita(R.pozos_con_rama.tabla, R.pozos_con_rama.columna),
        petroleo: entero(v.petroleo?.valor ?? 0), volatil: entero(v.volatil_condensado?.valor ?? 0), gas: entero(v.gas?.valor ?? 0),
        citaVentana: cita("indicadores", "ventana"),
        g1: entero(g.cohorte_formacion.valor), g2: entero(g.cohorte_formacion_ventana.valor), g3: entero(g.cohorte_formacion_operadora.valor),
        citaCurvas: cita("curvas_tipo", "publicable"), url: `${GH}informes/indicadores-2026-10-31.md`,
      },
    ),
    t(
      "inicio.f3",
      '<b>F3 · Este sitio.</b> Estático, regenerado cada mes por CI desde las tablas publicadas (fecha de datos arriba a la derecha). <a href="{metodo}">Método y fuentes</a>.',
      { metodo: enlace("metodo.html") },
    ),
    t(
      "inicio.f5",
      '<b>F5 · F6 · Simular y valorizar.</b> Ajustes de declinación, Monte Carlo de campaña desde las curvas tipo publicadas y precios públicos para pasar de m³ a dólares brutos. En este sitio, el <a href="{simulador}">simulador de campaña</a>; con tus propios pozos, el servidor MCP local (<a href="{url}">README</a>).',
      { simulador: enlace("simulador.html"), url: "https://github.com/LucasBurriel/vaca-muerta-abierta#readme" },
    ),
  ];
  document.getElementById("titulares").innerHTML = `<ul class="compacta">${li.map((x) => `<li>${x}</li>`).join("")}</ul>`;

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
        return t(
          "inicio.tooltip",
          "<b>cohorte {cohorte}</b> · n = {n} ({nIp} con IP90/m)<br>rama mediana: {rama} m<br>IP90 petróleo/m mediana: {ip} m³/d por m",
          { cohorte: f.cohorte, n: f.n, nIp: f.n_con_ip90_por_m, rama: num(f.rama_m_mediana, 0), ip: num(f.ip90_petroleo_m3_d_por_m_mediana, 3) },
        );
      },
    },
    xAxis: { type: "category", data: filas.map((f) => f.cohorte) },
    yAxis: [
      { type: "value", name: t("inicio.eje.rama", "rama mediana (m)"), nameLocation: "middle", nameGap: 50 },
      { type: "value", name: t("inicio.eje.ip", "IP90 petróleo / m (m³/d por m)"), nameLocation: "middle", nameGap: 50, min: 0 },
    ],
    series: [
      {
        name: t("inicio.serie.rama", "rama_m (mediana)"),
        type: "bar",
        data: filas.map((f) => ({ value: f.rama_m_mediana, itemStyle: { opacity: f.n_con_ip90_por_m < 5 ? 0.35 : 0.85 } })),
        color: "#9aa5b1",
      },
      {
        name: t("inicio.serie.ip", "ip90_petroleo_m3_d_por_m (mediana)"),
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
  document.getElementById("cita-grafico").innerHTML = t(
    "inicio.cita.grafico",
    "Fuente: {citas} — {regla}. Barras atenuadas: menos de 5 pozos con IP90/m (la línea se omite).",
    { citas: T.origen_columnas.map((c) => cita(T.tabla, c)).join(" "), regla: esc(t("regla.vaca_muerta_petroleo_por_cohorte", T.regla)) },
  );
}

main().catch((e) => {
  document.getElementById("tarjetas").innerHTML = `<p class="error">${t("error.datos", "No se pudieron cargar los datos: {mensaje}", { mensaje: esc(e.message) })}</p>`;
  console.error(e);
});
