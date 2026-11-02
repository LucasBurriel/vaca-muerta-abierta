"""Phase 5: decline-curve fits and campaign Monte Carlo on top of the published tables (ADR-031).

This is **decline-curve analysis**, not reservoir simulation: there are no pressures, no PVT, no geology in the
public data, so the only thing that can be fitted is the shape of the rate history and the only thing that can be
sampled is the published dispersion between wells. Every result says so.

- :mod:`vma.simulacion.declinacion`  Arps (exponential, hyperbolic, harmonic, with a terminal decline) and Duong
  fitted by least squares on log rate, model choice by AIC, EUR to 20-30 years, a band from a residual bootstrap.
- :mod:`vma.simulacion.campania`     n wells drawn from a published type curve (P10/P50/P90 by month), staggered,
  with lateral scaling when the per-metre curve exists; aggregated P10/P50/P90 of rate and cumulative per month.
"""
