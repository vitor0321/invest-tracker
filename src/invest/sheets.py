"""Camada da planilha: lê Notas/Carteira, escreve só em abas novas."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from gspread.exceptions import WorksheetNotFound  # noqa: F401 (reexportado)

SHEET_ID = "1ukZLWORhufJVCoo7SsqMFyPVQNY5ykr0IcfmdfIwHkw"
ANALYSIS, WATCH, PARAMS, HISTORY = "Análise", "Observação", "Parâmetros", "Histórico de sinais"
OWN_TABS = (ANALYSIS, WATCH, PARAMS, HISTORY)

DEFAULT_PARAMS = [
    ("ntnb_real", 0.074),          # juro real do Tesouro IPCA+ longo; atualizar todo mês
    ("inflacao_esperada", 0.04),   # inflação de longo prazo
    ("premio_risco", 0.02),        # prêmio exigido da bolsa sobre a renda fixa
    ("retorno_exigido", ""),       # vazio = calculado dos juros; número = sobrescreve
    ("dy_alvo", ""),               # vazio = retorno exigido - inflação; número = sobrescreve
    ("graham_fator", 22.5),
    ("payout_max", 1.0),
    ("divida_ebitda_max", 3.0),
    ("idade_max_dias", 10),
    ("peso_folga", 0.5),
    ("peso_qualidade", 0.3),
    ("peso_regularidade", 0.2),
    ("email", "vitorwalcker.dev@gmail.com"),
]

_BR = ["AGRO3", "AXIA3", "BBAS3", "BBDC4", "BBSE3", "BRSR6", "B3SA3", "EGIE3", "ISAE4",
       "ITSA4", "KLBN11", "VALE3", "VAMO3", "VIVT3", "WIZC3"]
_FII = ["BCIA11", "BTLG11", "HGRU11", "KNUQ11", "PMLL11", "VGIP11"]
_US = ["GOOGL", "AAPL", "META", "AMZN", "NVDA", "V", "FCX", "LLY", "COST"]
_ETF = ["VOO", "QQQ", "QUAL"]
SEED_TYPES = (
    [(t, "acao_br") for t in _BR] + [(t, "fii") for t in _FII]
    + [(t, "eua") for t in _US] + [(t, "etf") for t in _ETF]
)

SEED_WATCHLIST = (
    [(t, "acao_br") for t in ["TAEE11", "CPLE3", "SAPR11", "CMIG4", "PETR4", "ABEV3",
                              "WEGE3", "TIMS3", "ITUB4", "CXSE3"]]
    + [(t, "fii") for t in ["MXRF11", "XPML11", "KNRI11", "HGLG11", "VISC11"]]
    + [(t, "eua") for t in ["JNJ", "KO", "PG", "O"]] + [("SCHD", "etf")]
)


class ForbiddenTabError(Exception):
    pass


@dataclass
class WatchItem:
    ticker: str
    kind: str
    vpa_manual: float | None = None


@dataclass
class Params:
    target_dy: float
    required_return: float
    graham_factor: float
    max_payout: float
    max_leverage: float
    max_age_days: int
    weights: dict[str, float]
    email: str
    types: dict[str, str]
    vpa_manual: dict[str, float] = field(default_factory=dict)


@dataclass
class AnalysisRow:
    kind: str
    ticker: str
    price: float | None
    bazin: float | None
    graham: float | None
    gordon: float | None
    slack_pct: float | None
    score: int | None
    signal: str
    source: str
    collected_at: str
    reference: float | None = None
    held: bool = False
    notes: str = ""


@dataclass
class SignalChange:
    ticker: str
    old: str
    new: str
    date: str


def open_sheet(sa_json: str):
    import gspread

    return gspread.service_account_from_dict(json.loads(sa_json)).open_by_key(SHEET_ID)


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def read_holdings(sh) -> dict[str, float]:
    rows = sh.worksheet("Carteira").get("A7:B", value_render_option="UNFORMATTED_VALUE")
    out: dict[str, float] = {}
    for r in rows:
        if len(r) < 2 or not str(r[0]).strip():
            continue
        qty = _num(r[1])
        if qty and qty > 0:
            out[str(r[0]).strip()] = qty
    return out


def write_tab(sh, title: str, rows: list[list]) -> None:
    if title not in OWN_TABS:
        raise ForbiddenTabError(title)
    ws = sh.worksheet(title)
    ws.clear()
    ws.update(rows, "A1", value_input_option="RAW")


def _get(sh, title: str) -> list[list]:
    return sh.worksheet(title).get(value_render_option="UNFORMATTED_VALUE")


def ensure_tabs(sh) -> None:
    existing = {ws.title for ws in sh.worksheets()}
    for title in OWN_TABS:
        if title in existing:
            continue
        sh.add_worksheet(title=title, rows=1000, cols=12)
        if title == PARAMS:
            n = max(len(DEFAULT_PARAMS), len(SEED_TYPES))
            rows = [["Parâmetro", "Valor", "", "Papel", "Tipo", "VPA manual"]]
            for i in range(n):
                left = list(DEFAULT_PARAMS[i]) if i < len(DEFAULT_PARAMS) else ["", ""]
                right = list(SEED_TYPES[i]) if i < len(SEED_TYPES) else ["", ""]
                rows.append(left + [""] + right + [""])
            write_tab(sh, PARAMS, rows)
        elif title == WATCH:
            write_tab(sh, WATCH, [["Papel", "Tipo", "VPA manual"]] + [list(x) + [""] for x in SEED_WATCHLIST])
        elif title == ANALYSIS:
            write_tab(sh, ANALYSIS, [ANALYSIS_HEADER])
        elif title == HISTORY:
            write_tab(sh, HISTORY, [["Data", "Papel", "De", "Para"]])


ANALYSIS_HEADER = ["Tipo", "Papel", "Carteira", "Preço", "Bazin", "Graham", "Gordon", "Referência",
                   "Folga %", "Nota", "Sinal", "Motivo", "Fonte", "Coletado em"]

SIGNAL_ORDER = ["oportunidade", "caro", "risco", "dado_velho", "neutro", "sem_dados"]
# cores (fundo, texto) por sinal, em RGB 0-1
SIGNAL_COLORS = {
    "oportunidade": ((0.78, 0.94, 0.81), (0.0, 0.38, 0.0)),
    "caro": ((1.0, 0.92, 0.70), (0.55, 0.33, 0.0)),
    "risco": ((0.96, 0.78, 0.76), (0.61, 0.0, 0.0)),
    "dado_velho": ((0.85, 0.85, 0.85), (0.35, 0.35, 0.35)),
    "sem_dados": ((0.93, 0.93, 0.93), (0.45, 0.45, 0.45)),
}
COLUMN_WIDTHS = [70, 85, 75, 85, 85, 85, 85, 100, 80, 60, 115, 340, 75, 105]


def _sort_key(r: AnalysisRow):
    order = SIGNAL_ORDER.index(r.signal) if r.signal in SIGNAL_ORDER else len(SIGNAL_ORDER)
    return (order, -(r.score if r.score is not None else -1), r.ticker)


def build_format_requests(sheet_id: int, existing_rules: int = 0) -> list[dict]:
    def rng(c0, c1, r0=1, r1=1000):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def color(rgb):
        return {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}

    n = len(ANALYSIS_HEADER)
    reqs: list[dict] = [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
                        for _ in range(existing_rules)]
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id,
                       "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}})
    reqs.append({"repeatCell": {
        "range": rng(0, n, 0, 1),
        "cell": {"userEnteredFormat": {
            "backgroundColor": color((0.12, 0.23, 0.37)),
            "textFormat": {"bold": True, "foregroundColor": color((1, 1, 1))},
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,"
                  "verticalAlignment,wrapStrategy)"}})
    for c0, c1, pattern in ((3, 8, "#,##0.00"), (8, 9, '0.0"%"'), (9, 10, "0")):
        reqs.append({"repeatCell": {
            "range": rng(c0, c1),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern},
                                           "horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
    reqs.append({"repeatCell": {
        "range": rng(2, 3), "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat(horizontalAlignment)"}})
    reqs.append({"repeatCell": {
        "range": rng(10, 11),
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(horizontalAlignment,textFormat)"}})
    for signal, (bg, fg) in SIGNAL_COLORS.items():
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(10, 11)],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": signal}]},
                "format": {"backgroundColor": color(bg), "textFormat": {"foregroundColor": color(fg)}}}}}})
    for cond, fg in (("NUMBER_GREATER", (0.0, 0.5, 0.0)), ("NUMBER_LESS", (0.75, 0.0, 0.0))):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(8, 9)],
            "booleanRule": {
                "condition": {"type": cond, "values": [{"userEnteredValue": "0"}]},
                "format": {"textFormat": {"foregroundColor": color(fg), "bold": True}}}}}})
    for i, width in enumerate(COLUMN_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    reqs.append({"setBasicFilter": {"filter": {"range": rng(0, n, 0, 1000)}}})
    return reqs


def format_analysis(sh) -> None:
    """Formata a aba Análise (cabeçalho, filtro, cores por sinal). Pode rodar toda vez."""
    ws = sh.worksheet(ANALYSIS)
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),conditionalFormats)"})
    existing = next((len(s.get("conditionalFormats", [])) for s in meta.get("sheets", [])
                     if s.get("properties", {}).get("sheetId") == ws.id), 0)
    sh.batch_update({"requests": build_format_requests(ws.id, existing)})


def read_params(sh) -> Params:
    rows = _get(sh, PARAMS)[1:]
    kv = {str(r[0]): r[1] for r in rows if len(r) >= 2 and r[0] != ""}
    types = {str(r[3]).strip(): str(r[4]).strip() for r in rows if len(r) >= 5 and r[3] != ""}
    def rate(key: str, default: float) -> float:
        value = _num(kv.get(key))
        return default if value is None else value

    ntnb_real, inflation, premium = rate("ntnb_real", 0.074), rate("inflacao_esperada", 0.04), rate("premio_risco", 0.02)
    derived_return = (1 + ntnb_real) * (1 + inflation) - 1 + premium
    required_return = _num(kv.get("retorno_exigido")) or derived_return
    target_dy = _num(kv.get("dy_alvo")) or (required_return - inflation)
    return Params(
        target_dy=target_dy,
        required_return=required_return,
        graham_factor=float(kv["graham_fator"]),
        max_payout=float(kv["payout_max"]),
        max_leverage=float(kv["divida_ebitda_max"]),
        max_age_days=int(kv["idade_max_dias"]),
        weights={
            "folga": float(kv["peso_folga"]),
            "qualidade": float(kv["peso_qualidade"]),
            "regularidade": float(kv["peso_regularidade"]),
        },
        email=str(kv["email"]),
        types=types,
        vpa_manual={
            str(r[3]).strip(): v
            for r in rows
            if len(r) >= 6 and r[3] != "" and (v := _num(r[5])) and v > 0
        },
    )


def read_watchlist(sh) -> list[WatchItem]:
    rows = _get(sh, WATCH)[1:]
    return [
        WatchItem(str(r[0]).strip(), str(r[1]).strip(), _num(r[2]) if len(r) > 2 else None)
        for r in rows
        if len(r) >= 2 and r[0] != ""
    ]


def write_analysis(sh, rows: list[AnalysisRow]) -> None:
    body = [
        [r.kind, r.ticker, "Sim" if r.held else "", r.price, r.bazin, r.graham, r.gordon, r.reference,
         r.slack_pct, r.score, r.signal, r.notes, r.source, r.collected_at]
        for r in sorted(rows, key=_sort_key)
    ]
    write_tab(sh, ANALYSIS, [ANALYSIS_HEADER] + [["" if v is None else v for v in b] for b in body])


def last_signals(sh) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in _get(sh, HISTORY)[1:]:
        if len(r) >= 4:
            out[str(r[1])] = str(r[3])
    return out


def append_signal_changes(sh, changes: list[SignalChange]) -> None:
    if changes:
        sh.worksheet(HISTORY).append_rows(
            [[c.date, c.ticker, c.old, c.new] for c in changes], value_input_option="RAW"
        )
