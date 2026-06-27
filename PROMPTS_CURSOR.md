Confira se as 4 correções abaixo (já entregues antes em
PROMPT_CORRECAO_PONTOS_CEGOS.md) estão de fato aplicadas no repositório
atual. Para cada uma: se já estiver aplicada, não faça nada e me confirme
o "ok". Se não estiver (ou estiver parcial), aplique agora, literalmente,
sem reinterpretar a lógica. No final, rode os testes/lint e me dê um
checklist de status de cada item — e IMPORTANTE: commite as mudanças e
gere o zip/export final a partir da pasta de trabalho ATUAL (não de um
branch ou pasta antiga), porque o último export que recebi veio idêntico
ao original, sem nenhuma das correções.

═══════════════════════════════════════════════════════════════
COMO VERIFICAR (rode antes de qualquer alteração)
═══════════════════════════════════════════════════════════════

```bash
echo "--- Correção 1 (cofre/sync ML) ---"
grep -n "_ml_store_path\|ML_TOKEN_STORE\|_salvar_store_ml\|_hidratar_cache_ml_do_store" core/token_manager.py

echo "--- Correção 2 (retry 401 padronizado no ML) ---"
grep -n "request(" integracoes/ml/ml_client.py | grep -v "_request_ml\|def _request_ml\|import"

echo "--- Correção 3 (kill switch em atualizar_preco_item) ---"
grep -n -A3 "def atualizar_preco_item" integracoes/ml/ml_client.py integracoes/shopee/shopee_client.py integracoes/magalu/magalu_client.py integracoes/amazon/amazon_client.py

echo "--- Correção 4 (NfeVerificacaoIndisponivel) ---"
grep -rn "NfeVerificacaoIndisponivel" integracoes/bling/bling_client.py agentes/faturamento/agente_faturamento.py
```

Interprete assim:
- Correção 1: ok se o `grep` devolver as 4 funções.
- Correção 2: ok se o `grep` devolver VAZIO (ou seja, nenhuma chamada
  `request(` direta sobrou fora de `_request_ml`/import).
- Correção 3: ok se as 4 funções `atualizar_preco_item` mostrarem
  `bloqueio_escrita_global` nas linhas seguintes ao `def`.
- Correção 4: ok se o `grep` devolver ocorrências nos dois arquivos.

Se qualquer um vier vazio/incompleto, aplique o item correspondente abaixo.

═══════════════════════════════════════════════════════════════
CORREÇÃO 1 — core/token_manager.py
═══════════════════════════════════════════════════════════════

Adicionar (se ainda não existir) depois de `_ml_refresh_disponivel()` e
antes de `_renovar_token_ml`:

```python
def _ml_store_path() -> Path | None:
    """
    Cofre do token ML em disco, opcional (ativo só quando ML_TOKEN_STORE
    está definido). Resolve o caso de processos efêmeros (Actions) que
    renovam o token mas não tinham como persistir o refresh_token novo.
        ML_TOKEN_STORE=dados/ml_token.json
    """
    p = (os.getenv("ML_TOKEN_STORE") or "").strip()
    return Path(p) if p else None


def _carregar_store_ml() -> dict:
    p = _ml_store_path()
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error("Falha ao ler store ML (%s): %s", p, e)
        return {}


def _salvar_store_ml(access_token: str, refresh_token: str | None, expires_at: float) -> None:
    p = _ml_store_path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at,
                    "atualizado_em": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        logger.info("Tokens ML persistidos em %s", p)
    except Exception as e:
        logger.error("Falha ao gravar store ML (%s): %s", p, e)


def _hidratar_cache_ml_do_store() -> None:
    """Na partida de um processo novo, usa o token/refresh do disco em vez do .env estático."""
    if _token_cache_ml["access_token"] is None:
        store = _carregar_store_ml()
        if store.get("access_token"):
            _token_cache_ml["access_token"] = store["access_token"]
            _token_cache_ml["expires_at"] = store.get("expires_at", 0)
        if store.get("refresh_token"):
            _ml_refresh_efetivo["valor"] = store["refresh_token"]
```

Trocar `_ml_refresh_disponivel()`:

```python
def _ml_refresh_disponivel() -> str | None:
    """Prioriza o refresh_token rotacionado (em memória) sobre o do .env/secret."""
    if _ml_refresh_efetivo["valor"] is None:
        _ml_refresh_efetivo["valor"] = (cfg.ML_REFRESH_TOKEN or "").strip() or None
    return _ml_refresh_efetivo["valor"]
```

por:

```python
def _ml_refresh_disponivel() -> str | None:
    """Prioridade: refresh_token rotacionado em memória > disco (ML_TOKEN_STORE) > .env/secret."""
    if _ml_refresh_efetivo["valor"] is None:
        _hidratar_cache_ml_do_store()
    if _ml_refresh_efetivo["valor"] is None:
        _ml_refresh_efetivo["valor"] = (cfg.ML_REFRESH_TOKEN or "").strip() or None
    return _ml_refresh_efetivo["valor"]
```

Em `_renovar_token_ml()`, trocar:

```python
        if novo_refresh:
            _ml_refresh_efetivo["valor"] = novo_refresh
            cfg.ML_REFRESH_TOKEN = novo_refresh

        logger.info("Token ML renovado com sucesso")

        return access_token
```

por:

