import { ETIQUETAS, cabecera, cargar, cita, colorEscala, distintos, entero, esc, fila, llenarSelect, motivoNulo, num, paleta, razonNulo } from "./comun.js";
import { t } from "./i18n.js";

const $ = (id) => document.getElementById(id);
let P, mapa, capa;
const SIN_DATO = "#9a9a9a";

function filtrados() {
  const c = P.columnas;
  const op = $("f-operadora").value, fm = $("f-formacion").value, co = $("f-cohorte").value, ve = $("f-ventana").value;
  const soloAlcance = $("f-alcance").checked;
  const out = [];
  for (let i = 0; i < P.n; i++) {
    if (c.longitud[i] === null || c.latitud[i] === null) continue;
    if (soloAlcance && !c.en_alcance[i]) continue;
    if (op && c.operadora[i] !== op) continue;
    if (fm && c.formacion[i] !== fm) continue;
    if (co && String(c.cohorte[i]) !== co) continue;
    if (ve && c.ventana[i] !== ve) continue;
    out.push(i);
  }
  return out;
}

function cuantil(vals, q) {
  const s = [...vals].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

function popup(r, col) {
  const campos = ["operadora", "formacion", "cohorte", "ventana", "rama_m", "etapas", "ip90_equivalente_m3_d_por_m", "ip90_petroleo_m3_d_por_m", "ip90_gas_mil_m3_d_por_m", "estado"];
  const filas = campos.map((k) => {
    const [et, un] = ETIQUETAS[k] || [k, ""];
    const v = r[k];
    const sinDato = t("nulo.corto", "sin dato");
    const razon = razonNulo(k, r.flags) ?? t("nulo.fuente.corto", "la fuente no lo trae");
    const txt = v === null || v === undefined ? `<i title="${esc(motivoNulo(k, r.flags))}">${sinDato} (${esc(razon)})</i>` : typeof v === "number" ? (k === "cohorte" ? v : num(v, k.endsWith("_por_m") ? 4 : 0)) : esc(v);
    return `<tr><td>${esc(et)}${un ? ` <small>(${esc(un)})</small>` : ""}</td><td><b>${txt}</b></td></tr>`;
  });
  return `<b>${esc(r.sigla)}</b> ${cita("pozos", "sigla")}<br><table>${filas.join("")}</table>
    <small>${t("mapa.popup.pie", "coordenadas {lon} {lat}; valores {val}", { lon: cita("pozos", "longitud"), lat: cita("pozos", "latitud"), val: cita("indicadores", col) })}</small>`;
}

function dibujar() {
  const col = $("f-color").value;
  const idx = filtrados();
  const c = P.columnas;
  if (capa) capa.remove();
  capa = L.layerGroup();
  const render = L.canvas({ padding: 0.5 });
  let colorDe, leyenda;
  const numerico = col.endsWith("_por_m");
  if (numerico) {
    const vals = idx.map((i) => c[col][i]).filter((v) => v !== null && v > 0);
    const lo = vals.length ? cuantil(vals, 0.05) : 0, hi = vals.length ? cuantil(vals, 0.95) : 1;
    colorDe = (i) => (c[col][i] === null ? SIN_DATO : colorEscala(c[col][i], lo, hi));
    const [et, un] = ETIQUETAS[col];
    leyenda =
      `<span style="--c:${colorEscala(lo, lo, hi)}">P5 ${num(lo, 4)}</span><span style="--c:${colorEscala((lo + hi) / 2, lo, hi)}">${num((lo + hi) / 2, 4)}</span>` +
      `<span style="--c:${colorEscala(hi, lo, hi)}">P95 ${num(hi, 4)}</span><span style="--c:${SIN_DATO}">${t("nulo.corto", "sin dato")} (${entero(idx.length - vals.length)})</span>` +
      `&nbsp; ${esc(et)} (${esc(un)}) ${cita("indicadores", col)} — ${t("mapa.escala", "escala recortada en P5–P95 de los pozos filtrados")}`;
  } else {
    const cats = distintos(idx.map((i) => c[col][i]));
    const cols = paleta(cats.length);
    const m = new Map(cats.map((k, j) => [k, cols[j]]));
    colorDe = (i) => m.get(c[col][i]) ?? SIN_DATO;
    leyenda = cats.map((k) => `<span style="--c:${m.get(k)}">${esc(k)}</span>`).join("") + `<span style="--c:${SIN_DATO}">${t("nulo.corto", "sin dato")}</span> ${cita("indicadores", col)}`;
  }
  const bounds = [];
  for (const i of idx) {
    const ll = [c.latitud[i], c.longitud[i]];
    bounds.push(ll);
    const mk = L.circleMarker(ll, { renderer: render, radius: 4, weight: 0.6, color: "#333", fillColor: colorDe(i), fillOpacity: 0.85 });
    mk.bindPopup(() => popup(fila(P, i), col), { maxWidth: 360 });
    capa.addLayer(mk);
  }
  capa.addTo(mapa);
  if (bounds.length && !dibujar.ajustado) {
    mapa.fitBounds(bounds, { padding: [20, 20] });
    dibujar.ajustado = true;
  }
  $("leyenda").innerHTML = leyenda;
  const sinCoord = P.columnas.longitud.filter((v) => v === null).length;
  $("resumen-filtro").innerHTML = t(
    "mapa.resumen",
    "{n} pozos dibujados {lon} {lat}; {sin} pozos del maestro no tienen coordenadas (flag <code>sin_coordenadas</code>).",
    { n: entero(idx.length), lon: cita("pozos", "longitud"), lat: cita("pozos", "latitud"), sin: entero(sinCoord) },
  );
}

async function main() {
  [, P] = await Promise.all([cabecera("mapa"), cargar("pozos.json")]);
  const c = P.columnas;
  const enAlcance = (col) => distintos(c[col].filter((_, i) => c.en_alcance[i]));
  llenarSelect($("f-operadora"), enAlcance("operadora"));
  llenarSelect($("f-formacion"), enAlcance("formacion"));
  llenarSelect($("f-cohorte"), enAlcance("cohorte"));
  llenarSelect($("f-ventana"), enAlcance("ventana"));
  mapa = L.map("mapa", { preferCanvas: true }).setView([-38.3, -69.0], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 17, attribution: "© OpenStreetMap contributors" }).addTo(mapa);
  for (const id of ["f-color", "f-operadora", "f-formacion", "f-cohorte", "f-ventana", "f-alcance"]) $(id).addEventListener("change", dibujar);
  dibujar();
}

main().catch((e) => {
  $("resumen-filtro").innerHTML = `<span class="error">${t("error.datos", "No se pudieron cargar los datos: {mensaje}", { mensaje: esc(e.message) })}</span>`;
  console.error(e);
});
