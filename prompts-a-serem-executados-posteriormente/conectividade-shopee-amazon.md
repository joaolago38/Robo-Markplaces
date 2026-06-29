# PROMPT — estender agente de conectividade para Shopee e Amazon

Cole no Cursor dentro de `Robo-Markplaces`.

Crie a branch `feature/conectividade-shopee-amazon` antes de começar.

---

## CONTEXTO

`agentes/conectividade_marketplaces.py` hoje cobre só ML e Magalu.
Shopee e Amazon já têm `probe_conexao()` nos clients mas não entram no
agente nem no workflow horário.

---

## PASSOS

1. **`agentes/conectividade_marketplaces.py`**
   - Incluir `"shopee"` e `"amazon"` em `_MARKETPLACES`
   - Em `_probe()`, importar `probe_conexao` dos clients correspondentes

2. **`core/datadog_logger.py`**
   - Entrada `conectividade_marketplaces` já existe — confirmar teste-guarda

3. **`.github/workflows/conectividade_marketplaces.yml`**
   - Adicionar secrets `SHOPEE_*` e `AMAZON_*` no bloco `env`
   - Renomear workflow para refletir 4 marketplaces (opcional, cosmético)

4. **`tests/test_conectividade_marketplaces.py`**
   - Testes para shopee/amazon ok e falha (mock de `probe_conexao`)
   - `executar()` deve agregar 4 resultados

5. **`api/app.py`** (opcional)
   - Atualizar docstring do endpoint `/marketplaces/conectividade/testar`

---

## VALIDAR

```bash
ruff check .
py -m pytest tests/test_conectividade_marketplaces.py tests -q --no-cov
py -c "from agentes.conectividade_marketplaces import executar; import pprint; pprint.pprint(executar())"
```

Sem credenciais locais, shopee/amazon podem reportar `ok: False` — esperado.
