#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.github_secrets import sync_secrets_github as _sync_secrets_github

logger = logging.getLogger("renovar_tokens")

try:
    from core.notificador import alertar_critico
except Exception as exc:
    logger.warning("notificador indisponível — alertas críticos só no stdout: %s", exc)

    def alertar_critico(msg: str) -> bool:  # type: ignore[misc]
        print(f"[ALERTA CRÍTICO — Telegram não configurado]\n{msg}")
        return False


CREDENCIAIS_ML = ["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]
CREDENCIAIS_SHOPEE = ["SHOPEE_PARTNER_ID", "SHOPEE_PARTNER_KEY", "SHOPEE_SHOP_ID"]
CREDENCIAIS_MAGALU = ["MAGALU_CLIENT_ID", "MAGALU_CLIENT_SECRET", "MAGALU_REFRESH_TOKEN"]

_provedores_alertados: set[str] = set()


def _tem_credenciais(variaveis: list[str]) -> bool:
    return all(os.getenv(v, "").strip() for v in variaveis)


def _sanitizar_motivo(motivo: str) -> str:
    """Remove possíveis tokens do texto antes de enviar alerta."""
    texto = (motivo or "").strip()
    texto = re.sub(
        r"(?i)\b(refresh_token|access_token|token|bearer)\b[\s:=]+[^\s,;]+",
        r"\1=***",
        texto,
    )
    return texto[:500]


def _dica_bling_travado(motivo: str) -> tuple[str, str]:
    """
    Retorna (diagnóstico, ação) diferenciando refresh expirado vs client secret.
    """
    m = (motivo or "").lower()
    if "credenciais bling ausentes" in m or (
        "credenciais" in m and not os.getenv("BLING_CLIENT_SECRET", "").strip()
    ):
        return (
            "BLING_CLIENT_SECRET ausente ou credenciais incompletas.",
            "Corrija BLING_CLIENT_ID, BLING_CLIENT_SECRET e BLING_REFRESH_TOKEN nos Secrets.",
        )
    if "invalid_client" in m or ("client" in m and "secret" in m):
        return (
            "BLING_CLIENT_ID/BLING_CLIENT_SECRET incorretos.",
            "Confira BLING_CLIENT_ID e BLING_CLIENT_SECRET no GitHub (sem aspas/espaços).",
        )
    if "invalid_grant" in m or "expirado" in m or "inválido" in m or "invalido" in m:
        return (
            "refresh_token inválido/expirado (HTTP 400 invalid_grant).",
            "Rode `python pegar_token_bling.py SEU_CODE` e atualize BLING_ACCESS_TOKEN e "
            "BLING_REFRESH_TOKEN nos Secrets do GitHub.",
        )
    return (
        "renovação automática falhou — o ciclo não se auto-cura.",
        "Rode `python pegar_token_bling.py SEU_CODE` e atualize BLING_ACCESS_TOKEN e "
        "BLING_REFRESH_TOKEN nos Secrets do GitHub.",
    )


def _alertar_token_travado(provedor: str, motivo: str) -> None:
    """Dispara no máximo um alerta crítico por provedor por execução."""
    chave = (provedor or "").strip().lower()
    if not chave or chave in _provedores_alertados:
        return
    _provedores_alertados.add(chave)

    motivo_limpo = _sanitizar_motivo(motivo)
    if chave == "bling":
        diagnostico, acao = _dica_bling_travado(motivo_limpo)
        msg = (
            "🚨 BLING TRAVADO — renovação automática falhou.\n"
            "O ciclo não se auto-cura: é preciso bootstrap manual.\n"
            f"{diagnostico}\n"
            f"Ação: {acao}\n"
            f"Detalhe: {motivo_limpo or 'sem detalhe'}"
        )
    else:
        rotulos = {
            "mercadolivre": "MERCADO LIVRE",
            "magalu": "MAGALU",
            "shopee": "SHOPEE",
            "meta": "META",
        }
        rotulo = rotulos.get(chave, provedor.upper())
        msg = (
            f"🚨 {rotulo} TRAVADO — renovação automática falhou.\n"
            "O ciclo pode não se auto-curar sem atualizar os Secrets.\n"
            f"Detalhe: {motivo_limpo or 'sem detalhe'}"
        )

    alertar_critico(msg)


def main() -> int:
    global _provedores_alertados
    _provedores_alertados = set()

    print("=" * 60)
    print("Renovacao de tokens — Robo-Markplaces")
    print("=" * 60)

    exit_code = 0
    em_actions = os.getenv("GITHUB_ACTIONS") == "true"
    quer_sync = os.getenv("BLING_SYNC_GITHUB", "").strip().lower() in {"1", "true", "yes"}

    print("\n[Bling]")
    # ──────────────────────────────────────────────────────────────
    # PAUSADO em 01/07/2026: renovação automática do Bling desativada
    # de propósito. Causa raiz NÃO é bug de código — é a empresa
    # vinculada ao token estar marcada como inativa no painel do
    # Bling (HTTP 403 "A empresa vinculada ao token está inativa").
    # Renovar o token não resolve isso; é preciso resolver a
    # ativação da conta direto no Bling primeiro.
    #
    # Pra reativar: descomente o bloco original abaixo (git blame /
    # histórico deste arquivo, commit da pausa) assim que a conta
    # Bling estiver ativa de novo, e confirme rodando manualmente:
    #     python -c "from core.token_manager import renovar_token_bling_detalhado; print(renovar_token_bling_detalhado())"
    # ──────────────────────────────────────────────────────────────
    print("  bling: PAUSADO (renovação automática desativada manualmente)")
    print("  Motivo: empresa vinculada ao token inativa no painel Bling (HTTP 403).")
    print("  Ação: resolver a ativação da conta no Bling, depois reativar este bloco em scripts/renovar_tokens.py.")

    # try:
    #     from core.token_manager import renovar_token_bling_detalhado
    #     res_bling = renovar_token_bling_detalhado()
    #     if res_bling.get("ok"):
    #         print("  bling: ok — token renovado")
    #         novo_refresh = res_bling.get("refresh_token")
    #         # BLING_* no GitHub: sincronizado em _renovar_token_bling() quando GITHUB_ACTIONS=true.
    #         if not em_actions and not quer_sync:
    #             print("  ATENCAO: o Bling rotaciona o refresh_token a cada renovacao.")
    #             print("  Atualize os secrets com os novos valores abaixo, senao a")
    #             print("  proxima execucao falhara (o refresh_token antigo foi invalidado):")
    #             print(f"    BLING_ACCESS_TOKEN  -> {res_bling.get('access_token')}")
    #             print(f"    BLING_REFRESH_TOKEN -> {novo_refresh}")
    #     else:
    #         motivo = str(res_bling.get("motivo", "") or "")
    #         print(f"  bling: falhou — {motivo}")
    #         print("  Se o refresh_token expirou, gere um novo com pegar_token_bling.py")
    #         _alertar_token_travado("bling", motivo)
    #         exit_code = 1
    # except Exception as exc:
    #     print(f"  bling: ERRO — {exc}")
    #     print("  Renovacao manual via pegar_token_bling.py")
    #     _alertar_token_travado("bling", str(exc))
    #     exit_code = 1

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
                motivo = str(res_meta.get("motivo", "") or "")
                print(f"  meta: falhou — {motivo}")
                print("  Se o token longo expirou, gere um novo com pegar_token_meta.py")
                _alertar_token_travado("meta", motivo)
                exit_code = 1
        except Exception as exc:
            print(f"  meta: ERRO — {exc}")
            _alertar_token_travado("meta", str(exc))
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
            elif nome == "magalu":
                # ──────────────────────────────────────────────────
                # ALERTA PAUSADO em 01/07/2026: a causa raiz já está
                # identificada e corrigida no código (host/endpoint
                # de integracoes/magalu/magalu_client.py) — falta só
                # um passo manual: reautorizar via
                # pegar_token_magalu.py e colar o MAGALU_ACCESS_TOKEN
                # / MAGALU_REFRESH_TOKEN novos nos Secrets do GitHub.
                # O MAGALU_REFRESH_TOKEN atual está morto
                # (invalid_grant) e não se auto-cura sozinho.
                #
                # Pra reativar o alerta: remova este 'elif' e deixe
                # o magalu cair no 'else' genérico abaixo, assim que
                # os Secrets forem atualizados com sucesso.
                # ──────────────────────────────────────────────────
                print("  magalu: PAUSADO (alerta desativado manualmente)")
                print("  Motivo: MAGALU_REFRESH_TOKEN morto (invalid_grant) nos Secrets do GitHub.")
                print("  Ação: reautorize com pegar_token_magalu.py e atualize MAGALU_ACCESS_TOKEN")
                print("  e MAGALU_REFRESH_TOKEN nos Secrets — depois reative este alerta.")
            else:
                motivo = str(payload.get("motivo", "") or "").strip()
                if motivo:
                    print(f"  {nome}: falhou — {motivo}")
                else:
                    print(f"  {nome}: falhou na renovação — ver erro acima")
                    motivo = "falha na renovação — ver log"
                _alertar_token_travado(nome, motivo)
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