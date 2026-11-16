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
    assert row.score is None and row.signal == "neutro"  # sem dividendos: sem teto, não é falha


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
    f.annual_dividends = [0.1, 1.0, 1.0]
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
    assert r1.reference == pytest.approx(min(r1.bazin, r1.gordon))
    f = good("MXRF11", price=8.75)
    f.bvps, f.dividend_12m, f.months_paid_12m = 9.926, 1.19, 12
    r2 = analyze("MXRF11", "fii", f, PARAMS, held=False, now=NOW)
    assert r2.reference == pytest.approx(9.926)


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


def test_notes_explain_quality_failures_and_reference_method():
    f = good("ITUB4", price=25.0)
    f.payout, f.eps, f.net_debt_ebitda = 1.34, 2.0, None
    f.annual_dividends = [3.0, 2.0, 3.0, 2.0, 3.0, 3.0]
    note = analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).notes
    assert "payout 134%" in note
    assert "dívida/EBITDA sem dado" in note
    assert "2 cortes de dividendo" in note
    assert "Referência: Bazin" in note


def test_notes_flag_dividend_cut_and_leverage_value():
    f = good("BBAS3", price=25.0)
    f.annual_dividends = [3.0, 3.0, 3.0, 3.0, 1.0]
    f.net_debt_ebitda = 4.5
    note = analyze("BBAS3", "acao_br", f, PARAMS, held=True, now=NOW).notes
    assert "dividendo caiu mais de 20%" in note
    assert "dívida/EBITDA 4,5" in note


def test_notes_for_clean_fii_and_failing_fii():
    f = good("MXRF11", price=10.0)
    f.bvps, f.eps = 10.0, None
    f.dividend_12m, f.months_paid_12m, f.last_dividend = 1.2, 12, 0.10
    assert analyze("MXRF11", "fii", f, PARAMS, held=False, now=NOW).notes == "Referência: VPA × 1,00"
    f.price, f.dividend_12m = 12.0, 0.5
    note = analyze("MXRF11", "fii", f, PARAMS, held=False, now=NOW).notes
    assert "P/VP 1,20" in note and "DY 4,2%" in note


# --- melhores por setor ---
def test_caching_provider_fetches_each_ticker_once():
    from invest.run import CachingProvider

    calls = []

    class Inner:
        def fetch(self, ticker, market):
            calls.append((ticker, market))
            return good(ticker)

    p = CachingProvider(Inner())
    a, b = p.fetch("ITUB4", "br"), p.fetch("ITUB4", "br")
    p.fetch("AAPL", "us")
    assert a is b and calls == [("ITUB4", "br"), ("AAPL", "us")]


def test_build_best_survives_provider_errors_and_marks_holdings():
    from invest.run import build_best

    class Flaky:
        def fetch(self, ticker, market):
            if ticker == "BOOM3":
                raise RuntimeError("yahoo fora do ar")
            f = good(ticker)
            f.roe, f.profit_margin, f.earnings_growth = 0.2, 0.2, 0.1
            return f

    universe = [("Financeiro", "ITUB4"), ("Financeiro", "BOOM3")]
    rows = [AR("acao_br", "ITUB4", 40.0, None, None, None, None, None, "neutro", "yahoo", "d", held=True)]
    best, portfolio = build_best(universe, {"ITUB4": 10}, rows, PARAMS, Flaky())
    assert [(b.ticker, b.position, b.held) for b in best] == [("ITUB4", 1, True), ("BOOM3", None, False)]
    assert portfolio == [("Financeiro", 400.0, 100.0)]


# --- calibragem média (revisão das regras) ---
from dataclasses import replace


def test_unit_is_not_flagged_by_per_share_payout():
    f = good("TAEE11")
    f.payout = 2.5  # dividendo por unit dividido por lucro por ação
    row = analyze("TAEE11", "acao_br", f, PARAMS, held=False, now=NOW)
    assert row.signal == "oportunidade" and "payout" not in row.notes


def test_us_stock_uses_us_rates_and_reference_ignores_graham():
    params = replace(PARAMS, us_required_return=0.09, us_inflation=0.025)
    row = analyze("JNJ", "eua", good("JNJ"), params, held=False, now=NOW)
    assert row.gordon == pytest.approx(3.0 * 1.025 / 0.065)
    assert row.graham is not None and row.reference == pytest.approx(row.gordon)


def test_gordon_growth_never_below_inflation():
    params = replace(PARAMS, inflation=0.04, required_return=0.14)
    row = analyze("ITUB4", "acao_br", good(), params, held=False, now=NOW)
    assert row.gordon == pytest.approx(3.0 * 1.04 / 0.10)


