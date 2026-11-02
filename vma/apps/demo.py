"""A minimal local MCP Apps host for eyeballing the four views without Claude Desktop (ADR-032).

    python -m vma.apps.demo [--salida DIR] [--fuente auto|parquet|json]

Writes ``DIR/host.html`` plus the four resource documents, each with a real tool result computed now from the
committed synthetic dataset (``tests/fixtures/sintetico``). ``host.html`` embeds every view in an iframe and plays
the host side of the protocol: answers ``ui/initialize`` with a ``hostContext`` (theme, styles), waits for
``ui/notifications/initialized``, sends ``ui/notifications/tool-input`` and ``ui/notifications/tool-result``,
resizes on ``ui/notifications/size-changed``, and answers ``tools/call`` from the simulator by re-running the
tool through a tiny local HTTP endpoint when ``--servir`` is given (otherwise it answers with the stored result
and says so). It is a test rig, not a product: the real hosts are Claude Desktop, ChatGPT, VS Code and the others
listed in the ext-apps README.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vma import apps as APPS
from vma.consulta import datos as D
from vma.consulta import herramientas as H

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "sintetico"

LLAMADAS = {
    "curva_mia.html": ("comparar_mi_pozo", {"sigla": "MIO-003", "mes_max": 24}),
    "mapa_vecinos.html": ("vecinos_de_mis_pozos", {"radio_km": 8, "filtros": {"campania": "PAD-A"}}),
    "ranking_posicion.html": (
        "comparar_mi_campania",
        {"filtros": {"campania": "PAD-B"}, "metrica": "ip90_petroleo_m3_d_por_m"},
    ),
    "simulador_campania.html": (
        "simular_campania",
        {
            "formacion": "Vaca Muerta",
            "ventana": "petroleo",
            "n_pozos": 12,
            "meses": 120,
            "rama_m": 2800,
            "ritmo_pozos_por_mes": 3,
            "n_sim": 300,
        },
    ),
}

HOST = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Host de prueba · MCP Apps · vaca-muerta-abierta</title>
<style>
body { font: 14px system-ui, sans-serif; margin: 0; background: #eceae4; color: #222; }
header { padding: 10px 16px; background: #1d1d1b; color: #eee; display: flex; gap: 16px; align-items: center; }
header code { color: #f6c7a8; }
section { margin: 16px; background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.12); overflow: hidden; }
section h2 { margin: 0; padding: 8px 14px; font-size: 13px; color: #555; border-bottom: 1px solid #e5e5e5; display:flex; justify-content: space-between; }
iframe { width: 100%; border: 0; display: block; height: 200px; }
.log { font: 11px ui-monospace, monospace; color: #666; padding: 4px 14px; max-height: 70px; overflow: auto; border-top: 1px solid #eee; white-space: pre; }
label { margin-left: auto; font-size: 12px; }
</style></head><body>
<header><b>Host de prueba MCP Apps</b> <span>protocolo <code>2026-01-26</code> · recursos <code>ui://vaca-muerta/</code> · datos sintéticos</span>
<label><input type="checkbox" id="tema"> tema oscuro</label></header>
<div id="vistas"></div>
<script>
const VISTAS = __VISTAS__;
const RESULTADOS = __RESULTADOS__;
const SERVIR = __SERVIR__;
const STYLES = { variables: { "--color-background-primary": "light-dark(#fbfaf7, #15161a)", "--color-text-primary": "light-dark(#1d1d1b, #e8e6df)", "--font-sans": "system-ui, sans-serif", "--border-radius-md": "8px" } };
const estados = {};
function log(name, txt) { const el = document.getElementById("log-" + name); el.textContent = (txt + "\\n" + el.textContent).slice(0, 2000); }
function enviar(name, msg) { estados[name].frame.contentWindow.postMessage(msg, "*"); }
function tema() { return document.getElementById("tema").checked ? "dark" : "light"; }
for (const v of VISTAS) {
  const sec = document.createElement("section");
  sec.innerHTML = `<h2><span>${v.titulo} — <code>${v.uri}</code> ← <code>${v.tool}</code></span><span>${JSON.stringify(v.args)}</span></h2><iframe id="f-${v.archivo}" src="${v.archivo}" sandbox="allow-scripts allow-same-origin allow-popups"></iframe><div class="log" id="log-${v.archivo}"></div>`;
  document.getElementById("vistas").appendChild(sec);
  estados[v.archivo] = { frame: sec.querySelector("iframe"), v };
}
window.addEventListener("message", async (ev) => {
  const m = ev.data; if (!m || m.jsonrpc !== "2.0") return;
  const name = Object.keys(estados).find((k) => estados[k].frame.contentWindow === ev.source); if (!name) return;
  const st = estados[name];
  if (m.method === "ui/initialize") {
    log(name, "← ui/initialize " + JSON.stringify(m.params).slice(0, 120));
    enviar(name, { jsonrpc: "2.0", id: m.id, result: { protocolVersion: "2026-01-26", hostInfo: { name: "host-de-prueba", version: "0.1" }, hostCapabilities: { serverTools: {}, openLinks: {} }, hostContext: { theme: tema(), styles: STYLES, displayMode: "inline", platform: "desktop", locale: "es-AR" } } });
  } else if (m.method === "ui/notifications/initialized") {
    log(name, "← initialized → tool-input, tool-result");
    enviar(name, { jsonrpc: "2.0", method: "ui/notifications/tool-input", params: { arguments: st.v.args } });
    enviar(name, { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: RESULTADOS[name] });
  } else if (m.method === "ui/notifications/size-changed") {
    st.frame.style.height = Math.min(Math.max(m.params.height + 4, 120), 1600) + "px";
  } else if (m.method === "tools/call") {
    log(name, "← tools/call " + m.params.name + " " + JSON.stringify(m.params.arguments));
    if (SERVIR) {
      try {
        const r = await fetch("/tools/call", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(m.params) });
        enviar(name, { jsonrpc: "2.0", id: m.id, result: await r.json() });
      } catch (e) { enviar(name, { jsonrpc: "2.0", id: m.id, error: { code: -32000, message: String(e) } }); }
    } else {
      enviar(name, { jsonrpc: "2.0", id: m.id, result: RESULTADOS[name] });
      log(name, "  (sin --servir: se devuelve el resultado guardado)");
    }
  } else if (m.method === "ui/message" || m.method === "ui/open-link" || m.method === "ui/update-model-context") {
    log(name, "← " + m.method + " " + JSON.stringify(m.params).slice(0, 160));
    enviar(name, { jsonrpc: "2.0", id: m.id, result: {} });
  } else if (m.method) {
    log(name, "← " + m.method);
    if (m.id !== undefined) enviar(name, { jsonrpc: "2.0", id: m.id, result: {} });
  }
});
document.getElementById("tema").addEventListener("change", () => {
  for (const name in estados) enviar(name, { jsonrpc: "2.0", method: "ui/notifications/host-context-changed", params: { theme: tema() } });
});
</script></body></html>
"""


