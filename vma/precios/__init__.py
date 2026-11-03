"""F6: public prices and the valuation in US dollars (ADR-034, ADR-035).

Two opt-in sources of the portal (``vma/sources.py``) become one published table, ``precios``:

- ``regalias_crudo`` · *Informe Regalías CRUDO.xlsx* inside a ZIP: the **average realised sale price of crude in
  USD/m³ by province and month** (sheet ``Tabla precios``), plus the royalty-computable production in m³ (``Tabla
  producción``) and the royalties paid in USD (``Tabla regalías``). Monthly since 1991; the last two months are
  provisional (the sheet says so).
- ``precios_gas`` · CSV, Res. 1/2018: **USD/MMBTU by basin, month and contract type** (firme / interrumpible /
  total) for seven segments (distribuidora, GNC, usina, industria, otros, PPP, exportación), since 2019-01.

The table has one row per ``producto × region × mes × segmento × contrato``; ``precio_dataset`` is the number as
published in ``unidad_dataset``, and ``precio_usd_m3`` / ``precio_usd_mil_m3`` are the same price in the units the
observatory stores volumes in (oil m³, gas mil m³). The gas conversion assumes the published volumes are at the
Argentine reference of 9,300 kcal/m³ and 1 MMBTU = 252,000 kcal (``vma/units.py``); richer gas would be worth more
per m³ than this says, so the notes say so.

``valorizar.py`` is the pure function that turns a monthly volume series into USD per month, cumulative and a
simple NPV, with three price modes; ``fuentes.py`` holds the parsers, the table builder and the pipeline stage.
Nothing here is an economic evaluation: gross revenue, no royalties unless asked, no capex, no opex, no taxes.
"""

from __future__ import annotations

from vma.normalize import strip_accents

TABLA = "precios"
DOC = "docs/precios.md"

PRODUCTOS = ("petroleo", "gas")
SEGMENTO_PETROLEO = "promedio_venta"
SEGMENTOS_GAS = ("distribuidora", "gnc", "usina", "industria", "otros", "ppp", "expo")
CONTRATOS_GAS = ("firme", "interrumpible", "total")

# Defaults the valuation uses when the caller does not choose (ADR-035): the Neuquén realised crude price (Medanito
# is the Neuquina reference crude, says the workbook) and the Neuquina weighted-average gas price over every segment.
REGION_PETROLEO_DEFAULT = "Neuquén"
REGION_GAS_DEFAULT = "Neuquina"
SEGMENTO_GAS_DEFAULT = "ppp"
CONTRATO_GAS_DEFAULT = "total"

# Dataset header -> canonical spelling of the province (oil) or basin (gas).
PROVINCIAS = {
    "CHUBUT": "Chubut",
    "ESTADO NACIONAL": "Estado Nacional",
    "FORMOSA": "Formosa",
    "JUJUY": "Jujuy",
    "LA PAMPA": "La Pampa",
    "MENDOZA": "Mendoza",
    "NEUQUEN": "Neuquén",
    "RIO NEGRO": "Río Negro",
    "SALTA": "Salta",
    "SANTA CRUZ": "Santa Cruz",
    "TIERRA DEL FUEGO": "Tierra del Fuego",
    "TOTAL PROVINCIA": "Total Provincia",
}
CUENCAS_GAS = (
    "Austral Santa Cruz",
    "Austral Tierra del Fuego",
    "Golfo de San Jorge",
    "Neuquina",
    "Noroeste",
    "Total Cuenca",
)


def clave_region(s: str | None) -> str:
    """Loose key of a province or basin name: accents off, upper case, single spaces."""
    if s is None:
        return ""
    return " ".join(strip_accents(str(s)).upper().replace("+", " ").split())


def provincia_canonica(nombre: str | None) -> str | None:
    """The table's spelling of a province given any spelling (``NEUQUEN``, ``Neuquén``, ``rio negro``)."""
    k = clave_region(nombre)
    if not k:
        return None
    return PROVINCIAS.get(k) or next((v for v in PROVINCIAS.values() if clave_region(v) == k), None)


def cuenca_gas_canonica(cuenca: str | None, provincia: str | None = None) -> str | None:
    """The gas dataset's basin for a well's ``cuenca`` (master spelling: NEUQUINA, GOLFO SAN JORGE, AUSTRAL,
    NOROESTE); the Austral basin is split by province in the dataset, so the province decides."""
    k = clave_region(cuenca)
    if not k:
        return None
    if k.startswith("NEUQUIN"):
        return "Neuquina"
    if "SAN JORGE" in k:
        return "Golfo de San Jorge"
    if k.startswith("AUSTRAL"):
        if "FUEGO" in k or "FUEGO" in clave_region(provincia):
            return "Austral Tierra del Fuego"
        return "Austral Santa Cruz"
    if k.startswith("NOROESTE") or k.startswith("NORTE"):
        return "Noroeste"
    if k == "TOTAL CUENCA" or k == "TOTAL":
        return "Total Cuenca"
    return next((c for c in CUENCAS_GAS if clave_region(c) == k), None)


__all__ = [
    "CONTRATOS_GAS",
    "CONTRATO_GAS_DEFAULT",
    "CUENCAS_GAS",
    "DOC",
    "PRODUCTOS",
    "PROVINCIAS",
    "REGION_GAS_DEFAULT",
    "REGION_PETROLEO_DEFAULT",
    "SEGMENTOS_GAS",
    "SEGMENTO_GAS_DEFAULT",
    "SEGMENTO_PETROLEO",
    "TABLA",
    "clave_region",
    "cuenca_gas_canonica",
    "provincia_canonica",
]
