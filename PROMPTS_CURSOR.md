Crie o arquivo `tests/test_magalu_client.py` do zero (ele não existe mais no projeto — foi perdido numa correção anterior), cobrindo todas as funções de `integracoes/magalu/magalu_client.py`.

CONTEXTO DO BUG:
O arquivo `tests/test_magalu_client.py` foi deletado em algum momento (em vez de corrigido, numa rodada anterior que pedia só o ajuste de uma data fixa num teste). Hoje ele não existe de verdade no projeto. Isso faz a cobertura de `integracoes/magalu/magalu_client.py` cair pra ~23% (só é exercitado incidentalmente por outros testes que importam o módulo, como `tests/test_whatsapp_vendas.py` e `tests/test_agente_panorama.py`, sem testar as funções dele de verdade). Essa cobertura baixa está derrubando a cobertura total do projeto abaixo dos 80% exigidos (`--cov-fail-under=80` em `pyproject.toml`), fazendo o CI falhar mesmo sem nenhum bug funcional.

NÃO existe mais nenhuma versão antiga desse arquivo para recuperar — crie um arquivo novo, completo, do zero.

FUNÇÕES A COBRIR (todas as públicas de `integracoes/magalu/magalu_client.py`, no estado atual do arquivo):

1. `probe_conexao() -> dict` — testar: não configurado (`MAGALU_ACCESS_TOKEN`/`MAGALU_MERCHANT_ID` vazios) retorna `{"ok": False, "status": 0, ...}`; resposta HTTP 200 retorna `ok: True`; HTTP 401 retorna mensagem de token expirado; HTTP 403 retorna mensagem de permissão; outro status retorna `ok: False` com o status correspondente; exceção de rede é capturada e retorna `ok: False` sem lançar.

2. `listar_perguntas_nao_respondidas(limit=20) -> list[dict]` — testar: não configurado retorna `[]`; resposta 200 com `{"data": [...]}` retorna a lista; resposta com `{"items": [...]}` (formato alternativo) também funciona; status != 200 retorna `[]`; exceção retorna `[]`.

3. `responder_pergunta(question_id, texto) -> bool` — testar: não configurado retorna `False`; sucesso (sem exceção em `raise_for_status`) retorna `True`; exceção (ex.: `raise_for_status` lança) retorna `False`.

4. `manter_conta_ativa(limite_dias_sem_acesso=5) -> dict` — testar: já acessado hoje (mock de `dias_sem_acesso` retornando `< 1`) retorna `acao: "já acessado hoje"` sem chamar a API; não configurado retorna `ok: False, acao: "não configurado"`; sucesso chama `registrar_acesso` e retorna `ok: True, acao: "keepalive executado"`; exceção retorna `ok: False, acao: "falha no keepalive"`. Mocke `dias_sem_acesso` e `registrar_acesso` (de `core.marketplace_keepalive`) nesses testes.

5. `obter_saude_conta() -> dict` — testar: não configurado retorna `configurado: False, dias_sem_acesso: 999`; configurado retorna `configurado: True` com `pendencias` igual ao tamanho da lista retornada por `listar_perguntas_nao_respondidas` (mocke essa função).

6. `atualizar_preco_item(sku, novo_preco) -> bool` — testar: não configurado retorna `False`; sucesso retorna `True`; exceção retorna `False`.

7. `atualizar_estoque_item(sku, novo_estoque) -> bool` — IMPORTANTE, essa função tem o kill switch global (`core.guardrails.bloqueio_escrita_global`): testar (a) com o kill switch ATIVO (mocke `core.guardrails.bloqueio_escrita_global` para retornar um dict de erro) — a função deve retornar `False` SEM fazer nenhuma chamada HTTP (assert que `request`/mock de rede não foi chamado); (b) kill switch inativo + não configurado retorna `False`; (c) kill switch inativo + sucesso retorna `True`; (d) kill switch inativo + exceção na chamada retorna `False`.

8. `listar_pedidos(dias=7) -> list[dict]` — já existia um teste pra essa função antes (`test_listar_pedidos_ok`); recrie cobrindo: não configurado retorna `[]`; sucesso com 1 pedido dentro da janela de `dias` retorna a lista formatada (IMPORTANTE: use uma data relativa calculada com `datetime.now(timezone.utc) - timedelta(days=2)` no mock de `created_at`, NUNCA uma data absoluta fixa tipo `"2026-06-16T..."` — isso já causou um bug de teste "vencendo" no passado, não repita o erro); pedido fora da janela de `dias` (data antiga) é filtrado e não aparece no retorno; pedido sem `code`/`id`/`order_id` é ignorado; status HTTP != 200 retorna `[]`; exceção retorna `[]`.

PADRÃO A SEGUIR:
- Use exatamente o mesmo estilo de setup/stub de dependências (`yaml`, `dotenv`, `requests`, `requests.adapters`) já usado em `tests/test_shopee_client.py` ou `tests/test_ml_client.py` — copie esse bloco de cabeçalho se for o mesmo padrão necessário pra importar `magalu_client` isoladamente em ambiente de teste mínimo.
- Use `unittest.TestCase` com `@patch.object(mag, "request")` para mockar a função `request` de `core.http_client`, e `@patch.object(mag, "MAGALU_MERCHANT_ID", "m1")` / `@patch.object(mag, "MAGALU_ACCESS_TOKEN", "tok")` para simular configuração, seguindo o padrão que já existia no projeto pra esse arquivo (visível em testes de outros clientes do mesmo estilo, como `tests/test_ml_client.py`).
- Crie um helper `_resp(status_code, json_body)` que devolve um mock de resposta HTTP com `.status_code`, `.json()` e `.raise_for_status()` coerentes com o `status_code` (lance exceção em `raise_for_status()` quando `status_code >= 400`), reaproveitando o padrão já usado nos outros arquivos de teste de cliente.

VALIDAÇÃO FINAL:
1. Rode `python -m pytest tests/test_magalu_client.py -v --cov=integracoes/magalu/magalu_client.py --cov-report=term-missing` e itere até a cobertura desse arquivo ficar em pelo menos 90% (mire em ficar parecido com `integracoes/bling/bling_client.py`, que está em 96%).
2. Rode a suíte completa `python -m pytest -q` e confirme cobertura TOTAL do projeto ≥ 80%.
3. Rode `ruff check api agentes core integracoes tests` e confirme 0 erros de lint.
4. Não altere nenhum código de produção (`integracoes/magalu/magalu_client.py` ou qualquer outro) — essa tarefa é só criar o arquivo de teste.