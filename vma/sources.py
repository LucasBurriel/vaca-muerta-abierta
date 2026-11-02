"""Catalogue of the public datasets this project downloads.

Everything here was read from the CKAN API of datos.energia.gob.ar on 2026-10-30
(``package_show`` on each dataset). Resource ids are stable in practice, but the
Secretaría re-uploads files from time to time, so ``pipeline.py download`` re-reads
the CKAN metadata and warns if a resource id or file name has moved.

All datasets are published by the Secretaría de Energía de la Nación Argentina under
CC-BY 4.0. See docs/fuentes.md for the human-readable version of this table.
"""

from __future__ import annotations

from dataclasses import dataclass

CKAN_API = "https://datos.energia.gob.ar/api/3/action"
DOWNLOAD_BASE = "https://datos.energia.gob.ar/dataset/{dataset_id}/resource/{resource_id}/download/{filename}"


FAMILIES = ("produccion", "pozos", "fractura", "perforacion", "reservas", "precios", "areas")


@dataclass(frozen=True)
class Source:
    key: str  # short name used for files on disk and table names
    family: str  # one of FAMILIES
    dataset: str  # CKAN package name
    dataset_id: str  # CKAN package uuid (part of the download URL)
    resource_id: str
    filename: str
    title: str
    approx_mb: float
    default: bool = True  # downloaded by ``pipeline.py download`` with no arguments
    formato: str = "csv"  # csv | zip-xlsx: what the portal serves (F5 catalogue, ADR-029)
    url_fija: str | None = None  # some resources live on energia.gob.ar, not under the CKAN download path
    grano: str = ""  # one line: the unit of one row, for docs and for the agent's metadatos

    @property
    def url(self) -> str:
        if self.url_fija:
            return self.url_fija
        return DOWNLOAD_BASE.format(
            dataset_id=self.dataset_id, resource_id=self.resource_id, filename=self.filename
        )

    @property
    def archivo_local(self) -> str:
        """File name under ``data/raw/<date>/``: the key plus the real extension."""
        ext = "zip" if self.formato.startswith("zip") else self.formato
        return f"{self.key}.{ext}"

    @property
    def landing_page(self) -> str:
        return f"https://datos.energia.gob.ar/dataset/{self.dataset}"


_PROD = ("produccion-de-petroleo-y-gas-por-pozo", "c846e79c-026c-4040-897f-1ad3543b407c")
_FRAC = ("datos-de-fractura-de-pozos-adjunto-iv", "71fa2e84-0316-4a1b-af68-7f35e41f58d7")
_PERF = ("perforacion-de-pozos-de-petroleo-y-gas", "7ea2ac77-d7a0-4129-9fbf-6f1a25d94e21")
_TRAY = ("trayectoria-de-pozos", "f5c0b5a5-b402-44d7-8fe0-f9e4fcb78b8d")
# F5 catalogue (read 2026-11-02, ADR-029): reserves, prices, royalties, production by field, concession polygons
_RESERVAS = ("reservas-de-petroleo-y-gas", "61c8fc78-540f-463b-aefb-ef854e6baed1")
_PRECIOS_GAS = ("precios-de-gas-natural", "5ddbdfbb-b6f9-4bc1-9e71-0055e86cf552")
_REGALIAS = (
    "regalias-de-petroleo-crudo-gas-natural-glp-gasolina-y-condensado",
    "91818b43-e6cd-43cb-916f-15987b87de69",
)
_SESCO = ("produccion-de-petroleo-y-gas-tablas-dinamicas", "590d1284-fd6d-4686-afd8-b3da5d90a6e9")
_CONCESIONES = ("produccion-hidrocarburos-concesiones-de-explotacion", "81cfad0a-4162-4f85-ad71-837f5a5fae57")
_ESTADISTICA = (
    "http://www.energia.gob.ar/contenidos/archivos/Reorganizacion/informacion_del_mercado/"
    "mercado_hidrocarburos/informacion_estadistica/"
)

