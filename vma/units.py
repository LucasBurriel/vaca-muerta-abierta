"""Unit conversions, in one place, with tests.

Canonical units are the ones the Secretaría publishes and the ones the observatory
stores: oil and water in m³, gas in thousands of m³ (the Argentine ``Mm³``, *not*
millions), proppant in tonnes, lengths in metres. Everything else is a presentation
conversion done here and nowhere else (docs/decisiones.md, ADR-004).

Factors:
  1 bbl (US oil barrel)        = 0.158 987 294 928 m³
  1 m³                         = 35.314 666 7 ft³
  1 ft                         = 0.3048 m
  oil equivalent (Secretaría)  1 m³ oil ≡ 1,000 m³ gas  (so 1 unit of ``prod_gas`` in
                               thousands of m³ counts as 1 m³ of oil equivalent)
"""

from __future__ import annotations

M3_PER_BBL = 0.158987294928
BBL_PER_M3 = 1 / M3_PER_BBL  # 6.2898107704
FT3_PER_M3 = 35.3146667215
M_PER_FT = 0.3048
FT_PER_M = 1 / M_PER_FT
LB_PER_KG = 2.20462262185
M3_GAS_PER_M3_OIL_EQ = 1000.0


def m3_to_bbl(m3: float) -> float:
    return m3 * BBL_PER_M3


def bbl_to_m3(bbl: float) -> float:
    return bbl * M3_PER_BBL


def thousand_m3_to_mcf(km3: float) -> float:
    """Gas: thousands of m³ -> thousands of ft³ (Mcf). Standard conditions assumed equal."""
    return km3 * FT3_PER_M3


def thousand_m3_to_mmscf(km3: float) -> float:
    return thousand_m3_to_mcf(km3) / 1000.0


def gas_thousand_m3_to_m3_oil_eq(km3: float) -> float:
    """Gas in thousands of m³ -> m³ of oil equivalent with the Secretaría's 1,000:1 factor."""
    return km3 * 1000.0 / M3_GAS_PER_M3_OIL_EQ


def oil_eq_m3(oil_m3: float, gas_thousand_m3: float) -> float:
    return oil_m3 + gas_thousand_m3_to_m3_oil_eq(gas_thousand_m3)


def m_to_ft(m: float) -> float:
    return m * FT_PER_M


def tonnes_to_lb(t: float) -> float:
    return t * 1000.0 * LB_PER_KG


def tonnes_per_m_to_lb_per_ft(t_per_m: float) -> float:
    """Proppant intensity t/m -> lb/ft (the unit US shale literature uses)."""
    return tonnes_to_lb(t_per_m) / FT_PER_M


def m3_per_m_to_bbl_per_ft(m3_per_m: float) -> float:
    """Fluid intensity m³/m -> bbl/ft."""
    return m3_to_bbl(m3_per_m) / FT_PER_M


def daily_rate(volume_month: float, days: float | None) -> float | None:
    """Volume per producing day; None (not 0) when there were no producing days."""
    if days is None or days <= 0:
        return None
    return volume_month / days
