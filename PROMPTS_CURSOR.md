# Tarefa: implementar funcionalidades faltantes da integração com Mercado Livre

## Contexto do projeto
Projeto Python que integra com a API do Mercado Livre (Mercado Libre / developers.mercadolibre.com).
Já existe:
- `.env` com: ML_CLIENT_ID, ML_CLIENT_SECRET, ML_ACCESS_TOKEN, ML_REFRESH_TOKEN, ML_SELLER_ID
- `catalogo/produtos.json` (catálogo estático) e `catalogo/COMO_PUBLICAR_NO_ML.md`
- `scripts/diagnostico_ml_produtos.py` e `scripts/verificar_marketplaces.py`
- Um sistema de agentes que roda em loop e envia alertas no Telegram
- Mecanismo de refresh de token (use o existente; não reinvente)

Antes de codar, LEIA o código atual para entender: como o token é carregado/renovado, onde ficam as chamadas HTTP, como os agentes são registrados/disparados, e o formato do `produtos.json`. Reaproveite os padrões que já existem.

## Regras gerais (obrigatórias)
1. Centralize TODAS as chamadas à API em um único cliente HTTP (ex.: `ml_client.py`) com: refresh automático em 401, tratamento de rate limit (429, backoff), e logging estruturado de request/response (sem vazar tokens).
2. NUNCA escreva token/secret no código. Use sempre `os.getenv`.
3. Toda ação IRREVERSÍVEL ou que GASTA DINHEIRO/afeta o comprador deve ter:
   - modo `dry_run=True` por padrão, e
   - confirmação explícita (flag/variável) para executar de verdade.
   Isso vale para: encerrar anúncio, publicar anúncio, ligar/pausar Product Ads, alterar orçamento, enviar mensagem a comprador.
4. Antes de usar qualquer endpoint abaixo, CONFIRME a versão/rota atual na doc oficial (developers.mercadolibre.com) — as rotas mudam. Os caminhos abaixo são ponto de partida, não verdade absoluta.
5. Escreva testes (pytest) com a API mockada e adicione cada nova capacidade ao diagnóstico para validar a conexão.
6. Não quebre nada que já funciona. Mudanças incrementais, um recurso por vez.

## Tarefas (em ordem de prioridade)

### 1. Pausar / ativar / encerrar anúncio
- `PUT /items/{item_id}` com body `{"status": "paused" | "active" | "closed"}`.
- `closed` é praticamente irreversível → exigir confirmação.
- Expor funções `pausar_anuncio(item_id)`, `ativar_anuncio(item_id)`, `encerrar_anuncio(item_id)` e conectá-las ao agente.

### 2. Sincronizar estoque para o ML (a função já existe, só falta conectar)
- Localize a função de sync pronta e ligue-a a um agente/rotina.
- Estoque simples: `PUT /items/{item_id}` `{"available_quantity": N}`.
- Com variações: `PUT /items/{item_id}/variations/{variation_id}`.
- Origem do estoque: defina a fonte de verdade (planilha/ERP/produtos.json) e documente.

### 3. Product Ads de verdade (ligar/pausar/orçamento) — hoje é stub
- Hoje só lê ACOS e alerta no Telegram. Implementar controle real via Mercado Ads:
  - Listar advertiser/campanhas, alterar `status` (active/paused) e `budget` da campanha.
  - Pontos de partida: `/advertising/advertisers`, campanhas e métricas sob `/advertising/...`.
- Regra de negócio sugerida: se ACOS > limite por X dias → pausar (com dry_run e confirmação).

### 4. Repricing com preço de concorrente AO VIVO (hoje usa preço estático)
- Substituir a leitura de `catalogo/produtos.json` por preço de mercado em tempo real:
  - Sugestão de preço: `GET /suggestions/items/{item_id}/details` (traz preço de referência do mercado), e/ou
  - Busca de concorrentes: `GET /sites/MLB/search?q=...`.
- Aplicar regras de margem mínima e teto antes de atualizar o preço via `PUT /items/{item_id}`.

### 5. Mensagens pós-venda / chat com comprador (hoje só pré-venda)
- Ler: `GET /messages/packs/{pack_id}/sellers/{seller_id}`.
- Responder: `POST /messages/packs/{pack_id}/sellers/{seller_id}`.
- Enviar mensagem a comprador exige confirmação (regra 3). Manter o fluxo de perguntas pré-venda existente intacto.

### 6. Envio / logística (shipping)
- `GET /shipments/{shipment_id}` (status), itens do envio, e geração de etiqueta.
- Expor consulta de status e, se aplicável, impressão de etiqueta. Etiqueta/ação de despacho → confirmação.

### 7. Categorias, avaliações e reclamações/disputas
- Categorias: `GET /sites/MLB/categories` e `GET /categories/{id}/attributes` (necessário para publicar — ver tarefa 8).
- Avaliações: `GET /reviews/item/{item_id}`.
- Reclamações/disputas (mediações): explorar os endpoints de claims/post-purchase. Começar só por LEITURA + alerta no Telegram; ações de resposta vêm depois.

### 8. Criar / publicar anúncio (hoje é manual)
- `POST /items` com payload completo: title, category_id, price, currency_id, available_quantity, condition, listing_type_id, pictures, attributes, etc.
- Use o predador/preditor de categoria e os atributos obrigatórios da categoria antes de publicar.
- Publicação real → dry_run + confirmação. Validar payload contra os atributos obrigatórios antes de enviar.

## Critérios de aceitação
- Cada recurso tem função isolada, testes mockados e entrada no script de diagnóstico.
- Nenhuma ação que gasta dinheiro ou afeta comprador roda sem dry_run/confirmação.
- 401 dispara refresh automático e a chamada é repetida uma vez.
- README atualizado: o que cada novo agente faz, variáveis necessárias e como acionar.

## Como validar ao final
- `python scripts/diagnostico_ml_produtos.py` deve listar anúncios e exercitar as novas leituras.
- `pytest` verde.
- Rodar cada novo recurso em dry_run e mostrar no log o que SERIA feito, sem executar.

Comece pela tarefa 1, me mostre o diff, e só siga para a próxima após eu aprovar.