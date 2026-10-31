import pytest

from vma.normalize import (
    SIGLA_LEVELS,
    formation_key,
    operator_key,
    sigla_l1,
    sigla_l2,
    sigla_l3,
    sigla_l4,
    sigla_levels,
    split_sigla,
)


def test_levels_are_monotonic_in_aggressiveness():
    s = "  YPF.Nq.LACh-1234(h) "
    out = sigla_levels(s)
    assert list(out) == list(SIGLA_LEVELS)
    assert out["L0 raw"] == s
    assert out["L1 trim"] == "YPF.Nq.LACh-1234(h)"
    assert out["L2 trim+upper"] == "YPF.NQ.LACH-1234(H)"
    assert out["L3 +drop (h)/(d) suffix"] == "YPF.NQ.LACH-1234"
    assert out["L4 +alnum only"] == "YPFNQLACH1234"


@pytest.mark.parametrize(
    "a,b",
    [
        ("YPF.Nq.LACh-1234(h)", "YPF.NQ.LACH-1234(H)"),
        (" YPF.Nq.LACh-1234(h)", "YPF.Nq.LACh-1234(h) "),
        ("APA.Nq.RCo-1042(d)", "apa.nq.rco-1042(D)"),
    ],
)
def test_l2_unifies_case_and_spaces(a, b):
    assert sigla_l2(a) == sigla_l2(b)


def test_l3_drops_only_trailing_type_suffix():
    assert sigla_l3("YPF.Nq.LACh-1234(h)") == "YPF.NQ.LACH-1234"
    assert sigla_l3("YPF.Nq.LACh-1234(hi)") == "YPF.NQ.LACH-1234"
    assert sigla_l3("YPF.Nq.LACh-1234") == "YPF.NQ.LACH-1234"
    # a parenthesised token in the middle is not a suffix
    assert sigla_l3("YPF.Nq.(x)LACh-1234") == "YPF.NQ.(X)LACH-1234"


def test_l4_collapses_punctuation_but_never_merges_numbers():
    assert sigla_l4("YPF.Nq.LACh-1234") == sigla_l4("YPF Nq LACh 1234")
    assert sigla_l4("YPF.Nq.LACh-12") != sigla_l4("YPF.Nq.LACh-123")


def test_l1_only_trims():
    assert sigla_l1("  a b  ") == "a b"


def test_split_sigla():
    p = split_sigla("YPF.Nq.LACh-1234(h)")
    assert p == {
        "operator": "YPF",
        "province": "Nq",
        "area": "LACh",
        "type": None,
        "number": "1234",
        "suffix": "(h)",
    }
    p = split_sigla("APS.Nq.ADC.xp-1033")
    assert p["operator"] == "APS" and p["type"] == "xp" and p["number"] == "1033" and p["suffix"] is None
    assert split_sigla("A-1")["operator"] is None


@pytest.mark.parametrize(
    "a,b",
    [
        ("VISTA OIL & GAS ARGENTINA SAU", "Vista Oil & Gas Argentina SA"),
        ("PAN AMERICAN ENERGY (SUCURSAL ARGENTINA) LLC", "PAN AMERICAN ENERGY SL"),
        ("GEOPARK ARGENTINA LTD. (SUCURSAL ARGENTINA)", "GEOPARK ARGENTINA S.A."),
        ("YSUR ENERGÍA ARGENTINA S.R.L.", "YSUR ENERGIA ARGENTINA SRL"),
        ("CAPETROL ARGENTINA S.A.", "CAPETROL S.A."),
    ],
)
def test_operator_key_blocks_known_variants(a, b):
    assert operator_key(a) == operator_key(b)


def test_operator_key_keeps_distinct_companies_apart():
    assert operator_key("YPF S.A.") != operator_key("YSUR ENERGÍA ARGENTINA S.R.L.")
    assert operator_key("PLUSPETROL S.A.") != operator_key("PETROLERA ENTRE LOMAS S.A.")


@pytest.mark.parametrize(
    "a,b",
    [
        ("vaca muerta", "VACA MUERTA"),
        ("Fm. Vaca Muerta", "vaca muerta"),
        ("Formación Vaca Muerta", "vaca muerta"),
        ("huitrín", "Huitrin"),
        ("cañadon seco", "Cañadón Seco"),
    ],
)
def test_formation_key(a, b):
    assert formation_key(a) == formation_key(b)


def test_formation_key_keeps_members_apart():
    assert formation_key("vaca muerta") != formation_key("quintuco")
    assert formation_key("grupo chubut") == "CHUBUT"
