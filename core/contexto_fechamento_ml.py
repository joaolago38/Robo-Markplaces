"""
core/contexto_fechamento_ml.py
Lê o último snapshot da conversão manicures (Ads Meta + oferta ativa)
para enriquecer o chat do Mercado Livre — sem efetivar Ads/publicação.

Só leitura de logs. A efetivação (ligar Ads, publicar IG/FB, reply Meta)
continua com flags + confirmação do gestor.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT

logger = logging.getLogger("contexto_fechamento_ml")

SNAPSHOT = ROOT / "logs" / "conversao_manicures_ultima.json"


def carregar_contexto_fechamento_ml() -> dict[str, Any]:
    """
    Retorna:
      sinal_ads, oferta (link_ml, nome, sku), link_ml, pronto_divulgar
    """
    data = ler_json(SNAPSHOT, default={})
    if not isinstance(data, dict):
        return {
            "ok": False,
            "motivo": "sem_snapshot_conversao",
            "sinal_ads": None,
            "oferta": None,
            "link_ml": "",
            "link_valido": False,
        }

    ads = data.get("ads") if isinstance(data.get("ads"), dict) else {}
    oferta = data.get("oferta") if isinstance(data.get("oferta"), dict) else {}
    link = str(oferta.get("link_ml") or "").strip()
    link_valido = bool(
        link.startswith("http")
        and "MLB_PREENCHER" not in link.upper()
        and "lista.mercadolivre" not in link.lower()
    )

    # Normaliza bloco que a análise espera
    sinal = dict(ads) if ads else None
    if sinal is not None and oferta.get("campanha_id"):
        sinal = {**sinal, "oferta_ativa_id": oferta.get("campanha_id")}

    return {
        "ok": True,
        "motivo": "snapshot_conversao",
        "sinal_ads": sinal,
        "oferta": {
            "campanha_id": oferta.get("campanha_id"),
            "campanha_nome": oferta.get("campanha_nome") or oferta.get("nome"),
            "sku": oferta.get("sku"),
            "link_ml": link,
            "preco_brl": oferta.get("preco_brl"),
            "escalou_ia": oferta.get("escalou_ia"),
            "modelo_ia": oferta.get("modelo_ia"),
        }
        if oferta
        else None,
        "link_ml": link,
        "link_valido": link_valido,
        "sustentabilidade": (ads.get("sustentabilidade") or {}).get("status")
        if isinstance(ads.get("sustentabilidade"), dict)
        else ads.get("status_sustentavel"),
        "atualizado_em": data.get("timestamp"),
    }
