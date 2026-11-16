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
    assert check_quality(0.5, 2.0, 0).passed is True
    assert check_quality(1.2, 2.0, 0).failures == ["payout"]
    assert check_quality(None, 2.0, 0).failures == ["payout"]


def test_fii_quality():
    assert fii_quality(FiiMetrics(0.95, 0.09, 12)).passed is True
    assert fii_quality(FiiMetrics(1.3, 0.09, 12)).failures == ["pvp"]


def test_fii_quality_flags_last_payment_drop_over_20_percent():
    drop = fii_quality(FiiMetrics(0.8, 0.12, 12, last_dividend=0.67, avg_dividend=0.86))
    assert drop.passed is False and drop.failures == ["queda_rendimento"]
    assert fii_quality(FiiMetrics(0.8, 0.12, 12, last_dividend=0.80, avg_dividend=0.86)).passed is True
    assert fii_quality(FiiMetrics(0.8, 0.12, 12)).passed is True  # sem dado do último rendimento: não pune


def test_check_quality_can_skip_leverage_for_financials():
    assert check_quality(0.5, None, 0).failures == ["divida"]
    assert check_quality(0.5, None, 0, check_leverage=False).passed is True


# --- calibragem média ---
def test_quality_tolerates_one_dividend_cut_in_five_years():
    assert check_quality(0.5, 2.0, 1).passed is True
    assert check_quality(0.5, 2.0, 2).failures == ["cortes"]
    assert check_quality(0.5, 2.0, None).failures == ["historico_curto"]


def test_quality_can_skip_payout_for_units():
    assert check_quality(None, 2.0, 0, check_payout=False).passed is True


def test_count_cuts_needs_four_years_and_counts_drops_over_20_percent():
    from invest.valuation import count_cuts

    assert count_cuts([3.0, 3.0, 2.0, 3.0, 3.0, 3.0]) == 1
    assert count_cuts([3.0, 2.0, 3.0, 2.0, 3.0, 3.0]) == 2
    assert count_cuts([3.0, 2.9, 2.8, 2.7]) == 0
    assert count_cuts([3.0, 3.0, 3.0]) is None
