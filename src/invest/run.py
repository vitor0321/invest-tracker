from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from invest import alerts, sheets
from invest.data.base import DataProvider, Fundamentals
from invest.data.yahoo import YahooProvider
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


def analyze(ticker: str, kind: str, f: Fundamentals, p: Params, held: bool, now: datetime,
            manual_bvps: float | None = None) -> AnalysisRow:
    date = f.collected_at.date().isoformat()

    def row(signal, bazin=None, graham=None, gordon=None, slack=None, score=None, reference=None):
        return AnalysisRow(kind, ticker, f.price, bazin, graham, gordon, slack, score, signal,
                           f.source, date, reference)

    age = (now - f.collected_at).days
    bvps = f.bvps if f.bvps is not None else manual_bvps
    if f.price is None:
        return row("dado_velho" if age > p.max_age_days else "sem_dados")
    if kind == "etf":
        return row("dado_velho" if age > p.max_age_days else "neutro")

    bazin = graham = gordon = None
    if kind == "fii":
        quality = QualityResult(False, ["sem_dados"])
        reference = None
        if bvps:
            pvp = f.price / bvps
            dy = (f.dividend_12m / f.price) if f.dividend_12m is not None else None
            quality = fii_quality(FiiMetrics(pvp, dy, f.months_paid_12m))
            reference = bvps * 1.10
        regularity = f.months_paid_12m / 12
        dividend_cut = False
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
                                p.max_payout, p.max_leverage)
        regularity = len([d for d in divs if d > 0]) / 5
        dividend_cut = (len(f.annual_dividends) >= 2
                        and f.annual_dividends[-1] < f.annual_dividends[-2] * (1 - DIVIDEND_CUT_TOLERANCE))

    signal = classify(f.price, reference, quality, dividend_cut, f.payout, age, held,
                      p.max_age_days, p.max_payout)
    score = compute_score(f.price, reference, quality.passed, regularity, p.weights)
    slack = round((reference - f.price) / reference * 100, 1) if reference else None
    return row(signal, bazin, graham, gordon, slack, score, reference)


def run_once(holdings: dict[str, float], watch: list[WatchItem], params: Params,
             provider: DataProvider, previous: dict[str, str], now: datetime,
             send: Callable[[str, str, str], None],
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
        send(subject, body, params.email)
    return rows, changes


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

    def send(subject: str, body: str, to: str) -> None:
        if args.dry_run:
            print(subject, body, sep="\n")
        else:
            alerts.send_email(subject, body, to, user, os.environ["SMTP_APP_PASSWORD"])

    def record(changes):
        if not args.dry_run:
            sheets.append_signal_changes(sh, changes)

    rows, _ = run_once(sheets.read_holdings(sh), sheets.read_watchlist(sh), params,
                       YahooProvider(), sheets.last_signals(sh), now, send, record)
    sheets.write_analysis(sh, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
