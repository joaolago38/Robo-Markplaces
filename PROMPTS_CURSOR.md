Crie um workflow novo de CI no GitHub Actions que rode o lint + a suíte de testes automaticamente em TODO push e pull request — hoje isso só acontece via cron agendado ou disparo manual.

CONTEXTO:
O workflow `.github/workflows/agente_principal.yml` (nome "Robo-Markplaces" na aba Actions) só é disparado por:
```yaml
on:
  schedule:
    - cron: "0 11 * * *"
    - cron: "*/30 11-23 * * *"
    ...
  workflow_dispatch:
    inputs:
      rotina: ...
```
Não existe `on: push` nem `on: pull_request`. Isso significa que dar `git push` NUNCA dispara o job `qualidade` (que roda `ruff check` + `pytest -q`) automaticamente — só roda nos horários agendados ou quando alguém clica manualmente em "Run workflow". Isso causa confusão: depois de corrigir um bug e dar push, é fácil achar que o CI já validou o commit, quando na verdade o resultado mostrado ainda é de um run anterior.

IMPORTANTE: `agente_principal.yml` também dispara, nos MESMOS triggers de schedule/workflow_dispatch, jobs que executam AÇÕES REAIS de produção (relatório, chat com clientes, notificação de vendas no WhatsApp, keepalive/algoritmo dos marketplaces) — usando Secrets reais de Bling/ML/Shopee/Magalu/Amazon/Telegram/WhatsApp. NÃO adicione `on: push`/`on: pull_request` a esse arquivo, ou cada commit/PR passaria a também disparar essas rotinas de produção, o que seria um problema grave (ex.: mandar mensagens reais de WhatsApp a cada commit).

TAREFA:

1. Crie um arquivo novo `.github/workflows/ci.yml`, com um workflow dedicado SÓ para qualidade de código, separado de `agente_principal.yml`:
   ```yaml
   name: CI

   on:
     push:
       branches: ["main"]
     pull_request:
       branches: ["main"]

   env:
     PYTHON_VERSION: "3.11"

   jobs:
     qualidade:
       name: Qualidade (lint + testes)
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: ${{ env.PYTHON_VERSION }}
             cache: pip
         - name: Instalar dependências
           run: |
             pip install -r requirements.txt
             pip install -r requirements-dev.txt
         - name: Lint
           run: ruff check api agentes core integracoes tests
         - name: Testes
           run: python -m pytest -q
   ```
   Use exatamente os mesmos comandos de lint e teste já usados no job `qualidade` de `agente_principal.yml`, para manter consistência (mesma versão do Python, mesmo comando de lint, mesmo comando de pytest).

2. NÃO copie nenhum dos outros jobs (`relatorio`, `chat_marketplaces`, `vendas_whatsapp`, `algoritmo_marketplaces`) para esse novo arquivo — eles continuam existindo SÓ em `agente_principal.yml`, disparados só por schedule/workflow_dispatch, exatamente como estão hoje. Esse novo `ci.yml` deve ter APENAS o job de qualidade.

3. NÃO modifique `.github/workflows/agente_principal.yml` — esse arquivo continua exatamente como está, mantendo `schedule` e `workflow_dispatch` como únicos triggers, e seguindo rodando as rotinas de produção do jeito que já roda hoje. A única mudança é a CRIAÇÃO do novo arquivo `ci.yml`.

4. Esse novo workflow não precisa de nenhum Secret (Bling, ML, Telegram, etc.) — só precisa instalar dependências e rodar lint/testes, então não copie nenhuma seção `env:` de Secrets para ele.

5. Atualize o `README.md`, na seção sobre CI/workflows, mencionando que agora existe um workflow dedicado (`ci.yml`) que valida lint + testes automaticamente em todo push/PR pra `main`, separado do orquestrador de produção (`agente_principal.yml`).

6. Para validar: confirme (lendo o YAML criado) que a sintaxe está correta e que os nomes dos triggers (`push`, `pull_request`) e branches (`main`) batem com o branch principal real do repositório (confirme isso olhando outros workflows do projeto para ver se todos usam `main` como branch padrão, ou outro nome).