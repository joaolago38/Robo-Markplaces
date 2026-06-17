# Tarefa: corrigir a lista de credenciais do Magalu em `scripts/renovar_tokens.py`

## Bug
No arquivo `scripts/renovar_tokens.py`, no topo, existe esta constante:

```python
CREDENCIAIS_MAGALU = ["MAGALU_CLIENT_ID", "MAGALU_CLIENT_SECRET", "MAGALU_MERCHANT_ID"]
```

Ela está **errada**. O `MAGALU_MERCHANT_ID` é opcional, costuma ficar vazio, e **não é usado na renovação do token**. A função real de renovação `_renovar_token_magalu()` (em `core/token_manager.py`) só precisa de `MAGALU_CLIENT_ID`, `MAGALU_CLIENT_SECRET` e `MAGALU_REFRESH_TOKEN`.

Como o `MERCHANT_ID` está vazio, o check `tem_magalu = _tem_credenciais(CREDENCIAIS_MAGALU)` retorna `False`. Isso causa dois efeitos ruins no mesmo arquivo:
1. O resumo imprime `"magalu: sem credenciais — ignorado"` mesmo quando a renovação acontece (rótulo falso).
2. O write-back do Magalu é pulado, porque está condicionado a `tem_magalu`:
   ```python
   if magalu_ok and tem_magalu and (em_actions or quer_sync):
       ... grava o Secret MAGALU_*
   ```
   Ou seja, mesmo renovando com sucesso, o refresh rotacionado nunca é salvo.

## Correção (uma linha)
Troque a constante para usar `MAGALU_REFRESH_TOKEN` no lugar de `MAGALU_MERCHANT_ID`, alinhando com o que a renovação realmente exige:

```python
CREDENCIAIS_MAGALU = ["MAGALU_CLIENT_ID", "MAGALU_CLIENT_SECRET", "MAGALU_REFRESH_TOKEN"]
```

## NÃO fazer
- Não alterar `CREDENCIAIS_ML` nem `CREDENCIAIS_SHOPEE` (essas já estão corretas para os respectivos fluxos — a Shopee usa partner_id/partner_key/shop_id de propósito).
- Não mexer em `core/token_manager.py` nem em qualquer outra parte do `renovar_tokens.py`.
- Não remover o suporte ao `MAGALU_MERCHANT_ID` em outros lugares do projeto (ele pode ser usado em chamadas de API do Magalu); apenas tirá-lo do check de credenciais da renovação.

## Validar
- Se houver testes (`tests/test_renovar_tokens*.py`), rode `pytest -q` e garanta que continuam passando.
- Rode `ruff check .` se o projeto usar ruff.

## Entregar
A linha `CREDENCIAIS_MAGALU` corrigida, e confirmação de que os testes (se existirem) continuam verdes.