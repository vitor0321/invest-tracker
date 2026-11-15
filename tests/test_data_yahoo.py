import pandas as pd

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
        idx = pd.to_datetime(["2022-05-01", "2023-05-01", "2023-11-01", "2024-05-01"])
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
