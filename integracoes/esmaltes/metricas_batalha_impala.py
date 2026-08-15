"""
integracoes/esmaltes/metricas_batalha_impala.py
Consolida anúncios Impala amostrados no ML e compara com nossos kits.

Não é crawl total do marketplace — usa a amostra deduplicada das varreduras
(kits / concorrentes / snapshot). Emite gauges robo.impala.batalha.*.

Tags: tam:, kit:, papel:, prio: — nunca sku:/termo:/item:.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.analise_anita import detectar_marca
from integracoes.esmaltes.decisao_dia_esmaltes import carregar_skus_guerra
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag

logger = logging.getLogger("metricas_batalha_impala")

SNAPSHOT_PATH = ROOT / "logs" / "impala_batalha_ultima.json"
# MLB + 1–2 dígitos (ex.: MLB1) é lixo de amostra, não anúncio real.
_ITEM_ID_LIXO = re.compile(r"^MLB\d{1,2}$", re.I)


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _eh_impala(anuncio: dict[str, Any]) -> bool:
    marca = str(anuncio.get("marca") or "").strip().lower()
    if marca == "impala":
        return True
    return detectar_marca(str(anuncio.get("titulo") or "")).lower() == "impala"


def _qtd_kit(anuncio: dict[str, Any]) -> int | None:
    try:
        q = int(anuncio.get("qtd_kit") or 0)
        return q if q >= 2 else None
    except (TypeError, ValueError):
        return None


def _qtd_nosso_sku(produto: dict[str, Any]) -> int | None:
    """Infere tamanho do kit pelo SKU / nome / cores."""
    sku = str(produto.get("sku") or "").upper()
    for token in sku.replace("-", " ").split():
        if token.isdigit() and 2 <= int(token) <= 50:
            return int(token)
    cores = produto.get("cores")
    if isinstance(cores, list) and len(cores) >= 2:
        return len(cores)
    nome = str(produto.get("nome") or "")
    m = re.search(r"\bkit\s+(\d+)\b", nome, re.I)
    if m:
        return int(m.group(1))
    return None


def _preco_nosso(produto: dict[str, Any]) -> float:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return _f(ml.get("preco") or produto.get("preco"))


def _item_id_amostra_ok(item_id: str) -> bool:
    iid = (item_id or "").strip().upper()
    if not iid.startswith("MLB") or "PREENCHER" in iid:
        return False
    return _ITEM_ID_LIXO.fullmatch(iid) is None


def extrair_anuncios_impala(kits_unicos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra/dedupe anúncios Impala da amostra de kits."""
    por_id: dict[str, dict[str, Any]] = {}
    for a in kits_unicos or []:
        if not isinstance(a, dict) or not _eh_impala(a):
            continue
        iid = str(a.get("item_id") or "").strip().upper()
        if not _item_id_amostra_ok(iid):
            continue
        atual = por_id.get(iid)
        vend = int(a.get("quantidade_vendida") or 0)
        if not atual or vend > int(atual.get("quantidade_vendida") or 0):
            por_id[iid] = dict(a)
            por_id[iid]["marca"] = "Impala"
    return list(por_id.values())


