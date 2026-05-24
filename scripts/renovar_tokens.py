#!/usr/bin/env python3
"""
Renova tokens de acesso e salva os novos valores de volta nos GitHub Secrets.
Roda no GitHub Actions a cada 30min via renovar_tokens.yml.

Fluxo:
  1. Busca a chave pública do repositório GitHub
  2. Renova cada token via refresh_token
  3. Criptografa o novo valor com a chave pública (PyNaCl / libsodium)
  4. Salva de volta no Secret via GitHub API
  5. Atualiza GITHUB_ENV para jobs subsequentes no mesmo run
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ══════════════════════════════════════════════════════════════════════════
# GitHub Secrets API
# ══════════════════════════════════════════════════════════════════════════

def _gh_headers() -> dict:
    token = os.getenv("GH_TOKEN", "")
    return {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_public_key() -> dict:
    """Retorna {"key_id": str, "key": str (base64)} do repositório."""
    repo = os.getenv("GITHUB_REPOSITORY", "")
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    r = requests.get(url, headers=_gh_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Criptografa usando libsodium (PyNaCl) — exigido pela GitHub API."""
    from base64 import b64decode, b64encode
    from nacl import encoding, public  # pip install PyNaCl

    pk = public.PublicKey(b64decode(public_key_b64), encoding.RawEncoder)
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode("utf-8"))
    return b64encode(encrypted).decode("utf-8")


def _salvar_secret(nome: str, valor: str, key_id: str, pub_key_b64: str) -> bool:
    """Salva (ou atualiza) um Secret no repositório GitHub."""
    gh_token = os.getenv("GH_TOKEN", "")
    gh_repo  = os.getenv("GITHUB_REPOSITORY", "")
    if not gh_token or not gh_repo:
        print(f"    [aviso] GH_TOKEN/GITHUB_REPOSITORY ausentes — {nome} nao salvo")
        return False
    if not valor:
        print(f"    [aviso] valor vazio — {nome} nao salvo")
        return False
    try:
        encrypted = _encrypt_secret(pub_key_b64, valor)
        url = f"https://api.github.com/repos/{gh_repo}/actions/secrets/{nome}"
        r = requests.put(
            url,
            headers=_gh_headers(),
            json={"encrypted_value": encrypted, "key_id": key_id},
            timeout=10,
        )
        ok = r.status_code in (201, 204)
        status = "salvo ✓" if ok else f"ERRO HTTP {r.status_code}"
        print(f"    {nome}: {status}")
        return ok
    except Exception as exc:
        print(f"    {nome}: ERRO — {exc}")
        return False


def _atualizar_github_env(**kwargs: str) -> None:
    """Exporta variáveis para jobs subsequentes no mesmo Actions run."""
    env_file = os.getenv("GITHUB_ENV", "")
    if not env_file:
        return
    try:
        with open(env_file, "a", encoding="utf-8") as f:
            for nome, valor in kwargs.items():
                if valor:
                    f.write(f"{nome}={valor}\n")
    except OSError:
        pass


# ══════════════════════════════════════════════════════════════════════════
# Renovação de tokens por marketplace
# ══════════════════════════════════════════════════════════════════════════

