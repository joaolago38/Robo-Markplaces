Implemente as 3 correções abaixo no Robo-Markplaces, relacionadas a riscos operacionais reais entre Bling e os marketplaces (Mercado Livre, Magalu, Shopee). Implemente NA ORDEM (1 → 2 → 3) e rode `python -m pytest -q` + `ruff check api agentes core integracoes tests` depois de cada item antes de seguir pro próximo.

═══════════════════════════════════════════════════
ITEM 1 (CRÍTICO) — Sincronizar estoque do Bling para os marketplaces (evitar overselling)
═══════════════════════════════════════════════════

PROBLEMA CONFIRMADO:
As funções `atualizar_estoque_item()` já existem em `integracoes/ml/ml_client.py`, `integracoes/magalu/magalu_client.py` e `integracoes/shopee/shopee_client.py`, mas NENHUMA delas é chamada em nenhum agente ou workflow hoje — são código morto. Não existe nenhuma sincronização automática de estoque entre canais. Risco real: vender o mesmo SKU esgotado em 2 canais ao mesmo tempo (overselling), gerando cancelamento forçado e penalidade de reputação.

O mapeamento SKU → canal (item_id por marketplace) já existe em `catalogo/produtos.json` — cada produto tem uma chave `"canais"` com `mercadolivre`/`shopee`/etc., cada um com `ativo` (bool) e `item_id` (quando aplicável). Esse arquivo é a fonte de verdade dos IDs de anúncio — não vem do Bling.

TAREFA:

1. Crie `agentes/sincronizar_estoque_marketplaces.py`, seguindo o estilo dos outros agentes (`agentes/repricing/agente_repricing_marketplaces.py` é a melhor referência de padrão: guardrails, dry_run, retorno estruturado em dict, logging, `try/except` que nunca propaga exceção).

2. A função principal `executar(produtos: list[dict] | None = None, dry_run: bool = True) -> dict` deve:
   a. Se `produtos` não for passado, carregar de `catalogo/produtos.json` (use `json.load` com o caminho relativo à raiz do projeto — veja como outros módulos resolvem paths relativos no projeto, ou use `pathlib.Path(__file__).resolve().parent.parent / "catalogo" / "produtos.json"`).
   b. Para cada produto da lista, buscar o estoque REAL atual no Bling via `bling_client.buscar_produto(sku)` (campo `estoque` do retorno). Se vier `None` (Bling às vezes não retorna saldo na listagem, conforme o comentário/TODO já existente em `_extrair_estoque` no `bling_client.py`), pule esse produto e registre um aviso no log — NÃO sincronize um valor desconhecido como se fosse zero.
   c. Para cada canal dentro de `produto["canais"]` onde `ativo == True` e existe um `item_id` válido (ou `sku` para Magalu, que usa SKU em vez de item_id — confirme isso lendo a assinatura de `magalu_client.atualizar_estoque_item(sku, novo_estoque)`):
      - Compare o estoque real do Bling com o `estoque` salvo no JSON daquele canal.
      - Se for diferente, monte um ajuste pendente (não aplique ainda se `dry_run=True`).
   d. Se `dry_run=False`, chame a função `atualizar_estoque_item` correta por canal (`ml_client`, `magalu_client`, `shopee_client` — crie um dispatcher tipo o `_updater()` que já existe em `agente_repricing_marketplaces.py`, mas para a função de estoque).
   e. Retorne um payload estruturado:
      ```python
      {
          "dry_run": dry_run,
          "total_produtos": ...,
          "total_ajustes": ...,
          "ajustes": [
              {"sku": ..., "canal": ..., "estoque_bling": ..., "estoque_anterior_canal": ..., "aplicado": ...},
              ...
          ],
          "produtos_sem_estoque_bling": [...],  # skus onde o Bling não retornou saldo
      }
      ```
   f. Se `total_ajustes > 0`, envie um resumo via `core.notificador.alertar_gestor()` (ex.: "Estoque sincronizado: N ajustes aplicados/detectados").
   g. Se algum produto ficar com estoque 0 em algum canal ativo, adicione um alerta `alertar_critico()` específico sugerindo revisão (pausar anúncio manualmente, ou — se quiser ousar mais — avalie chamar `pausar_anuncio()`/`encerrar_anuncio()` do canal correspondente quando o estoque chegar a 0 e `dry_run=False`; implemente isso APENAS se a função de pausa do canal já existir e estiver com guardrails — para ML já existe `pausar_anuncio(item_id, dry_run, confirmar)` em `ml_client.py`).

