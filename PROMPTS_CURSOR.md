# Tarefa: corrigir a renovação de tokens (write-back de refresh_token rotativo) — Robo-Markplaces

## Contexto do repositório (JÁ existe — LEIA antes de mexer, não reescreva do zero)

Projeto Python 3.11. Renovação de tokens fica em:
- `core/token_manager.py` — lógica de renovação por marketplace (Bling, ML, Shopee, Magalu, Meta).
- `scripts/renovar_tokens.py` — CLI orquestrador, roda no GitHub Actions a cada 30 min (`.github/workflows/renovar_tokens.yml`).
- `core/config.py` — lê os segredos do ambiente (`os.getenv`).

Padrões que DEVEM ser mantidos:
- Funções de renovação **nunca lançam exceção** para fora: logam o erro e retornam `None`/`False`/dict com `ok=False`.
- O write-back de Secrets usa a função `_sync_secrets_github(access_token, refresh_token, prefix=...)` que já existe em `scripts/renovar_tokens.py` (usa o `gh secret set` via subprocess).
- Não quebrar os testes existentes em `tests/`. Adicionar testes novos com `subprocess.run` e o HTTP mockados. Lint com `ruff`.

## Diagnóstico (a causa raiz — corrija exatamente isto)

O Bling (e também Shopee/Magalu) **rotacionam o refresh_token a cada renovação**: a resposta traz um refresh_token novo e invalida o antigo. O `token_manager.py` já guarda o novo em memória (`cfg.*_REFRESH_TOKEN` e nos dicts `_*_refresh_efetivo`), mas no GitHub Actions o cofre em disco fica desligado de propósito (`BLING_TOKEN_STORE` não é definido), então a ÚNICA forma de persistir é o write-back nos Secrets.

O furo: em `scripts/renovar_tokens.py`, `_sync_secrets_github(...)` só é chamada para **Meta** e **ML**. O bloco do **Bling** apenas IMPRIME os tokens novos (nunca faz write-back), e **Shopee/Magalu** também não fazem. Consequência: a renovação funciona uma vez, o refresh_token rotaciona, mas o Secret continua com o token antigo (morto) → próxima execução dá `HTTP 400 "Invalid refresh token"`.

A função `_sync_secrets_github` inclusive já tem `prefix="BLING"` como default — o write-back do Bling foi planejado e nunca ligado.

---

## Tarefa 1 — Write-back do Bling no Actions

Em `scripts/renovar_tokens.py`, no bloco `[Bling]`, no ramo de sucesso (`if res_bling.get("ok"):`):
- Manter o comportamento atual de IMPRIMIR os tokens quando **não** estiver no Actions (rodada local/manual).
- Quando estiver no Actions OU `BLING_SYNC_GITHUB` ligado, chamar o write-back em vez de só imprimir, espelhando o que o Meta/ML já fazem:

```python
em_actions = os.getenv("GITHUB_ACTIONS") == "true"
quer_sync = os.getenv("BLING_SYNC_GITHUB", "").strip().lower() in {"1", "true", "yes"}
if em_actions or quer_sync:
    if not _sync_secrets_github(
        res_bling["access_token"],
        res_bling.get("refresh_token"),
        prefix="BLING",
    ):
        exit_code = 1
else:
    # mantém o print atual com os novos valores para colar manualmente
    ...
```

Importante: usar o `refresh_token` que veio em `res_bling` (já rotacionado), NÃO renovar de novo (não consumir o refresh duas vezes).

## Tarefa 2 — Write-back de Shopee e Magalu (mesmo furo)

2a. Em `core/token_manager.py`, adicionar dois acessores espelhando `tokens_ml_atuais()` (que já existe na linha ~95). Eles devem devolver os tokens mais recentes EM MEMÓRIA, sem disparar nova renovação:

```python
def tokens_shopee_atuais() -> dict:
    return {
        "access_token": _token_cache_shopee["access_token"] or cfg.SHOPEE_ACCESS_TOKEN,
        "refresh_token": _shopee_refresh_efetivo["valor"] or cfg.SHOPEE_REFRESH_TOKEN,
    }

def tokens_magalu_atuais() -> dict:
    return {
        "access_token": _token_cache_magalu["access_token"] or cfg.MAGALU_ACCESS_TOKEN,
        "refresh_token": _magalu_refresh_efetivo["valor"] or cfg.MAGALU_REFRESH_TOKEN,
    }
```

