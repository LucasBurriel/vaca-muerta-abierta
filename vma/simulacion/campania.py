"""Campaign Monte Carlo from a published type curve (ADR-031).

What is sampled is the **dispersion between wells that the published curve shows**: each simulated well draws a
position ``u`` in the group (uniform), keeps it through its life with a small monthly jitter in percentile space,
and its rate at each month is read from the P90/P50/P10 of that month by log-linear interpolation (the inverse of
``vma.propios.comparar.percentil_en_curva``). Beyond the last published month the three quantile curves are
extended with a hyperbolic fit of each quantile (``vma.simulacion.declinacion``) so a 10-year campaign can be
summed; where two extended tails would cross, the P10 or P90 tail follows the P50 (ADR-036). If the per-metre curve is published for the group and a lateral is given, the per-metre rate is sampled
and multiplied by the lateral; otherwise the absolute curve is used and the lateral is ignored (said in the notes).

Wells start staggered at ``ritmo`` wells per month from month 0. Output: for every calendar month of the campaign,
the P10/P50/P90 (and mean) across simulations of the aggregated producing-day rate and of the cumulative volume,
with the number of wells on line; and the final cumulative with its band. There is no interference between wells,
no facility constraint, no downtime beyond the uptime factor, no price: the band is only the published dispersion.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from vma.simulacion import declinacion as DC

DIAS_MES = DC.DIAS_MES
N_SIM_MAX = 2000
N_POZOS_MAX = 500
MESES_MAX = 360
FRAC_BASE = (
    0.5  # the tail is spliced at the last month that still has this share of the group's wells (ADR-038)
)


class ErrorSimulacion(ValueError):
    """The campaign cannot be simulated as asked; the message is for the model to read."""


def _extender_cuantil(mes: np.ndarray, q: np.ndarray, hasta: int, d_min_anual: float) -> np.ndarray:
    """Extend one quantile curve to month ``hasta - 1`` with a hyperbolic (fallback exponential) fit of its tail."""
    out = np.full(hasta, np.nan)
    out[mes[mes < hasta]] = q[mes < hasta]
    ultimo = int(mes.max())
    if ultimo >= hasta - 1:
        return out
    desde = max(DC.OMITIR_MESES, ultimo - 36)
    sel = (mes >= desde) & (q > 0)
    try:
        aj = DC.ajustar(mes[sel] + 0.5, q[sel], "hiperbolico")
    except DC.ErrorAjuste:
        try:
            aj = DC.ajustar(mes[sel] + 0.5, q[sel], "exponencial")
        except DC.ErrorAjuste:
            return out
    d_min_mes = -math.log(1.0 - d_min_anual) / 12.0 if 0 < d_min_anual < 1 else 0.0
    t_ext = np.arange(ultimo + 1, hasta) + 0.5
    cola = DC.tasa_con_d_min(aj.modelo, aj.parametros, t_ext, d_min_mes)
    # splice continuously: scale the tail so it starts at the last published value
    pred_ult = DC.tasa_con_d_min(aj.modelo, aj.parametros, np.array([ultimo + 0.5]), d_min_mes)[0]
    if pred_ult > 0 and q[mes == ultimo].size:
        cola = cola * (float(q[mes == ultimo][0]) / pred_ult)
    out[ultimo + 1 :] = cola
    return out


def cuantiles_extendidos(curva: pd.DataFrame, hasta: int, d_min_anual: float = DC.D_MIN_ANUAL) -> dict:
    """The three quantile curves of a group, cleaned and extended to ``hasta`` months: what the Monte Carlo samples.

    ``curva``: columns mes, p10, p50, p90 and optionally ``n`` (wells behind each month). Months with a null or
    non-positive quantile are dropped; at least ``DC.MIN_PUNTOS`` must remain. With ``n``, the months after the last
    one that still has ``FRAC_BASE`` of the group's peak well count are not sampled: in a young cohort they are the
    few oldest wells, their quantiles jump, and a tail spliced there carries the jump for the rest of the well's
    life (ADR-038). They are extrapolated like the rest of the tail and counted in ``meses_descartados``;
    ``ultimo_mes`` is then the splice month, not the last published one. Returns ``p10``/``p50``/``p90`` (arrays of length ``hasta``, NaN where there is
    neither a published value nor an extension), ``valido`` (the three are present), ``meses_publicados``,
    ``ultimo_mes`` (last published month), ``meses_extrapolados`` (months asked beyond it) and ``meses_acotados``
    (extrapolated months where a crossing tail was held on the P50, see below). Shared by
    :func:`simular` and by the site's ``simulador.json`` (``vma/site.py``, ADR-036), so the browser samples exactly
    the curves the Python simulator samples.
    """
    c = curva.dropna(subset=["p10", "p50", "p90"]).sort_values("mes")
    c = c[(c.p90 > 0) & (c.p50 > 0) & (c.p10 > 0)]
    if len(c) < DC.MIN_PUNTOS:
        raise ErrorSimulacion(
            f"la curva tiene {len(c)} meses publicables con P10/P50/P90 > 0; se necesitan {DC.MIN_PUNTOS}"
        )
    descartados = 0
    if "n" in c and c.n.notna().any():
        firme = c[c.n >= FRAC_BASE * c.n.max()]
        if len(firme) >= DC.MIN_PUNTOS:
            corte = int(firme.mes.max())
            descartados = int((c.mes > corte).sum())
            c = c[c.mes <= corte]
    hasta = int(hasta)
    mes_arr = c.mes.to_numpy(dtype=int)
    q10 = _extender_cuantil(mes_arr, c.p10.to_numpy(dtype=float), hasta, d_min_anual)
    q50 = _extender_cuantil(mes_arr, c.p50.to_numpy(dtype=float), hasta, d_min_anual)
    q90 = _extender_cuantil(mes_arr, c.p90.to_numpy(dtype=float), hasta, d_min_anual)
    ultimo = int(mes_arr.max())
    valido = ~(np.isnan(q10) | np.isnan(q50) | np.isnan(q90))
    # The three tails are fitted independently and can cross far from the data, which would turn the band inside
    # out. Published months are never touched; in the extrapolated ones a P10 or P90 tail that meets the P50 tail
    # follows it from there on (ADR-036). ``meses_acotados`` counts the months where this guard acted.
    cola = valido & (np.arange(hasta) > ultimo)
    cruzado = cola & ((q10 < q50) | (q90 > q50))
    q10 = np.where(cola, np.fmax(q10, q50), q10)
    q90 = np.where(cola, np.fmin(q90, q50), q90)
    return {
        "p10": q10,
        "p50": q50,
        "p90": q90,
        "valido": valido,
        "meses_publicados": int(len(c)),
        "ultimo_mes": ultimo,
        "meses_extrapolados": int(hasta - 1 - ultimo) if hasta - 1 > ultimo else 0,
        "meses_acotados": int(cruzado.sum()),
        "meses_descartados": descartados,
    }


def _tasa_desde_percentil(u: np.ndarray, p10: np.ndarray, p50: np.ndarray, p90: np.ndarray) -> np.ndarray:
    """Inverse of ``percentil_en_curva``: exceedance percentile ``u`` (0-100, 10 = high) -> rate, log-linear
    between the three quantiles of each month (arrays of the same shape as ``u``)."""
    lp90, lp50, lp10 = np.log(p90), np.log(p50), np.log(p10)
    u = np.clip(np.asarray(u, dtype=float), 1.0, 99.0)
    y = np.where(
        u >= 50.0,
        lp50 + (u - 50.0) / 40.0 * (lp90 - lp50),
        lp50 + (50.0 - u) / 40.0 * (lp10 - lp50),
    )
    return np.exp(y)


def simular(
    curva: pd.DataFrame,
    n_pozos: int,
    meses: int,
    rama_m: float | None = None,
    por_metro: bool = False,
    ritmo: int | None = None,
    n_sim: int = 500,
    semilla: int = 0,
    uptime: float = 0.92,
    jitter_percentil: float = 8.0,
    d_min_anual: float = DC.D_MIN_ANUAL,
) -> dict:
    """``curva``: columns mes, p10, p50, p90 and optionally n (publishable months only). Returns the aggregated bands per month."""
    n_pozos, meses, n_sim = int(n_pozos), int(meses), int(n_sim)
    if not (1 <= n_pozos <= N_POZOS_MAX):
        raise ErrorSimulacion(f"n_pozos debe estar entre 1 y {N_POZOS_MAX}")
    if not (1 <= meses <= MESES_MAX):
        raise ErrorSimulacion(f"meses debe estar entre 1 y {MESES_MAX}")
    if not (10 <= n_sim <= N_SIM_MAX):
        raise ErrorSimulacion(f"n_sim debe estar entre 10 y {N_SIM_MAX}")
    ritmo = int(ritmo) if ritmo else n_pozos
    ritmo = max(1, min(ritmo, n_pozos))
    inicios = np.repeat(np.arange(math.ceil(n_pozos / ritmo)), ritmo)[:n_pozos]  # month each well starts
    vida = meses  # a well needs at most `meses` months of curve
    ext = cuantiles_extendidos(curva, vida, d_min_anual)
    q10, q50, q90, valido = ext["p10"], ext["p50"], ext["p90"], ext["valido"]
    extendidos = ext["meses_extrapolados"]
    escala = float(rama_m) if (por_metro and rama_m) else 1.0

    rng = np.random.default_rng(semilla)
    tasa_agg = np.zeros((n_sim, meses))  # aggregated producing-day rate per calendar month
    vol_agg = np.zeros((n_sim, meses))
    en_linea = np.zeros(meses, dtype=int)
    for m in range(meses):
        en_linea[m] = int((inicios <= m).sum())
    for s in range(n_sim):
        u0 = rng.uniform(1.0, 99.0, size=n_pozos)
        for w in range(n_pozos):
            i0 = int(inicios[w])
            if i0 >= meses:
                continue
            k = np.arange(0, meses - i0)  # well months
            kk = k[valido[k]]
            if kk.size == 0:
                continue
            u = np.clip(u0[w] + rng.normal(0.0, jitter_percentil, size=kk.size), 1.0, 99.0)
            q = _tasa_desde_percentil(u, q10[kk], q50[kk], q90[kk]) * escala
            tasa_agg[s, i0 + kk] += q
            vol_agg[s, i0 + kk] += q * DIAS_MES * uptime
    acum = np.cumsum(vol_agg, axis=1)

    def banda(a: np.ndarray) -> dict:
        return {
            "p10": np.percentile(a, 90, axis=0).tolist(),
            "p50": np.percentile(a, 50, axis=0).tolist(),
            "p90": np.percentile(a, 10, axis=0).tolist(),
            "media": a.mean(axis=0).tolist(),
        }

    final = acum[:, -1]
    por_pozo = final / n_pozos
    return {
        "n_pozos": n_pozos,
        "meses": meses,
        "ritmo_pozos_por_mes": ritmo,
        "n_sim": n_sim,
        "semilla": int(semilla),
        "uptime": uptime,
        "jitter_percentil": jitter_percentil,
        "rama_m": float(rama_m) if rama_m else None,
        "escala_por_metro": por_metro and bool(rama_m),
        "meses_curva_publicados": ext["meses_publicados"],
        "meses_extrapolados": extendidos,
        "meses_acotados": ext["meses_acotados"],
        "meses_descartados": ext["meses_descartados"],
        "mes": list(range(meses)),
        "pozos_en_linea": en_linea.tolist(),
        "tasa_agregada": banda(tasa_agg),
        "acumulado": banda(acum),
        "final": {
            "acumulado_p10": float(np.percentile(final, 90)),
            "acumulado_p50": float(np.percentile(final, 50)),
            "acumulado_p90": float(np.percentile(final, 10)),
            "acumulado_media": float(final.mean()),
            "por_pozo_p10": float(np.percentile(por_pozo, 90)),
            "por_pozo_p50": float(np.percentile(por_pozo, 50)),
            "por_pozo_p90": float(np.percentile(por_pozo, 10)),
            "tasa_pico_p50": float(np.percentile(tasa_agg.max(axis=1), 50)),
            "mes_pico_p50": int(np.median(tasa_agg.argmax(axis=1))),
        },
    }
