Implemente os 3 itens abaixo, na ordem, literalmente. Antes de começar,
crie uma branch isolada (`fix/tokens-amazon-shopee-magalu`). Se algum
trecho "trocar X por Y" não bater exatamente com o arquivo atual, PARE e
me mostre o trecho real antes de aplicar — não tente adivinhar onde
encaixar. Ao final, é obrigatório manter cobertura de testes em **90%
ou mais** (hoje o `pyproject.toml` exige 80% — aumente para 90% e
garanta que o código novo tenha teste suficiente pra não furar isso).

═══════════════════════════════════════════════════════════════
ITEM 1 — Amazon: criar renovação automática de token (LWA)
Hoje `amazon_client.py` só lê AMAZON_ACCESS_TOKEN estático do .env —
sem isso o token expira em ~1h e exige troca manual sempre.
═══════════════════════════════════════════════════════════════

1a. Em core/token_manager.py, adicionar (perto das outras seções de
provider, ex.: depois da seção Magalu) o cache e a função de renovação,
seguindo o MESMO padrão usado em `_renovar_token_magalu`/`get_token_magalu`,
mas usando o endpoint LWA da Amazon:

```python
_token_cache_amazon = {"access_token": None, "expires_at": 0}
_amazon_refresh_efetivo = {"valor": None}


def _amazon_refresh_disponivel() -> str | None:
    if _amazon_refresh_efetivo["valor"] is None:
        _amazon_refresh_efetivo["valor"] = (cfg.AMAZON_REFRESH_TOKEN or "").strip() or None
    return _amazon_refresh_efetivo["valor"]


def _renovar_token_amazon():
    refresh = _amazon_refresh_disponivel()
    if not all([cfg.AMAZON_LWA_CLIENT_ID, cfg.AMAZON_LWA_CLIENT_SECRET, refresh]):
        logger.error("Credenciais Amazon (LWA) ausentes para renovação de token.")
        return None

    try:
        r = request(
            "POST",
            "https://api.amazon.com/auth/o2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": cfg.AMAZON_LWA_CLIENT_ID,
                "client_secret": cfg.AMAZON_LWA_CLIENT_SECRET,
            },
            timeout=20,
        )
        r.raise_for_status()
        body = r.json() or {}

        access_token = body.get("access_token")
        if not access_token:
            logger.error("Amazon refresh sem access_token na resposta.")
            return None

        expires_in = int(body.get("expires_in") or 3600)
        novo_refresh = body.get("refresh_token")  # LWA normalmente não rotaciona, mas trata se vier

        _token_cache_amazon["access_token"] = access_token
        _token_cache_amazon["expires_at"] = time.time() + max(60, expires_in) - 60

        if novo_refresh:
            _amazon_refresh_efetivo["valor"] = novo_refresh
            cfg.AMAZON_REFRESH_TOKEN = novo_refresh

        cfg.AMAZON_ACCESS_TOKEN = access_token

        if os.getenv("GITHUB_ACTIONS") == "true":
            if sync_secrets_github(access_token, novo_refresh or refresh, prefix="AMAZON"):
                logger.info("Secrets AMAZON_* sincronizados no GitHub (rotação automática).")
            else:
                logger.warning("Falha ao sincronizar AMAZON_* no GitHub após renovação.")

        logger.info("Token Amazon renovado com sucesso")
        return access_token

    except Exception as e:
        logger.error("Erro ao renovar token Amazon: %s", e)
        return None


def get_token_amazon():
    if not _amazon_refresh_disponivel():
        return cfg.AMAZON_ACCESS_TOKEN or None

    now = time.time()

    if _token_cache_amazon["access_token"] and now < _token_cache_amazon["expires_at"]:
        return _token_cache_amazon["access_token"]

    novo = _renovar_token_amazon()
    return novo or cfg.AMAZON_ACCESS_TOKEN or None
```

1b. Em integracoes/amazon/amazon_client.py, trocar o import e a função
`_h()` para usar a renovação automática (mesmo padrão do `magalu_client.py`).
Trocar:

```python
from core.config import AMAZON_ACCESS_TOKEN, AMAZON_MARKETPLACE_ID
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("amazon_client")
BASE = "https://sellingpartnerapi-na.amazon.com"


def _enabled() -> bool:
    return bool(AMAZON_ACCESS_TOKEN)


def _h():
    return {
        "x-amz-access-token": AMAZON_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
```

por:

```python
from core.config import AMAZON_ACCESS_TOKEN, AMAZON_MARKETPLACE_ID, AMAZON_REFRESH_TOKEN
from core.http_client import request
from core.http_errors import log_http_erro_listagem, status_http
from core.token_manager import get_token_amazon
from core.marketplace_keepalive import registrar_acesso, dias_sem_acesso

logger = logging.getLogger("amazon_client")
BASE = "https://sellingpartnerapi-na.amazon.com"


def _enabled() -> bool:
    return bool(AMAZON_ACCESS_TOKEN or AMAZON_REFRESH_TOKEN)


def _h():
    tok = AMAZON_ACCESS_TOKEN
    if AMAZON_REFRESH_TOKEN:
        tok = get_token_amazon() or AMAZON_ACCESS_TOKEN
    return {
        "x-amz-access-token": tok,
        "Content-Type": "application/json",
    }
```

