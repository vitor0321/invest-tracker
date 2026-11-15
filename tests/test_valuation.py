import pytest

from invest.valuation import (
    FiiMetrics,
    bazin_ceiling,
    check_quality,
    fii_quality,
    gordon_price,
    graham_fair_price,
    reference_price,
)


def test_bazin():
    assert bazin_ceiling([2.0, 3.0, 4.0]) == pytest.approx(50.0)
    assert bazin_ceiling([]) is None


def test_graham():
    assert graham_fair_price(2.0, 10.0) == pytest.approx(21.2132, abs=1e-4)
    assert graham_fair_price(-1.0, 10.0) is None
    assert graham_fair_price(2.0, -5.0) is None


def test_gordon():
    assert gordon_price(1.0, 0.10, 0.04) == pytest.approx(16.6667, abs=1e-4)
    assert gordon_price(1.0, 0.10, 0.12) == pytest.approx(25.0)
    assert gordon_price(1.0, 0.05, 0.08) is None


def test_reference_price():
    assert reference_price([50.0, None, 21.2]) == 21.2
    assert reference_price([None]) is None


def test_quality():
    assert check_quality(0.5, 2.0, 6).passed is True
    assert check_quality(1.2, 2.0, 6).failures == ["payout"]
    assert check_quality(None, 2.0, 6).failures == ["payout"]


def test_fii_quality():
    assert fii_quality(FiiMetrics(0.95, 0.09, 12)).passed is True
    assert fii_quality(FiiMetrics(1.3, 0.09, 12)).failures == ["pvp"]
