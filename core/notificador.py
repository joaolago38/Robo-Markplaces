"""
core/notificador.py
Envia alertas via Telegram. Nunca lança exceção.
"""
import logging
import requests
from datetime import datetime
from core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GESTOR_CHAT_ID

logger = logging.getLogger("notificador")

def _enviar(chat_id: str, msg: str) -> bool:
    if not TELEGRAM_TOKEN or not chat_id:
        print(f"[TELEGRAM não configurado]\n{msg}")
        return True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram erro: {e}")
        return False

def alertar(msg: str) -> bool:
    return _enviar(TELEGRAM_CHAT_ID, f"🔔 *Alerta* {datetime.now().strftime('%d/%m %H:%M')}\n\n{msg}")

def alertar_gestor(msg: str) -> bool:
    return _enviar(TELEGRAM_GESTOR_CHAT_ID, f"📊 *Gestor* {datetime.now().strftime('%d/%m %H:%M')}\n\n{msg}")

def alertar_critico(msg: str) -> bool:
    alertar_gestor(f"🚨 CRÍTICO\n{msg}")
    return alertar(f"🚨 CRÍTICO\n{msg}")
