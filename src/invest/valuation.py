"""Fórmulas clássicas de valor. None significa "não se aplica"."""
from __future__ import annotations

from dataclasses import dataclass, field


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


def check_quality(
    payout: float | None,
    net_debt_ebitda: float | None,
    years_without_cut: int,
    max_payout: float = 1.0,
    max_leverage: float = 3.0,
    min_years: int = 5,
) -> QualityResult:
    failures: list[str] = []
    if payout is None or payout > max_payout:
        failures.append("payout")
    if net_debt_ebitda is None or net_debt_ebitda > max_leverage:
        failures.append("divida")
    if years_without_cut < min_years:
        failures.append("anos_sem_corte")
    return _result(failures)


@dataclass
class FiiMetrics:
    pvp: float | None
    dy_12m: float | None
    months_paid_12m: int


def fii_quality(
    m: FiiMetrics,
    max_pvp: float = 1.10,
    min_dy: float = 0.08,
    min_months: int = 11,
) -> QualityResult:
    failures: list[str] = []
    if m.pvp is None or m.pvp > max_pvp:
        failures.append("pvp")
    if m.dy_12m is None or m.dy_12m < min_dy:
        failures.append("dy")
    if m.months_paid_12m < min_months:
        failures.append("regularidade")
    return _result(failures)
