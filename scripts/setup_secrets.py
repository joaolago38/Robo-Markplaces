#!/usr/bin/env python3
"""
Setup interativo dos GitHub Secrets para o Robo-Markplaces.

Verifica quais secrets estão configurados e guia o usuário
para configurar os que faltam.

Uso:
    python scripts/setup_secrets.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Mapa de todos os secrets necessários ──────────────────────────────────
SECRETS = {
    "OBRIGATORIOS_AGORA": {
        "descricao": "Minimo para o robo comecar a operar",
        "items": {
            "ANTHROPIC_API_KEY": {
                "descricao": "Chave de acesso ao Claude (IA)",
                "onde":      "console.anthropic.com -> API Keys (deposite $5 = R$30)",
                "formato":   "sk-ant-api03-...",
            },
            "ANTHROPIC_ADMIN_API_KEY": {
                "descricao": "Admin key — gasto real do mês no Datadog (opcional, contas com org)",
                "onde":      "console.anthropic.com -> Settings -> Admin API keys (sk-ant-admin...)",
                "formato":   "sk-ant-admin01-...",
            },
            "TELEGRAM_TOKEN": {
                "descricao": "Token do bot do Telegram para alertas",
                "onde":      "No Telegram: converse com @BotFather -> /newbot",
                "formato":   "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
            },
            "TELEGRAM_CHAT_ID": {
                "descricao": "Seu chat ID no Telegram",
                "onde":      "No Telegram: converse com @userinfobot -> ele responde seu ID",
                "formato":   "123456789",
            },
        }
    },
    "WHATSAPP": {
        "descricao": "Notificacoes de venda em tempo real no WhatsApp",
        "items": {
            "WHATSAPP_BUSINESS_TOKEN": {
                "descricao": "Token do WhatsApp Business Cloud (Meta)",
                "onde":      "developers.facebook.com -> WhatsApp -> configuracoes",
                "formato":   "EAAXBb94...",
            },
            "WHATSAPP_PHONE_ID": {
                "descricao": "ID do numero de telefone WhatsApp Business",
                "onde":      "developers.facebook.com -> WhatsApp -> configuracoes -> phone_number_id",
                "formato":   "1015009041706906",
            },
            "WHATSAPP_NUMERO_DESTINO": {
                "descricao": "Seu numero para receber notificacoes",
                "onde":      "Seu proprio numero (sem + e sem espacos)",
                "formato":   "5519999889059",
            },
        }
    },
    "MERCADO_LIVRE": {
        "descricao": "Chat automatico e repricing no ML",
        "items": {
            "ML_CLIENT_ID": {
                "descricao": "Client ID do app no ML",
                "onde":      "developers.mercadolibre.com -> Minhas aplicacoes",
                "formato":   "123456789",
            },
            "ML_CLIENT_SECRET": {
                "descricao": "Client Secret do app no ML",
                "onde":      "developers.mercadolibre.com -> Minhas aplicacoes",
                "formato":   "AbCdEfGhIjKlMnOpQrStUvWxYz123456",
            },
            "ML_ACCESS_TOKEN": {
                "descricao": "Token de acesso ao ML",
                "onde":      "Gerado via OAuth2 (renovado automaticamente pelo robo)",
                "formato":   "APP_USR-...",
            },
            "ML_REFRESH_TOKEN": {
                "descricao": "Refresh token do ML",
                "onde":      "Gerado junto com o access_token",
                "formato":   "TG-...",
            },
            "ML_SELLER_ID": {
                "descricao": "Seu ID de vendedor no ML",
                "onde":      "URL do seu perfil no ML: mercadolivre.com.br/perfil/SEUUSUARIO",
                "formato":   "123456789",
            },
        }
    },
    "SHOPEE": {
        "descricao": "Chat automatico e vendas na Shopee",
        "items": {
            "SHOPEE_PARTNER_ID":    {"descricao": "Partner ID",    "onde": "open.shopee.com -> meu app",  "formato": "1234567"},
            "SHOPEE_PARTNER_KEY":   {"descricao": "Partner Key",   "onde": "open.shopee.com -> meu app",  "formato": "abc123..."},
            "SHOPEE_SHOP_ID":       {"descricao": "Shop ID",       "onde": "Retornado na autorizacao",    "formato": "1234567"},
            "SHOPEE_ACCESS_TOKEN":  {"descricao": "Access Token",  "onde": "Gerado via OAuth2",           "formato": "abc123..."},
            "SHOPEE_REFRESH_TOKEN": {"descricao": "Refresh Token", "onde": "Gerado via OAuth2",           "formato": "abc123..."},
        }
    },
    "MAGALU": {
        "descricao": "Chat automatico no Magazine Luiza",
        "items": {
            "MAGALU_CLIENT_ID":     {"descricao": "Client ID",     "onde": "developers.magalu.com", "formato": "abc123"},
            "MAGALU_CLIENT_SECRET": {"descricao": "Client Secret", "onde": "developers.magalu.com", "formato": "abc123"},
            "MAGALU_MERCHANT_ID":   {"descricao": "Merchant ID",   "onde": "developers.magalu.com", "formato": "abc123"},
            "MAGALU_ACCESS_TOKEN":  {"descricao": "Access Token",  "onde": "Gerado via OAuth2",     "formato": "abc123"},
            "MAGALU_REFRESH_TOKEN": {"descricao": "Refresh Token", "onde": "Gerado via OAuth2",     "formato": "abc123"},
        }
    },
    "BLING_JA_CONFIGURADO": {
        "descricao": "Bling ERP - NF-e automatica (JA CONFIGURADO)",
        "items": {
            "BLING_CLIENT_ID":     {"descricao": "Client ID",     "onde": "JA configurado no GitHub Secrets",          "formato": "ok"},
            "BLING_CLIENT_SECRET": {"descricao": "Client Secret", "onde": "JA configurado no GitHub Secrets",          "formato": "ok"},
            "BLING_ACCESS_TOKEN":  {"descricao": "Access Token",  "onde": "JA configurado - renovado automaticamente", "formato": "ok"},
            "BLING_REFRESH_TOKEN": {"descricao": "Refresh Token", "onde": "JA configurado - renovado automaticamente", "formato": "ok"},
        }
    },
}


def _check_env(nome: str) -> bool:
    """Verifica se a variavel esta configurada no ambiente local."""
    val = os.getenv(nome, "").strip()
    return bool(val) and val != "..." and not val.startswith("sk-ant-")


def main():
    print()
    print("=" * 60)
    print("  Robo-Markplaces - Setup de GitHub Secrets")
    print("=" * 60)
    print()
    print("Acesse para configurar:")
    print("  github.com/joaolago38/Robo-Markplaces/settings/secrets/actions")
    print()

    total = 0
    configurados = 0

    for grupo, info in SECRETS.items():
        print(f"-- {info['descricao']} --")
        for nome, detalhes in info["items"].items():
            total += 1
            ok = _check_env(nome) or "JA configurado" in detalhes["onde"]
            status = "[OK]  " if ok else "[FALTA]"
            if ok:
                configurados += 1
            print(f"  {status} {nome}")
            if not ok:
                print(f"          Onde obter: {detalhes['onde']}")
                print(f"          Formato:    {detalhes['formato']}")
        print()

    pct = int(configurados / total * 100) if total else 0
    print(f"Progresso: {configurados}/{total} secrets configurados ({pct}%)")
    print()
    print("Como adicionar no GitHub:")
    print("  1. Acesse a URL acima")
    print("  2. Clique em 'New repository secret'")
    print("  3. Nome: o campo acima (ex: ANTHROPIC_API_KEY)")
    print("  4. Value: o valor obtido na fonte indicada")
    print("  5. Clique em 'Add secret'")
    print()
    print("Prioridade: configure primeiro os OBRIGATORIOS_AGORA")
    print("O robo ja funciona com: ANTHROPIC + TELEGRAM + BLING (ok)")
    print()


if __name__ == "__main__":
    main()