def resultado_mcp(d: D.Datos, nombre: str, args: dict) -> dict:
    """What the MCP server would send as ``CallToolResult``: text content with the JSON envelope."""
    try:
        env = H.ejecutar(d, nombre, args)
        return {
            "content": [{"type": "text", "text": json.dumps(env, ensure_ascii=False, default=str)}],
            "isError": False,
        }
    except H.ErrorHerramienta as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}],
            "isError": True,
        }


def generar(salida: Path, fuente: str = "auto", servir: bool = False) -> Path:
    salida.mkdir(parents=True, exist_ok=True)
    d = D.abrir(ROOT, fuente)
    H.ejecutar(
        d,
        "cargar_mis_pozos",
        {"ruta": str(FIX / "mis_pozos_produccion.csv"), "ruta_pozos": str(FIX / "mis_pozos_atributos.csv")},
    )
    vistas, resultados = [], {}
    for archivo, (tool, args) in LLAMADAS.items():
        (salida / archivo).write_text(APPS.html(archivo), encoding="utf-8")
        vistas.append(
            {
                "archivo": archivo,
                "uri": APPS.uri(archivo),
                "tool": tool,
                "args": args,
                "titulo": APPS.VISTAS[archivo]["titulo"],
            }
        )
        resultados[archivo] = resultado_mcp(d, tool, args)
    host = (
        HOST.replace("__VISTAS__", json.dumps(vistas, ensure_ascii=False))
        .replace("__RESULTADOS__", json.dumps(resultados, ensure_ascii=False))
        .replace("__SERVIR__", "true" if servir else "false")
    )
    (salida / "host.html").write_text(host, encoding="utf-8")
    return salida / "host.html"


def servir(salida: Path, puerto: int, d: D.Datos) -> None:  # pragma: no cover - interactive
    """Static files plus POST /tools/call for the simulator's re-runs (localhost only)."""
    import http.server
    import socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(salida), **k)

        def do_POST(self):
            if self.path != "/tools/call":
                self.send_error(404)
                return
            n = int(self.headers.get("content-length", "0"))
            params = json.loads(self.rfile.read(n) or b"{}")
            body = json.dumps(
                resultado_mcp(d, params.get("name", ""), params.get("arguments") or {}), ensure_ascii=False
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", puerto), Handler) as srv:
        print(f"host de prueba en http://127.0.0.1:{puerto}/host.html (Ctrl-C para salir)", file=sys.stderr)
        srv.serve_forever()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m vma.apps.demo",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--salida", type=Path, default=ROOT / "data" / "apps-demo")
    ap.add_argument("--fuente", default="auto", choices=["auto", "parquet", "json"])
    ap.add_argument(
        "--servir",
        action="store_true",
        help="servir la carpeta en localhost y atender tools/call del simulador",
    )
    ap.add_argument("--puerto", type=int, default=8765)
    args = ap.parse_args(argv)
    host = generar(args.salida, args.fuente, servir=args.servir)
    print(f"host de prueba: {host}", file=sys.stderr)
    if args.servir:
        d = D.abrir(ROOT, args.fuente)
        H.ejecutar(
            d,
            "cargar_mis_pozos",
            {
                "ruta": str(FIX / "mis_pozos_produccion.csv"),
                "ruta_pozos": str(FIX / "mis_pozos_atributos.csv"),
            },
        )
        servir(args.salida, args.puerto, d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
