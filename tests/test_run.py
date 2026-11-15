from datetime import datetime, timezone

from invest.alerts import render_email
from invest.data.base import Fundamentals
from invest.run import analyze, detect_changes, run_once
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
                  previous=history, now=NOW, send=lambda s, b, to: sent.append((s, b, to)))
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
