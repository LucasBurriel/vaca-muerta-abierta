// Campaign Monte Carlo in the browser (ADR-036). DOM-free: the page (simulador.js) and Node (tests/js) import it.
//
// It mirrors vma/simulacion/campania.py `simular()` step by step:
//   - every simulated well draws a position u ~ U(1, 99) in the group (exceedance percentile, 10 = high case);
//   - it keeps it through its life with a monthly jitter N(0, sigma) in percentile space, clipped to [1, 99];
//   - its rate each month is read from the P90/P50/P10 of that month by log-linear interpolation;
//   - wells start staggered, `ritmo` per month from month 0;
//   - monthly volume = producing-day rate x days per month x uptime;
//   - per calendar month, P10/P50/P90 (P10 high) and mean across simulations of the aggregated rate and cumulative.
// The quantile curves arrive already extended (site/data/simulador.json, written by vma/site.py with the same
// function the Python simulator uses), so nothing is fitted here.
//
// Two things differ from Python and are declared: the random generator (mulberry32 + Box-Muller instead of NumPy's
// PCG64, so results agree statistically, not draw by draw) and the money: here oil and gas of a well share the
// same position u, and gross revenue and its NPV are computed inside every simulation, then banded.

export const N_SIM_MAX = 2000;
export const N_POZOS_MAX = 500;
export const MESES_MAX = 120;

// --- seeded random numbers ------------------------------------------------------------------------------------------

export function crearRng(semilla) {
  let a = (Number(semilla) || 0) >>> 0;
  let guardado = null; // second Box-Muller deviate
  const uniforme = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const normal = () => {
    if (guardado !== null) {
      const z = guardado;
      guardado = null;
      return z;
    }
    let u1 = uniforme();
    if (u1 < 1e-300) u1 = 1e-300;
    const r = Math.sqrt(-2 * Math.log(u1)), th = 2 * Math.PI * uniforme();
    guardado = r * Math.sin(th);
    return r * Math.cos(th);
  };
  return { uniforme, normal };
}

// --- pieces shared with the Python implementation ---------------------------------------------------------------------

/** Exceedance percentile u (0-100, 10 = high) -> rate, log-linear between the three quantiles of the month. */
export function tasaDesdePercentil(u, p10, p50, p90) {
  const x = Math.min(99, Math.max(1, u));
  const l50 = Math.log(p50);
  const y = x >= 50 ? l50 + ((x - 50) / 40) * (Math.log(p90) - l50) : l50 + ((50 - x) / 40) * (Math.log(p10) - l50);
  return Math.exp(y);
}

/** Month in which each well starts: `ritmo` wells per month from month 0. */
export function inicios(nPozos, ritmo) {
  const r = Math.max(1, Math.min(Math.trunc(ritmo) || nPozos, nPozos));
  return Array.from({ length: nPozos }, (_, w) => Math.floor(w / r));
}

/** numpy.percentile (linear interpolation) on an ascending Float64Array. */
export function percentilOrdenado(orden, q) {
  const n = orden.length;
  if (!n) return NaN;
  const pos = (q / 100) * (n - 1), i = Math.floor(pos), f = pos - i;
  return i + 1 < n ? orden[i] + f * (orden[i + 1] - orden[i]) : orden[i];
}

function prepararCurva(curva, meses) {
  // logs of the three quantiles per well month; `valido` false where any is missing or not positive
  if (!curva) return null;
  const l10 = new Float64Array(meses), l50 = new Float64Array(meses), l90 = new Float64Array(meses);
  const valido = new Uint8Array(meses);
  for (let k = 0; k < meses; k++) {
    const a = curva.p10[k], b = curva.p50[k], c = curva.p90[k];
    if (a > 0 && b > 0 && c > 0) {
      l10[k] = Math.log(a);
      l50[k] = Math.log(b);
      l90[k] = Math.log(c);
      valido[k] = 1;
    }
  }
  return { l10, l50, l90, valido };
}

