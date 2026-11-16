from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from invest.valuation import DIVIDEND_CUT_TOLERANCE
from invest.data.base import Fundamentals, Market, log, normalize_ticker


MAX_CREDIBLE_PAYOUT = 3.0


def _default_factory(symbol: str):
    import yfinance as yf

    return yf.Ticker(symbol)


def _annual_totals(dividends) -> list[float]:
    """Soma por ano civil, só anos completos, últimos 6 (5 comparações ano a ano)."""
    by_year: dict[int, float] = {}
    first = None
    for ts, value in dividends.items():
        by_year[ts.year] = by_year.get(ts.year, 0.0) + float(value)
        first = ts if first is None or ts < first else first
    if first is not None and first.month > 2:
        by_year.pop(first.year, None)  # histórico do Yahoo começa no meio do ano: ano parcial
    current = datetime.now(timezone.utc).year
    years = sorted(y for y in by_year if y < current)
    return [round(by_year[y], 6) for y in years][-6:]



def _years_without_cut(annual: list[float]) -> int:
    count = 0
    for prev, cur in zip(reversed(annual[:-1]), reversed(annual[1:])):
        if cur >= prev * (1 - DIVIDEND_CUT_TOLERANCE):
            count += 1
        else:
            break
    return count


def _clean(x) -> float | None:
    """Número finito ou None (o Yahoo às vezes devolve texto ou NaN)."""
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


def _last_payment(dividends) -> float | None:
    values = [(ts, float(v)) for ts, v in dividends.items()]
    return max(values, key=lambda item: item[0])[1] if values else None


def _trailing_12m(dividends) -> tuple[float, int]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365)
    total, months = 0.0, set()
    for ts, value in dividends.items():
        naive = ts.tz_localize(None) if getattr(ts, "tzinfo", None) else ts
        if naive >= cutoff:
            total += float(value)
            months.add((naive.year, naive.month))
    return total, len(months)


class YahooProvider:
    def __init__(self, ticker_factory: Callable = _default_factory):
        self._factory = ticker_factory

    def fetch(self, ticker: str, market: Market) -> Fundamentals:
        result = Fundamentals(ticker=ticker, source="yahoo")
        try:
            t = self._factory(normalize_ticker(ticker, market))
            info = t.info or {}
            qt = info.get("regularMarketTime")
            if isinstance(qt, (int, float)):
                result.collected_at = datetime.fromtimestamp(qt, tz=timezone.utc)
            result.price = info.get("currentPrice") or info.get("regularMarketPrice")
            result.eps = info.get("trailingEps")
            result.bvps = info.get("bookValue")
            debt, cash, ebitda = info.get("totalDebt"), info.get("totalCash"), info.get("ebitda")
            if debt is not None and cash is not None and ebitda:
                result.net_debt_ebitda = (debt - cash) / ebitda
            result.annual_dividends = _annual_totals(t.dividends)
            result.years_without_cut = _years_without_cut(result.annual_dividends)
            result.dividend_12m, result.months_paid_12m = _trailing_12m(t.dividends)
            result.last_dividend = _last_payment(t.dividends)
            result.sector = info.get("sector")
            result.roe = _clean(info.get("returnOnEquity"))
            result.profit_margin = _clean(info.get("profitMargins"))
            result.earnings_growth = _clean(info.get("earningsGrowth"))
            result.revenue_growth = _clean(info.get("revenueGrowth"))
            result.currency = info.get("currency")
            result.financial_currency = info.get("financialCurrency")
            if (result.currency and result.financial_currency
                    and result.currency != result.financial_currency):
                result.eps = result.bvps = None  # lucro em outra moeda: não comparável com a cotação
            if info.get("sector") != "Real Estate" and result.eps and result.eps > 0:
                result.payout = result.dividend_12m / result.eps
                if result.payout > MAX_CREDIBLE_PAYOUT:  # LPA incoerente com os dividendos
                    result.eps = result.payout = None
        except Exception as exc:  # fonte instável: nunca derruba a rodada
            log.warning("yahoo falhou para %s: %s", ticker, exc)
            return Fundamentals(ticker=ticker, source="yahoo")
        return result
