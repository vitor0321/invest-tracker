from __future__ import annotations

import smtplib
from email.message import EmailMessage

from invest.sheets import AnalysisRow, SignalChange


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


def render_email_html(changes: list[SignalChange], rows: list[AnalysisRow] | None = None) -> str:
    by_ticker = {r.ticker: r for r in rows or []}
    ordered = sorted(changes, key=lambda c: _ORDER.index(c.new) if c.new in _ORDER else len(_ORDER))
    cell = 'style="padding:8px 10px;border-bottom:1px solid #e3e7ee;font-size:14px;{}"'
    lines = []
    for c in ordered:
        r = by_ticker.get(c.ticker)
        bg = _BADGE.get(c.new, _BADGE["neutro"])[0]
        name = f"<b>{c.ticker}</b>" + (' <span style="color:#667;font-size:11px">· na carteira</span>'
                                       if r and r.held else "")
        folga = ""
        if r and r.slack_pct is not None:
            col = "#006100" if r.slack_pct > 0 else "#9c0006"
            folga = f'<span style="color:{col};font-weight:bold">{_br(r.slack_pct, "%")}</span>'
        lines.append(
            f'<tr style="border-left:5px solid {bg}">'
            f'<td {cell.format("")}>{name}</td>'
            f'<td {cell.format("")}>{_badge(c.old)} &rarr; {_badge(c.new)}</td>'
            f'<td {cell.format("text-align:right")}>{_br(r.price if r else None)}</td>'
            f'<td {cell.format("text-align:right")}>{_br(r.reference if r else None)}</td>'
            f'<td {cell.format("text-align:right")}>{folga or "—"}</td>'
            f'<td {cell.format("text-align:center")}>{r.score if r and r.score is not None else "—"}</td>'
            f"</tr>"
        )
    th = 'style="padding:8px 10px;background:#1f3a5f;color:#fff;font-size:12px;text-align:{}"'
    legend = "".join(f"<li>{_badge(k)} {v}</li>" for k, v in _MEANING.items())
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;color:#222">'
        f'<h2 style="margin:0 0 4px">Investimentos: {len(changes)} mudança(s) de sinal</h2>'
        '<p style="margin:0 0 14px;color:#667;font-size:13px">Mais importantes primeiro. '
        'Preço e referência na moeda de cada papel.</p>'
        '<table cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse">'
        f'<tr><th {th.format("left")}>Papel</th><th {th.format("left")}>Mudança</th>'
        f'<th {th.format("right")}>Preço</th><th {th.format("right")}>Referência</th>'
        f'<th {th.format("right")}>Folga</th><th {th.format("center")}>Nota</th></tr>'
        + "".join(lines) +
        '</table>'
        '<p style="margin:18px 0 6px;font-size:13px"><b>O que cada sinal quer dizer</b></p>'
        f'<ul style="margin:0;padding-left:18px;font-size:12px;line-height:2;list-style:none">{legend}</ul>'
        '<p style="margin-top:16px;font-size:12px;color:#667">É um sinal com números à vista, '
        'não é uma ordem de compra ou venda.</p></div>'
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
