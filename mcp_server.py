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

    # --- F5: the user's own wells (ADR-030); data stays in this process ---------------------------------------

    @mcp.tool(description=H.descripcion("cargar_mis_pozos"))
    def cargar_mis_pozos(ruta: str, mapeo: dict | None = None, ruta_pozos: str | None = None) -> str:
        return _correr("cargar_mis_pozos", ruta=ruta, mapeo=mapeo, ruta_pozos=ruta_pozos)

    @mcp.tool(description=H.descripcion("comparar_mi_pozo"))
    def comparar_mi_pozo(
        sigla: str,
        tasa: str = "petroleo_m3_d",
        cohorte_ref: int | None = None,
        incluye_outliers: bool = True,
        mes_max: int = 36,
    ) -> str:
        return _correr(
            "comparar_mi_pozo",
            sigla=sigla,
            tasa=tasa,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
            mes_max=mes_max,
        )

    @mcp.tool(description=H.descripcion("comparar_mi_campania"))
    def comparar_mi_campania(
        filtros: dict | None = None,
        metrica: str = "ip90_petroleo_m3_d_por_m",
        cohorte_ref: int | None = None,
        incluye_outliers: bool = True,
    ) -> str:
        return _correr(
            "comparar_mi_campania",
            filtros=filtros or {},
            metrica=metrica,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
        )

    @mcp.tool(description=H.descripcion("brechas"))
    def brechas(
        sigla: str | None = None,
        filtros: dict | None = None,
        tasa: str = "petroleo_m3_d",
        cohorte_ref: int | None = None,
        incluye_outliers: bool = True,
        mes_max: int = 24,
    ) -> str:
        return _correr(
            "brechas",
            sigla=sigla,
            filtros=filtros,
            tasa=tasa,
            cohorte_ref=cohorte_ref,
            incluye_outliers=incluye_outliers,
            mes_max=mes_max,
        )

    # --- F5: decline fits and campaign Monte Carlo (ADR-031) ------------------------------------------------------

    @mcp.tool(description=H.descripcion("pronosticar_pozo"))
    def pronosticar_pozo(
        sigla: str,
        mio: bool = False,
        tasa: str = "petroleo_m3_d",
        modelo: str = "auto",
        horizonte_anios: int = 20,
        omitir_meses: int = 2,
        n_bootstrap: int = 200,
        d_min_anual: float = 0.06,
        q_min: float | None = None,
        uptime: float | None = None,
    ) -> str:
        return _correr(
            "pronosticar_pozo",
            sigla=sigla,
            mio=mio,
            tasa=tasa,
            modelo=modelo,
            horizonte_anios=horizonte_anios,
            omitir_meses=omitir_meses,
            n_bootstrap=n_bootstrap,
            d_min_anual=d_min_anual,
            q_min=q_min,
            uptime=uptime,
        )

    @mcp.tool(description=H.descripcion("pronosticar_curva_tipo"))
    def pronosticar_curva_tipo(
        nivel: str,
        claves: dict,
        tasa: str = "petroleo_m3_d",
        modelo: str = "auto",
        horizonte_anios: int = 20,
        incluye_outliers: bool = True,
        omitir_meses: int = 2,
        d_min_anual: float = 0.06,
        uptime: float = 0.92,
        q_min: float | None = None,
    ) -> str:
        return _correr(
            "pronosticar_curva_tipo",
            nivel=nivel,
            claves=claves,
            tasa=tasa,
            modelo=modelo,
            horizonte_anios=horizonte_anios,
            incluye_outliers=incluye_outliers,
            omitir_meses=omitir_meses,
            d_min_anual=d_min_anual,
            uptime=uptime,
            q_min=q_min,
        )

    @mcp.tool(description=H.descripcion("simular_campania"))
    def simular_campania(
        formacion: str,
        n_pozos: int,
        meses: int = 120,
        ventana: str | None = None,
        cohorte_ref: int | None = None,
        rama_m: float | None = None,
        ritmo_pozos_por_mes: int | None = None,
        tasa: str = "petroleo_m3_d",
        n_sim: int = 500,
        semilla: int = 0,
        uptime: float = 0.92,
        incluye_outliers: bool = True,
    ) -> str:
        return _correr(
            "simular_campania",
            formacion=formacion,
            n_pozos=n_pozos,
            meses=meses,
            ventana=ventana,
            cohorte_ref=cohorte_ref,
            rama_m=rama_m,
            ritmo_pozos_por_mes=ritmo_pozos_por_mes,
            tasa=tasa,
            n_sim=n_sim,
            semilla=semilla,
            uptime=uptime,
            incluye_outliers=incluye_outliers,
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
