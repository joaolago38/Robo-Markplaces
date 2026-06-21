# Prompt — Sanar pontos cegos do Robo-Markplaces (reduzir erros silenciosos)

Aplique as correções abaixo no projeto Robo-Markplaces, em ordem de prioridade.
Para CADA correção, adicione/atualize os testes correspondentes em `tests/` e, ao
final, rode `python -m pytest -q` garantindo que TUDO continua verde (hoje são
377 testes passando — não pode regredir). Não altere credenciais reais.

====================================================================
## 🔴 CRÍTICO 1 — `estoque` None quebra o publicador (TypeError)
====================================================================
Depois que a normalização do Bling passou a retornar `estoque = None` quando o
saldo não vem na listagem, qualquer comparação direta com None estoura.

- Em `agentes/social/publicador.py` (linha ~16), troque:
  ```python
  elegiveis = [p for p in produtos if p["estoque"] >= ESTOQUE_CRITICO]
  ```
  por (tratando None como 0, e sem usar acesso direto por chave):
  ```python
  elegiveis = [p for p in produtos if (p.get("estoque") or 0) >= ESTOQUE_CRITICO]
  ```
- Faça uma varredura no projeto por QUALQUER comparação/uso de estoque que assuma
  inteiro (`p["estoque"]`, `>= ESTOQUE_CRITICO`, `<= limite`, somas) e proteja
  todas com `(... or 0)`. Confira pelo menos:
  `agentes/magalu/agente_magalu.py`, `agentes/ml/agente_ml.py`,
  `agentes/auto_respostas_visuais.py`, `agentes/repricing/*`,
  `agentes/operacao_24h.py`, `core/claude_client.py`.
- Teste novo: produto com `estoque=None` não deve quebrar `selecionar_produto()`
  nem o repricing; deve ser tratado como 0.

====================================================================
## 🔴 CRÍTICO 2 — NF-e emite de verdade por padrão (efeito fiscal acidental)
====================================================================
`emitir_nfe_pedido(pedido, dry_run=False)` tem default inseguro: chamar sem o
parâmetro EMITE nota real. E `agentes/operacao_24h.py` roda com `dry_run_nfe=False`
inclusive no bloco `__main__`.

- Em `agentes/faturamento/agente_faturamento.py`, mude o default para seguro:
  ```python
  def emitir_nfe_pedido(pedido: dict, dry_run: bool = True) -> dict:
  ```
- Em `agentes/operacao_24h.py`:
  - `_faturar_pedidos_lojahub(dry_run_nfe: bool = True, ...)` (default seguro).
  - `executar(dry_run_repricing: bool = True, dry_run_nfe: bool = True)`.
  - No bloco `if __name__ == "__main__":`, use `dry_run_nfe=True`.
  - A emissão real só deve acontecer quando o chamador passar `dry_run_nfe=False`
    EXPLICITAMENTE (ou via variável de ambiente dedicada, ex.
    `NFE_EMITIR_REAL=true`). Documente isso num comentário.
- Ajuste os testes existentes de faturamento/operacao_24h para refletir o novo
  default e adicione um teste garantindo que, sem `dry_run=False` explícito,
  `criar_nfe` (a chamada que emite de verdade) NÃO é invocada.

====================================================================
## 🟠 ALTO 3 — Erros HTTP mascarados como "lista vazia"
====================================================================
O padrão "nunca lança exceção → retorna []/{}/0.0" faz um 401/403/erro de rede
ficar idêntico a um resultado realmente vazio. Foi o que causou confusão no
Bling (403 aparecia como "lista vazia").

Use o `bling_client.py` como referência (ele já loga status HTTP != 200 e tem
`probe_produtos`). Aplique o mesmo princípio nos demais clients de leitura
(`integracoes/ml/ml_client.py`, `integracoes/magalu/magalu_client.py`,
`integracoes/shopee/shopee_client.py`, `integracoes/amazon/amazon_client.py`):

- Em funções de listagem/consulta, ANTES de retornar `[]`/`{}`:
  - se `status_code` existir e for != 200, logar em nível ERROR com o status e os
    primeiros ~200 chars do corpo (sem vazar token).
  - manter o retorno vazio para não quebrar o fluxo, mas o log deve deixar claro
    que foi ERRO, não vazio.
- Onde fizer sentido, exponha uma função `probe_*()` de diagnóstico (como a
  `probe_produtos` do Bling) que retorna `{ok, status, msg}` sem mascarar.
