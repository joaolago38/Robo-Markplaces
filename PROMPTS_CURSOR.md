# Tarefa: implementar Product Ads (controle real), Repricing ao vivo e Reclamações/Avaliações no Mercado Livre

## Contexto
Projeto Python que já integra com a API do Mercado Livre. Já existem:
- `.env` com ML_CLIENT_ID, ML_CLIENT_SECRET, ML_ACCESS_TOKEN, ML_REFRESH_TOKEN, ML_SELLER_ID
- mecanismo de refresh de token
- um sistema de agentes em loop + alertas no Telegram
- `catalogo/produtos.json` (catálogo estático)
- hoje o módulo de Product Ads só LÊ o ACOS e alerta no Telegram (stub)

Antes de codar: leia o cliente HTTP/refresh atual, o loop de agentes e como o Telegram é disparado. Centralize chamadas em um único `ml_client.py` com refresh em 401, backoff em 429 e logging sem vazar token.

> Os endpoints abaixo foram conferidos, mas SEMPRE valide a versão/rota atual em developers.mercadolibre.com antes de usar. Repare nos headers `api-version` — eles variam por recurso.

## Regras de segurança (obrigatórias)
- Toda ação que GASTA DINHEIRO ou afeta o comprador (pausar/ativar campanha, mudar orçamento, alterar preço, abrir disputa, responder reclamação) roda com `dry_run=True` por padrão e só executa de verdade com confirmação explícita.
- Em `dry_run`, logar e mandar no Telegram exatamente o que SERIA feito (antes/depois), sem chamar a API de escrita.
- Limites de guarda (guardrails) configuráveis: variação máxima de preço por execução, orçamento máximo de campanha, e "kill switch" geral via env.

---

## 1. Product Ads de verdade (ligar/pausar/orçamento)

### Descoberta
- Advertiser do vendedor: `GET /advertising/advertisers?product_id=PADS` (header `Api-Version: 1`).
  - Se vier 404 "No permissions found for user_id", o vendedor não tem Publicidade habilitada (Mi perfil > Publicidad). Tratar e alertar.

### Leitura (já parcialmente feito — consolidar)
- Campanhas + métricas:
  `GET /advertising/advertisers/{ADVERTISER_ID}/product_ads/campaigns?limit=&offset=&date_from=&date_to=&metrics=clicks,prints,ctr,cost,cpc,acos,roas,cvr,units_quantity,total_amount`
  (header `api-version: 2`)
- Status de anúncio por item: `GET /advertising/product_ads/items/{ITEM_ID}` (`api-version: 2`).
  - Estados relevantes: `hold` (item pausado/sem estoque no marketplace), `idle` (elegível mas fora de campanha).

### Escrita (o que falta)
- Atualizar campanha (status e/ou orçamento):
  `PUT /marketplace/advertising/{ADVERTISER_SITE_ID}/product_ads/campaigns/{CAMPAIGN_ID}` (`api-version: 2`)
  Body (enviar só o que muda):
```json
  { "status": "active|paused", "budget": 990, "strategy": "profitability", "channel": "marketplace", "roas_target": 25 }
```
- IMPORTANTE: NÃO use `acos_target` (descontinuado em 24/02/2026). Use `roas_target`.

### Regra de negócio sugerida
- Se ACOS acima do limite por X dias OU orçamento estourando sem conversão → propor pausar/reduzir orçamento (dry_run + confirmação).
- Funções: `listar_campanhas()`, `pausar_campanha(id)`, `ativar_campanha(id)`, `definir_orcamento(id, valor)`. Conectar ao agente.

---

## 2. Repricing com preço de concorrente AO VIVO

### Substituir a fonte estática (`produtos.json`) por referência de mercado em tempo real
- Itens do vendedor que possuem referência de preço:
  `GET /marketplace/benchmarks/user/{USER_ID}/items`
- A referência traz tipos `similar_price` e `adjusted_price`, com `amount` e `usd_amount` — use isso como sinal de mercado.
- Complementar (opcional) com busca de concorrentes: `GET /sites/{SITE_ID}/search?q=...` para o mesmo produto.

### Aplicar preço
- `PUT /items/{item_id}` com `{ "price": <novo_preco> }` (variações: `PUT /items/{item_id}/variations/{variation_id}`).
- Antes de aplicar: respeitar margem mínima, teto, e a variação máxima por execução (guardrail). Tudo em dry_run primeiro.
- (Opcional) Assinar o webhook `items_prices` para reagir a mudanças de preço em vez de só fazer polling.

### Entregáveis
- `obter_preco_mercado(item_id)`, `calcular_novo_preco(item_id)`, `aplicar_preco(item_id, preco)` — desacopladas e testáveis.

---

## 3. Categorias, avaliações e reclamações/disputas

### Categorias
- Árvore: `GET /sites/{SITE_ID}/categories` e detalhe/atributos: `GET /categories/{CATEGORY_ID}/attributes`.
- Preditor de categoria para classificar/validar anúncios.

### Avaliações
- `GET /reviews/item/{ITEM_ID}` para ler avaliações por anúncio (agregadas e individuais). Começar por leitura + alerta no Telegram de notas baixas.

### Reclamações / disputas (COMEÇAR SÓ COM LEITURA)
- Há duas superfícies conforme o tipo de vendedor — detecte qual se aplica:
  - `GET /post-purchase/v1/claims/{CLAIM_ID}` e
  - `/marketplace/v2/claims/{CLAIM_ID}` (vendedores marketplace/CBT).
- Útil: `GET /post-purchase/v1/claims/{CLAIM_ID}/affects-reputation` (se a reclamação afeta reputação).
- Motivos: `GET /post-purchase/v1/reasons/{REASON}/children`.
- Devoluções: `/post-purchase/v2/claims/{CLAIM_ID}/returns`.
- TRATAR o caso 403 "Model 6 / CBT": esses vendedores são bloqueados nesses endpoints — capturar e avisar, sem quebrar o loop.

### Ações (somente atrás de confirmação)
- Responder reclamação (mensagem): `POST` com body `{ "receiver_role": "complainant|mediator|respondent", "message": "...", "attachments": [...] }`.
- Abrir disputa: `POST /marketplace/v2/claims/{CLAIM_ID}/actions/open-dispute`.
- Implementar essas escritas por último, com dry_run + confirmação obrigatórios.

---

## Critérios de aceitação
- Cada função isolada, com testes pytest e a API mockada.
- Nenhuma escrita (campanha, preço, disputa, mensagem) executa sem dry_run/confirmação e dentro dos guardrails.
- 401 → refresh + retry uma vez; 429 → backoff; 403 Model 6 → tratado sem derrubar o agente.
- README e o diagnóstico atualizados com os novos recursos e variáveis.

## Como validar
- Rodar cada recurso em dry_run e mostrar no log/Telegram o "antes/depois" sem executar.
- `pytest` verde.
- Faça a tarefa 1 primeiro, me mostre o diff e aguarde aprovação antes de seguir para 2 e 3.