function validar(p) {
  const ent = (v) => Number.isInteger(v);
  if (!ent(p.nPozos) || p.nPozos < 1 || p.nPozos > N_POZOS_MAX) throw new RangeError(`n_pozos: 1..${N_POZOS_MAX}`);
  if (!ent(p.meses) || p.meses < 1 || p.meses > MESES_MAX) throw new RangeError(`meses: 1..${MESES_MAX}`);
  if (!ent(p.nSim) || p.nSim < 10 || p.nSim > N_SIM_MAX) throw new RangeError(`n_sim: 10..${N_SIM_MAX}`);
  if (!(p.uptime > 0 && p.uptime <= 1)) throw new RangeError("uptime: (0, 1]");
  if (!p.petroleo && !p.gas) throw new RangeError("curva: petroleo | gas");
}

// --- the simulation ----------------------------------------------------------------------------------------------------

/**
 * Start a simulation that can be run in chunks (so a page stays responsive).
 *
 * params: {
 *   petroleo, gas          {p10, p50, p90} arrays by well month (already extended), or null
 *   escalaPetroleo, escalaGas   multiplier of the sampled rate (the lateral in m for a per-metre curve; 1 otherwise)
 *   nPozos, meses, ritmo, nSim, semilla, uptime, jitter (percentile points, 8), diasMes (365.25 / 12)
 *   precioPetroleo (USD/m3), precioGas (USD per thousand m3), tasaAnual (0.10), regalia (0)
 * }
 * Returns { total, hechas(), correr(n), resultado() }.
 */
