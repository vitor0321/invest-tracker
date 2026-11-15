from datetime import datetime, timezone

from invest.alerts import render_email
from invest.data.base import Fundamentals
from invest.run import analyze, detect_changes, run_once
from invest.sheets import AnalysisRow as AR
from invest.sheets import Params, SignalChange, WatchItem

PARAMS = Params(0.06, 0.10, 22.5, 1.0, 3.0, 10,
                {"folga": 0.5, "qualidade": 0.3, "regularidade": 0.2},
                "x@y.com", {"ITUB4": "acao_br"})
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def good(ticker="ITUB4", price=25.0):
    return Fundamentals(ticker=ticker, price=price, annual_dividends=[3.0] * 5,
                        eps=4.0, bvps=30.0, payout=0.5, net_debt_ebitda=1.0,
                        years_without_cut=5, source="yahoo", collected_at=NOW)


def test_detect_changes():
    assert detect_changes({"TAEE11": "neutro"}, {"TAEE11": "oportunidade"}, "2026-11-16") == [
        SignalChange("TAEE11", "neutro", "oportunidade", "2026-11-16")
    ]
    assert detect_changes({"A": "neutro"}, {"A": "neutro"}, "d") == []
    assert detect_changes({}, {"A": "neutro", "B": "sem_dados"}, "d") == []
    assert len(detect_changes({}, {"A": "oportunidade"}, "d")) == 1


def test_analyze_opportunity():
    row = analyze("ITUB4", "acao_br", good(), PARAMS, held=False, now=NOW)
    assert row.bazin == 50.0
    assert row.signal == "oportunidade"
    assert row.score is not None


def test_analyze_no_data_has_no_score():
    row = analyze("AXIA3", "acao_br", Fundamentals(ticker="AXIA3", source="yahoo"), PARAMS, held=True, now=NOW)
    assert row.signal == "sem_dados" and row.score is None


def test_analyze_old_data_is_stale():
    f = good()
    f.collected_at = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal == "dado_velho"


def test_etf_has_no_fair_price():
    row = analyze("VOO", "etf", good("VOO"), PARAMS, held=True, now=NOW)
    assert row.bazin is None and row.score is None


class Provider:
    def __init__(self, bad=()):
        self.bad = set(bad)

    def fetch(self, ticker, market):
        if ticker in self.bad:
            raise RuntimeError("fora do ar")
        return good(ticker)


def test_run_once_sends_email_only_on_change_and_survives_failure():
    sent, history = [], {}
    items = [WatchItem("TAEE11", "acao_br"), WatchItem("BAD3", "acao_br")]
    kwargs = dict(holdings={}, watch=items, params=PARAMS, provider=Provider(bad={"BAD3"}),
                  previous=history, now=NOW, send=lambda s, b, to, html=None: sent.append((s, b, to)))
    rows, changes = run_once(**kwargs)
    assert {r.ticker: r.signal for r in rows} == {"TAEE11": "oportunidade", "BAD3": "sem_dados"}
    assert len(changes) == 1 and len(sent) == 1 and sent[0][2] == "x@y.com"
    history.update({"TAEE11": "oportunidade", "BAD3": "sem_dados"})
    sent.clear()
    _, changes2 = run_once(**kwargs)
    assert changes2 == [] and sent == []


def test_untyped_holding_is_listed_not_guessed():
    rows, _ = run_once(holdings={"ZZZ9": 1.0}, watch=[], params=PARAMS, provider=Provider(),
                       previous={}, now=NOW, send=lambda *a: None)
    assert rows[0].kind == "sem_tipo" and rows[0].signal == "sem_dados"


def test_render_email_mentions_ticker_and_signal():
    subject, body = render_email([SignalChange("TAEE11", "neutro", "oportunidade", "2026-11-16")])
    assert "TAEE11" in subject or "TAEE11" in body
    assert "oportunidade" in body


# --- correções da revisão final ---
import pytest


