#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CREDENCIAIS_ML = ["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]
CREDENCIAIS_SHOPEE = ["SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY", "SHOPEE_SHOP_ID"]
CREDENCIAIS_MAGALU = ["MAGALU_CLIENT_ID", "MAGALU_CLIENT_SECRET", "MAGALU_MERCHANT_ID"]

def _tem_credenciais(variaveis: list[str]) -> bool:
    return all(os.getenv(v, "").strip() for v in variaveis)


def _sync_secrets_github(access_token: str, refresh_token: str | None, prefix: str = "BLING") -> bool:
    if not shutil.which("gh"):
        print(f"  gh CLI não encontrado — Secret {prefix}_* não atualizado")
        return False

    repo = (os.getenv("GH_REPO") or "").strip()
    base_cmd = ["gh", "secret", "set"]
    repo_args = ["--repo", repo] if repo else []

    pares = [(f"{prefix}_ACCESS_TOKEN", access_token)]
    if refresh_token:
        pares.append((f"{prefix}_REFRESH_TOKEN", refresh_token))

    ok = True
    for nome, valor in pares:
        try:
            subprocess.run(
                base_cmd + [nome] + repo_args,
                input=valor,
                text=True,
                check=True,
                capture_output=True,
            )
            print(f"  Secret {nome} atualizado no GitHub")
        except subprocess.CalledProcessError as e:
            print(f"  Falha ao atualizar {nome}: {e.stderr.strip()}")
            ok = False
    return ok


def main() -> int:
    print("=" * 60)
    print("Renovacao de tokens — Robo-Markplaces")
    print("=" * 60)

    exit_code = 0
    em_actions = os.getenv("GITHUB_ACTIONS") == "true"
    quer_sync = os.getenv("BLING_SYNC_GITHUB", "").strip().lower() in {"1", "true", "yes"}

    print("\n[Bling]")
    tem_bling = _tem_credenciais(["BLING_CLIENT_ID", "BLING_CLIENT_SECRET", "BLING_REFRESH_TOKEN"])
    if not tem_bling:
        print("  Sem CLIENT_ID/SECRET/REFRESH_TOKEN — renovacao manual via pegar_token_bling.py")
    else:
        try:
            from core.token_manager import renovar_token_bling_detalhado
            res_bling = renovar_token_bling_detalhado()
            if res_bling.get("ok"):
                print("  bling: ok — token renovado")
                novo_refresh = res_bling.get("refresh_token")
                if em_actions or quer_sync:
                    if not _sync_secrets_github(
                        res_bling["access_token"],
                        novo_refresh,
                        prefix="BLING",
                    ):
                        exit_code = 1
                else:
                    print("  ATENCAO: o Bling rotaciona o refresh_token a cada renovacao.")
                    print("  Atualize os secrets com os novos valores abaixo, senao a")
                    print("  proxima execucao falhara (o refresh_token antigo foi invalidado):")
                    print(f"    BLING_ACCESS_TOKEN  -> {res_bling.get('access_token')}")
                    print(f"    BLING_REFRESH_TOKEN -> {novo_refresh}")
            else:
                print(f"  bling: falhou — {res_bling.get('motivo', '')}")
                print("  Se o refresh_token expirou, gere um novo com pegar_token_bling.py")
                exit_code = 1
        except Exception as exc:
            print(f"  bling: ERRO — {exc}")
            print("  Renovacao manual via pegar_token_bling.py")
            exit_code = 1

    print("\n[Meta]")
    tem_meta = _tem_credenciais(["META_APP_ID", "META_APP_SECRET", "META_ACCESS_TOKEN"])
    if not tem_meta:
        print("  Sem APP_ID/APP_SECRET/ACCESS_TOKEN — gere o token com pegar_token_meta.py")
    else:
        try:
            from core.token_manager import renovar_token_meta_detalhado
            res_meta = renovar_token_meta_detalhado()
            if res_meta.get("ok"):
                print("  meta: ok — token longo renovado (~60 dias)")
                if em_actions or quer_sync:
                    if not _sync_secrets_github(res_meta["access_token"], None, prefix="META"):
                        exit_code = 1
                else:
                    print(f"    META_ACCESS_TOKEN -> {res_meta['access_token']}")
            else:
                print(f"  meta: falhou — {res_meta.get('motivo', '')}")
                print("  Se o token longo expirou, gere um novo com pegar_token_meta.py")
                exit_code = 1
        except Exception as exc:
            print(f"  meta: ERRO — {exc}")
            exit_code = 1

    print("\n[ML / Shopee / Magalu]")

    tem_ml     = _tem_credenciais(CREDENCIAIS_ML)
    tem_shopee = _tem_credenciais(CREDENCIAIS_SHOPEE)
    tem_magalu = _tem_credenciais(CREDENCIAIS_MAGALU)

    if not tem_ml and not tem_shopee and not tem_magalu:
        print("  Nenhuma credencial configurada — ignorado")
        print("\n" + "=" * 60)
        print(f"Concluido — exit code: {exit_code}")
        return exit_code

    try:
        from core.token_manager import renovar_todos_tokens
        resultados = renovar_todos_tokens()

        ignorar = {
            "mercadolivre": not tem_ml,
            "shopee":       not tem_shopee,
            "magalu":       not tem_magalu,
        }

        for nome, payload in sorted(resultados.items()):
            ok = payload.get("ok")
            if ignorar.get(nome):
                print(f"  {nome}: sem credenciais — ignorado")
            elif ok:
                print(f"  {nome}: ok")
            else:
                motivo = payload.get("motivo", "")
                print(f"  {nome}: falhou — {motivo}")
                exit_code = 1

        # Write-back: refresh_tokens rotativos — grava nos Secrets sem renovar de novo.
        ml_ok = resultados.get("mercadolivre", {}).get("ok")
        if ml_ok and tem_ml and (em_actions or quer_sync):
            from core.token_manager import tokens_ml_atuais

            tk = tokens_ml_atuais()
            if not _sync_secrets_github(tk["access_token"], tk["refresh_token"], prefix="ML"):
                exit_code = 1

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

    except Exception as exc:
        print(f"  ERRO: {exc}")
        exit_code = 1

    print("\n" + "=" * 60)
    print(f"Concluido — exit code: {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())