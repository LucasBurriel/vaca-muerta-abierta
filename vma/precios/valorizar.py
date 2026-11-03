"""Monthly volumes -> US dollars: per month, cumulative and a simple NPV (F6, ADR-035).

Pure functions: no DuckDB, no I/O. The caller (``vma/consulta/herramientas.py``) brings the volume series and the
price series (:class:`SeriePrecio`, read from the published ``precios`` table) and gets a JSON-safe block back.

Three price modes:

- ``historico`` · the realised price of the calendar month of each volume (``mes0`` + k months) in the well's
  province (oil) or basin (gas). Months after the last published price take the last one and are counted; months
  before the first published price have no USD and are counted too.
- ``flat`` · one price per product chosen by the caller, in USD/m³ or USD/bbl for oil, USD per mil m³ or USD/MMBTU
  for gas (converted with ``vma/units.py``).
- ``ultimo`` · the last published price of each product in the region, held constant.

What comes out is **gross revenue** (volume × price): no capex, no opex, no transport, no taxes, and no royalties
unless ``regalia`` > 0, in which case that fraction of the gross is deducted (the Argentine base rate is 12 %;
provinces and concessions differ). The NPV discounts month k by ``(1 + tasa_anual) ** (-k / 12)``, month 0 undiscounted,
``tasa_anual`` 10 % by default. Every block carries these caveats in ``notas`` so a reader never mistakes it for
an economic evaluation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from vma import units

MODOS = ("historico", "flat", "ultimo")
TASA_ANUAL_DEFAULT = 0.10
REGALIA_SUGERIDA = 0.12
DIAS_MES = 365.25 / 12  # the simulation's month, vma/simulacion/declinacion.py

NOTA_BRUTO = (
    "ingreso BRUTO = volumen × precio: sin capex, sin opex, sin transporte, sin impuestos; sin regalías salvo "
    f"regalia > 0 (la alícuota base argentina es {REGALIA_SUGERIDA:.0%}, regalia={REGALIA_SUGERIDA}); no es una evaluación económica (ADR-035)"
)
NOTA_GAS = (
    f"gas: USD/MMBTU → USD/mil m³ con 9.300 kcal/m³ y 1 MMBTU = 252.000 kcal ({units.MMBTU_PER_THOUSAND_M3:.2f} MMBTU por mil m³); "
    "gas más rico vale más por m³ que esto (ADR-034)"
)


class ErrorValorizacion(ValueError):
    """The valuation cannot be done as asked; the message is for the model to read."""


@dataclass
class SeriePrecio:
    """A monthly price series for one product in one region, in the observatory's volume unit."""

    producto: str  # petroleo | gas
    region: str  # province or basin as the table spells it
    unidad: str  # "USD/m³" (oil) or "USD/mil m³" (gas)
    por_mes: dict[str, float] = field(default_factory=dict)  # "YYYY-MM" -> price
    fuente: str = ""  # regalias_crudo | precios_gas
    segmento: str | None = None
    contrato: str | None = None
    provisorios: set[str] = field(default_factory=set)  # months the source marks provisional
    notas: list[str] = field(default_factory=list)  # e.g. the region fallback

    @property
    def ultimo_mes(self) -> str | None:
        return max(self.por_mes) if self.por_mes else None

    @property
    def primer_mes(self) -> str | None:
        return min(self.por_mes) if self.por_mes else None

    @property
    def ultimo(self) -> float | None:
        return self.por_mes[self.ultimo_mes] if self.por_mes else None


# --- calendar -------------------------------------------------------------------------------------------------------


def mes_mas(mes0: str, k: int) -> str:
    """``"2024-03"`` + 11 -> ``"2025-02"``."""
    a, m = int(mes0[:4]), int(mes0[5:7])
    i = a * 12 + (m - 1) + int(k)
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def validar_mes(mes: str | None, nombre: str = "mes0") -> str | None:
    if mes is None:
        return None
    s = str(mes).strip()[:7]
    if len(s) != 7 or s[4] != "-" or not (s[:4].isdigit() and s[5:].isdigit()) or not 1 <= int(s[5:]) <= 12:
        raise ErrorValorizacion(f"{nombre} debe ser 'YYYY-MM'; recibí {mes!r}")
    return s


