"""Camada da planilha: lê Notas/Carteira, escreve só em abas novas."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from gspread.exceptions import WorksheetNotFound  # noqa: F401 (reexportado)

SHEET_ID = "1ukZLWORhufJVCoo7SsqMFyPVQNY5ykr0IcfmdfIwHkw"
ANALYSIS, WATCH, PARAMS, HISTORY = "Análise", "Observação", "Parâmetros", "Histórico de sinais"
OWN_TABS = (ANALYSIS, WATCH, PARAMS, HISTORY)

DEFAULT_PARAMS = [
    ("dy_alvo", 0.06),
    ("retorno_exigido", 0.10),
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
    [(t, "acao_br") for t in ["TAEE11", "CPLE6", "SAPR11", "CMIG4", "PETR4", "ABEV3",
                              "WEGE3", "TIMS3", "ITUB4", "CXSE3"]]
    + [(t, "fii") for t in ["MXRF11", "XPML11", "KNRI11", "HGLG11", "VISC11"]]
    + [(t, "eua") for t in ["JNJ", "KO", "PG", "SCHD", "O"]]
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


ANALYSIS_HEADER = ["Tipo", "Papel", "Preço", "Bazin", "Graham", "Gordon", "Folga %",
                   "Nota", "Sinal", "Fonte", "Coletado em"]


def read_params(sh) -> Params:
    rows = _get(sh, PARAMS)[1:]
    kv = {str(r[0]): r[1] for r in rows if len(r) >= 2 and r[0] != ""}
    types = {str(r[3]).strip(): str(r[4]).strip() for r in rows if len(r) >= 5 and r[3] != ""}
    return Params(
        target_dy=float(kv["dy_alvo"]),
        required_return=float(kv["retorno_exigido"]),
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
        [r.kind, r.ticker, r.price, r.bazin, r.graham, r.gordon, r.slack_pct,
         r.score, r.signal, r.source, r.collected_at]
        for r in rows
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
