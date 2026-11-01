import { ETIQUETAS, cabecera, cargar, cita, distintos, entero, esc, fila, llenarSelect, motivoNulo, num } from "./comun.js";

// Columns shown, in order: [column, source table, decimals]. Names are the published tables' names.
const COLS = [
  ["sigla", "indicadores", null],
  ["operadora", "indicadores", null],
  ["formacion", "indicadores", null],
  ["cohorte", "indicadores", null],
  ["ventana", "indicadores", null],
  ["rama_m", "indicadores", 0],
  ["etapas", "indicadores", 0],
  ["etapas_por_100m", "indicadores", 2],
  ["arena_tn_por_m", "indicadores", 2],
  ["ip90_petroleo_m3_d", "indicadores", 1],
  ["ip90_gas_mil_m3_d", "indicadores", 1],
  ["ip90_petroleo_m3_d_por_m", "indicadores", 4],
  ["ip90_gas_mil_m3_d_por_m", "indicadores", 4],
  ["ip90_equivalente_m3_d_por_m", "indicadores", 4],
  ["acum12_equivalente_m3_por_m", "indicadores", 2],
  ["gor12_m3_m3", "indicadores", 0],
  ["corte_agua12", "indicadores", 2],
  ["outlier_ip90_m", "indicadores", null],
  ["estado", "pozos", null],
];
const PAGINA = 100;

let P, idx = [], orden = { col: "ip90_equivalente_m3_d_por_m", desc: true }, pagina = 0;
const $ = (id) => document.getElementById(id);

function aplicarFiltros() {
  const c = P.columnas;
  const op = $("f-operadora").value, fm = $("f-formacion").value, co = $("f-cohorte").value, ve = $("f-ventana").value;
  const q = $("f-sigla").value.trim().toUpperCase();
  const soloAlcance = $("f-alcance").checked, conRama = $("f-con-rama").checked;
  idx = [];
  for (let i = 0; i < P.n; i++) {
    if (soloAlcance && !c.en_alcance[i]) continue;
    if (conRama && !c.rama_normalizable[i]) continue;
    if (op && c.operadora[i] !== op) continue;
    if (fm && c.formacion[i] !== fm) continue;
    if (co && String(c.cohorte[i]) !== co) continue;
    if (ve && c.ventana[i] !== ve) continue;
    if (q && !String(c.sigla_clave[i]).includes(q)) continue;
    idx.push(i);
  }
  ordenar();
  pagina = 0;
  render();
}

function ordenar() {
  const v = P.columnas[orden.col];
  const s = orden.desc ? -1 : 1;
  idx.sort((a, b) => {
    const x = v[a], y = v[b];
    if (x === null || x === undefined) return 1; // nulls last, whatever the direction
    if (y === null || y === undefined) return -1;
    if (typeof x === "number" && typeof y === "number") return s * (x - y);
    return s * String(x).localeCompare(String(y), "es");
  });
}

function celda(col, dec, r) {
  const v = r[col];
  if (v === null || v === undefined) {
    return `<td class="nulo" title="${esc(motivoNulo(col, r.flags))}"><abbr>sin dato</abbr></td>`;
  }
  if (typeof v === "boolean") return `<td>${v ? "sí" : "no"}</td>`;
  if (typeof v === "number") return `<td class="num">${dec === null ? v : num(v, dec)}</td>`;
  return `<td>${esc(v)}</td>`;
}

function render() {
  const thead = document.querySelector("#tabla thead");
  thead.innerHTML =
    "<tr>" +
    COLS.map(([col, tabla]) => {
      const [et, un] = ETIQUETAS[col] || [col, ""];
      const cls = orden.col === col ? (orden.desc ? "orden-desc" : "orden-asc") : "";
      return `<th class="${cls}" data-col="${col}" title="${esc(un)}">${esc(et)}${un ? ` <small>(${esc(un)})</small>` : ""}${cita(tabla, col)}</th>`;
    }).join("") +
    "</tr>";
  thead.querySelectorAll("th").forEach((th) =>
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      orden = orden.col === col ? { col, desc: !orden.desc } : { col, desc: true };
      ordenar();
      render();
    }),
  );
  const ini = pagina * PAGINA, fin = Math.min(idx.length, ini + PAGINA);
  const filas = [];
  for (let k = ini; k < fin; k++) {
    const r = fila(P, idx[k]);
    const cls = [r.outlier_ip90_m ? "outlier" : "", r.en_alcance ? "" : "fuera"].join(" ");
    filas.push(`<tr class="${cls}">${COLS.map(([col, , dec]) => celda(col, dec, r)).join("")}</tr>`);
  }
  document.querySelector("#tabla tbody").innerHTML = filas.join("");
  $("pag-info").textContent = idx.length ? `${ini + 1}–${fin} de ${entero(idx.length)}` : "sin filas";
  $("pag-ant").disabled = pagina === 0;
  $("pag-sig").disabled = fin >= idx.length;
  const conPm = idx.filter((i) => P.columnas.ip90_equivalente_m3_d_por_m[i] !== null).length;
  $("resumen-filtro").innerHTML =
    `${entero(idx.length)} pozos; ${entero(conPm)} con IP90 por metro ${cita("indicadores", "ip90_equivalente_m3_d_por_m")}. ` +
    `Ordenado por <code>${esc(orden.col)}</code> ${orden.desc ? "descendente" : "ascendente"}; los nulos van al final.`;
}

function descargarCsv() {
  const cols = Object.keys(P.columnas).filter((k) => k !== "flags");
  const esc1 = (v) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lineas = [[...cols, "flags"].join(",")];
  for (const i of idx) {
    const r = fila(P, i);
    lineas.push([...cols.map((k) => esc1(r[k])), esc1(r.flags.join("|"))].join(","));
  }
  const blob = new Blob(["﻿" + lineas.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "pozos-filtrados.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function main() {
  [, P] = await Promise.all([cabecera("explorador"), cargar("pozos.json")]);
  const c = P.columnas;
  const enAlcance = (col) => distintos(c[col].filter((_, i) => c.en_alcance[i]));
  llenarSelect($("f-operadora"), enAlcance("operadora"));
  llenarSelect($("f-formacion"), enAlcance("formacion"));
  llenarSelect($("f-cohorte"), enAlcance("cohorte"));
  llenarSelect($("f-ventana"), enAlcance("ventana"));
  for (const id of ["f-operadora", "f-formacion", "f-cohorte", "f-ventana", "f-alcance", "f-con-rama"]) $(id).addEventListener("change", aplicarFiltros);
  $("f-sigla").addEventListener("input", aplicarFiltros);
  $("pag-ant").addEventListener("click", () => { pagina--; render(); });
  $("pag-sig").addEventListener("click", () => { pagina++; render(); });
  $("descargar").addEventListener("click", descargarCsv);
  aplicarFiltros();
}

main().catch((e) => {
  $("resumen-filtro").innerHTML = `<span class="error">No se pudieron cargar los datos: ${esc(e.message)}</span>`;
  console.error(e);
});
