# Acompanhamento de Investimentos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Script em Python que, todo dia útil, busca dados gratuitos, calcula preço de referência (Bazin, Graham, Gordon), qualidade e nota de ações BR, FIIs e ativos dos EUA, grava em abas novas da planilha "Controle Ações 2024" e envia e-mail quando um ativo muda de sinal.

**Architecture:** Camada de dados atrás de uma interface (`DataProvider`), funções puras de cálculo, camada de planilha (só lê Notas/Carteira, só escreve em abas novas) e um orquestrador agendado no GitHub Actions. Nenhuma regra de cálculo conhece a fonte de dados.

**Tech Stack:** Python 3.12, pytest, `yfinance`, `requests`, `pandas`, `gspread` + `google-auth` (conta de serviço), `smtplib` (Gmail), GitHub Actions.

**Spec:** https://claude.ai/artifact/HNwU3S1U18hRdzXqXdkFwt (doc "Sistema de acompanhamento de investimentos: design")

## Global Constraints

- Só fontes gratuitas. Nada de brapi Pro nem outro custo fixo.
- O sistema lê as abas `Notas` e `Carteira` e escreve só em abas novas: `Análise`, `Observação`, `Parâmetros`, `Histórico de sinais`. Nunca edita `Notas`, `Carteira` ou `CF detalhe`.
- Planilha id `1ukZLWORhufJVCoo7SsqMFyPVQNY5ykr0IcfmdfIwHkw`, em português do Brasil. O script grava números como números (`RAW`), sem texto formatado.
- Chaves e senhas só em segredos do GitHub (`GOOGLE_SA_JSON`, `SMTP_APP_PASSWORD`). Nada disso na planilha ou no repositório.
- Alertas para `vitorwalcker.dev@gmail.com`, só quando o sinal de um ativo muda.
- Todo valor guarda `fonte` e `coletado_em`. Ativo sem dado suficiente fica sem nota, nunca com nota errada.
- Limites iniciais (editáveis em `Parâmetros`): DY alvo 6% (Brasil), 22,5 no Graham, retorno exigido 10% no Gordon, payout máximo 100%, dívida líquida/EBITDA máxima 3.
- Preço de referência = menor entre os métodos aplicáveis. ETFs: só preço e DY.
- Lista de observação inicial (20): TAEE11, CPLE6, SAPR11, CMIG4, PETR4, ABEV3, WEGE3, TIMS3, ITUB4, CXSE3, MXRF11, XPML11, KNRI11, HGLG11, VISC11, JNJ, KO, PG, SCHD, O.

## Review Focus

- Papel sem histórico de dividendos (ex.: AXIA3 acabou de mudar de código): sem Bazin, sem nota, sem alerta de oportunidade.
- LPA ou VPA negativo: Graham devolve "não se aplica", nunca raiz de número negativo.
- Crescimento do dividendo maior ou igual ao retorno exigido: Gordon não explode nem devolve preço negativo.
- Fonte devolve vazio, erro ou dado com mais de 10 dias: alerta `dado velho`, sem derrubar a rodada dos outros ativos.
- Rodar duas vezes no mesmo dia: não repete e-mail nem duplica linhas no `Histórico de sinais`.
- Ticker na `Carteira` sem tipo conhecido (ação BR, FII, EUA, ETF): vai para uma lista de "sem tipo" na aba `Análise`, nunca é chutado.

---

### Task 1: Esqueleto do projeto

**Files:**
- Create: `pyproject.toml`, `src/invest/__init__.py`, `tests/test_smoke.py`, `.gitignore`

**Interfaces:**
- Produces: pacote `invest` importável; `pytest` roda da raiz.

- [ ] **Step 1: Teste** `test_smoke.py::test_package_imports` faz `import invest` e `assert invest.__version__ == "0.1.0"`.
- [ ] **Step 2:** `pytest -q` → FAIL (módulo inexistente).
- [ ] **Step 3:** Criar `pyproject.toml` (Python >=3.12; dependências `yfinance`, `requests`, `pandas`, `gspread`, `google-auth`; dev `pytest`) e `src/invest/__init__.py` com `__version__ = "0.1.0"`. `.gitignore` com `.venv`, `__pycache__`, `*.json`.
- [ ] **Step 4:** `pip install -e .[dev] && pytest -q` → PASS.
- [ ] **Step 5:** Commit `chore: project skeleton`.

