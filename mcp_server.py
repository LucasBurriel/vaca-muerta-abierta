"""MCP server (stdio) exposing the F4 read-only tools to Claude Desktop, Claude Code or any MCP client (ADR-025).

    python mcp_server.py                 # Parquet if built, else the committed site/data/ snapshot
    python mcp_server.py --fuente json
    python mcp_server.py --sql           # also expose sql_solo_lectura (opt-in; read-only, allowlisted, LIMITed)

Claude Desktop (claude_desktop_config.json) / Claude Code (.mcp.json):

    {"mcpServers": {"vaca-muerta-abierta": {"command": "python",
      "args": ["C:/ruta/al/repo/mcp_server.py"]}}}

Every tool returns the same JSON envelope as the CLI agent: ``datos`` + ``cita`` (tabla, columnas, filtros,
regla_doc) + ``exclusiones`` + ``notas`` + ``fecha_datos`` + ``version_maestro`` + ``fuente``. The server
never writes: it opens the tables read-only and has no tool that changes anything. Needs ``pip install -e ".[agente]"``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vma.consulta import datos as D
from vma.consulta import herramientas as H

ROOT = Path(__file__).resolve().parent


def construir(d: D.Datos, con_sql: bool):
    """Build the FastMCP server with one MCP tool per registry entry, all delegating to ``H.ejecutar``."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "vaca-muerta-abierta",
        instructions=(
            "Datos públicos por pozo de Vaca Muerta (Secretaría de Energía, Capítulo IV), limpios y con linaje. "
            "Herramientas de solo lectura; cada resultado trae su cita (tabla, columnas, filtros, regla). "
            "Sin cita no hay número; cuando un indicador es nulo, 'sin_dato_porque' dice el motivo. "
            f"Fuente: {d.fuente}, descargada {d.fecha_descarga}, maestro {d.version_maestro}."
        ),
    )

    def _json(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)

    def _correr(nombre: str, **entrada) -> str:
        entrada = {k: v for k, v in entrada.items() if v is not None}
        try:
            return _json(H.ejecutar(d, nombre, entrada, con_sql=con_sql))
        except H.ErrorHerramienta as e:
            return _json({"error": str(e)})

    @mcp.tool(description=H.descripcion("metadatos"))
    def metadatos() -> str:
        return _correr("metadatos")

    @mcp.tool(description=H.descripcion("describir_tabla"))
    def describir_tabla(tabla: str) -> str:
        return _correr("describir_tabla", tabla=tabla)

    @mcp.tool(description=H.descripcion("buscar_pozo"))
    def buscar_pozo(texto: str, maximo: int = 20) -> str:
        return _correr("buscar_pozo", texto=texto, maximo=maximo)

    @mcp.tool(description=H.descripcion("ficha_pozo"))
    def ficha_pozo(sigla_clave: str) -> str:
        return _correr("ficha_pozo", sigla_clave=sigla_clave)

    @mcp.tool(description=H.descripcion("comparar_grupo"))
    def comparar_grupo(
        formacion: str,
        cohorte: int | None = None,
        dimension: str = "operadora",
        metrica: str = "ip90_petroleo_m3_d_por_m",
        n_min: int = H.N_MIN,
        incluye_outliers: bool = True,
        ventana: str | None = None,
    ) -> str:
        return _correr(
            "comparar_grupo",
            formacion=formacion,
            cohorte=cohorte,
            dimension=dimension,
            metrica=metrica,
            n_min=n_min,
            incluye_outliers=incluye_outliers,
            ventana=ventana,
        )

    @mcp.tool(description=H.descripcion("ranking"))
    def ranking(
        metrica: str = "ip90_petroleo_m3_d_por_m",
        filtros: dict | None = None,
        n_min: int = H.N_MIN,
        por: str = "operadora",
        orden: str = "desc",
        top: int = 10,
        incluye_outliers: bool = True,
    ) -> str:
        return _correr(
            "ranking",
            metrica=metrica,
            filtros=filtros or {},
            n_min=n_min,
            por=por,
            orden=orden,
            top=top,
            incluye_outliers=incluye_outliers,
        )

    @mcp.tool(description=H.descripcion("curva_tipo"))
    def curva_tipo(
        nivel: str,
        claves: dict,
        incluye_outliers: bool = True,
        tasa: str = "petroleo_m3_d",
        mes_max: int = 60,
    ) -> str:
        return _correr(
            "curva_tipo",
            nivel=nivel,
            claves=claves,
            incluye_outliers=incluye_outliers,
            tasa=tasa,
            mes_max=mes_max,
        )

    if con_sql:

        @mcp.tool(description=H.descripcion("sql_solo_lectura"))
        def sql_solo_lectura(sql: str, limite: int = H.SQL_LIMIT) -> str:
            return _correr("sql_solo_lectura", sql=sql, limite=limite)

    return mcp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mcp_server.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--fuente", default="auto", choices=["auto", "parquet", "json"])
    ap.add_argument("--datos", type=Path, default=ROOT)
    ap.add_argument("--sql", action="store_true", help="exponer sql_solo_lectura (ADR-025)")
    args = ap.parse_args(argv)
    d = D.abrir(args.datos, args.fuente)
    print(f"mcp vaca-muerta-abierta: {d.fuente} {d.ruta}, descargados {d.fecha_descarga}", file=sys.stderr)
    construir(d, args.sql).run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
