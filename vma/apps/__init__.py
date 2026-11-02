"""MCP Apps (extension ``io.modelcontextprotocol/ui``, spec 2026-01-26) for the observatory's server (ADR-032).

Four interactive views, each a self-contained HTML document served as a ``ui://vaca-muerta/...`` resource with
MIME type ``text/html;profile=mcp-app`` and attached to a tool through ``_meta.ui.resourceUri``:

| resource | tool | shows |
|---|---|---|
| ``ui://vaca-muerta/curva_mia.html``         | ``comparar_mi_pozo``     | the published P10/P50/P90 with the user's well on top |
| ``ui://vaca-muerta/mapa_vecinos.html``      | ``vecinos_de_mis_pozos`` | the user's wells among the public neighbours on a map |
| ``ui://vaca-muerta/ranking_posicion.html``  | ``comparar_mi_campania`` | the campaign's wells against their public medians |
| ``ui://vaca-muerta/simulador_campania.html``| ``simular_campania``     | the aggregated bands, with controls that re-run the tool |

The HTML talks to the host with JSON-RPC over ``postMessage`` (``ui/initialize`` → ``ui/notifications/initialized``
→ ``ui/notifications/tool-result``; ``ui/notifications/size-changed``; ``tools/call`` for the simulator), no SDK:
the bridge is ``ui/puente.js``, injected at the ``<!--PUENTE-->`` marker; the shared stylesheet ``ui/base.css`` at
``<!--BASE_CSS-->``. Charts and maps come from cdnjs with pinned versions and integrity hashes, the same as the
static site (ADR-021); the resource's ``_meta.ui.csp.resourceDomains`` allows exactly those hosts. Hosts without
the extension ignore ``_meta.ui`` and show the tool's text, which every tool returns anyway (ADR-025).

Python's ``mcp`` (FastMCP) accepts ``meta`` on tools but its ``resources/read`` has no place for ``_meta``, so
:func:`instalar` registers the resources through FastMCP and wraps the low-level ``ReadResourceRequest`` handler
to add the UI metadata to ``ui://`` contents. Nothing else of the SDK is touched.
"""

from __future__ import annotations

from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
MIME = "text/html;profile=mcp-app"
PREFIJO = "ui://vaca-muerta/"
VERSION_SPEC = "2026-01-26"
EXTENSION = "io.modelcontextprotocol/ui"

CDN = ["https://cdnjs.cloudflare.com"]
MAPAS = ["https://tile.openstreetmap.org", "https://*.tile.openstreetmap.org"]

# resource file -> (tool it is attached to, title, extra resource domains)
VISTAS: dict[str, dict] = {
    "curva_mia.html": {
        "tool": "comparar_mi_pozo",
        "titulo": "Mi pozo contra la curva tipo",
        "descripcion": "Curva tipo publicada (P10/P50/P90 por mes) con la historia del pozo propio superpuesta, percentil por mes e IP90 contra el grupo.",
        "dominios": CDN,
    },
    "mapa_vecinos.html": {
        "tool": "vecinos_de_mis_pozos",
        "titulo": "Mis pozos entre los vecinos",
        "descripcion": "Mapa con los pozos propios y los pozos públicos vecinos, tamaño por IP90 por metro, con la mediana de los vecinos por pozo.",
        "dominios": CDN + MAPAS,
    },
    "ranking_posicion.html": {
        "tool": "comparar_mi_campania",
        "titulo": "Mi campaña en el ranking",
        "descripcion": "Cada pozo propio contra la mediana pública de su grupo: cociente, porcentaje de pozos que supera, resumen de la campaña.",
        "dominios": CDN,
    },
    "simulador_campania.html": {
        "tool": "simular_campania",
        "titulo": "Simulador de campaña",
        "descripcion": "Bandas P10/P50/P90 de tasa agregada y acumulado de una campaña simulada, con controles que vuelven a llamar a simular_campania.",
        "dominios": CDN,
    },
}


def uri(archivo: str) -> str:
    return PREFIJO + archivo


def tool_meta(tool: str) -> dict | None:
    """``_meta`` for a tool that has a view, else None."""
    for archivo, v in VISTAS.items():
        if v["tool"] == tool:
            return {"ui": {"resourceUri": uri(archivo), "visibility": ["model", "app"]}}
    return None


def html(archivo: str) -> str:
    """The resource document: the view with the bridge and the stylesheet inlined (self-contained)."""
    if archivo not in VISTAS:
        raise KeyError(f"vista desconocida {archivo!r}; las vistas son {', '.join(VISTAS)}")
    doc = (UI_DIR / archivo).read_text(encoding="utf-8")
    puente = (UI_DIR / "puente.js").read_text(encoding="utf-8")
    css = (UI_DIR / "base.css").read_text(encoding="utf-8")
    doc = doc.replace("<!--PUENTE-->", f"<script>\n{puente}\n</script>", 1)
    doc = doc.replace("<!--BASE_CSS-->", f"<style>\n{css}\n</style>", 1)
    assert "<!--PUENTE-->" not in doc and "<!--BASE_CSS-->" not in doc
    return doc


def resource_meta(archivo: str) -> dict:
    """``_meta.ui`` of the resource contents: the CSP the view needs and a border preference."""
    v = VISTAS[archivo]
    return {
        "ui": {
            "csp": {"connectDomains": [], "resourceDomains": list(v["dominios"])},
            "prefersBorder": True,
        }
    }


def _lector(archivo: str):
    """A zero-argument reader for one view (FastMCP resources take no parameters)."""

    def leer() -> str:
        return html(archivo)

    leer.__name__ = f"leer_{archivo.replace('.', '_')}"
    return leer


def instalar(mcp) -> list[str]:
    """Register the four resources on a FastMCP server and make ``resources/read`` return their ``_meta.ui``.
    Returns the registered URIs. Idempotent per server instance."""
    import mcp.types as T

    uris = []
    for archivo, v in VISTAS.items():
        u = uri(archivo)
        mcp.resource(u, name=archivo, title=v["titulo"], description=v["descripcion"], mime_type=MIME)(
            _lector(archivo)
        )
        uris.append(u)

    original = mcp._mcp_server.request_handlers[T.ReadResourceRequest]

    async def con_meta(req):
        res = await original(req)
        rr = getattr(res, "root", None)
        if isinstance(rr, T.ReadResourceResult):
            for c in rr.contents:
                s = str(c.uri)
                if s.startswith(PREFIJO):
                    archivo = s[len(PREFIJO) :]
                    if archivo in VISTAS:
                        c.meta = resource_meta(archivo)
        return res

    mcp._mcp_server.request_handlers[T.ReadResourceRequest] = con_meta
    return uris
