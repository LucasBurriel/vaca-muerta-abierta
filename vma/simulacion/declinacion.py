"""Decline-curve fits with an honest band (ADR-031).

Models, with ``t`` in months from first production (mid-month: ``t = mes + 0.5``) and ``q`` the producing-day rate:

- exponential: ``q = qi · exp(-D t)``
- hyperbolic:  ``q = qi · (1 + b D t)^(-1/b)``, ``0 < b <= 2``; switched to exponential once the instantaneous
  decline falls to ``d_min`` (modified Arps, the usual guard against b > 1 running forever)
- harmonic:    hyperbolic with ``b = 1``
- Duong:       ``q = q1 · t^(-m) · exp(a / (1 - m) · (t^(1 - m) - 1))`` (``m != 1``), the long-transient model used
  for shale; after the fitted window it is also capped by ``d_min``

Fitting is least squares on ``ln q`` (so early months do not dominate), done with linear algebra on a grid of the
non-linear parameter (``b`` for hyperbolic, ``m`` for Duong): for a fixed ``b``, ``q^(-b)`` is linear in ``t``; for a
fixed ``m``, ``ln q`` is linear in ``(1, ln t, g(t))``. No optimiser, no SciPy, deterministic. The model is chosen
by AIC on the log residuals unless the user names one. The band is a bootstrap of the residuals: resample them with
replacement, add to the fitted log curve, refit, recompute the EUR; P10/P50/P90 of those EURs (P10 high).

EUR integrates the forecast rate over calendar months to the horizon, with the well's observed uptime (producing
days / calendar days) and an optional economic rate limit. It is the volume the *curve* implies, not a reserve:
no price, no cost, no operations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MODELOS = ("exponencial", "hiperbolico", "armonico", "duong")
DIAS_MES = 365.25 / 12
B_GRID = np.round(np.arange(0.05, 2.0001, 0.05), 2)
M_GRID = np.round(np.concatenate([np.arange(0.50, 0.99, 0.02), np.arange(1.02, 1.80, 0.02)]), 2)
MIN_PUNTOS = 6
D_MIN_ANUAL = 0.06  # terminal (exponential) decline once the curve flattens below it
OMITIR_MESES = 2  # first months (cleanup, flowback, ramp-up) are not part of the decline


class ErrorAjuste(ValueError):
    """The series cannot be fitted as asked; the message is for the model to read."""


@dataclass
class Ajuste:
    modelo: str
    parametros: dict  # qi, D (1/mes), b | q1, a, m ; all in months
    t: np.ndarray  # the fitted abscissa (months, mid-month)
    q: np.ndarray  # the fitted ordinate (rate)
    residuos_log: np.ndarray
    sse_log: float
    aic: float
    n: int

    @property
    def rmse_log(self) -> float:
        return float(math.sqrt(self.sse_log / self.n)) if self.n else float("nan")


@dataclass
class Pronostico:
    ajuste: Ajuste
    horizonte_meses: int
    uptime: float
    q_min: float | None
    d_min_anual: float
    meses: np.ndarray  # 0..H-1 (calendar months from first production)
    tasa: (
        np.ndarray
    )  # forecast producing-day rate per month (history replaced by the fit from the fit window on)
    volumen_mes: np.ndarray  # rate × days × uptime (0 after the economic limit)
    acumulado: np.ndarray
    eur: float
    mes_limite: int | None  # first month under q_min, if any
    historia_acum: float  # observed cumulative volume up to the last history month
    bootstrap: dict = field(default_factory=dict)  # eur_p10, eur_p50, eur_p90, n, parametros_p50...


# --- the models ------------------------------------------------------------------------------------------------------


def tasa_modelo(modelo: str, p: dict, t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=float)
    if modelo == "exponencial":
        return p["qi"] * np.exp(-p["D"] * t)
    if modelo in ("hiperbolico", "armonico"):
        b, D = p["b"], p["D"]
        return p["qi"] * np.power(1.0 + b * D * t, -1.0 / b)
    if modelo == "duong":
        a, m, q1 = p["a"], p["m"], p["q1"]
        t = np.maximum(t, 1e-6)
        return q1 * np.power(t, -m) * np.exp(a / (1.0 - m) * (np.power(t, 1.0 - m) - 1.0))
    raise ErrorAjuste(f"modelo {modelo!r} desconocido; los modelos son {', '.join(MODELOS)}")


def declinacion_instantanea(modelo: str, p: dict, t: np.ndarray) -> np.ndarray:
    """-d ln q / dt in 1/month, for the terminal-decline switch."""
    t = np.asarray(t, dtype=float)
    if modelo == "exponencial":
        return np.full_like(t, p["D"])
    if modelo in ("hiperbolico", "armonico"):
        return p["D"] / (1.0 + p["b"] * p["D"] * t)
    if modelo == "duong":
        a, m = p["a"], p["m"]
        t = np.maximum(t, 1e-6)
        return m / t - a * np.power(t, -m)
    raise ErrorAjuste(modelo)


def tasa_con_d_min(modelo: str, p: dict, t: np.ndarray, d_min_mes: float) -> np.ndarray:
    """The model's rate, switched to exponential at ``d_min`` once its instantaneous decline falls under it."""
    t = np.asarray(t, dtype=float)
    q = tasa_modelo(modelo, p, t)
    if d_min_mes <= 0:
        return q
    dec = declinacion_instantanea(modelo, p, t)
    bajo = np.where(dec < d_min_mes)[0]
    if bajo.size == 0:
        return q
    i = int(bajo[0])
    if modelo == "duong" and dec[i] < 0:  # Duong can turn upward with a bad a/m: cap from its maximum
        pass
    t_sw, q_sw = t[i], q[i]
    q = q.copy()
    q[i:] = q_sw * np.exp(-d_min_mes * (t[i:] - t_sw))
    return q


