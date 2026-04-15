"""
integracoes/meta/meta_ads_client.py
Cliente de leitura de métricas de campanhas na Meta Ads API.
"""
import logging

from core.config import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID
from core.http_client import request

logger = logging.getLogger("meta_ads_client")
BASE = "https://graph.facebook.com/v19.0"


def _enabled() -> bool:
    return bool(META_ACCESS_TOKEN and META_AD_ACCOUNT_ID)


def listar_metricas_campanhas(periodo_dias: int = 1, limite: int = 50) -> list[dict]:
    """
    Retorna métricas por campanha ativa (status filtrado no próprio endpoint).
    """
    if not _enabled():
        logger.warning("Meta Ads não configurado (META_ACCESS_TOKEN/META_AD_ACCOUNT_ID).")
        return []

    try:
        account_id = str(META_AD_ACCOUNT_ID).replace("act_", "")
        url = f"{BASE}/act_{account_id}/insights"
        params = {
            "access_token": META_ACCESS_TOKEN,
            "level": "campaign",
            "date_preset": "today" if periodo_dias <= 1 else "last_7d",
            "fields": ",".join(
                [
                    "campaign_id",
                    "campaign_name",
                    "spend",
                    "cpc",
                    "ctr",
                    "frequency",
                    "actions",
                    "action_values",
                ]
            ),
            "limit": limite,
        }
        r = request("GET", url, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as exc:
        logger.error("Meta Ads listar_metricas_campanhas erro: %s", exc)
        return []


def _to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalizar_metrica_campanha(row: dict) -> dict:
    """
    Normaliza uma linha da API para estrutura padrão do projeto.
    """
    actions = row.get("actions") or []
    action_values = row.get("action_values") or []

    compras = 0.0
    receita = 0.0
    for a in actions:
        if a.get("action_type") in ("purchase", "offsite_conversion.purchase"):
            compras += _to_float(a.get("value", 0))
    for v in action_values:
        if v.get("action_type") in ("purchase", "offsite_conversion.purchase"):
            receita += _to_float(v.get("value", 0))

    gasto = _to_float(row.get("spend", 0))
    roas = (receita / gasto) if gasto > 0 else 0.0

    return {
        "id": row.get("campaign_id"),
        "nome": row.get("campaign_name", "campanha"),
        "gasto": round(gasto, 2),
        "cpc": _to_float(row.get("cpc", 0)),
        "ctr": _to_float(row.get("ctr", 0)),
        "frequencia": _to_float(row.get("frequency", 0)),
        "compras": compras,
        "receita": round(receita, 2),
        "roas": round(roas, 2),
    }
