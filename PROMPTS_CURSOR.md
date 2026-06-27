Aplique as 4 correções abaixo no repositório Robo-Markplaces, literalmente,
sem reinterpretar a lógica. São pontos cegos reais encontrados em revisão:
(1) ML pode perder o refresh_token rotacionado entre workflows do GitHub
Actions; (2) algumas funções de escrita do ML não renovam token em 401;
(3) o kill switch ROBO_PAUSAR_ESCRITA não cobre atualizar_preco_item em
nenhum marketplace; (4) o Bling pode emitir NF-e duplicada se a checagem
de duplicidade falhar por erro de rede.

Depois de aplicar, rode `pytest` e `ruff check .` e me avise se algo quebrar.

═══════════════════════════════════════════════════════════════
CORREÇÃO 1 — core/token_manager.py
Persistir/sincronizar o refresh_token do ML do mesmo jeito que já é
feito para o Bling, para que renovações disparadas por QUALQUER
workflow (não só renovar_tokens.yml) não "torrem" o refresh_token.
═══════════════════════════════════════════════════════════════

1a. Adicionar, depois da função `_ml_refresh_disponivel()` (e antes de
`_renovar_token_ml`), as funções de cofre em disco (mesmo padrão de
`_bling_store_path` / `_carregar_store_bling` / `_salvar_store_bling`):

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

1b. Em `_ml_refresh_disponivel()`, hidratar do store ANTES do .env (mesma
prioridade usada no Bling: disco > .env/secret). Trocar:

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

1c. Em `_renovar_token_ml()`, depois do bloco que atualiza
`_ml_refresh_efetivo`/`cfg.ML_REFRESH_TOKEN` e ANTES do `logger.info("Token ML renovado com sucesso")`,
persistir em disco e sincronizar no GitHub (mesmo padrão do Bling). Trocar:

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

        # Persiste em disco (se o cofre estiver ativo) — resolve a rotação fora do Actions.
        _salvar_store_ml(
            access_token,
            novo_refresh or refresh,
            _token_cache_ml["expires_at"],
        )

        # CRÍTICO: o ML invalida o refresh_token a cada uso. Se este renovar
        # rodou fora do renovar_tokens.py (ex.: 401 disparado por monitor_ml.yml),
        # sem este sync o Secret antigo fica órfão e a próxima renovação falha
        # com invalid_grant.
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

1d. Em `get_token_ml()`, hidratar do store antes de checar o cache (mesmo
padrão do Bling). Trocar:

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

1e. Conferir que `core/token_manager.py` já importa `sync_secrets_github`
(já importa — usado pelo Bling). Não precisa adicionar import novo.

1f. Nos workflows `.github/workflows/monitor_ml.yml`,
`monitor_concorrentes_ml.yml`, `ads_gatilho_ml.yml`, `panorama.yml`,
`operacao_24h_seguranca.yml`, `agente_principal.yml` (qualquer workflow
que rode código que chama `ml_client`), adicionar no step que executa
o agente:

```yaml
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          GH_REPO: ${{ github.repository }}
```

(mantendo os envs ML_* já existentes). Sem isso, mesmo com o código
corrigido, o `gh secret set` não vai funcionar dentro desses workflows.

═══════════════════════════════════════════════════════════════
CORREÇÃO 2 — integracoes/ml/ml_client.py
Padronizar TODAS as chamadas autenticadas para usar `_request_ml`
(que já tem o retry automático em 401), em vez de `request(...,
headers=_h())` direto.
═══════════════════════════════════════════════════════════════

Trocar, em cada função abaixo, a chamada `request("MÉTODO", url, headers=_h(), ...)`
por `_request_ml("MÉTODO", url, ...)` (remover o `headers=_h()` manual —
`_request_ml` já injeta o header e faz o retry em 401):