# --- fitting ------------------------------------------------------------------------------------------------------------


def _lin(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef


def _aic(sse: float, n: int, k: int) -> float:
    sse = max(sse, 1e-12)
    return n * math.log(sse / n) + 2 * k


def ajustar(t: np.ndarray, q: np.ndarray, modelo: str) -> Ajuste:
    """Fit one model to (t, q); t in months (mid-month), q > 0."""
    t = np.asarray(t, dtype=float)
    q = np.asarray(q, dtype=float)
    ok = np.isfinite(t) & np.isfinite(q) & (q > 0)
    t, q = t[ok], q[ok]
    n = int(t.size)
    if n < MIN_PUNTOS:
        raise ErrorAjuste(f"se necesitan al menos {MIN_PUNTOS} meses con tasa > 0 para ajustar; hay {n}")
    lq = np.log(q)
    if modelo == "exponencial":
        c = _lin(np.column_stack([np.ones(n), t]), lq)
        p = {"qi": float(math.exp(c[0])), "D": float(max(-c[1], 1e-6))}
        k = 2
    elif modelo in ("hiperbolico", "armonico"):
        mejor = None
        grid = [1.0] if modelo == "armonico" else B_GRID
        for b in grid:
            y = np.power(q, -b)
            c = _lin(np.column_stack([np.ones(n), t]), y)
            A, B = float(c[0]), float(c[1])
            if A <= 0 or B <= 0:
                continue
            qi = A ** (-1.0 / b)
            D = B / (A * b)
            pr = {"qi": float(qi), "D": float(D), "b": float(b)}
            sse = float(np.sum((np.log(tasa_modelo("hiperbolico", pr, t)) - lq) ** 2))
            if mejor is None or sse < mejor[0]:
                mejor = (sse, pr)
        if mejor is None:
            raise ErrorAjuste(
                f"{modelo}: la serie no declina (ninguna b da D > 0); probá exponencial o mirá los datos"
            )
        p = mejor[1]
        k = 2 if modelo == "armonico" else 3
    elif modelo == "duong":
        mejor = None
        tt = np.maximum(t, 1e-6)
        for m in M_GRID:
            g = (np.power(tt, 1.0 - m) - 1.0) / (1.0 - m)
            c = _lin(np.column_stack([np.ones(n), g]), lq + m * np.log(tt))
            pr = {"q1": float(math.exp(c[0])), "a": float(c[1]), "m": float(m)}
            if pr["a"] <= 0 or pr["a"] >= pr["m"] * 3:  # a must be positive and smaller than m·t^(m-1) soon
                continue
            sse = float(np.sum((np.log(tasa_modelo("duong", pr, t)) - lq) ** 2))
            if mejor is None or sse < mejor[0]:
                mejor = (sse, pr)
        if mejor is None:
            raise ErrorAjuste("duong: no hay (a, m) admisibles para esta serie; probá hiperbolico")
        p = mejor[1]
        k = 3
    else:
        raise ErrorAjuste(f"modelo {modelo!r} desconocido; los modelos son {', '.join(MODELOS)}")
    pred = np.log(tasa_modelo(modelo, p, t))
    res = lq - pred
    sse = float(np.sum(res**2))
    return Ajuste(
        modelo=modelo, parametros=p, t=t, q=q, residuos_log=res, sse_log=sse, aic=_aic(sse, n, k), n=n
    )


def ajustar_auto(
    t: np.ndarray, q: np.ndarray, candidatos: tuple[str, ...] = MODELOS
) -> tuple[Ajuste, list[dict]]:
    """Fit every candidate, return the lowest AIC and the comparison table (errors included as text)."""
    tabla, ajustes = [], []
    for m in candidatos:
        try:
            a = ajustar(t, q, m)
            ajustes.append(a)
            tabla.append({"modelo": m, "aic": a.aic, "rmse_log": a.rmse_log, "parametros": a.parametros})
        except ErrorAjuste as e:
            tabla.append({"modelo": m, "error": str(e)})
    if not ajustes:
        raise ErrorAjuste("ningún modelo ajusta: " + "; ".join(f"{r['modelo']}: {r['error']}" for r in tabla))
    mejor = min(ajustes, key=lambda a: a.aic)
    for r in tabla:
        r["elegido"] = r["modelo"] == mejor.modelo
    return mejor, tabla


# --- forecast and EUR -----------------------------------------------------------------------------------------------


def pronosticar(
    ajuste: Ajuste,
    mes_hist: np.ndarray,
    vol_hist: np.ndarray,
    uptime: float,
    horizonte_meses: int,
    q_min: float | None = None,
    d_min_anual: float = D_MIN_ANUAL,
) -> Pronostico:
    """History (observed monthly volumes by month index) + the fitted curve from the last history month to the horizon."""
    mes_hist = np.asarray(mes_hist, dtype=int)
    vol_hist = np.asarray(vol_hist, dtype=float)
    ultimo = int(mes_hist.max()) if mes_hist.size else -1
    H = int(horizonte_meses)
    meses = np.arange(0, max(H, ultimo + 1))
    t = meses + 0.5
    d_min_mes = -math.log(1.0 - d_min_anual) / 12.0 if 0 < d_min_anual < 1 else 0.0
    tasa = tasa_con_d_min(ajuste.modelo, ajuste.parametros, t, d_min_mes)
    vol = tasa * DIAS_MES * uptime
    # history months keep what was observed
    hist = np.zeros_like(vol)
    hist_mask = np.zeros(vol.size, dtype=bool)
    for m, v in zip(mes_hist, vol_hist, strict=True):
        if 0 <= m < vol.size:
            hist[m] = v
            hist_mask[m] = True
    vol = np.where(hist_mask, hist, vol)
    mes_limite = None
    if q_min is not None and q_min > 0:
        bajo = np.where((~hist_mask) & (tasa < q_min))[0]
        if bajo.size:
            mes_limite = int(bajo[0])
            vol[mes_limite:] = 0.0
    vol = vol[:H] if vol.size > H else vol
    tasa = tasa[: vol.size]
    meses = meses[: vol.size]
    acum = np.cumsum(vol)
    return Pronostico(
        ajuste=ajuste,
        horizonte_meses=H,
        uptime=float(uptime),
        q_min=q_min,
        d_min_anual=d_min_anual,
        meses=meses,
        tasa=tasa,
        volumen_mes=vol,
        acumulado=acum,
        eur=float(acum[-1]) if acum.size else 0.0,
        mes_limite=mes_limite,
        historia_acum=float(vol_hist.sum()),
    )


def bootstrap_eur(
    ajuste: Ajuste,
    mes_hist: np.ndarray,
    vol_hist: np.ndarray,
    uptime: float,
    horizonte_meses: int,
    q_min: float | None,
    d_min_anual: float,
    n: int = 200,
    semilla: int = 0,
) -> dict:
    """Residual bootstrap on the log rate: refit the same model on perturbed series, collect EURs."""
    rng = np.random.default_rng(semilla)
    base_log = np.log(tasa_modelo(ajuste.modelo, ajuste.parametros, ajuste.t))
    eurs, params = [], []
    fallos = 0
    for _ in range(int(n)):
        res = rng.choice(ajuste.residuos_log, size=ajuste.residuos_log.size, replace=True)
        q_b = np.exp(base_log + res)
        try:
            a_b = ajustar(ajuste.t, q_b, ajuste.modelo)
        except ErrorAjuste:
            fallos += 1
            continue
        pr = pronosticar(a_b, mes_hist, vol_hist, uptime, horizonte_meses, q_min, d_min_anual)
        eurs.append(pr.eur)
        params.append(a_b.parametros)
    if len(eurs) < 20:
        return {
            "n": len(eurs),
            "fallos": fallos,
            "sin_dato_porque": "menos de 20 réplicas válidas; sin banda",
        }
    e = np.asarray(eurs)
    return {
        "n": len(eurs),
        "fallos": fallos,
        "eur_p10": float(np.percentile(e, 90)),  # oil convention: P10 is the high case
        "eur_p50": float(np.percentile(e, 50)),
        "eur_p90": float(np.percentile(e, 10)),
        "eur_media": float(e.mean()),
        "parametros_p50": {k: float(np.median([p[k] for p in params])) for k in params[0]},
    }


def resumen_pronostico(pr: Pronostico, cada: int = 12) -> dict:
    """JSON-friendly view: parameters, EUR, yearly checkpoints and the band."""
    p = pr.ajuste.parametros
    anual = []
    for m in range(cada - 1, pr.meses.size, cada):
        anual.append(
            {
                "mes": int(m),
                "anio": (m + 1) // 12,
                "tasa": float(pr.tasa[m]),
                "acumulado": float(pr.acumulado[m]),
            }
        )
    d_efectiva_anual = None
    if pr.ajuste.modelo == "exponencial":
        d_efectiva_anual = 1.0 - math.exp(-p["D"] * 12)
    return {
        "modelo": pr.ajuste.modelo,
        "parametros": {k: float(v) for k, v in p.items()},
        "unidades_parametros": "t en meses desde la primera producción (medio mes); D en 1/mes; qi, q1 en la unidad de la tasa",
        "declinacion_efectiva_anual_inicial": d_efectiva_anual,
        "n_meses_ajustados": pr.ajuste.n,
        "rmse_log": pr.ajuste.rmse_log,
        "aic": pr.ajuste.aic,
        "horizonte_meses": pr.horizonte_meses,
        "uptime": pr.uptime,
        "d_min_anual": pr.d_min_anual,
        "q_min": pr.q_min,
        "mes_limite_economico": pr.mes_limite,
        "historia_acumulada": pr.historia_acum,
        "eur": pr.eur,
        "eur_restante": pr.eur - pr.historia_acum,
        "por_anio": anual,
        "banda_bootstrap": pr.bootstrap,
    }