---

### Task 2: Cálculos puros (Bazin, Graham, Gordon, qualidade, FII)

**Files:**
- Create: `src/invest/valuation.py`, `tests/test_valuation.py`

**Interfaces:**
- Produces (todas devolvem `float | None`, `None` = não se aplica):
  - `bazin_ceiling(annual_dividends: list[float], target_dy: float = 0.06) -> float | None` (média dos anos informados ÷ `target_dy`; lista vazia → `None`)
  - `graham_fair_price(eps: float, bvps: float, factor: float = 22.5) -> float | None` (`None` se `eps <= 0` ou `bvps <= 0`)
  - `gordon_price(next_dividend: float, required_return: float, growth: float, growth_cap: float = 0.06) -> float | None` (`growth` limitado a `growth_cap`; `None` se `growth >= required_return` depois do teto)
  - `reference_price(prices: list[float | None]) -> float | None` (menor valor não nulo)
- Produces: `QualityResult(passed: bool, failures: list[str])` e `check_quality(payout: float | None, net_debt_ebitda: float | None, years_without_cut: int, max_payout: float = 1.0, max_leverage: float = 3.0, min_years: int = 5) -> QualityResult` (dado `None` conta como falha com o nome do critério).
- Produces: `FiiMetrics(pvp: float | None, dy_12m: float | None, months_paid_12m: int)` e `fii_quality(m: FiiMetrics, max_pvp: float = 1.10, min_dy: float = 0.08, min_months: int = 11) -> QualityResult`.

- [ ] **Step 1: Testes** com os valores exatos:
  - `bazin_ceiling([2.0, 3.0, 4.0]) == 50.0`; `bazin_ceiling([]) is None`
  - `graham_fair_price(2.0, 10.0) == pytest.approx(21.2132, abs=1e-4)`; `graham_fair_price(-1.0, 10.0) is None`
  - `gordon_price(1.0, 0.10, 0.04) == pytest.approx(16.6667, abs=1e-4)`; `gordon_price(1.0, 0.10, 0.12) == pytest.approx(25.0)` (crescimento limitado a 6% → 1,0 ÷ 0,04); `gordon_price(1.0, 0.05, 0.08) is None`
  - `reference_price([50.0, None, 21.2]) == 21.2`; `reference_price([None]) is None`
  - `check_quality(0.5, 2.0, 6).passed is True`; `check_quality(1.2, 2.0, 6).failures == ["payout"]`; `check_quality(None, 2.0, 6).failures == ["payout"]`
  - `fii_quality(FiiMetrics(0.95, 0.09, 12)).passed is True`; com `pvp=1.3` → `failures == ["pvp"]`
- [ ] **Step 2:** `pytest tests/test_valuation.py -v` → FAIL.
- [ ] **Step 3:** Implementar as assinaturas acima em `valuation.py`.
- [ ] **Step 4:** Rodar de novo → PASS.
- [ ] **Step 5:** Commit `feat: valuation formulas`.

---

### Task 3: Nota (0 a 100) e sinais

**Files:**
- Create: `src/invest/scoring.py`, `tests/test_scoring.py`

**Interfaces:**
- Consumes: `QualityResult` de `valuation.py`.
- Produces: `Signal = Literal["oportunidade", "caro", "risco", "dado_velho", "neutro", "sem_dados"]`
- Produces: `compute_score(price: float, reference: float | None, quality_passed: bool, dividend_regularity: float, weights: dict[str, float]) -> int | None` (`None` se `reference` é `None`). Componentes de 0 a 1: folga `clamp((reference - price) / reference, 0, 1)`, qualidade `1.0 | 0.0`, regularidade (fração de anos com dividendo). Pesos iniciais `{"folga": 0.5, "qualidade": 0.3, "regularidade": 0.2}`. Resultado `round(100 * soma)`.
- Produces: `classify(price: float, reference: float | None, quality: QualityResult, dividend_cut: bool, payout: float | None, data_age_days: int, held: bool, max_age_days: int = 10, max_payout: float = 1.0) -> Signal`. Ordem de decisão: `dado_velho` (idade > máx) → `sem_dados` (reference `None`) → `risco` (corte de dividendo ou payout > máx) → `oportunidade` (price ≤ reference e qualidade aprovada) → `caro` (só se `held` e price > reference) → `neutro`.