Mantém retrocompatibilidade: quem só tiver AMAZON_ACCESS_TOKEN estático
continua funcionando igual a hoje; quem configurar AMAZON_REFRESH_TOKEN
passa a ter renovação automática.

═══════════════════════════════════════════════════════════════
ITEM 2 — Shopee: criar script de obtenção inicial do token
Hoje existe pegar_token_ml.py, pegar_token_bling.py, pegar_token_magalu.py
e pegar_token_amazon.py — mas NÃO existe pegar_token_shopee.py.
═══════════════════════════════════════════════════════════════

Criar `pegar_token_shopee.py` na raiz do projeto (mesmo nível dos outros
`pegar_token_*.py`), com este conteúdo:

```python
"""
pegar_token_shopee.py
Bootstrap inicial do OAuth2 da Shopee Open Platform: gera a URL de
autorização, e depois troca o "code" + "shop_id" do redirect pelo
primeiro access_token + refresh_token.

Credenciais vêm de variáveis de ambiente / .env (NUNCA hardcoded):
    SHOPEE_PARTNER_ID, SHOPEE_PARTNER_KEY
    SHOPEE_REDIRECT_URI   (opcional; default https://www.google.com)

Como usar:
    1) Rode sem argumentos para gerar a URL de autorização:
           python pegar_token_shopee.py
       Abra a URL impressa, faça login como o vendedor e autorize o app.
    2) A Shopee redireciona para a Redirect URI com ?code=XXXX&shop_id=YYYY
       na query string. Copie os dois valores. ATENÇÃO: o code expira
       em poucos minutos.
    3) Rode IMEDIATAMENTE passando os dois valores:
           python pegar_token_shopee.py SEU_CODE SEU_SHOP_ID
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
import urllib.parse

import requests

HOST = "https://partner.shopeemobile.com"


def _carregar_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


_carregar_dotenv()

PARTNER_ID = os.getenv("SHOPEE_PARTNER_ID", "").strip()
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
REDIRECT_URI = os.getenv("SHOPEE_REDIRECT_URI", "https://www.google.com").strip()


def _assinar(path: str, timestamp: int) -> str:
    base = f"{PARTNER_ID}{path}{timestamp}"
    return hmac.new(PARTNER_KEY.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


def gerar_url_autorizacao() -> str:
    path = "/api/v2/shop/auth_partner"
    ts = int(time.time())
    sign = _assinar(path, ts)
    qs = urllib.parse.urlencode(
        {
            "partner_id": int(PARTNER_ID),
            "timestamp": ts,
            "sign": sign,
            "redirect": REDIRECT_URI,
        }
    )
    return f"{HOST}{path}?{qs}"


def trocar_code_por_token(code: str, shop_id: str) -> tuple[requests.Response, dict]:
    path = "/api/v2/auth/token/get"
    ts = int(time.time())
    sign = _assinar(path, ts)
    qs = urllib.parse.urlencode({"partner_id": int(PARTNER_ID), "timestamp": ts, "sign": sign})

    resp = requests.post(
        f"{HOST}{path}?{qs}",
        json={"code": code, "shop_id": int(shop_id), "partner_id": int(PARTNER_ID)},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    try:
        dados = resp.json()
    except ValueError:
        dados = {}
    return resp, dados


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not PARTNER_ID or not PARTNER_KEY:
        print("Defina SHOPEE_PARTNER_ID e SHOPEE_PARTNER_KEY no .env / ambiente.")
        return 1

    if len(args) < 2:
        print("Nenhum code/shop_id informado. Abra esta URL, autorize o app, e copie")
        print("'code' e 'shop_id' da URL de retorno:\n")
        print(gerar_url_autorizacao())
        print("\nDepois rode: python pegar_token_shopee.py SEU_CODE SEU_SHOP_ID")
        return 0

    code, shop_id = args[0].strip(), args[1].strip()

    print("Enviando requisicao para a Shopee...")
    resp, dados = trocar_code_por_token(code, shop_id)
    print(f"Status: {resp.status_code}")

    if dados.get("access_token"):
        print("=" * 60)
        print("SUCESSO! Copie para o GitHub Secrets:")
        print("=" * 60)
        print(f"SHOPEE_SHOP_ID:       {shop_id}")
        print(f"SHOPEE_ACCESS_TOKEN:  {dados['access_token']}")
        print(f"SHOPEE_REFRESH_TOKEN: {dados.get('refresh_token', '')}")
        print(f"Expira em:            {int(dados.get('expire_in', 0)) // 3600}h")
        print("=" * 60)
        return 0

    print("ERRO:", dados.get("message") or dados)
    print("Dica: o code expira rápido — gere uma nova URL e refaça o fluxo.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Adicionar uma seção curta no README (mesmo padrão da seção do Bling/ML)
explicando esses 3 passos, perto de onde o Shopee já é mencionado.

═══════════════════════════════════════════════════════════════
ITEM 3 — Replicar o cofre em disco + sync GitHub (já existe no ML/Bling)
para Shopee e Magalu
═══════════════════════════════════════════════════════════════

Para CADA provider (Shopee e Magalu), seguir o mesmo padrão já usado em
`_salvar_store_bling`/`_carregar_store_bling`/`_hidratar_cache_bling_do_store`
(e replicado no ML): variável de ambiente `SHOPEE_TOKEN_STORE` e
`MAGALU_TOKEN_STORE`, funções de leitura/escrita em disco, hidratação no
início de `get_token_shopee`/`get_token_magalu`, e persistência dentro de
`_renovar_token_shopee`/`_renovar_token_magalu` (logo após atualizar o
cache em memória, no mesmo ponto onde hoje só atualiza `cfg.SHOPEE_*`/
`cfg.MAGALU_*`).

Para reduzir duplicação, criar uma função genérica reaproveitável em vez
de copiar 2x o boilerplate:

```python
def _store_path(env_var: str) -> Path | None:
    p = (os.getenv(env_var) or "").strip()
    return Path(p) if p else None


