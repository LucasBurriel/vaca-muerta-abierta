"""Sin cita no hay número (ADR-027): every number in an answer must appear in a tool result of that turn.

The check is lightweight and deliberately dumb: it extracts the numbers the model wrote (Spanish and English
formats, thousands separators, percentages, ISO dates) and looks for each one among the numbers any tool
returned during the turn, with a tolerance for rounding. A number that comes from nowhere is a *número sin
cita*; the agent then asks the model to redo the answer once, and if it still fails the answer is shown with a
warning instead of being silently trusted.

What is allowed without a citation: numbers that appear in the question or in the arguments the model passed to
the tools (it is restating the filter), small integers up to :data:`ENTERO_LIBRE` (ordinals, "los 3 grupos"),
and numbers glued to a word (``IP90``, ``ADR-016``, ``P50``, ``acum12``, ``L2``), which are identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ENTERO_LIBRE = 10  # integers 0..10 need no citation: ordinals, counts of listed items, "dos de tres"

_FECHA = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
# a number: digits with optional . or , groups; not glued to a letter, underscore or another digit/separator
_NUMERO = re.compile(r"(?<![A-Za-z0-9_.,])(?<![A-Za-z]-)[-+]?\d+(?:[.,]\d+)*(?![A-Za-z0-9_])")


@dataclass
class Validacion:
    ok: bool
    sin_cita: list[str] = field(default_factory=list)  # the tokens as written
    n_numeros: int = 0
    n_referencia: int = 0

    def mensaje(self) -> str:
        if self.ok:
            return "ok: todos los números de la respuesta salen de una herramienta"
        return (
            "número sin cita: "
            + ", ".join(self.sin_cita)
            + ". Ningún resultado de herramienta de este turno "
            "contiene esos valores. Reescribí la respuesta usando sólo valores devueltos por las herramientas "
            "(podés volver a consultar), o decí que el dato no está."
        )


# --- number extraction -----------------------------------------------------------------------------------------


def _candidatos(token: str) -> list[float]:
    """Numeric readings of a written token. ``1.206`` may be 1206 (es) or 1.206 (en): both are returned."""
    t = token.replace(" ", "")
    signo = -1.0 if t.startswith("-") else 1.0
    t = t.lstrip("+-")
    if "," in t and "." in t:
        # the last separator is the decimal one; the other groups thousands
        dec = max(t.rfind(","), t.rfind("."))
        entero = re.sub(r"[.,]", "", t[:dec])
        return [signo * float(f"{entero}.{t[dec + 1 :]}")]
    sep = "," if "," in t else "." if "." in t else None
    if sep is None:
        return [signo * float(t)]
    partes = t.split(sep)
    if len(partes) > 2:  # 1.234.567
        return [signo * float("".join(partes))]
    ent, frac = partes
    lecturas = [signo * float(f"{ent}.{frac}")]
    if len(frac) == 3 and ent != "0" and len(ent) <= 3:  # 1.206 / 1,206: also a thousands group
        lecturas.append(signo * float(ent + frac))
    return lecturas


def numeros_en_texto(texto: str) -> list[tuple[str, list[float]]]:
    """``[(token as written, candidate values), ...]`` for every number in ``texto`` (dates removed first)."""
    sin_fechas = _FECHA.sub(" ", texto)
    out = []
    for m in _NUMERO.finditer(sin_fechas):
        tok = m.group(0)
        try:
            out.append((tok, _candidatos(tok)))
        except ValueError:
            continue
    return out


def fechas_en_texto(texto: str) -> list[str]:
    return _FECHA.findall(texto)


# --- the reference set ----------------------------------------------------------------------------------------


def _recorrer(obj: Any, numeros: set[float], textos: set[str]) -> None:
    if obj is None or isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        numeros.add(float(obj))
        return
    if isinstance(obj, str):
        textos.add(obj)
        for _tok, cands in numeros_en_texto(obj):
            numeros.update(cands)
        for f in fechas_en_texto(obj):
            textos.add(f)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            textos.add(str(k))
            _recorrer(v, numeros, textos)
        return
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            _recorrer(v, numeros, textos)


def referencia(resultados: list[Any], extra_textos: list[str] | None = None) -> tuple[set[float], set[str]]:
    """Every number and every string found in the tool results (and in extra texts: the question, tool inputs)."""
    numeros: set[float] = set()
    textos: set[str] = set()
    for r in resultados:
        _recorrer(r, numeros, textos)
    for t in extra_textos or []:
        _recorrer(t, numeros, textos)
    # a fraction may be quoted as a percentage
    numeros |= {round(x * 100, 6) for x in list(numeros) if 0 < abs(x) <= 1}
    return numeros, textos


# --- matching -------------------------------------------------------------------------------------------------


def _decimales(token: str) -> int:
    t = token.replace(" ", "")
    if "," in t and "." in t:
        return len(t) - max(t.rfind(","), t.rfind(".")) - 1
    sep = "," if "," in t else "." if "." in t else None
    if sep is None or t.count(sep) > 1:
        return 0
    return len(t.split(sep)[1])


def _cifras_significativas(token: str) -> int:
    digitos = re.sub(r"[^0-9]", "", token).lstrip("0")
    return max(1, len(digitos))


def coincide(valor: float, token: str, numeros: set[float]) -> bool:
    """``valor`` (one reading of ``token``) matches some reference number up to the rounding the token shows:
    the same number of significant digits, or half a unit of its last decimal."""
    if valor in numeros:
        return True
    d = _decimales(token)
    k = _cifras_significativas(token)
    abs_tol = 0.5 * 10 ** (-d) + 1e-9
    for n in numeros:
        if abs(n - valor) <= abs_tol:
            return True
        if n != 0 and float(f"{n:.{k}g}") == valor:
            return True
    return False


def validar(respuesta: str, resultados: list[Any], permitidos: list[str] | None = None) -> Validacion:
    """Check ``respuesta`` against the tool ``resultados`` of the turn.

    ``permitidos``: texts whose numbers need no citation (the user's question, the tool inputs the model chose).
    """
    numeros, textos = referencia(resultados, permitidos)
    sin_cita: list[str] = []
    n = 0
    for fecha in fechas_en_texto(respuesta):
        n += 1
        if not any(fecha in t for t in textos):
            sin_cita.append(fecha)
    for tok, cands in numeros_en_texto(respuesta):
        n += 1
        if all(c.is_integer() and 0 <= c <= ENTERO_LIBRE for c in cands):
            continue
        if any(coincide(c, tok, numeros) for c in cands):
            continue
        sin_cita.append(tok)
    return Validacion(ok=not sin_cita, sin_cita=sin_cita, n_numeros=n, n_referencia=len(numeros))
