"""Resumo da carteira: distribuição do patrimônio, contagem de sinais e listas do dia."""
from __future__ import annotations

from dataclasses import dataclass, field

from invest.quality import portfolio_by_sector

SIGNALS = ["oportunidade", "caro", "risco", "neutro", "dado_velho", "sem_dados"]


DEFAULT_CLASS = {"acao_br": "Ações Brasil", "fii": "FIIs", "eua": "Ações EUA", "etf": "ETFs EUA"}


@dataclass
class Allocation:
    label: str
    value: float              # em reais
    pct: float                # % atual dos investimentos (sem a reserva)
    target: float | None      # % alvo
    deviation: float | None   # atual - alvo, em pontos percentuais
    gap: float | None         # reais que faltam (+) ou sobram (-) para o alvo


def build_allocation(holdings: dict[str, float], rows: list, classes: dict[str, str],
                     targets: dict[str, float], usd_brl: float | None) -> list[Allocation]:
    """Peso de cada classe contra o alvo. Sem a cotação do dólar não dá para somar: devolve vazio."""
    if not usd_brl:
        return []
    values: dict[str, float] = {label: 0.0 for label in targets}
    by_ticker = {r.ticker: r for r in rows}
    for ticker, qty in holdings.items():
        r = by_ticker.get(ticker)
        if r is None or r.price is None or r.kind not in DEFAULT_CLASS:
            continue
        label = classes.get(ticker) or DEFAULT_CLASS[r.kind]
        values[label] = values.get(label, 0.0) + qty * r.price * (usd_brl if r.kind in ("eua", "etf") else 1.0)
    total = sum(values.values())
    if total <= 0:
        return []
    out = []
    for label, value in values.items():
        pct = round(value / total * 100, 1)
        target = targets.get(label)
        if target is None:
            out.append(Allocation(label, round(value, 2), pct, None, None, None))
        else:
            out.append(Allocation(label, round(value, 2), pct, round(target * 100, 1),
                                  round(pct - target * 100, 1), round(target * total - value, 2)))
    # onde o próximo aporte ajuda mais vem primeiro; sem alvo, o maior primeiro
    return sorted(out, key=lambda a: (a.gap is None, -(a.gap or 0.0), -a.value))


@dataclass
class Summary:
    date: str
    distribution: list[tuple[str, float, float | None]]
    total_brl: float
    usd_brl: float | None
    counts: list[tuple[str, int, int]]  # sinal, na carteira, em observação
    opportunities: list = field(default_factory=list)
    attention: list = field(default_factory=list)
    allocation: list = field(default_factory=list)


def build_summary(holdings: dict[str, float], rows: list, sector_of: dict[str, str], reserve: float,
                  reserve_label: str, usd_brl: float | None, date: str,
                  classes: dict[str, str] | None = None, targets: dict[str, float] | None = None) -> Summary:
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
        build_allocation(holdings, rows, classes or {}, targets or {}, usd_brl),
    )
