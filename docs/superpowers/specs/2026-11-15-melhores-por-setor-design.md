# Melhores por setor — desenho

## Intenção
Vitor quer diversificar a carteira em vários setores. Precisa ver, por setor, as 5 empresas brasileiras
mais sólidas e com melhor perspectiva para investir a longo prazo. "Melhor" aqui é qualidade do negócio,
não preço baixo (o preço teto continua na aba `Análise`).

## Objetivos / não-objetivos / anti-objetivos
- Objetivo: aba com top 5 por setor e bloco mostrando quanto da carteira está em cada setor.
- Não-objetivo (v1): ações dos EUA, FIIs, tese qualitativa escrita por mim, varrer toda a B3.
- Anti-objetivo: parecer recomendação de compra. É um ranking de qualidade por números; o preço pode estar caro.

## Restrições
- Só dados gratuitos (Yahoo via yfinance), rodando no GitHub Actions já existente.
- Abas existentes e as originais (Notas, Carteira, CF detalhe) não mudam.
- O limite antigo de 20 papéis deixa de valer: ~55 papéis, coleta de poucos minutos.

## Abordagens consideradas
1. **Lista curada + nota objetiva (escolhida).** Eu monto o universo, Vitor edita; nota calculada de dados.
2. Lista curada + tese escrita por mim: descartada (opinião que envelhece).
3. Varrer toda a B3: descartada (sem lista gratuita confiável; entram papéis sem liquidez).

## Desenho
- **Aba `Universo` (entrada, editável):** colunas Setor, Papel. Vitor adiciona/remove linhas livremente.
- **Aba `Melhores por setor` (saída):** por setor, até 5 linhas ordenadas por nota de qualidade, com:
  posição, papel, nota (0-100), ROE, margem, crescimento de lucro, crescimento de receita,
  dívida/EBITDA, DY 12m, anos sem corte, "na carteira", e coluna Motivo (o que puxou a nota para baixo / dados que faltaram).
- **Bloco "Carteira por setor"** na mesma aba (ou em aba própria `Carteira por setor`): peso de cada setor no valor
  da carteira (quantidade x preço), com "Sem setor" para papel que não está no Universo.
- Reaproveita `YahooProvider`; novos campos em `Fundamentals`: roe, margem, crescimento de lucro e de receita.
- Mesma rodada diária; falha de um papel não derruba a aba (papel sem dados fica fora do ranking e aparece no Motivo).

## Nota de qualidade (decisão minha; pesos editáveis na aba `Parâmetros`)
| Componente | Peso | Fonte |
|---|---|---|
| Rentabilidade (ROE) | 25% | Yahoo `returnOnEquity` |
| Margem líquida | 15% | Yahoo `profitMargins` |
| Crescimento (lucro e receita) | 25% | Yahoo `earningsGrowth`, `revenueGrowth` |
| Solidez (dívida/EBITDA; financeiras isentas) | 15% | já coletado |
| Dividendos (anos sem corte, regularidade) | 20% | já coletado |

Cada componente vira 0-100 por faixas fixas (ex.: ROE 0% = 0, 20% ou mais = 100). Dado faltando: componente sai e
os pesos restantes são reponderados; menos de 3 componentes disponíveis = papel fora do ranking.

## Setores (8) e candidatos iniciais (até 7)
Lista inicial minha; Vitor edita no `Universo`.
- **Financeiro:** ITUB4, BBAS3, BBDC4, BPAC11, BBSE3, B3SA3, CXSE3
- **Energia elétrica e saneamento:** TAEE11, CPLE3, EGIE3, CMIG4, AXIA3, SBSP3, SAPR11
- **Petróleo e gás:** PETR4, PRIO3, VBBR3, UGPA3, CSAN3, BRAV3, RAIZ4
- **Materiais básicos:** VALE3, SUZB3, KLBN11, GGBR4, CSNA3, USIM5, GOAU4
- **Consumo e varejo:** ABEV3, LREN3, RADL3, ASAI3, NATU3, MDIA3, ARZZ3
- **Saúde:** RDOR3, HAPV3, FLRY3, HYPE3, ODPV3, MATD3, PNVL3
- **Indústria, transporte e agro:** WEGE3, RENT3, EMBR3, RAIL3, MOTV3, SLCE3, AGRO3
- **Telecom e tecnologia:** VIVT3, TIMS3, TOTS3, LWSA3, INTB3, POSI3

Os códigos podem estar defasados (fusões, mudanças de ticker). Papel sem dado no Yahoo aparece como "sem dados" no Motivo.

## Limitações conhecidas
- Crescimento vem de campos de variação recente do Yahoo, não de CAGR de vários anos: é ruidoso.
- "Futuro promissor" é medido só por números de crescimento e rentabilidade, não por vantagem competitiva.
- Nota alta não significa preço bom. O preço está na aba `Análise`.

## Fica para quem constrói
Faixas exatas de cada componente, layout visual (reaproveitar a formatação da aba `Análise`) e nomes internos.
