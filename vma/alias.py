"""Versioned alias tables: ``alias/siglas.csv``, ``alias/operadoras.csv``, ``alias/formaciones.csv``.

All three share one layout::

    variante, canonico, fuente, desde, nota

``variante`` is a spelling as published, ``canonico`` the name the observatory uses,
``fuente`` where the variant was seen (dataset keys, ``;``-separated), ``desde`` the date
the row entered the table (ISO) and ``nota`` the human reason when the mapping is not a
trivial spelling difference (a rename, a merger). Rows are never deleted: the table is
the history of every identity decision, and ``git log`` is its audit trail.

Operators and formations are curated by hand (phase 0 produced the drafts, phase 1
resolved them, ADR-012). Siglas are maintained by code: ``update_siglas`` appends the
spellings that the master build sees for the first time and keeps the existing rows
untouched, so ``desde`` stays the first date each variant was observed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .normalize import formation_key, operator_key, sigla_l2

COLUMNS = ["variante", "canonico", "fuente", "desde", "nota"]


@dataclass
class AliasTable:
    """One alias CSV in memory. ``exact`` maps the trimmed variant to its canonical name;
    ``by_key`` maps a blocking key to a canonical name for case/accents-insensitive hits."""

    path: Path
    rows: list[dict[str, str]] = field(default_factory=list)
    exact: dict[str, str] = field(default_factory=dict)
    by_key: dict[str, str] = field(default_factory=dict)
    version: str = ""

    def resolve(self, name: str | None, key_fn) -> tuple[str | None, str]:
        """Return ``(canonical, how)`` where ``how`` is ``exact`` | ``key`` | ``missing``.
        A missing name is returned trimmed, never dropped: the master flags it."""
        if name is None or not str(name).strip():
            return None, "null"
        n = str(name).strip()
        if n in self.exact:
            return self.exact[n], "exact"
        k = key_fn(n)
        if k in self.by_key:
            return self.by_key[k], "key"
        return n, "missing"


def read_alias(path: Path, key_fn) -> AliasTable:
    t = AliasTable(path=path)
    if not path.exists():
        return t
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            # ``variante`` keeps its raw spelling (leading/trailing blanks are the point for siglas)
            r = {c: (r.get(c) or "") if c == "variante" else (r.get(c) or "").strip() for c in COLUMNS}
            t.rows.append(r)
            t.exact[r["variante"]] = r["canonico"]
            t.exact.setdefault(r["variante"].strip(), r["canonico"])
            t.by_key.setdefault(key_fn(r["variante"]), r["canonico"])
            if r["desde"] > t.version:
                t.version = r["desde"]
    return t


def write_alias(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


@dataclass
class Aliases:
    operadoras: AliasTable
    formaciones: AliasTable
    siglas: AliasTable

    @property
    def version(self) -> str:
        return max(self.operadoras.version, self.formaciones.version, self.siglas.version)

    def operadora(self, name: str | None) -> tuple[str | None, str]:
        return self.operadoras.resolve(name, operator_key)

    def formacion(self, name: str | None) -> tuple[str | None, str]:
        return self.formaciones.resolve(name, formation_key)


def load_aliases(alias_dir: Path) -> Aliases:
    return Aliases(
        operadoras=read_alias(alias_dir / "operadoras.csv", operator_key),
        formaciones=read_alias(alias_dir / "formaciones.csv", formation_key),
        siglas=read_alias(alias_dir / "siglas.csv", sigla_l2),
    )


def update_siglas(
    table: AliasTable, variants: list[tuple[str, str, str]], today: date
) -> tuple[list[dict[str, str]], int]:
    """Append sigla spellings not yet in the table. ``variants`` are
    ``(variante, canonico, fuente)`` for every raw spelling that differs from the published
    spelling of its well (the register's, trimmed). Returns the full row list and how many
    rows were added."""
    rows = list(table.rows)
    seen = {r["variante"] for r in rows}
    added = 0
    for variante, canonico, fuente in sorted(set(variants)):
        if variante in seen or variante == canonico:
            continue
        rows.append(
            {
                "variante": variante,
                "canonico": canonico,
                "fuente": fuente,
                "desde": today.isoformat(),
                "nota": "grafia distinta en la fuente (mayusculas); misma clave L2",
            }
        )
        seen.add(variante)
        added += 1
    return rows, added
