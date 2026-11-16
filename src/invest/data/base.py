from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

log = logging.getLogger("invest")

Market = Literal["br", "us"]


@dataclass
class Fundamentals:
    ticker: str
    price: float | None = None
    annual_dividends: list[float] = field(default_factory=list)
    eps: float | None = None
    bvps: float | None = None
    payout: float | None = None
    net_debt_ebitda: float | None = None
    years_without_cut: int = 0
    dividend_12m: float | None = None
    months_paid_12m: int = 0
    last_dividend: float | None = None
    sector: str | None = None
    roe: float | None = None
    profit_margin: float | None = None
    earnings_growth: float | None = None
    revenue_growth: float | None = None
    currency: str | None = None
    financial_currency: str | None = None
    source: str = ""
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DataProvider(Protocol):
    def fetch(self, ticker: str, market: Market) -> Fundamentals: ...


def normalize_ticker(ticker: str, market: str) -> str:
    return f"{ticker}.SA" if market == "br" else ticker
