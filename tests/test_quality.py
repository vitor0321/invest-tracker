from datetime import datetime, timezone

from invest.data.base import Fundamentals
from invest.quality import portfolio_by_sector, quality_score, rank_by_sector
from invest.sheets import AnalysisRow

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def company(ticker="WEGE3", **over):
    base = dict(ticker=ticker, price=50.0, roe=0.25, profit_margin=0.22, earnings_growth=0.20,
                revenue_growth=0.20, net_debt_ebitda=0.5, annual_dividends=[1.0] * 6,
                years_without_cut=5, dividend_12m=2.0, source="yahoo", collected_at=NOW)
    base.update(over)
    return Fundamentals(**base)


def weak(ticker="RUIM3"):
    return company(ticker, roe=0.0, profit_margin=0.0, earnings_growth=-0.10, revenue_growth=-0.10,
                   net_debt_ebitda=4.0, annual_dividends=[], years_without_cut=0)


def test_strong_company_scores_100_and_weak_scores_0():
    assert quality_score(company()).score == 100
    assert quality_score(weak()).score == 0


def test_roe_of_10_percent_is_half_of_its_component():
    only_roe = {"roe": 1.0, "margem": 0.0, "crescimento": 0.0, "solidez": 0.0, "dividendos": 0.0}
    assert quality_score(company(roe=0.10), only_roe).score == 50


def test_missing_data_is_reweighted_and_explained():
    q = quality_score(company(roe=None, profit_margin=None))
    assert q.score == 100
    assert "ROE" in q.notes and "margem" in q.notes


def test_fewer_than_three_components_is_unranked():
    thin = company(roe=None, profit_margin=None, earnings_growth=None, revenue_growth=None)
    q = quality_score(thin)  # sobram só solidez e dividendos
    assert q.score is None and "dados insuficientes" in q.notes


def test_no_price_means_no_data():
    q = quality_score(Fundamentals(ticker="XXXX3", source="erro", collected_at=NOW))
    assert q.score is None and "sem dados" in q.notes


def test_financial_company_is_exempt_from_leverage():
    bank = company("ITUB4", net_debt_ebitda=None, sector="Financial Services")
    q = quality_score(bank)
    assert q.score == 100 and "dívida" not in q.notes
    assert "dívida" in quality_score(company(net_debt_ebitda=None)).notes


def test_absurd_growth_is_capped():
    assert quality_score(company(earnings_growth=5.0, revenue_growth=5.0)).score == 100


def test_one_growth_figure_is_enough():
    q = quality_score(company(earnings_growth=None, revenue_growth=0.20))
    assert q.score == 100


def test_rank_keeps_top_5_per_sector_in_universe_order_and_lists_unranked_last():
    universe = [("Indústria", f"IND{i}") for i in range(7)] + [("Saúde", "SAU1"), ("Saúde", "SEMD3")]
    data = {f"IND{i}": company(f"IND{i}", roe=0.02 * i) for i in range(7)}
    data["SAU1"] = company("SAU1")
    data["SEMD3"] = Fundamentals(ticker="SEMD3", source="erro", collected_at=NOW)
    rows = rank_by_sector(universe, data, held={"IND6"})
    ind = [r for r in rows if r.sector == "Indústria"]
    assert [r.ticker for r in ind] == ["IND6", "IND5", "IND4", "IND3", "IND2"]
    assert [r.position for r in ind] == [1, 2, 3, 4, 5]
    assert ind[0].held is True and ind[1].held is False
    sau = [r for r in rows if r.sector == "Saúde"]
    assert [(r.ticker, r.position) for r in sau] == [("SAU1", 1), ("SEMD3", None)]
    assert rows.index(ind[0]) < rows.index(sau[0])
    assert sau[0].dy_12m == 0.04 and sau[0].roe == 0.25


def test_rank_tolerates_ticker_missing_from_data():
    rows = rank_by_sector([("Saúde", "NADA3")], {}, held=set())
    assert rows[0].position is None and "sem dados" in rows[0].notes


def row(kind, ticker, price):
    return AnalysisRow(kind, ticker, price, None, None, None, None, None, "neutro", "yahoo", "d")


def test_portfolio_by_sector_weights_brl_and_keeps_usd_apart():
    holdings = {"ITUB4": 10, "WEGE3": 10, "ZZZZ3": 10, "MXRF11": 100, "AAPL": 2, "SEMP3": 5}
    rows = [row("acao_br", "ITUB4", 40.0), row("acao_br", "WEGE3", 50.0), row("acao_br", "ZZZZ3", 10.0),
            row("fii", "MXRF11", 10.0), row("eua", "AAPL", 200.0), row("acao_br", "SEMP3", None)]
    out = portfolio_by_sector(holdings, rows, {"ITUB4": "Financeiro", "WEGE3": "Indústria"})
    by = {label: (value, pct) for label, value, pct in out}
    assert by["Financeiro"] == (400.0, 20.0)
    assert by["Indústria"] == (500.0, 25.0)
    assert by["Sem setor"] == (100.0, 5.0)
    assert by["FIIs"] == (1000.0, 50.0)
    assert by["Exterior (US$)"] == (400.0, None)
    assert out[0][0] == "FIIs" and out[-1][0] == "Exterior (US$)"  # maior primeiro, dólar por último


def test_portfolio_converts_usd_and_includes_emergency_reserve():
    holdings = {"ITUB4": 10, "MXRF11": 100, "AAPL": 2}
    rows = [row("acao_br", "ITUB4", 100.0), row("fii", "MXRF11", 10.0), row("eua", "AAPL", 200.0)]
    out = portfolio_by_sector(holdings, rows, {"ITUB4": "Financeiro"}, reserve=1000.0, reserve_label="CDB",
                              usd_brl=5.0)
    by = {label: (value, pct) for label, value, pct in out}
    assert by["Exterior (EUA)"] == (2000.0, 40.0)
    assert by["Reserva de emergência (CDB)"] == (1000.0, 20.0)
    assert by["Financeiro"] == (1000.0, 20.0) and by["FIIs"] == (1000.0, 20.0)
    assert "Exterior (US$)" not in by
