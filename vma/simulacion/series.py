"""Monthly series a forecast can be fitted on: the user's wells (session views) or a public well (raw CSV).

The published tables carry no per-well monthly series (ADR-022), so a public well's history comes from the raw
``produccion_nc.csv`` of the latest download, summed over the well's ``idpozo`` exactly as ``vma/indicadores.py``
does. That needs a Parquet source (the master's ``idpozos``) and the raw file on disk; the first call loads the
needed columns into the session connection once (a few seconds), later calls are instant. On a fresh clone (JSON
only) the tool says what is missing and points to ``pronosticar_curva_tipo``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from vma import units
from vma.consulta.datos import Datos
from vma.normalize import sigla_l2

COLUMNAS = ["mes", "mes_fecha", "dias_mes", "tef_d", "petroleo_m3", "gas_mil_m3", "agua_m3", "equivalente_m3"]


class SinSerie(ValueError):
    """No monthly series for that well; the message says why and what to do."""


def _raw_csv(d: Datos) -> Path | None:
    if d.fuente != "parquet":
        return None
    root = Path(d.ruta).resolve().parents[2]  # data/publicado/<date> -> repo root
    base = root / "data" / "raw"
    if not base.exists():
        return None
    dias = sorted(p for p in base.iterdir() if p.is_dir() and (p / "produccion_nc.csv").exists())
    return dias[-1] / "produccion_nc.csv" if dias else None


def _asegurar_raw(d: Datos) -> None:
    if d.con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = '_prod_raw'").fetchone()[0]:
        return
    csv = _raw_csv(d)
    if csv is None:
        raise SinSerie(
            "la serie mensual de un pozo público no está en las tablas publicadas (ADR-022) y no encuentro "
            "data/raw/<fecha>/produccion_nc.csv con fuente parquet; corré `python pipeline.py download master "
            "indicadores curvas` o usá pronosticar_curva_tipo sobre la curva de su grupo"
        )
    d.con.execute(
        "CREATE TABLE _prod_raw AS SELECT idpozo, anio, mes, prod_pet, prod_gas, prod_agua, tef "
        f"FROM read_csv_auto('{csv.as_posix()}', sample_size=200000)"
    )


def serie_publica(d: Datos, sigla_clave: str) -> tuple[pd.DataFrame, dict]:
    """Monthly producing-day series of a public well (month 0 = first month with oil or gas > 0)."""
    clave = sigla_l2(sigla_clave or "")
    if not d.tiene("pozos", "idpozos"):
        raise SinSerie(
            "la fuente json no trae pozos.idpozos; hace falta la fuente parquet para armar la serie"
        )
    fila = d.filas(
        "SELECT sigla, sigla_clave, idpozos, formacion_principal, operadora, rama_m, primera_produccion FROM pozos WHERE sigla_clave = ?",
        [clave],
    )
    if not fila:
        raise SinSerie(f"sigla_clave {clave!r} no está en pozos; usá buscar_pozo primero")
    _asegurar_raw(d)
    ids = [int(x) for x in str(fila[0]["idpozos"] or "").split("|") if x.strip().isdigit()]
    if not ids:
        raise SinSerie(f"{clave}: el maestro no tiene idpozos para este pozo (sin producción publicada)")
    marcas = ",".join("?" * len(ids))
    g = d.df(
        f"SELECT make_date(anio, mes, 1) AS mes_fecha, sum(prod_pet) AS petroleo_m3, sum(prod_gas) AS gas_mil_m3, "
        f"sum(prod_agua) AS agua_m3, max(tef) AS tef FROM _prod_raw WHERE idpozo IN ({marcas}) GROUP BY 1 ORDER BY 1",
        ids,
    )
    if g.empty:
        raise SinSerie(f"{clave}: sin filas de producción en el crudo para idpozos {ids}")
    g["mes_fecha"] = pd.to_datetime(g.mes_fecha)
    g["dias_mes"] = g.mes_fecha.dt.days_in_month.astype(float)
    produce = (g.petroleo_m3 > 0) | (g.gas_mil_m3 > 0)
    first = g.loc[produce, "mes_fecha"].min()
    g["mes"] = (g.mes_fecha.dt.year - first.year) * 12 + (g.mes_fecha.dt.month - first.month)
    tef = pd.to_numeric(g.tef, errors="coerce").fillna(0.0).clip(lower=0.0)
    g["tef_d"] = tef.where(~((tef == 0) & produce), g.dias_mes).clip(upper=g.dias_mes)
    g["equivalente_m3"] = g.petroleo_m3 + g.gas_mil_m3.map(units.gas_thousand_m3_to_m3_oil_eq)
    g = g[g.mes >= 0]
    meta = {
        "sigla": fila[0]["sigla"],
        "sigla_clave": clave,
        "formacion": fila[0]["formacion_principal"],
        "operadora": fila[0]["operadora"],
        "rama_m": fila[0]["rama_m"],
        "idpozos": ids,
        "origen": "data/raw produccion_nc.csv, suma de idpozo por mes (docs/indicadores.md)",
    }
    return g[COLUMNAS].reset_index(drop=True), meta


def serie_mia(d: Datos, sigla: str) -> tuple[pd.DataFrame, dict]:
    if d.propios is None:
        raise SinSerie("no hay datos propios cargados: llamá cargar_mis_pozos(ruta) primero")
    mis = d.propios
    clave = sigla_l2(sigla or "")
    ind = mis.indicadores
    hit = ind[(ind.sigla == clave) | (ind.sigla_original.astype(str).map(sigla_l2) == clave)]
    if hit.empty:
        raise SinSerie(f"{sigla!r} no está entre mis pozos cargados ({len(ind)} pozos)")
    pozo = hit.iloc[0]
    g = mis.produccion[
        (mis.produccion.sigla == pozo.sigla) & mis.produccion.k.notna() & (mis.produccion.k >= 0)
    ].copy()
    g["mes"] = g.k.astype(int)
    meta = {
        "sigla": pozo.sigla,
        "sigla_clave": pozo.sigla,
        "formacion": pozo.get("formacion"),
        "operadora": pozo.get("operadora"),
        "rama_m": None if pd.isna(pozo.get("rama_m")) else float(pozo.rama_m),
        "origen": "mis_produccion (sesión)",
        "sintetico": bool(mis.meta.get("sintetico")),
    }
    return g[COLUMNAS].reset_index(drop=True), meta
