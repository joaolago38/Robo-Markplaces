Implemente um agente novo, somente-sugestão (não escreve nada no ML), que usa o Claude para sugerir melhorias de título/descrição de anúncios do Mercado Livre, comparando com os concorrentes — para ajudar a competir melhor no algoritmo de busca do ML sem depender de tentativa e erro manual.

CONTEXTO E DADOS JÁ DISPONÍVEIS (não precisa criar):
- `integracoes/ml/ml_client.py::buscar_metricas_item(item_id) -> dict` já retorna do PRÓPRIO anúncio: `titulo`, `status`, `preco`, `estoque`, `visitas_7d`, `visitas_30d`.
- `integracoes/ml/ml_client.py::buscar_detalhes_concorrentes(item_id, limite=5) -> list[dict]` já retorna dos concorrentes: `titulo`, `preco`, `frete_gratis`, `condicao`, `quantidade_vendida`.
- `core/claude_client.py::perguntar(prompt, max_tokens=500, contexto=None) -> str` já existe para chamar o Claude, mas o `SYSTEM` prompt hoje está fixo em "agente de vendas de esmaltes" — não serve pra essa tarefa de otimização de listing.

IMPORTANTE — ESSE AGENTE NÃO ESCREVE NADA NO MERCADO LIVRE:
Não existe (e não deve ser criada) nenhuma função de escrita de título/descrição no `ml_client.py` para este agente usar — ele é 100% sugestão para revisão humana via Telegram. Alterar título de anúncio afeta SEO/conversão de forma sensível e não deve ser automático.

TAREFA:

1. Em `core/claude_client.py`, ajuste a função `perguntar` para aceitar um `system` opcional, sem quebrar quem já chama sem esse parâmetro:
   ```python
   def perguntar(prompt: str, max_tokens: int = 500, contexto: str | None = None, system: str | None = None) -> str:
       ...
       "system": system or SYSTEM,
       ...
   ```
   (mantenha o `SYSTEM` padrão atual como fallback para todas as chamadas existentes que não passam `system`.)

2. Crie `agentes/ml/agente_otimizador_listing.py`, seguindo o estilo dos outros agentes do projeto (logger, try/except que nunca propaga exceção, retorno em dict estruturado). Defina:
   ```python
   SYSTEM_OTIMIZADOR = (
       "Você analisa anúncios do Mercado Livre e sugere melhorias de título "
       "com base em dados reais fornecidos (próprio anúncio e concorrentes). "
       "Nunca invente especificações, certificações ou características do produto "
       "que não estejam no contexto fornecido. Seja objetivo: até 3 sugestões de "
       "título alternativo (respeitando o limite de 60 caracteres do Mercado Livre) "
       "e um motivo curto para cada sugestão, baseado em padrões observados nos "
       "concorrentes com mais vendas/visitas."
   )

   def analisar_item(item_id: str) -> dict:
       """
       Busca métricas do próprio item + concorrentes, pede ao Claude sugestões
       de título, e retorna um dict estruturado. Nunca lança exceção.
       """
   ```
   `analisar_item` deve:
   - Chamar `ml_client.buscar_metricas_item(item_id)`; se vier vazio (item não encontrado/erro), retornar `{"ok": False, "erro": "..."}`.
   - Chamar `ml_client.buscar_detalhes_concorrentes(item_id, limite=5)`.
   - Montar um contexto textual claro com os dados reais (título atual, preço, visitas, e cada concorrente com título/preço/vendas), e chamar `claude_client.perguntar(..., system=SYSTEM_OTIMIZADOR, contexto=...)` pedindo as sugestões.
   - Retornar `{"ok": True, "item_id": ..., "titulo_atual": ..., "visitas_7d": ..., "sugestoes_texto": <resposta do Claude>, "concorrentes_analisados": <quantidade>}`.
   - Se `claude_client.perguntar` retornar uma das strings de erro padrão dela (ex.: começando com "⚠️"), propague isso em `sugestoes_texto` mas mantenha `ok: True` (a busca de dados funcionou, só a IA falhou) — deixe claro no payload com um campo extra `ia_falhou: True` nesse caso.

3. Adicione também `analisar_catalogo(limite_itens: int = 10) -> dict`, que:
   - Carrega `catalogo/produtos.json` (mesmo arquivo já usado por `agentes/sincronizar_estoque_marketplaces.py`) para obter os `item_id` do Mercado Livre de cada produto ativo (`canais.mercadolivre.ativo == True` e `item_id` válido).
   - Roda `analisar_item` para até `limite_itens` produtos (para não exceder tempo de execução/rate limit da API do ML em uma única chamada).
   - Monta um resumo consolidado e envia via `core.notificador.alertar_gestor()` — formato sugerido: para cada item com sugestão relevante, título atual, visitas, e a primeira sugestão do Claude; produtos sem nenhum concorrente encontrado podem ser omitidos do resumo (não há base de comparação).
   - Retorna um dict com a lista completa de resultados por item, para uso por quem chamar programaticamente (ex.: endpoint da API).

4. Adicione um endpoint novo em `api/app.py`, seguindo o padrão dos outros:
   ```python
   @app.route("/ml/listing/otimizar", methods=["POST"])
   def ml_listing_otimizar():
       """
       POST /ml/listing/otimizar
       Sugere melhorias de título de anúncios do ML via IA, comparando com concorrentes.
       Não altera nada no Mercado Livre — apenas sugestão para revisão humana.
       Body opcional:
       {
           "item_id": "MLB123...",     // se informado, analisa só esse item
           "limite_itens": 10           // se item_id não for informado, analisa o catálogo
       }
       """
   ```
   Se `item_id` vier no body, chame `analisar_item`; senão, chame `analisar_catalogo(limite_itens=...)`.

5. Crie um workflow novo `.github/workflows/otimizar_listing.yml`, rodando 1x por semana (ex.: segunda-feira de manhã, horário BRT, igual ao `relatorio_financeiro.yml` — confira o horário usado lá para não rodar tudo junto e sobrecarregar o ciclo da manhã), chamando `analisar_catalogo()`. Inclua os Secrets necessários: ML (`ML_ACCESS_TOKEN`, `ML_SELLER_ID`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REFRESH_TOKEN`), `ANTHROPIC_API_KEY`, e os de Telegram para o alerta.

6. Testes: crie `tests/test_agente_otimizador_listing.py` cobrindo:
   - `analisar_item`: item não encontrado retorna `ok: False`; sucesso com concorrentes monta o contexto e chama `claude_client.perguntar` com `system=SYSTEM_OTIMIZADOR` (mocke `perguntar` e confirme os argumentos); falha da IA (mock retornando string de erro) ainda retorna `ok: True` com `ia_falhou: True`.
   - `analisar_catalogo`: lê produtos do `catalogo/produtos.json` mockado (não leia o arquivo real do projeto no teste — use um fixture/mock de conteúdo), respeita `limite_itens`, ignora produtos sem ML ativo, chama `alertar_gestor` ao final.
   - Em `core/claude_client.py`: teste confirmando que `perguntar(..., system="outro")` usa o `system` passado em vez do `SYSTEM` padrão, e que chamadas sem `system` continuam usando o `SYSTEM` padrão (não quebra comportamento existente).

7. Atualize o `README.md`: documente o novo endpoint, o novo workflow, e deixe claro que esse agente é SOMENTE SUGESTÃO — não altera nada automaticamente no Mercado Livre.

8. Rode `python -m pytest -q` e `ruff check api agentes core integracoes tests` no final. Confirme 0 falhas e cobertura ≥ 80%.