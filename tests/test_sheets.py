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
                            "conditionalFormats": [{}] * self.existing_rules,
                            "charts": [{"chartId": 100 + i} for i in range(getattr(self, "existing_charts", 0))]}]}

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


# --- melhores por setor ---
from invest.quality import QUALITY_WEIGHTS, BestRow
from invest.sheets import format_best, read_universe, write_best


def test_ensure_tabs_seeds_universe_with_8_sectors_of_at_most_7():
    sh = make_sheet()
    ensure_tabs(sh)
    universe = read_universe(sh)
    sectors = {}
    for sector, ticker in universe:
        sectors.setdefault(sector, []).append(ticker)
    assert len(sectors) == 9 and "EUA" in sectors
    assert all(1 <= len(v) <= 7 for k, v in sectors.items() if k != "EUA")
    assert len({t for _, t in universe}) == len(universe)  # sem papel repetido
    assert sh.tabs["Universo"].values[0] == ["Setor", "Papel"]
    assert sh.tabs["Melhores por setor"].values[0][:3] == ["Setor", "Pos", "Papel"]


def test_read_universe_skips_blank_and_incomplete_rows():
    sh = make_sheet()
    ensure_tabs(sh)
    sh.tabs["Universo"].values = [["Setor", "Papel"], ["Saúde", " RDOR3 "], ["", ""], ["Saúde"], ["", "X"],
                                  ["Financeiro", "ITUB4"]]
    assert read_universe(sh) == [("Saúde", "RDOR3"), ("Financeiro", "ITUB4")]


def test_write_best_writes_only_the_ranking():
    sh = make_sheet()
    ensure_tabs(sh)
    best = [BestRow("Saúde", 1, "RDOR3", True, 82, 0.214, 0.10, 0.05, -0.02, 1.25, 0.031, 4, "fraco em: margem"),
            BestRow("Saúde", None, "XXXX3", False, None, None, None, None, None, None, None, None, "sem dados")]
    write_best(sh, best)
    v = sh.tabs["Melhores por setor"].values
    assert len(v[0]) == 13
    assert v[1] == ["Saúde", 1, "RDOR3", "Sim", 82, 21.4, 10.0, 5.0, -2.0, 1.25, 3.1, 4, "fraco em: margem"]
    assert v[2][:5] == ["Saúde", "", "XXXX3", "", ""] and v[2][12] == "sem dados"


def test_quality_weights_default_on_old_sheet_and_read_when_present():
    sh = make_sheet()
    ensure_tabs(sh)
    assert read_params(sh).quality_weights == QUALITY_WEIGHTS
    _set_param(sh, "q_peso_roe", 0.5)
    w = read_params(sh).quality_weights
    assert w["roe"] == 0.5 and w["margem"] == QUALITY_WEIGHTS["margem"]


def test_format_best_resets_old_rules_and_sets_filter_on_ranking_only():
    sh = make_sheet()
    ensure_tabs(sh)
    sh.existing_rules = 2
    format_best(sh)
    reqs = sh.batches[-1]["requests"]
    kinds = [next(iter(q)) for q in reqs]
    assert kinds[:2] == ["deleteConditionalFormatRule"] * 2
    flt = next(q["setBasicFilter"]["filter"]["range"] for q in reqs if "setBasicFilter" in q)
    assert (flt["startColumnIndex"], flt["endColumnIndex"]) == (0, 13)


# --- calibragem média ---
def test_read_holdings_adds_positions_only_listed_in_cf_detalhe():
    sh = make_sheet()
    sh.tabs["CF detalhe"].values = [
        ["CNPJ", "NOME", "Cod", "Preço/m", "Qtde.", "Valor"],
        ["00", "Banco do Brasil", "BBAS3", 16.9, 999],
        ["", "", "FIIs"],
        ["", "ALPHABET INC.", "GOOGL", 115.15, 1.6802],
        ["", "Visa", "V", 326.5, 1.0],
        ["", "Zerada", "XPTO3", 10.0, 0],
        ["", "", "", "", ""],
    ]
    assert read_holdings(sh) == {"AGRO3": 22.0, "BBAS3": 259.0, "GOOGL": 1.6802, "V": 1.0}


def test_read_holdings_survives_missing_cf_detalhe():
    sh = make_sheet()
    del sh.tabs["CF detalhe"]
    assert read_holdings(sh) == {"AGRO3": 22.0, "BBAS3": 259.0}


def test_new_rate_and_fii_params_have_defaults_and_can_be_overridden():
    sh = make_sheet()
    ensure_tabs(sh)
    p = read_params(sh)
    assert p.inflation == 0.04 and p.us_inflation == 0.025 and p.max_cuts == 1
    assert p.us_required_return == pytest.approx(0.094)
    assert p.fii_max_pvp == 1.0 and p.fii_min_dy == pytest.approx(0.084)
    _set_param(sh, "fii_dy_min", 0.10)
    _set_param(sh, "eua_treasury_10a", 0.04)
    p = read_params(sh)
    assert p.fii_min_dy == 0.10 and p.us_required_return == pytest.approx(0.085)


