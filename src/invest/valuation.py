"""Fórmulas clássicas de valor. None significa "não se aplica"."""
from __future__ import annotations

from dataclasses import dataclass, field

DIVIDEND_CUT_TOLERANCE = 0.20  # queda maior que isso conta como corte


def bazin_ceiling(annual_dividends: list[float], target_dy: float = 0.06) -> float | None:
    if not annual_dividends or target_dy <= 0:
        return None
    return (sum(annual_dividends) / len(annual_dividends)) / target_dy


def graham_fair_price(eps: float, bvps: float, factor: float = 22.5) -> float | None:
    if eps <= 0 or bvps <= 0:
        return None
    return (factor * eps * bvps) ** 0.5


def gordon_price(
    next_dividend: float,
    required_return: float,
    growth: float,
    growth_cap: float = 0.06,
    min_spread: float = 0.02,
) -> float | None:
    g = min(growth, growth_cap)
    if required_return - g < min_spread:
        return None
    return next_dividend / (required_return - g)


def reference_price(prices: list[float | None]) -> float | None:
    valid = [p for p in prices if p is not None]
    return min(valid) if valid else None


@dataclass
class QualityResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def _result(failures: list[str]) -> QualityResult:
    return QualityResult(passed=not failures, failures=failures)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def count_cuts(annual: list[float], tolerance: float = DIVIDEND_CUT_TOLERANCE) -> int | None:
    """Quedas maiores que a tolerância nas últimas 5 comparações ano a ano. None = histórico curto."""
    if len(annual) < 4:
        return None
    pairs = list(zip(annual[:-1], annual[1:]))[-5:]
    return sum(1 for prev, cur in pairs if cur < prev * (1 - tolerance))


def check_quality(
    payout: float | None,
    net_debt_ebitda: float | None,
    dividend_cuts: int | None,
    max_payout: float = 1.0,
    max_leverage: float = 3.0,
    max_cuts: int = 1,
    check_leverage: bool = True,
    check_payout: bool = True,
) -> QualityResult:
    failures: list[str] = []
    if check_payout and (payout is None or payout > max_payout):
        failures.append("payout")
    if check_leverage and (net_debt_ebitda is None or net_debt_ebitda > max_leverage):
        failures.append("divida")
    if dividend_cuts is None:
        failures.append("historico_curto")
    elif dividend_cuts > max_cuts:
        failures.append("cortes")
    return _result(failures)


@dataclass
class FiiMetrics:
    pvp: float | None
    dy_12m: float | None
    months_paid_12m: int
    last_dividend: float | None = None
    avg_dividend: float | None = None


def fii_quality(
    m: FiiMetrics,
    max_pvp: float = 1.0,
    min_dy: float = 0.08,
    min_months: int = 11,
    max_drop: float = DIVIDEND_CUT_TOLERANCE,
) -> QualityResult:
    failures: list[str] = []
    if m.pvp is None or m.pvp > max_pvp:
        failures.append("pvp")
    if m.dy_12m is None or m.dy_12m < min_dy:
        failures.append("dy")
    if m.months_paid_12m < min_months:
        failures.append("regularidade")
    if (m.last_dividend is not None and m.avg_dividend
            and m.last_dividend < m.avg_dividend * (1 - max_drop)):
        failures.append("queda_rendimento")
    return _result(failures)
