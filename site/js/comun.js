// Shared helpers for the static site: data loading, number formatting, citations, column labels.
// Every number shown on a page carries the table and column it came from (`cita`).

const cache = new Map();

export async function cargar(nombre) {
  if (!cache.has(nombre)) {
    cache.set(
      nombre,
      fetch(`data/${nombre}`).then((r) => {
        if (!r.ok) throw new Error(`${nombre}: HTTP ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(nombre);
}

export function cita(tabla, columna, regla) {
  const t = regla ? `${tabla}.${columna} — ${regla}` : `${tabla}.${columna}`;
  return `<span class="cita" title="${esc(t)}">${esc(tabla)}.${esc(columna)}</span>`;
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const fmtInt = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });

export function num(v, dec = 3) {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  if (Number.isInteger(v) && dec === 0) return fmtInt.format(v);
  const abs = Math.abs(v);
  const d = dec === "auto" ? (abs >= 100 ? 0 : abs >= 1 ? 2 : 3) : dec;
  return new Intl.NumberFormat("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
}

export function entero(v) {
  return v === null || v === undefined ? null : fmtInt.format(v);
}

// Labels and units of the columns shown on the site (names are the tables' column names, never translated).
export const ETIQUETAS = {
  sigla: ["Sigla", ""],
  operadora: ["Operadora", ""],
  formacion: ["Formación", ""],
  area: ["Área", ""],
  cohorte: ["Cohorte", "año de primera producción"],
  ventana: ["Ventana", "por GOR propio"],
  rama_m: ["Rama", "m"],
  etapas: ["Etapas", ""],
  etapas_por_100m: ["Etapas / 100 m", ""],
  arena_tn_por_m: ["Arena", "t/m"],
  agua_fractura_m3_por_m: ["Agua fractura", "m³/m"],
  dias_efectivos_total: ["Días efectivos", "d"],
  ip90_petroleo_m3_d: ["IP90 petróleo", "m³/d"],
  ip90_gas_mil_m3_d: ["IP90 gas", "mil m³/d"],
  ip90_equivalente_m3_d: ["IP90 equivalente", "m³/d"],
  ip90_petroleo_m3_d_por_m: ["IP90 petróleo / m", "m³/d por m"],
  ip90_gas_mil_m3_d_por_m: ["IP90 gas / m", "mil m³/d por m"],
  ip90_equivalente_m3_d_por_m: ["IP90 equiv. / m", "m³/d por m"],
  acum12_petroleo_m3_por_m: ["Acum. 12 m petróleo / m", "m³/m"],
  acum12_gas_mil_m3_por_m: ["Acum. 12 m gas / m", "mil m³/m"],
  acum12_equivalente_m3_por_m: ["Acum. 12 m equiv. / m", "m³/m"],
  gor12_m3_m3: ["GOR 12 m", "m³/m³"],
  corte_agua12: ["Corte de agua 12 m", "fracción"],
  outlier_ip90_m: ["Outlier IP90/m", "ADR-018"],
  estado: ["Estado", ""],
  tipo_pozo: ["Tipo de pozo", ""],
  primera_produccion: ["Primera producción", "mes"],
};

export const TASAS = {
  equivalente_m3_d_por_m: ["Equivalente por metro", "m³ eq/d por m de rama"],
  petroleo_m3_d_por_m: ["Petróleo por metro", "m³/d por m de rama"],
  gas_mil_m3_d_por_m: ["Gas por metro", "mil m³/d por m de rama"],
  equivalente_m3_d: ["Equivalente", "m³ eq/d"],
  petroleo_m3_d: ["Petróleo", "m³/d"],
  gas_mil_m3_d: ["Gas", "mil m³/d"],
};

// Why a value is null: the flags of the row that explain each null column (docs/indicadores.md).
const MOTIVOS = {
  rama_m: ["sin_rama_sin_fractura", "sin_rama_faltante", "sin_rama_cero", "sin_rama", "sin_produccion"],
  etapas: ["sin_rama_sin_fractura", "sin_produccion"],
  por_m: ["sin_rama_sin_fractura", "sin_rama_faltante", "sin_rama_cero", "sin_rama", "rama_corta"],
  ip90: ["ip90_dias_insuficientes", "sin_produccion", "nunca_produjo"],
  acum12: ["acum12_historia_corta", "sin_produccion", "nunca_produjo"],
  gor12_m3_m3: ["gor12_sin_petroleo", "acum12_historia_corta", "sin_produccion", "nunca_produjo"],
  corte_agua12: ["corte_agua12_sin_liquido", "acum12_historia_corta", "sin_produccion", "nunca_produjo"],
  outlier_ip90_m: ["outlier_no_evaluado", "fuera_alcance"],
  cohorte: ["sin_produccion", "nunca_produjo"],
  ventana: ["sin_produccion", "nunca_produjo", "gor12_sin_petroleo"],
};

export const DESCRIPCION_FLAGS = {
  fuera_alcance: "fuera del alcance (no es Neuquina no convencional, ADR-002)",
  sin_produccion: "sin registro de producción (pozo solo con fractura)",
  nunca_produjo: "hay registros pero petróleo y gas siempre 0",
  sin_rama_sin_fractura: "sin registro de fractura: no hay longitud de rama",
  sin_rama_faltante: "horizontal (≥ 10 etapas) con rama 0 en la fuente: longitud no cargada",
  sin_rama_cero: "rama 0 en la fuente con pocas etapas",
  sin_rama: "sin rama por otro motivo",
  rama_corta: "rama menor a 500 m: no se normaliza por metro (ADR-019)",
  tef_cero_con_produccion: "un mes con producción y 0 días efectivos: se tomó el mes entero",
  tef_mayor_mes: "un mes con más días efectivos que días del mes: acotado",
  primer_mes_parcial: "primer mes con menos de 15 días efectivos (informativo)",
  produccion_suma_idpozo: "dos o más idpozo del pozo sumados en un mes",
  volumen_negativo: "un volumen mensual negativo en la fuente (corrección)",
  ip30_dias_insuficientes: "menos de 30 días efectivos: IP30 nulo",
  ip90_dias_insuficientes: "menos de 90 días efectivos: IP90 nulo",
  ip180_dias_insuficientes: "menos de 180 días efectivos: IP180 nulo",
  acum6_historia_corta: "la fuente no cubre 6 meses todavía",
  acum12_historia_corta: "la fuente no cubre 12 meses todavía",
  acum24_historia_corta: "la fuente no cubre 24 meses todavía",
  acum6_meses_faltantes: "meses sin registro dentro de la ventana de 6, contados como 0",
  acum12_meses_faltantes: "meses sin registro dentro de la ventana de 12, contados como 0",
  acum24_meses_faltantes: "meses sin registro dentro de la ventana de 24, contados como 0",
  gor6_sin_petroleo: "sin petróleo en 6 meses: GOR indefinido (pozo de gas)",
  gor12_sin_petroleo: "sin petróleo en 12 meses: GOR indefinido (pozo de gas)",
  corte_agua6_sin_liquido: "ni petróleo ni agua en 6 meses",
  corte_agua12_sin_liquido: "ni petróleo ni agua en 12 meses",
  ventana_provisoria: "ventana clasificada con gor6 o toda la historia, no con gor12",
  outlier_ip90_m_alto: "outlier alto de IP90/m dentro de su formación (ADR-018)",
  outlier_ip90_m_bajo: "outlier bajo de IP90/m dentro de su formación (ADR-018)",
  outlier_no_evaluado: "no evaluado para outliers (sin IP90/m o formación chica)",
};

export function motivoNulo(columna, flags) {
  let claves = MOTIVOS[columna];
  if (!claves) {
    if (columna.endsWith("_por_m")) claves = MOTIVOS.por_m.concat(columna.startsWith("ip90") ? MOTIVOS.ip90 : MOTIVOS.acum12);
    else if (columna.startsWith("ip90")) claves = MOTIVOS.ip90;
    else if (columna.startsWith("acum12")) claves = MOTIVOS.acum12;
    else claves = [];
  }
  const hit = claves.filter((k) => flags.includes(k));
  if (!hit.length) return "sin dato: la fuente no lo trae";
  return "sin dato porque: " + hit.map((k) => DESCRIPCION_FLAGS[k] || k).join("; ");
}

// Columnar table -> row object accessor without copying everything.
export function fila(P, i) {
  const r = {};
  for (const k in P.columnas) r[k] = P.columnas[k][i];
  r.flags = (P.columnas.flags[i] || []).map((j) => P.flags_dic[j]);
  return r;
}

export function distintos(valores) {
  return [...new Set(valores.filter((v) => v !== null && v !== undefined))].sort((a, b) =>
    typeof a === "number" ? a - b : String(a).localeCompare(String(b), "es"),
  );
}

export function llenarSelect(sel, valores, { todo = "todas" } = {}) {
  const prev = sel.value;
  sel.innerHTML = `<option value="">${todo}</option>` + valores.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
}

export async function cabecera(activa) {
  const meta = await cargar("meta.json");
  const el = document.querySelector("header.top .fecha");
  if (el) el.innerHTML = `datos descargados el <b>${esc(meta.fecha_descarga)}</b> · maestro <b>${esc(meta.version_maestro)}</b>`;
  document.querySelectorAll("header.top nav a").forEach((a) => {
    if (a.dataset.pagina === activa) a.classList.add("activa");
  });
  const pie = document.querySelector(".pie .meta");
  if (pie) {
    pie.innerHTML =
      `Datos: Secretaría de Energía de la Nación Argentina, ${esc(meta.licencia_datos)}; descarga del ${esc(meta.fecha_descarga)}, ` +
      `tablas publicadas en <code>data/publicado/${esc(meta.version_maestro)}/</code>. Código MIT. ` +
      `Generado el ${esc(meta.fecha_generacion)}.`;
  }
  return meta;
}

export function paleta(n) {
  const base = ["#b5451b", "#2b6cb0", "#2f7a4a", "#a86b00", "#6b46c1", "#c53030", "#0f766e", "#7c2d12", "#4a5568", "#be185d"];
  return Array.from({ length: n }, (_, i) => base[i % base.length]);
}

export function colorEscala(v, min, max) {
  // light yellow -> dark red, perceptually ordered enough for a map of a ratio
  const t = Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
  const stops = [
    [255, 245, 200],
    [254, 196, 79],
    [236, 112, 20],
    [153, 52, 4],
  ];
  const k = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  const f = t * (stops.length - 1) - k;
  const c = stops[k].map((a, i) => Math.round(a + (stops[k + 1][i] - a) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
