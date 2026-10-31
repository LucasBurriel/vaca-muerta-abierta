"""Normalisation of the three free-text identities in the public data: well sigla,
operator name and formation name.

The sigla is the human-readable well code (``YPF.Nq.LACh-1234(h)``). Every dataset
writes it a little differently (leading spaces, ``NQ``/``Nq``, dropped parentheses), so
``sigla_levels`` applies normalisations of increasing aggressiveness and phase 0 reports
how many more wells match at each level. Later phases pick one level and freeze it.

Operator and formation keys are *blocking keys* for alias tables (``alias/*.csv``): two
strings with the same key are candidates for the same entity, to be confirmed by a human.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_SUFFIX = re.compile(r"\(([a-z0-9]{1,3})\)\s*$", re.IGNORECASE)  # (h) (d) (hi) (re) ...
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_LEGAL = re.compile(
    r"\b(S\.?\s?A\.?|S\.?\s?R\.?\s?L\.?|S\.?\s?L\.?|S\.?\s?A\.?\s?U\.?|S\.?\s?A\.?\s?I\.?\s?C\.?|"
    r"SUCURSAL ARGENTINA|SUC\.? ARG\.?|ARGENTINA|LTD\.?|LLC|INC\.?|B\.?V\.?|SL)\b"
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# --- sigla -----------------------------------------------------------------------------


def sigla_l0(s: str) -> str:
    """Raw, as published."""
    return s


def sigla_l1(s: str) -> str:
    """Trim outer whitespace."""
    return s.strip()


def sigla_l2(s: str) -> str:
    """L1 + upper-case (``Nq`` vs ``NQ``) + collapse inner whitespace."""
    return _WS.sub(" ", sigla_l1(s)).upper()


def sigla_l3(s: str) -> str:
    """L2 + drop the trailing well-type suffix ``(h)``, ``(d)``, ``(hi)`` …"""
    return _SUFFIX.sub("", sigla_l2(s)).strip()


def sigla_l4(s: str) -> str:
    """L3 + keep only letters and digits (dots, hyphens, spaces removed)."""
    return _NON_ALNUM.sub("", sigla_l3(s))


SIGLA_LEVELS = {
    "L0 raw": sigla_l0,
    "L1 trim": sigla_l1,
    "L2 trim+upper": sigla_l2,
    "L3 +drop (h)/(d) suffix": sigla_l3,
    "L4 +alnum only": sigla_l4,
}


def sigla_levels(s: str) -> dict[str, str]:
    return {name: fn(s) for name, fn in SIGLA_LEVELS.items()}


def split_sigla(s: str) -> dict[str, str | None]:
    """Best-effort split of ``OPER.Prov.Area-Number(suffix)``. Returns None parts when the
    sigla does not follow the pattern; phase 0 only counts how often that happens."""
    s2 = sigla_l1(s)
    m = re.match(
        r"^([A-Za-z0-9]+)\.([A-Za-z]{1,4})\.([A-Za-z0-9]+)[.\-]?([A-Za-z]*)-?(\d+)(\([a-z0-9]+\))?$", s2
    )
    if not m:
        return {
            "operator": None,
            "province": None,
            "area": None,
            "type": None,
            "number": None,
            "suffix": None,
        }
    op, prov, area, typ, num, suf = m.groups()
    return {"operator": op, "province": prov, "area": area, "type": typ or None, "number": num, "suffix": suf}


# --- operator ---------------------------------------------------------------------------


def operator_key(name: str) -> str:
    """Blocking key: accents off, upper, legal forms and punctuation removed."""
    s = strip_accents(name).upper()
    s = s.replace("&", " Y ")
    s = re.sub(r"[.,\-()/]", " ", s)
    s = _LEGAL.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


# --- formation --------------------------------------------------------------------------

_FORMATION_PREFIX = re.compile(r"^(FM\.?|FORMACION|FORMACIÓN|FORM\.?|GRUPO|GR\.?)\s+")


def formation_key(name: str) -> str:
    """Blocking key: accents off, upper, 'Fm.'/'Formación' prefix removed, single spaces."""
    s = strip_accents(name).upper().strip()
    s = _FORMATION_PREFIX.sub("", s)
    s = re.sub(r"[.\-_/]", " ", s)
    s = _WS.sub(" ", s).strip()
    return s