def _renovar_bling() -> dict:
    """Renova o Access Token do Bling via refresh_token (OAuth2 v3)."""
    client_id     = os.getenv("BLING_CLIENT_ID", "")
    client_secret = os.getenv("BLING_CLIENT_SECRET", "")
    refresh_token = os.getenv("BLING_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        return {"ok": False, "motivo": "credenciais BLING ausentes"}

    credenciais = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()

    try:
        r = requests.post(
            "https://www.bling.com.br/Api/v3/oauth/token",
            headers={
                "Authorization": f"Basic {credenciais}",
                "Content-Type":  "application/x-www-form-urlencoded",
                "Accept":        "application/json",
            },
            data={
                "grant_type":   "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        r.raise_for_status()
        dados = r.json()

        if "access_token" not in dados:
            return {"ok": False, "motivo": str(dados.get("error", dados))}

        return {
            "ok":            True,
            "access_token":  dados["access_token"],
            "refresh_token": dados.get("refresh_token", refresh_token),
            "expires_in":    dados.get("expires_in", 21600),
        }
    except Exception as exc:
        return {"ok": False, "motivo": str(exc)}


# ── Retry com backoff ──────────────────────────────────────────────────────
MAX_TENTATIVAS   = 3
BACKOFF_SEGUNDOS = [0, 30, 90]


def _renovar_bling_com_retry() -> dict:
    import time
    erros: list[str] = []
    for tentativa in range(MAX_TENTATIVAS):
        espera = BACKOFF_SEGUNDOS[tentativa]
        if espera > 0:
            print(f"  [retry] aguardando {espera}s antes da tentativa {tentativa + 1}/{MAX_TENTATIVAS}...")
            time.sleep(espera)
        res = _renovar_bling()
        if res["ok"]:
            if tentativa > 0:
                print(f"  [retry] sucesso na tentativa {tentativa + 1}")
            return res
        erros.append(f"tent.{tentativa + 1}: {res['motivo']}")
        print(f"  [retry] falhou — {res['motivo']}")
    return {
        "ok":         False,
        "motivo":     " | ".join(erros),
        "tentativas": MAX_TENTATIVAS,
    }


# ── Contador de falhas consecutivas ───────────────────────────────────────
FALHAS_LOG = ROOT / "logs" / "renovacao_falhas.json"


def _contar_falhas_consecutivas() -> int:
    try:
        import json as _json
        if FALHAS_LOG.exists():
            return _json.loads(FALHAS_LOG.read_text(encoding="utf-8")).get("bling", 0)
    except Exception:
        pass
    return 0


def _registrar_falha() -> int:
    import json as _json
    from datetime import datetime as _dt
    try:
        FALHAS_LOG.parent.mkdir(parents=True, exist_ok=True)
        atual = _contar_falhas_consecutivas()
        novo  = atual + 1
        FALHAS_LOG.write_text(
            _json.dumps({"bling": novo, "ultima_falha": _dt.now().isoformat()}),
            encoding="utf-8",
        )
        return novo
    except Exception:
        return 1


def _registrar_sucesso() -> None:
    import json as _json
    try:
        FALHAS_LOG.parent.mkdir(parents=True, exist_ok=True)
        FALHAS_LOG.write_text(
            _json.dumps({"bling": 0, "ultima_falha": None}),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Alerta escalonado ──────────────────────────────────────────────────────

def _alertar_falha_bling(motivo: str, falhas_consecutivas: int) -> None:
    """
    1-2  falhas → alertar()         aviso simples
    3-5  falhas → alertar_gestor()  1h30 sem renovar
    6+   falhas → alertar_critico() 3h+ sem renovar
    """
    try:
        from core.notificador import alertar, alertar_critico, alertar_gestor

        tempo_sem = falhas_consecutivas * 30
        expira_em = max(0, 360 - tempo_sem)

        msg = (
            f"♻️ *Renovação Bling — "
            f"{'CRÍTICO' if falhas_consecutivas >= 6 else 'Atenção'}*\n\n"
            f"Falhas consecutivas: {falhas_consecutivas}×\n"
            f"Sem renovar há: ~{tempo_sem} minutos\n"
            f"Token expira em: ~{expira_em} minutos\n\n"
            f"Motivo: `{motivo[:200]}`\n\n"
        )

        if falhas_consecutivas >= 6:
            msg += (
                "🚨 *Token pode expirar em breve!*\n"
                "Acesse: github.com/joaolago38/Robo-Markplaces/actions\n"
                "→ _Renovar tokens marketplace_ → *Run workflow*"
            )
            alertar_critico(msg)
        elif falhas_consecutivas >= 3:
            msg += "⚠️ Verifique se o Bling ou o GitHub Actions estão com problemas."
            alertar_gestor(msg)
        else:
            msg += "_Tentando novamente em 30 minutos._"
            alertar(msg)

    except Exception as exc:
        print(f"  [alerta] falha ao enviar Telegram: {exc}")


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("Renovacao de tokens — Robo-Markplaces")
    print("=" * 60)

    exit_code = 0

    # Obtém chave pública do repo para salvar Secrets
    pub_key_id  = ""
    pub_key_b64 = ""
    if os.getenv("GH_TOKEN") and os.getenv("GITHUB_REPOSITORY"):
        try:
            pk = _get_public_key()
            pub_key_id  = pk["key_id"]
            pub_key_b64 = pk["key"]
            print(f"Chave publica GitHub: key_id={pub_key_id[:8]}...")
        except Exception as exc:
            print(f"[aviso] Nao foi possivel obter chave GitHub: {exc}")

    # ── Bling ────────────────────────────────────────────────────────────
    print("\n[Bling]")
    res = _renovar_bling_com_retry()
    if res["ok"]:
        print(f"  Token renovado — expira em {res['expires_in']}s")
        _registrar_sucesso()
        if pub_key_id:
            _salvar_secret("BLING_ACCESS_TOKEN",  res["access_token"],  pub_key_id, pub_key_b64)
            _salvar_secret("BLING_REFRESH_TOKEN", res["refresh_token"], pub_key_id, pub_key_b64)
        _atualizar_github_env(
            BLING_ACCESS_TOKEN=res["access_token"],
            BLING_REFRESH_TOKEN=res["refresh_token"],
        )
    else:
        falhas = _registrar_falha()
        print(f"  FALHOU ({falhas}× consecutiva(s)): {res['motivo']}")
        _alertar_falha_bling(res["motivo"], falhas)
        exit_code = 1

    # ── ML / Shopee / Magalu — delega ao token_manager existente ─────────
    print("\n[ML / Shopee / Magalu]")
    try:
        from core.token_manager import renovar_todos_tokens
        resultados = renovar_todos_tokens()
        for nome, payload in sorted(resultados.items()):
            ok = payload.get("ok")
            token_novo = payload.get("access_token", "")
            print(f"  {nome}: {'ok' if ok else 'falhou'}")

            # Salva token novo no Secret correspondente
            secret_map = {
                "mercadolivre": "ML_ACCESS_TOKEN",
                "shopee":       "SHOPEE_ACCESS_TOKEN",
                "magalu":       "MAGALU_ACCESS_TOKEN",
            }
            secret_nome = secret_map.get(nome)
            if ok and token_novo and secret_nome and pub_key_id:
                _salvar_secret(secret_nome, token_novo, pub_key_id, pub_key_b64)

            if ok is False:
                exit_code = 1
    except Exception as exc:
        print(f"  ERRO: {exc}")
        exit_code = 1

    print("\n" + "=" * 60)
    print(f"Concluido — exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
