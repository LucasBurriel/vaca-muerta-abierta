"""The minimum schema of the user's data and its validation (docs/mis-datos.md).

Two logical tables, which may come as one file (well attributes repeated on every monthly row) or as two:

- **produccion**: one row per well × month. Required: ``sigla``, a month (``fecha`` as YYYY-MM or YYYY-MM-DD, or
  ``anio`` + ``mes``), ``petroleo_m3``, ``gas_mil_m3``. Optional: ``agua_m3``, ``tef`` (producing days; without it
  the whole month counts, said in the notes).
- **pozos**: one row per well. All optional: ``formacion``, ``rama_m``, ``etapas``, ``arena_tn``,
  ``agua_fractura_m3``, ``longitud``, ``latitud``, ``campania``, ``ventana``.

Units are the portal's (docs/fuentes.md#units-as-published): oil and water in m³/month, gas in thousands of
m³/month, lengths in m, proppant in t. Column names are mapped by alias (case-insensitive, accents ignored) or by
an explicit ``mapeo`` ``{canonical: your column}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from vma.normalize import strip_accents

PRODUCCION_REQUERIDAS = ("sigla", "petroleo_m3", "gas_mil_m3")  # plus a month: fecha or anio + mes
PRODUCCION_OPCIONALES = ("agua_m3", "tef")
POZOS_OPCIONALES = (
    "formacion",
    "rama_m",
    "etapas",
    "arena_tn",
    "agua_fractura_m3",
    "longitud",
    "latitud",
    "campania",
    "ventana",
    "operadora",
)
TIEMPO = ("fecha", "anio", "mes")
CANONICAS = PRODUCCION_REQUERIDAS + TIEMPO + PRODUCCION_OPCIONALES + POZOS_OPCIONALES

# aliases the loader recognises without a mapping; keys normalised with ``_clave``
ALIAS: dict[str, tuple[str, ...]] = {
    "sigla": ("sigla", "pozo", "well", "well_name", "nombre_pozo", "sigla_pozo", "uwi"),
    "fecha": ("fecha", "mes_fecha", "periodo", "period", "date", "fecha_data"),
    "anio": ("anio", "ano", "year", "anyo"),
    "mes": ("mes", "month"),
    "petroleo_m3": ("petroleo_m3", "prod_pet", "petroleo", "oil_m3", "oil", "crudo_m3", "pet_m3"),
    "gas_mil_m3": ("gas_mil_m3", "prod_gas", "gas", "gas_km3", "gas_mm3", "gas_miles_m3"),
    "agua_m3": ("agua_m3", "prod_agua", "agua", "water_m3", "water"),
    "tef": ("tef", "dias", "dias_produccion", "dias_efectivos", "days_on", "dias_tef", "tiempo_efectivo"),
    "rama_m": ("rama_m", "rama", "longitud_rama_horizontal_m", "lateral_m", "rama_lateral_m", "lateral"),
    "etapas": ("etapas", "cantidad_fracturas", "stages", "n_etapas", "etapas_fractura"),
    "arena_tn": ("arena_tn", "arena", "arena_bombeada_tn", "proppant_t", "proppant_tn", "arena_total_tn"),
    "agua_fractura_m3": ("agua_fractura_m3", "agua_inyectada_m3", "agua_fractura", "frac_water_m3"),
    "formacion": ("formacion", "formation", "fm", "formacion_productiva"),
    "longitud": ("longitud", "lon", "lng", "x", "coordenadax", "longitude"),
    "latitud": ("latitud", "lat", "y", "coordenaday", "latitude"),
    "campania": ("campania", "campana", "pad", "campaign", "proyecto", "lote"),
    "ventana": ("ventana", "fluido", "window", "ventana_fluido"),
    "operadora": ("operadora", "empresa", "operator", "company"),
}
VENTANAS = ("petroleo", "volatil_condensado", "gas")


def _clave(nombre: str) -> str:
    return strip_accents(str(nombre)).strip().lower().replace(" ", "_").replace("-", "_")


def resolver_mapeo(columnas: list[str], mapeo: dict[str, str] | None = None) -> dict[str, str]:
    """``{canonical: column in the file}`` for every canonical column found, explicit ``mapeo`` first."""
    por_clave = {_clave(c): c for c in columnas}
    out: dict[str, str] = {}
    for canon, propia in (mapeo or {}).items():
        if canon not in CANONICAS:
            raise ValueError(
                f"mapeo: {canon!r} no es una columna canónica; las canónicas son {', '.join(CANONICAS)}"
            )
        if propia not in columnas:
            raise ValueError(
                f"mapeo: la columna {propia!r} (para {canon}) no está en el archivo; hay {', '.join(columnas)}"
            )
        out[canon] = propia
    for canon, alias in ALIAS.items():
        if canon in out:
            continue
        for a in alias:
            if a in por_clave and por_clave[a] not in out.values():
                out[canon] = por_clave[a]
                break
    return out


@dataclass
class Validacion:
    ok: bool
    errores: list[str] = field(default_factory=list)  # the file cannot be used
    avisos: list[str] = field(default_factory=list)  # usable, with a caveat the tools repeat in ``notas``
    mapeo: dict[str, str] = field(default_factory=dict)

    def mensaje(self) -> str:
        if self.ok:
            return "ok" + (f"; avisos: {'; '.join(self.avisos)}" if self.avisos else "")
        return "archivo inválido: " + "; ".join(self.errores)


def validar_columnas(columnas: list[str], mapeo: dict[str, str] | None = None) -> Validacion:
    """Can this set of columns be read as the user's production table? Errors say what is missing and how to map."""
    m = resolver_mapeo(columnas, mapeo)
    errores, avisos = [], []
    for c in PRODUCCION_REQUERIDAS:
        if c not in m:
            errores.append(
                f"falta la columna {c!r} (alias aceptados: {', '.join(ALIAS[c])}); si tiene otro nombre pasá mapeo={{'{c}': 'tu_columna'}}"
            )
    if "fecha" not in m and not ("anio" in m and "mes" in m):
        errores.append("falta el mes: una columna 'fecha' (YYYY-MM o YYYY-MM-DD) o el par 'anio' + 'mes'")
    if "tef" not in m:
        avisos.append(
            "sin 'tef' (días efectivos): cada mes cuenta sus días calendario, las tasas por día efectivo quedan subestimadas si el pozo paró"
        )
    if "agua_m3" not in m:
        avisos.append("sin 'agua_m3': corte de agua no computable")
    if "rama_m" not in m:
        avisos.append("sin 'rama_m': nada por metro, la comparación por metro queda sin dato")
    if "formacion" not in m:
        avisos.append(
            "sin 'formacion': se asume Vaca Muerta para elegir la curva tipo; pasá la columna si no es así"
        )
    return Validacion(ok=not errores, errores=errores, avisos=avisos, mapeo=m)


