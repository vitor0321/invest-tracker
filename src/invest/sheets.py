"""Camada da planilha: lê Notas/Carteira, escreve só em abas novas."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from invest.quality import QUALITY_WEIGHTS, BestRow

from gspread.exceptions import WorksheetNotFound  # noqa: F401 (reexportado)

SHEET_ID = "1ukZLWORhufJVCoo7SsqMFyPVQNY5ykr0IcfmdfIwHkw"
ANALYSIS, WATCH, PARAMS, HISTORY = "Análise", "Observação", "Parâmetros", "Histórico de sinais"
UNIVERSE, BEST, SUMMARY = "Universo", "Melhores por setor", "Resumo"
OWN_TABS = (ANALYSIS, WATCH, PARAMS, HISTORY, UNIVERSE, BEST, SUMMARY)

# Candidatos iniciais por setor (editável na aba Universo). O ranking mostra os 5 melhores de cada.
SEED_UNIVERSE = {
    "Financeiro": ["ITUB4", "BBAS3", "BBDC4", "BPAC11", "BBSE3", "B3SA3", "CXSE3"],
    "Energia elétrica e saneamento": ["TAEE11", "CPLE3", "EGIE3", "CMIG4", "AXIA3", "SBSP3", "SAPR11"],
    "Petróleo e gás": ["PETR4", "PRIO3", "VBBR3", "UGPA3", "CSAN3", "BRAV3", "RAIZ4"],
    "Materiais básicos": ["VALE3", "SUZB3", "KLBN11", "GGBR4", "CSNA3", "USIM5", "GOAU4"],
    "Consumo e varejo": ["ABEV3", "LREN3", "RADL3", "ASAI3", "NATU3", "MDIA3", "AZZA3"],
    "Saúde": ["RDOR3", "HAPV3", "FLRY3", "HYPE3", "ODPV3", "MATD3", "PNVL3"],
    "Indústria, transporte e agro": ["WEGE3", "RENT3", "EMBR3", "RAIL3", "MOTV3", "SLCE3", "AGRO3"],
    "Telecom e tecnologia": ["VIVT3", "TIMS3", "TOTS3", "LWSA3", "INTB3", "POSI3"],
    "EUA": ["GOOGL", "AAPL", "META", "AMZN", "NVDA", "V", "FCX", "LLY", "COST", "JNJ", "KO", "PG"],
}
BEST_HEADER = ["Setor", "Pos", "Papel", "Carteira", "Nota", "ROE %", "Margem %", "Cresc. lucro %",
               "Cresc. receita %", "Dív/EBITDA", "DY 12m %", "Anos sem corte", "Motivo"]
LIST_HEADER = ["Tipo", "Carteira", "Preço", "Referência", "Folga %", "Nota", "Motivo"]
SUMMARY_COLS = 8

DEFAULT_PARAMS = [
    ("ntnb_real", 0.074),          # juro real do Tesouro IPCA+ longo; atualizar todo mês
    ("inflacao_esperada", 0.04),   # inflação de longo prazo
    ("premio_risco", 0.02),        # prêmio exigido da bolsa sobre a renda fixa
    ("retorno_exigido", ""),       # vazio = calculado dos juros; número = sobrescreve
    ("dy_alvo", ""),               # vazio = retorno exigido - inflação; número = sobrescreve
    ("eua_treasury_10a", 0.049),   # título de 10 anos dos EUA; atualizar de vez em quando
    ("eua_premio_risco", 0.045),   # prêmio da bolsa americana sobre o Treasury
    ("eua_inflacao", 0.025),
    ("fii_pvp_max", 1.0),          # FII só é oportunidade até esse P/VP
    ("fii_dy_min", ""),            # vazio = ntnb_real + 1 ponto; número = sobrescreve
    ("cortes_max", 1),             # cortes de dividendo (>20%) tolerados em 5 anos
    ("reserva_emergencia", 0),     # reserva de emergência em reais (entra no Resumo)
    ("reserva_onde", "CDB"),       # onde a reserva está aplicada (só o nome)
    ("crescimento_max", 0.15),     # trilho de crescimento: teto do crescimento na fórmula de Graham
    ("roe_min", 0.15),             # trilho de crescimento: ROE mínimo
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
    quality_weights: dict[str, float] = field(default_factory=lambda: dict(QUALITY_WEIGHTS))
    inflation: float = 0.0            # piso de crescimento no Gordon (Brasil)
    us_required_return: float = 0.10  # retorno exigido das ações dos EUA, em dólar
    us_inflation: float = 0.0
    fii_max_pvp: float = 1.0
    fii_min_dy: float = 0.08
    max_cuts: int = 1                 # cortes de dividendo tolerados em 5 anos
    risk_free: float = 0.044          # juro nominal longo do Brasil (trilho de crescimento)
    us_risk_free: float = 0.044       # título de 10 anos dos EUA
    growth_cap: float = 0.15          # crescimento máximo aceito na fórmula de Graham
    min_roe: float = 0.15
    reserve: float = 0.0              # reserva de emergência, em reais
    reserve_label: str = "CDB"


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
    for ticker, qty in _cf_detalhe_positions(sh).items():
        out.setdefault(ticker, qty)  # a aba Carteira manda; CF detalhe só completa (EUA, etc.)
    return out


def _cf_detalhe_positions(sh) -> dict[str, float]:
    """Lê (sem nunca escrever) Cod e Qtde. da aba CF detalhe: colunas C e E."""
    try:
        rows = sh.worksheet("CF detalhe").get("A1:E", value_render_option="UNFORMATTED_VALUE")
    except Exception:
        return {}
    out: dict[str, float] = {}
    for r in rows:
        if len(r) < 5:
            continue
        ticker, qty = str(r[2]).strip(), _num(r[4])
        if re.fullmatch(r"[A-Z][A-Z0-9]{0,5}", ticker) and qty and qty > 0:
            out[ticker] = qty
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
        sh.add_worksheet(title=title, rows=1000, cols=20)
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
        elif title == UNIVERSE:
            write_tab(sh, UNIVERSE, [["Setor", "Papel"]] + [[sector, t] for sector, tickers
                                                             in SEED_UNIVERSE.items() for t in tickers])
        elif title == BEST:
            write_tab(sh, BEST, [BEST_HEADER])
        elif title == SUMMARY:
            write_tab(sh, SUMMARY, [["Resumo da carteira", "aguardando a primeira rodada"]])


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


def _mask(prefix: str, *names: str) -> str:
    """Máscara de campos com caminho completo (a API não aceita parênteses em pedidos de escrita)."""
    return ",".join(f"{prefix}.{name}" for name in names)


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
        "fields": _mask("gridProperties", "frozenRowCount", "frozenColumnCount")}})
    reqs.append({"repeatCell": {
        "range": rng(0, n, 0, 1),
        "cell": {"userEnteredFormat": {
            "backgroundColor": color((0.12, 0.23, 0.37)),
            "textFormat": {"bold": True, "foregroundColor": color((1, 1, 1))},
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
        "fields": _mask("userEnteredFormat", "backgroundColor", "textFormat", "horizontalAlignment", "verticalAlignment", "wrapStrategy")}})
    for c0, c1, pattern in ((3, 8, "#,##0.00"), (8, 9, '0.0"%"'), (9, 10, "0")):
        reqs.append({"repeatCell": {
            "range": rng(c0, c1),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern},
                                           "horizontalAlignment": "RIGHT"}},
            "fields": _mask("userEnteredFormat", "numberFormat", "horizontalAlignment")}})
    reqs.append({"repeatCell": {
        "range": rng(2, 3), "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": _mask("userEnteredFormat", "horizontalAlignment")}})
    reqs.append({"repeatCell": {
        "range": rng(10, 11),
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}}},
        "fields": _mask("userEnteredFormat", "horizontalAlignment", "textFormat")}})
    reqs.append({"repeatCell": {
        "range": rng(0, n), "cell": {"userEnteredFormat": {"verticalAlignment": "MIDDLE"}},
        "fields": "userEnteredFormat.verticalAlignment"}})
    reqs.append({"repeatCell": {
        "range": rng(11, 12), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat.wrapStrategy"}})
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {  # zebra: entra primeiro, menor prioridade
        "ranges": [rng(0, n)],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=ISEVEN(ROW())"}]},
            "format": {"backgroundColor": color((0.96, 0.97, 0.99))}}}}})
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {  # o que está na carteira em negrito
        "ranges": [rng(1, 2)],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$C2="Sim"'}]},
            "format": {"textFormat": {"bold": True}}}}}})
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
        quality_weights={k: rate(f"q_peso_{k}", v) for k, v in QUALITY_WEIGHTS.items()},
        inflation=inflation,
        us_required_return=rate("eua_treasury_10a", 0.049) + rate("eua_premio_risco", 0.045),
        us_inflation=rate("eua_inflacao", 0.025),
        fii_max_pvp=rate("fii_pvp_max", 1.0),
        fii_min_dy=_num(kv.get("fii_dy_min")) or (ntnb_real + 0.01),
        max_cuts=int(rate("cortes_max", 1)),
        risk_free=(1 + ntnb_real) * (1 + inflation) - 1,
        us_risk_free=rate("eua_treasury_10a", 0.049),
        growth_cap=rate("crescimento_max", 0.15),
        min_roe=rate("roe_min", 0.15),
        reserve=rate("reserva_emergencia", 0.0),
        reserve_label=str(kv.get("reserva_onde") or "CDB").strip() or "CDB",
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


def read_universe(sh) -> list[tuple[str, str]]:
    rows = _get(sh, UNIVERSE)[1:]
    return [(str(r[0]).strip(), str(r[1]).strip()) for r in rows
            if len(r) >= 2 and str(r[0]).strip() and str(r[1]).strip()]


def _pct(x: float | None) -> float | str:
    return "" if x is None else round(x * 100, 1)


def write_best(sh, best: list[BestRow]) -> None:
    rows = [[b.sector, b.position, b.ticker, "Sim" if b.held else "", b.score, _pct(b.roe), _pct(b.margin),
             _pct(b.earnings_growth), _pct(b.revenue_growth),
             None if b.net_debt_ebitda is None else round(b.net_debt_ebitda, 2),
             _pct(b.dy_12m), b.years_without_cut, b.notes] for b in best]
    write_tab(sh, BEST, [BEST_HEADER] + [["" if v is None else v for v in r] for r in rows])


def write_summary(sh, s) -> dict:
    """Grava a aba Resumo e devolve onde cada bloco ficou (para a formatação e o gráfico)."""
    rows: list[list] = [["Resumo da carteira", f"Atualizado em {s.date}"], []]
    sections = [len(rows)]
    rows.append(["Distribuição do patrimônio", "Valor (R$)", "% do total"])
    dist_first = len(rows)
    rows += [[label, value, "" if pct is None else pct] for label, value, pct in s.distribution]
    dist_rows = sum(1 for _, _, pct in s.distribution if pct is not None)
    rows.append(["Total", s.total_brl])
    rows.append(["Dólar usado", s.usd_brl if s.usd_brl else "sem cotação: exterior em US$, fora do %"])
    while len(rows) < 22:  # espaço para o gráfico, que fica ao lado
        rows.append([])
    rows.append([])
    sections.append(len(rows))
    rows.append(["Sinais de hoje", "Na carteira", "Em observação"])
    rows += [[signal, held, watch] for signal, held, watch in s.counts]
    lists_first = len(rows)
    for title, items in (("Oportunidades", s.opportunities),
                         ("Atenção na carteira (caro e risco)", s.attention)):
        rows.append([])
        sections.append(len(rows))
        rows.append([title] + LIST_HEADER)
        rows += [[r.ticker, r.kind, "Sim" if r.held else "", r.price, r.reference, r.slack_pct, r.score, r.notes]
                 for r in items] or [["nenhum hoje"]]
    padded = [["" if v is None else v for v in r] + [""] * (SUMMARY_COLS - len(r)) for r in rows]
    write_tab(sh, SUMMARY, padded)
    return {"dist_first": dist_first, "dist_rows": dist_rows, "dist_total_rows": len(s.distribution),
            "section_rows": sections,
            "lists_first": lists_first, "total_rows": len(rows)}


SUMMARY_WIDTHS = [290, 120, 110, 95, 95, 85, 60, 420]


def build_summary_format_requests(sheet_id: int, layout: dict, chart_ids: list[int]) -> list[dict]:
    def rng(c0, c1, r0, r1):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def color(rgb):
        return {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}

    def fmt(c0, c1, r0, r1, pattern):
        return {"repeatCell": {
            "range": rng(c0, c1, r0, r1),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern},
                                           "horizontalAlignment": "RIGHT"}},
            "fields": _mask("userEnteredFormat", "numberFormat", "horizontalAlignment")}}

    d, n, end = layout["dist_first"], layout["dist_rows"], max(layout["total_rows"], 200)
    reqs: list[dict] = [{"deleteEmbeddedObject": {"objectId": cid}} for cid in chart_ids]
    reqs.append({"repeatCell": {"range": rng(0, SUMMARY_COLS, 0, end), "cell": {"userEnteredFormat": {}},
                                "fields": "userEnteredFormat"}})  # limpa a formatação da rodada anterior
    reqs.append({"repeatCell": {
        "range": rng(0, 1, 0, 1),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 16}}},
        "fields": "userEnteredFormat.textFormat"}})
    for r in layout["section_rows"]:
        reqs.append({"repeatCell": {
            "range": rng(0, SUMMARY_COLS if r >= layout["lists_first"] else 3, r, r + 1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": color((0.12, 0.23, 0.37)),
                "textFormat": {"bold": True, "foregroundColor": color((1, 1, 1))}}},
            "fields": _mask("userEnteredFormat", "backgroundColor", "textFormat")}})
    total_row = d + len_dist(layout)
    reqs += [fmt(1, 2, d, total_row + 2, "#,##0.00"), fmt(2, 3, d, total_row, '0.0"%"'),
             fmt(3, 5, layout["lists_first"], end, "#,##0.00"), fmt(5, 6, layout["lists_first"], end, '0.0"%"')]
    reqs.append({"repeatCell": {
        "range": rng(0, 2, total_row, total_row + 1),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat"}})
    reqs.append({"repeatCell": {
        "range": rng(7, 8, layout["lists_first"], end),
        "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}}, "fields": "userEnteredFormat.wrapStrategy"}})
    for i, width in enumerate(SUMMARY_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    if n:
        reqs.append({"addChart": {"chart": {
            "spec": {
                "title": "Distribuição do patrimônio",
                "pieChart": {
                    "legendPosition": "RIGHT_LEGEND",
                    "pieHole": 0.45,
                    "domain": {"sourceRange": {"sources": [rng(0, 1, d, d + n)]}},
                    "series": {"sourceRange": {"sources": [rng(1, 2, d, d + n)]}},
                }},
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": sheet_id, "rowIndex": 2, "columnIndex": 3},
                "offsetXPixels": 20, "widthPixels": 560, "heightPixels": 380}}}}})
    return reqs


def len_dist(layout: dict) -> int:
    """Linhas do bloco de distribuição, incluindo uma eventual linha em US$ fora do percentual."""
    return layout.get("dist_total_rows", layout["dist_rows"])


def format_summary(sh, layout: dict) -> None:
    ws = sh.worksheet(SUMMARY)
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),charts(chartId))"})
    charts = next(([c["chartId"] for c in s.get("charts", [])] for s in meta.get("sheets", [])
                   if s.get("properties", {}).get("sheetId") == ws.id), [])
    sh.batch_update({"requests": build_summary_format_requests(ws.id, layout, charts)})


BEST_WIDTHS = [210, 45, 80, 75, 60, 70, 80, 95, 105, 95, 80, 95, 380]


def build_best_format_requests(sheet_id: int, existing_rules: int = 0) -> list[dict]:
    def rng(c0, c1, r0=1, r1=1000):
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def color(rgb):
        return {"red": rgb[0], "green": rgb[1], "blue": rgb[2]}

    def fmt(c0, c1, pattern):
        return {"repeatCell": {
            "range": rng(c0, c1),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern},
                                           "horizontalAlignment": "RIGHT"}},
            "fields": _mask("userEnteredFormat", "numberFormat", "horizontalAlignment")}}

    n = len(BEST_HEADER)
    reqs: list[dict] = [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
                        for _ in range(existing_rules)]
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"}})
    for c0, c1 in ((0, n),):
        reqs.append({"repeatCell": {
            "range": rng(c0, c1, 0, 1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": color((0.12, 0.23, 0.37)),
                "textFormat": {"bold": True, "foregroundColor": color((1, 1, 1))},
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
            "fields": _mask("userEnteredFormat", "backgroundColor", "textFormat", "horizontalAlignment", "verticalAlignment", "wrapStrategy")}})
    reqs += [fmt(5, 9, '0.0"%"'), fmt(9, 10, "0.00"), fmt(10, 11, '0.0"%"')]
    reqs.append({"repeatCell": {
        "range": rng(12, 13), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat.wrapStrategy"}})
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [rng(0, 4)],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=$B2=1"}]},
            "format": {"backgroundColor": color((0.87, 0.92, 0.97)), "textFormat": {"bold": True}}}}}})
    for c0, c1 in ((1, 2), (3, 5), (11, 12)):
        reqs.append({"repeatCell": {
            "range": rng(c0, c1), "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": _mask("userEnteredFormat", "horizontalAlignment")}})
    for cond, value, (bg, fg) in (("NUMBER_GREATER_THAN_EQ", "70", SIGNAL_COLORS["oportunidade"]),
                                  ("NUMBER_LESS", "40", SIGNAL_COLORS["risco"])):
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(4, 5)],
            "booleanRule": {
                "condition": {"type": cond, "values": [{"userEnteredValue": value}]},
                "format": {"backgroundColor": color(bg),
                           "textFormat": {"foregroundColor": color(fg), "bold": True}}}}}})
    for i, width in enumerate(BEST_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
    reqs.append({"setBasicFilter": {"filter": {"range": rng(0, n, 0, 1000)}}})
    return reqs


def format_best(sh) -> None:
    """Formata a aba Melhores por setor. Pode rodar toda vez."""
    ws = sh.worksheet(BEST)
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),conditionalFormats)"})
    existing = next((len(s.get("conditionalFormats", [])) for s in meta.get("sheets", [])
                     if s.get("properties", {}).get("sheetId") == ws.id), 0)
    sh.batch_update({"requests": build_best_format_requests(ws.id, existing)})
