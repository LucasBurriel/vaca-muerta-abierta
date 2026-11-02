"""Ask the published tables a question in natural language (F4).

python agente.py "¿Qué operadora tiene la mejor mediana de IP90 por metro en Vaca Muerta, ventana de petróleo, cohorte 2024?"
python agente.py --chat                       multi-turn
python agente.py --proveedor mock "..."       no model, no key: scripted planner over the same tools (tests, CI)
python agente.py --fuente json "..."          force the committed site/data/ snapshot (default: Parquet if built)
python agente.py --sql "..."                  also expose sql_solo_lectura (opt-in, read-only, allowlisted; ADR-025)
python agente.py --json "..."                 print the transcript as JSON (question, tools, validation, answer)

Needs ANTHROPIC_API_KEY (or a `claude`/`ant` login the SDK can read) for the real model; without it, falls back to
the mock and says so. Every number in the answer is checked against the tool results (ADR-027).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vma.consulta import agente as A
from vma.consulta import datos as D
from vma.consulta import ubicacion as U

ROOT = Path(__file__).resolve().parent


def _mostrar_llamada(ll: A.Llamada) -> None:
    args = json.dumps(ll.entrada, ensure_ascii=False)
    estado = "error" if ll.error else f"{ll.segundos * 1000:.0f} ms"
    print(f"  -> {ll.herramienta}({args})  [{estado}]", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="agente.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("pregunta", nargs="?", help="la pregunta; sin ella, --chat")
    ap.add_argument("--chat", action="store_true", help="modo conversación (Ctrl-D o 'salir' para terminar)")
    ap.add_argument(
        "--proveedor",
        default="auto",
        choices=["auto", "anthropic", "mock", "mock-sin-cita"],
        help="auto = anthropic si hay ANTHROPIC_API_KEY, si no mock",
    )
    ap.add_argument("--modelo", default=A.MODELO_DEFAULT)
    ap.add_argument(
        "--esfuerzo", default=A.ESFUERZO_DEFAULT, choices=["low", "medium", "high", "xhigh", "max"]
    )
    ap.add_argument("--fuente", default="auto", choices=["auto", "parquet", "json"])
    ap.add_argument(
        "--datos",
        type=Path,
        default=None,
        help=f"raíz con site/data o data/publicado (default: el clon, ${U.ENV}, o el snapshot en {U.cache_dir()})",
    )
    ap.add_argument(
        "--sql", action="store_true", help="exponer sql_solo_lectura (riesgo documentado, ADR-025)"
    )
    ap.add_argument("--json", action="store_true", help="imprimir el transcript como JSON")
    ap.add_argument("--silencioso", action="store_true", help="no mostrar las llamadas a herramientas")
    args = ap.parse_args(argv)
    for stream in (
        sys.stdout,
        sys.stderr,
    ):  # Windows consoles default to cp1252; the answers carry m³ and accents
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if not args.pregunta and not args.chat:
        ap.error("falta la pregunta (o --chat)")
    d = D.abrir(U.raiz_datos(args.datos, ROOT), args.fuente)
    proveedor = A.elegir_proveedor(args.proveedor, args.modelo, args.esfuerzo)
    if not args.json:
        print(
            f"datos: {d.fuente} ({d.ruta}), descargados {d.fecha_descarga}, maestro {d.version_maestro}; "
            f"proveedor {proveedor.nombre} {proveedor.modelo}",
            file=sys.stderr,
        )
    al_llamar = None if (args.silencioso or args.json) else _mostrar_llamada

    def una(pregunta: str, historial: list[dict] | None) -> int:
        r = A.responder(pregunta, d, proveedor, con_sql=args.sql, historial=historial, al_llamar=al_llamar)
        if args.json:
            print(json.dumps(r.transcript(), ensure_ascii=False, indent=1))
        else:
            print()
            print(r.texto)
            if r.validacion is not None and not args.silencioso:
                print(
                    f"\n[validador: {r.validacion.mensaje()[:120]}; turnos {r.turnos}, reintentos {r.reintentos}]",
                    file=sys.stderr,
                )
        return 0 if (r.validacion is None or r.validacion.ok) else 2

    if args.pregunta and not args.chat:
        return una(args.pregunta, None)
    historial: list[dict] = []
    if args.pregunta:
        una(args.pregunta, historial)
    print("chat: escribí la pregunta; 'salir' o Ctrl-D para terminar", file=sys.stderr)
    while True:
        try:
            q = input("\nvos> ").strip()
        except EOFError:
            break
        if not q:
            continue
        if q.lower() in ("salir", "exit", "quit"):
            break
        una(q, historial)
    return 0


if __name__ == "__main__":
    sys.exit(main())
