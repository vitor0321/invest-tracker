import pandas as pd
import pytest

from invest.data.base import normalize_ticker
from invest.data.yahoo import YahooProvider


class FakeTicker:
    def __init__(self, symbol, fail=False):
        self.symbol = symbol
        self.fail = fail

    @property
    def dividends(self):
        if self.fail:
            raise RuntimeError("boom")
        idx = pd.to_datetime(["2022-01-15", "2023-05-01", "2023-11-01", "2024-05-01"])
        return pd.Series([1.0, 1.0, 1.0, 3.0], index=idx)

    @property
    def info(self):
        return {
            "currentPrice": 40.0,
            "trailingEps": 2.0,
            "bookValue": 10.0,
            "payoutRatio": 0.5,
            "totalDebt": 300.0,
            "totalCash": 100.0,
            "ebitda": 100.0,
        }


def test_normalize_ticker():
    assert normalize_ticker("ITUB4", "br") == "ITUB4.SA"
    assert normalize_ticker("JNJ", "us") == "JNJ"


def test_provider_groups_dividends_by_year():
    f = YahooProvider(ticker_factory=FakeTicker).fetch("ITUB4", "br")
    assert f.annual_dividends == [1.0, 2.0, 3.0]
    assert f.price == 40.0
    assert f.eps == 2.0
    assert f.bvps == 10.0
    assert f.payout == 0.0  # payout próprio: dividendos de 12 meses / LPA
    assert f.net_debt_ebitda == 2.0
    assert f.years_without_cut == 2
    assert f.source == "yahoo"


def test_provider_failure_returns_empty_fundamentals():
    f = YahooProvider(ticker_factory=lambda s: FakeTicker(s, fail=True)).fetch("X", "br")
    assert f.price is None
    assert f.annual_dividends == []
    assert f.eps is None


def test_provider_trailing_12m_dividends():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    idx = pd.to_datetime([now - timedelta(days=30 * k) for k in (1, 2, 3, 20)])

    class Recent(FakeTicker):
        @property
        def dividends(self):
            return pd.Series([1.0, 1.0, 1.0, 5.0], index=idx.tz_localize(None))

    f = YahooProvider(ticker_factory=Recent).fetch("MXRF11", "br")
    assert f.dividend_12m == 3.0
    assert f.months_paid_12m == 3


def _recent_ticker(info_extra=None):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    idx = pd.to_datetime([now - timedelta(days=30 * k) for k in (1, 4)]).tz_localize(None)

    class T(FakeTicker):
        @property
        def dividends(self):
            return pd.Series([1.0, 1.0], index=idx)

        @property
        def info(self):
            return dict(FakeTicker.info.fget(self), **(info_extra or {}))

    return T


def test_payout_is_computed_from_own_dividends_not_yahoo():
    f = YahooProvider(ticker_factory=_recent_ticker({"payoutRatio": 5.08})).fetch("VALE3", "br")
    assert f.payout == 1.0 and f.eps == 2.0  # 2.0 de dividendos / LPA 2.0, ignora 5.08


def test_payout_is_none_for_real_estate_sector():
    f = YahooProvider(ticker_factory=_recent_ticker({"sector": "Real Estate"})).fetch("O", "us")
    assert f.payout is None


def test_eps_and_bvps_dropped_when_financial_currency_differs():
    f = YahooProvider(ticker_factory=_recent_ticker({"currency": "BRL", "financialCurrency": "USD"})).fetch("VALE3", "br")
    assert f.eps is None and f.bvps is None and f.price == 40.0
    assert (f.currency, f.financial_currency) == ("BRL", "USD")


def test_first_partial_year_of_history_is_dropped():
    idx = pd.to_datetime(["2021-08-01", "2022-01-10", "2023-01-10", "2024-01-10", "2025-01-10"])

    class Trunc(FakeTicker):
        @property
        def dividends(self):
            return pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)

    f = YahooProvider(ticker_factory=Trunc).fetch("MXRF11", "br")
    assert f.annual_dividends == [2.0, 3.0, 4.0, 5.0]


def test_absurd_payout_discards_eps_and_payout():
    f = YahooProvider(ticker_factory=_recent_ticker({"trailingEps": 0.5})).fetch("VALE3", "br")
    assert f.payout is None and f.eps is None and f.price == 40.0


