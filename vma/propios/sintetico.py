"""A synthetic "my wells" dataset derived from public wells with noise (ADR-030).

It exists so the comparison and simulation tools can be tested, demonstrated and documented without anyone's
real data. Recipe: take ``n`` in-scope public wells of a formation and cohort range with at least ``meses_min``
months of history; multiply each well's monthly volumes by a well-level factor (log-normal, sd ``sigma_pozo``)
and a month-level factor (log-normal, sd ``sigma_mes``); jitter lateral length (±5 %), stages (±2) and coordinates
(±0.02°); rename the wells ``MIO-001`` … and assign them to two or three campaigns. The output is marked synthetic
in a side file ``<archivo>.meta.json`` and in the ``origen`` column, and the recipe (seed, sigmas, source wells
count) is written there so anyone can regenerate it. The public siglas are **not** kept: the point is a dataset
that looks like an operator's, not a disguised copy of specific wells.

Two entry points: :func:`generar` from DataFrames (tests), :func:`generar_desde_repo` from the latest published
tables plus the raw production file (``python pipeline.py sintetico``).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from vma.consulta import datos as D

CAMPANIAS = ("PAD-A", "PAD-B", "PAD-C")


def generar(
    mensual: pd.DataFrame,
    pozos: pd.DataFrame,
    n: int = 30,
    semilla: int = 7,
    sigma_pozo: float = 0.15,
    sigma_mes: float = 0.08,
    meses_min: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """``mensual``: sigla_clave, mes_fecha, petroleo_m3, gas_mil_m3, agua_m3, tef_d. ``pozos``: sigla_clave,
    formacion, rama_m, etapas, longitud, latitud, cohorte (and optionally arena_tn, agua_fractura_m3, ventana).
    Returns (produccion, pozos) in the user schema (docs/mis-datos.md) and the recipe."""
    rng = np.random.default_rng(semilla)
    cuenta = mensual.groupby("sigla_clave").size()
    elegibles = sorted(set(cuenta[cuenta >= meses_min].index) & set(pozos.sigla_clave))
    if len(elegibles) < 2:
        raise ValueError(f"menos de 2 pozos con >= {meses_min} meses; no hay con qué generar")
    n = min(int(n), len(elegibles))
    fuente = sorted(rng.choice(elegibles, size=n, replace=False).tolist())
    nombres = {s: f"MIO-{i + 1:03d}" for i, s in enumerate(fuente)}
    campania = {s: CAMPANIAS[i % len(CAMPANIAS)] for i, s in enumerate(fuente)}
    f_pozo = {s: float(np.exp(rng.normal(0.0, sigma_pozo))) for s in fuente}

    m = mensual[mensual.sigla_clave.isin(fuente)].sort_values(["sigla_clave", "mes_fecha"]).copy()
    f_mes = np.exp(rng.normal(0.0, sigma_mes, size=len(m)))
    fp = m.sigla_clave.map(f_pozo).to_numpy()
    prod = pd.DataFrame(
        {
            "sigla": m.sigla_clave.map(nombres).to_numpy(),
            "fecha": pd.to_datetime(m.mes_fecha).dt.strftime("%Y-%m").to_numpy(),
            "petroleo_m3": np.round(m.petroleo_m3.fillna(0).to_numpy() * fp * f_mes, 1),
            "gas_mil_m3": np.round(m.gas_mil_m3.fillna(0).to_numpy() * fp * f_mes, 1),
            "agua_m3": np.round(
                m.agua_m3.fillna(0).to_numpy() * fp * np.exp(rng.normal(0.0, sigma_mes, size=len(m))), 1
            ),
            "tef": m.tef_d.to_numpy(),
        }
    )
    p = pozos[pozos.sigla_clave.isin(fuente)].set_index("sigla_clave").loc[fuente].reset_index()
    rama = pd.to_numeric(p.rama_m, errors="coerce").to_numpy(dtype=float)
    etapas = (
        pd.to_numeric(p.get("etapas"), errors="coerce").to_numpy(dtype=float)
        if "etapas" in p
        else np.full(n, np.nan)
    )
    out_pozos = pd.DataFrame(
        {
            "sigla": [nombres[s] for s in p.sigla_clave],
            "campania": [campania[s] for s in p.sigla_clave],
            "formacion": p.formacion.to_numpy(),
            "rama_m": np.where(np.isnan(rama), np.nan, np.round(rama * rng.uniform(0.95, 1.05, size=n), 0)),
            "etapas": np.where(
                np.isnan(etapas), np.nan, np.clip(etapas + rng.integers(-2, 3, size=n), 1, None)
            ),
            "longitud": np.round(
                pd.to_numeric(p.longitud, errors="coerce").to_numpy(dtype=float)
                + rng.uniform(-0.02, 0.02, size=n),
                5,
            ),
            "latitud": np.round(
                pd.to_numeric(p.latitud, errors="coerce").to_numpy(dtype=float)
                + rng.uniform(-0.02, 0.02, size=n),
                5,
            ),
            "origen": "sintetico",
        }
    )
    for c in ("arena_tn", "agua_fractura_m3"):
        if c in p:
            v = pd.to_numeric(p[c], errors="coerce").to_numpy(dtype=float)
            out_pozos[c] = np.where(np.isnan(v), np.nan, np.round(v * rng.uniform(0.9, 1.1, size=n), 0))
    out_pozos["etapas"] = out_pozos.etapas.astype("Int64")
    receta = {
        "sintetico": True,
        "descripcion": "pozos públicos del Capítulo IV con ruido multiplicativo y siglas cambiadas; no son pozos reales",
        "generado": date.today().isoformat(),
        "semilla": int(semilla),
        "n_pozos": int(n),
        "sigma_pozo": sigma_pozo,
        "sigma_mes": sigma_mes,
        "meses_min": int(meses_min),
        "fuente": "produccion_nc + indicadores (vma/propios/sintetico.py)",
        "cohortes": sorted({int(c) for c in pd.to_numeric(p.cohorte, errors="coerce").dropna()}),
        "formaciones": sorted(p.formacion.dropna().unique().tolist()),
        "campanias": list(CAMPANIAS[: min(n, len(CAMPANIAS))]),
        "licencia_origen": "CC-BY 4.0, Secretaría de Energía de la Nación Argentina",
    }
    return prod, out_pozos, receta


def generar_desde_repo(
    root: Path,
    n: int = 30,
    semilla: int = 7,
    formacion: str = "Vaca Muerta",
    cohortes: tuple[int, int] = (2022, 2024),
    ventana: str | None = "petroleo",
    meses_min: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Pick the source wells from the latest ``indicadores.parquet`` and their months from the raw production CSV."""
    from vma.download import latest_raw_dir

    pub = D.ultimo_publicado(root)
    if pub is None:
        raise FileNotFoundError(
            "no hay tablas publicadas; corré `python pipeline.py master indicadores curvas`"
        )
    raw = latest_raw_dir(root) / "produccion_nc.csv"
    if not raw.exists():
        raise FileNotFoundError(f"no está {raw}; corré `python pipeline.py download`")
    con = duckdb.connect()
    ind = con.execute(
        "SELECT sigla_clave, formacion, cohorte, ventana, rama_m, etapas, meses_con_registro, "
        "arena_tn_por_m * rama_m AS arena_tn, agua_fractura_m3_por_m * rama_m AS agua_fractura_m3 "
        f"FROM read_parquet('{(pub / 'indicadores.parquet').as_posix()}') "
        "WHERE en_alcance AND lower(formacion) = lower(?) AND cohorte BETWEEN ? AND ? "
        "AND (? IS NULL OR ventana = ?) AND meses_con_registro >= ? AND coalesce(outlier_ip90_m, false) = false",
        [formacion, cohortes[0], cohortes[1], ventana, ventana, meses_min],
    ).df()
    if ind.empty:
        raise ValueError(
            f"ningún pozo público cumple formacion={formacion}, cohortes={cohortes}, ventana={ventana}"
        )
    maestro = con.execute(
        "SELECT sigla_clave, idpozos, longitud, latitud FROM read_parquet(?)",
        [(pub / "pozos.parquet").as_posix()],
    ).df()
    pozos = ind.merge(maestro, on="sigla_clave", how="left")
    ids = pozos[["sigla_clave", "idpozos"]].copy()
    ids["idpozo"] = ids.idpozos.astype(str).str.split("|")
    ids = ids.explode("idpozo")
    ids["idpozo"] = pd.to_numeric(ids.idpozo, errors="coerce")
    ids = ids.dropna(subset=["idpozo"])
    ids["idpozo"] = ids.idpozo.astype(int)
    con.register("_ids", ids[["sigla_clave", "idpozo"]])
    mensual = con.execute(
        "SELECT i.sigla_clave, make_date(p.anio, p.mes, 1) AS mes_fecha, sum(p.prod_pet) AS petroleo_m3, "
        "sum(p.prod_gas) AS gas_mil_m3, sum(p.prod_agua) AS agua_m3, "
        "least(max(p.tef), day(last_day(make_date(p.anio, p.mes, 1)))) AS tef_d "
        f"FROM read_csv_auto('{raw.as_posix()}', sample_size=200000) p JOIN _ids i USING (idpozo) "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    ).df()
    mensual["mes_fecha"] = pd.to_datetime(mensual.mes_fecha)
    con.close()
    prod, out_pozos, receta = generar(mensual, pozos, n=n, semilla=semilla, meses_min=meses_min)
    receta["filtro_publico"] = {
        "formacion": formacion,
        "cohortes": list(cohortes),
        "ventana": ventana,
        "sin_outliers": True,
    }
    return prod, out_pozos, receta


def escribir(prod: pd.DataFrame, pozos: pd.DataFrame, receta: dict, carpeta: Path) -> tuple[Path, Path, Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    p1 = carpeta / "mis_pozos_produccion.csv"
    p2 = carpeta / "mis_pozos_atributos.csv"
    p3 = carpeta / "mis_pozos_produccion.csv.meta.json"
    prod.to_csv(p1, index=False, encoding="utf-8")
    pozos.to_csv(p2, index=False, encoding="utf-8")
    p3.write_text(json.dumps(receta, indent=2, ensure_ascii=False), encoding="utf-8")
    return p1, p2, p3


def run(root: Path, n: int = 30, semilla: int = 7, salida: Path | None = None) -> Path:
    prod, pozos, receta = generar_desde_repo(root, n=n, semilla=semilla)
    carpeta = salida or root / "data" / "sintetico" / date.today().isoformat()
    p1, _, _ = escribir(prod, pozos, receta, carpeta)
    print(f"sintético: {len(pozos)} pozos, {len(prod)} filas -> {carpeta}")
    return p1
