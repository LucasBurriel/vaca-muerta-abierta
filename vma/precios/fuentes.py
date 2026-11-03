"""Parsers of the two price sources and the published ``precios`` table (F6, ADR-034).

    python pipeline.py download regalias_crudo precios_gas   # raw files, dated, hashed (vma/download.py)
    python pipeline.py precios                               # -> data/publicado/<date>/precios.{csv,parquet} + site/data/precios.json

**regalias_crudo** is a ZIP with one workbook, *Informe Regalías CRUDO.xlsx*, whose three ``Tabla …`` sheets are
pivot tables with the same shape: a header row ``AÑO | MES | <province> … | TOTAL PROVINCIA`` (its position moves
between sheets, so it is found by content, not by row number), then one row per month with the year filled only on
January. Cells are 0 where there is nothing to report (months not yet reported, provinces without production), so
0 is read as *no price*, never as a price. Row 1 carries the realisation date, row 2 says the last two periods are
provisional. The fourth sheet lists the crude types per basin (Medanito = Neuquina); it is documented, not loaded.

**precios_gas** is a tidy CSV: ``anio, mes, cuenca, contrato, precio_<segmento> × 7, indice_tiempo, fecha``; 0.00
means no sales in that segment and basin that month and is dropped.

The table is published whole as Parquet/CSV next to the other tables; the site snapshot (``site/data/precios.json``,
the only thing a fresh clone has) keeps the oil series from 2006 (the first Capítulo IV production) and, for gas,
the ``total`` contract only, which is what the valuation reads (ADR-023 applies the same way: the subset is
declared in ``describir_tabla``).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from vma import units
from vma.precios import (
    CONTRATOS_GAS,
    PROVINCIAS,
    SEGMENTO_PETROLEO,
    SEGMENTOS_GAS,
    clave_region,
)

COLUMNAS = [
    "producto",  # petroleo | gas
    "region",  # province (oil) or basin (gas), canonical spelling
    "tipo_region",  # provincia | cuenca
    "anio",
    "mes",
    "mes_fecha",  # first day of the month
    "fuente",  # regalias_crudo | precios_gas (vma/sources.py key)
    "segmento",  # oil: promedio_venta; gas: distribuidora, gnc, usina, industria, otros, ppp, expo
    "contrato",  # gas: firme | interrumpible | total; oil: null
    "unidad_dataset",  # USD/m³ | USD/MMBTU
    "precio_dataset",  # as published
    "precio_usd_m3",  # oil: = precio_dataset; gas: per m³ at 9,300 kcal/m³
    "precio_usd_mil_m3",  # oil: ×1000; gas: per mil m³ (the unit volumes are stored in)
    "provisorio",  # oil: the last two reported months, says the workbook
    "produccion_m3",  # oil only: royalty-computable production of the province that month
    "regalias_usd",  # oil only: royalties paid
    "fecha_realizacion",  # oil only: row 1 of the workbook
    "fecha_descarga",
    "version",  # publication folder date
]
SNAPSHOT_DESDE = 2006  # the site's JSON keeps oil prices from this year on (first Capítulo IV production)
HOJAS = {"precios": "Tabla precios", "produccion": "Tabla producción", "regalias": "Tabla regalías"}


class ErrorFuente(ValueError):
    """The raw file does not have the layout documented in docs/precios.md."""


# --- regalias_crudo (ZIP -> XLSX) ------------------------------------------------------------------------------------


def _abrir_libro(origen: Path | bytes):
    import warnings

    import openpyxl

    raw = origen if isinstance(origen, bytes) else Path(origen).read_bytes()
    if raw[:2] == b"PK" and not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ErrorFuente("regalias_crudo: el archivo no es un ZIP ni un XLSX")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xlsx = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
        if xlsx:  # the portal's ZIP with the workbook inside
            raw = z.read(xlsx[0])
        elif "xl/workbook.xml" not in z.namelist():
            raise ErrorFuente(f"regalias_crudo: el ZIP no trae un .xlsx ({z.namelist()[:5]})")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl warns about the slicer extension of the pivot sheets
        return openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)


def _hoja(libro, nombre: str):
    k = clave_region(nombre)
    for n in libro.sheetnames:
        if clave_region(n) == k:
            return libro[n]
    raise ErrorFuente(f"regalias_crudo: falta la hoja {nombre!r}; hojas: {libro.sheetnames}")


def _leer_pivot(ws, valor: str) -> pd.DataFrame:
    """One ``Tabla …`` sheet -> long frame ``region, anio, mes, <valor>`` (0 -> NaN)."""
    filas = list(ws.iter_rows(values_only=True))
    enc = next(
        (i for i, r in enumerate(filas) if r and clave_region(r[0]) == "ANO" and clave_region(r[1]) == "MES"),
        None,
    )
    if enc is None:
        raise ErrorFuente(
            f"regalias_crudo/{ws.title}: no encuentro la fila de encabezado AÑO | MES | provincias"
        )
    header = filas[enc]
    cols = [(j, clave_region(h)) for j, h in enumerate(header) if j >= 2 and h not in (None, "")]
    out: list[dict[str, Any]] = []
    anio = None
    for r in filas[enc + 1 :]:
        if r is None or len(r) < 2:
            continue
        if r[0] not in (None, ""):
            try:
                anio = int(r[0])
            except (TypeError, ValueError):
                continue
        if anio is None or r[1] in (None, ""):
            continue
        try:
            mes = int(r[1])
        except (TypeError, ValueError):
            continue
        if not 1 <= mes <= 12:
            continue
        for j, k in cols:
            v = r[j] if j < len(r) else None
            try:
                v = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                v = None
            if v is not None and v == 0:
                v = None
            out.append({"region_clave": k, "anio": anio, "mes": mes, valor: v})
    return pd.DataFrame(out, columns=["region_clave", "anio", "mes", valor])


def _fecha_celda(filas: list[tuple], etiqueta: str) -> str | None:
    for r in filas[:5]:
        for j, c in enumerate(r):
            if isinstance(c, str) and etiqueta in clave_region(c) and j + 1 < len(r):
                v = r[j + 1]
                if isinstance(v, datetime | date):
                    return v.strftime("%Y-%m-%d")
                if isinstance(v, str):
                    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
                    if m:
                        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def leer_regalias_crudo(origen: Path | bytes) -> tuple[pd.DataFrame, dict]:
    """The workbook -> (``region, anio, mes, precio_usd_m3, produccion_m3, regalias_usd, provisorio``, meta).
    Rows where price, production and royalties are all empty are dropped."""
    libro = _abrir_libro(origen)
    ws = _hoja(libro, HOJAS["precios"])
    primeras = list(ws.iter_rows(min_row=1, max_row=3, values_only=True))
    meta = {
        "fecha_realizacion": _fecha_celda(primeras, "REALIZACION"),
        "fecha_proxima_actualizacion": _fecha_celda(primeras, "PROXIMA"),
        "nota_provisorio": next(
            (c for r in primeras for c in r if isinstance(c, str) and "provisori" in c.lower()), None
        ),
        "hojas": list(libro.sheetnames),
    }
    precios = _leer_pivot(ws, "precio_usd_m3")
    partes = [precios]
    for clave, col in (("produccion", "produccion_m3"), ("regalias", "regalias_usd")):
        try:
            partes.append(_leer_pivot(_hoja(libro, HOJAS[clave]), col))
        except ErrorFuente:
            meta[f"sin_{clave}"] = True
    libro.close()
    df = partes[0]
    for p in partes[1:]:
        df = df.merge(p, on=["region_clave", "anio", "mes"], how="outer")
    for col in ("produccion_m3", "regalias_usd"):
        if col not in df:
            df[col] = None
    df = df.dropna(subset=["precio_usd_m3", "produccion_m3", "regalias_usd"], how="all")
    df["region"] = df.region_clave.map(lambda k: PROVINCIAS.get(k) or k.title())
    df = df.drop(columns=["region_clave"])
    # the last two reported months (any province with a price) are provisional, says the sheet
    con_precio = df[df.precio_usd_m3.notna()]
    meses = sorted(set(zip(con_precio.anio, con_precio.mes, strict=True)))
    ultimos = set(meses[-2:])
    df["provisorio"] = [(a, m) in ultimos for a, m in zip(df.anio, df.mes, strict=True)]
    meta["ultimo_mes"] = f"{meses[-1][0]:04d}-{meses[-1][1]:02d}" if meses else None
    return df.sort_values(["region", "anio", "mes"]).reset_index(drop=True), meta


# --- precios_gas (CSV) -----------------------------------------------------------------------------------------------


def leer_precios_gas(origen: Path | bytes) -> pd.DataFrame:
    """The CSV -> long frame ``cuenca, anio, mes, contrato, segmento, precio_usd_mmbtu`` (0 dropped)."""
    raw = origen if isinstance(origen, bytes) else Path(origen).read_bytes()
    df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    faltan = {"anio", "mes", "cuenca", "contrato"} - set(df.columns)
    if faltan:
        raise ErrorFuente(f"precios_gas: faltan columnas {sorted(faltan)}; tiene {list(df.columns)}")
    seg_cols = {c: c.removeprefix("precio_") for c in df.columns if c.startswith("precio_")}
    desconocidos = set(seg_cols.values()) - set(SEGMENTOS_GAS)
    if desconocidos:
        raise ErrorFuente(f"precios_gas: segmentos no documentados {sorted(desconocidos)} (docs/precios.md)")
    largo = df.melt(
        id_vars=["anio", "mes", "cuenca", "contrato"],
        value_vars=list(seg_cols),
        var_name="segmento",
        value_name="precio_usd_mmbtu",
    )
    largo["segmento"] = largo.segmento.map(seg_cols)
    largo["contrato"] = largo.contrato.astype(str).str.strip().str.lower()
    malos = set(largo.contrato.unique()) - set(CONTRATOS_GAS)
    if malos:
        raise ErrorFuente(f"precios_gas: contratos no documentados {sorted(malos)}")
    largo["precio_usd_mmbtu"] = pd.to_numeric(largo.precio_usd_mmbtu, errors="coerce")
    largo = largo[largo.precio_usd_mmbtu.notna() & (largo.precio_usd_mmbtu > 0)].copy()
    largo["cuenca"] = largo.cuenca.astype(str).str.strip()
    largo["anio"] = largo.anio.astype(int)
    largo["mes"] = largo.mes.astype(int)
    return largo.sort_values(["cuenca", "anio", "mes", "contrato", "segmento"]).reset_index(drop=True)


# --- the published table ---------------------------------------------------------------------------------------------


def construir(
    regalias: pd.DataFrame | None,
    gas: pd.DataFrame | None,
    *,
    fecha_descarga: str | None,
    version: str,
    fecha_realizacion: str | None = None,
) -> pd.DataFrame:
    partes = []
    if regalias is not None and len(regalias):
        p = pd.DataFrame(
            {
                "producto": "petroleo",
                "region": regalias.region,
                "tipo_region": "provincia",
                "anio": regalias.anio.astype(int),
                "mes": regalias.mes.astype(int),
                "fuente": "regalias_crudo",
                "segmento": SEGMENTO_PETROLEO,
                "unidad_dataset": "USD/m³",
                "precio_dataset": regalias.precio_usd_m3,
                "precio_usd_m3": regalias.precio_usd_m3,
                "precio_usd_mil_m3": regalias.precio_usd_m3 * 1000.0,
                "provisorio": regalias.provisorio.astype(bool),
                "produccion_m3": regalias.produccion_m3,
                "regalias_usd": regalias.regalias_usd,
            }
        )
        if fecha_realizacion:
            p["fecha_realizacion"] = fecha_realizacion
        partes.append(p)
    if gas is not None and len(gas):
        g = pd.DataFrame(
            {
                "producto": "gas",
                "region": gas.cuenca,
                "tipo_region": "cuenca",
                "anio": gas.anio.astype(int),
                "mes": gas.mes.astype(int),
                "fuente": "precios_gas",
                "segmento": gas.segmento,
                "contrato": gas.contrato,
                "unidad_dataset": "USD/MMBTU",
                "precio_dataset": gas.precio_usd_mmbtu,
                "precio_usd_m3": gas.precio_usd_mmbtu.map(units.usd_per_mmbtu_to_usd_per_thousand_m3)
                / 1000.0,
                "precio_usd_mil_m3": gas.precio_usd_mmbtu.map(units.usd_per_mmbtu_to_usd_per_thousand_m3),
                "provisorio": False,
            }
        )
        partes.append(g)
    if not partes:
        return pd.DataFrame(columns=COLUMNAS)
    t = pd.concat(partes, ignore_index=True).reindex(columns=COLUMNAS)  # the columns a part lacks come as NaN
    t["mes_fecha"] = pd.to_datetime({"year": t.anio, "month": t.mes, "day": 1}, errors="coerce").dt.date
    t["fecha_descarga"] = fecha_descarga
    t["version"] = version
    for c in ("produccion_m3", "regalias_usd", "precio_dataset", "precio_usd_m3", "precio_usd_mil_m3"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    return t.sort_values(
        ["producto", "region", "segmento", "contrato", "anio", "mes"], na_position="first"
    ).reset_index(drop=True)


def tabla_vacia() -> pd.DataFrame:
    """The schema with no rows: what a source without the table registers so every query still runs."""
    t = pd.DataFrame(columns=COLUMNAS)
    tipos = {
        "anio": "Int64",
        "mes": "Int64",
        "precio_dataset": "float64",
        "precio_usd_m3": "float64",
        "precio_usd_mil_m3": "float64",
        "provisorio": "boolean",
        "produccion_m3": "float64",
        "regalias_usd": "float64",
    }
    for c in COLUMNAS:
        t[c] = t[c].astype(tipos.get(c, "string"))
    t["mes_fecha"] = pd.to_datetime(t["mes_fecha"].astype("string"), errors="coerce")
    return t


# --- the site snapshot -----------------------------------------------------------------------------------------------

_COLS_JSON = [
    "producto",
    "region",
    "mes",
    "segmento",
    "contrato",
    "precio_dataset",
    "provisorio",
    "produccion_m3",
    "regalias_usd",
]


def snapshot_json(t: pd.DataFrame, desde: int = SNAPSHOT_DESDE) -> dict:
    """Columnar JSON for ``site/data/precios.json``: oil from ``desde``, gas ``total`` contract only."""
    from vma.site import clean, sig

    s = t[
        ((t.producto == "petroleo") & (t.anio >= desde)) | ((t.producto == "gas") & (t.contrato == "total"))
    ]
    cols: dict[str, list] = {}
    cols["producto"] = s.producto.tolist()
    cols["region"] = s.region.tolist()
    cols["mes"] = [f"{a:04d}-{m:02d}" for a, m in zip(s.anio.astype(int), s.mes.astype(int), strict=True)]
    cols["segmento"] = s.segmento.tolist()
    cols["contrato"] = [clean(c) for c in s.contrato]
    cols["precio_dataset"] = [sig(v) for v in s.precio_dataset]
    cols["provisorio"] = s.provisorio.astype(bool).tolist()
    cols["produccion_m3"] = [sig(v) for v in s.produccion_m3]
    cols["regalias_usd"] = [sig(v) for v in s.regalias_usd]
    petro = t[t.producto == "petroleo"]
    return {
        "columnas": cols,
        "n": int(len(s)),
        "recorte": f"petróleo desde {desde}; gas sólo contrato total (ADR-034)",
        "unidad_dataset": {"petroleo": "USD/m³", "gas": "USD/MMBTU"},
        "mmbtu_por_mil_m3": units.MMBTU_PER_THOUSAND_M3,
        "fecha_realizacion": clean(petro.fecha_realizacion.iloc[0]) if len(petro) else None,
        "fecha_descarga": clean(t.fecha_descarga.iloc[0]) if len(t) else None,
        "version": clean(t.version.iloc[0]) if len(t) else None,
        "ultimo_mes": {
            p: (
                f"{g.anio.max():04d}-{int(g.loc[g.anio == g.anio.max(), 'mes'].max()):02d}"
                if len(g)
                else None
            )
            for p, g in ((p, t[(t.producto == p) & t.precio_dataset.notna()]) for p in ("petroleo", "gas"))
        },
    }


def desde_json(doc: dict) -> pd.DataFrame:
    """The snapshot back to the table's columns (conversions recomputed with the same factors)."""
    c = doc["columnas"]
    if not c.get("producto"):
        return tabla_vacia()
    t = pd.DataFrame({k: c[k] for k in _COLS_JSON if k in c})
    t["anio"] = t.mes.str.slice(0, 4).astype(int)
    t["mes"] = t.mes.str.slice(5, 7).astype(int)
    es_gas = t.producto == "gas"
    t["tipo_region"] = es_gas.map({True: "cuenca", False: "provincia"})
    t["fuente"] = es_gas.map({True: "precios_gas", False: "regalias_crudo"})
    t["unidad_dataset"] = es_gas.map({True: "USD/MMBTU", False: "USD/m³"})
    t["precio_dataset"] = pd.to_numeric(t.precio_dataset, errors="coerce")
    t["precio_usd_mil_m3"] = t.precio_dataset.where(
        ~es_gas, t.precio_dataset.map(units.usd_per_mmbtu_to_usd_per_thousand_m3)
    )
    t.loc[~es_gas, "precio_usd_mil_m3"] = t.loc[~es_gas, "precio_dataset"] * 1000.0
    t["precio_usd_m3"] = t.precio_usd_mil_m3 / 1000.0
    t.loc[~es_gas, "precio_usd_m3"] = t.loc[~es_gas, "precio_dataset"]
    t["fecha_realizacion"] = doc.get("fecha_realizacion")
    t.loc[es_gas, "fecha_realizacion"] = None
    t["fecha_descarga"] = doc.get("fecha_descarga")
    t["version"] = doc.get("version")
    t["mes_fecha"] = pd.to_datetime({"year": t.anio, "month": t.mes, "day": 1}).dt.date
    return t.reindex(columns=COLUMNAS)


