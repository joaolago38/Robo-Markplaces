"""
agentes/ml/agente_ml.py
Agente do Mercado Livre.
Contratos: spec/spec.yaml > marketplaces[mercadolivre]
"""
import logging
import time
import requests
from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID, MARGEM_MINIMA
from core.claude_client import responder_chat
from core.notificador import alertar, alertar_critico
from integracoes.bling.bling_client import buscar_produto

logger = logging.getLogger("agente_ml")
BASE = "https://api.mercadolibre.com"

def _h():
    return {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}

def buscar_perguntas() -> list[dict]:
    try:
        r = requests.get(f"{BASE}/my/received_questions/search",
            headers=_h(), params={"status": "UNANSWERED", "seller_id": ML_SELLER_ID}, timeout=15)
        r.raise_for_status()
        return r.json().get("questions", [])
    except Exception as e:
        logger.error(f"ML buscar_perguntas: {e}")
        return []

def responder(pergunta_id: str, texto: str) -> bool:
    try:
        r = requests.post(f"{BASE}/answers", headers=_h(),
            json={"question_id": pergunta_id, "text": texto}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"ML responder {pergunta_id}: {e}")
        return False

def ciclo_chat() -> int:
    perguntas = buscar_perguntas()
    ok = 0
    for p in perguntas:
        produto = buscar_produto(p.get("item_id", "")) or {}
        resposta = responder_chat(p.get("text", ""), produto, "mercadolivre")
        if responder(p["id"], resposta):
            ok += 1
        time.sleep(1)
    logger.info(f"ML chat: {ok}/{len(perguntas)} respondidas")
    return ok

def verificar_reputacao() -> dict:
    try:
        r = requests.get(f"{BASE}/users/{ML_SELLER_ID}", headers=_h(), timeout=15)
        r.raise_for_status()
        rep = r.json().get("seller_reputation", {})
        nivel = rep.get("level_id", "")
        pct   = rep.get("metrics", {}).get("claims", {}).get("rate", 0)
        if pct > 0.01:
            alertar_critico(f"ML: reclamações em {pct*100:.1f}% — acima de 1%!")
        logger.info(f"ML reputação: {nivel} | reclamações: {pct*100:.2f}%")
        return {"nivel": nivel, "reclamacoes_pct": pct}
    except Exception as e:
        logger.error(f"ML reputacao: {e}")
        return {}

def executar() -> dict:
    logger.info("=== Agente ML iniciado ===")
    return {"chat": ciclo_chat(), "reputacao": verificar_reputacao()}
