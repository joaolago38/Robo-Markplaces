# Prompt para o Cursor — Resolver de forma definitiva o erro 400/401 do Bling

Cole no Cursor (Agent). Peça: **"Aplique o patch, rode o debug e me mostre a saída completa. NÃO tente adivinhar a causa — use o que o debug retornar."**

> Diagnóstico do log: TODA renovação cai em `400` no `/oauth/token`, então o
> `buscar_produto` dá `401` em loop. O código está correto (tenta renovar no 401);
> o Bling é que recusa a renovação. Causa = uma de duas:
> (a) `invalid_grant` → refresh_token queimado/expirado → precisa re-bootstrap;
> (b) `invalid_client` → client_id/secret errado ou malformado (o `.env.exemplo`
> tinha `BLING_CLIENT_SECRET=."ae4b6c…"` com ponto e aspas). **Se for (b),
> re-bootstrap NÃO resolve** — o `pegar_token_bling.py` usa o mesmo secret.
> Hoje o log esconde qual é. Este prompt revela e direciona o conserto.

---

## Prompt

### Título: Diagnóstico definitivo do 400 do Bling (revelar causa + rodar debug)

**Prompt:**
```
PARTE 1 — Tornar o erro do refresh legível em core/token_manager.py

1a) Se NÃO existir, adicione esta função logo ANTES de "def _renovar_token_bling():":

def _dica_erro_refresh_bling(status: int, detalhe: str) -> None:
    d = (detalhe or "").lower()
    if "invalid_grant" in d or "expired" in d or "revoked" in d:
        logger.error("→ refresh_token invalido/expirado/ja usado. Re-bootstrap com pegar_token_bling.py e atualize BLING_ACCESS_TOKEN e BLING_REFRESH_TOKEN.")
    elif "invalid_client" in d or "client" in d or status in (401, 403):
        logger.error("→ client_id/client_secret incorretos. Confira BLING_CLIENT_ID e BLING_CLIENT_SECRET (sem ponto, sem aspas, sem espaco).")
    elif status == 400:
        logger.error("→ HTTP 400 no /oauth/token: quase sempre refresh_token consumido/expirado OU BLING_CLIENT_SECRET ausente/errado.")

1b) Dentro de _renovar_token_bling, substitua ESTE trecho:

            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            timeout=25,
        )
        r.raise_for_status()
        tokens = r.json()

POR este:

            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            timeout=25,
        )

        if r.status_code != 200:
            detalhe = ""
            try:
                corpo = r.json()
                detalhe = corpo.get("error_description") or corpo.get("error") or ""
                if isinstance(detalhe, dict):
                    detalhe = detalhe.get("description") or detalhe.get("message") or str(detalhe)
            except Exception:
                detalhe = (getattr(r, "text", "") or "")[:300]
            logger.error("Bling refresh falhou (HTTP %s): %s", r.status_code, detalhe)
            _dica_erro_refresh_bling(r.status_code, str(detalhe))
            return None

        tokens = r.json()

NÃO altere o resto da função.

PARTE 2 — Rodar o diagnóstico que já existe e MOSTRAR a saída

Rode (com as variáveis BLING_* no ambiente/.env) e me mostre a saída COMPLETA,
especialmente a seção [1] (sanidade das credenciais) e a [3] (veredito):

    python scripts/debug_bling_refresh.py

PARTE 3 — Verificação rápida
    ruff check api agentes core integracoes tests   (deve dar All checks passed!)
    python -m unittest discover -s tests -p "test_*.py"   (tudo OK)

NÃO faça mais nada além disso. Não rode cadastro de NCM nem nada que dependa do Bling
até o token voltar. Me devolva a saída do debug para decidirmos o conserto.
```

**Contexto:**
- Arquivos: `core/token_manager.py`; script já existente `scripts/debug_bling_refresh.py`.
- Log: `Erro ao renovar token Bling: 400 Client Error: Bad Request` em loop → `buscar_produto` 401.

**Resultado esperado:**
- O log do refresh passa a mostrar `Bling refresh falhou (HTTP 400): <motivo>` + a linha `→ ...`.
- O `debug_bling_refresh.py` imprime o veredito: `invalid_grant` ou `invalid_client` (e flags de defeito no secret).

**Status:** ⬜ a fazer

---

## Decisão do conserto (com base no veredito do debug)

**Caso A — `invalid_client`, ou a seção [1] acusar ponto/aspas/tamanho errado no secret:**
O problema é o `BLING_CLIENT_SECRET` (provável herança do `.env.exemplo` malformado).
1. Corrija o Secret `BLING_CLIENT_SECRET` no GitHub (e no `.env` local): só os caracteres
   do secret — sem `.`, sem aspas, sem espaço. Mesmo para `BLING_CLIENT_ID`.
2. Se desconfiar que o secret vazou/está errado, **rotacione** o Client Secret no painel do Bling.
3. Só então faça o re-bootstrap (passo abaixo).

**Caso B — `invalid_grant`:**
O refresh_token está queimado. Faça o re-bootstrap:
1. Abra no navegador (logado na conta Bling) e autorize:
   `https://www.bling.com.br/Api/v3/oauth/authorize?response_type=code&client_id=SEU_CLIENT_ID&redirect_uri=https%3A%2F%2Fgoogle.com&state=robo`
2. Copie o `code` da URL de retorno (expira em ~60s) e rode na hora:
   `python pegar_token_bling.py SEU_CODE`
3. Atualize os Secrets `BLING_ACCESS_TOKEN` e `BLING_REFRESH_TOKEN` com os valores impressos.

**Para NÃO voltar a quebrar (anti-recorrência):**
- No Actions, o write-back deve gravar o refresh_token rotacionado de volta nos Secrets
  (já implementado em `renovar_tokens.py` + `GH_REPO` no workflow). Confirme que está ativo.
- Em máquina persistente, defina `BLING_TOKEN_STORE=dados/bling_token.json` para persistir
  a rotação em disco.

> Observação honesta: este loop NÃO se resolve só com código — o código já reage certo
> ao 401. O que falta é uma credencial válida. O patch acima serve para parar de adivinhar
> e atacar a causa certa de primeira.