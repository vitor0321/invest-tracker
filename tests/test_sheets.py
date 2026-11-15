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
    id = 7

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

    existing_rules = 0
    batches: list = []

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": [{"properties": {"sheetId": 7, "title": "Análise"},
                            "conditionalFormats": [{}] * self.existing_rules}]}

    def batch_update(self, body):
        self.batches = getattr(self, "batches", []) + [body]


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
    assert p.required_return == pytest.approx(0.1370, abs=1e-4)  # NTN-B 7,4% real + 4% inflação + 2% prêmio
    assert p.target_dy == pytest.approx(0.0970, abs=1e-4)  # retorno exigido - inflação
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


def test_manual_vpa_columns_roundtrip():
    sh = make_sheet()
    ensure_tabs(sh)
    sh.tabs["Observação"].values[1] = ["TAEE11", "acao_br", 23.4]
    sh.tabs["Parâmetros"].values[1] = sh.tabs["Parâmetros"].values[1][:5] + [158.0]
    assert read_watchlist(sh)[0].vpa_manual == 23.4
    assert read_watchlist(sh)[1].vpa_manual is None
    p = read_params(sh)
    assert p.vpa_manual == {"AGRO3": 158.0}


def test_seed_watchlist_uses_current_codes_and_etf_type():
    sh = make_sheet()
    ensure_tabs(sh)
    items = {i.ticker: i.kind for i in read_watchlist(sh)}
    assert "CPLE6" not in items and items["CPLE3"] == "acao_br"
    assert items["SCHD"] == "etf"
    assert "Referência" in sh.tabs["Análise"].values[0]


def _set_param(sh, key, value):
    for row in sh.tabs["Parâmetros"].values[1:]:
        if row[0] == key:
            row[1] = value
            return
    sh.tabs["Parâmetros"].values.append([key, value])


def test_rates_drive_required_return_and_target_dy():
    sh = make_sheet()
    ensure_tabs(sh)
    _set_param(sh, "ntnb_real", 0.06)
    _set_param(sh, "inflacao_esperada", 0.0)
    _set_param(sh, "premio_risco", 0.02)
    p = read_params(sh)
    assert p.required_return == pytest.approx(0.08)
    assert p.target_dy == pytest.approx(0.08)


def test_explicit_dy_alvo_and_retorno_exigido_override_the_rates():
    sh = make_sheet()
    ensure_tabs(sh)
    _set_param(sh, "dy_alvo", 0.06)
    _set_param(sh, "retorno_exigido", 0.10)
    p = read_params(sh)
    assert p.target_dy == 0.06 and p.required_return == 0.10


def test_old_sheet_without_rate_params_still_reads():
    sh = make_sheet()
    ensure_tabs(sh)
    sh.tabs["Parâmetros"].values = [r for r in sh.tabs["Parâmetros"].values
                                    if r[0] not in ("ntnb_real", "inflacao_esperada", "premio_risco")]
    assert read_params(sh).required_return == pytest.approx(0.1370, abs=1e-4)


def test_analysis_sorted_by_actionability_and_marks_holdings():
    sh = make_sheet()
    ensure_tabs(sh)

    def r(t, sig, score, held=False):
        return AnalysisRow("acao_br", t, 10.0, None, None, None, 5.0, score, sig, "yahoo", "d", held=held)

    write_analysis(sh, [r("N1", "neutro", 90), r("R1", "risco", 50), r("C1", "caro", 40, True),
                        r("O1", "oportunidade", 60), r("O2", "oportunidade", 80)])
    values = sh.tabs["Análise"].values
    assert [row[1] for row in values[1:]] == ["O2", "O1", "C1", "R1", "N1"]
    assert values[0][2] == "Carteira"
    assert [row[2] for row in values[1:]] == ["", "", "Sim", "", ""]


def test_format_analysis_applies_header_filter_rules_and_resets_old_rules():
    from invest.sheets import format_analysis

    sh = make_sheet()
    ensure_tabs(sh)
    sh.existing_rules = 3
    format_analysis(sh)
    reqs = sh.batches[0]["requests"]
    kinds = [next(iter(q)) for q in reqs]
    assert kinds[:3] == ["deleteConditionalFormatRule"] * 3      # idempotente: limpa regras antigas
    assert "setBasicFilter" in kinds and "updateSheetProperties" in kinds
    texts = [q["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
             for q in reqs if "addConditionalFormatRule" in q
             and q["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["type"] == "TEXT_EQ"]
    assert set(texts) == {"oportunidade", "caro", "risco", "dado_velho", "sem_dados"}


def test_analysis_tab_has_reason_column_after_signal():
    sh = make_sheet()
    ensure_tabs(sh)
    write_analysis(sh, [AnalysisRow("acao_br", "ITUB4", 40.0, 50.0, 21.2, None, 20.0, 60, "neutro",
                                    "yahoo", "d", notes="payout 134%")])
    header, row = sh.tabs["Análise"].values[0], sh.tabs["Análise"].values[1]
    assert header[10:13] == ["Sinal", "Motivo", "Fonte"]
    assert row[11] == "payout 134%" and row[12] == "yahoo"
