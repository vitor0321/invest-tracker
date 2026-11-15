"""Prova dos dados: imprime o que a fonte devolve para 5 papéis de cada tipo.

Rode na sua máquina: python scripts/prova_dados.py
Compare com Status Invest ou Investidor10.
"""
from invest.data.yahoo import YahooProvider

SAMPLE = {
    "br": ["ITUB4", "TAEE11", "BBAS3", "EGIE3", "VALE3"],
    "fii": ["MXRF11", "XPML11", "KNRI11", "HGLG11", "BTLG11"],
    "us": ["JNJ", "KO", "PG", "AAPL", "O"],
}


def main() -> None:
    provider = YahooProvider()
    for kind, tickers in SAMPLE.items():
        market = "us" if kind == "us" else "br"
        print(f"\n== {kind} ==")
        for t in tickers:
            f = provider.fetch(t, market)
            last5 = f.annual_dividends[-5:]
            avg = sum(last5) / len(last5) if last5 else None
            print(
                f"{t:8} preço={f.price} div_médio_5a={avg} div_12m={f.dividend_12m} "
                f"LPA={f.eps} VPA={f.bvps} payout_próprio={f.payout} "
                f"moeda={f.currency}/{f.financial_currency} fonte={f.source}"
            )
            print(f"         dividendos por ano (6 últimos anos completos): {f.annual_dividends}")


if __name__ == "__main__":
    main()
