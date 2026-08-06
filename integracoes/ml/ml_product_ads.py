"""
integracoes/ml/ml_product_ads.py
Product Ads do Mercado Livre — leitura e controle de campanhas (status/orçamento).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from core.config import (
    ACOS_MAXIMO,
    ML_ADS_ACOS_DIAS_LIMITE,
    ML_ADS_KILL_SWITCH,
    ML_ADS_ORCAMENTO_MAXIMO,
)
from core.notificador import alertar_gestor
from integracoes.ml.ml_client import BASE, _enabled, _request_ml

logger = logging.getLogger("ml_product_ads")

_METRICS = "clicks,prints,ctr,cost,cpc,acos,roas,cvr,units_quantity,total_amount"


def _notificar_dry_run(acao: str, detalhe: str) -> None:
    try:
        alertar_gestor(f"🔶 DRY-RUN ML Product Ads\n{acao}\n{detalhe}")
    except Exception:
        pass


def _guardrails_escrita(budget: float | None = None) -> dict | None:
    """Retorna dict de erro se algum guardrail bloquear; None se OK."""
    from core.guardrails import bloqueio_escrita_global

    if bloqueio := bloqueio_escrita_global():
        return bloqueio
    if ML_ADS_KILL_SWITCH:
        return {"ok": False, "erro": "ML_ADS_KILL_SWITCH ativo — escrita bloqueada"}
    if budget is not None and budget > ML_ADS_ORCAMENTO_MAXIMO:
        return {
            "ok": False,
            "erro": f"orçamento R$ {budget} excede ML_ADS_ORCAMENTO_MAXIMO ({ML_ADS_ORCAMENTO_MAXIMO})",
        }
    return None


def obter_advertiser() -> dict:
    """
    Descobre o advertiser PADS do vendedor.
    Retorna {ok, advertiser_id, site_id} ou {ok: False, erro, codigo?}.
    """
    if not _enabled():
        return {"ok": False, "erro": "Mercado Livre não configurado"}

    try:
        r = _request_ml(
            "GET",
            f"{BASE}/advertising/advertisers",
            headers={"Api-Version": "1"},
            params={"product_id": "PADS"},
            timeout=20,
        )
        if r.status_code == 404:
            body = r.json() if r.content else {}
            texto = str(body).lower()
            if "permission" in texto or "no permissions" in texto:
                return {
                    "ok": False,
                    "erro": "Publicidade não habilitada (Mi perfil > Publicidad)",
                    "codigo": "sem_permissao",
                }
            return {"ok": False, "erro": f"Advertiser não encontrado (HTTP 404): {body}"}

        r.raise_for_status()
        data = r.json() or {}
        if isinstance(data, list):
            advertisers = data
        else:
            advertisers = data.get("advertisers") or data.get("results") or [data]

        if not advertisers:
            return {"ok": False, "erro": "Nenhum advertiser PADS retornado"}

        adv = advertisers[0] if isinstance(advertisers[0], dict) else {}
        advertiser_id = str(adv.get("advertiser_id") or adv.get("id") or "").strip()
        site_id = str(
            adv.get("site_id") or adv.get("advertiser_site_id") or adv.get("site") or "MLB"
        ).strip()

        if not advertiser_id:
            return {"ok": False, "erro": "Resposta sem advertiser_id", "raw": adv}

        return {"ok": True, "advertiser_id": advertiser_id, "site_id": site_id, "raw": adv}
    except Exception as exc:
        logger.error("ML obter_advertiser erro: %s", exc)
        return {"ok": False, "erro": str(exc)}


def _periodo_ads(dias: int) -> tuple[str, str]:
    tz = timezone(timedelta(hours=-3))
    hoje = datetime.now(tz).date()
    return (hoje - timedelta(days=dias)).isoformat(), hoje.isoformat()


def _normalizar_campanha(row: dict) -> dict:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
    return {
        "id": str(row.get("id") or row.get("campaign_id") or ""),
        "nome": str(row.get("name") or row.get("campaign_name") or ""),
        "status": str(row.get("status") or ""),
        "budget": float(row.get("budget") or 0),
        "acos": float((metrics or {}).get("acos") or row.get("acos") or 0),
        "roas": float((metrics or {}).get("roas") or row.get("roas") or 0),
        "cost": float((metrics or {}).get("cost") or row.get("cost") or 0),
        "clicks": int((metrics or {}).get("clicks") or row.get("clicks") or 0),
    }


def listar_campanhas(
    advertiser_id: str = "",
    *,
    dias: int = 14,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Lista campanhas Product Ads com métricas do período. Nunca lança exceção."""
    if not _enabled():
        return []

    if not advertiser_id:
        adv = obter_advertiser()
        if not adv.get("ok"):
            logger.warning("listar_campanhas: %s", adv.get("erro"))
            return []
        advertiser_id = adv["advertiser_id"]

    try:
        date_from, date_to = _periodo_ads(dias)
        r = _request_ml(
            "GET",
            f"{BASE}/advertising/advertisers/{advertiser_id}/product_ads/campaigns",
            headers={"api-version": "2"},
            params={
                "limit": limit,
                "offset": offset,
                "date_from": date_from,
                "date_to": date_to,
                "metrics": _METRICS,
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json() or {}
        rows = body.get("results") or body.get("campaigns") or body.get("data") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        return [_normalizar_campanha(row) for row in rows if isinstance(row, dict)]
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # 404 = advertiser/campanhas inexistente ou Product Ads sem escopo —
        # config, não queda do robô. Evita ERROR recorrente no Datadog.
        if status == 404:
            logger.warning(
                "ML listar_campanhas: Product Ads indisponível (HTTP 404) "
                "advertiser=%s — confira escopos advertising / ID no DevCenter",
                advertiser_id,
            )
            try:
                from core.datadog_metrics import incrementar

                incrementar(
                    "ads.probe_falha",
                    tags=["motivo:http_404", "origem:listar_campanhas"],
                )
            except Exception:
                pass
        else:
            logger.error("ML listar_campanhas erro: %s", exc)
        return []


def obter_status_product_ads_item(item_id: str) -> dict:
    """Status Product Ads de um item (hold/idle/active etc.)."""
    item_id = (item_id or "").strip()
    if not item_id or not _enabled():
        return {"ok": False, "erro": "item_id ausente ou ML não configurado"}
    try:
        r = _request_ml(
            "GET",
            f"{BASE}/advertising/product_ads/items/{item_id}",
            headers={"api-version": "2"},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json() or {}
        return {
            "ok": True,
            "item_id": item_id,
            "status": str(body.get("status") or ""),
            "campaign_id": str(body.get("campaign_id") or ""),
            "raw": body,
        }
    except Exception as exc:
        logger.error("ML obter_status_product_ads_item erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "item_id": item_id, "erro": str(exc)}


def _atualizar_campanha(
    campaign_id: str,
    advertiser_site_id: str,
    payload: dict,
    acao: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
    budget: float | None = None,
) -> dict:
    campaign_id = (campaign_id or "").strip()
    advertiser_site_id = (advertiser_site_id or "MLB").strip()
    if not campaign_id:
        return {"ok": False, "erro": "campaign_id ausente", "acao": acao, "dry_run": dry_run}
    if not _enabled():
        return {"ok": False, "erro": "ML não configurado", "acao": acao, "dry_run": dry_run}

    bloqueio = _guardrails_escrita(budget)
    if bloqueio and not dry_run:
        return {**bloqueio, "acao": acao, "dry_run": False, "campaign_id": campaign_id}

    detalhe = f"campanha={campaign_id} site={advertiser_site_id} payload={payload}"

    if dry_run:
        logger.info("[DRY-RUN] ML Product Ads %s — %s", acao, detalhe)
        _notificar_dry_run(acao, detalhe)
        return {
            "ok": True,
            "dry_run": True,
            "acao": acao,
            "campaign_id": campaign_id,
            "payload": payload,
        }

    if not confirmar:
        return {
            "ok": False,
            "dry_run": False,
            "acao": acao,
            "campaign_id": campaign_id,
            "erro": "confirmar=True obrigatório para escrita em campanha",
        }

    if bloqueio:
        return {**bloqueio, "acao": acao, "dry_run": False, "campaign_id": campaign_id}

    try:
        r = _request_ml(
            "PUT",
            f"{BASE}/marketplace/advertising/{advertiser_site_id}/product_ads/campaigns/{campaign_id}",
            headers={"api-version": "2"},
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        body = r.json() or {}
        logger.info("ML Product Ads %s ok campanha=%s", acao, campaign_id)
        return {
            "ok": True,
            "dry_run": False,
            "acao": acao,
            "campaign_id": campaign_id,
            "status": body.get("status"),
            "budget": body.get("budget"),
        }
    except Exception as exc:
        logger.error("ML Product Ads %s erro campanha=%s: %s", acao, campaign_id, exc)
        return {"ok": False, "dry_run": False, "acao": acao, "campaign_id": campaign_id, "erro": str(exc)}


def probe_escrita_product_ads() -> dict:
    """
    Testa se a API de escrita Product Ads está autorizada (scopes).
    Faz PUT idempotente (mesmo status atual) na 1ª campanha.
    Retorna {ok, codigo, erro?} — não lança.
    """
    adv = obter_advertiser()
    if not adv.get("ok"):
        return {
            "ok": False,
            "codigo": str(adv.get("codigo") or "sem_advertiser"),
            "erro": adv.get("erro") or "advertiser indisponível",
        }
    campanhas = listar_campanhas(advertiser_id=adv.get("advertiser_id"))
    if not campanhas:
        return {
            "ok": False,
            "codigo": "sem_campanhas",
            "erro": "Nenhuma campanha Product Ads para testar escrita",
        }
    camp = campanhas[0]
    cid = str(camp.get("id") or "").strip()
    status_atual = str(camp.get("status") or "paused").lower()
    if status_atual not in {"active", "paused"}:
        status_atual = "paused"
    out = _atualizar_campanha(
        cid,
        adv["site_id"],
        {"status": status_atual, "channel": "marketplace"},
        "probe_escrita",
        dry_run=False,
        confirmar=True,
    )
    if out.get("ok"):
        return {"ok": True, "codigo": "ok", "campaign_id": cid}
    erro = str(out.get("erro") or "escrita falhou")
    codigo = "http_401" if "401" in erro else "escrita_falhou"
    return {"ok": False, "codigo": codigo, "erro": erro, "campaign_id": cid}


def pausar_campanha(
    campaign_id: str,
    advertiser_site_id: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
) -> dict:
    return _atualizar_campanha(
        campaign_id,
        advertiser_site_id,
        {"status": "paused", "channel": "marketplace"},
        "pausar_campanha",
        dry_run=dry_run,
        confirmar=confirmar,
    )


def ativar_campanha(
    campaign_id: str,
    advertiser_site_id: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
) -> dict:
    return _atualizar_campanha(
        campaign_id,
        advertiser_site_id,
        {"status": "active", "channel": "marketplace"},
        "ativar_campanha",
        dry_run=dry_run,
        confirmar=confirmar,
    )


def definir_orcamento(
    campaign_id: str,
    valor: float,
    advertiser_site_id: str,
    *,
    dry_run: bool = True,
    confirmar: bool = False,
    roas_target: float | None = None,
) -> dict:
    payload: dict = {
        "budget": float(valor),
        "channel": "marketplace",
        "strategy": "profitability",
    }
    if roas_target is not None:
        payload["roas_target"] = float(roas_target)
    return _atualizar_campanha(
        campaign_id,
        advertiser_site_id,
        payload,
        "definir_orcamento",
        dry_run=dry_run,
        confirmar=confirmar,
        budget=float(valor),
    )


def campanhas_acos_acima_limite(
    limite: float | None = None,
    dias: int | None = None,
) -> list[dict]:
    """Campanhas com ACOS acima do limite configurado (ACOS_MAXIMO)."""
    lim = limite if limite is not None else ACOS_MAXIMO
    campanhas = listar_campanhas(dias=dias or ML_ADS_ACOS_DIAS_LIMITE)
    return [c for c in campanhas if c.get("acos", 0) > lim and c.get("cost", 0) > 0]


def aplicar_decisao_campanhas(
    decisao: str,
    *,
    budget: float = 0.0,
    dry_run: bool = True,
    confirmar: bool = False,
    campaign_ids: list[str] | None = None,
) -> list[dict]:
    """
    Aplica pausar/ativar(+orçamento)/escalar em todas as campanhas (ou nas IDs informadas).
    Em ligar/ativar com budget > 0, ativa e define o orçamento diário.
    Usado pelo agente após confirmação do gestor.
    """
    adv = obter_advertiser()
    if not adv.get("ok"):
        return [{"ok": False, "erro": adv.get("erro")}]

    site_id = adv["site_id"]
    campanhas = listar_campanhas(advertiser_id=adv["advertiser_id"])
    if campaign_ids:
        ids_set = set(campaign_ids)
        campanhas = [c for c in campanhas if c.get("id") in ids_set]

    resultados: list[dict] = []
    for camp in campanhas:
        cid = camp.get("id")
        if not cid:
            continue
        if decisao == "pausar":
            resultados.append(pausar_campanha(cid, site_id, dry_run=dry_run, confirmar=confirmar))
        elif decisao in ("ligar", "ativar"):
            # Ligar = ativar status + orçamento inicial (BUDGET_FASE_INICIO via agente).
            resultados.append(ativar_campanha(cid, site_id, dry_run=dry_run, confirmar=confirmar))
            if budget > 0:
                resultados.append(
                    definir_orcamento(cid, budget, site_id, dry_run=dry_run, confirmar=confirmar)
                )
        elif decisao == "escalar" and budget > 0:
            resultados.append(
                definir_orcamento(cid, budget, site_id, dry_run=dry_run, confirmar=confirmar)
            )
    return resultados
