import math

import pytest

from vma import units as u


def test_barrel_round_trip():
    assert math.isclose(u.bbl_to_m3(u.m3_to_bbl(123.4)), 123.4, rel_tol=1e-12)
    assert math.isclose(u.m3_to_bbl(1), 6.2898, rel_tol=1e-4)
    assert math.isclose(u.m3_to_bbl(1000), 6289.81, rel_tol=1e-5)


def test_gas_thousand_m3_to_mcf():
    # 1,000 m3 of gas = 35,314.67 ft3 = 35.31 Mcf
    assert math.isclose(u.thousand_m3_to_mcf(1), 35.3146667, rel_tol=1e-6)
    assert math.isclose(u.thousand_m3_to_mmscf(1000), 35.3146667, rel_tol=1e-6)


def test_oil_equivalent_uses_secretaria_factor():
    # 1,000 m3 of gas (= 1 unit of prod_gas) counts as 1 m3 of oil equivalent
    assert u.gas_thousand_m3_to_m3_oil_eq(1) == 1
    assert u.oil_eq_m3(oil_m3=100, gas_thousand_m3=50) == 150


def test_length_and_intensity_conversions():
    assert math.isclose(u.m_to_ft(1), 3.280839895, rel_tol=1e-9)
    assert math.isclose(u.m_to_ft(3000), 9842.52, rel_tol=1e-5)
    # 1 t/m = 1000 kg / m = 2204.62 lb / 3.2808 ft = 671.97 lb/ft
    assert math.isclose(u.tonnes_per_m_to_lb_per_ft(1), 671.969, rel_tol=1e-5)
    # 1 m3/m = 6.2898 bbl / 3.2808 ft = 1.917 bbl/ft
    assert math.isclose(u.m3_per_m_to_bbl_per_ft(1), 1.91713, rel_tol=1e-5)


@pytest.mark.parametrize("days", [0, -1, None])
def test_daily_rate_is_none_without_producing_days(days):
    assert u.daily_rate(100, days) is None


def test_daily_rate():
    assert u.daily_rate(310, 31) == 10


def test_factors_are_frozen():
    # if the source changes units, these tests must fail loudly rather than drift
    assert u.M3_PER_BBL == 0.158987294928
    assert u.FT3_PER_M3 == 35.3146667215
    assert u.M3_GAS_PER_M3_OIL_EQ == 1000.0
