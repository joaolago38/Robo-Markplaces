Implemente envio automático de logs para o Datadog (Log Management via HTTP Intake API, sem precisar de Agent/servidor), com foco especial em dar visibilidade total das operações de Mercado Livre e Bling — e preencha lacunas de logging que encontrei nessas operações vitais (hoje só erros são logados, sucessos não aparecem em nenhum lugar persistente).

CONTEXTO:
O projeto roda majoritariamente em GitHub Actions (VMs efêmeras) — os logs de `print`/`logger` hoje só existem no console de cada execução e se perdem quando o job termina. Não há lugar centralizado pra ver "o que aconteceu" entre execuções. O Datadog tem uma API HTTP de Log Intake que aceita logs via POST simples, sem precisar instalar Agent nem ter servidor — funciona perfeitamente de dentro de um job do GitHub Actions.

IMPORTANTE SOBRE CUSTO: Log Management do Datadog é cobrado por volume de log ingerido — não tente reduzir isso no código, mas ao implementar, garanta que SÓ nível INFO pra cima seja enviado (nunca DEBUG), e adicione uma forma fácil de desligar tudo (`DD_LOGS_ENABLED=false`) sem precisar reverter código, para o usuário poder controlar o volume/custo depois.

═══════════════════════════════════════════════════
ITEM 1 — Handler de logging centralizado para o Datadog
═══════════════════════════════════════════════════

1. Crie `core/datadog_logger.py`:
   ```python
   """
   core/datadog_logger.py
   Handler de logging que envia registros para o Datadog Log Management
   via HTTP Intake API. Nunca lança exceção — falha de rede no envio do
   log não pode derrubar a aplicação.
   """
   import json
   import logging
   import os

   import requests

   from core.config import (
       DD_API_KEY,
       DD_SITE,
       DD_LOGS_ENABLED,
   )

   _MARKETPLACE_POR_LOGGER = {
       "bling_client": "bling",
       "token_manager": "bling_e_ml",  # token_manager cobre vários providers; refine se quiser separar
       "ml_client": "mercadolivre",
       "ml_product_ads": "mercadolivre_ads",
       "magalu_client": "magalu",
       "shopee_client": "shopee",
       "agente_faturamento": "bling",
       "agente_repricing_marketplaces": "mercadolivre_e_outros",
       "sincronizar_estoque_marketplaces": "mercadolivre_e_outros",
       "agente_monitor_ml": "mercadolivre",
       "agente_ads_gatilho": "mercadolivre_ads",
   }


   class DatadogLogHandler(logging.Handler):
       def __init__(self):
           super().__init__()
           self._url = f"https://http-intake.logs.{DD_SITE}/api/v2/logs"

       def emit(self, record: logging.LogRecord) -> None:
           if not DD_LOGS_ENABLED or not DD_API_KEY:
               return
           try:
               marketplace = _MARKETPLACE_POR_LOGGER.get(record.name, "geral")
               payload = [{
                   "message": self.format(record),
                   "ddsource": "python",
                   "service": "robo-markplaces",
                   "ddtags": f"env:production,logger:{record.name},marketplace:{marketplace},level:{record.levelname.lower()}",
               }]
               requests.post(
                   self._url,
                   headers={"DD-API-KEY": DD_API_KEY, "Content-Type": "application/json"},
                   data=json.dumps(payload),
                   timeout=3,
               )
           except Exception:
               # Nunca deixar uma falha de envio de log derrubar a aplicação.
               pass
   ```
   Ajuste o nome dos campos/payload conforme a documentação oficial atual da API v2 de Log Intake do Datadog (`POST /api/v2/logs`) — confirme o formato exato (o exemplo acima é a estrutura básica esperada, mas valide nomes de campo como `ddsource`, `ddtags`, `service`, `message` antes de finalizar).

2. Em `core/config.py`, adicione:
   ```python
   DD_API_KEY = os.getenv("DD_API_KEY", "")
   DD_SITE = os.getenv("DD_SITE", "datadoghq.com")
   DD_LOGS_ENABLED = os.getenv("DD_LOGS_ENABLED", "true").lower() in {"1", "true", "yes"}
   ```

3. Crie uma função `configurar_logging_datadog()` em `core/datadog_logger.py` que:
   - Cria uma instância de `DatadogLogHandler`.
   - Define um nível mínimo `logging.INFO` no handler (nunca propague DEBUG).
   - Anexa o handler ao **logger raiz** (`logging.getLogger()`), com `logging.basicConfig` ou `getLogger().addHandler(handler)`, de forma que TODOS os loggers já existentes no projeto (`bling_client`, `ml_client`, `token_manager`, etc.) passem a enviar pro Datadog automaticamente, sem precisar editar cada módulo individualmente.
   - Só faça isso se `DD_API_KEY` estiver configurada e `DD_LOGS_ENABLED` for `True`; senão, não anexe nada (no-op silencioso).
   - Garanta que essa função seja **idempotente** (chamar mais de uma vez não duplica o handler — verifique se já não há um `DatadogLogHandler` anexado antes de adicionar outro).