- `atualizar_preco_item` (linha ~254): `request("PUT", ...)` → `_request_ml("PUT", ...)`
- `atualizar_estoque_item` (linha ~279): `request("PUT", ...)` → `_request_ml("PUT", ...)`
- `listar_pedidos` (linha ~306): `request("GET", ...)` → `_request_ml("GET", ...)`
- `buscar_metricas_item` (linhas ~360, ~364, ~374 — as 3 chamadas): `request("GET", ...)` → `_request_ml("GET", ...)`
- `_listar_linhas_concorrentes_catalogo` (linhas ~416, ~423): `request("GET", ...)` → `_request_ml("GET", ...)`
- `listar_perguntas_nao_respondidas` (linha ~181): `request("GET", ...)` → `_request_ml("GET", ...)`
- `responder_pergunta` (linha ~202): `request("POST", ...)` → `_request_ml("POST", ...)`
- `buscar_reputacao_vendedor` (linha ~221): `request("GET", ...)` → `_request_ml("GET", ...)`

Exemplo concreto (`atualizar_preco_item`) — trocar:

```python
        r = request(
            "PUT",
            f"{BASE}/items/{item_id}",
            headers=_h(),
            json={"price": float(novo_preco)},
            timeout=30,
        )
```

por:

```python
        r = _request_ml(
            "PUT",
            f"{BASE}/items/{item_id}",
            json={"price": float(novo_preco)},
            timeout=30,
        )
```

NÃO alterar `probe_conexao` e `buscar_concorrentes_por_termo` — o primeiro
é diagnóstico intencional ("sem mascarar erros HTTP") e o segundo é busca
pública sem autenticação.

═══════════════════════════════════════════════════════════════
CORREÇÃO 3 — kill switch em atualizar_preco_item (todos os marketplaces)
Hoje só atualizar_estoque_item checa ROBO_PAUSAR_ESCRITA. Replicar a mesma
checagem em atualizar_preco_item nos 4 clientes, para que o kill switch
proteja preço mesmo se alguém chamar a função fora do agente de repricing.
═══════════════════════════════════════════════════════════════

3a. integracoes/ml/ml_client.py — em `atualizar_preco_item`, adicionar o
guardrail logo no início (mesmo padrão de `atualizar_estoque_item`):

```python
def atualizar_preco_item(item_id: str, novo_preco: float) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("ML atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
    if not _enabled():
        logger.warning("Mercado Livre não configurado para atualização de preço.")
        return False
    try:
        r = _request_ml(
            "PUT",
            f"{BASE}/items/{item_id}",
            json={"price": float(novo_preco)},
            timeout=30,
        )
        r.raise_for_status()
        logger.info("ML preço atualizado com sucesso item_id=%s novo_preco=%.2f", item_id, float(novo_preco))
        return True
    except Exception as exc:
        logger.error("ML atualizar_preco_item erro item_id=%s: %s", item_id, exc)
        return False
```

3b. integracoes/shopee/shopee_client.py — mesmo padrão em
`atualizar_preco_item`:

```python
def atualizar_preco_item(item_id: int, novo_preco: float, model_id: int | None = None) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Shopee atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
    if not _enabled():
        logger.warning("Shopee não configurado para atualização de preço.")
        return False
    ...
```
(manter o restante do corpo da função igual, só adicionar as 4 linhas do
guardrail antes do `if not _enabled()`)

3c. integracoes/magalu/magalu_client.py — mesmo padrão em
`atualizar_preco_item` (adicionar o guardrail no início, igual ao item 3b).

3d. integracoes/amazon/amazon_client.py — mesmo padrão em
`atualizar_preco_item`:

```python
def atualizar_preco_item(sku: str, novo_preco: float) -> bool:
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        logger.warning("Amazon atualizar_preco_item bloqueado: %s", bloqueio["erro"])
        return False
    if not _enabled():
        logger.warning("Amazon não configurado para atualização de preço.")
        return False
    ...
```

═══════════════════════════════════════════════════════════════
CORREÇÃO 4 — integracoes/bling/bling_client.py + agentes/faturamento/agente_faturamento.py
buscar_nfe_por_pedido não deve devolver "não existe" quando a checagem
falhou por erro de rede/API — isso pode gerar NF-e duplicada (problema
fiscal). Separar os dois casos: "não encontrado" (None) vs "não foi
possível verificar" (exceção dedicada).
═══════════════════════════════════════════════════════════════