# --- pipeline stage ------------------------------------------------------------------------------------------------


def _archivo_raw(root: Path, nombre: str) -> tuple[Path, str] | None:
    """The newest ``data/raw/<date>/<nombre>`` and that date (price files may be downloaded on their own day)."""
    base = root / "data" / "raw"
    if not base.exists():
        return None
    dias = sorted(p for p in base.iterdir() if p.is_dir() and (p / nombre).exists())
    return (dias[-1] / nombre, dias[-1].name) if dias else None


def run(root: Path, today: date | None = None, salida_site: bool = True) -> tuple[Path, Path]:
    """``python pipeline.py precios``: parse both raw files, publish the table next to the other published tables
    (the newest ``data/publicado/<date>/`` with the three core tables; else ``<today>``) and refresh the snapshot."""
    from vma.consulta.datos import ultimo_publicado
    from vma.indicadores import publish

    from .. import sources as SRC

    regalias = _archivo_raw(root, SRC.SOURCES["regalias_crudo"].archivo_local)
    gas = _archivo_raw(root, SRC.SOURCES["precios_gas"].archivo_local)
    if regalias is None and gas is None:
        raise SystemExit(
            "no raw price files: run `python pipeline.py download regalias_crudo precios_gas` first (docs/precios.md)"
        )
    pub = ultimo_publicado(root)
    day = today or (date.fromisoformat(pub.name) if pub is not None else date.today())
    fechas = []
    r_df = meta = None
    if regalias is not None:
        r_df, meta = leer_regalias_crudo(regalias[0])
        fechas.append(regalias[1])
        print(
            f"regalias_crudo: {len(r_df):,} province-months, realised {meta.get('fecha_realizacion')}, last {meta.get('ultimo_mes')}"
        )
    g_df = None
    if gas is not None:
        g_df = leer_precios_gas(gas[0])
        fechas.append(gas[1])
        print(f"precios_gas: {len(g_df):,} basin-month-contract-segment prices")
    t = construir(
        r_df,
        g_df,
        fecha_descarga=max(fechas) if fechas else None,
        version=day.isoformat(),
        fecha_realizacion=(meta or {}).get("fecha_realizacion"),
    )
    paths = publish(root, t, day, "precios")
    print(f"{len(t):,} rows -> {paths[0]}  {paths[1]}")
    if salida_site:
        out = root / "site" / "data" / "precios.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        doc = snapshot_json(t)
        out.write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        print(f"snapshot: {out} ({doc['n']:,} rows, {out.stat().st_size / 1e6:.2f} MB)")
    return paths


__all__ = [
    "COLUMNAS",
    "ErrorFuente",
    "construir",
    "desde_json",
    "leer_precios_gas",
    "leer_regalias_crudo",
    "run",
    "snapshot_json",
    "tabla_vacia",
]