def _carregar_store(env_var: str) -> dict:
    p = _store_path(env_var)
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error("Falha ao ler store (%s): %s", p, e)
        return {}


def _salvar_store(env_var: str, access_token: str, refresh_token: str | None, expires_at: float) -> None:
    p = _store_path(env_var)
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
    except Exception as e:
        logger.error("Falha ao gravar store (%s): %s", p, e)
```

E usar essas funções genéricas dentro de `_shopee_refresh_disponivel`
(hidratar de `_carregar_store("SHOPEE_TOKEN_STORE")` antes do `.env`,
igual já foi feito pro ML em `_ml_refresh_disponivel`), de
`_renovar_token_shopee` (chamar `_salvar_store("SHOPEE_TOKEN_STORE", ...)`
+ `sync_secrets_github(..., prefix="SHOPEE")` quando `GITHUB_ACTIONS=true`),
e o equivalente para `_magalu_refresh_disponivel`/`_renovar_token_magalu`
com `MAGALU_TOKEN_STORE`/`prefix="MAGALU"`.

NÃO duplicar as funções já existentes `_ml_store_path`/`_salvar_store_ml`/
`_bling_store_path`/`_salvar_store_bling` — se quiser, pode migrá-las para
usar as novas funções genéricas também, mas isso é opcional; o obrigatório
é que Shopee e Magalu passem a ter o mesmo comportamento de persistência
que ML e Bling já têm.

═══════════════════════════════════════════════════════════════
ITEM 4 — Cobertura de testes: subir o piso de 80% para 90%
═══════════════════════════════════════════════════════════════

4a. Em pyproject.toml, trocar:

```
"--cov-fail-under=80",
```

por:

```
"--cov-fail-under=90",
```

4b. Adicionar testes cobrindo TODO o código novo dos itens 1, 2 e 3:

- `get_token_amazon`/`_renovar_token_amazon`: sucesso, credenciais
  ausentes, resposta sem `access_token`, erro de rede, sync no GitHub
  quando `GITHUB_ACTIONS=true` (mockado).
- `amazon_client._h()`: usa `get_token_amazon()` quando há refresh_token
  configurado, usa `AMAZON_ACCESS_TOKEN` estático quando não há.
- `pegar_token_shopee.py`: criar `tests/test_pegar_token_shopee.py`
  testando `gerar_url_autorizacao` (contém partner_id/sign/timestamp) e
  `trocar_code_por_token` (sucesso e erro), mockando `requests.post`.
- Funções genéricas `_store_path`/`_carregar_store`/`_salvar_store`:
  store ativo vs. inativo (env var vazia), JSON corrompido no disco,
  escrita com sucesso.
- `_renovar_token_shopee`/`_renovar_token_magalu`: persistência em disco
  e sync no GitHub quando aplicável (mesmo padrão de teste já existente
  para Bling/ML em `tests/test_token_manager_providers.py`).

4c. Rode no final, nesta ordem, e cole os resultados:

```bash
pytest -q
ruff check .
```

Se a cobertura ficar abaixo de 90% mesmo após os testes do item 4b, me
diga exatamente quais linhas/arquivos ainda estão descobertos antes de
inventar testes triviais só pra "engordar número" — prefiro saber a
lacuna real.

═══════════════════════════════════════════════════════════════
CHECKLIST FINAL — devolver nesse formato
═══════════════════════════════════════════════════════════════

- [ ] Branch `fix/tokens-amazon-shopee-magalu` criada
- [ ] Item 1 (renovação automática Amazon) — aplicado e testado
- [ ] Item 2 (`pegar_token_shopee.py`) — criado e testado
- [ ] Item 3 (cofre/sync Shopee + Magalu) — aplicado e testado
- [ ] Item 4 (piso de cobertura 90%) — `pyproject.toml` atualizado
- [ ] `pytest -q` passando, cobertura real: ____%
- [ ] `ruff check .` sem erros
- [ ] `git diff --stat` colado para revisão antes de qualquer commit