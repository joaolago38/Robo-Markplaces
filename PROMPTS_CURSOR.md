# Tarefa: logar o corpo da resposta no erro de renovação do Magalu (diagnóstico)

## Contexto
A renovação do token do Magalu está falhando com `400 Bad Request` no endpoint `https://id.magalu.com/oauth/token`. O problema: o código atual loga apenas o **status** do erro, não o **corpo** da resposta — e é o corpo que diz o motivo real (`invalid_grant`, `invalid_client`, `invalid_request`, etc.). Sem o corpo, não dá para saber a causa.

Arquivo: `core/token_manager.py`, função `_renovar_token_magalu()` (por volta das linhas 367-416).

Hoje o final da função é assim (resumido):
```python
    try:
        r = request("POST", "https://id.magalu.com/oauth/token", data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=25)
        r.raise_for_status()
        tokens = r.json()
        ...
    except Exception as e:
        logger.error("Erro ao renovar token Magazine Luiza: %s", e)
        return None
```

O `raise_for_status()` levanta o erro sem o corpo, e o `except` loga só `e` (ex.: "400 Client Error: Bad Request").

## O que fazer

Em `_renovar_token_magalu()`, **antes** de `raise_for_status()`, trate o caso de status de erro logando status + corpo (truncado para não poluir o log), e retorne `None`. Mantenha o `try/except` externo para erros de rede (onde `r` pode não existir). Exemplo do que se espera:

```python
    try:
        r = request("POST", "https://id.magalu.com/oauth/token", data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=25)
        if r.status_code >= 400:
            logger.error("Erro ao renovar token Magazine Luiza: HTTP %s — %s",
                         r.status_code, r.text[:500])
            return None
        tokens = r.json()
        ...  # resto igual (access_token, expires_in, novo_refresh, caches, etc.)
    except Exception as e:
        logger.error("Erro ao renovar token Magazine Luiza (rede/parse): %s", e)
        return None
```

Pontos importantes:
- NÃO alterar o contrato da função: continua retornando `None` em falha e o `access_token` em sucesso.
- NÃO mudar o corpo da requisição, a URL, os headers nem o grant_type.
- Truncar o corpo (`r.text[:500]`) para evitar log gigante.
- Manter todo o resto da função idêntico (parse do access_token, expires_in, rotação do refresh, caches `_token_cache_magalu` / `_magalu_refresh_efetivo`, atribuições em `cfg`).

## Opcional (melhora um rótulo enganoso)
No `scripts/renovar_tokens.py`, no resumo que imprime `"{nome}: sem credenciais — ignorado"` para os resultados de `renovar_todos_tokens()`: hoje qualquer `ok=False` vira "sem credenciais", mesmo quando as credenciais existem e a renovação é que falhou (foi o que aconteceu com o Magalu). Se for simples, distinga os dois casos: quando há credenciais mas `ok=False`, imprimir algo como `"{nome}: falhou na renovação — ver erro acima"` em vez de "sem credenciais". Se exigir refatoração grande, pode pular esta parte.

## NÃO fazer
- Não tocar nas funções de Bling, ML, Shopee, Meta nesta tarefa (foco no Magalu).
- Não logar as credenciais (client_secret, tokens) — apenas status e corpo da resposta do servidor.
- Não commitar `.env`.

## Entregar
A função `_renovar_token_magalu()` ajustada, e (se fez a parte opcional) o ajuste do rótulo no `renovar_tokens.py`.