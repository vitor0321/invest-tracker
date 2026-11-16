"""Nota de qualidade do negócio (0-100) e ranking por setor. Não olha preço."""
from __future__ import annotations

from dataclasses import dataclass

from invest.data.base import Fundamentals

QUALITY_WEIGHTS = {"roe": 0.25, "margem": 0.15, "crescimento": 0.25, "solidez": 0.15, "dividendos": 0.20}
MIN_COMPONENTS = 3
FINANCIAL = "Financial Services"
_LABELS = {"roe": "ROE", "margem": "margem", "crescimento": "crescimento", "solidez": "dívida/EBITDA"}


@dataclass
class QualityScore:
    score: int | None
    notes: str = ""


@dataclass
class BestRow:
    sector: str
    position: int | None
    ticker: str
    held: bool
    score: int | None
    roe: float | None
    margin: float | None
    earnings_growth: float | None
    revenue_growth: float | None
    net_debt_ebitda: float | None
    dy_12m: float | None
    years_without_cut: int | None
    notes: str = ""


def _scale(x: float, zero: float, full: float) -> float:
    """0 pontos em `zero`, 100 em `full`, linear e limitado."""
    return max(0.0, min(100.0, (x - zero) / (full - zero) * 100))


def _components(f: Fundamentals) -> dict[str, float | None]:
    growth = [g for g in (f.earnings_growth, f.revenue_growth) if g is not None]
    last5 = f.annual_dividends[-5:]
    paid = sum(1 for d in last5 if d > 0) / 5
    return {
        "roe": None if f.roe is None else _scale(f.roe, 0.0, 0.20),
        "margem": None if f.profit_margin is None else _scale(f.profit_margin, 0.0, 0.20),
        "crescimento": _scale(sum(growth) / len(growth), -0.10, 0.20) if growth else None,
        "solidez": None if f.net_debt_ebitda is None else _scale(f.net_debt_ebitda, 4.0, 1.0),
        "dividendos": 70 * min(f.years_without_cut, 5) / 5 + 30 * paid,
    }


def quality_score(f: Fundamentals, weights: dict[str, float] = QUALITY_WEIGHTS) -> QualityScore:
    if f.price is None:
        return QualityScore(None, "sem dados no Yahoo")
    parts = _components(f)
    exempt = {"solidez"} if f.sector == FINANCIAL and parts["solidez"] is None else set()
    missing = [_LABELS[k] for k, v in parts.items() if v is None and k not in exempt]
    available = {k: v for k, v in parts.items() if v is not None}
    notes = ("sem dado: " + ", ".join(missing)) if missing else ""
    if len(available) < MIN_COMPONENTS:
        return QualityScore(None, "dados insuficientes" + (f" ({notes})" if notes else ""))
    total = sum(weights.get(k, 0.0) for k in available)
    if total <= 0:
        return QualityScore(None, "dados insuficientes")
    score = sum(weights.get(k, 0.0) * v for k, v in available.items()) / total
    weak = [k for k, v in available.items() if v < 40 and weights.get(k, 0.0) > 0]
    if weak:
        names = {"dividendos": "dividendos", **_LABELS}
        notes = "; ".join(x for x in ("fraco em: " + ", ".join(names[k] for k in weak), notes) if x)
    return QualityScore(round(score), notes)


def rank_by_sector(universe: list[tuple[str, str]], data: dict[str, Fundamentals], held: set[str],
                   weights: dict[str, float] = QUALITY_WEIGHTS, top: int = 5) -> list[BestRow]:
    sectors: dict[str, list[BestRow]] = {}
    for sector, ticker in universe:
        f = data.get(ticker) or Fundamentals(ticker=ticker)
        q = quality_score(f, weights)
        dy = f.dividend_12m / f.price if f.price and f.dividend_12m is not None else None
        sectors.setdefault(sector, []).append(BestRow(
            sector, None, ticker, ticker in held, q.score, f.roe, f.profit_margin, f.earnings_growth,
            f.revenue_growth, f.net_debt_ebitda, dy, f.years_without_cut if f.price else None, q.notes))
    out: list[BestRow] = []
    for rows in sectors.values():
        ranked = sorted((r for r in rows if r.score is not None), key=lambda r: (-r.score, r.ticker))[:top]
        for i, r in enumerate(ranked, start=1):
            r.position = i
        out += ranked + [r for r in rows if r.score is None]
    return out


def portfolio_by_sector(holdings: dict[str, float], rows, sector_of: dict[str, str],
                        reserve: float = 0.0, reserve_label: str = "CDB", usd_brl: float | None = None,
                        ) -> list[tuple[str, float, float | None]]:
    """Valor por setor em reais. Com a cotação do dólar, o exterior entra convertido;
    sem ela, fica à parte em US$ e fora do percentual."""
    brl: dict[str, float] = {}
    usd = 0.0
    by_ticker = {r.ticker: r for r in rows}
    for ticker, qty in holdings.items():
        r = by_ticker.get(ticker)
        if r is None or r.price is None:
            continue
        value = qty * r.price
        if r.kind in ("eua", "etf"):
            usd += value
        else:
            label = "FIIs" if r.kind == "fii" else sector_of.get(ticker, "Sem setor")
            brl[label] = brl.get(label, 0.0) + value
    if usd and usd_brl:
        brl["Exterior (EUA)"] = usd * usd_brl
    if reserve and reserve > 0:
        brl[f"Reserva de emergência ({reserve_label})"] = reserve
    total = sum(brl.values())
    out: list[tuple[str, float, float | None]] = [
        (label, round(value, 2), round(value / total * 100, 1))
        for label, value in sorted(brl.items(), key=lambda kv: -kv[1])
    ]
    if usd and not usd_brl:
        out.append(("Exterior (US$)", round(usd, 2), None))
    return out