```python
        if novo_refresh:
            _ml_refresh_efetivo["valor"] = novo_refresh
            cfg.ML_REFRESH_TOKEN = novo_refresh

        cfg.ML_ACCESS_TOKEN = access_token

        _salvar_store_ml(
            access_token,
            novo_refresh or refresh,
            _token_cache_ml["expires_at"],
        )

        if os.getenv("GITHUB_ACTIONS") == "true":
            if sync_secrets_github(access_token, novo_refresh or refresh, prefix="ML"):
                logger.info("Secrets ML_* sincronizados no GitHub (rotação automática).")
            else:
                logger.warning(
                    "Falha ao sincronizar ML_* no GitHub após rotação — "
                    "a próxima renovação pode falhar até o sync funcionar."
                )

        logger.info("Token ML renovado com sucesso")

        return access_token
```

Trocar `get_token_ml()`:

```python
def get_token_ml():
    now = time.time()

    if _token_cache_ml["access_token"] and now < _token_cache_ml["expires_at"]:
        return _token_cache_ml["access_token"]

    return _renovar_token_ml()
```

por:

```python
def get_token_ml(forcar: bool = False):
    now = time.time()

    _hidratar_cache_ml_do_store()

    if not forcar:
        if _token_cache_ml["access_token"] and now < _token_cache_ml["expires_at"]:
            return _token_cache_ml["access_token"]

    return _renovar_token_ml()
```

Nos workflows que rodam código do ML (`monitor_ml.yml`,
`monitor_concorrentes_ml.yml`, `ads_gatilho_ml.yml`, `panorama.yml`,
`operacao_24h_seguranca.yml`, `agente_principal.yml`), garantir no step
que executa o agente:

```yaml
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          GH_REPO: ${{ github.repository }}
```

═══════════════════════════════════════════════════════════════
CORREÇÃO 2 — integracoes/ml/ml_client.py
═══════════════════════════════════════════════════════════════

Trocar toda chamada `request("MÉTODO", url, headers=_h(), ...)` por
`_request_ml("MÉTODO", url, ...)` (sem `headers=_h()` manual) nestas
funções: `atualizar_preco_item`, `atualizar_estoque_item`,
`listar_pedidos`, `buscar_metricas_item` (as 3 chamadas),
`_listar_linhas_concorrentes_catalogo` (as 2 chamadas),
`listar_perguntas_nao_respondidas`, `responder_pergunta`,
`buscar_reputacao_vendedor`.

NÃO alterar `probe_conexao` (diagnóstico intencional) nem
`buscar_concorrentes_por_termo` (busca pública sem autenticação).

═══════════════════════════════════════════════════════════════
CORREÇÃO 3 — kill switch em atualizar_preco_item (4 marketplaces)
═══════════════════════════════════════════════════════════════

Em `integracoes/ml/ml_client.py`, `integracoes/shopee/shopee_client.py`,
`integracoes/magalu/magalu_client.py` e `integracoes/amazon/amazon_client.py`,
adicionar no INÍCIO de `atualizar_preco_item` (mesmo padrão já usado em
`atualizar_estoque_item` de cada cliente):

```python
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("<NOME_MARKETPLACE> atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
```//substituir <NOME_MARKETPLACE> por ML / Shopee / Magalu / Amazon em cada arquivo

═══════════════════════════════════════════════════════════════
CORREÇÃO 4 — Bling: não tratar erro de verificação como "não existe"
═══════════════════════════════════════════════════════════════

Em `integracoes/bling/bling_client.py`, adicionar antes do `logger =`:

```python
class NfeVerificacaoIndisponivel(Exception):
    """Levantada quando não foi possível confirmar se já existe NF-e para o pedido."""
```

Em `buscar_nfe_por_pedido`, trocar o `except Exception` final (o que loga
e devolve `None`) para levantar essa exceção em vez de retornar `None`:

```python
    except Exception as exc:
        logger.error("Bling buscar_nfe_por_pedido erro pedido=%s: %s", pedido_ref, exc)
        raise NfeVerificacaoIndisponivel(
            f"não foi possível confirmar duplicidade de NF-e para pedido {pedido_ref}: {exc}"
        ) from exc
```

Em `agentes/faturamento/agente_faturamento.py`, importar
`NfeVerificacaoIndisponivel` e, em `emitir_nfe_pedido`, envolver a chamada
a `buscar_nfe_por_pedido(pedido_id)` em try/except, abortando a emissão
(com `alertar_critico`) em vez de seguir para `criar_nfe` quando a
exceção for levantada.

═══════════════════════════════════════════════════════════════
DEPOIS DE APLICAR — checklist final obrigatório
═══════════════════════════════════════════════════════════════

1. Rode de novo os 4 comandos de verificação do topo e confirme que
   agora todos retornam "ok" pelos critérios descritos.
2. Rode `pytest -q` e `ruff check .` — cole o resultado.
3. Rode `git status` e `git diff --stat` para eu ver exatamente quais
   arquivos mudaram.
4. Confirme explicitamente: "estou gerando o zip/export a partir do
   diretório de trabalho atual, com as mudanças acima já salvas em
   disco" — não a partir de um commit antigo, branch separado ou cache.
5. Devolva um checklist final no formato:
   - [ ] Correção 1 (cofre/sync token ML) — aplicada e verificada
   - [ ] Correção 2 (retry 401 padronizado) — aplicada e verificada
   - [ ] Correção 3 (kill switch em atualizar_preco_item) — aplicada e verificada
   - [ ] Correção 4 (NfeVerificacaoIndisponivel) — aplicada e verificada
   - [ ] pytest passando
   - [ ] ruff sem erros
   - [ ] zip/export gerado a partir do estado atual do código