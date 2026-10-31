import hashlib
import json
from datetime import date

import pytest
from conftest import fake_opener_factory

from vma import download as dl
from vma.sources import SOURCES, default_keys


def test_sources_catalogue_is_consistent():
    for s in SOURCES.values():
        assert s.url.startswith("https://datos.energia.gob.ar/dataset/")
        assert s.url.endswith(s.filename)
        assert s.family in {"produccion", "pozos", "fractura", "perforacion"}
    assert "produccion_nc" in default_keys()
    assert "metros_perforados" not in default_keys()  # opt-in


def test_download_writes_files_and_manifest(tmp_path, fixtures_dir):
    body = (fixtures_dir / "produccion_nc.csv").read_bytes()
    src = SOURCES["produccion_nc"]
    opener = fake_opener_factory(
        {src.url: body},
        ckan={src.resource_id: {"last_modified": "2026-10-22T21:00:55", "size": len(body), "url": src.url}},
    )
    logs = []
    manifest = dl.download(
        tmp_path, ["produccion_nc"], day=date(2026, 10, 30), opener=opener, log=logs.append
    )

    out = tmp_path / "data" / "raw" / "2026-10-30" / "produccion_nc.csv"
    assert out.read_bytes() == body
    assert not out.with_suffix(".csv.part").exists()
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    (entry,) = doc["sources"]
    assert entry["key"] == "produccion_nc"
    assert entry["bytes"] == len(body)
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["ckan_last_modified"] == "2026-10-22T21:00:55"
    assert entry["license"] == "CC-BY-4.0"
    assert entry["url"] == src.url


def test_download_skips_existing_unless_force(tmp_path, fixtures_dir):
    body = (fixtures_dir / "fractura.csv").read_bytes()
    src = SOURCES["fractura"]
    opener = fake_opener_factory({src.url: body})
    day = date(2026, 10, 30)
    dl.download(tmp_path, ["fractura"], day=day, opener=opener, log=lambda _: None)
    n_calls = len(opener.calls)
    dl.download(tmp_path, ["fractura"], day=day, opener=opener, log=lambda _: None)
    assert len(opener.calls) == n_calls  # nothing fetched the second time
    dl.download(tmp_path, ["fractura"], day=day, force=True, opener=opener, log=lambda _: None)
    assert len(opener.calls) > n_calls


def test_manifest_merges_across_runs(tmp_path, fixtures_dir):
    files = {
        SOURCES["fractura"].url: (fixtures_dir / "fractura.csv").read_bytes(),
        SOURCES["produccion_nc"].url: (fixtures_dir / "produccion_nc.csv").read_bytes(),
    }
    opener = fake_opener_factory(files)
    day = date(2026, 10, 30)
    dl.download(tmp_path, ["fractura"], day=day, opener=opener, log=lambda _: None)
    path = dl.download(tmp_path, ["produccion_nc"], day=day, opener=opener, log=lambda _: None)
    keys = [e["key"] for e in json.loads(path.read_text(encoding="utf-8"))["sources"]]
    assert keys == ["fractura", "produccion_nc"]
    assert dl.latest_raw_dir(tmp_path).name == "2026-10-30"


def test_ckan_failure_is_not_fatal(tmp_path, fixtures_dir):
    body = (fixtures_dir / "fractura.csv").read_bytes()
    src = SOURCES["fractura"]
    inner = fake_opener_factory({src.url: body})

    def opener(url):
        if "resource_show" in url:
            raise OSError("ckan down")
        return inner(url)

    path = dl.download(tmp_path, ["fractura"], day=date(2026, 1, 1), opener=opener, log=lambda _: None)
    (entry,) = json.loads(path.read_text(encoding="utf-8"))["sources"]
    assert entry["ckan_last_modified"] is None
    assert entry["bytes"] == len(body)


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        dl.download(tmp_path, ["nope"], opener=lambda u: None, log=lambda _: None)