def test_small_dividend_dips_do_not_break_the_no_cut_streak():
    from invest.data.yahoo import _years_without_cut

    assert _years_without_cut([1.0, 0.85, 0.9, 1.0, 1.1, 1.2]) == 5
    assert _years_without_cut([1.0, 1.0, 0.5, 1.0]) == 1


def test_provider_exposes_last_dividend_payment():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    idx = pd.to_datetime([now - timedelta(days=30 * k) for k in (1, 2, 3)]).tz_localize(None)

    class Recent(FakeTicker):
        @property
        def dividends(self):
            return pd.Series([0.67, 1.05, 1.05], index=idx)  # 30 dias atrás é o pagamento mais recente

    f = YahooProvider(ticker_factory=Recent).fetch("VGIP11", "br")
    assert f.last_dividend == 0.67


def test_provider_exposes_sector():
    class Bank(FakeTicker):
        @property
        def info(self):
            return dict(FakeTicker.info.fget(self), sector="Financial Services")

    assert YahooProvider(ticker_factory=Bank).fetch("ITUB4", "br").sector == "Financial Services"


def test_provider_exposes_quality_fields():
    class Q(FakeTicker):
        @property
        def info(self):
            return dict(FakeTicker.info.fget(self), returnOnEquity=0.21, profitMargins=0.15,
                        earningsGrowth=0.08, revenueGrowth=0.11)

    f = YahooProvider(ticker_factory=Q).fetch("WEGE3", "br")
    assert (f.roe, f.profit_margin, f.earnings_growth, f.revenue_growth) == (0.21, 0.15, 0.08, 0.11)


def test_provider_exposes_52_week_high_and_200_day_average():
    class E(FakeTicker):
        @property
        def info(self):
            return dict(FakeTicker.info.fget(self), fiftyTwoWeekHigh=700.5, twoHundredDayAverage=640.0)

    f = YahooProvider(ticker_factory=E).fetch("VOO", "us")
    assert (f.high_52w, f.avg_200d) == (700.5, 640.0)


# --- crescimento de vários anos ---
def _stmt(revenue, income, years=(2025, 2024, 2023, 2022)):
    cols = pd.to_datetime([f"{y}-12-31" for y in years])
    return pd.DataFrame([revenue, income], index=["Total Revenue", "Net Income"], columns=cols)


def _with_stmt(stmt, **info):
    class T(FakeTicker):
        @property
        def info(self):
            return dict(FakeTicker.info.fget(self), **info)

        income_stmt = stmt

    return T


def test_growth_comes_from_multi_year_statements_not_last_quarter():
    stmt = _stmt([1331.0, 1210.0, 1100.0, 1000.0], [172.8, 144.0, 120.0, 100.0])  # +10% e +20% ao ano
    f = YahooProvider(ticker_factory=_with_stmt(stmt, earningsGrowth=7.17, revenueGrowth=1.2)).fetch("PRIO3", "br")
    assert f.revenue_growth == pytest.approx(0.10) and f.earnings_growth == pytest.approx(0.20)
    assert f.growth_years == 3


def test_growth_falls_back_to_quarter_when_statements_are_short_or_missing():
    short = _stmt([1100.0, 1000.0], [120.0, 100.0], years=(2025, 2024))
    f = YahooProvider(ticker_factory=_with_stmt(short, earningsGrowth=0.3, revenueGrowth=0.1)).fetch("X", "br")
    assert (f.earnings_growth, f.revenue_growth, f.growth_years) == (0.3, 0.1, None)
    f = YahooProvider(ticker_factory=_with_stmt(None, earningsGrowth=0.3, revenueGrowth=0.1)).fetch("X", "br")
    assert (f.earnings_growth, f.revenue_growth, f.growth_years) == (0.3, 0.1, None)
    assert f.price == 40.0  # balanço ausente não derruba o resto da coleta


def test_multi_year_growth_skips_losses_and_nan():
    nan = float("nan")
    stmt = _stmt([1210.0, 1100.0, 1000.0, nan], [50.0, 20.0, -10.0, nan])
    f = YahooProvider(ticker_factory=_with_stmt(stmt, earningsGrowth=0.3)).fetch("X", "br")
    assert f.revenue_growth == pytest.approx(0.10) and f.growth_years == 2
    assert f.earnings_growth is None  # saiu de prejuízo: taxa não faz sentido, e o trimestre também não entra
