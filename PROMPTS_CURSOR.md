Implemente as melhorias abaixo no Robo-Markplaces, relacionadas a ACOS / Product Ads do Mercado Livre. São 5 itens independentes — implemente NA ORDEM listada (do mais simples/maior impacto para o mais complexo) e rode `python -m pytest -q` depois de cada item para garantir que nada quebrou antes de seguir pro próximo.

═══════════════════════════════════════════════════
ITEM 1 (PRIORIDADE MÁXIMA) — Corrigir ACOS errado em operacao_24h
═══════════════════════════════════════════════════

BUG CONFIRMADO:
Em `agentes/operacao_24h.py`, função `executar()`, o ACOS usado no gatilho de ads vem de:
```python
_rep = buscar_reputacao_vendedor()
_metrics = _rep.get("metrics", {})
_acos_atual = float(_metrics.get("acos", 0.0) or 0.0)
```
`buscar_reputacao_vendedor()` (em `integracoes/ml/ml_client.py`) chama `GET /users/{ML_SELLER_ID}` e retorna o campo `seller_reputation` — essa é a API de REPUTAÇÃO do vendedor (claims, cancelamentos, atraso), que NÃO tem chave `acos`. Ou seja, `_acos_atual` é **sempre 0.0** nesse fluxo, então a condição de pausa em `agente_ads_gatilho.avaliar_momento_ads()`:
```python
elif acos_atual > ACOS_MAXIMO and acos_atual > 0:
    decisao = "pausar"
```
nunca é satisfeita via `operacao_24h`. O gatilho de pausa por ACOS alto está efetivamente morto nesse fluxo (mesmo que `agente_ads_gatilho.executar(item_id=...)` saiba calcular certo quando recebe um `item_id`).

CORREÇÃO:
1. Em `agentes/operacao_24h.py`, substitua o cálculo de `_acos_atual` para usar dados reais de Product Ads em vez de reputação. Use a função `campanhas_acos_acima_limite` ou `listar_campanhas` de `integracoes/ml/ml_product_ads.py` para obter o ACOS agregado das campanhas ativas (ex.: ACOS ponderado por gasto, ou o maior ACOS entre as campanhas com `cost > 0`).
2. Importe no topo do arquivo:
   ```python
   from integracoes.ml.ml_product_ads import listar_campanhas
   ```
3. Substitua o bloco que calcula `_acos_atual` por algo como:
   ```python
   try:
       _campanhas = listar_campanhas(dias=14)
       _campanhas_com_gasto = [c for c in _campanhas if c.get("cost", 0) > 0]
       if _campanhas_com_gasto:
           _gasto_total = sum(c["cost"] for c in _campanhas_com_gasto)
           _acos_atual = sum(c["acos"] * c["cost"] for c in _campanhas_com_gasto) / _gasto_total
       else:
           _acos_atual = 0.0
   except Exception as _e:
       logger.warning("Não foi possível calcular ACOS agregado de Product Ads: %s", _e)
       _acos_atual = 0.0
   ```
   (mantenha a busca de reputação como está, só para `_total_avaliacoes`, `_nota_media` e `_full_ativo` — não remova essas linhas, só pare de usar `_metrics.get("acos")`).
4. Garanta que o payload de retorno continue compatível (`gatilho_ads = verificar_gatilho_ads(acos_atual=_acos_atual, full_ativo=_full_ativo)` permanece igual).
5. Ajuste/crie teste em `tests/test_operacao_24h.py` cobrindo: quando há campanhas com ACOS acima do limite e gasto > 0, `_acos_atual` calculado deve refletir isso e o gatilho deve poder decidir "pausar" (mock de `listar_campanhas` retornando campanhas fake).

═══════════════════════════════════════════════════
ITEM 2 — Cron dedicado para agente_ads_gatilho
═══════════════════════════════════════════════════

Hoje `agentes/ml/agente_ads_gatilho.py` só roda dentro de `operacao_24h`, que não está no schedule diário de ads (`monitor_ml.yml` roda só o monitor, não o gatilho).

