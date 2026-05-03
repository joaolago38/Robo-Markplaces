"""
core/notificador.py
Envia alertas via Telegram. Nunca lança exceção.
"""
import json
import logging
import time
from datetime import datetime
from core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GESTOR_CHAT_ID
from core.http_client import request

logger = logging.getLogger("notificador")

def _enviar(chat_id: str, msg: str) -> bool:
    if not TELEGRAM_TOKEN or not chat_id:
        print(f"[TELEGRAM não configurado]\n{msg}")
        return True
    try:
        r = request(
            "POST",
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Telegram erro: %s", e)
        return False

def alertar(msg: str) -> bool:
    return _enviar(TELEGRAM_CHAT_ID, f"🔔 *Alerta* {datetime.now().strftime('%d/%m %H:%M')}\n\n{msg}")

def alertar_gestor(msg: str) -> bool:
    return _enviar(TELEGRAM_GESTOR_CHAT_ID, f"📊 *Gestor* {datetime.now().strftime('%d/%m %H:%M')}\n\n{msg}")

def alertar_critico(msg: str) -> bool:
    alertar_gestor(f"🚨 CRÍTICO\n{msg}")
    return alertar(f"🚨 CRÍTICO\n{msg}")


def notificar_venda_whatsapp(
    marketplace: str,
    pedido_id: str,
    produto: str,
    valor: float,
    quantidade: int = 1,
) -> bool:
    """Notifica nova venda no WhatsApp (Evolution ou Meta). Nunca lança exceção."""
    try:
        from core.whatsapp import notificar_venda

        return notificar_venda(
            marketplace=marketplace,
            pedido_id=pedido_id,
            produto=produto,
            valor=valor,
            quantidade=quantidade,
        )
    except Exception as exc:
        logger.error("notificar_venda_whatsapp: %s", exc)
        return False


def _responder_callback(callback_query_id: str, texto: str) -> None:
    """Responde ao callback_query para remover indicador de carregamento do botão."""
    if not TELEGRAM_TOKEN or not callback_query_id:
        return
    try:
        request(
            "POST",
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": texto},
            timeout=10,
        )
    except Exception as e:
        logger.error("Telegram answerCallbackQuery erro: %s", e)


def perguntar_gestor_e_aguardar(pergunta: str, timeout_segundos: int = 600) -> bool:
    """
    Envia uma pergunta ao gestor via Telegram com botões SIM/NÃO (inline keyboard).
    Aguarda resposta por até timeout_segundos (padrão: 10 minutos).
    Retorna True se gestor respondeu SIM, False em qualquer outro caso.
    Nunca lança exceção.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_GESTOR_CHAT_ID:
        logger.warning("Telegram não configurado — confirmação de ads auto-aprovada")
        return True
    url_base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        sm = request(
            "POST",
            f"{url_base}/sendMessage",
            json={
                "chat_id": TELEGRAM_GESTOR_CHAT_ID,
                "text": f"❓ *Confirmação necessária*\n\n{pergunta}\n\n_Responda abaixo:_",
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "✅ SIM", "callback_data": "ads_sim"},
                        {"text": "❌ NÃO", "callback_data": "ads_nao"},
                    ]]
                },
            },
            timeout=10,
        )
        sm.raise_for_status()
        body = sm.json() or {}
        result = body.get("result") or {}
        message_id_enviado = result.get("message_id")
        if message_id_enviado is None:
            logger.error("Telegram sendMessage sem message_id para confirmação de ads")
            return False

        inicio = time.monotonic()
        next_offset = None

        while (time.monotonic() - inicio) < timeout_segundos:
            restante = timeout_segundos - (time.monotonic() - inicio)
            poll_timeout = int(min(5, max(1, restante)))
            params: dict[str, str | int] = {
                "timeout": poll_timeout,
                "allowed_updates": json.dumps(["callback_query"]),
            }
            if next_offset is not None:
                params["offset"] = next_offset

            r = request(
                "GET",
                f"{url_base}/getUpdates",
                params=params,
                timeout=poll_timeout + 10,
            )
            r.raise_for_status()
            updates = (r.json() or {}).get("result") or []

            for update in updates:
                if isinstance(update, dict):
                    uid = update.get("update_id")
                    if uid is not None:
                        next_offset = int(uid) + 1

                callback = (update.get("callback_query") or {}) if isinstance(update, dict) else {}
                data = callback.get("data") or ""
                msg_id = (callback.get("message") or {}).get("message_id")
                if msg_id != message_id_enviado:
                    continue
                if data == "ads_sim":
                    _responder_callback(callback.get("id"), "✅ Confirmado!")
                    return True
                if data == "ads_nao":
                    _responder_callback(callback.get("id"), "❌ Cancelado.")
                    return False

            time.sleep(5)

        return False
    except Exception as exc:
        logger.error("Telegram perguntar_gestor_e_aguardar erro: %s", exc)
        return False
