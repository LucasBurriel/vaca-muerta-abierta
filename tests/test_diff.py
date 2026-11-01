"""Diff between two downloads on fixture folders; single-download case exits cleanly."""

import shutil
from pathlib import Path

from vma import diff as D


def _root(tmp_path: Path, fixtures_dir: Path, days=("2026-01-01", "2026-02-01")) -> Path:
    for d in days:
        shutil.copytree(fixtures_dir / "diff" / d, tmp_path / "data" / "raw" / d)
    return tmp_path


def test_single_download_says_so_and_exits_zero(tmp_path, fixtures_dir, capsys):
    root = _root(tmp_path, fixtures_dir, days=("2026-01-01",))
    assert D.run(root, None, None) == 0
    assert "only 1 download" in capsys.readouterr().out
    assert not (root / "informes").exists()


def test_no_download_at_all(tmp_path, capsys):
    assert D.run(tmp_path, None, None) == 0
    assert "nothing to compare" in capsys.readouterr().out


def test_diff_counts(tmp_path, fixtures_dir):
    root = _root(tmp_path, fixtures_dir)
    res = D.diff_downloads(root, "2026-01-01", "2026-02-01")
    s = res.summary()
    assert s["pozos: new idpozo in b"] == 1 and s["pozos: idpozo removed in b"] == 0
    assert s["pozos: operator changed"] == 1 and s["pozos: sigla changed"] == 0
    assert s["produccion_nc: new wells in b"] == 1
    assert s["produccion_nc: new well-months in b"] == 3
    assert s["produccion_nc: well-months rectified (volumes or days changed)"] == 1
    assert s["produccion_nc: of which flagged rectificado in b"] == 1
    assert s["fractura: new records in b"] == 1
    assert s["fractura: lateral length changed"] == 1
    assert s["fractura: lateral length filled in (0 -> > 0)"] == 1
    ops = res.sections["pozos: operator changes"]
    assert (
        ops.iloc[0].before == "VISTA OIL & GAS ARGENTINA SAU"
        and ops.iloc[0].after == "VISTA ENERGY ARGENTINA SAU"
    )
    bym = res.sections["produccion_nc: rectified well-months by month"]
    assert str(bym.iloc[0].month)[:7] == "2025-11" and bym.iloc[0].rectified == 1


def test_run_writes_report_with_default_last_two(tmp_path, fixtures_dir, capsys):
    root = _root(tmp_path, fixtures_dir)
    assert D.run(root, None, None) == 0
    out = root / "informes" / "diff-2026-01-01-2026-02-01.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# Download diff — 2026-01-01 → 2026-02-01" in text and "## produccion_nc" in text
    assert "report:" in capsys.readouterr().out


def test_missing_dataset_is_noted_not_fatal(tmp_path, fixtures_dir):
    root = _root(tmp_path, fixtures_dir)
    (root / "data" / "raw" / "2026-02-01" / "fractura.csv").unlink()
    res = D.diff_downloads(root, "2026-01-01", "2026-02-01")
    assert "fractura" not in res.sections and any("fractura" in n for n in res.notes)
    assert "- `fractura` missing" in D.render(res)
