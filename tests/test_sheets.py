import pytest

from invest import sheets
from invest.sheets import (
    AnalysisRow,
    ForbiddenTabError,
    SignalChange,
    append_signal_changes,
    ensure_tabs,
    last_signals,
    read_holdings,
    read_params,
    read_watchlist,
    write_analysis,
)


class FakeWS:
    def __init__(self, title, values=None):
        self.title = title
        self.values = values or []

    def get(self, range_name=None, **kw):
        return [list(r) for r in self.values[self._start(range_name):]]

    @staticmethod
    def _start(range_name):
        # "A7:B" -> índice 6; sem intervalo -> 0
        if not range_name:
            return 0
        digits = "".join(c for c in range_name.split(":")[0] if c.isdigit())
        return int(digits) - 1 if digits else 0

    def update(self, values, range_name=None, **kw):
        self.values = [list(r) for r in values]

    def clear(self):
        self.values = []

    def append_rows(self, rows, **kw):
        self.values.extend([list(r) for r in rows])


class FakeSheet:
    def __init__(self, tabs):
        self.tabs = {t.title: t for t in tabs}
        self.writes = []

    def worksheet(self, title):
        if title not in self.tabs:
            raise sheets.WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows=1000, cols=26):
        self.tabs[title] = FakeWS(title)
        return self.tabs[title]

    def worksheets(self):
        return list(self.tabs.values())


def make_sheet():
    carteira = FakeWS("Carteira", [[""]] * 5 + [["Papel", "Quantidade"], ["AGRO3", 22], ["BBAS3", 259]])
    return FakeSheet([carteira, FakeWS("Notas"), FakeWS("CF detalhe")])


def test_read_holdings_ignores_zero_and_blank():
    sh = make_sheet()
    sh.tabs["Carteira"].values += [["KLBN4", 0], ["", ""]]
    assert read_holdings(sh) == {"AGRO3": 22.0, "BBAS3": 259.0}


def test_ensure_tabs_is_idempotent():
    sh = make_sheet()
    ensure_tabs(sh)
    snapshot = {k: [list(r) for r in v.values] for k, v in sh.tabs.items()}
    ensure_tabs(sh)
    assert {k: v.values for k, v in sh.tabs.items()} == snapshot
    for name in ("Análise", "Observação", "Parâmetros", "Histórico de sinais"):
        assert name in sh.tabs


def test_defaults_after_ensure():
    sh = make_sheet()
    ensure_tabs(sh)
    p = read_params(sh)
    assert p.target_dy == 0.06
    assert p.required_return == 0.10
    assert p.graham_factor == 22.5
    assert p.max_payout == 1.0
    assert p.max_leverage == 3.0
    assert p.email == "vitorwalcker.dev@gmail.com"
    assert p.weights == {"folga": 0.5, "qualidade": 0.3, "regularidade": 0.2}
    assert p.types["ITSA4"] == "acao_br" and p.types["HGRU11"] == "fii" and p.types["VOO"] == "etf"
    items = read_watchlist(sh)
    assert len(items) == 20 and items[0].ticker == "TAEE11" and items[0].kind == "acao_br"


def test_original_tabs_never_written():
    sh = make_sheet()
    ensure_tabs(sh)
    with pytest.raises(ForbiddenTabError):
        sheets.write_tab(sh, "Notas", [["x"]])
    with pytest.raises(ForbiddenTabError):
        sheets.write_tab(sh, "Carteira", [["x"]])
    with pytest.raises(ForbiddenTabError):
        sheets.write_tab(sh, "CF detalhe", [["x"]])


def test_analysis_and_history_roundtrip():
    sh = make_sheet()
    ensure_tabs(sh)
    row = AnalysisRow("acao_br", "ITUB4", 40.0, 50.0, 21.2, None, 20.0, 60, "oportunidade", "yahoo", "2026-11-16")
    write_analysis(sh, [row])
    assert sh.tabs["Análise"].values[1][1] == "ITUB4"
    assert last_signals(sh) == {}
    append_signal_changes(sh, [SignalChange("ITUB4", "neutro", "oportunidade", "2026-11-16")])
    append_signal_changes(sh, [SignalChange("ITUB4", "oportunidade", "caro", "2026-11-17")])
    assert last_signals(sh) == {"ITUB4": "caro"}
