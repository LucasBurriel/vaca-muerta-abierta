"""Command-line entry point. One subcommand per stage; each stage is a module in vma/.

python pipeline.py sources                       list catalogued sources
python pipeline.py download [key ...] [--force]  raw CSVs -> data/raw/<date>/ + manifest.json
python pipeline.py schema                        real schema of each dataset -> docs/esquemas/
python pipeline.py quality                       informes/calidad-<date>.md + docs/*.png
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

    args = ap.parse_args(argv)
    if args.cmd == "sources":
        from vma.sources import SOURCES

        for s in SOURCES.values():
            flag = "" if s.default else "  (opt-in)"
            print(f"{s.key:26} {s.family:12} ~{s.approx_mb:>6} MB  {s.title}{flag}")
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