- [ ] **Step 1: Testes:** `compute_score(40, 50, True, 1.0, W) == 60` (folga 0,2 × 0,5 = 0,10, mais 0,30 de qualidade, mais 0,20 de regularidade); `compute_score(60, 50, True, 1.0, W) == 50` (folga 0, preço acima da referência); `compute_score(40, None, True, 1.0, W) is None`. `classify` com um caso por sinal e um caso de precedência (dado velho vence oportunidade; risco vence oportunidade).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementar conforme assinaturas.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: scoring and signals`.

---

### Task 4: Camada de dados e prova dos dados (Fase 1)

**Files:**
- Create: `src/invest/data/base.py`, `src/invest/data/yahoo.py`, `src/invest/data/cvm.py`, `tests/test_data_yahoo.py`, `scripts/prova_dados.py`

**Interfaces:**
- Produces em `base.py`:
  - `@dataclass Fundamentals(ticker: str, price: float | None, annual_dividends: list[float], eps: float | None, bvps: float | None, payout: float | None, net_debt_ebitda: float | None, years_without_cut: int, source: str, collected_at: datetime)`
  - `class DataProvider(Protocol): def fetch(self, ticker: str, market: Literal["br", "us"]) -> Fundamentals`
  - `normalize_ticker(ticker: str, market: str) -> str` (`"br"` → sufixo `.SA`; `"us"` → igual)
- Produces `YahooProvider(DataProvider)` (usa `yfinance`; dividendos agrupados por ano, últimos 5 anos completos) e `CvmProvider.net_debt_ebitda(cnpj: str) -> float | None` (dados abertos DFP/ITR da CVM).
- `scripts/prova_dados.py`: imprime, para 5 papéis de cada tipo, cotação, média de dividendos de 5 anos, LPA e VPA com a fonte, para o Vitor comparar com Status Invest ou Investidor10.

- [ ] **Step 1: Testes** (`test_data_yahoo.py`, sem rede, com `yfinance.Ticker` simulado): `normalize_ticker("ITUB4", "br") == "ITUB4.SA"`; `normalize_ticker("JNJ", "us") == "JNJ"`; dividendos de 2022=1,0, 2023=2,0 e 2024=3,0 viram `annual_dividends == [1.0, 2.0, 3.0]`; provedor com erro devolve `Fundamentals` com campos `None` e não levanta exceção.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementar `base.py`, `yahoo.py` e `cvm.py`; falha de rede vira campos `None` mais mensagem em log, nunca exceção para o chamador.
- [ ] **Step 4:** PASS. Rodar `python scripts/prova_dados.py` e **mostrar a saída ao Vitor**.
- [ ] **Step 5: Ponto de decisão:** o Vitor compara os números. Se não baterem, reduzir o escopo (design: sem vacância de FIIs, só dados anuais). Não pagar fonte.
- [ ] **Step 6:** Commit `feat: data providers and data proof`.

---

### Task 5: Planilha (leitura e abas novas)

**Files:**
- Create: `src/invest/sheets.py`, `tests/test_sheets.py`

**Interfaces:**
- Consumes: `Fundamentals`, `Signal`.
- Produces:
  - `read_holdings(sh) -> dict[str, float]` (ticker → quantidade, da aba `Carteira`, só quantidade > 0)
  - `read_watchlist(sh) -> list[WatchItem]` e `read_params(sh) -> Params` (DY alvo, retorno exigido, limites, pesos, e-mail, mapa `ticker → tipo` com tipos `acao_br | fii | eua | etf`)
  - `ensure_tabs(sh) -> None` (cria `Análise`, `Observação`, `Parâmetros`, `Histórico de sinais` com cabeçalho e valores iniciais da seção Global Constraints, só se faltarem)
  - `write_analysis(sh, rows: list[AnalysisRow]) -> None` (sobrescreve só `Análise`: tipo, papel, preço, preço por método, folga %, nota, sinal, fonte, data)
  - `last_signals(sh) -> dict[str, Signal]` e `append_signal_changes(sh, changes: list[SignalChange]) -> None` (`Histórico de sinais`)
  - Função `open_sheet(sa_json: str) -> Spreadsheet` com `gspread.service_account_from_dict`.
- Regra: nenhuma função escreve em `Notas`, `Carteira` ou `CF detalhe`.

- [ ] **Step 1: Testes** com planilha simulada (objeto em memória com a interface mínima do `gspread`): `read_holdings` ignora quantidade 0 (KLBN4); `ensure_tabs` é idempotente (duas chamadas, mesmo resultado); teste de segurança: qualquer chamada de escrita em aba fora das quatro novas levanta `ForbiddenTabError`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementar; números gravados com `value_input_option="RAW"`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: sheets layer`.