3. Quando `dry_run=False` e um ajuste for aplicado com sucesso, ATUALIZE também o campo `estoque` correspondente em `catalogo/produtos.json` (reescreva o arquivo), para manter esse arquivo como espelho do que foi sincronizado pela última vez. Use escrita atômica (escrever em arquivo temporário e renomear) para não corromper o JSON se o processo for interrompido no meio.

4. Adicione um endpoint novo em `api/app.py`, seguindo o padrão dos outros (`_get_json_payload()`, etc.):
   ```python
   @app.route("/marketplaces/estoque/sincronizar", methods=["POST"])
   def sincronizar_estoque_marketplaces():
       """
       POST /marketplaces/estoque/sincronizar
       Sincroniza estoque do Bling para os marketplaces ativos no catalogo/produtos.json.
       Body opcional: { "dry_run": true }
       """
       ...
   ```
   Adicione na lista de "Endpoints principais" impressa no final do arquivo e no `README.md`.

5. Crie um workflow novo `.github/workflows/sincronizar_estoque.yml`, rodando a cada 1-2 horas (ex.: `*/2 * * * *` em horas, ajuste pro fuso BRT como os outros workflows já fazem), chamando `python -m agentes.sincronizar_estoque_marketplaces` com `dry_run=False` direto via `if __name__ == "__main__"` (adicione esse bloco no agente, no padrão dos outros agentes do projeto).

6. Crie `tests/test_sincronizar_estoque_marketplaces.py` cobrindo: ajuste detectado e aplicado corretamente por canal, produto sem estoque conhecido no Bling é pulado (não trava), `dry_run=True` não chama nenhuma função de escrita, e alerta crítico disparado quando estoque chega a 0 num canal ativo.

═══════════════════════════════════════════════════
ITEM 2 (CRÍTICO) — Evitar emissão de NF-e duplicada para o mesmo pedido
═══════════════════════════════════════════════════

PROBLEMA CONFIRMADO:
Existem 2 caminhos independentes que chamam `emitir_nfe_pedido()` (em `agentes/faturamento/agente_faturamento.py`): um via `agente_panorama.py` (pedidos vindos direto da API do ML/Magalu) e outro via `agentes/operacao_24h.py` (pedidos vindos do Lojahub, que agrega os mesmos marketplaces). Não existe nenhuma verificação de "esse pedido já tem NF-e emitida" antes de chamar `criar_nfe()` — risco real de duplicar nota fiscal para o mesmo pedido.

TAREFA:

1. Em `integracoes/bling/bling_client.py`, crie uma função nova:
   ```python
   def buscar_nfe_por_pedido(numero_pedido_loja: str, dias: int = 30) -> dict | None:
       """
       Verifica se já existe NF-e emitida para esse numeroPedidoLoja no Bling,
       buscando as NF-e dos últimos `dias` dias e filtrando pelo campo
       numeroPedidoLoja no payload retornado (filtragem no lado do cliente,
       para não depender de um parâmetro de busca específico da API do Bling
       que pode não existir/funcionar como esperado).
       Retorna o dict da NF-e encontrada, ou None se não encontrar (ou em caso de erro,
       sempre retorne None e logue o erro — nunca lance exceção, e NUNCA bloqueie a
       emissão por uma falha nessa verificação; trate como "não encontrado" se a
       checagem falhar, e deixe um aviso bem visível no log dizendo que a checagem
       de duplicidade não pôde ser confirmada).
       """
   ```
   Implemente usando `_request_bling("GET", f"{BASE}/nfe", params={...período...})`, seguindo o padrão de paginação/filtros já usado em outras funções de listagem do mesmo arquivo (`listar_produtos`, etc. — confirme o nome exato dos parâmetros de data aceitos pelo endpoint `GET /nfe` da API v3 do Bling, consultando a documentação oficial do Bling antes de implementar; se não tiver certeza do nome do parâmetro de filtro por data, liste sem filtro de data e filtre tudo no lado do Python, ainda comparando por `numeroPedidoLoja`).