def rising_six_years():
    import pandas as pd

    class T:
        dividends = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                              index=pd.to_datetime([f"{y}-01-15" for y in range(2020, 2026)]))
        info = {"currentPrice": 25.0, "trailingEps": 4.0, "bookValue": 30.0, "payoutRatio": 0.5,
                "totalDebt": 100.0, "totalCash": 50.0, "ebitda": 100.0}

    return T()


def test_c1_real_dividend_series_can_reach_oportunidade():
    from invest.data.yahoo import YahooProvider

    f = YahooProvider(ticker_factory=lambda s: rising_six_years()).fetch("ITUB4", "br")
    assert f.years_without_cut == 5
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=datetime.now(timezone.utc)).signal == "oportunidade"


def test_i1_collected_at_comes_from_quote_time():
    from invest.data.yahoo import YahooProvider

    t = rising_six_years()
    t.info = dict(t.info, regularMarketTime=int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()))
    f = YahooProvider(ticker_factory=lambda s: t).fetch("X", "br")
    assert f.collected_at.year == 2026 and f.collected_at.month == 1
    assert analyze("X", "acao_br", f, PARAMS, held=False, now=NOW).signal == "dado_velho"


def test_i2_no_dividend_history_means_no_score():
    f = good()
    f.annual_dividends = []
    row = analyze("AXIA3", "acao_br", f, PARAMS, held=True, now=NOW)
    assert row.score is None and row.signal == "sem_dados"


def test_i3_unknown_type_is_sem_tipo_and_case_insensitive():
    w = [WatchItem("AAA", "FII-typo"), WatchItem("TAEE11", "ACAO_BR")]
    rows, _ = run_once({}, w, PARAMS, Provider(), {}, NOW, lambda *a: None)
    by = {r.ticker: r for r in rows}
    assert by["AAA"].kind == "sem_tipo"
    assert by["TAEE11"].kind == "acao_br"


def test_i4_no_bazin_for_us_stocks():
    row = analyze("JNJ", "eua", good("JNJ"), PARAMS, held=False, now=NOW)
    assert row.bazin is None and row.graham is not None


def test_i5_gordon_growth_is_capped_before_projection():
    f = good()
    f.annual_dividends = [0.1, 1.0]
    row = analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW)
    assert row.gordon == pytest.approx(26.5)


def test_i5_gordon_spread_too_small_is_none():
    from invest.valuation import gordon_price

    assert gordon_price(1.0, 0.061, 0.05) is None


def test_i6_history_recorded_before_email():
    order = []
    run_once({}, [WatchItem("TAEE11", "acao_br")], PARAMS, Provider(), {}, NOW,
             send=lambda *a: order.append("send"), record=lambda c: order.append("record"))
    assert order == ["record", "send"]


def test_i7_fetch_error_does_not_alert():
    assert detect_changes({"A": "oportunidade"}, {"A": "sem_dados"}, "d") == []
    assert detect_changes({"A": "sem_dados"}, {"A": "oportunidade"}, "d")[0].new == "oportunidade"


def test_manual_vpa_fills_missing_bvps_for_fii():
    from invest.sheets import Params as P

    f = good("XPML11", price=92.0)
    f.bvps, f.eps = None, None
    f.dividend_12m, f.months_paid_12m = 11.04, 12
    row = analyze("XPML11", "fii", f, PARAMS, held=False, now=NOW, manual_bvps=109.39)
    assert row.score is not None and row.signal == "oportunidade"
    assert analyze("XPML11", "fii", f, PARAMS, held=False, now=NOW).signal == "sem_dados"


def test_run_once_passes_manual_vpa_from_watchlist_and_params():
    from dataclasses import replace

    class P2(Provider):
        def fetch(self, ticker, market):
            f = good(ticker, price=92.0)
            f.bvps, f.eps = None, None
            f.dividend_12m, f.months_paid_12m = 11.04, 12
            return f

    params = replace(PARAMS, vpa_manual={"HGLG11": 158.0})
    rows, _ = run_once({}, [WatchItem("XPML11", "fii", 109.39), WatchItem("HGLG11", "fii")], params,
                       P2(), {}, NOW, lambda *a: None)
    assert {r.ticker: r.signal for r in rows} == {"XPML11": "oportunidade", "HGLG11": "oportunidade"}


