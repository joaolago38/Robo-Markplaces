"""
integracoes/esmaltes/radar_diferencial_impala.py
Classifica rivais do ML: comparável vs lixo, extras que atraem (Carmed,
brinde, tratamento…) e margem operacional da frente.

Emite gauges robo.impala.guerra.* (sem tag sku:). Nunca lança.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ROOT, TAXA_CANAL_PADRAO_PCT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.decisao_dia_esmaltes import carregar_skus_guerra
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag, margem_real_pct

logger = logging.getLogger("radar_diferencial_impala")

SNAPSHOT_PATH = ROOT / "logs" / "radar_diferencial_impala_ultima.json"
CACHE_BUSCA = ROOT / "logs" / "ml_busca_termo_cache.json"
BATALHA_SNAPSHOT = ROOT / "logs" / "impala_batalha_ultima.json"
PISO_OP_PCT = 15.0
CACHE_STALE_H = 48.0
SNAPSHOT_REAIS_MAX_H = 2.0
_FRENTE = ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006")

_TERMOS_CACHE = (
    "kit 3 esmaltes impala mimo carmed",
    "kit 3 esmaltes impala",
    "kit 4 esmaltes impala perolado",
    "kit 6 esmaltes impala ju paes",
    "kit 6 esmaltes impala sortidos",
    "kit impala",
)

_EXTRAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("carmed", re.compile(r"carmed", re.I)),
    ("brinde", re.compile(r"brinde|\bganhe\b|gr[aá]tis", re.I)),
    ("alicate", re.compile(r"alicate|mundial\s*777", re.I)),
    ("tratamento", re.compile(r"tratamento|incolor|base\s*verniz|endurecedor", re.I)),
    ("francesinha", re.compile(r"francesinha", re.I)),
    ("removedor", re.compile(r"removedor|acetona", re.I)),
    ("full", re.compile(r"\bfull\b", re.I)),
    ("outra_marca", re.compile(r"risqu[eé]|colorama|anita|dailus", re.I)),
)

_RE_KIT_N = re.compile(r"\bkit\s+(\d+)\b", re.I)
_RE_PEROLA = re.compile(r"perol|p[eé]rola", re.I)


def extras_titulo(titulo: str) -> list[str]:
    t = str(titulo or "")
    hits = [nome for nome, rx in _EXTRAS if rx.search(t)]
    return hits or ["nenhum"]


def _qtd(anuncio: dict[str, Any]) -> int | None:
    try:
        q = int(anuncio.get("qtd_kit") or 0)
        if q >= 2:
            return q
    except (TypeError, ValueError):
        pass
    m = _RE_KIT_N.search(str(anuncio.get("titulo") or ""))
    if m:
        n = int(m.group(1))
        return n if 2 <= n <= 50 else None
    return None


def comparavel_frente(anuncio: dict[str, Any], sku: str) -> bool:
    """True só se o anúncio disputa o mesmo kit da frente (não francesinha/tratamento)."""
    titulo = str(anuncio.get("titulo") or "").lower()
    q = _qtd(anuncio)
    sku_u = (sku or "").strip().upper()
    if sku_u == "IMP-MIMO-003":
        if q not in (None, 3):
            return False
        if re.search(r"francesinha|tratamento|incolor|risqu", titulo):
            return False
        return bool(re.search(r"mimo|carmed", titulo))
    if sku_u == "IMP-PERL-004":
        if q not in (None, 4):
            return False
        return bool(_RE_PEROLA.search(titulo))
    if sku_u == "IMP-JUPAES-006":
        if q not in (None, 6):
            return False
        return bool(re.search(r"ju\s*paes|jupaes|virando", titulo))
    return False


def _parse_ts(raw: Any) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _idade_horas(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0)


def _anuncios_do_cache() -> tuple[list[dict[str, Any]], float | None]:
    data = ler_json(CACHE_BUSCA, default={})
    if not isinstance(data, dict):
        return [], None
    out: list[dict[str, Any]] = []
    vistos: set[str] = set()
    oldest: datetime | None = None
    for termo in _TERMOS_CACHE:
        bloco = data.get(termo) or {}
        if not isinstance(bloco, dict):
            continue
        ts = _parse_ts(bloco.get("timestamp"))
        rows = [a for a in (bloco.get("resultados") or []) if isinstance(a, dict)]
        if not rows:
            continue
        if ts is not None and (oldest is None or ts < oldest):
            oldest = ts
        for a in rows:
            iid = str(a.get("item_id") or "").strip().upper()
            if not iid or iid in vistos:
                continue
            vistos.add(iid)
            out.append(a)
    return out, _idade_horas(oldest)


def _anuncios_do_snapshot_batalha() -> list[dict[str, Any]]:
    data = ler_json(BATALHA_SNAPSHOT, default={})
    if not isinstance(data, dict):
        return []
    idade = _idade_horas(_parse_ts(data.get("timestamp")))
    if idade is None or idade > SNAPSHOT_REAIS_MAX_H:
        return []
    out: list[dict[str, Any]] = []
    for a in data.get("anuncios_reais") or []:
        if isinstance(a, dict) and str(a.get("item_id") or "").strip():
            out.append(a)
    return out


def _produto(sku: str, produtos: list[dict[str, Any]]) -> dict[str, Any] | None:
    alvo = sku.strip().upper()
    for p in produtos:
        if str(p.get("sku") or "").strip().upper() == alvo:
            return p
    return None


def _mlb_ok_produto(produto: dict[str, Any] | None) -> bool:
    from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
    from integracoes.esmaltes.decisao_dia_esmaltes import _item_id

    if not isinstance(produto, dict):
        return False
    return bool(_mlb_valido(_item_id(produto)))


def _estoque_produto(produto: dict[str, Any] | None) -> int:
    if not isinstance(produto, dict):
        return 0
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    try:
        return max(int(produto.get("estoque_total") or 0), int(ml.get("estoque") or 0))
    except (TypeError, ValueError):
        return 0


def _resolver_amostra(
    anuncios: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str, float | None]:
    if anuncios is None:
        snap = _anuncios_do_snapshot_batalha()
        if snap:
            return snap, "snapshot_batalha", None
        cache, idade = _anuncios_do_cache()
        return cache, "cache_busca", idade
    amostra = [a for a in anuncios if isinstance(a, dict)]
    if amostra:
        return amostra, "amostra", None
    cache, idade = _anuncios_do_cache()
    return cache, "cache_busca", idade


def _decidir_fazer(
    margens: list[dict[str, Any]],
    *,
    mlb_frente: int,
    estoque_frente: int,
) -> str:
    if mlb_frente <= 0:
        return "Publicar MIMO no ML (sem item id) com titulo Mimo + Carmed — nao igualar francesinha"
    if estoque_frente <= 0:
        return "Entrar estoque da frente (catalogo 0) antes de guerra de preco"
    mimo = next((m for m in margens if m.get("sku") == "IMP-MIMO-003"), {})
    if mimo.get("margem_op_pct") is not None and mimo["margem_op_pct"] < PISO_OP_PCT:
        return "Nao baixar MIMO — margem operacional abaixo de 15%"
    if any(int(m.get("rivais_comparaveis") or 0) > 0 for m in margens):
        return "Diferenciar no listing (extra nosso vs rival comparavel) — preco so no PERL se gap >= 3% e >= piso"
    return "Manter MIMO com Carmed no titulo — nao igualar francesinha"


def montar_radar(
    anuncios: list[dict[str, Any]] | None = None,
    *,
    produtos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    amostra, fonte, cache_idade_h = _resolver_amostra(anuncios)
    guerra = {str(g.get("sku") or "").upper(): g for g in carregar_skus_guerra()}

    extras_cnt: Counter[str] = Counter()
    classificados: list[dict[str, Any]] = []
    for a in amostra:
        ex = extras_titulo(str(a.get("titulo") or ""))
        for e in ex:
            extras_cnt[e] += 1
        row = {
            "item_id": a.get("item_id"),
            "titulo": str(a.get("titulo") or "")[:90],
            "preco": a.get("preco"),
            "qtd_kit": _qtd(a),
            "extras": ex,
            "comparavel": {sku: comparavel_frente(a, sku) for sku in _FRENTE},
        }
        classificados.append(row)

    for nome, _rx in _EXTRAS:
        extras_cnt.setdefault(nome, 0)
    extras_cnt.setdefault("nenhum", 0)

    n_comp = sum(1 for r in classificados if any(r["comparavel"].values()))
    n_lixo = max(0, len(classificados) - n_comp)

    margens: list[dict[str, Any]] = []
    mlb_frente = 0
    estoque_frente = 0
    for sku in _FRENTE:
        p = _produto(sku, prods)
        mop = margem_real_pct(p) if p else None
        g = guerra.get(sku) or {}
        ml = ((p or {}).get("canais") or {}).get("mercadolivre") or {}
        titulo_nosso = str(
            (ml.get("titulo_anuncio") if isinstance(ml, dict) else "")
            or (p or {}).get("nome")
            or ""
        )
        mlb_ok = _mlb_ok_produto(p)
        est = _estoque_produto(p)
        if mlb_ok:
            mlb_frente += 1
        estoque_frente += est
        margens.append(
            {
                "sku": sku,
                "kit_tag": kit_tag(sku),
                "papel": str(g.get("papel") or "guerra"),
                "margem_op_pct": mop,
                "acima_piso15": bool(mop is not None and mop >= PISO_OP_PCT),
                "diferencial": str(g.get("diferencial_obrigatorio") or ""),
                "nossos_extras": extras_titulo(titulo_nosso),
                "rivais_comparaveis": sum(1 for r in classificados if r["comparavel"].get(sku)),
                "mlb_ok": mlb_ok,
                "estoque": est,
            }
        )

    fazer = _decidir_fazer(margens, mlb_frente=mlb_frente, estoque_frente=estoque_frente)
    cache_stale = bool(fonte == "cache_busca" and cache_idade_h is not None and cache_idade_h >= CACHE_STALE_H)
    amostra_viva = fonte == "amostra"
    mercado_confiavel = bool(amostra_viva or fonte == "snapshot_batalha" or (fonte == "cache_busca" and not cache_stale))

    payload = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "piso_op_pct": PISO_OP_PCT,
        "taxa_pct": TAXA_CANAL_PADRAO_PCT,
        "n_anuncios": len(classificados),
        "n_comparaveis": n_comp,
        "n_nao_comparaveis": n_lixo,
        "extras": dict(extras_cnt),
        "margens": margens,
        "fazer": fazer,
        "nao_fazer": "Igualar kit 3 francesinha/tratamento; perseguir dump abaixo do piso 15%",
        "rivais": classificados[:20],
        "fonte": fonte,
        "cache_idade_h": round(cache_idade_h, 1) if cache_idade_h is not None else None,
        "cache_stale": cache_stale,
        "mlb_frente": mlb_frente,
        "estoque_frente": estoque_frente,
        "amostra_viva": amostra_viva,
        "mercado_confiavel": mercado_confiavel,
    }
    try:
        from integracoes.esmaltes.doutrina_guerra_impala import avaliar_condicoes_guerra

        cond = avaliar_condicoes_guerra(produtos=prods, radar=payload)
        payload["condicoes"] = {
            "fase": cond.get("fase"),
            "fase_nome": cond.get("fase_nome"),
            "cenario": cond.get("cenario"),
            "fazer": cond.get("fazer"),
            "proximo": cond.get("proximo"),
            "agentes": cond.get("agentes"),
            "checks": cond.get("checks"),
            "liberar": cond.get("liberar"),
        }
        if cond.get("fazer"):
            payload["fazer"] = str(cond["fazer"])
    except Exception as exc:
        logger.warning("condicoes guerra: %s", exc)
    return payload


def emitir_metricas_radar(payload: dict[str, Any] | None) -> None:
    """Gauges de mercado só com amostra confiável; cache velho emite 0 (não finge mercado de hoje)."""
    data = payload if isinstance(payload, dict) else {}
    confiavel = bool(data.get("mercado_confiavel"))
    n_comp = float(data.get("n_comparaveis") or 0) if confiavel else 0.0
    n_lixo = float(data.get("n_nao_comparaveis") or 0) if confiavel else 0.0
    n_amostra = float(data.get("n_anuncios") or 0) if confiavel else 0.0
    extras = data.get("extras") or {}
    gauge("impala.guerra.rivais_comparaveis", n_comp)
    gauge("impala.guerra.rivais_nao_comparaveis", n_lixo)
    gauge("impala.guerra.rivais_amostra", n_amostra)
    gauge("impala.guerra.mlb_frente", float(data.get("mlb_frente") or 0))
    gauge("impala.guerra.estoque_frente", float(data.get("estoque_frente") or 0))
    gauge("impala.guerra.amostra_viva", 1.0 if data.get("amostra_viva") else 0.0)
    gauge("impala.guerra.mercado_confiavel", 1.0 if confiavel else 0.0)
    gauge("impala.guerra.cache_stale", 1.0 if data.get("cache_stale") else 0.0)
    if data.get("cache_idade_h") is not None:
        gauge("impala.guerra.cache_idade_h", float(data["cache_idade_h"]))
    nomes_extra = [nome for nome, _rx in _EXTRAS] + ["nenhum"]
    for extra in nomes_extra:
        n = float(extras.get(extra) or 0) if confiavel else 0.0
        gauge("impala.guerra.extra_n", n, tags=[f"extra:{extra}"[:40]])
    for m in data.get("margens") or []:
        if not isinstance(m, dict):
            continue
        tags = [m.get("kit_tag") or "kit:x", f"papel:{m.get('papel') or 'guerra'}"]
        if m.get("margem_op_pct") is not None:
            gauge("impala.guerra.margem_op_pct", float(m["margem_op_pct"]), tags=tags)
        gauge("impala.guerra.piso15_ok", 1.0 if m.get("acima_piso15") else 0.0, tags=tags)
        rivais_kit = float(m.get("rivais_comparaveis") or 0) if confiavel else 0.0
        gauge("impala.guerra.rivais_comp_kit", rivais_kit, tags=tags)
        extras_nossos = m.get("nossos_extras") or []
        carmed_no_ar = bool(m.get("mlb_ok") and "carmed" in extras_nossos)
        gauge("impala.guerra.nosso_carmed", 1.0 if carmed_no_ar else 0.0, tags=tags)
        gauge("impala.guerra.mlb_ok", 1.0 if m.get("mlb_ok") else 0.0, tags=tags)
    n_piso = sum(1 for m in (data.get("margens") or []) if isinstance(m, dict) and m.get("acima_piso15"))
    gauge("impala.guerra.kits_acima_piso15", float(n_piso))
    try:
        from integracoes.esmaltes.doutrina_guerra_impala import emitir_metricas_condicoes

        cond = data.get("condicoes") if isinstance(data.get("condicoes"), dict) else None
        emitir_metricas_condicoes(cond)
    except Exception as exc:
        logger.warning("condicoes datadog: %s", exc)
    incrementar("impala.guerra.radar_rodadas")


def url_dashboard_decisao() -> str:
    from core.config import DD_DASH_ECOMMERCE, DD_SITE

    site = (DD_SITE or "us5.datadoghq.com").strip()
    dash = (DD_DASH_ECOMMERCE or "j53-h48-8ea").strip()
    return f"https://{site}/dashboard/{dash}"


def formatar_mensagem(payload: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    extras = payload.get("extras") or {}
    extras_vivos = {k: v for k, v in extras.items() if int(v or 0) > 0}
    extras_txt = (
        ", ".join(f"{k} {v}" for k, v in sorted(extras_vivos.items(), key=lambda x: -x[1])[:6])
        or "nenhum"
    )
    linhas_m = []
    for m in payload.get("margens") or []:
        mop = m.get("margem_op_pct")
        mop_txt = f"{mop:.1f}%" if isinstance(mop, (int, float)) else "-"
        ok = "ok" if m.get("acima_piso15") else "abaixo 15%"
        mlb = "MLB" if m.get("mlb_ok") else "sem MLB"
        linhas_m.append(
            f"  `{m.get('sku')}` {mop_txt} ({ok}) · {mlb} · rivais comparaveis {m.get('rivais_comparaveis') or 0}"
        )
    dash = url_dashboard_decisao()
    fonte = str(payload.get("fonte") or "?")
    idade = payload.get("cache_idade_h")
    fonte_txt = fonte
    if idade is not None:
        fonte_txt = f"{fonte} ({idade:.0f}h)"
        if payload.get("cache_stale"):
            fonte_txt += " STALE"
    cond = payload.get("condicoes") if isinstance(payload.get("condicoes"), dict) else {}
    fase_txt = ""
    if cond.get("fase") is not None:
        fase_txt = (
            f"*Fase guerra {cond.get('fase')}/5* `{cond.get('fase_nome') or ''}` · "
            f"proximo: {cond.get('proximo') or '—'}"
        )
    return "\n".join(
        [
            cabecalho_agente("radar_diferencial_impala", "*VISAO ATUACAO* Impala — diferencial + margem"),
            *([fase_txt] if fase_txt else []),
            f"*FAZER:* {payload.get('fazer')}",
            f"*NAO FAZER:* {payload.get('nao_fazer')}",
            f"Fonte: {fonte_txt} · MLB frente {payload.get('mlb_frente') or 0}/3 · estoque {payload.get('estoque_frente') or 0}",
            f"Amostra ML: {payload.get('n_anuncios') or 0} · comparaveis {payload.get('n_comparaveis') or 0} · "
            f"nao comparaveis {payload.get('n_nao_comparaveis') or 0}"
            + ("" if payload.get("mercado_confiavel") else " (Datadog=0, cache nao e mercado de hoje)"),
            f"Extras nos titulos rivais: {extras_txt}",
            "*Margem operacional de catalogo (preco planejado - taxa 18% - custo) / preco — nao e listing no ar*",
            *linhas_m,
            "",
            f"Ver serie no Datadog (Ecommerce Impala → grupo Decisao guerra): {dash}",
            "_Alerta para abrir o Datadog: margem, extras do rival, MLB publicado e se o kit e comparavel._",
        ]
    )


def processar_radar(
    anuncios: list[dict[str, Any]] | None = None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    try:
        payload = montar_radar(anuncios, produtos=produtos)
        emitir_metricas_radar(payload)
        payload["mensagem"] = formatar_mensagem(payload)
        if enviar_alerta:
            payload["alerta_enviado"], payload["alerta_motivo"] = _alertar(payload)
        else:
            payload["alerta_enviado"] = False
            payload["alerta_motivo"] = "sem_alerta"
        gauge("impala.guerra.alerta_ok", 1.0 if payload.get("alerta_enviado") else 0.0)
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception as exc:
            logger.warning("snapshot radar: %s", exc)
        return payload
    except Exception as exc:
        logger.warning("processar_radar: %s", exc)
        incrementar("impala.guerra.radar_erro")
        return {"ok": False, "erro": str(exc)}


def _alertar(payload: dict[str, Any]) -> tuple[bool, str]:
    from core.config import VISAO_ATUACAO_IMPALA_ALERTA, VISAO_ATUACAO_IMPALA_COOLDOWN_SEG
    from core.notificador import alertar_gestor, gestor_telegram_configurado
    from core.prontidao import pode_alertar_esmaltes
    from core.telegram_gate import pode_enviar

    if not VISAO_ATUACAO_IMPALA_ALERTA:
        return False, "alerta_desligado"
    pode, motivo = pode_alertar_esmaltes()
    if not pode:
        logger.warning("Telegram esmaltes bloqueado: %s", motivo)
        return False, motivo
    if not gestor_telegram_configurado():
        return False, "telegram_nao_configurado"
    if not pode_enviar():
        return False, "telegram_circuito"
    ok = bool(
        alertar_gestor(
            payload.get("mensagem") or "",
            chave="visao_atuacao_impala:resumo",
            cooldown_segundos=VISAO_ATUACAO_IMPALA_COOLDOWN_SEG,
            agente_id=None,
        )
    )
    if ok:
        return True, "ok"
    return False, "envio_ou_cooldown"


def snapshot_fresco(max_min: float = 25.0) -> dict[str, Any] | None:
    data = ler_json(SNAPSHOT_PATH, default={})
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    idade_h = _idade_horas(_parse_ts(data.get("timestamp")))
    if idade_h is None or idade_h * 60.0 > max_min:
        return None
    return data