2b. Em `scripts/renovar_tokens.py`, no bloco que processa `renovar_todos_tokens()`, depois do write-back do ML, adicionar o mesmo para Shopee e Magalu — somente quando o resultado for `ok`, houver credenciais (`tem_shopee`/`tem_magalu`) e (`em_actions or quer_sync`):

```python
shopee_ok = resultados.get("shopee", {}).get("ok")
if shopee_ok and tem_shopee and (em_actions or quer_sync):
    from core.token_manager import tokens_shopee_atuais
    tk = tokens_shopee_atuais()
    if not _sync_secrets_github(tk["access_token"], tk["refresh_token"], prefix="SHOPEE"):
        exit_code = 1

magalu_ok = resultados.get("magalu", {}).get("ok")
if magalu_ok and tem_magalu and (em_actions or quer_sync):
    from core.token_manager import tokens_magalu_atuais
    tk = tokens_magalu_atuais()
    if not _sync_secrets_github(tk["access_token"], tk["refresh_token"], prefix="MAGALU"):
        exit_code = 1
```

(Confirme as chaves exatas que `renovar_todos_tokens()` usa no dict de resultados — `"shopee"`, `"magalu"`, `"mercadolivre"` — e ajuste se necessário.)

## Tarefa 3 — `.strip()` nas credenciais em `core/config.py`

Hoje `BLING_CLIENT_ID/SECRET/ACCESS_TOKEN/REFRESH_TOKEN` (linhas ~38-41) são lidos com `os.getenv(..., "")` SEM `.strip()`. Um espaço ou `\n` colado no Secret gera `Basic` auth errado → `400 invalid_client`, idêntico a token expirado e difícil de diagnosticar. Adicionar `.strip()` na leitura de TODAS as credenciais (Bling, ML, Shopee, Magalu, Meta) para padronizar:

```python
BLING_CLIENT_ID     = os.getenv("BLING_CLIENT_ID", "").strip()
BLING_CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "").strip()
BLING_ACCESS_TOKEN  = os.getenv("BLING_ACCESS_TOKEN", "").strip()
BLING_REFRESH_TOKEN = os.getenv("BLING_REFRESH_TOKEN", "").strip()
# ... mesma coisa para ML_*, SHOPEE_*, MAGALU_*, META_*
```

## Tarefa 4 — Workflow

Em `.github/workflows/renovar_tokens.yml`:
- O write-back exige que `GH_TOKEN` seja um **PAT com escopo `secrets: write`** (o `GITHUB_TOKEN` padrão NÃO grava Secret). O workflow já passa `secrets.GH_TOKEN` — apenas adicione um comentário avisando do escopo necessário. Não invente token novo.
- Atualizar o `name:` do job para incluir Bling (cosmético: "Renovar Bling / ML / Shopee / Magalu / Meta").
- NÃO alterar o cron.

## Testes

- Adicionar testes em `tests/test_renovar_tokens.py` (e onde fizer sentido) que mockem `shutil.which("gh")`, `subprocess.run` e a chamada HTTP de renovação, verificando que:
  - quando `GITHUB_ACTIONS=true` e a renovação do Bling dá `ok`, `_sync_secrets_github` é chamada com `prefix="BLING"` e com o refresh_token NOVO;
  - mesma verificação para Shopee (`prefix="SHOPEE"`) e Magalu (`prefix="MAGALU"`);
  - fora do Actions, o Bling apenas imprime e NÃO chama o write-back.
- Garantir que `tokens_shopee_atuais()`/`tokens_magalu_atuais()` não disparam renovação.
- Rodar `ruff check .` e `pytest -q` e deixar tudo verde.

## Entregar

Os arquivos alterados (`scripts/renovar_tokens.py`, `core/token_manager.py`, `core/config.py`, `.github/workflows/renovar_tokens.yml`) + testes novos, com um resumo do que mudou.

---

## Passo manual (NÃO é código — faça você, uma vez, antes de validar)

O `BLING_REFRESH_TOKEN` que está no Secret hoje já está morto (rotacionado-e-perdido ou expirado >30 dias). Re-bootstrap uma vez:
1. Abra no navegador a URL de authorize do `pegar_token_bling.py` (com seu `client_id`) e autorize.
2. Copie o `code` da URL de retorno (expira em ~60s) e rode IMEDIATAMENTE: `python pegar_token_bling.py SEU_CODE`.
3. Cole `BLING_ACCESS_TOKEN` e `BLING_REFRESH_TOKEN` novos nos GitHub Secrets.

Depois disso, com o write-back ligado, a renovação automática passa a se sustentar sozinha.