2. Em `agentes/faturamento/agente_faturamento.py`, dentro de `emitir_nfe_pedido()`, ANTES de montar/chamar `criar_nfe()` (mas depois da validação de NCM, que já existe), adicione a checagem:
   ```python
   if not dry_run:
       existente = buscar_nfe_por_pedido(pedido_id)
       if existente:
           logger.info("NF-e já existente para pedido %s — pulando emissão duplicada.", pedido_id)
           return {
               "ok": True,
               "pedido_id": pedido_id,
               "ja_emitida": True,
               "nfe": existente,
           }
   ```
   IMPORTANTE: essa checagem só deve rodar quando `dry_run=False` (emissão real) — não precisa checar duplicidade em modo simulação, já que nada é criado nesse caso. Importe `buscar_nfe_por_pedido` no topo do arquivo junto com `buscar_produto, criar_nfe`.

3. Garanta que essa mudança seja TRANSPARENTE para quem chama `emitir_nfe_pedido()` — tanto `agente_panorama.py` quanto `agentes/operacao_24h.py` já tratam o retorno por `resultado.get("ok")`; como o novo caminho também retorna `ok: True`, nenhum dos dois precisa de alteração. Apenas confirme isso lendo os dois call sites (`agente_panorama.py::_processar_nfe` e `operacao_24h.py`) para garantir que tratam bem o campo novo `ja_emitida` (não precisa fazer nada com ele, só não deve quebrar se o campo não for reconhecido).

4. Adicione testes em `tests/test_agente_faturamento.py` (ou crie se não existir, seguindo o padrão de outros `tests/test_*.py`): mockando `buscar_nfe_por_pedido` para simular: (a) pedido já faturado → não chama `criar_nfe`, retorna `ja_emitida: True`; (b) pedido novo → chama `criar_nfe` normalmente; (c) a checagem de duplicidade falha com exceção → não bloqueia a emissão (segue chamando `criar_nfe` normalmente, só loga o aviso).

5. Adicione testes em `tests/test_bling_client.py` para `buscar_nfe_por_pedido`: encontra NF-e existente, não encontra (lista vazia), erro de rede (retorna `None`, não lança).

═══════════════════════════════════════════════════
ITEM 3 — Cron de segurança para operacao_24h
═══════════════════════════════════════════════════

PROBLEMA CONFIRMADO:
`agentes/operacao_24h.py` só é executado via `POST /operacao/24h` na API Flask — não existe em nenhum workflow do GitHub Actions. Depende 100% de algo externo (n8n) chamar esse endpoint; se o n8n falhar silenciosamente, essa rotina (repricing + faturamento + algoritmo de saúde) para sem nenhum alerta interno avisando.

Como o Item 2 já elimina o risco de duplicidade, agora é seguro ter esse cron rodando como camada extra de segurança, mesmo que o n8n também esteja chamando o mesmo endpoint/função em paralelo.

TAREFA:
1. Crie `.github/workflows/operacao_24h_seguranca.yml`, no mesmo padrão dos outros workflows do projeto, rodando a cada 2 horas (ex.: `0 */2 * * *` em UTC, com comentário convertendo pra BRT como os outros já fazem).
2. O step principal deve chamar `python -c "from agentes.operacao_24h import executar; executar(dry_run_repricing=False, dry_run_nfe=False)"` — confirme a assinatura exata de `executar()` em `agentes/operacao_24h.py` antes de escrever essa linha (os nomes dos parâmetros podem ser diferentes do que está aqui de exemplo).
3. Inclua todas as variáveis de ambiente/Secrets necessárias (Bling, ML, Magalu, Lojahub, Telegram) — copie a lista de Secrets de outro workflow existente que já use as mesmas integrações (ex.: `agente_principal.yml` ou `panorama.yml`).
4. Documente no `README.md` que esse workflow é um "cron de segurança" — explique que ele não substitui o n8n, é uma camada redundante para garantir que repricing/faturamento não fiquem dias parados se o n8n cair, e que a proteção contra NF-e duplicada (Item 2) torna seguro os dois rodarem em paralelo.

═══════════════════════════════════════════════════
REGRAS GERAIS
═══════════════════════════════════════════════════
- Nenhuma das 3 mudanças deve afetar o comportamento de quem já chama essas funções hoje sem os novos parâmetros — tudo deve ter defaults compatíveis.
- Toda escrita (estoque, NF-e) continua exigindo os guardrails que já existem no projeto (dry_run, try/except, nunca propagar exceção).
- Rode `python -m pytest -q` e `ruff check api agentes core integracoes tests` no final de tudo. Confirme 0 falhas e cobertura ≥ 80% (`--cov-fail-under=80` em `pyproject.toml`).
- Atualize o `README.md` para cada novo endpoint, workflow, agente ou variável de ambiente adicionada.