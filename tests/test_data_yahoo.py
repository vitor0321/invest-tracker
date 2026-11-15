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
    assert f.payout == 0.5
    assert f.net_debt_ebitda == 2.0
    assert f.years_without_cut == 2
    assert f.source == "yahoo"


def test_provider_failure_returns_empty_fundamentals():
    f = YahooProvider(ticker_factory=lambda s: FakeTicker(s, fail=True)).fetch("X", "br")
    assert f.price is None
    assert f.annual_dividends == []
    assert f.eps is None
