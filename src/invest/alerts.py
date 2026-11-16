from __future__ import annotations

import smtplib
from email.message import EmailMessage

from invest.sheets import SHEET_ID, AnalysisRow, SignalChange


def render_email(changes: list[SignalChange], rows: list[AnalysisRow] | None = None) -> tuple[str, str]:
    by_ticker = {r.ticker: r for r in rows or []}
    lines = []
    for c in changes:
        line = f"{c.ticker}: {c.old} -> {c.new} ({c.date})"
        r = by_ticker.get(c.ticker)
        if r:
            ref = f"{r.reference:.2f}" if r.reference is not None else "sem preço de referência"
            price = f"{r.price:.2f}" if r.price is not None else "sem preço"
            line += f"\n   preço {price}, referência {ref}, fonte {r.source}"
        lines.append(line)
    subject = f"Investimentos: {len(changes)} mudança(s) de sinal"
    body = "\n".join(lines) + "\n\nÉ um sinal com números à vista, não uma ordem de compra ou venda."
    return subject, body


_BADGE = {  # sinal -> (fundo, texto)
    "oportunidade": ("#c6efce", "#006100"), "caro": ("#ffeb9c", "#8c5400"),
    "risco": ("#f4c7c3", "#9c0006"), "dado_velho": ("#d9d9d9", "#595959"),
    "sem_dados": ("#ededed", "#737373"), "neutro": ("#eef2f7", "#44546a"), "novo": ("#eef2f7", "#44546a"),
}
_ORDER = ["risco", "caro", "oportunidade", "dado_velho", "neutro", "sem_dados"]
_MEANING = {
    "oportunidade": "preço abaixo da referência e qualidade ok",
    "caro": "preço acima da referência (só para o que você tem)",
    "risco": "dividendo cortado, payout alto demais ou rendimento do FII em queda",
    "neutro": "nada a destacar",
    "dado_velho": "cotação desatualizada",
    "sem_dados": "faltam dados para avaliar",
}


def _br(x: float | None, suffix: str = "") -> str:
    if x is None:
        return "—"
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + suffix


def _badge(signal: str) -> str:
    bg, fg = _BADGE.get(signal, _BADGE["neutro"])
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;'
            f'font-size:12px;font-weight:bold;white-space:nowrap">{signal}</span>')


_GROUPS = [("Atenção", ("risco", "caro", "dado_velho")), ("Oportunidades", ("oportunidade",)),
           ("Outras mudanças", ("neutro", "sem_dados"))]
_PLURAL = {"oportunidade": "oportunidades", "caro": "caros", "risco": "riscos", "neutro": "neutros"}
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"


def _money(r: AnalysisRow | None, value: float | None) -> str:
    if value is None:
        return "—"
    return ("US$ " if r is not None and r.kind in ("eua", "etf") else "R$ ") + _br(value)


def _change_row(c: SignalChange, r: AnalysisRow | None) -> str:
    bg = _BADGE.get(c.new, _BADGE["neutro"])[0]
    held = (' <span style="background:#eef2f7;color:#44546a;padding:1px 6px;border-radius:8px;'
            'font-size:11px">na carteira</span>') if r and r.held else ""
    folga = ""
    if r and r.slack_pct is not None:
        col = "#006100" if r.slack_pct > 0 else "#9c0006"
        sign = "+" if r.slack_pct > 0 else ""
        folga = f'<span style="color:{col};font-weight:bold">{sign}{_br(r.slack_pct)}%</span>'
    nota = f"nota {r.score}" if r and r.score is not None else ""
    notes = (f'<div style="color:#667;font-size:12px;margin-top:4px">{r.notes}</div>' if r and r.notes else "")
    numbers = " · ".join(x for x in (
        f"preço <b>{_money(r, r.price)}</b>" if r else "",
        f"referência <b>{_money(r, r.reference)}</b>" if r and r.reference is not None else "",
        f"folga {folga}" if folga else "", nota) if x)
    return (
        f'<tr><td style="padding:12px 14px;border-bottom:1px solid #e3e7ee;border-left:5px solid {bg}">'
        f'<div style="font-size:16px"><b>{c.ticker}</b>{held}'
        f'<span style="float:right">{_badge(c.old)} &rarr; {_badge(c.new)}</span></div>'
        f'<div style="font-size:13px;margin-top:6px;color:#222">{numbers}</div>{notes}</td></tr>'
    )


def render_email_html(changes: list[SignalChange], rows: list[AnalysisRow] | None = None) -> str:
    by_ticker = {r.ticker: r for r in rows or []}
    counts: dict[str, int] = {}
    for c in changes:
        counts[c.new] = counts.get(c.new, 0) + 1
    chips = " ".join(
        f'<span style="background:{_BADGE.get(k, _BADGE["neutro"])[0]};color:{_BADGE.get(k, _BADGE["neutro"])[1]};'
        f'padding:4px 10px;border-radius:12px;font-size:13px;font-weight:bold;white-space:nowrap">'
        f'{n} {_PLURAL.get(k, k) if n > 1 else k}</span>'
        for k, n in sorted(counts.items(), key=lambda kv: _ORDER.index(kv[0]) if kv[0] in _ORDER else 99))
    blocks = []
    for title, signals in _GROUPS:
        group = sorted((c for c in changes if c.new in signals),
                       key=lambda c: (_ORDER.index(c.new) if c.new in _ORDER else 99, c.ticker))
        if not group:
            continue
        blocks.append(
            f'<h3 style="margin:22px 0 8px;font-size:15px;color:#1f3a5f">{title}</h3>'
            '<table cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;'
            'background:#fff;border:1px solid #e3e7ee">'
            + "".join(_change_row(c, by_ticker.get(c.ticker)) for c in group) + "</table>")
    legend = "".join(f'<tr><td style="padding:3px 8px 3px 0">{_badge(k)}</td>'
                     f'<td style="font-size:12px;color:#445">{v}</td></tr>' for k, v in _MEANING.items())
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:0 auto;color:#222;'
        'background:#f6f8fb;padding:20px">'
        '<div style="background:#1f3a5f;color:#fff;padding:16px 18px;border-radius:6px 6px 0 0">'
        '<div style="font-size:12px;opacity:.8">Acompanhamento de investimentos</div>'
        f'<div style="font-size:20px;font-weight:bold;margin-top:2px">{len(changes)} mudança(s) de sinal</div></div>'
        f'<div style="background:#fff;padding:12px 18px;border:1px solid #e3e7ee;border-top:0">{chips}</div>'
        + "".join(blocks) +
        f'<p style="margin:22px 0"><a href="{SHEET_URL}" style="background:#1f3a5f;color:#fff;'
        'text-decoration:none;padding:10px 16px;border-radius:4px;font-size:14px">Abrir a planilha</a></p>'
        '<p style="margin:0 0 6px;font-size:13px"><b>O que cada sinal quer dizer</b></p>'
        f'<table cellspacing="0" cellpadding="0">{legend}</table>'
        '<p style="margin-top:16px;font-size:12px;color:#667">Preço e referência na moeda de cada papel. '
        'É um sinal com números à vista, não é uma ordem de compra ou venda.</p></div>'
    )


def send_email(subject: str, body: str, to: str, user: str, password: str,
               html: str | None = None) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