def validar_valores(prod: pd.DataFrame) -> Validacion:
    """Row-level checks on the normalised production table (canonical columns already)."""
    errores, avisos = [], []
    if prod.empty:
        errores.append("el archivo no tiene filas")
        return Validacion(ok=False, errores=errores)
    if prod.sigla.isna().any() or (prod.sigla.astype(str).str.strip() == "").any():
        errores.append("hay filas sin sigla")
    if prod.mes_fecha.isna().any():
        n = int(prod.mes_fecha.isna().sum())
        errores.append(f"{n} fila(s) con fecha ilegible: se espera YYYY-MM, YYYY-MM-DD o anio + mes")
    for c in ("petroleo_m3", "gas_mil_m3", "agua_m3"):
        if c in prod and (prod[c] < 0).any():
            avisos.append(
                f"{int((prod[c] < 0).sum())} fila(s) con {c} negativo: se conservan y se marcan (volumen_negativo)"
            )
    dup = prod.duplicated(["sigla", "mes_fecha"]).sum()
    if dup:
        avisos.append(f"{int(dup)} fila(s) repetidas pozo × mes: se suman (como el portal con varios idpozo)")
    if "tef" in prod and prod.tef.notna().any() and (prod.tef > prod.dias_mes).any():
        avisos.append(
            "hay meses con tef mayor que los días del mes: se topan a los días del mes (tef_mayor_mes)"
        )
    if prod.sigla.nunique() > 5000:
        avisos.append("más de 5000 pozos: las herramientas cortan las listas a 50 filas, filtrá por campaña")
    return Validacion(ok=not errores, errores=errores, avisos=avisos)