4a. No topo de integracoes/bling/bling_client.py, adicionar a exceção
dedicada (depois dos imports, antes de `logger = ...`):

```python
class NfeVerificacaoIndisponivel(Exception):
    """Levantada quando não foi possível confirmar se já existe NF-e para o pedido."""
```

4b. Em `buscar_nfe_por_pedido`, trocar o bloco final de except — hoje ele
loga e retorna `None` (= "não existe"). Trocar:

```python
    except Exception as exc:
        logger.error(
            "Bling buscar_nfe_por_pedido erro pedido=%s: %s",
            pedido_ref,
            exc,
        )
        logger.warning(
            "Checagem de duplicidade NF-e não pôde ser confirmada para pedido %s — "
            "prosseguindo como se não existisse.",
            pedido_ref,
        )
        return None
```

por:

```python
    except Exception as exc:
        logger.error(
            "Bling buscar_nfe_por_pedido erro pedido=%s: %s",
            pedido_ref,
            exc,
        )
        raise NfeVerificacaoIndisponivel(
            f"não foi possível confirmar duplicidade de NF-e para pedido {pedido_ref}: {exc}"
        ) from exc
```

4c. Em agentes/faturamento/agente_faturamento.py, importar a exceção e
tratar no `emitir_nfe_pedido`. Trocar o import:

```python
from integracoes.bling.bling_client import buscar_nfe_por_pedido, buscar_produto, criar_nfe
```

por:

```python
from integracoes.bling.bling_client import (
    NfeVerificacaoIndisponivel,
    buscar_nfe_por_pedido,
    buscar_produto,
    criar_nfe,
)
```

4d. Ainda em `emitir_nfe_pedido`, trocar:

```python
    existente = buscar_nfe_por_pedido(pedido_id)
    if existente:
        logger.info("NF-e já existente para pedido %s — pulando emissão duplicada.", pedido_id)
        return {
            "ok": True,
            "pedido_id": pedido_id,
            "ja_emitida": True,
            "nfe": existente,
        }
```

por:

```python
    try:
        existente = buscar_nfe_por_pedido(pedido_id)
    except NfeVerificacaoIndisponivel as exc:
        msg = f"NF-e NÃO emitida para pedido {pedido_id}: checagem de duplicidade falhou ({exc})"
        alertar_critico(msg)
        return {"ok": False, "erro": msg, "pedido_id": pedido_id}

    if existente:
        logger.info("NF-e já existente para pedido %s — pulando emissão duplicada.", pedido_id)
        return {
            "ok": True,
            "pedido_id": pedido_id,
            "ja_emitida": True,
            "nfe": existente,
        }
```

═══════════════════════════════════════════════════════════════
TESTES — atualizar/criar para cobrir os 4 cenários
═══════════════════════════════════════════════════════════════

- tests/test_token_manager_providers.py: adicionar teste equivalente ao
  já existente para Bling, confirmando que `_renovar_token_ml` chama
  `sync_secrets_github` quando `GITHUB_ACTIONS=true` e persiste em
  `ML_TOKEN_STORE` quando definido.
- tests/test_ml_client.py: adicionar teste garantindo que
  `atualizar_preco_item`, `atualizar_estoque_item`, `listar_pedidos` e
  `buscar_metricas_item` chamam `_request_ml` (e não `request` direto) —
  mockar `_request_ml` e checar que foi chamado.
- tests/test_ml_client.py / test_shopee_client.py / test_magalu_client.py /
  test_amazon_client.py: teste novo garantindo que `atualizar_preco_item`
  retorna `False` e não chama a API quando `ROBO_PAUSAR_ESCRITA=true`.
- tests/test_bling_client.py: teste novo garantindo que
  `buscar_nfe_por_pedido` levanta `NfeVerificacaoIndisponivel` quando a
  request falha (em vez de devolver `None`).
- tests/test_agente_faturamento.py: teste novo garantindo que
  `emitir_nfe_pedido` retorna `{"ok": False, ...}` e NÃO chama `criar_nfe`
  quando `buscar_nfe_por_pedido` levanta `NfeVerificacaoIndisponivel`.

Rode `pytest -q` e `ruff check .` no final e cole o resultado.