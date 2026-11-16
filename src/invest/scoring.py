from __future__ import annotations

from typing import Literal

from invest.valuation import QualityResult

Signal = Literal["oportunidade", "caro", "risco", "dado_velho", "neutro", "sem_dados"]

DEFAULT_WEIGHTS = {"folga": 0.5, "qualidade": 0.3, "regularidade": 0.2}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_score(
    price: float,
    reference: float | None,
    quality: float,  # fração das checagens de qualidade aprovadas (True/False também serve)
    dividend_regularity: float,
    weights: dict[str, float],
) -> int | None:
    if reference is None or reference <= 0:
        return None
    slack = _clamp((reference - price) / reference)
    total = (
        weights["folga"] * slack
        + weights["qualidade"] * _clamp(float(quality))
        + weights["regularidade"] * _clamp(dividend_regularity)
    )
    return round(100 * total)


def classify(
    price: float,
    reference: float | None,
    quality: QualityResult,
    dividend_cut: bool,
    payout: float | None,
    data_age_days: int,
    held: bool,
    max_age_days: int = 10,
    max_payout: float = 1.0,
) -> Signal:
    if data_age_days > max_age_days:
        return "dado_velho"
    if reference is None:
        return "sem_dados"
    if dividend_cut or (payout is not None and payout > max_payout):
        return "risco"
    if price <= reference and quality.passed:
        return "oportunidade"
    if held and price > reference:
        return "caro"
    return "neutro"