def montar_batalha(
    *,
    anuncios_impala: list[dict[str, Any]],
    produtos: list[dict[str, Any]] | None = None,
    guerra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """KPIs: com quantos lutamos + gap vs nossos preços por tamanho/kit."""
    produtos = produtos if produtos is not None else carregar_produtos_catalogo()
    guerra = guerra if guerra is not None else carregar_skus_guerra()
    papel_por_sku = {
        str(g.get("sku") or "").strip().upper(): str(g.get("papel") or "guerra").lower()
        for g in guerra
        if str(g.get("sku") or "").strip()
    }

    precos = [_f(a.get("preco")) for a in anuncios_impala if _f(a.get("preco")) > 0]
    vendas = sum(int(a.get("quantidade_vendida") or 0) for a in anuncios_impala)
    sellers = {
        str(a.get("seller_id") or "").strip()
        for a in anuncios_impala
        if str(a.get("seller_id") or "").strip()
    }

    por_tam: dict[int, list[dict[str, Any]]] = {}
    for a in anuncios_impala:
        q = _qtd_kit(a)
        if q is None:
            continue
        por_tam.setdefault(q, []).append(a)

    buckets_tam: list[dict[str, Any]] = []
    for tam, ads in sorted(por_tam.items()):
        ps = [_f(x.get("preco")) for x in ads if _f(x.get("preco")) > 0]
        buckets_tam.append(
            {
                "tam": tam,
                "anuncios": len(ads),
                "preco_min": round(min(ps), 2) if ps else 0.0,
                "preco_mediano": round(float(statistics.median(ps)), 2) if ps else 0.0,
                "preco_medio": round(sum(ps) / len(ps), 2) if ps else 0.0,
                "vendas": sum(int(x.get("quantidade_vendida") or 0) for x in ads),
            }
        )

    comparacoes: list[dict[str, Any]] = []
    acima = 0
    abaixo_ou_igual = 0
    for p in produtos or []:
        if not isinstance(p, dict):
            continue
        sku = str(p.get("sku") or "").strip().upper()
        if not sku:
            continue
        tam = _qtd_nosso_sku(p)
        nosso = _preco_nosso(p)
        rival_min = None
        rival_n = 0
        fonte_rival = "ausente"
        if tam and tam in por_tam:
            ps = [_f(x.get("preco")) for x in por_tam[tam] if _f(x.get("preco")) > 0]
            rival_n = len(por_tam[tam])
            if ps:
                rival_min = round(min(ps), 2)
                fonte_rival = "ao_vivo"
        mercado = _f(p.get("preco_ml_mercado"))
        rival_ref_catalogo = round(mercado, 2) if mercado > 0 else None

        gap = None
        if fonte_rival == "ao_vivo" and nosso > 0 and rival_min and rival_min > 0:
            gap = round(100.0 * (nosso - rival_min) / rival_min, 2)
            if gap > 0:
                acima += 1
            else:
                abaixo_ou_igual += 1

        comparacoes.append(
            {
                "sku": sku,
                "papel": papel_por_sku.get(sku, "catalogo"),
                "prio": str(p.get("prioridade") or "p?").lower(),
                "kit_tag": kit_tag(sku),
                "tam": tam,
                "nosso_preco": nosso,
                "rival_min": rival_min,
                "rival_ref_catalogo": rival_ref_catalogo,
                "fonte_rival": fonte_rival,
                "rivais_no_tam": rival_n,
                "gap_pct": gap,
                "mlb_ok": str(
                    ((p.get("canais") or {}).get("mercadolivre") or {}).get("item_id") or ""
                )
                .upper()
                .startswith("MLB")
                and "PREENCHER"
                not in str(
                    ((p.get("canais") or {}).get("mercadolivre") or {}).get("item_id") or ""
                ).upper(),
            }
        )

    top = sorted(
        anuncios_impala,
        key=lambda x: (
            int(x.get("quantidade_vendida") or 0),
            -_f(x.get("preco")),
        ),
        reverse=True,
    )[:12]

    return {
        "anuncios_unicos": len(anuncios_impala),
        "sellers_unicos": len(sellers),
        "vendas_proxy": vendas,
        "preco_min": round(min(precos), 2) if precos else 0.0,
        "preco_mediano": round(float(statistics.median(precos)), 2) if precos else 0.0,
        "preco_medio": round(sum(precos) / len(precos), 2) if precos else 0.0,
        "preco_max": round(max(precos), 2) if precos else 0.0,
        "por_tamanho": buckets_tam,
        "comparacoes": comparacoes,
        "nossos_acima_rival": acima,
        "nossos_abaixo_ou_igual": abaixo_ou_igual,
        "comparacoes_ao_vivo": sum(1 for c in comparacoes if c.get("fonte_rival") == "ao_vivo"),
        "comparacoes_sem_rival": sum(1 for c in comparacoes if c.get("fonte_rival") != "ao_vivo"),
        "top_anuncios": [
            {
                "item_id": t.get("item_id"),
                "titulo": str(t.get("titulo") or "")[:80],
                "preco": t.get("preco"),
                "quantidade_vendida": t.get("quantidade_vendida"),
                "qtd_kit": t.get("qtd_kit"),
                "seller_id": t.get("seller_id"),
            }
            for t in top
        ],
    }


def emitir_metricas_batalha_impala(
    batalha: dict[str, Any] | None = None,
    *,
    kits_unicos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Monta (se preciso) e envia gauges. Nunca lança."""
    try:
        if batalha is None:
            anuncios = extrair_anuncios_impala(kits_unicos or [])
            batalha = montar_batalha(anuncios_impala=anuncios)

        gauge("impala.batalha.anuncios_unicos", float(batalha.get("anuncios_unicos") or 0))
        gauge("impala.batalha.sellers_unicos", float(batalha.get("sellers_unicos") or 0))
        gauge("impala.batalha.vendas_proxy", float(batalha.get("vendas_proxy") or 0))
        gauge("impala.batalha.preco_min", float(batalha.get("preco_min") or 0))
        gauge("impala.batalha.preco_mediano", float(batalha.get("preco_mediano") or 0))
        gauge("impala.batalha.preco_medio", float(batalha.get("preco_medio") or 0))
        gauge("impala.batalha.preco_max", float(batalha.get("preco_max") or 0))
        gauge("impala.batalha.nossos_acima_rival", float(batalha.get("nossos_acima_rival") or 0))
        gauge(
            "impala.batalha.nossos_abaixo_ou_igual",
            float(batalha.get("nossos_abaixo_ou_igual") or 0),
        )
        gauge("impala.batalha.comparacoes_ao_vivo", float(batalha.get("comparacoes_ao_vivo") or 0))
        gauge("impala.batalha.comparacoes_sem_rival", float(batalha.get("comparacoes_sem_rival") or 0))

        for b in batalha.get("por_tamanho") or []:
            tags = [f"tam:{int(b.get('tam') or 0)}"]
            gauge("impala.batalha.tam_anuncios", float(b.get("anuncios") or 0), tags=tags)
            gauge("impala.batalha.tam_preco_min", float(b.get("preco_min") or 0), tags=tags)
            gauge("impala.batalha.tam_preco_mediano", float(b.get("preco_mediano") or 0), tags=tags)
            gauge("impala.batalha.tam_vendas", float(b.get("vendas") or 0), tags=tags)

        for c in batalha.get("comparacoes") or []:
            tags = [
                c.get("kit_tag") or "kit:x",
                f"papel:{c.get('papel') or 'catalogo'}",
                f"prio:{c.get('prio') or 'p?'}",
            ]
            if c.get("tam"):
                tags.append(f"tam:{int(c['tam'])}")
            tags.append(f"fonte:{c.get('fonte_rival') or 'ausente'}")
            gauge("impala.batalha.nosso_preco", float(c.get("nosso_preco") or 0), tags=tags)
            if c.get("fonte_rival") == "ao_vivo" and c.get("rival_min") is not None:
                gauge("impala.batalha.rival_min", float(c["rival_min"]), tags=tags)
            if c.get("fonte_rival") == "ao_vivo" and c.get("gap_pct") is not None:
                gauge("impala.batalha.gap_vs_rival_pct", float(c["gap_pct"]), tags=tags)
            gauge("impala.batalha.rivais_no_tam", float(c.get("rivais_no_tam") or 0), tags=tags)

        incrementar("impala.batalha.rodadas")
        return {"ok": True, **{k: batalha[k] for k in batalha if k not in ("comparacoes", "top_anuncios", "por_tamanho")}}
    except Exception as exc:
        logger.warning("emitir_metricas_batalha_impala: %s", exc)
        incrementar("impala.batalha.erro")
        return {"ok": False, "erro": str(exc)}


def processar_e_persistir(
    kits_unicos: list[dict[str, Any]],
    *,
    origem: str = "kits_monitor",
) -> dict[str, Any]:
    """Extrai Impala, monta batalha, persiste snapshot e emite métricas."""
    from datetime import datetime, timezone

    anuncios = extrair_anuncios_impala(kits_unicos)
    amostra_impala = len(anuncios)
    anuncios_reais = list(anuncios)
    produtos_reais = carregar_produtos_catalogo()
    overlay = False
    batalha_sim: dict[str, Any] | None = None
    try:
        from core.config import SIMULACAO_GUERRA_IMPALA_OPERACIONAL
        from integracoes.esmaltes.simulacao_guerra_impala import aplicar_visao_operacional

        if SIMULACAO_GUERRA_IMPALA_OPERACIONAL:
            prods_s, ads_s, overlay = aplicar_visao_operacional(anuncios_reais, produtos=produtos_reais)
            if overlay:
                batalha_sim = montar_batalha(anuncios_impala=ads_s, produtos=prods_s)
                batalha_sim = {**batalha_sim, "visao_operacional": True, "cenario": "igual_para_igual"}
    except Exception as exc:
        logger.warning("visao operacional: %s", exc)
        overlay = False
        batalha_sim = None
    # Datadog e golpe/agir usam só o real (sem MLB9000 / rivais de fixture).
    batalha = montar_batalha(anuncios_impala=anuncios_reais, produtos=produtos_reais)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origem": origem,
        "batalha": batalha,
        "batalha_sim": batalha_sim,
        "amostra_impala": amostra_impala,
        "visao_operacional": overlay,
        "anuncios_reais": [
            {
                "item_id": a.get("item_id"),
                "titulo": str(a.get("titulo") or "")[:120],
                "preco": a.get("preco"),
                "qtd_kit": a.get("qtd_kit"),
            }
            for a in anuncios_reais[:40]
            if isinstance(a, dict)
        ],
    }
    try:
        escrever_json_atomico(SNAPSHOT_PATH, payload)
    except Exception as exc:
        logger.warning("snapshot batalha: %s", exc)
    emit = emitir_metricas_batalha_impala(batalha)
    try:
        gauge("impala.guerra.overlay", 1.0 if overlay else 0.0)
    except Exception:
        pass
    agir: dict[str, Any] = {}
    golpe: dict[str, Any] = {}
    radar: dict[str, Any] = {}
    try:
        from integracoes.esmaltes.decisao_batalha_agir import processar_agir_batalha

        agir = processar_agir_batalha(batalha)
        payload["agir"] = {
            "criticas": agir.get("criticas"),
            "por_acao": agir.get("por_acao"),
            "top": agir.get("top"),
            "resumo_claude": agir.get("resumo_claude"),
        }
        try:
            from integracoes.esmaltes.golpe_guerra_impala import processar_golpe_batalha

            golpe = processar_golpe_batalha(batalha, produtos=produtos_reais, enviar_alerta=True)
            payload["golpe"] = {
                "disparar": golpe.get("disparar"),
                "classificacao": (golpe.get("golpe") or {}).get("classificacao"),
                "sku": (golpe.get("golpe") or {}).get("sku"),
                "arma": (golpe.get("golpe") or {}).get("arma"),
            }
        except Exception as exc:
            logger.warning("golpe guerra: %s", exc)
        try:
            from integracoes.esmaltes.radar_diferencial_impala import processar_radar

            radar = processar_radar(anuncios_reais, produtos=produtos_reais, enviar_alerta=True)
            payload["radar_diferencial"] = {
                "n_comparaveis": radar.get("n_comparaveis"),
                "n_nao_comparaveis": radar.get("n_nao_comparaveis"),
                "fazer": radar.get("fazer"),
                "extras": radar.get("extras"),
                "mercado_confiavel": radar.get("mercado_confiavel"),
                "fonte": radar.get("fonte"),
            }
        except Exception as exc:
            logger.warning("radar diferencial: %s", exc)
            radar = {}
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception as exc:
            logger.warning("snapshot batalha+agir: %s", exc)
    except Exception as exc:
        logger.warning("agir batalha: %s", exc)
    return {**payload, "emit": emit, "agir": agir, "golpe": golpe, "radar_diferencial": radar if isinstance(radar, dict) else {}}


def processar_de_snapshot_kits(caminho: str | None = None) -> dict[str, Any]:
    """Reprocessa logs/esmaltes_kits_monitor_ultima.json sem nova busca."""
    path = ROOT / (caminho or "logs/esmaltes_kits_monitor_ultima.json")
    data = ler_json(path, default={})
    if not isinstance(data, dict):
        return {"ok": False, "erro": "snapshot_invalido"}
    cons = data.get("consolidado") or data
    kits = cons.get("kits_unicos") or cons.get("top_vendas") or []
    return processar_e_persistir(list(kits), origem="snapshot_kits")