SOURCES: dict[str, Source] = {
    s.key: s
    for s in [
        Source(
            "produccion_nc",
            "produccion",
            *_PROD,
            "b5b58cdc-9e07-41f9-b392-fb9ec68b0725",
            "produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv",
            "Producción de Pozos de Gas y Petróleo No Convencional",
            149,
        ),
        Source(
            "pozos",
            "pozos",
            *_PROD,
            "cb5c0f04-7835-45cd-b982-3e25ca7d7751",
            "capitulo-iv-pozos.csv",
            "Capítulo IV - Pozos",
            34,
        ),
        Source(
            "padron_pozos",
            "pozos",
            *_PROD,
            "5578dd48-d0dd-487e-8ddc-bd3ebb1afef0",
            "padrn-de-pozos-de-captulo-iv-con-fecha-de-primera-produccin.csv",
            "Padrón de Pozos de Capítulo IV con fecha de primera producción",
            1.2,
        ),
        Source(
            "listado_pozos_operadoras",
            "pozos",
            *_PROD,
            "cbfa4d79-ffb3-4096-bab5-eb0dde9a8385",
            "listado-de-pozos-cargados-por-empresas-operadoras.csv",
            "Listado de pozos cargados por empresas operadoras",
            27,
        ),
        Source(
            "fractura",
            "fractura",
            *_FRAC,
            "2280ad92-6ed3-403e-a095-50139863ab0d",
            "datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv",
            "Datos de fractura de pozos de hidrocarburos (Adjunto IV) - Actualización diaria",
            1.3,
        ),
        Source(
            "pozos_terminados",
            "perforacion",
            *_PERF,
            "a2ce14af-5c56-45c2-9b9c-c7a1e5156dff",
            "pozos-terminados.csv",
            "Pozos terminados",
            192,
        ),
        Source(
            "pozos_en_perforacion",
            "perforacion",
            *_PERF,
            "af6838ef-f675-4409-ac6a-e7c391a5dbab",
            "pozos-en-perforacin.csv",
            "Pozos en Perforación",
            68,
        ),
        Source(
            "metros_perforados",
            "perforacion",
            *_PERF,
            "712805f3-35d4-4825-93c6-98d03aeca203",
            "metros-perforados.csv",
            "Metros Perforados desde 2009",
            70,
            default=False,
        ),
        Source(
            "trayectorias_vm",
            "pozos",
            *_TRAY,
            "94741ac7-4f46-4efe-b112-d3f82a4ef7c5",
            "trayectorias-de-pozo-vaca-muerta.csv",
            "Trayectorias de Pozo Vaca Muerta",
            40,
            default=False,
        ),
        # --- F5 catalogue, all opt-in (ADR-029) -------------------------------------------------------------
        Source(
            "reservas",
            "reservas",
            *_RESERVAS,
            "4833d5e4-5d43-4387-80f1-982fbc89a300",
            "reservas_al_31-12-2025.zip",
            "Reservas al 31/12/2025 hasta el final de la vida útil de los yacimientos / fin de la concesión",
            0.3,
            default=False,
            formato="zip-xlsx",
            url_fija=_ESTADISTICA + "reservas/reservas_al_31-12-2025.zip",
            grano="operador × cuenca × provincia × concesión × yacimiento; P1/P2/P3 y recursos, conv. y no conv., petróleo Mm³ y gas MMm³",
        ),
        Source(
            "precios_gas",
            "precios",
            *_PRECIOS_GAS,
            "d87ca6ab-2979-474b-994a-e4ba259bb217",
            "precios-de-gas-natural-.csv",
            "Precios de Gas Natural - Res 1/2018 (desde enero 2019)",
            0.15,
            default=False,
            grano="cuenca × mes × tipo de contrato; precios USD/MMBTU por segmento (distribuidora, GNC, usina, industria, PPP, exportación)",
        ),
        Source(
            "regalias_crudo",
            "precios",
            *_REGALIAS,
            "a43e6f07-187e-4523-a4f7-d6457afd1d1e",
            "Regalias_CRUDO.zip",
            "Regalías de Petróleo Crudo (precios USD/m³, producción y regalías USD por provincia y mes)",
            1.3,
            default=False,
            formato="zip-xlsx",
            url_fija=_ESTADISTICA + "regalias/Regalias_CRUDO.zip",
            grano="provincia × mes desde 1991; precio promedio de venta USD/m³, producción computable y regalías USD; últimos dos meses provisorios",
        ),
        Source(
            "produccion_yacimiento_formacion",
            "produccion",
            *_SESCO,
            "2f2834f4-1981-448f-9a3c-1e519d8c10cd",
            "produccin-de-captulo-iv-agrupada-por-yacimiento-y-formacin-productiva.csv",
            "Producción de Capítulo IV agrupada por yacimiento y formación productiva",
            125,
            default=False,
            grano="empresa × yacimiento × formación × mes desde 2006, todas las cuencas y tipos de recurso; petróleo m³, gas mil m³, agua m³, tef",
        ),
        Source(
            "concesiones",
            "areas",
            *_CONCESIONES,
            "b6af0c0e-e463-4cb7-b458-373aafc0ac08",
            "produccin-hidrocarburos-concesiones-de-explotacin.csv",
            "Producción Hidrocarburos - Concesiones de Explotación (atributos; polígonos en el SHP hermano)",
            0.06,
            default=False,
            grano="una fila por concesión de explotación: área, código SESCO, operadora, informante, participación del consorcio",
        ),
    ]
}

# Conventional production is published as one 240-330 MB file per year (2006-2026).
# Out of scope for the first phases (basin: Neuquina, unconventional); documented in
# docs/fuentes.md. ``pipeline.py download --year 2024`` is deliberately not offered yet.


def default_keys() -> list[str]:
    return [k for k, s in SOURCES.items() if s.default]


def opt_in_keys() -> list[str]:
    return [k for k, s in SOURCES.items() if not s.default]