def test_unit_tickers_do_not_use_per_share_eps():
    row = analyze("TAEE11", "acao_br", good("TAEE11"), PARAMS, held=False, now=NOW)
    assert row.graham is None and row.bazin == 50.0


# --- calibragem após a primeira rodada real ---
def test_gordon_growth_is_floored_at_zero():
    f = good()
    f.annual_dividends = [4.0, 3.0, 2.0, 1.0, 0.5]
    row = analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW)
    assert row.gordon == pytest.approx(5.0)  # 0,5 / 0,10, nunca abaixo disso


def test_small_dividend_dip_is_not_risk_but_a_big_cut_is():
    f = good()
    f.annual_dividends = [3.0, 3.0, 3.0, 3.0, 2.6]  # -13%
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal != "risco"
    f.annual_dividends = [3.0, 3.0, 3.0, 3.0, 2.0]  # -33%
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal == "risco"


def test_row_exposes_reference_for_stocks_and_fiis():
    r1 = analyze("ITUB4", "acao_br", good(), PARAMS, held=False, now=NOW)
    assert r1.reference == pytest.approx(min(r1.bazin, r1.graham, r1.gordon))
    f = good("MXRF11", price=8.75)
    f.bvps, f.dividend_12m, f.months_paid_12m = 9.926, 1.19, 12
    r2 = analyze("MXRF11", "fii", f, PARAMS, held=False, now=NOW)
    assert r2.reference == pytest.approx(9.926 * 1.10)


def test_email_shows_reference_for_fii():
    from invest.sheets import AnalysisRow as AR

    row = AR("fii", "MXRF11", 8.75, None, None, None, 19.9, 60, "oportunidade", "yahoo", "d", reference=10.92)
    _, body = render_email([SignalChange("MXRF11", "novo", "oportunidade", "d")], [row])
    assert "10.92" in body


def test_fii_with_big_last_payment_drop_is_risk_not_opportunity():
    f = good("VGIP11", price=64.95)
    f.bvps, f.eps = None, None
    f.dividend_12m, f.months_paid_12m, f.last_dividend = 10.29, 12, 0.67
    row = analyze("VGIP11", "fii", f, PARAMS, held=True, now=NOW, manual_bvps=90.8)
    assert row.signal == "risco"
    f.last_dividend = 0.86
    assert analyze("VGIP11", "fii", f, PARAMS, held=True, now=NOW, manual_bvps=90.8).signal == "oportunidade"


def test_bank_without_ebitda_is_not_failed_on_leverage():
    f = good("ITUB4", price=20.0)
    f.net_debt_ebitda = None
    f.sector = "Financial Services"
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal == "oportunidade"
    f.sector = "Utilities"
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal == "neutro"


def test_render_email_html_is_scannable():
    from invest.alerts import render_email_html

    rows = [AR("fii", "VGIP11", 64.95, None, None, None, 34.9, 70, "risco", "yahoo", "d", reference=99.88, held=True),
            AR("acao_br", "TAEE11", 40.0, 50.0, None, None, 20.0, 80, "oportunidade", "yahoo", "d", reference=50.0)]
    changes = [SignalChange("TAEE11", "neutro", "oportunidade", "2026-11-15"),
               SignalChange("VGIP11", "oportunidade", "risco", "2026-11-15")]
    html = render_email_html(changes, rows)
    assert "VGIP11" in html and "TAEE11" in html
    assert "64,95" in html and "99,88" in html          # formato brasileiro
    assert html.index("VGIP11") < html.index("TAEE11")  # risco vem antes de oportunidade
    assert "carteira" in html.lower()                    # marca o que você já tem
    assert "não é uma ordem" in html.lower() or "não uma ordem" in html.lower()


def test_run_once_passes_html_to_send():
    got = []
    run_once({}, [WatchItem("TAEE11", "acao_br")], PARAMS, Provider(), {}, NOW,
             lambda s, b, to, html=None: got.append(html))
    assert got and "<table" in got[0]