# --- flat prices ----------------------------------------------------------------------------------------------------


def precio_flat(precio_flat: dict | None) -> tuple[float | None, float | None, list[str]]:
    """``{petroleo_usd_m3 | petroleo_usd_bbl, gas_usd_mil_m3 | gas_usd_mmbtu}`` -> (USD/m³, USD/mil m³, notes)."""
    f = dict(precio_flat or {})
    extra = set(f) - {"petroleo_usd_m3", "petroleo_usd_bbl", "gas_usd_mil_m3", "gas_usd_mmbtu"}
    if extra:
        raise ErrorValorizacion(
            f"precio_flat: claves desconocidas {sorted(extra)}; usá petroleo_usd_m3 o petroleo_usd_bbl, gas_usd_mil_m3 o gas_usd_mmbtu"
        )
    notas = []
    petro = gas = None
    if f.get("petroleo_usd_m3") is not None:
        petro = float(f["petroleo_usd_m3"])
    elif f.get("petroleo_usd_bbl") is not None:
        petro = units.usd_per_bbl_to_usd_per_m3(float(f["petroleo_usd_bbl"]))
        notas.append(
            f"petróleo: {float(f['petroleo_usd_bbl']):g} USD/bbl = {petro:.2f} USD/m³ ({units.BBL_PER_M3:.4f} bbl/m³)"
        )
    if f.get("gas_usd_mil_m3") is not None:
        gas = float(f["gas_usd_mil_m3"])
    elif f.get("gas_usd_mmbtu") is not None:
        gas = units.usd_per_mmbtu_to_usd_per_thousand_m3(float(f["gas_usd_mmbtu"]))
        notas.append(f"gas: {float(f['gas_usd_mmbtu']):g} USD/MMBTU = {gas:.2f} USD/mil m³")
    for v, n in ((petro, "petróleo"), (gas, "gas")):
        if v is not None and (v < 0 or math.isnan(v)):
            raise ErrorValorizacion(f"precio_flat de {n} debe ser >= 0")
    return petro, gas, notas


# --- the valuation --------------------------------------------------------------------------------------------------


def _precio_del_mes(serie: SeriePrecio, mes: str) -> tuple[float | None, str]:
    """(price, how): ``mes`` | ``ultimo`` (after the last published) | ``sin_precio`` (before the first or a gap)."""
    if mes in serie.por_mes:
        return serie.por_mes[mes], "mes"
    if serie.ultimo_mes is not None and mes > serie.ultimo_mes:
        return serie.ultimo, "ultimo"
    return None, "sin_precio"


