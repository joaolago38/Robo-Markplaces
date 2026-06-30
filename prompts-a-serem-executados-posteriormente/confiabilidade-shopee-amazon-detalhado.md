# PROMPT — confiabilidade real-time Shopee + Amazon (padrão `*_detalhado`)

Cole no Cursor dentro de `Robo-Markplaces`.
Replica o que já foi feito em ML/Magalu (Fase 4 do pacote Datadog) para
**Shopee e Amazon**.

Crie a branch `feature/confiabilidade-shopee-amazon` antes de começar.
Se algum trecho não bater com o repositório, pare e mostre o trecho real.

---

## CONTEXTO

Hoje só ML e Magalu têm:
- `listar_pedidos_detalhado()` → `(pedidos, ok)`
- `registrar_acesso()` só em sucesso real em `obter_saude_conta()`
- métrica `robo.dados.degradado` em falhas
- paginação onde aplicável

Shopee já faz `if ok: registrar_acesso` parcialmente; Amazon ainda pode
mascarar falha de API como lista vazia.

---

## ESCOPO

### Shopee (`integracoes/shopee/shopee_client.py`)

1. `listar_pedidos_detalhado(dias, max_paginas=10)` com paginação
2. `listar_pedidos()` como wrapper fino
3. `_listar_perguntas_nao_respondidas_detalhado` se existir listagem similar
4. `obter_saude_conta`: `registrar_acesso` só se `ok=True`
5. `incrementar("dados.degradado", ...)` em exceções

### Amazon (`integracoes/amazon/amazon_client.py`)

Mesmo padrão para `listar_pedidos` e `obter_saude_conta`.

### `agentes/vendas_notificador.py`

Usar `*_detalhado` + `_checar_busca_falhou` para Shopee e Amazon
(nos mesmos pontos já usados para ML/Magalu).

### Testes

Criar `tests/test_blindspots_shopee_amazon.py` espelhando
`tests/test_blindspots_ml_magalu.py`.

---

## GARANTIA

Assinaturas públicas existentes de `listar_pedidos()` mantêm retorno
`list[dict]` — wrappers finos apenas.

---

## VALIDAR

```bash
ruff check .
py -m pytest tests -q --no-cov
```

Todos os testes passando; contagem deve subir em relação a 679.
