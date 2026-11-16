from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from invest import alerts, sheets
from invest.data.base import DataProvider, Fundamentals
from invest.data.yahoo import YahooProvider
from invest.quality import portfolio_by_sector, rank_by_sector
from invest.scoring import classify, compute_score
from invest.sheets import AnalysisRow, Params, SignalChange, WatchItem
from invest.valuation import (
    DIVIDEND_CUT_TOLERANCE,
    FiiMetrics, QualityResult, bazin_ceiling, check_quality, fii_quality,
    gordon_price, graham_fair_price, reference_price,
)

log = logging.getLogger("invest")
SILENT_FIRST = {"neutro", "sem_dados"}
VALID_KINDS = {"acao_br", "fii", "eua", "etf"}
GROWTH_CAP = 0.06


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
           reference: float | None) -> str:
    fails: list[str] = []
    for code in quality.failures:
        if code == "payout":
            fails.append("payout sem dado" if f.payout is None else f"payout {f.payout * 100:.0f}%")
        elif code == "divida":
            fails.append("dívida/EBITDA sem dado" if f.net_debt_ebitda is None
                         else f"dívida/EBITDA {_pt(f.net_debt_ebitda)}")
        elif code == "anos_sem_corte":
            fails.append(f"{f.years_without_cut} ano(s) sem corte")
        elif code == "pvp":
            fails.append("sem VPA (preencha o VPA manual)" if pvp is None else f"P/VP {_pt(pvp, 2)}")
        elif code == "dy":
            fails.append("DY sem dado" if dy is None else f"DY {_pt(dy * 100)}%")
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
            parts.append("Referência: VPA × 1,10")
        else:
            name = next((n for n, v in methods.items() if v is not None and v == reference), None)
            if name:
                parts.append(f"Referência: {name}")
    return " | ".join(parts)


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
        return row("dado_velho" if age > p.max_age_days else "neutro")

    bazin = graham = gordon = None
    pvp = dy = None
    if kind == "fii":
        quality = QualityResult(False, ["sem_dados"])
        reference = None
        if bvps:
            pvp = f.price / bvps
            dy = (f.dividend_12m / f.price) if f.dividend_12m is not None else None
            avg = (f.dividend_12m / f.months_paid_12m
                   if f.dividend_12m and f.months_paid_12m else None)
            quality = fii_quality(FiiMetrics(pvp, dy, f.months_paid_12m, f.last_dividend, avg))
            reference = bvps * 1.10
        regularity = f.months_paid_12m / 12
        dividend_cut = "queda_rendimento" in quality.failures
    else:
        if not f.annual_dividends:
            return row("sem_dados")
        divs = f.annual_dividends[-5:]
        bazin = bazin_ceiling(divs, p.target_dy) if kind == "acao_br" else None
        per_share_eps = f.eps if not ticker.endswith("11") else None  # unit: LPA do Yahoo é por ação
        graham = graham_fair_price(per_share_eps, bvps, p.graham_factor) if per_share_eps and bvps else None
        if f.annual_dividends and f.annual_dividends[-1] > 0:
            g = max(0.0, min(_growth(divs), GROWTH_CAP))
            gordon = gordon_price(f.annual_dividends[-1] * (1 + g), p.required_return, g)
        reference = reference_price([bazin, graham, gordon])
        quality = check_quality(f.payout, f.net_debt_ebitda, f.years_without_cut,
                                p.max_payout, p.max_leverage,
                                check_leverage=f.sector != "Financial Services")  # banco não tem EBITDA
        regularity = len([d for d in divs if d > 0]) / 5
        dividend_cut = (len(f.annual_dividends) >= 2
                        and f.annual_dividends[-1] < f.annual_dividends[-2] * (1 - DIVIDEND_CUT_TOLERANCE))

    signal = classify(f.price, reference, quality, dividend_cut, f.payout, age, held,
                      p.max_age_days, p.max_payout)
    score = compute_score(f.price, reference, quality.passed, regularity, p.weights)
    slack = round((reference - f.price) / reference * 100, 1) if reference else None
    notes = _notes(kind, f, p, quality, dividend_cut, pvp, dy, age,
                   {"Bazin": bazin, "Graham": graham, "Gordon": gordon}, reference)
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
    for _, ticker in universe:
        try:
            data[ticker] = provider.fetch(ticker, "br")
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
    try:  # aba extra: nunca derruba a rodada principal
        best, portfolio = build_best(sheets.read_universe(sh), holdings, rows, params, provider)
        sheets.write_best(sh, best, portfolio)
        sheets.format_best(sh)
    except Exception as exc:
        log.warning("melhores por setor falhou: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
