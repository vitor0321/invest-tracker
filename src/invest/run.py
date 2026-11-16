from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from invest import alerts, sheets
from invest.data.base import DataProvider, Fundamentals
from invest.data.yahoo import YahooProvider
from invest.portfolio import build_summary
from invest.quality import portfolio_by_sector, rank_by_sector
from invest.scoring import classify, compute_score
from invest.sheets import AnalysisRow, Params, SignalChange, WatchItem
from invest.valuation import (
    DIVIDEND_CUT_TOLERANCE,
    FiiMetrics, QualityResult, bazin_ceiling, check_quality, count_cuts, fii_quality,
    gordon_price, graham_fair_price, graham_growth_price, median, reference_price,
)

log = logging.getLogger("invest")
SILENT_FIRST = {"neutro", "sem_dados"}
VALID_KINDS = {"acao_br", "fii", "eua", "etf"}
GROWTH_CAP = 0.06
MIN_DIVIDEND_YIELD = 0.02  # abaixo disso, métodos de dividendos não dizem nada sobre o preço
REVENUE_DROP_RISK = -0.10


def detect_changes(previous: dict[str, str], current: dict[str, str], date: str) -> list[SignalChange]:
    out = []
    for ticker, new in current.items():
        old = previous.get(ticker)
        if new == "sem_dados":  # falha de fonte não vira alerta nem histórico
            continue
        if old is None:
            if new not in SILENT_FIRST:
                out.append(SignalChange(ticker, "novo", new, date))
        elif old != new:
            out.append(SignalChange(ticker, old, new, date))
    return out


def _growth(annual: list[float]) -> float:
    if len(annual) < 2 or annual[0] <= 0 or annual[-1] <= 0:
        return 0.0
    return (annual[-1] / annual[0]) ** (1 / (len(annual) - 1)) - 1