4. Chame `configurar_logging_datadog()` automaticamente na inicialização de `core/config.py` (no final do módulo, depois de todas as variáveis serem definidas) — assim, qualquer script/agente que já importa `core.config` (praticamente todos) passa a ter os logs enviados ao Datadog automaticamente, sem precisar adicionar nenhuma chamada manual em cada entrypoint.

═══════════════════════════════════════════════════
ITEM 2 — Preencher lacunas de logging nas operações vitais (Bling e ML)
═══════════════════════════════════════════════════

Hoje, `integracoes/bling/bling_client.py` só tem `logger.error`/`logger.warning` — NENHUM `logger.info` em nenhum caminho de sucesso. Isso significa que, mesmo com o Datadog configurado, você não vai ver quando as coisas DÃO CERTO, só quando falham. Adicione `logger.info` nos seguintes pontos (sem exagerar — só nas operações de ESCRITA/estado importante, não em toda leitura, para não gerar volume excessivo):

1. `integracoes/bling/bling_client.py::criar_nfe()` — após sucesso (`r.raise_for_status()` sem exceção), adicione `logger.info("Bling NF-e criada com sucesso numeroPedidoLoja=%s", payload_nfe.get("numeroPedidoLoja"))` antes do `return`.
2. `integracoes/bling/bling_client.py::atualizar_ncm_produto()` — log de sucesso similar, incluindo o `produto_id` e o NCM aplicado.
3. `agentes/faturamento/agente_faturamento.py::emitir_nfe_pedido()` — no caminho de sucesso real (depois de `criar_nfe` retornar `ok: True`, antes do `return` final da função), adicione `logger.info("NF-e emitida com sucesso pedido_id=%s", pedido_id)`. Hoje só existe log para o caso de NF-e JÁ existente (duplicada) — falta o log do caminho de emissão nova com sucesso.
4. `integracoes/ml/ml_client.py::pausar_anuncio()` e `encerrar_anuncio()` — log de sucesso incluindo `item_id` e o motivo (se disponível no contexto de quem chamou — se não houver motivo disponível na função, log só com `item_id` mesmo).
5. `integracoes/ml/ml_client.py::atualizar_preco_item()` e `atualizar_estoque_item()` — log de sucesso com `item_id` e o novo valor aplicado.
6. `core/token_manager.py::_renovar_token_bling()` (e o equivalente de ML/Magalu, se existirem funções de renovação parecidas) — confirme que já existe `logger.info` de sucesso na renovação (acredito que já exista "Token Bling renovado com sucesso" — se sim, não duplique; só confirme que está lá).

Para todos os pontos acima, NÃO logue dados sensíveis (tokens, dados de cliente como CPF/email completos) na mensagem — use apenas IDs, valores numéricos e status.

═══════════════════════════════════════════════════
ITEM 3 — Configuração e documentação
═══════════════════════════════════════════════════

1. Adicione em `.env.exemplo`, com comentários explicando cada uma:
   ```
   DD_API_KEY=
   DD_SITE=datadoghq.com
   DD_LOGS_ENABLED=true
   ```
2. Adicione `DD_API_KEY`, `DD_SITE` e `DD_LOGS_ENABLED` como Secrets/env em TODOS os workflows do `.github/workflows/` que já rodam código Python do projeto (cada job que tem uma seção `env:` com os outros Secrets) — sem isso, o handler nunca vai ter a API key disponível nas execuções agendadas.
3. No `README.md`, adicione uma seção "Observabilidade com Datadog" explicando:
   - Como obter a `DD_API_KEY` (Datadog → Organization Settings → API Keys).
   - Que isso é OPCIONAL — sem a variável configurada, o sistema funciona exatamente igual, só sem enviar logs.
   - Que o volume de log é cobrado pelo Datadog (Log Management tem custo por GB ingerido) — sugira, se o custo for uma preocupação, desligar com `DD_LOGS_ENABLED=false` a qualquer momento.
   - As tags disponíveis para filtrar no Datadog: `marketplace:bling`, `marketplace:mercadolivre`, `service:robo-markplaces`, `level:info|warning|error`.

═══════════════════════════════════════════════════
ITEM 4 — Testes
═══════════════════════════════════════════════════

Crie `tests/test_datadog_logger.py` cobrindo:
- Sem `DD_API_KEY` configurada: `emit()` não faz nenhuma chamada HTTP (mocke `requests.post` e use `assert_not_called()`).
- Com `DD_API_KEY` configurada e `DD_LOGS_ENABLED=true`: `emit()` chama `requests.post` com a URL/headers/payload esperados, incluindo a tag de `marketplace` correta com base no nome do logger (teste pelo menos com `logger.name == "bling_client"` esperando `marketplace:bling` e `logger.name == "ml_client"` esperando `marketplace:mercadolivre`).
- `requests.post` lançando exceção (rede fora) — `emit()` não deve propagar a exceção (deve ser engolida silenciosamente).
- `configurar_logging_datadog()` chamado duas vezes não duplica o handler no logger raiz (idempotência).

Rode `python -m pytest -q` e `ruff check api agentes core integracoes tests` no final. Confirme 0 falhas e cobertura ≥ 80%.