def test_growth_track_params():
    sh = make_sheet()
    ensure_tabs(sh)
    p = read_params(sh)
    assert p.risk_free == pytest.approx(1.074 * 1.04 - 1) and p.us_risk_free == pytest.approx(0.049)
    assert p.growth_cap == 0.15 and p.min_roe == 0.15
    _set_param(sh, "crescimento_max", 0.10)
    assert read_params(sh).growth_cap == 0.10


# --- resumo, reserva de emergência e gráfico ---
from invest.portfolio import Summary
from invest.sheets import format_summary, write_summary


def test_reserve_params_default_to_zero_and_are_read():
    sh = make_sheet()
    ensure_tabs(sh)
    p = read_params(sh)
    assert p.reserve == 0.0 and p.reserve_label == "CDB"
    _set_param(sh, "reserva_emergencia", 15000)
    _set_param(sh, "reserva_onde", "Tesouro Selic")
    p = read_params(sh)
    assert p.reserve == 15000.0 and p.reserve_label == "Tesouro Selic"


def _summary():
    opp = AnalysisRow("acao_br", "CMIG4", 11.03, 12.97, None, None, 17.6, 57, "oportunidade", "yahoo", "d",
                      reference=12.97, notes="Referência: Bazin")
    att = AnalysisRow("eua", "GOOGL", 295.77, None, None, None, -50.6, 40, "caro", "yahoo", "d",
                      reference=146.17, held=True, notes="Trilho crescimento")
    return Summary("2026-11-16", [("Financeiro", 5000.0, 50.0), ("Reserva de emergência (CDB)", 4000.0, 40.0),
                                  ("FIIs", 1000.0, 10.0)], 10000.0, 5.4,
                   [("oportunidade", 0, 1), ("caro", 1, 0)], [opp], [att])


def test_write_summary_lays_out_blocks_and_returns_their_rows():
    sh = make_sheet()
    ensure_tabs(sh)
    layout = write_summary(sh, _summary())
    v = sh.tabs["Resumo"].values
    assert v[0][0] == "Resumo da carteira" and "2026-11-16" in v[0][1]
    d = layout["dist_first"]
    assert v[d - 1][:3] == ["Distribuição do patrimônio", "Valor (R$)", "% do total"]
    assert v[d][:3] == ["Financeiro", 5000.0, 50.0] and layout["dist_rows"] == 3
    assert v[d + 3][:2] == ["Total", 10000.0]
    flat = [c for row in v for c in row]
    assert "CMIG4" in flat and "GOOGL" in flat and "Dólar usado" in flat
    for r in layout["section_rows"]:
        assert v[r][0] != ""
    assert layout["dist_first"] - 1 in layout["section_rows"]


def test_format_summary_replaces_old_charts_with_one_pie_over_the_distribution():
    sh = make_sheet()
    ensure_tabs(sh)
    layout = write_summary(sh, _summary())
    sh.existing_charts = 2
    format_summary(sh, layout)
    reqs = sh.batches[-1]["requests"]
    assert [q["deleteEmbeddedObject"]["objectId"] for q in reqs if "deleteEmbeddedObject" in q] == [100, 101]
    charts = [q["addChart"]["chart"] for q in reqs if "addChart" in q]
    assert len(charts) == 1
    pie = charts[0]["spec"]["pieChart"]
    dom = pie["domain"]["sourceRange"]["sources"][0]
    ser = pie["series"]["sourceRange"]["sources"][0]
    d = layout["dist_first"]
    assert (dom["startRowIndex"], dom["endRowIndex"], dom["startColumnIndex"]) == (d, d + 3, 0)
    assert (ser["startRowIndex"], ser["endRowIndex"], ser["startColumnIndex"]) == (d, d + 3, 1)


def test_analysis_format_adds_zebra_and_wraps_reason_column():
    from invest.sheets import build_format_requests

    reqs = build_format_requests(7)
    formulas = [q["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
                for q in reqs if "addConditionalFormatRule" in q
                and q["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["type"] == "CUSTOM_FORMULA"]
    assert any("ISEVEN(ROW())" in f for f in formulas)
    wraps = [q for q in reqs if "repeatCell" in q
             and q["repeatCell"]["cell"]["userEnteredFormat"].get("wrapStrategy") == "WRAP"
             and q["repeatCell"]["range"]["startColumnIndex"] == 11]
    assert wraps


def test_no_request_field_mask_uses_parentheses():
    # a API recusa "userEnteredFormat(a,b)" em pedidos de escrita: tem de ser caminho completo
    from invest.sheets import build_best_format_requests, build_format_requests, build_summary_format_requests

    layout = {"dist_first": 3, "dist_rows": 2, "dist_total_rows": 2, "section_rows": [2, 23], "lists_first": 27,
              "total_rows": 30}
    reqs = build_format_requests(7) + build_best_format_requests(7) + build_summary_format_requests(7, layout, [])
    masks = [body["fields"] for q in reqs for body in q.values() if isinstance(body, dict) and "fields" in body]
    assert masks and not [m for m in masks if "(" in m]
