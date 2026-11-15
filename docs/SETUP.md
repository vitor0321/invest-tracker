# Configuração (uma vez só)

## 1. Repositório no GitHub
1. Crie um repositório **privado** no GitHub e envie este projeto.
2. Em *Actions*, rode o fluxo **prova-dados** (*Run workflow*). A saída mostra cotação, dividendos, LPA e VPA de 15 papéis. Compare com o Status Invest ou o Investidor10. Se os números não baterem, avise antes de seguir.

## 2. Conta de serviço do Google
1. Em console.cloud.google.com, crie um projeto (ex.: `investimentos`).
2. *APIs e serviços > Biblioteca*: ative **Google Sheets API**.
3. *IAM > Contas de serviço*: crie uma conta (ex.: `acompanhamento`). Em *Chaves*, crie uma chave **JSON** e baixe.
4. Abra a planilha **Controle Ações 2024**, clique em *Compartilhar* e dê acesso de **Editor** ao e-mail da conta de serviço (campo `client_email` do JSON).
5. No GitHub: *Settings > Secrets and variables > Actions > New repository secret* com nome `GOOGLE_SA_JSON` e o conteúdo inteiro do JSON.

## 3. E-mail
1. Na conta vitorwalcker.dev@gmail.com, ative a verificação em duas etapas e crie uma **senha de app** (myaccount.google.com/apppasswords).
2. No GitHub, crie o segredo `SMTP_APP_PASSWORD` com essa senha.

## 4. Primeira rodada
1. *Actions > daily > Run workflow* com **dry_run** marcado. Ele cria as abas `Análise`, `Observação`, `Parâmetros` e `Histórico de sinais` e preenche `Análise`, sem enviar e-mail.
2. Confira o preço teto de três papéis que você conhece. Ajuste a aba `Parâmetros` se quiser.
3. Rode sem dry_run. Dali em diante roda sozinho, 18h de Brasília, em dias úteis.

Para um papel novo na carteira, adicione uma linha com o tipo (`acao_br`, `fii`, `eua`, `etf`) em `Parâmetros`, colunas D e E. Sem isso ele aparece como "sem_tipo".
