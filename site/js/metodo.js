import { cabecera, entero, esc } from "./comun.js";

const QUE_ES = {
  pozos: ["maestro de pozos: una fila por pozo físico, alias, operadora y formación normalizadas, coordenadas, rama, fechas", "docs/maestro.md"],
  indicadores: ["una fila por pozo: IP30/90/180 en días efectivos, acumulados, por metro, GOR, corte de agua, ventana, outliers, flags, linaje", "docs/indicadores.md"],
  curvas_tipo: ["una fila por nivel × grupo × incluye_outliers × mes: P10/P50/P90/media de la tasa por día efectivo, n_pozos, publicable", "docs/indicadores.md"],
};
const GH = "https://github.com/LucasBurriel/vaca-muerta-abierta/blob/main/";

async function main() {
  const meta = await cabecera("metodo");
  document.querySelector("#fuentes tbody").innerHTML = meta.fuentes
    .map(
      (f) => `<tr><td><a href="${esc(f.url)}">${esc(f.key)}</a></td><td class="mono">${esc(f.file)}</td>
        <td class="num">${entero(f.bytes)}</td><td class="mono" title="${esc(f.sha256)}">${esc(String(f.sha256).slice(0, 16))}…</td>
        <td>${esc(String(f.ckan_last_modified ?? "").slice(0, 19))}</td></tr>`,
    )
    .join("");
  document.getElementById("meta-linea").textContent =
    `Descarga del ${meta.fecha_descarga} (manifiesto generado ${meta.manifest_generated_at}); maestro y tablas publicadas en data/publicado/${meta.version_maestro}/; ` +
    `JSON del sitio generados el ${meta.fecha_generacion} (${meta.generado_utc}).`;
  document.querySelector("#tablas tbody").innerHTML = Object.entries(meta.tablas)
    .map(([k, t]) => {
      const [que, doc] = QUE_ES[k] || ["", ""];
      return `<tr><td class="mono">${esc(k)}</td><td class="num">${entero(t.filas)}</td><td class="num">${entero(t.columnas)}</td>
        <td style="white-space:normal">${esc(que)}</td><td><a href="${GH}${doc}">${esc(doc)}</a></td></tr>`;
    })
    .join("");
}

main().catch((e) => {
  document.getElementById("meta-linea").innerHTML = `<span class="error">No se pudo cargar meta.json: ${esc(e.message)}</span>`;
  console.error(e);
});
