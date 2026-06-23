Implemente um kill switch global no Robo-Markplaces: uma única variável de ambiente, `ROBO_PAUSAR_ESCRITA`, que bloqueia TODA escrita real (NF-e, repricing, estoque, anúncios) em qualquer canal, de uma vez, independente do `dry_run` de cada chamada individual.

CONTEXTO:
Hoje cada escrita real depende do parâmetro `dry_run` de cada chamada — funciona bem, mas não existe um único botão para travar tudo de emergência sem precisar mudar `dry_run` em vários lugares (Secrets do GitHub, corpo das requisições do n8n, etc.). Já existe um precedente parecido, só que restrito a Ads do ML: `ML_ADS_KILL_SWITCH` em `core/config.py`, checado dentro de `integracoes/ml/ml_product_ads.py::_guardrails_escrita()`. Vamos generalizar essa ideia para o projeto todo.

TAREFA:

1. Em `core/config.py`, adicione, próximo a `ML_ADS_KILL_SWITCH`:
   ```python
   ROBO_PAUSAR_ESCRITA = os.getenv("ROBO_PAUSAR_ESCRITA", "false").lower() in {"1", "true", "yes"}
   ```
   Documente no `.env.exemplo` com um comentário curto explicando que é o kill switch global de emergência — quando `true`, nenhuma escrita real acontece em nenhum canal, mesmo que `dry_run=False` seja passado.

2. Crie uma função auxiliar compartilhada em `core/config.py` (ou em um módulo novo `core/guardrails.py`, se preferir manter `config.py` só com declarações de variáveis — escolha o que for mais consistente com o resto do projeto):
   ```python
   def bloqueio_escrita_global() -> dict | None:
       """Retorna dict de erro padronizado se o kill switch global estiver ativo; None se a escrita pode seguir."""
       if ROBO_PAUSAR_ESCRITA:
           return {"ok": False, "erro": "ROBO_PAUSAR_ESCRITA ativo — toda escrita real está bloqueada globalmente"}
       return None
   ```

3. Adicione a checagem dessa função (`if (bloqueio := bloqueio_escrita_global()): return bloqueio` ou equivalente, adaptando ao formato de retorno de cada função) NO INÍCIO de cada uma das seguintes funções, ANTES de qualquer chamada de escrita real à API do canal (a checagem deve valer mesmo quando `dry_run=False` for passado — ela é mais forte que o `dry_run` de cada chamada):

   a. `integracoes/bling/bling_client.py::criar_nfe(payload_nfe)` — retornar `{"ok": False, "erro": "..."}` igual ao padrão de erro já usado nessa função.

   b. `integracoes/ml/ml_client.py::atualizar_estoque_item(item_id, novo_estoque)` — função retorna `bool`; se bloqueado, logar com `logger.warning` e retornar `False` (sem chamar a API).

   c. `integracoes/ml/ml_client.py::pausar_anuncio(item_id, *, dry_run, confirmar)` e `encerrar_anuncio(item_id, *, dry_run, confirmar)` — essas já retornam dict; adicione a checagem antes da lógica de `dry_run`/`confirmar`, retornando o erro do kill switch se ativo.

   d. `integracoes/magalu/magalu_client.py::atualizar_estoque_item(sku, novo_estoque)` — mesmo padrão do item (b): retorna `bool`, loga e retorna `False` se bloqueado.

   e. `integracoes/shopee/shopee_client.py::atualizar_estoque_item(item_id, novo_estoque, model_id=None)` — mesmo padrão.

   f. `integracoes/ml/ml_product_ads.py::_guardrails_escrita(budget=None)` — adicione a checagem do kill switch global ALI TAMBÉM, antes (ou junto) da checagem já existente do `ML_ADS_KILL_SWITCH`, para que `ROBO_PAUSAR_ESCRITA=true` também pause ads do ML, além do switch específico que já existe.

4. Além dos pontos de escrita de baixo nível (passo 3), adicione TAMBÉM uma checagem no início das funções de entrada dos agentes (defesa em profundidade — assim o bloqueio aparece de forma clara e cedo no log/payload, antes de gastar tempo processando):
   - `agentes/repricing/agente_repricing_marketplaces.py::executar(...)`
   - `agentes/faturamento/agente_faturamento.py::emitir_nfe_pedido(...)`
   - `agentes/sincronizar_estoque_marketplaces.py::executar(...)`
   - `agentes/operacao_24h.py::executar(...)`

   Em cada uma, se `cfg.ROBO_PAUSAR_ESCRITA` estiver ativo E a chamada não for puramente `dry_run=True` (ou seja, se o caller pediu escrita real), retorne imediatamente um payload de erro claro (seguindo o formato de retorno já usado por cada função) e envie UM alerta único via `alertar_gestor()` ou `alertar_critico()` avisando que o kill switch global está ativo e bloqueou a execução — para deixar bem visível que o motivo de "nada aconteceu" foi intencional, não uma falha.

5. NÃO bloqueie operações de LEITURA (monitoramento, relatórios, diagnóstico) — o kill switch global é só para escrita real. Funções como `agente_monitor_ml.analisar()`, `agente_panorama` (na parte de leitura/relatório), `verificar_marketplaces.py`, etc. devem continuar funcionando normalmente mesmo com `ROBO_PAUSAR_ESCRITA=true`.

6. Atualize o `README.md`:
   - Documente `ROBO_PAUSAR_ESCRITA` numa seção clara, tipo "Kill switch de emergência", explicando que ele tem prioridade sobre qualquer `dry_run=False` e lista todos os pontos que ele afeta (NF-e, estoque em todos os canais, anúncios ML, ads ML).
   - Mencione que, para reativar a escrita, basta voltar `ROBO_PAUSAR_ESCRITA=false` (ou remover a variável) nos Secrets/`.env`.

7. Adicione testes cobrindo, para CADA função alterada nos passos 3 e 4: com `ROBO_PAUSAR_ESCRITA=true` (via `patch.object`/`monkeypatch` na variável de `core.config`), a função NÃO deve chamar a API externa (mocke a chamada HTTP/cliente e use `assert_not_called()`) e deve retornar o erro/False esperado. Com `ROBO_PAUSAR_ESCRITA=false` (padrão), o comportamento deve continuar exatamente como já é hoje.

8. Rode `python -m pytest -q` e `ruff check api agentes core integracoes tests` no final. Confirme 0 falhas e cobertura ≥ 80% (`--cov-fail-under=80` em `pyproject.toml`).