"""Resumo da carteira: distribuição do patrimônio, contagem de sinais e listas do dia."""
from __future__ import annotations

from dataclasses import dataclass, field

from invest.quality import portfolio_by_sector

SIGNALS = ["oportunidade", "caro", "risco", "neutro", "dado_velho", "sem_dados"]


@dataclass
class Summary:
    date: str
    distribution: list[tuple[str, float, float | None]]
    total_brl: float
    usd_brl: float | None
    counts: list[tuple[str, int, int]]  # sinal, na carteira, em observação
    opportunities: list = field(default_factory=list)
    attention: list = field(default_factory=list)


def build_summary(holdings: dict[str, float], rows: list, sector_of: dict[str, str], reserve: float,
                  reserve_label: str, usd_brl: float | None, date: str) -> Summary:
    distribution = portfolio_by_sector(holdings, rows, sector_of, reserve, reserve_label, usd_brl)
    total = round(sum(value for _, value, pct in distribution if pct is not None), 2)
    counts = [(s, sum(1 for r in rows if r.signal == s and r.held),
               sum(1 for r in rows if r.signal == s and not r.held)) for s in SIGNALS]
    by_score = lambda r: (-(r.score if r.score is not None else -1), r.ticker)  # noqa: E731
    return Summary(
        date, distribution, total, usd_brl,
        [c for c in counts if c[1] or c[2]],
        sorted((r for r in rows if r.signal == "oportunidade"), key=by_score),
        sorted((r for r in rows if r.held and r.signal in ("risco", "caro")),
               key=lambda r: (r.signal != "risco", r.slack_pct if r.slack_pct is not None else 0)),
    )
