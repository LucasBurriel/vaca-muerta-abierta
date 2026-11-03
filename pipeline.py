"""Command-line entry point. One subcommand per stage; each stage is a module in vma/.

python pipeline.py sources                       list catalogued sources
python pipeline.py download [key ...] [--force]  raw CSVs -> data/raw/<date>/ + manifest.json
python pipeline.py schema                        real schema of each dataset -> docs/esquemas/
python pipeline.py quality                       informes/calidad-<date>.md + docs/*.png
python pipeline.py master                        data/publicado/<date>/pozos.{csv,parquet} + informes/maestro-<date>.md
python pipeline.py diff [--a DATE --b DATE]      informes/diff-<a>-<b>.md between two downloads (default: last two)
python pipeline.py indicadores                   data/publicado/<date>/indicadores.{csv,parquet} (per-well indicators)
python pipeline.py curvas                        data/publicado/<date>/curvas_tipo.{csv,parquet} + informes/indicadores-<date>.md
python pipeline.py site                          site/data/*.json for the static site (from the latest published tables)
python pipeline.py precios                       data/publicado/<date>/precios.{csv,parquet} + site/data/precios.json (F6; needs
                                                 `download regalias_crudo precios_gas` first)
python pipeline.py sintetico [--n 30] [--semilla 7] [--salida DIR]   synthetic "my wells" dataset from public wells + noise (F5)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download the raw CSVs into data/raw/<date>/ with a manifest")
    d.add_argument("keys", nargs="*", help="source keys (default: all default sources)")
    d.add_argument("--force", action="store_true")
    d.add_argument("--day", type=date.fromisoformat, default=None, help="folder date (default: today)")

    sub.add_parser("sources", help="list catalogued sources")
    sub.add_parser("schema", help="dump the real schema of every downloaded dataset")
    sub.add_parser("quality", help="build the data-quality report with charts")
    m = sub.add_parser("master", help="build and publish the well master (one row per physical well)")
    m.add_argument("--day", type=date.fromisoformat, default=None, help="publication date (default: today)")
    i = sub.add_parser(
        "indicadores", help="per-well indicators with lineage from the latest master + raw production"
    )
    i.add_argument("--day", type=date.fromisoformat, default=None, help="publication date (default: today)")
    c = sub.add_parser(
        "curvas", help="type curves by cohort (with and without outliers) + the F2 report with charts"
    )
    c.add_argument("--day", type=date.fromisoformat, default=None, help="publication date (default: today)")
    st = sub.add_parser("site", help="pre-aggregated JSON for the static site -> site/data/")
    st.add_argument("--day", type=date.fromisoformat, default=None, help="generation date (default: today)")
    pr = sub.add_parser(
        "precios",
        help="public prices (crude USD/m³ by province, gas USD/MMBTU by basin) -> precios table + site snapshot (ADR-034)",
    )
    pr.add_argument(
        "--day",
        type=date.fromisoformat,
        default=None,
        help="publication folder (default: the newest data/publicado/<date>/ with the core tables, else today)",
    )
    pr.add_argument("--sin-site", action="store_true", help="do not rewrite site/data/precios.json")
    sn = sub.add_parser(
        "sintetico", help="synthetic 'mis pozos' dataset from public wells with noise (ADR-030)"
    )
    sn.add_argument("--n", type=int, default=30, help="wells to derive (20-50 is the documented range)")
    sn.add_argument("--semilla", type=int, default=7)
    sn.add_argument("--salida", type=Path, default=None, help="folder (default: data/sintetico/<date>/)")
    df_ = sub.add_parser("diff", help="differences between two dated downloads in data/raw/")
    df_.add_argument("--a", default=None, help="earlier download folder (YYYY-MM-DD)")
    df_.add_argument("--b", default=None, help="later download folder (YYYY-MM-DD)")

    args = ap.parse_args(argv)
    if args.cmd == "sources":
        from vma.sources import SOURCES

        for s in SOURCES.values():
            flag = "" if s.default else "  (opt-in)"
            fmt = "" if s.formato == "csv" else f" [{s.formato}]"
            print(f"{s.key:32} {s.family:12} ~{s.approx_mb:>6} MB  {s.title}{flag}{fmt}")
        return 0
    if args.cmd == "download":
        from vma.download import download

        path = download(ROOT, args.keys or None, day=args.day, force=args.force)
        print(f"manifest: {path}")
        return 0
    if args.cmd == "schema":
        from vma.schema import dump_schemas

        dump_schemas(ROOT)
        return 0
    if args.cmd == "quality":
        from vma.quality import build_report

        print(build_report(ROOT))
        return 0
    if args.cmd == "master":
        from vma.master import run

        run(ROOT, today=args.day)
        return 0
    if args.cmd == "indicadores":
        from vma.indicadores import run

        run(ROOT, today=args.day)
        return 0
    if args.cmd == "curvas":
        from vma.curvas import run

        run(ROOT, today=args.day)
        return 0
    if args.cmd == "site":
        from vma.site import run

        run(ROOT, today=args.day)
        return 0
    if args.cmd == "precios":
        from vma.precios.fuentes import run

        run(ROOT, today=args.day, salida_site=not args.sin_site)
        return 0
    if args.cmd == "sintetico":
        from vma.propios.sintetico import run

        run(ROOT, n=args.n, semilla=args.semilla, salida=args.salida)
        return 0
    if args.cmd == "diff":
        from vma.diff import run

        return run(ROOT, args.a, args.b)
    return 1


if __name__ == "__main__":
    sys.exit(main())