def test_extraordinary_dividend_year_does_not_inflate_gordon_or_flag_risk():
    f = good(price=9.0)
    f.annual_dividends = [1.0, 1.0, 1.0, 1.0, 5.0]
    f.payout = 1.6  # 12 meses com dividendo extraordinário
    row = analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW)
    assert row.gordon == pytest.approx(10.0)
    assert row.signal == "oportunidade"


def test_year_after_extraordinary_dividend_is_not_a_cut():
    f = good()
    f.annual_dividends = [3.0, 3.0, 3.0, 9.0, 3.0]
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal != "risco"


def test_one_cut_in_five_years_still_passes_but_two_do_not():
    f = good()
    f.annual_dividends = [3.0, 3.0, 2.0, 3.0, 3.0, 3.0]
    assert analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW).signal == "oportunidade"
    f.annual_dividends = [3.0, 2.0, 3.0, 2.0, 3.0, 3.0]
    row = analyze("ITUB4", "acao_br", f, PARAMS, held=False, now=NOW)
    assert row.signal == "neutro" and "2 cortes" in row.notes


def test_low_or_no_dividend_stock_gets_no_price_ceiling():
    f = good("WEGE3", price=50.0)
    f.annual_dividends = [0.5] * 5  # 1% ao ano
    row = analyze("WEGE3", "acao_br", f, PARAMS, held=True, now=NOW)
    assert row.signal == "neutro" and row.reference is None
    assert "sem dado de crescimento" in row.notes
    f.annual_dividends = []
    row = analyze("NVDA", "eua", f, PARAMS, held=True, now=NOW)
    assert row.signal == "neutro" and "sem dado de crescimento" in row.notes


def test_fii_above_book_value_is_not_opportunity():
    f = good("HGLG11", price=105.0)
    f.bvps, f.eps = 100.0, None
    f.dividend_12m, f.months_paid_12m, f.last_dividend = 12.0, 12, 1.0
    row = analyze("HGLG11", "fii", f, PARAMS, held=False, now=NOW)
    assert row.reference == pytest.approx(100.0) and row.signal == "neutro"
    assert "P/VP 1,05" in row.notes


def test_slack_is_upside_to_reference_over_price():
    row = analyze("ITUB4", "acao_br", good(price=60.0), PARAMS, held=True, now=NOW)
    assert row.reference == pytest.approx(30.0) and row.slack_pct == -50.0


def test_partial_quality_scores_above_total_failure():
    one = good(price=60.0)
    one.net_debt_ebitda = 5.0
    three = good(price=60.0)
    three.net_debt_ebitda, three.payout, three.eps = 5.0, 1.5, 1.0
    three.annual_dividends = [3.0, 2.0, 3.0, 2.0, 3.0, 3.0]
    a = analyze("ITUB4", "acao_br", one, PARAMS, held=False, now=NOW).score
    b = analyze("ITUB4", "acao_br", three, PARAMS, held=False, now=NOW).score
    assert a > b


# --- trilho de crescimento (paga menos de 2% em dividendos) ---
def grower(ticker="GOOGL", price=100.0, eps=5.0, eg=0.20, rg=0.10, roe=0.25, nde=0.5):
    f = good(ticker, price=price)
    f.annual_dividends, f.eps, f.bvps = [], eps, 20.0
    f.earnings_growth, f.revenue_growth, f.roe, f.net_debt_ebitda = eg, rg, roe, nde
    return f


def test_growth_stock_uses_graham_growth_formula_and_shows_peg():
    row = analyze("GOOGL", "eua", grower(), PARAMS, held=False, now=NOW)
    assert row.reference == pytest.approx(5.0 * (8.5 + 2 * 10))  # g = menor entre lucro e receita
    assert row.signal == "oportunidade" and row.score is not None
    assert "crescimento" in row.notes and "PEG 2,0" in row.notes


def test_growth_rate_is_capped_and_floored():
    assert analyze("X", "eua", grower(eg=0.5, rg=0.5), PARAMS, False, NOW).reference == pytest.approx(5 * 38.5)
    assert analyze("X", "eua", grower(eg=-0.2, rg=0.05), PARAMS, False, NOW).reference == pytest.approx(5 * 8.5)


def test_growth_reference_shrinks_with_each_country_interest_rate():
    params = replace(PARAMS, us_risk_free=0.088, risk_free=0.132)
    assert analyze("X", "eua", grower(), params, False, NOW).reference == pytest.approx(142.5 / 2)
    assert analyze("WEGE3", "acao_br", grower("WEGE3"), params, False, NOW).reference == pytest.approx(142.5 / 3)