- Não trate 403 como se renovar token resolvesse: ao receber 403, logar que é
  provável falta de ESCOPO/permissão (não apenas token expirado).
- Testes: para cada client, um teste com resposta mock 401, 403 e erro de rede,
  verificando que loga ERROR e retorna vazio (use `assertLogs`).

====================================================================
## 🟠 ALTO 4 — Camada de alertas falha em silêncio
====================================================================
`core/notificador.py` e `core/whatsapp.py` têm cobertura baixa, e
`notificador._enviar` retorna `True` quando o canal NÃO está configurado
(imprime e finge sucesso). Em produção isso = alerta "enviado" que ninguém recebe.

- Em `core/notificador.py`: quando o canal não estiver configurado, ainda pode
  imprimir no stdout, mas registre um `logger.warning` deixando claro que o
  alerta NÃO foi entregue por falta de configuração. Considere retornar um valor
  que diferencie "entregue" de "apenas impresso" (ex.: retornar `False` ou um
  dict `{entregue: False, motivo: "telegram_nao_configurado"}`), ajustando os
  chamadores conforme necessário.
- Suba a cobertura de `core/notificador.py` e `core/whatsapp.py` para ≥ 80%,
  cobrindo: canal não configurado, envio com sucesso (request mockado) e falha de
  envio (exceção do request).

====================================================================
## 🟠 ALTO 5 — `core/token_manager.py` pouco testado (60%)
====================================================================
É o componente que mais quebrou (refresh do Bling com 400/401) e o menos coberto.

- Adicione testes para os caminhos de renovação de token de cada provedor
  (Bling, ML, Meta, Magalu) cobrindo:
  - refresh com sucesso (request mock 200 → novos tokens),
  - refresh com 400/401 (credenciais inválidas) → mensagem de dica clara,
  - ausência de client_id/secret/refresh_token → não tenta e loga motivo,
  - rotação de refresh_token (quando o provedor devolve um novo refresh).
- Meta de cobertura para `core/token_manager.py`: ≥ 85%.

====================================================================
## 🟡 MÉDIO 6 — Magalu quase sem teste (16%)
====================================================================
- Adicione testes para `integracoes/magalu/magalu_client.py` cobrindo
  `_enabled`, `obter_saude_conta`, `listar_perguntas_nao_respondidas`,
  `listar_pedidos`, `atualizar_preco_item`, `atualizar_estoque_item`
  (todos com request mockado, incluindo caminhos de erro/HTTP != 200).
  Meta: ≥ 80%.

====================================================================
## 🟡 MÉDIO 7 — Trava de cobertura no CI
====================================================================
- Adicione `pytest-cov` ao `requirements-dev.txt`.
- Crie um `pyproject.toml` (ou `pytest.ini`) configurando uma trava mínima de
  cobertura GLOBAL de 80% (`--cov=. --cov-fail-under=80`), e garanta que o
  workflow de testes do GitHub Actions rode com cobertura e falhe se cair abaixo.
- Não reduza a meta para "passar": se algum módulo crítico estiver abaixo, escreva
  os testes.

====================================================================
## 🟡 MÉDIO 8 — Token do Telegram na URL
====================================================================
- Avalie mover o token do Telegram para fora da URL quando possível, ou garantir
  que a URL com token NUNCA seja logada (verifique logs de retry/erro do
  `http_client` e do `notificador`). Se mantiver na URL (padrão da API), assegure
  que nenhum `logger`/`print` imprima a URL completa.

====================================================================
## Critérios de aceite (confirme ao final)
====================================================================
1. `python -m pytest -q` — todos verdes (≥ 377, sem regressão).
2. `python -m pytest --cov=. --cov-report=term-missing` mostrando:
   - `core/token_manager.py` ≥ 85%
   - `core/notificador.py` e `core/whatsapp.py` ≥ 80%
   - `integracoes/magalu/magalu_client.py` ≥ 80%
   - cobertura GLOBAL ≥ 80% com `--cov-fail-under=80` ativo.
3. Nenhuma ação de escrita (NF-e real, mudança de preço/estoque) ocorre por
   padrão sem flag explícita.
4. Erros HTTP (401/403/rede) agora aparecem como ERROR nos logs, não como
   "vazio" silencioso.
5. Nenhum teste faz chamada de rede real (tudo mockado).

> Lembrete: roda no GitHub Actions a partir do que está commitado. Aplique,
> rode os testes, e faça commit + push na branch `main`.