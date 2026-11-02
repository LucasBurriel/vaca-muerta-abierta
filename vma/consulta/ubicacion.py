"""Where the published data is when the package is installed outside a clone (F5 packaging, ADR-033).

Resolution order for the agent and the MCP server:

1. ``--datos RUTA`` on the command line;
2. the environment variable ``VMA_DATOS``;
3. the folder the scripts live in, when it is a clone (it has ``site/data/pozos.json`` or ``data/publicado/``);
4. the user cache (``~/.vaca-muerta-abierta/``): if it holds a snapshot, use it; else download the site's JSON
   snapshot (about 5 MB, the same files GitHub Pages serves) into it and use that.

Nothing of the user's is ever written there: only the public snapshot.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO

ENV = "VMA_DATOS"
PAGES = "https://lucasburriel.github.io/vaca-muerta-abierta/data/"
ARCHIVOS = (
    "meta.json",
    "resumen.json",
    "pozos.json",
    "curvas_cohorte_formacion.json",
    "curvas_cohorte_formacion_ventana.json",
    "curvas_cohorte_formacion_operadora.json",
)

Opener = Callable[[str], IO[bytes]]


def cache_dir() -> Path:
    return Path(os.environ.get("VMA_CACHE", Path.home() / ".vaca-muerta-abierta"))


def es_clon(raiz: Path) -> bool:
    return (raiz / "site" / "data" / "pozos.json").exists() or (raiz / "data" / "publicado").exists()


def _abrir_url(url: str) -> IO[bytes]:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "vaca-muerta-abierta/0.1 (vma-mcp)"})
    return urllib.request.urlopen(req, timeout=120)  # noqa: S310 - fixed https host


def descargar_snapshot(
    destino: Path, base_url: str = PAGES, opener: Opener = _abrir_url, log: Callable[[str], None] = print
) -> Path:
    """Fetch the site's JSON snapshot into ``destino/site/data/``; returns ``destino``. Partial downloads are removed."""
    carpeta = Path(destino) / "site" / "data"
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS:
        url = base_url.rstrip("/") + "/" + nombre
        tmp = carpeta / (nombre + ".part")
        log(f"  {url}")
        with opener(url) as r, tmp.open("wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        try:
            json.loads(tmp.read_text(encoding="utf-8"))
        except ValueError as e:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{url} no es JSON válido: {e}") from e
        tmp.replace(carpeta / nombre)
    return Path(destino)


def raiz_datos(
    explicita: Path | None,
    raiz_scripts: Path,
    *,
    descargar: bool = True,
    opener: Opener = _abrir_url,
    log: Callable[[str], None] = lambda s: print(s, file=sys.stderr),
) -> Path:
    """The folder to open with ``vma.consulta.datos.abrir``, by the order in the module docstring."""
    if explicita is not None:
        return Path(explicita)
    env = os.environ.get(ENV)
    if env:
        return Path(env)
    if es_clon(raiz_scripts):
        return raiz_scripts
    cache = cache_dir()
    if es_clon(cache):
        return cache
    if not descargar:
        raise FileNotFoundError(
            f"no hay datos: ni {raiz_scripts} es un clon, ni {cache} tiene el snapshot; pasá --datos o {ENV}"
        )
    log(f"sin datos locales: descargando el snapshot del sitio en {cache} (sólo datos públicos)")
    descargar_snapshot(cache, opener=opener, log=log)
    return cache
