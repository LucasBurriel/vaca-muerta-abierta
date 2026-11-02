"""Compare the user's wells with the published type curves and indicators (ADR-030).

Pure functions over a :class:`~vma.consulta.datos.Datos` (the published tables) and a
:class:`~vma.propios.cargar.MisPozos` (the user's, already registered as views). They return plain dicts; the
tool layer in ``vma/consulta/herramientas.py`` wraps them in the citation envelope and rounds.

The reference group of a well is its **cohort × formation × fluid window** when that curve is published with at
least one publishable month, else **cohort × formation** (said in ``grupo.nivel``). ``cohorte_ref`` lets the user
pick another cohort (a 2026 well has no published curve yet, ADR-017). Percentiles follow the oil convention of the
published curves: P10 is the high case, so "P35" means the value is beaten by 35 % of the group's wells that month.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from vma.consulta.datos import Datos
from vma.normalize import formation_key, sigla_l2
from vma.propios.cargar import MisPozos

N_MIN = 5  # ADR-017
TASAS = ("petroleo_m3_d", "gas_mil_m3_d", "equivalente_m3_d")
VENTANAS = ("petroleo", "volatil_condensado", "gas")
FILTROS_MIOS = ("campania", "formacion", "cohorte", "ventana", "siglas")


class ErrorComparacion(ValueError):
    """The comparison cannot be made as asked; the message is for the model to read."""


# --- helpers -------------------------------------------------------------------------------------------------------


def _formacion_publicada(d: Datos, formacion: str | None) -> str | None:
    k = formation_key(formacion or "")
    for (f,) in d.con.execute(
        "SELECT DISTINCT formacion FROM curvas_tipo WHERE formacion IS NOT NULL"
    ).fetchall():
        if formation_key(f) == k:
            return f
    return None


def percentil_en_curva(
    valor: float | None, p10: float | None, p50: float | None, p90: float | None
) -> float | None:
    """Estimated exceedance percentile of ``valor`` given the three published quantiles (log-linear between them,
    linear extrapolation outside, clipped to 1..99). P10 is the high case: returns 10 at p10, 90 at p90."""
    if valor is None or any(x is None for x in (p10, p50, p90)):
        return None
    if any(isinstance(x, float) and math.isnan(x) for x in (valor, p10, p50, p90)):
        return None
    pts = [(p90, 90.0), (p50, 50.0), (p10, 10.0)]
    if valor <= 0 or any(p <= 0 for p, _ in pts) or not (p90 <= p50 <= p10):
        xs = [p for p, _ in pts]
        if not (xs[0] <= xs[1] <= xs[2]):
            return None
        f = lambda x: x  # noqa: E731
    else:
        f = math.log
    x = f(valor)
    (x0, y0), (x1, y1), (x2, y2) = [(f(p), y) for p, y in pts]
    if x <= x1:
        a, b = (x0, y0), (x1, y1)
    else:
        a, b = (x1, y1), (x2, y2)
    if b[0] == a[0]:
        return float(a[1])
    y = a[1] + (x - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
    return float(min(99.0, max(1.0, y)))


def _pozo_mio(mis: MisPozos, sigla: str) -> pd.Series:
    clave = sigla_l2(sigla or "")
    ind = mis.indicadores
    hit = ind[(ind.sigla == clave) | (ind.sigla_original.astype(str).map(sigla_l2) == clave)]
    if hit.empty:
        sub = ind[ind.sigla.str.contains(clave, regex=False)] if clave else ind.iloc[0:0]
        pista = f"; parecidos: {', '.join(sub.sigla.head(5))}" if len(sub) else ""
        raise ErrorComparacion(f"{sigla!r} no está entre mis pozos cargados ({len(ind)} pozos){pista}")
    return hit.iloc[0]


def _grupo(d: Datos, pozo: pd.Series, cohorte_ref: int | None, incluye_outliers: bool, tasa: str) -> dict:
    """Which published curve this well is compared with, and why."""
    formacion = _formacion_publicada(d, pozo.get("formacion"))
    if formacion is None:
        raise ErrorComparacion(
            f"la formación {pozo.get('formacion')!r} de mi pozo no tiene curva tipo publicada; "
            "las publicadas: "
            + ", ".join(f for (f,) in d.con.execute("SELECT DISTINCT formacion FROM curvas_tipo").fetchall())
        )
    cohorte = (
        int(cohorte_ref)
        if cohorte_ref is not None
        else (int(pozo.cohorte) if pd.notna(pozo.get("cohorte")) else None)
    )
    if cohorte is None:
        raise ErrorComparacion("mi pozo no tiene cohorte (nunca produjo) y no se pasó cohorte_ref")
    ventana = pozo.get("ventana") if isinstance(pozo.get("ventana"), str) else None
    niveles = []
    if ventana in VENTANAS:
        niveles.append(("cohorte_formacion_ventana", ventana))
    niveles.append(("cohorte_formacion", None))
    for nivel, v in niveles:
        preds = [
            "nivel = ?",
            "cohorte = ?",
            "formacion = ?",
            "incluye_outliers = ?",
            f"{tasa}_p50 IS NOT NULL",
        ]
        params: list[Any] = [nivel, cohorte, formacion, bool(incluye_outliers)]
        if v:
            preds.append("ventana = ?")
            params.append(v)
        n = d.con.execute(f"SELECT count(*) FROM curvas_tipo WHERE {' AND '.join(preds)}", params).fetchone()[
            0
        ]
        if n:
            return {
                "nivel": nivel,
                "cohorte": cohorte,
                "cohorte_del_pozo": int(pozo.cohorte) if pd.notna(pozo.get("cohorte")) else None,
                "formacion": formacion,
                "ventana": v,
                "ventana_del_pozo": ventana,
                "incluye_outliers": bool(incluye_outliers),
                "meses_publicables": int(n),
            }
    raise ErrorComparacion(
        f"no hay curva tipo publicada para cohorte {cohorte}, {formacion}"
        + (f", ventana {ventana}" if ventana else "")
        + " (ADR-017: menos de 5 pozos, o cohorte sin publicar); probá cohorte_ref con una cohorte anterior"
    )


def _curva(d: Datos, grupo: dict, tasa: str, mes_max: int) -> pd.DataFrame:
    preds = ["nivel = ?", "cohorte = ?", "formacion = ?", "incluye_outliers = ?", "mes <= ?"]
    params: list[Any] = [
        grupo["nivel"],
        grupo["cohorte"],
        grupo["formacion"],
        grupo["incluye_outliers"],
        int(mes_max),
    ]
    if grupo.get("ventana"):
        preds.append("ventana = ?")
        params.append(grupo["ventana"])
    n_col = "n_pozos_por_m" if tasa.endswith("_por_m") else "n_pozos"
    return d.df(
        f"SELECT mes, {n_col} AS n_pozos, {tasa}_p10 AS p10, {tasa}_p50 AS p50, {tasa}_p90 AS p90 "
        f"FROM curvas_tipo WHERE {' AND '.join(preds)} ORDER BY mes",
        params,
    )


def _serie_mia(mis: MisPozos, pozo: pd.Series, tasa: str) -> pd.DataFrame:
    base = tasa.removesuffix("_por_m")
    m = mis.produccion[
        (mis.produccion.sigla == pozo.sigla) & mis.produccion.k.notna() & (mis.produccion.k >= 0)
    ]
    m = m[m.tef_d > 0][["k", "tef_d", base, "petroleo_m3", "gas_mil_m3", "equivalente_m3"]].rename(
        columns={"k": "mes"}
    )
    m["mes"] = m.mes.astype(int)
    if tasa.endswith("_por_m"):
        if not bool(pozo.get("rama_normalizable")):
            raise ErrorComparacion(
                f"la tasa {tasa} necesita rama_m conocida y >= 500 m (ADR-019); mi pozo tiene rama_m={pozo.get('rama_m')}"
            )
        m["valor"] = m[base] / float(pozo.rama_m)
    else:
        m["valor"] = m[base]
    return m


def _rank_publico(
    d: Datos, grupo: dict, metrica: str, valor: float | None, incluye_outliers: bool
) -> dict | None:
    """Where ``valor`` falls among the public wells of the group for ``metrica``: median, n and the share below."""
    if not d.tiene("indicadores", metrica) or valor is None or pd.isna(valor):
        return None
    preds = ["en_alcance", "cohorte = ?", "formacion = ?", f"{metrica} IS NOT NULL"]
    params: list[Any] = [grupo["cohorte"], grupo["formacion"]]
    if grupo.get("ventana"):
        preds.append("ventana = ?")
        params.append(grupo["ventana"])
    if not incluye_outliers:
        preds.append("coalesce(outlier_ip90_m, false) = false")
    w = " AND ".join(preds)
    n, med, p25, p75, debajo = d.con.execute(
        f"SELECT count(*), median({metrica}), quantile_cont({metrica}, 0.25), quantile_cont({metrica}, 0.75), "
        f"sum(CASE WHEN {metrica} < ? THEN 1 ELSE 0 END) FROM indicadores WHERE {w}",
        [float(valor), *params],
    ).fetchone()
    if not n or n < N_MIN:
        return {
            "n_publico": int(n or 0),
            "sin_dato_porque": f"menos de {N_MIN} pozos públicos con {metrica} en el grupo (ADR-017)",
        }
    return {
        "metrica": metrica,
        "mio": float(valor),
        "mediana_publica": float(med),
        "p25_publico": float(p25),
        "p75_publico": float(p75),
        "n_publico": int(n),
        "ratio_vs_mediana": float(valor) / float(med) if med else None,
        "supera_pct_publicos": 100.0 * float(debajo) / float(n),
    }


# --- one well --------------------------------------------------------------------------------------------------------


def comparar_pozo(
    d: Datos,
    mis: MisPozos,
    sigla: str,
    tasa: str = "petroleo_m3_d",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
    mes_max: int = 36,
) -> dict:
    if tasa not in TASAS and tasa not in tuple(f"{t}_por_m" for t in TASAS):
        raise ErrorComparacion(f"tasa {tasa!r} no existe; las tasas son {', '.join(TASAS)} y sus _por_m")
    pozo = _pozo_mio(mis, sigla)
    grupo = _grupo(d, pozo, cohorte_ref, incluye_outliers, tasa)
    curva = _curva(d, grupo, tasa, mes_max)
    mia = _serie_mia(mis, pozo, tasa)
    j = mia[mia.mes <= int(mes_max)].merge(curva, on="mes", how="left")
    meses = []
    sin_curva = 0
    for r in j.itertuples(index=False):
        p10, p50, p90 = (None if pd.isna(x) else float(x) for x in (r.p10, r.p50, r.p90))
        fila = {
            "mes": int(r.mes),
            "mio": float(r.valor),
            "p10": p10,
            "p50": p50,
            "p90": p90,
            "n_pozos": None if pd.isna(r.n_pozos) else int(r.n_pozos),
        }
        if p50 is None:
            sin_curva += 1
            fila["sin_dato_porque"] = (
                f"n = {fila['n_pozos']} < {N_MIN} pozos públicos ese mes (ADR-017)"
                if fila["n_pozos"] is not None and fila["n_pozos"] < N_MIN
                else "mes fuera de la curva publicada"
            )
        else:
            fila["percentil"] = percentil_en_curva(float(r.valor), p10, p50, p90)
            fila["ratio_p50"] = float(r.valor) / p50 if p50 else None
        meses.append(fila)
    comp = [m for m in meses if m.get("percentil") is not None]
    pct = [m["percentil"] for m in comp]
    resumen = {
        "n_meses_mios": int(len(mia)),
        "n_meses_comparados": len(comp),
        "meses_sobre_p50": sum(1 for m in comp if m["ratio_p50"] is not None and m["ratio_p50"] > 1),
        "percentil_mediano": float(np.median(pct)) if pct else None,
        "percentil_ultimo_mes": comp[-1]["percentil"] if comp else None,
        "ratio_p50_mediano": float(np.median([m["ratio_p50"] for m in comp])) if comp else None,
    }
    base = tasa.removesuffix("_por_m")
    fluido = base.removesuffix("_m3_d").removesuffix("_mil")
    ip90 = _rank_publico(d, grupo, f"ip90_{base}", pozo.get(f"ip90_{base}"), incluye_outliers)
    ip90_m = (
        _rank_publico(d, grupo, f"ip90_{base}_por_m", pozo.get(f"ip90_{base}_por_m"), incluye_outliers)
        if bool(pozo.get("rama_normalizable"))
        else None
    )
    acum_col = "acum12_" + ("gas_mil_m3" if fluido == "gas" else f"{fluido}_m3")
    acum12 = _rank_publico(d, grupo, acum_col, pozo.get(acum_col), incluye_outliers)
    return {
        "pozo": {
            "sigla": pozo.sigla,
            "sigla_original": pozo.sigla_original,
            "formacion": pozo.get("formacion"),
            "cohorte": grupo["cohorte_del_pozo"],
            "ventana": grupo["ventana_del_pozo"],
            "ventana_fuente": pozo.get("ventana_fuente"),
            "rama_m": None if pd.isna(pozo.get("rama_m")) else float(pozo.rama_m),
            "campania": pozo.get("campania"),
            "flags": [f for f in str(pozo.get("flags") or "").split("|") if f],
        },
        "grupo": grupo,
        "tasa": tasa,
        "resumen": resumen,
        "indicadores_vs_grupo": {
            k: v for k, v in (("ip90", ip90), ("ip90_por_m", ip90_m), ("acum12", acum12)) if v is not None
        },
        "meses": meses,
        "meses_sin_curva": sin_curva,
    }


# --- several wells ---------------------------------------------------------------------------------------------------


def _seleccionar(mis: MisPozos, filtros: dict | None) -> pd.DataFrame:
    ind = mis.indicadores
    f = dict(filtros or {})
    extra = set(f) - set(FILTROS_MIOS)
    if extra:
        raise ErrorComparacion(
            f"filtros desconocidos {sorted(extra)}; los permitidos son {', '.join(FILTROS_MIOS)}"
        )
    sel = ind
    if f.get("campania"):
        sel = sel[sel.campania.astype(str).str.lower() == str(f["campania"]).lower()]
    if f.get("formacion"):
        k = formation_key(str(f["formacion"]))
        sel = sel[sel.formacion.astype(str).map(formation_key) == k]
    if f.get("cohorte") is not None:
        sel = sel[sel.cohorte == int(f["cohorte"])]
    if f.get("ventana"):
        if f["ventana"] not in VENTANAS:
            raise ErrorComparacion(f"ventana debe ser una de {', '.join(VENTANAS)}")
        sel = sel[sel.ventana == f["ventana"]]
    if f.get("siglas"):
        claves = {sigla_l2(s) for s in f["siglas"]}
        sel = sel[sel.sigla.isin(claves) | sel.sigla_original.astype(str).map(sigla_l2).isin(claves)]
    if sel.empty:
        raise ErrorComparacion(
            f"ningún pozo mío cumple los filtros {f}; tengo {len(ind)} pozos, campañas: "
            + ", ".join(sorted(ind.campania.dropna().astype(str).unique())[:10])
        )
    return sel


def comparar_campania(
    d: Datos,
    mis: MisPozos,
    filtros: dict | None = None,
    metrica: str = "ip90_petroleo_m3_d_por_m",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
) -> dict:
    if metrica not in mis.indicadores.columns:
        prefijos = ("ip", "acum", "gor", "corte", "rama", "etapas", "arena", "agua")
        hay = ", ".join(c for c in mis.indicadores.columns if c.startswith(prefijos))
        raise ErrorComparacion(f"métrica {metrica!r} no está en mis indicadores; hay: {hay}")
    if not d.tiene("indicadores", metrica):
        raise ErrorComparacion(f"la fuente {d.fuente} no trae indicadores.{metrica}")
    sel = _seleccionar(mis, filtros)
    filas, sin_dato, sin_grupo = [], {}, []
    for _, pozo in sel.iterrows():
        v = pozo.get(metrica)
        fila = {
            "sigla": pozo.sigla,
            "campania": pozo.get("campania"),
            "cohorte": None if pd.isna(pozo.get("cohorte")) else int(pozo.cohorte),
            "ventana": pozo.get("ventana") if isinstance(pozo.get("ventana"), str) else None,
            "rama_m": None if pd.isna(pozo.get("rama_m")) else float(pozo.rama_m),
            "mio": None if v is None or pd.isna(v) else float(v),
        }
        if fila["mio"] is None:
            motivo = next(
                (
                    f
                    for f in str(pozo.get("flags") or "").split("|")
                    if f.startswith(("ip", "acum", "sin_rama", "rama_corta", "nunca", "gor"))
                ),
                "sin dato",
            )
            sin_dato[motivo] = sin_dato.get(motivo, 0) + 1
            fila["sin_dato_porque"] = motivo
            filas.append(fila)
            continue
        try:
            grupo = _grupo(d, pozo, cohorte_ref, incluye_outliers, "petroleo_m3_d")
        except ErrorComparacion as e:
            sin_grupo.append(f"{pozo.sigla}: {e}")
            fila["sin_dato_porque"] = "sin grupo público comparable"
            filas.append(fila)
            continue
        rk = _rank_publico(d, grupo, metrica, fila["mio"], incluye_outliers) or {}
        fila.update(
            {
                "grupo": f"{grupo['nivel']}:{grupo['cohorte']}/{grupo['formacion']}"
                + (f"/{grupo['ventana']}" if grupo.get("ventana") else ""),
                "mediana_publica": rk.get("mediana_publica"),
                "n_publico": rk.get("n_publico"),
                "ratio_vs_mediana": rk.get("ratio_vs_mediana"),
                "supera_pct_publicos": rk.get("supera_pct_publicos"),
            }
        )
        if "sin_dato_porque" in rk:
            fila["sin_dato_porque"] = rk["sin_dato_porque"]
        filas.append(fila)
    con = [f for f in filas if f.get("ratio_vs_mediana") is not None]
    ratios = [f["ratio_vs_mediana"] for f in con]
    pcts = [f["supera_pct_publicos"] for f in con]
    resumen = {
        "n_mios": int(len(sel)),
        "n_comparados": len(con),
        "mediana_mia": float(np.median([f["mio"] for f in con])) if con else None,
        "mediana_de_medianas_publicas": float(np.median([f["mediana_publica"] for f in con]))
        if con
        else None,
        "ratio_mediano": float(np.median(ratios)) if ratios else None,
        "pozos_sobre_mediana_publica": sum(1 for r in ratios if r > 1),
        "supera_pct_mediano": float(np.median(pcts)) if pcts else None,
        "supera_pct_p25_p75": [float(np.percentile(pcts, 25)), float(np.percentile(pcts, 75))]
        if pcts
        else None,
    }
    filas.sort(key=lambda f: (f.get("ratio_vs_mediana") is None, -(f.get("ratio_vs_mediana") or 0)))
    return {
        "metrica": metrica,
        "filtros": dict(filtros or {}),
        "resumen": resumen,
        "pozos": filas,
        "sin_dato_porque": sin_dato,
        "sin_grupo": sin_grupo,
    }


# --- gaps --------------------------------------------------------------------------------------------------------------


def brechas(
    d: Datos,
    mis: MisPozos,
    sigla: str | None = None,
    filtros: dict | None = None,
    tasa: str = "petroleo_m3_d",
    cohorte_ref: int | None = None,
    incluye_outliers: bool = True,
    mes_max: int = 24,
) -> dict:
    """Where and how much each well is below the group's P50: by month (rate) and cumulated (volume)."""
    if tasa not in TASAS:
        raise ErrorComparacion(f"brechas trabaja con tasas absolutas: {', '.join(TASAS)}")
    sel = (
        mis.indicadores[mis.indicadores.sigla == _pozo_mio(mis, sigla).sigla]
        if sigla
        else _seleccionar(mis, filtros)
    )
    unidad_vol = {"petroleo_m3_d": "m³", "gas_mil_m3_d": "mil m³", "equivalente_m3_d": "m³ eq"}[tasa]
    por_pozo, errores = [], []
    tot_mio = tot_p50 = 0.0
    for _, pozo in sel.iterrows():
        try:
            grupo = _grupo(d, pozo, cohorte_ref, incluye_outliers, tasa)
            mia = _serie_mia(mis, pozo, tasa)
        except ErrorComparacion as e:
            errores.append(f"{pozo.sigla}: {e}")
            continue
        curva = _curva(d, grupo, tasa, mes_max)
        j = mia[mia.mes <= mes_max].merge(curva, on="mes", how="inner")
        j = j[j.p50.notna()]
        if j.empty:
            errores.append(
                f"{pozo.sigla}: ningún mes comparable con la curva de {grupo['cohorte']}/{grupo['formacion']}"
            )
            continue
        j["brecha_tasa"] = j.valor - j.p50
        j["brecha_vol"] = j.brecha_tasa * j.tef_d
        j["ratio"] = j.valor / j.p50
        debajo = j[j.ratio < 1]
        tramos = {
            "meses_0_5": int(((debajo.mes >= 0) & (debajo.mes <= 5)).sum()),
            "meses_6_11": int(((debajo.mes >= 6) & (debajo.mes <= 11)).sum()),
            "meses_12_mas": int((debajo.mes >= 12).sum()),
        }
        acum_mio = float((j.valor * j.tef_d).sum())
        acum_p50 = float((j.p50 * j.tef_d).sum())
        tot_mio += acum_mio
        tot_p50 += acum_p50
        peor = j.loc[j.ratio.idxmin()]
        por_pozo.append(
            {
                "sigla": pozo.sigla,
                "campania": pozo.get("campania"),
                "grupo": f"{grupo['nivel']}:{grupo['cohorte']}/{grupo['formacion']}"
                + (f"/{grupo['ventana']}" if grupo.get("ventana") else ""),
                "meses_comparados": int(len(j)),
                "meses_debajo_p50": int(len(debajo)),
                "tramos_debajo": tramos,
                "acum_mio": acum_mio,
                "acum_p50": acum_p50,
                "brecha_acum": acum_mio - acum_p50,
                "brecha_acum_pct": 100.0 * (acum_mio - acum_p50) / acum_p50 if acum_p50 else None,
                "peor_mes": {
                    "mes": int(peor.mes),
                    "mio": float(peor.valor),
                    "p50": float(peor.p50),
                    "ratio": float(peor.ratio),
                },
                "meses": [
                    {
                        "mes": int(r.mes),
                        "mio": float(r.valor),
                        "p50": float(r.p50),
                        "brecha_tasa": float(r.brecha_tasa),
                        "brecha_vol": float(r.brecha_vol),
                        "ratio": float(r.ratio),
                    }
                    for r in j.itertuples(index=False)
                ],
            }
        )
    por_pozo.sort(key=lambda p: p["brecha_acum"])
    return {
        "tasa": tasa,
        "unidad_volumen": unidad_vol,
        "mes_max": int(mes_max),
        "n_pozos": len(por_pozo),
        "total": {
            "acum_mio": tot_mio,
            "acum_p50": tot_p50,
            "brecha_acum": tot_mio - tot_p50,
            "brecha_acum_pct": 100.0 * (tot_mio - tot_p50) / tot_p50 if tot_p50 else None,
            "pozos_debajo_p50_acum": sum(1 for p in por_pozo if p["brecha_acum"] < 0),
        },
        "pozos": por_pozo,
        "sin_comparar": errores,
    }