def valorizar(
    petroleo_m3: Sequence[float | None] | None,
    gas_mil_m3: Sequence[float | None] | None,
    *,
    modo: str = "ultimo",
    precio_petroleo: SeriePrecio | None = None,
    precio_gas: SeriePrecio | None = None,
    mes0: str | None = None,
    flat: dict | None = None,
    tasa_anual: float = TASA_ANUAL_DEFAULT,
    regalia: float = 0.0,
    compacto: bool = False,
) -> dict:
    """Value two aligned monthly volume series (month 0 first; either may be None or shorter).

    Returns ``{modo, mes0, tasa_anual, regalia, precios: {petroleo, gas}, por_mes | series, total, notas}``.
    ``compacto`` gives parallel lists (``mes``, ``ingreso_usd``, ``acumulado_usd``…) instead of one dict per month,
    for long bands (simulations).
    """
    if modo not in MODOS:
        raise ErrorValorizacion(f"modo debe ser uno de {', '.join(MODOS)}; recibí {modo!r}")
    if not (0 <= float(regalia) < 1):
        raise ErrorValorizacion("regalia debe ser una fracción en [0, 1), p. ej. 0.12")
    if float(tasa_anual) <= -1:
        raise ErrorValorizacion("tasa_anual debe ser > -1 (fracción anual, p. ej. 0.10)")
    mes0 = validar_mes(mes0)
    petro = list(petroleo_m3 or [])
    gas = list(gas_mil_m3 or [])
    n = max(len(petro), len(gas))
    if n == 0:
        raise ErrorValorizacion("no hay volúmenes que valorizar")
    petro += [None] * (n - len(petro))
    gas += [None] * (n - len(gas))
    hay_petro = any(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in petro)
    hay_gas = any(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in gas)

    notas = [NOTA_BRUTO]
    flat_p = flat_g = None
    if modo == "flat":
        flat_p, flat_g, n_flat = precio_flat(flat)
        notas += n_flat
        if hay_petro and flat_p is None:
            raise ErrorValorizacion("modo flat: falta precio_flat.petroleo_usd_m3 (o petroleo_usd_bbl)")
        if hay_gas and flat_g is None:
            raise ErrorValorizacion("modo flat: falta precio_flat.gas_usd_mil_m3 (o gas_usd_mmbtu)")
    else:
        if hay_petro and (precio_petroleo is None or not precio_petroleo.por_mes):
            raise ErrorValorizacion(
                "no hay serie de precio de petróleo para la región pedida (tabla precios)"
            )
        if hay_gas and (precio_gas is None or not precio_gas.por_mes):
            raise ErrorValorizacion("no hay serie de precio de gas para la cuenca pedida (tabla precios)")
        if modo == "historico" and mes0 is None:
            raise ErrorValorizacion("modo historico necesita mes0 ('YYYY-MM'): el mes calendario del mes 0")
    if hay_gas:
        notas.append(NOTA_GAS)
    for s in (precio_petroleo, precio_gas):
        if s is not None and modo != "flat":
            notas += s.notas

    def precio(
        k: int, serie: SeriePrecio | None, flat_v: float | None, hay: bool
    ) -> tuple[float | None, str]:
        if not hay:
            return None, "sin_volumen"
        if modo == "flat":
            return flat_v, "flat"
        assert serie is not None
        if modo == "ultimo":
            return serie.ultimo, "ultimo"
        return _precio_del_mes(serie, mes_mas(mes0, k))  # type: ignore[arg-type]

    filas = []
    acum = 0.0
    van = 0.0
    tot_p = tot_g = tot_reg = 0.0
    sin_precio = con_ultimo = provisorios = 0
    usados_p: list[float] = []
    usados_g: list[float] = []
    for k in range(n):
        cal = mes_mas(mes0, k) if mes0 else None
        vp = petro[k]
        vg = gas[k]
        vp = None if vp is None or (isinstance(vp, float) and math.isnan(vp)) else float(vp)
        vg = None if vg is None or (isinstance(vg, float) and math.isnan(vg)) else float(vg)
        pp, como_p = precio(k, precio_petroleo, flat_p, hay_petro)
        pg, como_g = precio(k, precio_gas, flat_g, hay_gas)
        falta = (vp is not None and pp is None) or (vg is not None and pg is None)
        if falta:
            sin_precio += 1
        if "ultimo" in (como_p, como_g) and modo == "historico":
            con_ultimo += 1
        if (
            modo == "historico"
            and cal
            and (
                (precio_petroleo and cal in precio_petroleo.provisorios)
                or (precio_gas and cal in precio_gas.provisorios)
            )
        ):
            provisorios += 1
        usd_p = vp * pp if (vp is not None and pp is not None) else None
        usd_g = vg * pg if (vg is not None and pg is not None) else None
        if pp is not None and vp is not None:
            usados_p.append(pp)
        if pg is not None and vg is not None:
            usados_g.append(pg)
        bruto = (usd_p or 0.0) + (usd_g or 0.0) if not falta else None
        reg = bruto * float(regalia) if bruto is not None else None
        ingreso = bruto - reg if bruto is not None else None
        if ingreso is not None:
            acum += ingreso
            factor = (1.0 + float(tasa_anual)) ** (-k / 12.0)
            desc = ingreso * factor
            van += desc
            tot_p += usd_p or 0.0
            tot_g += usd_g or 0.0
            tot_reg += reg or 0.0
        else:
            desc = None
        filas.append(
            {
                "mes": k,
                "mes_calendario": cal,
                "petroleo_m3": vp,
                "gas_mil_m3": vg,
                "precio_petroleo_usd_m3": pp if vp is not None else None,
                "precio_gas_usd_mil_m3": pg if vg is not None else None,
                "petroleo_usd": usd_p,
                "gas_usd": usd_g,
                "bruto_usd": bruto,
                "regalia_usd": reg,
                "ingreso_usd": ingreso,
                "acumulado_usd": acum if ingreso is not None else None,
                "descontado_usd": desc,
            }
        )

    def resumen(
        serie: SeriePrecio | None, flat_v: float | None, usados: list[float], hay: bool, unidad: str
    ) -> dict | None:
        if not hay:
            return None
        r: dict = {"unidad": unidad}
        if modo == "flat":
            r.update({"modo": "flat", "precio": flat_v})
            return r
        assert serie is not None
        r.update(
            {
                "modo": modo,
                "region": serie.region,
                "fuente": serie.fuente,
                "segmento": serie.segmento,
                "contrato": serie.contrato,
                "ultimo_mes_publicado": serie.ultimo_mes,
                "ultimo_precio": serie.ultimo,
            }
        )
        if modo == "historico" and usados:
            r.update({"min": min(usados), "max": max(usados), "promedio_usado": sum(usados) / len(usados)})
        return r

    if sin_precio:
        notas.append(
            f"{sin_precio} mes(es) sin precio publicado (anteriores al primer mes de la serie o con hueco): sin USD, no suman al acumulado ni al VAN"
        )
    if con_ultimo:
        notas.append(
            f"{con_ultimo} mes(es) posteriores al último precio publicado: se usó el último precio, constante"
        )
    if provisorios:
        notas.append(
            f"{provisorios} mes(es) valorizados con precio provisorio (los dos últimos períodos de la fuente)"
        )
    if modo == "ultimo":
        notas.append(
            "modo ultimo: el último precio publicado, constante en toda la serie (sin inflación ni curva forward)"
        )
    notas.append(
        f"VAN: suma de ingreso_usd × (1 + {float(tasa_anual):g})^(-mes/12), mes 0 sin descontar; tasa anual {float(tasa_anual):.1%}"
    )
    total = {
        "meses": n,
        "meses_sin_precio": sin_precio,
        "meses_con_ultimo_precio": con_ultimo,
        "petroleo_usd": tot_p if hay_petro else None,
        "gas_usd": tot_g if hay_gas else None,
        "bruto_usd": tot_p + tot_g,
        "regalia_usd": tot_reg,
        "ingreso_usd": acum,
        "van_usd": van,
    }
    out: dict = {
        "modo": modo,
        "mes0": mes0,
        "tasa_anual": float(tasa_anual),
        "regalia": float(regalia),
        "precios": {
            "petroleo": resumen(precio_petroleo, flat_p, usados_p, hay_petro, "USD/m³"),
            "gas": resumen(precio_gas, flat_g, usados_g, hay_gas, "USD/mil m³"),
        },
        "total": total,
        "notas": notas,
    }
    if compacto:
        out["series"] = {
            "mes": [f["mes"] for f in filas],
            "mes_calendario": [f["mes_calendario"] for f in filas] if mes0 else None,
            "ingreso_usd": [f["ingreso_usd"] for f in filas],
            "acumulado_usd": [f["acumulado_usd"] for f in filas],
        }
    else:
        out["por_mes"] = filas
    return out


