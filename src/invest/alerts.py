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
            refs = [v for v in (r.bazin, r.graham, r.gordon) if v is not None]
            ref = f"{min(refs):.2f}" if refs else "sem preço de referência"
            price = f"{r.price:.2f}" if r.price is not None else "sem preço"
            line += f"\n   preço {price}, referência {ref}, fonte {r.source}"
        lines.append(line)
    subject = f"Investimentos: {len(changes)} mudança(s) de sinal"
    body = "\n".join(lines) + "\n\nÉ um sinal com números à vista, não uma ordem de compra ou venda."
    return subject, body


def send_email(subject: str, body: str, to: str, user: str, password: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
