# Melhores por setor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Aba `Melhores por setor` com os 5 papéis de maior nota de qualidade por setor e um bloco com o peso de cada setor na carteira.

**Architecture:** Novo módulo puro `quality.py` (nota, ranking, carteira por setor). `YahooProvider` ganha 4 campos. `sheets.py` ganha as abas `Universo` (entrada) e `Melhores por setor` (saída). `run.main` reaproveita as coletas com um provedor com cache.

**Tech Stack:** Python 3.12, pytest, yfinance, gspread.

**Spec:** `docs/superpowers/specs/2026-11-15-melhores-por-setor-design.md`

## Global Constraints
- Só dados gratuitos (Yahoo). Abas Notas, Carteira e CF detalhe nunca são escritas.
- Falha de coleta ou de formatação nunca derruba a rodada.
- Pesos: ROE 0,25; margem 0,15; crescimento 0,25; solidez 0,15; dividendos 0,20.
- Menos de 3 componentes disponíveis = fora do ranking.

## Review Focus
1. Papel do Universo sem dado no Yahoo: fora do ranking, listado com motivo (teste em Task 1).
2. Financeira sem EBITDA: solidez isenta, sem punição (Task 1).
3. Crescimento absurdo do Yahoo (ex.: +500%): limitado a 100 pontos (Task 1).
4. Carteira com ações em US$: não entram no percentual em R$ (Task 1).
5. Planilha antiga sem os pesos novos em `Parâmetros`: usa os padrões (Task 3).

---

### Task 1: `src/invest/quality.py` (teste: `tests/test_quality.py`)
**Produces:**
- `QUALITY_WEIGHTS: dict[str, float]` (chaves `roe`, `margem`, `crescimento`, `solidez`, `dividendos`)
- `quality_score(f: Fundamentals, weights=QUALITY_WEIGHTS) -> QualityScore(score: int | None, notes: str)`
- `BestRow(sector, position, ticker, held, score, roe, margin, earnings_growth, revenue_growth, net_debt_ebitda, dy_12m, years_without_cut, notes)`
- `rank_by_sector(universe: list[tuple[str, str]], data: dict[str, Fundamentals], held: set[str], weights=QUALITY_WEIGHTS, top=5) -> list[BestRow]`
- `portfolio_by_sector(holdings: dict[str, float], rows: list[AnalysisRow], sector_of: dict[str, str]) -> list[tuple[str, float, float | None]]`

Faixas (linear, limitado a 0-100): ROE 0→0, 20%→100; margem 0→0, 20%→100; crescimento = média dos disponíveis, −10%→0, +20%→100; solidez dív/EBITDA ≤1→100, ≥4→0 (financeira: componente isento); dividendos = 70 × min(anos sem corte, 5)/5 + 30 × fração dos últimos 5 anos com pagamento.

- [ ] Testes: empresa forte = 100; fraca = 0; ROE 10% sozinho vale 50; dado faltando repondera e aparece em `notes`; menos de 3 componentes → `None`; sem preço → `None`; financeira isenta; crescimento +500% limitado; ranking top 5 por setor na ordem do universo, sem nota no fim com posição vazia; carteira por setor com "FIIs", "Sem setor" e "Exterior (US$)" sem percentual.
- [ ] Ver falhar, implementar, ver passar, commit.

### Task 2: campos novos no Yahoo (`data/base.py`, `data/yahoo.py`, `tests/test_data_yahoo.py`)
**Produces:** `Fundamentals.roe`, `.profit_margin`, `.earnings_growth`, `.revenue_growth` (de `returnOnEquity`, `profitMargins`, `earningsGrowth`, `revenueGrowth`).
- [ ] Teste `test_provider_exposes_quality_fields`, ver falhar, implementar, ver passar, commit.

### Task 3: abas (`sheets.py`, `tests/test_sheets.py`)
**Produces:** `UNIVERSE = "Universo"`, `BEST = "Melhores por setor"` em `OWN_TABS`; `SEED_UNIVERSE`; `read_universe(sh) -> list[tuple[str, str]]`; `write_best(sh, best: list[BestRow], portfolio)`; `format_best(sh)`; `Params.quality_weights` lido de `q_peso_*` com padrão.
- [ ] Testes: `ensure_tabs` semeia o Universo (8 setores, até 7 por setor); `read_universe` ignora linhas vazias; `write_best` grava cabeçalho, linhas e o bloco da carteira à direita; pesos padrão em planilha antiga e pesos lidos quando presentes; `format_best` é idempotente.
- [ ] Ver falhar, implementar, ver passar, commit.

### Task 4: rodada (`run.py`, `tests/test_run.py`)
**Produces:** `CachingProvider(inner)`; `build_best(universe, holdings, rows, params, provider) -> tuple[list[BestRow], portfolio]`; `main` grava a aba dentro de `try` (nunca derruba a rodada).
- [ ] Testes: cache busca cada papel uma vez; `build_best` sobrevive a provedor que lança erro.
- [ ] Ver falhar, implementar, ver passar, suíte inteira, commit e push.