1. Veja os workflows existentes em `.github/workflows/` (ex.: `monitor_ml.yml`) para entender o padrão de schedule/cron usado no projeto.
2. Crie um workflow novo `.github/workflows/ads_gatilho_ml.yml`, copiando a estrutura do `monitor_ml.yml`, mas chamando `agentes/ml/agente_ads_gatilho.py` (via `python -m agentes.ml.agente_ads_gatilho` ou script equivalente) em um horário separado (ex.: 1x ao dia, sugestão 10:00 BRT, depois do monitor das 09:00).
3. Garanta que o script tenha um bloco `if __name__ == "__main__":` funcional standalone (ele já tem, no final do arquivo, chamando `executar()`) — não precisa de `item_id`, mas valide se faz sentido manter sem item_id ou se deveria iterar por itens com ads ativos (decida com base no item 1, já corrigido, que agora alimenta acos_atual agregado mesmo sem item_id — então o gatilho standalone pode chamar internamente o mesmo cálculo agregado do item 1, OU receber `acos_atual` como parâmetro de CLI/env).
4. Documente a nova rotina no `README.md`, na seção de agentes/cron, igual já é feito para os outros.

═══════════════════════════════════════════════════
ITEM 3 — Endpoint REST /ml/ads/diagnostico
═══════════════════════════════════════════════════

Hoje só existe endpoint de validação de campanhas para Meta (`/meta/campanhas/validar`); não existe equivalente para ML Product Ads, mesmo já existindo a lógica pronta em `agentes/ml/agente_monitor_ml.py`, função `analisar(*, limite_itens=MAX_ITENS_ANALISE, enviar_alerta=True) -> dict`, que já retorna um dict estruturado com `conta`, `ads`, `concorrencia`, `recomendacoes`, `resumo`.

1. Em `api/app.py`, siga exatamente o padrão dos endpoints existentes (ex.: `/marketplaces/algoritmo/ajustar`, linha ~484): valide JSON com `_get_json_payload()`, leia parâmetros opcionais do body.
2. Adicione:
   ```python
   @app.route("/ml/ads/diagnostico", methods=["POST"])
   def ml_ads_diagnostico():
       """
       POST /ml/ads/diagnostico
       Roda o diagnóstico somente-leitura de conta + Product Ads + concorrência no ML.
       Body opcional:
       {
           "limite_itens": 20,
           "enviar_alerta": false
       }
       """
       dados = _get_json_payload()
       if dados is None:
           return jsonify({"ok": False, "erro": "JSON inválido"}), 400

       from agentes.ml.agente_monitor_ml import analisar as analisar_monitor_ml, MAX_ITENS_ANALISE

       limite_itens = int(dados.get("limite_itens", MAX_ITENS_ANALISE))
       enviar_alerta = bool(dados.get("enviar_alerta", False))
       resultado = analisar_monitor_ml(limite_itens=limite_itens, enviar_alerta=enviar_alerta)
       status_code = 200 if resultado.get("ok") else 503
       return jsonify(resultado), status_code
   ```
3. Importe `analisar` no topo do arquivo se preferir, em vez de import local dentro da função (siga o padrão de imports já usado no resto do `api/app.py`).
4. Adicione o endpoint na lista de "Endpoints principais" do `README.md`.
5. Crie teste em `tests/test_api_endpoints.py` cobrindo: chamada com sucesso (mock de `analisar` retornando `ok: True`) e com ML não configurado (mock retornando `ok: False` → deve responder 503).

═══════════════════════════════════════════════════
ITEM 4 — Recomendação por campanha (não pausar tudo em lote)
═══════════════════════════════════════════════════

Hoje, em `integracoes/ml/ml_product_ads.py`, `aplicar_decisao_campanhas(decisao, ...)` aplica a decisão (ativar/pausar/escalar) em TODAS as campanhas, e é chamada assim em `agentes/ml/agente_ads_gatilho.py::_executar_api_se_aprovado`:
```python
aplicacoes = aplicar_decisao_campanhas(
    api_decisao,
    budget=float(resultado.get("budget_sugerido_dia") or 0),
    dry_run=False,
    confirmar=True,
)
```
Isso significa que se 1 campanha está com ACOS alto, TODAS são pausadas/alteradas — não é seletivo.

