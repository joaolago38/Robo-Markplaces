"""
integracoes/ml/ml_product_ads.py
Product Ads do Mercado Livre — leitura e controle de campanhas (status/orçamento).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from core.config import (
    ACOS_MAXIMO,
    ML_ADS_ACOS_DIAS_LIMITE,
    ML_ADS_KILL_SWITCH,
    ML_ADS_ORCAMENTO_MAXIMO,
    ROOT,
)
from core.notificador import alertar_gestor
from integracoes.ml.ml_client import BASE, _enabled, _request_ml

logger = logging.getLogger("ml_product_ads")

_METRICS = "clicks,prints,ctr,cost,cpc,acos,roas,cvr,units_quantity,total_amount"
# Estado da última listagem — probe/escrita usam para distinguir 404 de "sem campanha".
_ULTIMA_LISTAGEM: dict = {"ok": True, "codigo": "", "advertiser_id": ""}
_ULTIMO_AVISO_404_TS: float = 0.0
_COOLDOWN_AVISO_404_SEG = 6 * 3600  # log: evita spam warn a cada ciclo 30min
_COOLDOWN_METRICA_404_SEG = 7 * 86400  # métrica: 1 lembrete/semana, não a cada job
_COOLDOWN_404_PATH = ROOT / "logs" / "ads_product_ads_404.json"


def ultima_listagem_codigo() -> str:
    return str(_ULTIMA_LISTAGEM.get("codigo") or "")


def _estado_404() -> dict:
    try:
        from core.atomic_io import ler_json

        data = ler_json(_COOLDOWN_404_PATH, default={})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _salvar_estado_404(estado: dict) -> None:
    try:
        from core.atomic_io import escrever_json_atomico

        escrever_json_atomico(_COOLDOWN_404_PATH, estado)
    except Exception:
        pass


def _avisar_ads_indisponivel_404(advertiser_id: str) -> None:
    """Warn + métrica com cooldown em disco (Actions é processo novo a cada job)."""
    global _ULTIMO_AVISO_404_TS
    agora = time.time()
    estado = _estado_404()
    ultimo_warn = float(estado.get("warn_ts") or _ULTIMO_AVISO_404_TS or 0)
    ultimo_metric = float(estado.get("metric_ts") or 0)
    if (agora - ultimo_warn) < _COOLDOWN_AVISO_404_SEG:
        logger.debug(
            "ML listar_campanhas: Product Ads ainda 404 advertiser=%s (aviso em cooldown)",
            advertiser_id,
        )
        _ULTIMO_AVISO_404_TS = ultimo_warn
        return
    _ULTIMO_AVISO_404_TS = agora
    estado["warn_ts"] = agora
    estado["advertiser_id"] = advertiser_id or ""
    if (agora - ultimo_metric) >= _COOLDOWN_METRICA_404_SEG:
        try:
            from core.datadog_metrics import incrementar

            incrementar(
                "ads.indisponivel",
                tags=["motivo:http_404", f"advertiser:{advertiser_id or 'desconhecido'}"],
            )
            estado["metric_ts"] = agora
        except Exception:
            pass
    _salvar_estado_404(estado)
    logger.warning(
        "ML listar_campanhas: Product Ads indisponível (HTTP 404) "
        "advertiser=%s — confira escopos advertising / ID no DevCenter "
        "(próximos avisos em cooldown %sh)",
        advertiser_id,
        _COOLDOWN_AVISO_404_SEG // 3600,
    )


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


def _met(metrics: dict | None, row: dict, chave: str, *, inteiro: bool = False):
    src = metrics if isinstance(metrics, dict) else {}
    bruto = src.get(chave)
    if bruto is None:
        bruto = row.get(chave)
    try:
        if inteiro:
            return int(float(bruto or 0))
        return float(bruto or 0)
    except (TypeError, ValueError):
        return 0 if inteiro else 0.0


def _normalizar_campanha(row: dict) -> dict:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
    return {
        "id": str(row.get("id") or row.get("campaign_id") or ""),
        "nome": str(row.get("name") or row.get("campaign_name") or ""),
        "status": str(row.get("status") or ""),
        "budget": float(row.get("budget") or 0),
        "acos": _met(metrics, row, "acos"),
        "roas": _met(metrics, row, "roas"),
        "cost": _met(metrics, row, "cost"),
        "clicks": _met(metrics, row, "clicks", inteiro=True),
        "prints": _met(metrics, row, "prints", inteiro=True),
        "ctr": _met(metrics, row, "ctr"),
        "cvr": _met(metrics, row, "cvr"),
        "cpc": _met(metrics, row, "cpc"),
        "units_quantity": _met(metrics, row, "units_quantity", inteiro=True),
        "total_amount": _met(metrics, row, "total_amount"),
    }


def emitir_metricas_visibilidade_ads(campanhas: list[dict] | None) -> None:
    """Gauges de CTR/CVR/prints para Datadog. Não decide pausa (pausa continua ACOS)."""
    try:
        from core.datadog_metrics import gauge

        rows = [c for c in (campanhas or []) if isinstance(c, dict)]
        prints = sum(int(c.get("prints") or 0) for c in rows)
        clicks = sum(int(c.get("clicks") or 0) for c in rows)
        ctrs = [float(c.get("ctr") or 0) for c in rows if float(c.get("ctr") or 0) > 0]
        cvrs = [float(c.get("cvr") or 0) for c in rows if float(c.get("cvr") or 0) > 0]
        cpcs = [float(c.get("cpc") or 0) for c in rows if float(c.get("cpc") or 0) > 0]
        gauge("ads.campanhas_n", float(len(rows)))
        gauge("ads.prints_total", float(prints))
        gauge("ads.clicks_total", float(clicks))
        gauge("ads.ctr_medio", (sum(ctrs) / len(ctrs)) if ctrs else 0.0)
        gauge("ads.cvr_medio", (sum(cvrs) / len(cvrs)) if cvrs else 0.0)
        gauge("ads.cpc_medio", (sum(cpcs) / len(cpcs)) if cpcs else 0.0)
        gauge("ads.ctr_cvr_visivel", 1.0 if prints or ctrs or cvrs else 0.0)
    except Exception:
        pass


def listar_campanhas(
    advertiser_id: str = "",
    *,
    dias: int = 14,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Lista campanhas Product Ads com métricas do período. Nunca lança exceção."""
    global _ULTIMA_LISTAGEM
    _ULTIMA_LISTAGEM = {"ok": True, "codigo": "", "advertiser_id": advertiser_id or ""}

    if not _enabled():
        _ULTIMA_LISTAGEM = {"ok": False, "codigo": "ml_desabilitado", "advertiser_id": ""}
        return []

    if not advertiser_id:
        adv = obter_advertiser()
        if not adv.get("ok"):
            codigo = str(adv.get("codigo") or "sem_advertiser")
            _ULTIMA_LISTAGEM = {
                "ok": False,
                "codigo": codigo,
                "advertiser_id": "",
            }
            logger.warning("listar_campanhas: %s", adv.get("erro"))
            return []
        advertiser_id = adv["advertiser_id"]
        _ULTIMA_LISTAGEM["advertiser_id"] = advertiser_id

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
        _ULTIMA_LISTAGEM = {
            "ok": True,
            "codigo": "ok",
            "advertiser_id": advertiser_id,
        }
        campanhas = [_normalizar_campanha(row) for row in rows if isinstance(row, dict)]
        emitir_metricas_visibilidade_ads(campanhas)
        return campanhas
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # 404 = advertiser/campanhas inexistente ou Product Ads sem escopo —
        # config, não queda do robô. Evita ERROR recorrente no Datadog.
        if status == 404:
            _ULTIMA_LISTAGEM = {
                "ok": False,
                "codigo": "http_404",
                "advertiser_id": advertiser_id,
            }
            _avisar_ads_indisponivel_404(advertiser_id)
            emitir_metricas_visibilidade_ads([])
            # Não incrementa ads.probe_falha: 404 de config conhecida poluía
            # o monitor P1 até o escopo Ads ser corrigido no DevCenter.
        else:
            _ULTIMA_LISTAGEM = {
                "ok": False,
                "codigo": f"http_{status}" if status else "http_erro",
                "advertiser_id": advertiser_id,
            }
            logger.error("ML listar_campanhas erro: %s", exc)
            try:
                from core.datadog_metrics import incrementar

                incrementar(
                    "ads.probe_falha",
                    tags=["motivo:http_erro", "origem:listar_campanhas"],
                )
            except Exception:
                pass
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
        codigo_lista = ultima_listagem_codigo()
        if codigo_lista == "http_404":
            return {
                "ok": False,
                "codigo": "http_404",
                "erro": (
                    "Product Ads indisponível (HTTP 404) — escopos advertising "
                    "ou advertiser_id no DevCenter"
                ),
            }
        if codigo_lista and codigo_lista not in {"ok", "sem_campanhas"}:
            return {
                "ok": False,
                "codigo": codigo_lista,
                "erro": f"Listagem Product Ads falhou ({codigo_lista})",
            }
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