---

### Task 6: Orquestrador, histórico de sinais e e-mail

**Files:**
- Create: `src/invest/run.py`, `src/invest/alerts.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: tudo das tasks 2 a 5.
- Produces:
  - `detect_changes(previous: dict[str, Signal], current: dict[str, Signal]) -> list[SignalChange]` (só mudanças; primeiro registro de um papel como `neutro`/`sem_dados` não gera e-mail)
  - `render_email(changes: list[SignalChange]) -> tuple[str, str]` (assunto e corpo com papel, sinal, preço, preço de referência e fonte)
  - `send_email(subject: str, body: str, to: str, user: str, password: str) -> None` (Gmail SMTP SSL, porta 465)
  - `main() -> int`: abre a planilha, `ensure_tabs`, junta carteira (com `held=True`) e observação, busca dados (um papel com erro não derruba os outros), calcula, grava `Análise`, registra mudanças e envia um e-mail só se houver mudança.

- [ ] **Step 1: Testes:** `detect_changes({"TAEE11": "neutro"}, {"TAEE11": "oportunidade"})` devolve uma mudança; igual → lista vazia; segunda rodada com os mesmos sinais → nenhum e-mail e `append_signal_changes` não é chamada; provedor que falha em um papel → esse papel sai como `sem_dados` e os outros seguem.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Rodada real local com `GOOGLE_SA_JSON` e sem enviar e-mail (`--dry-run`); o Vitor confere a aba `Análise` e o preço teto de três papéis que conhece.
- [ ] **Step 6:** Commit `feat: orchestrator and alerts`.

---

### Task 7: Agendamento no GitHub Actions e passo a passo das contas

**Files:**
- Create: `.github/workflows/daily.yml`, `docs/SETUP.md`

**Interfaces:**
- Consumes: `python -m invest.run`.

- [ ] **Step 1:** `docs/SETUP.md` com o passo a passo para o Vitor: criar projeto no Google Cloud, ativar a API do Google Sheets, criar a conta de serviço, baixar a chave JSON, compartilhar a planilha com o e-mail da conta de serviço como editor, criar a senha de app do Gmail e gravar os segredos `GOOGLE_SA_JSON` e `SMTP_APP_PASSWORD` no repositório.
- [ ] **Step 2:** `daily.yml`: gatilho `schedule` (cron `0 21 * * 1-5`, ou seja 18h de Brasília em dias úteis) e `workflow_dispatch`; passos de checkout, Python 3.12, `pip install -e .`, `pytest -q` e `python -m invest.run`; segredos por `env`.
- [ ] **Step 3:** Disparar manualmente (`workflow_dispatch`) e conferir que a aba `Análise` atualiza e nenhum e-mail repetido sai.
- [ ] **Step 4:** Semana de teste: rodar 5 dias úteis; checagem = sem falha e sem alerta repetido.
- [ ] **Step 5:** Commit `ci: daily schedule and setup guide`.