1. Olhe a assinatura completa de `aplicar_decisao_campanhas` em `integracoes/ml/ml_product_ads.py` (linha ~326) e veja se já existe algum parâmetro de filtro por `campaign_ids`. Se não existir, adicione um parâmetro opcional `campaign_ids: list[str] | None = None` — quando informado, a função deve aplicar a decisão SOMENTE nessas campanhas; quando `None`, mantém o comportamento atual (todas) para não quebrar quem já usa a função sem esse parâmetro.
2. Em `agentes/ml/agente_ads_gatilho.py`, na decisão `"pausar"`, em vez de pausar tudo, use `campanhas_acos_acima_limite()` (de `ml_product_ads.py`) para obter a lista de campanhas com ACOS acima do limite e passe só os IDs delas (`campaign_ids=[c["id"] for c in campanhas_acima]`) para `aplicar_decisao_campanhas`. Para as decisões `"ligar"` e `"escalar"`, mantenha o comportamento de aplicar em todas (ou avalie se faz sentido restringir também — documente a decisão tomada em um comentário no código).
3. Atualize/adicione testes em `tests/test_ml_product_ads.py` e `tests/test_agente_ads_gatilho.py` (crie esse arquivo de teste se não existir) cobrindo: pausa seletiva afeta só a campanha com ACOS alto, outras campanhas saudáveis não são tocadas.

═══════════════════════════════════════════════════
ITEM 5 — Enriquecer análise de concorrência (mais dados, não só preço)
═══════════════════════════════════════════════════

Hoje, em `agentes/ml/agente_monitor_ml.py`, função `_analisar_concorrencia`, e em `integracoes/ml/ml_client.py`, função `buscar_menor_preco_concorrente(item_id)`, a comparação com concorrentes retorna SOMENTE o menor preço (um número), sem título, condição do anúncio, frete ou outros atributos.

1. Em `integracoes/ml/ml_client.py`, ao lado de `buscar_menor_preco_concorrente`, crie uma função nova `buscar_detalhes_concorrentes(item_id: str, limite: int = 5) -> list[dict]` que reutiliza a mesma busca de itens concorrentes já feita internamente em `buscar_menor_preco_concorrente` (avalie reaproveitar a lógica de busca por categoria/keyword já existente), mas retornando, para cada concorrente encontrado, um dict com: `id`, `titulo`, `preco`, `frete_gratis` (bool, se disponível no payload do ML), `condicao` (novo/usado), `quantidade_vendida` (se disponível). Limite a quantidade de concorrentes retornados (parâmetro `limite`, default 5) para não pesar a chamada.
2. Nunca lance exceção (siga o padrão do resto do arquivo: `try/except` retornando lista vazia em caso de erro, com `logger.error`).
3. Em `agentes/ml/agente_monitor_ml.py::_analisar_concorrencia`, inclua esses detalhes no dict retornado por item (além do que já existe hoje), para que fiquem disponíveis no JSON consumido pelo `agente_panorama` e pelo Claude.
4. NÃO implemente scraping de páginas de concorrentes nem chamadas a APIs fora do ML — use só o que a API pública/autenticada do Mercado Livre já expõe (mesma base do que `buscar_menor_preco_concorrente` já usa).
5. Em `agentes/panorama/agente_panorama.py`, ajuste o prompt enviado ao Claude (veja onde ele monta o contexto/JSON operacional) para incluir esses novos campos de concorrência, e ajuste a instrução do prompt para que o Claude possa comentar sobre título/condição/frete do concorrente quando relevante — sem inventar dados que não vieram da API (deixe explícito no prompt que ele só deve comentar sobre o que está no JSON).
6. Atualize testes em `tests/test_ml_client.py` e `tests/test_agente_monitor_ml.py` (e `tests/test_agente_panorama.py` se o formato do prompt mudar) cobrindo o novo formato de dados.

═══════════════════════════════════════════════════
REGRAS GERAIS PARA TODOS OS ITENS
═══════════════════════════════════════════════════
- Não quebre nenhuma função pública existente (assinatura/retorno) sem motivo — prefira parâmetros opcionais com default que preservam o comportamento atual.
- Todas as chamadas a APIs externas devem continuar com `try/except` e nunca lançar exceção não tratada (padrão já usado em todo `integracoes/` e `core/`).
- Toda nova escrita (pausar/ativar campanha, alterar budget) continua exigindo `dry_run`/`confirmar` conforme os guardrails já existentes em `ml_product_ads.py` — não remova nem flexibilize esses guardrails.
- Rode `ruff check .` e `python -m pytest -q` no final de tudo. Cobertura mínima de 80% (`--cov-fail-under=80` já configurado em `pyproject.toml`) precisa continuar passando.
- Atualize o `README.md` sempre que adicionar endpoint, variável de ambiente nova ou rotina de cron nova, seguindo o estilo de documentação já usado nas seções existentes.