def test_growth_stock_with_loss_or_shrinking_revenue_is_risk():
    row = analyze("X", "eua", grower(eps=-1.0), PARAMS, held=True, now=NOW)
    assert row.signal == "risco" and "prejuízo" in row.notes
    row = analyze("X", "eua", grower(rg=-0.2), PARAMS, held=True, now=NOW)
    assert row.signal == "risco" and "receita caiu" in row.notes


def test_growth_stock_with_low_roe_is_not_opportunity():
    row = analyze("X", "eua", grower(roe=0.08), PARAMS, held=False, now=NOW)
    assert row.signal == "neutro" and "ROE 8,0%" in row.notes


def test_growth_stock_held_above_reference_is_expensive():
    row = analyze("X", "eua", grower(price=300.0), PARAMS, held=True, now=NOW)
    assert row.signal == "caro" and row.slack_pct == -52.5


def test_growth_unit_has_no_reference():
    row = analyze("XXXX11", "acao_br", grower("XXXX11"), PARAMS, held=True, now=NOW)
    assert row.reference is None and row.signal == "neutro"


def test_fii_without_vpa_tells_user_what_to_fill():
    f = good("BCIA11", price=81.0)
    f.bvps = None
    row = analyze("BCIA11", "fii", f, PARAMS, held=True, now=NOW)
    assert row.signal == "sem_dados" and "preencha o VPA manual" in row.notes


def test_build_best_fetches_us_tickers_in_the_us_market():
    from invest.run import build_best

    seen = []

    class Rec:
        def fetch(self, ticker, market):
            seen.append((ticker, market))
            return good(ticker)

    rows = [AR("eua", "GOOGL", 300.0, None, None, None, None, None, "neutro", "yahoo", "d", held=True)]
    build_best([("EUA", "GOOGL"), ("Financeiro", "ITUB4"), ("EUA", "MSFT")], {"GOOGL": 1}, rows, PARAMS, Rec())
    assert seen == [("GOOGL", "us"), ("ITUB4", "br"), ("MSFT", "us")]  # setor "EUA" também vale


# --- resumo e e-mail novo ---
def test_build_summary_counts_signals_and_picks_lists():
    from invest.portfolio import build_summary

    rows = [AR("acao_br", "ITUB4", 100.0, None, None, None, 10.0, 60, "oportunidade", "yahoo", "d", held=True),
            AR("acao_br", "CMIG4", 11.0, None, None, None, 17.0, 57, "oportunidade", "yahoo", "d"),
            AR("eua", "GOOGL", 300.0, None, None, None, -50.0, 40, "caro", "yahoo", "d", held=True),
            AR("acao_br", "WEGE3", 50.0, None, None, None, None, None, "neutro", "yahoo", "d")]
    s = build_summary({"ITUB4": 10, "GOOGL": 1}, rows, {"ITUB4": "Financeiro"}, 1000.0, "CDB", 5.0, "2026-11-16")
    assert s.total_brl == 3500.0 and s.usd_brl == 5.0
    assert ("oportunidade", 1, 1) in s.counts and ("caro", 1, 0) in s.counts
    assert [r.ticker for r in s.opportunities] == ["ITUB4", "CMIG4"]  # maior nota primeiro
    assert [r.ticker for r in s.attention] == ["GOOGL"]


def test_new_email_groups_by_urgency_and_explains_each_change():
    from invest.alerts import render_email_html

    rows = [AR("eua", "GOOGL", 295.77, None, None, None, -50.6, 40, "caro", "yahoo", "d", reference=146.17,
               held=True, notes="Trilho crescimento | PEG 2,9"),
            AR("acao_br", "CMIG4", 11.03, 12.97, None, None, 17.6, 57, "oportunidade", "yahoo", "d",
               reference=12.97, notes="Referência: Bazin")]
    html = render_email_html([SignalChange("CMIG4", "novo", "oportunidade", "d"),
                              SignalChange("GOOGL", "novo", "caro", "d")], rows)
    assert html.index("Atenção") < html.index("GOOGL") < html.index("Oportunidades") < html.index("CMIG4")
    assert "US$ 295,77" in html and "R$ 11,03" in html
    assert "PEG 2,9" in html and "Referência: Bazin" in html
    assert "docs.google.com/spreadsheets/d/" in html
    assert "1 oportunidade" in html and "1 caro" in html