def volumenes_desde_tasas(
    tasas: Sequence[float | None], uptime: float = 0.92, dias_mes: float = DIAS_MES
) -> list[float | None]:
    """Producing-day rates (m³/d or mil m³/d per month) -> monthly volumes: rate × 30.44 d × uptime."""
    return [
        None if q is None or (isinstance(q, float) and math.isnan(q)) else float(q) * dias_mes * float(uptime)
        for q in tasas
    ]


def volumenes_desde_acumulado(acum: Sequence[float | None]) -> list[float | None]:
    """A cumulative series -> the volume of each month (first month = first cumulative)."""
    out: list[float | None] = []
    prev = 0.0
    for a in acum:
        if a is None or (isinstance(a, float) and math.isnan(a)):
            out.append(None)
            continue
        out.append(max(float(a) - prev, 0.0))
        prev = float(a)
    return out


__all__ = [
    "DIAS_MES",
    "MODOS",
    "NOTA_BRUTO",
    "NOTA_GAS",
    "REGALIA_SUGERIDA",
    "TASA_ANUAL_DEFAULT",
    "ErrorValorizacion",
    "SeriePrecio",
    "mes_mas",
    "precio_flat",
    "validar_mes",
    "valorizar",
    "volumenes_desde_acumulado",
    "volumenes_desde_tasas",
]
