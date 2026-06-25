#!/usr/bin/env python3
"""
scripts/diagnostico_telegram.py

Valida a configuração do Telegram (token, chats e envio de alertas).
Não expõe o token completo em prints ou logs.

Uso:
    .venv\\Scripts\\python.exe scripts/diagnostico_telegram.py

Checa:
    1. Credenciais TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GESTOR_CHAT_ID
    2. Token válido via getMe (username do bot)
    3. Envio de teste via alertar()
    4. Envio de teste via alertar_gestor()
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

OK = "OK"
FALHA = "FALHA"
MSG_TESTE = "✅ Diagnóstico Robo-Markplaces — conexão Telegram OK"


def _mascarar_token(token: str) -> str:
    """Mascara token do bot para exibição segura (ex.: 8935544842:AAHU...***)."""
    texto = (token or "").strip()
    if not texto:
        return "(vazio)"
    if ":" in texto:
        prefixo, _, sufixo = texto.partition(":")
        visivel = sufixo[:4] if len(sufixo) >= 4 else sufixo[:1]
        return f"{prefixo}:{visivel}...***"
    return f"{texto[:6]}...***" if len(texto) > 6 else "***"


def _verificar_credenciais() -> dict:
    from core.config import TELEGRAM_CHAT_ID, TELEGRAM_GESTOR_CHAT_ID, TELEGRAM_TOKEN

    faltando: list[str] = []
    if not (TELEGRAM_TOKEN or "").strip():
        faltando.append("TELEGRAM_TOKEN")
    if not (TELEGRAM_CHAT_ID or "").strip():
        faltando.append("TELEGRAM_CHAT_ID")
    if not (TELEGRAM_GESTOR_CHAT_ID or "").strip():
        faltando.append("TELEGRAM_GESTOR_CHAT_ID")

    if faltando:
        return {
            "ok": False,
            "erro": f"Variável ausente: {', '.join(faltando)}",
            "faltando": faltando,
        }

    return {
        "ok": True,
        "token_mascarado": _mascarar_token(TELEGRAM_TOKEN),
        "chat_id": str(TELEGRAM_CHAT_ID).strip(),
        "gestor_chat_id": str(TELEGRAM_GESTOR_CHAT_ID).strip(),
    }


def _verificar_get_me() -> dict:
    from core.config import TELEGRAM_TOKEN
    from core.http_client import request
    from core.http_errors import mascarar_url_telegram

    try:
        r = request(
            "GET",
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
            timeout=15,
        )
        status = getattr(r, "status_code", 0)
        if status == 401:
            return {"ok": False, "erro": "token inválido ou expirado (HTTP 401)"}
        r.raise_for_status()
        body = r.json() if hasattr(r, "json") else {}
        if not isinstance(body, dict):
            return {"ok": False, "erro": "resposta getMe inválida"}
        if not body.get("ok"):
            desc = str(body.get("description") or "getMe retornou ok=false")
            return {"ok": False, "erro": mascarar_url_telegram(desc)}
        user = body.get("result") if isinstance(body.get("result"), dict) else {}
        username = str(user.get("username") or "").strip()
        return {
            "ok": True,
            "username": username or "(sem username)",
            "bot_id": user.get("id"),
        }
    except Exception as exc:
        return {"ok": False, "erro": mascarar_url_telegram(str(exc))}


def _testar_alertar() -> dict:
    from core.notificador import alertar

    try:
        enviado = bool(alertar(MSG_TESTE))
        if enviado:
            return {"ok": True}
        return {"ok": False, "erro": "alertar() retornou False — mensagem não entregue"}
    except Exception as exc:
        from core.http_errors import mascarar_url_telegram

        return {"ok": False, "erro": mascarar_url_telegram(str(exc))}


def _testar_alertar_gestor() -> dict:
    from core.notificador import alertar_gestor

    try:
        enviado = bool(alertar_gestor(MSG_TESTE))
        if enviado:
            return {"ok": True}
        return {"ok": False, "erro": "alertar_gestor() retornou False — mensagem não entregue"}
    except Exception as exc:
        from core.http_errors import mascarar_url_telegram

        return {"ok": False, "erro": mascarar_url_telegram(str(exc))}


def executar() -> dict:
    """Roda o diagnóstico e devolve dict estruturado. Nunca lança exceção."""
    resultado: dict = {"ok": False, "etapas": {}}

    credenciais = _verificar_credenciais()
    resultado["etapas"]["credenciais"] = credenciais
    if not credenciais.get("ok"):
        resultado["erro"] = credenciais.get("erro")
        return resultado

    getme = _verificar_get_me()
    resultado["etapas"]["getme"] = getme

    alerta = _testar_alertar()
    resultado["etapas"]["alertar"] = alerta

    gestor = _testar_alertar_gestor()
    resultado["etapas"]["alertar_gestor"] = gestor

    resultado["ok"] = all(
        etapa.get("ok")
        for etapa in resultado["etapas"].values()
        if isinstance(etapa, dict)
    )
    if not resultado["ok"] and not resultado.get("erro"):
        falhas = [
            nome
            for nome, etapa in resultado["etapas"].items()
            if isinstance(etapa, dict) and not etapa.get("ok")
        ]
        resultado["erro"] = f"Falha nas etapas: {', '.join(falhas)}"
    return resultado


def _imprimir(resultado: dict) -> None:
    print("=" * 60)
    print("Diagnóstico Telegram — Robo-Markplaces")
    print("=" * 60)

    etapas = resultado.get("etapas") or {}

    cred = etapas.get("credenciais", {})
    if cred.get("ok"):
        print(
            f"[{OK}] Credenciais — token {cred.get('token_mascarado')} | "
            f"chat {cred.get('chat_id')} | gestor {cred.get('gestor_chat_id')}"
        )
    else:
        print(f"[{FALHA}] Credenciais — {cred.get('erro')}")
        print("\n     Configure TELEGRAM_TOKEN, TELEGRAM_CHAT_ID e TELEGRAM_GESTOR_CHAT_ID no .env")
        return

    getme = etapas.get("getme", {})
    if getme.get("ok"):
        print(f"[{OK}] getMe — bot @{getme.get('username')} (id {getme.get('bot_id')})")
    else:
        print(f"[{FALHA}] getMe — {getme.get('erro')}")

    alerta = etapas.get("alertar", {})
    if alerta.get("ok"):
        print(f"[{OK}] alertar() — mensagem de teste enviada para TELEGRAM_CHAT_ID")
    else:
        print(f"[{FALHA}] alertar() — {alerta.get('erro')}")

    gestor = etapas.get("alertar_gestor", {})
    if gestor.get("ok"):
        print(f"[{OK}] alertar_gestor() — mensagem de teste enviada para TELEGRAM_GESTOR_CHAT_ID")
    else:
        print(f"[{FALHA}] alertar_gestor() — {gestor.get('erro')}")

    print()
    if resultado.get("ok"):
        print(f"Resumo: [{OK}] Telegram configurado e enviando alertas.")
    else:
        print(f"Resumo: [{FALHA}] {resultado.get('erro', 'uma ou mais etapas falharam')}")


def main(argv: list[str] | None = None) -> int:
    _ = argv if argv is not None else sys.argv[1:]
    resultado = executar()
    _imprimir(resultado)
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
