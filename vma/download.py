"""Dated, manifest-backed download of the raw CSVs.

Each run writes to ``data/raw/<YYYY-MM-DD>/<key>.csv`` and a ``manifest.json`` next to
the files with, per source: URL, bytes, SHA-256, download timestamp and the CKAN
``last_modified`` of the resource at that moment. Raw files are never versioned; the
manifest is what lets two runs be compared (which the brief calls the re-download
diff, a quality indicator of the public data itself).

Network access is isolated in ``open_url`` so tests can inject a fake opener.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO, Any

from .sources import CKAN_API, SOURCES, Source, default_keys

USER_AGENT = "vaca-muerta-abierta/0.0.1 (+https://github.com/LucasBurriel/vaca-muerta-abierta)"
CHUNK = 1 << 20

Opener = Callable[[str], IO[bytes]]


def open_url(url: str) -> IO[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=120)  # noqa: S310 - fixed https hosts


def raw_dir(root: Path, day: date | None = None) -> Path:
    return root / "data" / "raw" / (day or date.today()).isoformat()


def stream_to_file(resp: IO[bytes], dst: Path) -> tuple[int, str]:
    """Copy a response body to ``dst``; return (bytes, sha256 hex)."""
    h = hashlib.sha256()
    n = 0
    tmp = dst.with_suffix(dst.suffix + ".part")
    with tmp.open("wb") as f:
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
    tmp.replace(dst)
    return n, h.hexdigest()


def ckan_resource_meta(resource_id: str, opener: Opener = open_url) -> dict[str, Any] | None:
    """``resource_show`` for one resource; None when CKAN is unreachable."""
    try:
        with opener(f"{CKAN_API}/resource_show?id={resource_id}") as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001 - metadata is best effort
        return None
    if not data.get("success"):
        return None
    res = data["result"]
    return {
        "last_modified": res.get("last_modified"),
        "size": res.get("size"),
        "url": res.get("url"),
        "name": res.get("name"),
    }


def download_one(
    src: Source, dst_dir: Path, opener: Opener = open_url, log: Callable[[str], None] = print
) -> dict[str, Any]:
    dst = dst_dir / f"{src.key}.csv"
    meta = ckan_resource_meta(src.resource_id, opener)
    if meta and meta.get("url") and meta["url"].rsplit("/", 1)[-1] != src.filename:
        moved = meta["url"].rsplit("/", 1)[-1]
        log(f"  ! {src.key}: CKAN now names the file {moved!r}; using the catalogued URL anyway")
    log(f"  {src.key}: {src.url} (~{src.approx_mb} MB)")
    started = datetime.now(UTC)
    with opener(src.url) as resp:
        nbytes, sha = stream_to_file(resp, dst)
    return {
        "key": src.key,
        "family": src.family,
        "title": src.title,
        "dataset": src.dataset,
        "landing_page": src.landing_page,
        "url": src.url,
        "file": dst.name,
        "bytes": nbytes,
        "sha256": sha,
        "downloaded_at": started.isoformat(timespec="seconds"),
        "ckan_last_modified": (meta or {}).get("last_modified"),
        "ckan_size": (meta or {}).get("size"),
        "license": "CC-BY-4.0",
    }


def write_manifest(dst_dir: Path, entries: list[dict[str, Any]]) -> Path:
    path = dst_dir / "manifest.json"
    existing: dict[str, Any] = {}
    if path.exists():
        existing = {e["key"]: e for e in json.loads(path.read_text(encoding="utf-8"))["sources"]}
    for e in entries:
        existing[e["key"]] = e
    doc = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": sorted(existing.values(), key=lambda e: e["key"]),
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def download(
    root: Path,
    keys: list[str] | None = None,
    *,
    day: date | None = None,
    force: bool = False,
    opener: Opener = open_url,
    log: Callable[[str], None] = print,
) -> Path:
    """Download ``keys`` (default: all default sources) into ``data/raw/<day>/``.

    Returns the manifest path. Existing files for the same day are kept unless ``force``.
    """
    keys = keys or default_keys()
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        raise SystemExit(f"unknown source(s) {unknown}; options: {', '.join(SOURCES)}")
    dst_dir = raw_dir(root, day)
    dst_dir.mkdir(parents=True, exist_ok=True)
    log(f"-> {dst_dir}")
    entries = []
    for k in keys:
        src = SOURCES[k]
        if (dst_dir / f"{k}.csv").exists() and not force:
            log(f"  {k}: already present, skipping (use --force to re-download)")
            continue
        entries.append(download_one(src, dst_dir, opener, log))
    return write_manifest(dst_dir, entries)


def latest_raw_dir(root: Path) -> Path:
    base = root / "data" / "raw"
    days = sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []
    if not days:
        raise SystemExit("no raw data yet: run `python pipeline.py download`")
    return days[-1]


def read_manifest(root: Path) -> dict[str, Any]:
    path = latest_raw_dir(root) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def iter_manifest(root: Path) -> Iterator[dict[str, Any]]:
    yield from read_manifest(root)["sources"]


if __name__ == "__main__":  # pragma: no cover
    download(Path(__file__).resolve().parents[1], sys.argv[1:] or None)