export function iniciar(params) {
  const p = {
    escalaPetroleo: 1, escalaGas: 1, ritmo: null, nSim: 500, semilla: 0, uptime: 0.92, jitter: 8, diasMes: 365.25 / 12,
    precioPetroleo: 0, precioGas: 0, tasaAnual: 0.1, regalia: 0, petroleo: null, gas: null,
    ...params,
  };
  validar(p);
  const { nPozos, meses, nSim } = p;
  const ini = inicios(nPozos, p.ritmo ?? nPozos);
  const ritmo = Math.max(1, Math.min(Math.trunc(p.ritmo ?? nPozos) || nPozos, nPozos));
  const enLinea = Array.from({ length: meses }, (_, m) => ini.filter((i) => i <= m).length);
  const fluidos = [
    { clave: "petroleo", c: prepararCurva(p.petroleo, meses), escala: p.escalaPetroleo || 1, precio: p.precioPetroleo || 0 },
    { clave: "gas", c: prepararCurva(p.gas, meses), escala: p.escalaGas || 1, precio: p.precioGas || 0 },
  ].filter((f) => f.c);
  for (const f of fluidos) {
    f.tasa = new Float64Array(nSim * meses); // aggregated producing-day rate, [sim * meses + month]
    f.acum = new Float64Array(nSim * meses); // monthly volume while running, cumulative once finished
  }
  const ingreso = new Float64Array(nSim * meses);
  const ingresoAcum = new Float64Array(nSim * meses);
  const van = new Float64Array(nSim);
  const descuento = Float64Array.from({ length: meses }, (_, k) => Math.pow(1 + p.tasaAnual, -k / 12));
  const neto = 1 - (p.regalia || 0);
  const factorVol = p.diasMes * p.uptime;
  const rng = crearRng(p.semilla);
  const u0 = new Float64Array(nPozos);
  let hechas = 0;

  function correr(n) {
    const fin = Math.min(nSim, hechas + n);
    for (let s = hechas; s < fin; s++) {
      const base = s * meses;
      for (let w = 0; w < nPozos; w++) u0[w] = 1 + 98 * rng.uniforme();
      for (let w = 0; w < nPozos; w++) {
        const i0 = ini[w];
        if (i0 >= meses) continue;
        for (let k = 0; k < meses - i0; k++) {
          const u = Math.min(99, Math.max(1, u0[w] + p.jitter * rng.normal()));
          for (const f of fluidos) {
            const c = f.c;
            if (!c.valido[k]) continue;
            const y = u >= 50 ? c.l50[k] + ((u - 50) / 40) * (c.l90[k] - c.l50[k]) : c.l50[k] + ((50 - u) / 40) * (c.l10[k] - c.l50[k]);
            const q = Math.exp(y) * f.escala;
            f.tasa[base + i0 + k] += q;
            f.acum[base + i0 + k] += q * factorVol;
          }
        }
      }
      // money of this simulation (gross revenue: volume x price, minus the royalty fraction if any), then cumulate
      let acumUsd = 0, vanS = 0;
      for (let m = 0; m < meses; m++) {
        let usd = 0;
        for (const f of fluidos) usd += f.acum[base + m] * f.precio;
        usd *= neto;
        ingreso[base + m] = usd;
        acumUsd += usd;
        ingresoAcum[base + m] = acumUsd;
        vanS += usd * descuento[m];
      }
      van[s] = vanS;
      for (const f of fluidos) {
        let a = 0;
        for (let m = 0; m < meses; m++) {
          a += f.acum[base + m];
          f.acum[base + m] = a;
        }
      }
    }
    hechas = fin;
    return hechas;
  }

  function banda(matriz) {
    const p10 = new Array(meses), p50 = new Array(meses), p90 = new Array(meses), media = new Array(meses);
    const col = new Float64Array(nSim);
    for (let m = 0; m < meses; m++) {
      let suma = 0;
      for (let s = 0; s < nSim; s++) {
        col[s] = matriz[s * meses + m];
        suma += col[s];
      }
      col.sort();
      p10[m] = percentilOrdenado(col, 90); // oil convention: P10 is the high case
      p50[m] = percentilOrdenado(col, 50);
      p90[m] = percentilOrdenado(col, 10);
      media[m] = suma / nSim;
    }
    return { p10, p50, p90, media };
  }

  function tres(valores) {
    const o = Float64Array.from(valores).sort();
    let suma = 0;
    for (const v of o) suma += v;
    return { p10: percentilOrdenado(o, 90), p50: percentilOrdenado(o, 50), p90: percentilOrdenado(o, 10), media: suma / o.length };
  }

  function resultado() {
    if (hechas < nSim) throw new Error("simulation not finished");
    const out = {
      n_pozos: nPozos, meses, ritmo_pozos_por_mes: ritmo, n_sim: nSim, semilla: p.semilla, uptime: p.uptime,
      jitter_percentil: p.jitter, tasa_anual: p.tasaAnual, regalia: p.regalia || 0,
      mes: Array.from({ length: meses }, (_, m) => m),
      pozos_en_linea: enLinea,
      fluidos: {},
    };
    const ultimo = (matriz) => Float64Array.from({ length: nSim }, (_, s) => matriz[s * meses + meses - 1]);
    for (const f of fluidos) {
      const fin = ultimo(f.acum);
      const picos = new Float64Array(nSim), mesPico = new Float64Array(nSim);
      for (let s = 0; s < nSim; s++) {
        let mx = -Infinity, im = 0;
        for (let m = 0; m < meses; m++) {
          const v = f.tasa[s * meses + m];
          if (v > mx) {
            mx = v;
            im = m;
          }
        }
        picos[s] = mx;
        mesPico[s] = im;
      }
      out.fluidos[f.clave] = {
        escala: f.escala,
        precio: f.precio,
        tasa_agregada: banda(f.tasa),
        acumulado: banda(f.acum),
        final: {
          acumulado: tres(fin),
          por_pozo: tres(fin.map((v) => v / nPozos)),
          tasa_pico_p50: percentilOrdenado(picos.sort(), 50),
          mes_pico_p50: Math.trunc(percentilOrdenado(mesPico.sort(), 50)),
        },
      };
    }
    // oil equivalent with the Secretaría's factor: 1 m3 of oil = 1,000 m3 of gas (gas is in thousand m3)
    const eq = new Float64Array(nSim);
    for (const f of fluidos) for (let s = 0; s < nSim; s++) eq[s] += f.acum[s * meses + meses - 1];
    out.equivalente_final = tres(eq);
    out.usd = {
      ingreso_mes: banda(ingreso),
      ingreso_acumulado: banda(ingresoAcum),
      final: { ingreso: tres(ultimo(ingresoAcum)), van: tres(van) },
    };
    return out;
  }

  return { total: nSim, hechas: () => hechas, correr, resultado };
}

/** Run it all at once (Node, tests). */
export function simular(params) {
  const sim = iniciar(params);
  sim.correr(sim.total);
  return sim.resultado();
}
