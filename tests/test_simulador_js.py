"""The browser Monte Carlo (site/js/montecarlo.js, ADR-036) against the Python one, run under Node.

Skipped cleanly when Node is not installed: the site itself needs no Node, only this cross-check does. The two
implementations use different random generators, so the comparison is statistical: the same curve, the same
parameters, and the P50 (and the band) of the campaign must agree within a few percent.
"""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vma import site as S
from vma.simulacion import campania as SC

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed; the JS core is not exercised")


def _curva(meses: int = 40) -> pd.DataFrame:
    mes = np.arange(meses)
    p50 = 120.0 * np.power(1.0 + 1.1 * 0.25 * (mes + 0.5), -1.0 / 1.1)
    return pd.DataFrame({"mes": mes, "p10": 1.7 * p50, "p50": p50, "p90": 0.45 * p50})


def _correr(tmp_path: Path, casos: list[dict]) -> subprocess.CompletedProcess:
    entrada = tmp_path / "casos.json"
    entrada.write_text(json.dumps({"casos": casos}), encoding="utf-8")
    return subprocess.run(
        [NODE, str(ROOT / "tests" / "js" / "correr_montecarlo.mjs"), str(entrada)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _node(tmp_path: Path, casos: list[dict]) -> dict:
    r = _correr(tmp_path, casos)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _extendida(curva: pd.DataFrame, meses: int = 120) -> dict:
    """The curve as simulador.json ships it: extended by the shared function, rounded for transport."""
    e = SC.cuantiles_extendidos(curva, meses)
    return {s: [S.sig(float(v)) for v in e[s]] for s in ("p10", "p50", "p90")}


def test_js_helpers_match_python(tmp_path):
    out = _node(tmp_path, [])
    assert out["percentil"] == pytest.approx(
        [np.percentile([1, 2, 3, 4], 50), np.percentile([1, 2, 3, 4], 90)]
    )
    py = SC._tasa_desde_percentil(
        np.array([10.0, 50.0, 90.0, 30.0]), np.full(4, 150.0), np.full(4, 100.0), np.full(4, 50.0)
    )
    assert out["inversa"] == pytest.approx(py.tolist())
    assert out["inicios"] == np.repeat(np.arange(3), 4)[:10].tolist()
    assert out["rng_reproducible"] is True


@pytest.mark.parametrize(
    "kw",
    [
        {"n_pozos": 12, "meses": 120, "ritmo": 2, "uptime": 0.92},
        {"n_pozos": 40, "meses": 60, "ritmo": None, "uptime": 0.85},
        {"n_pozos": 3, "meses": 30, "ritmo": 1, "uptime": 1.0},
    ],
)
def test_js_campaign_matches_python_within_a_few_percent(tmp_path, kw):
    curva = _curva()
    py = SC.simular(curva, n_sim=500, semilla=0, **kw)
    caso = {
        "petroleo": _extendida(curva),
        "nPozos": kw["n_pozos"],
        "meses": kw["meses"],
        "ritmo": kw["ritmo"],
        "uptime": kw["uptime"],
        "nSim": 500,
        "semilla": 0,
        "precioPetroleo": 500.0,
        "tasaAnual": 0.10,
    }
    out = _node(tmp_path, [caso])["casos"][0]
    assert out["igual_por_partes"] is True
    js = out["resultado"]
    f = js["fluidos"]["petroleo"]
    assert js["pozos_en_linea"] == py["pozos_en_linea"]
    assert js["ritmo_pozos_por_mes"] == py["ritmo_pozos_por_mes"]
    # the headline: cumulative P50 of the campaign
    assert f["final"]["acumulado"]["p50"] == pytest.approx(py["final"]["acumulado_p50"], rel=0.03)
    assert f["final"]["acumulado"]["media"] == pytest.approx(py["final"]["acumulado_media"], rel=0.03)
    # the band: its width is noisier than its centre (500 draws of a different generator)
    ancho_py = py["final"]["acumulado_p10"] - py["final"]["acumulado_p90"]
    ancho_js = f["final"]["acumulado"]["p10"] - f["final"]["acumulado"]["p90"]
    assert ancho_js == pytest.approx(ancho_py, rel=0.20)
    assert f["final"]["acumulado"]["p90"] < f["final"]["acumulado"]["p50"] < f["final"]["acumulado"]["p10"]
    assert f["final"]["tasa_pico_p50"] == pytest.approx(py["final"]["tasa_pico_p50"], rel=0.05)
    assert abs(f["final"]["mes_pico_p50"] - py["final"]["mes_pico_p50"]) <= 1
    # month by month, the P50 of the aggregated rate and of the cumulative. The median of 500 runs has a sampling
    # error that grows as the campaign shrinks (three wells do not average the dispersion out), so the tolerance
    # is wider there: it is Monte Carlo noise between two generators, not a difference of method.
    tol = 0.06 if kw["n_pozos"] >= 12 else 0.12
    for clave in ("tasa_agregada", "acumulado"):
        a, b = np.array(f[clave]["p50"]), np.array(py[clave]["p50"])
        assert np.allclose(a, b, rtol=tol), clave
    # money: gross revenue is volume x price in every simulation; the NPV discounts month k by (1 + r)^(-k/12)
    assert js["usd"]["final"]["ingreso"]["p50"] == pytest.approx(
        500.0 * f["final"]["acumulado"]["p50"], rel=1e-9
    )
    vol = np.diff(np.array(f["acumulado"]["media"]), prepend=0.0)
    van = float((vol * 500.0 * (1.10) ** (-np.arange(kw["meses"]) / 12.0)).sum())
    assert js["usd"]["final"]["van"]["media"] == pytest.approx(van, rel=1e-9)


def test_js_lateral_scale_royalty_and_two_fluids(tmp_path):
    ext = _extendida(_curva())
    gas = {s: [v / 10.0 for v in ext[s]] for s in ext}
    base = {"petroleo": ext, "nPozos": 5, "meses": 48, "nSim": 200, "semilla": 3, "precioPetroleo": 400.0}
    casos = [
        base,
        {**base, "escalaPetroleo": 2.0},
        {**base, "regalia": 0.12},
        {**base, "gas": gas, "precioGas": 150.0},
    ]
    r = [c["resultado"] for c in _node(tmp_path, casos)["casos"]]
    a0 = r[0]["fluidos"]["petroleo"]["final"]["acumulado"]["p50"]
    assert r[1]["fluidos"]["petroleo"]["final"]["acumulado"]["p50"] == pytest.approx(2.0 * a0)
    assert r[2]["usd"]["final"]["van"]["p50"] == pytest.approx(0.88 * r[0]["usd"]["final"]["van"]["p50"])
    # gas shares the well's position: a tenth of the oil volume, valued at its own price, in the same simulation
    g = r[3]["fluidos"]["gas"]["final"]["acumulado"]["p50"]
    assert g == pytest.approx(a0 / 10.0)
    assert r[3]["usd"]["final"]["ingreso"]["p50"] == pytest.approx(400.0 * a0 + 150.0 * g)
    assert r[3]["equivalente_final"]["p50"] == pytest.approx(a0 + g)


def test_js_rejects_out_of_range_parameters(tmp_path):
    r = _correr(tmp_path, [{"petroleo": _extendida(_curva()), "nPozos": 0, "meses": 12}])
    assert r.returncode != 0 and "n_pozos" in r.stderr


def test_js_on_the_committed_simulador_json(tmp_path):
    """The default group of the page, on the real file when it is there: JS on the shipped curve against Python
    on the same shipped curve (already extended, so Python extends nothing)."""
    ruta = ROOT / "site" / "data" / "simulador.json"
    if not ruta.exists():
        pytest.skip("site/data/simulador.json not generated")
    D = json.loads(ruta.read_text(encoding="utf-8"))
    cand = [
        g
        for g in D["grupos"]
        if g["formacion"] == "Vaca Muerta"
        and g["ventana"] == "petroleo"
        and "petroleo_m3_d" in g["curvas"]
        and g["curvas"]["petroleo_m3_d"]["publicados"] >= 24
        and g["curvas"]["petroleo_m3_d"]["validos"] == D["meses"]
    ]
    if not cand:
        pytest.skip("no Vaca Muerta oil-window group with 24 published months in this snapshot")
    g = max(cand, key=lambda x: x["cohorte"])
    c = g["curvas"]["petroleo_m3_d"]
    curva = pd.DataFrame({"mes": range(D["meses"]), "p10": c["p10"], "p50": c["p50"], "p90": c["p90"]})
    py = SC.simular(curva, n_pozos=12, meses=D["meses"], ritmo=2, n_sim=500, semilla=0)
    assert py["meses_extrapolados"] == 0
    caso = {"petroleo": c, "nPozos": 12, "meses": D["meses"], "ritmo": 2, "nSim": 500, "semilla": 0}
    js = _node(tmp_path, [caso])["casos"][0]["resultado"]["fluidos"]["petroleo"]
    assert js["final"]["acumulado"]["p50"] == pytest.approx(py["final"]["acumulado_p50"], rel=0.03)
    assert js["final"]["por_pozo"]["p50"] == pytest.approx(py["final"]["por_pozo_p50"], rel=0.03)
