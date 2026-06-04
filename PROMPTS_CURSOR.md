# Prompt para o Cursor — Resolver os erros do CI (teste que quebra o Actions + bug do diagnóstico)

Cole no Cursor (Agent). Peça: **"Aplique as correções e rode a verificação simulando o CI. Não altere mais nada."**

> Diagnóstico (já investigado e validado):
> 1. **O CI quebra (exit code 1)** por causa do teste `test_RT09_ignora_marketplace_sem_credencial`.
>    Ele passa LOCAL mas falha no GitHub Actions: no Actions, `GITHUB_ACTIONS=true` faz o
>    `main()` disparar o write-back do token do ML (`gh secret set`); como o `gh` não está
>    autenticado no runner de teste, o sync falha e o `main()` retorna 1 (`1 != 0`).
> 2. **Bug no diagnóstico:** `[3] Dados da empresa — 'list' object has no attribute 'get'`
>    (o endpoint de empresa às vezes devolve lista, e o código chama `.get()` direto).

---

## Prompt

### Título: Corrigir teste sensível ao CI (RT09) + bug 'list' do diagnóstico de empresa

**Prompt:**
```
CORREÇÃO 1 — tests/test_renovar_tokens.py (o que quebra o Actions)

No teste test_RT09_ignora_marketplace_sem_credencial, o dicionário `env` precisa
neutralizar o ambiente de CI, senão o write-back do ML dispara e main() retorna 1.
Substitua o bloco:

        env = {
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
        }

por:

        env = {
            "ML_CLIENT_ID": "cid", "ML_CLIENT_SECRET": "csec", "ML_REFRESH_TOKEN": "ref",
            "SHOPEE_PARTNER_ID": "", "SHOPEE_PARTNER_KEY": "", "SHOPEE_SHOP_ID": "",
            "MAGALU_CLIENT_ID": "", "MAGALU_CLIENT_SECRET": "", "MAGALU_MERCHANT_ID": "",
            # isola o teste do ambiente de CI: sem isto, no GitHub Actions o write-back
            # do ML dispara (gh secret set) e faz main() retornar 1.
            "GITHUB_ACTIONS": "", "BLING_SYNC_GITHUB": "",
        }

CORREÇÃO 2 — scripts/debug_bling_refresh.py (bug 'list' object has no attribute 'get')

Na checagem [3] Dados da empresa, o código chama .get() direto no JSON do endpoint de
empresa, que às vezes vem como LISTA. Torne o parsing robusto a list/dict. Onde hoje há
algo como `dados = resp.json()` seguido de `dados.get(...)`, troque por:

    payload = resp.json()
    if isinstance(payload, dict):
        empresa = payload.get("data", payload)
    elif isinstance(payload, list):
        empresa = payload[0] if payload else {}
    else:
        empresa = {}
    if isinstance(empresa, list):
        empresa = empresa[0] if empresa else {}
    if not isinstance(empresa, dict):
        empresa = {}
    # use sempre `empresa.get(...)` a partir daqui (nome/razaoSocial/cnpj etc.)

VERIFICAÇÃO (rode e mostre a saída):
    # simula o CI — sem isto o problema não aparece localmente:
    GITHUB_ACTIONS=true python -m unittest discover -s tests -p "test_*.py"
    ruff check api agentes core integracoes tests

Os 201 testes devem passar (inclusive sob GITHUB_ACTIONS=true) e o ruff deve ficar limpo.
```

**Contexto:**
- Arquivos: `tests/test_renovar_tokens.py` (RT09) e `scripts/debug_bling_refresh.py` (checagem [3]).
- A falha só aparece no Actions porque depende de `GITHUB_ACTIONS=true`.

**Resultado esperado:**
- `GITHUB_ACTIONS=true python -m unittest discover -s tests -p "test_*.py"` → `OK`, 201 testes.
- `ruff check ...` → All checks passed!
- O Actions deixa de terminar com exit code 1.

**Status:** ⬜ a fazer

---

## Observações honestas

- A **Correção 1** conserta a quebra do CI de forma definitiva (já reproduzi a falha com
  `GITHUB_ACTIONS=true` e confirmei que o patch faz os 201 testes passarem). O teste estava
  exercitando, sem querer, o caminho de write-back; o patch isola o teste do ambiente.
- A **Correção 2** elimina o `'list' object has no attribute 'get'` no diagnóstico.
- O que este prompt **não** resolve (porque não é bug de código): o `400` na renovação do
  Bling continua sendo credencial inválida — siga o `PROMPT_CURSOR_RESOLVER_BLING_400`
  (revelar `invalid_grant` vs `invalid_client`) e, conforme o veredito, re-bootstrap ou
  corrigir o `BLING_CLIENT_SECRET`. E o `[5] Refresh token … ausentes` do diagnóstico indica
  que, no ambiente onde rodou, faltavam `BLING_CLIENT_ID/SECRET/REFRESH_TOKEN` nos Secrets.
- Detalhe menor (não quebra nada): o `ResourceWarning: unclosed file ... ncm.xlsx` é só um
  aviso de arquivo não fechado no teste de NCM; se quiser silenciar, feche o workbook após o
  uso (`wb.close()`), mas não afeta o resultado.