def _pt(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _notes(kind: str, f: Fundamentals, p: Params, quality: QualityResult, dividend_cut: bool,
           pvp: float | None, dy: float | None, age: int, methods: dict[str, float | None],
           reference: float | None, payout: float | None = None, cuts: int | None = None) -> str:
    fails: list[str] = []
    for code in quality.failures:
        if code == "payout":
            fails.append("payout sem dado" if payout is None else f"payout {payout * 100:.0f}%")
        elif code == "divida":
            fails.append("dívida/EBITDA sem dado" if f.net_debt_ebitda is None
                         else f"dívida/EBITDA {_pt(f.net_debt_ebitda)}")
        elif code == "cortes":
            fails.append(f"{cuts} cortes de dividendo em 5 anos")
        elif code == "historico_curto":
            fails.append("histórico de dividendos curto")
        elif code == "pvp":
            fails.append("sem VPA (preencha o VPA manual)" if pvp is None else f"P/VP {_pt(pvp, 2)}")
        elif code == "dy":
            fails.append("DY sem dado" if dy is None else f"DY {_pt(dy * 100)}%")
        elif code == "sem_dados":
            fails.append("sem VPA (preencha o VPA manual)")
        elif code == "regularidade":
            fails.append(f"só {f.months_paid_12m} de 12 meses com rendimento")
        elif code == "queda_rendimento":
            fails.append("último rendimento caiu mais de 20%")
        else:
            fails.append(code)
    if dividend_cut and "queda_rendimento" not in quality.failures:
        fails.append("dividendo caiu mais de 20% no último ano")
    parts = []
    if age > p.max_age_days:
        parts.append(f"cotação de {age} dias atrás")
    if fails:
        parts.append("Reprovou: " + "; ".join(fails))
    if reference is not None:
        if kind == "fii":
            parts.append(f"Referência: VPA × {_pt(p.fii_max_pvp, 2)}")
        else:
            name = next((n for n, v in methods.items() if v is not None and v == reference), None)
            if name:
                parts.append(f"Referência: {name}")
            graham = methods.get("Graham")
            if graham is not None and f.price is not None and f.price > graham:
                parts.append("acima do Graham")
    return " | ".join(parts)


def _etf_notes(f: Fundamentals) -> str:
    """ETF não tem preço teto: mostra só indicadores de momento."""
    parts = ["ETF: cesta de ações, sem preço teto"]
    if f.high_52w and f.high_52w > 0:
        gap = (f.high_52w - f.price) / f.high_52w * 100
        parts.append("na máxima de 52 semanas" if gap < 0.05
                     else f"{_pt(gap)}% abaixo da máxima de 52 semanas")
    if f.avg_200d and f.avg_200d > 0:
        diff = (f.price - f.avg_200d) / f.avg_200d * 100
        parts.append(f"{_pt(abs(diff))}% {'acima' if diff >= 0 else 'abaixo'} da média de 200 dias")
    return " | ".join(parts)


def _growth_track(ticker: str, kind: str, f: Fundamentals, p: Params, held: bool, age: int, row):
    """Paga menos de 2% em dividendos: preço pela fórmula de crescimento de Graham."""
    label = "Trilho crescimento (paga pouco dividendo)"
    stale = age > p.max_age_days
    unit = kind == "acao_br" and ticker.endswith("11")
    rates = [g for g in (f.earnings_growth, f.revenue_growth) if g is not None]
    if f.eps is not None and f.eps <= 0 and not unit:
        return row("dado_velho" if stale else "risco", notes=f"{label} | Reprovou: prejuízo nos últimos 12 meses")
    if unit or f.eps is None or not rates:
        missing = "unit sem lucro por unit" if unit else ("sem lucro por ação" if f.eps is None
                                                           else "sem dado de crescimento")
        return row("dado_velho" if stale else "neutro", notes=f"{label} | {missing}: sem preço de referência")
    growth = max(0.0, min(min(rates), p.growth_cap))  # o menor entre lucro e receita, limitado
    reference = graham_growth_price(f.eps, growth, p.us_risk_free if kind == "eua" else p.risk_free)
    graham = graham_fair_price(f.eps, f.bvps, p.graham_factor) if f.bvps else None
    financial = f.sector == "Financial Services"
    fails: list[str] = []
    if f.roe is None or f.roe < p.min_roe:
        fails.append("ROE sem dado" if f.roe is None else f"ROE {_pt(f.roe * 100)}%")
    if not financial and (f.net_debt_ebitda is None or f.net_debt_ebitda > p.max_leverage):
        fails.append("dívida/EBITDA sem dado" if f.net_debt_ebitda is None
                     else f"dívida/EBITDA {_pt(f.net_debt_ebitda)}")
    shrinking = f.revenue_growth is not None and f.revenue_growth < REVENUE_DROP_RISK
    if shrinking:
        fails.append(f"receita caiu {_pt(-f.revenue_growth * 100)}%")
    elif f.revenue_growth is not None and f.revenue_growth < 0:
        fails.append("receita em queda")
    checks = 3 - int(financial)
    quality = QualityResult(not fails, fails)
    signal = classify(f.price, reference, quality, shrinking, None, age, held, p.max_age_days, p.max_payout)
    regularity = len([g for g in rates if g > 0]) / len(rates)
    score = compute_score(f.price, reference, max(0.0, 1 - len(fails) / checks), regularity, p.weights)
    slack = round((reference - f.price) / f.price * 100, 1) if reference else None
    parts = [label]
    if fails:
        parts.append("Reprovou: " + "; ".join(fails))
    parts.append(f"Referência: Graham de crescimento (g {_pt(growth * 100)}%)")
    if growth > 0:
        parts.append(f"PEG {_pt(f.price / f.eps / (growth * 100))}")
    return row(signal, None, graham, None, slack, score, reference, " | ".join(parts))


def analyze(ticker: str, kind: str, f: Fundamentals, p: Params, held: bool, now: datetime,
            manual_bvps: float | None = None) -> AnalysisRow:
    date = f.collected_at.date().isoformat()

    def row(signal, bazin=None, graham=None, gordon=None, slack=None, score=None, reference=None,
            notes=""):
        return AnalysisRow(kind, ticker, f.price, bazin, graham, gordon, slack, score, signal,
                           f.source, date, reference, held, notes)

    age = (now - f.collected_at).days
    bvps = f.bvps if f.bvps is not None else manual_bvps
    if f.price is None:
        return row("dado_velho" if age > p.max_age_days else "sem_dados")
    if kind == "etf":
        return row("dado_velho" if age > p.max_age_days else "neutro", notes=_etf_notes(f))

    bazin = graham = gordon = None
    pvp = dy = None
    payout, cuts = f.payout, None
    if kind == "fii":
        quality = QualityResult(False, ["sem_dados"])
        checks = 4
        reference = None
        if bvps:
            pvp = f.price / bvps
            dy = (f.dividend_12m / f.price) if f.dividend_12m is not None else None
            avg = (f.dividend_12m / f.months_paid_12m
                   if f.dividend_12m and f.months_paid_12m else None)
            quality = fii_quality(FiiMetrics(pvp, dy, f.months_paid_12m, f.last_dividend, avg),
                                  p.fii_max_pvp, p.fii_min_dy)
            reference = bvps * p.fii_max_pvp
        regularity = f.months_paid_12m / 12
        dividend_cut = "queda_rendimento" in quality.failures
    else:
        divs = f.annual_dividends[-5:]
        if not divs or (sum(divs) / len(divs)) / f.price < MIN_DIVIDEND_YIELD:
            # empresa de crescimento: Bazin e Gordon dariam um teto sem sentido
            return _growth_track(ticker, kind, f, p, held, age, row)
        us = kind == "eua"
        required_return = p.us_required_return if us else p.required_return
        inflation = p.us_inflation if us else p.inflation
        unit = kind == "acao_br" and ticker.endswith("11")  # LPA do Yahoo é por ação, não por unit
        typical = median(divs)
        if unit:
            payout = None
        elif payout is not None and f.eps and f.eps > 0:
            payout = min(payout, typical / f.eps)  # ano de dividendo extraordinário não conta
        bazin = bazin_ceiling(divs, p.target_dy) if kind == "acao_br" else None
        graham = (graham_fair_price(f.eps, bvps, p.graham_factor)
                  if f.eps and bvps and not unit else None)
        base = min(divs[-1], typical)
        if base > 0:
            g = max(inflation, min(_growth(divs[:-1] + [base]), GROWTH_CAP))
            gordon = gordon_price(base * (1 + g), required_return, g, max(GROWTH_CAP, inflation))
        reference = reference_price([bazin, gordon])  # Graham é só informativo
        cuts = count_cuts(f.annual_dividends)
        financial = f.sector == "Financial Services"  # banco não tem EBITDA
        quality = check_quality(payout, f.net_debt_ebitda, cuts, p.max_payout, p.max_leverage,
                                p.max_cuts, check_leverage=not financial, check_payout=not unit)
        checks = 3 - int(financial) - int(unit)
        regularity = len([d for d in divs if d > 0]) / 5
        previous = f.annual_dividends[:-1]
        floor = 1 - DIVIDEND_CUT_TOLERANCE
        dividend_cut = (bool(previous) and divs[-1] < previous[-1] * floor
                        and divs[-1] < median(previous[-4:]) * floor)

    signal = classify(f.price, reference, quality, dividend_cut, payout, age, held,
                      p.max_age_days, p.max_payout)
    passed = max(0.0, 1 - len(quality.failures) / checks) if checks else 1.0
    score = compute_score(f.price, reference, passed, regularity, p.weights)
    slack = round((reference - f.price) / f.price * 100, 1) if reference else None
    notes = _notes(kind, f, p, quality, dividend_cut, pvp, dy, age,
                   {"Bazin": bazin, "Graham": graham, "Gordon": gordon}, reference, payout, cuts)
    return row(signal, bazin, graham, gordon, slack, score, reference, notes)


def run_once(holdings: dict[str, float], watch: list[WatchItem], params: Params,
             provider: DataProvider, previous: dict[str, str], now: datetime,
             send: Callable[..., None],
             record: Callable[[list[SignalChange]], None] | None = None) -> tuple[list[AnalysisRow], list[SignalChange]]:
    targets: list[tuple[str, str | None, bool, float | None]] = [
        (t, params.types.get(t), True, params.vpa_manual.get(t)) for t in holdings
    ] + [(w.ticker, w.kind, False, w.vpa_manual or params.vpa_manual.get(w.ticker))
         for w in watch if w.ticker not in holdings]
    rows: list[AnalysisRow] = []
    for ticker, kind, held, manual in targets:
        kind = kind.strip().lower() if kind else None
        if kind not in VALID_KINDS:
            rows.append(AnalysisRow("sem_tipo", ticker, None, None, None, None, None, None,
                                    "sem_dados", "", now.date().isoformat()))
            continue
        market = "us" if kind in ("eua", "etf") else "br"
        try:
            f = provider.fetch(ticker, market)
        except Exception as exc:
            log.warning("falha ao buscar %s: %s", ticker, exc)
            f = Fundamentals(ticker=ticker, source="erro", collected_at=now)
        rows.append(analyze(ticker, kind, f, params, held, now, manual))
    current = {r.ticker: r.signal for r in rows}
    changes = detect_changes(previous, current, now.date().isoformat())
    if changes:
        if record:
            record(changes)
        subject, body = alerts.render_email(changes, rows)
        send(subject, body, params.email, alerts.render_email_html(changes, rows))
    return rows, changes


class CachingProvider:
    """Evita buscar o mesmo papel duas vezes na mesma rodada."""

    def __init__(self, inner):
        self.inner = inner
        self._cache: dict[tuple[str, str], Fundamentals] = {}

    def fetch(self, ticker: str, market: str) -> Fundamentals:
        key = (ticker, market)
        if key not in self._cache:
            self._cache[key] = self.inner.fetch(ticker, market)
        return self._cache[key]


def build_best(universe: list[tuple[str, str]], holdings: dict[str, float], rows: list[AnalysisRow],
               params: Params, provider):
    data: dict[str, Fundamentals] = {}
    kinds = {r.ticker: r.kind for r in rows}
    for sector, ticker in universe:
        us = kinds.get(ticker) in ("eua", "etf") or sector.strip().upper() == "EUA"
        try:
            data[ticker] = provider.fetch(ticker, "us" if us else "br")
        except Exception as exc:
            log.warning("falha ao buscar %s: %s", ticker, exc)
    best = rank_by_sector(universe, data, set(holdings), params.quality_weights)
    portfolio = portfolio_by_sector(holdings, rows, {t: s for s, t in universe})
    return best, portfolio


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="não envia e-mail nem grava histórico")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    sh = sheets.open_sheet(os.environ["GOOGLE_SA_JSON"])
    sheets.ensure_tabs(sh)
    params = sheets.read_params(sh)
    now = datetime.now(timezone.utc)
    user = os.environ.get("SMTP_USER", "vitorwalcker.dev@gmail.com")

    def send(subject: str, body: str, to: str, html: str | None = None) -> None:
        if args.dry_run:
            print(subject, body, sep="\n")
        else:
            alerts.send_email(subject, body, to, user, os.environ["SMTP_APP_PASSWORD"], html)

    def record(changes):
        if not args.dry_run:
            sheets.append_signal_changes(sh, changes)

    holdings = sheets.read_holdings(sh)
    provider = CachingProvider(YahooProvider())
    rows, _ = run_once(holdings, sheets.read_watchlist(sh), params,
                       provider, sheets.last_signals(sh), now, send, record)
    sheets.write_analysis(sh, rows)
    try:
        sheets.format_analysis(sh)
    except Exception as exc:  # visual nunca derruba a rodada
        log.warning("formatação falhou: %s", exc)
    universe: list[tuple[str, str]] = []
    try:  # abas extras: nunca derrubam a rodada principal
        universe = sheets.read_universe(sh)
        best, _ = build_best(universe, holdings, rows, params, provider)
        sheets.write_best(sh, best)
        sheets.format_best(sh)
    except Exception as exc:
        log.warning("melhores por setor falhou: %s", exc)
    try:
        usd_brl = None
        try:
            usd_brl = provider.fetch("BRL=X", "us").price  # dólar em reais
        except Exception as exc:
            log.warning("cotação do dólar falhou: %s", exc)
        summary = build_summary(holdings, rows, {t: s for s, t in universe}, params.reserve,
                                params.reserve_label, usd_brl, now.date().isoformat())
        sheets.format_summary(sh, sheets.write_summary(sh, summary))
    except Exception as exc:
        log.warning("resumo falhou: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
