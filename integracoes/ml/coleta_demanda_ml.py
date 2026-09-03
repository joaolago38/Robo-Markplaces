"""
Coleta de demanda ML além de sold_quantity:
  - visitas de rivais (/visits/time_window)
  - funil próprio (visitas → pedidos → conversão)
  - pontos cegos explícitos no que a API não entrega
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, tag_produto
from integracoes.ml import ml_client

logger = logging.getLogger("coleta_demanda_ml")

DEMANDA_HIST_PATH = ROOT / "logs" / "demanda_historico.json"
_MAX_DEMAND_SNAPS = 400


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _titulo_bate(titulo: str, padrao: str | None) -> bool:
    if not padrao:
        return True
    try:
        return bool(re.search(padrao, titulo or "", flags=re.IGNORECASE))
    except re.error:
        return padrao.lower() in (titulo or "").lower()


def enriquecer_visitas_lista(produtos: list[dict[str, Any]], *, limite: int = 12) -> int:
    """Preenche visitas_7d/30d nos top produtos (in-place). Retorna quantos receberam dado."""
    if not produtos or limite <= 0:
        return 0
    vistos: set[str] = set()
    atualizados = 0
    for prod in produtos:
        if atualizados >= limite:
            break
        iid = str(prod.get("item_id") or "").strip()
        if not iid or iid in vistos:
            continue
        vistos.add(iid)
        if _i(prod.get("visitas_7d")) > 0 or _i(prod.get("visitas_30d")) > 0:
            continue
        visitas = ml_client.buscar_visitas_item(iid)
        if not visitas.get("disponivel"):
            continue
        v7 = _i(visitas.get("visitas_7d"))
        v30 = _i(visitas.get("visitas_30d"))
        for p in produtos:
            if str(p.get("item_id") or "").strip() == iid:
                p["visitas_7d"] = v7
                p["visitas_30d"] = v30
                p["visitas_disponivel"] = True
        atualizados += 1
    return atualizados


def enriquecer_visitas_amostra(resultados: list[dict[str, Any]], *, limite: int = 12) -> int:
    """
    Enriquece top anúncios nos resultados de varredura (in-place) com visitas.
    Propaga o mesmo item_id em todos os termos.
    """
    por_item: dict[str, dict[str, Any]] = {}
    for resultado in resultados or []:
        if not resultado.get("ok"):
            continue
        for prod in resultado.get("produtos") or []:
            iid = str(prod.get("item_id") or "").strip()
            if not iid:
                continue
            atual = por_item.get(iid)
            score = (_i(prod.get("quantidade_vendida")), _i(prod.get("avaliacoes")), float(prod.get("preco") or 0))
            if not atual:
                por_item[iid] = prod
                continue
            score_atual = (
                _i(atual.get("quantidade_vendida")),
                _i(atual.get("avaliacoes")),
                float(atual.get("preco") or 0),
            )
            if score > score_atual:
                por_item[iid] = prod

    candidatos = list(por_item.values())[: max(0, limite * 3)]
    # prioriza quem ainda não tem visitas
    candidatos.sort(
        key=lambda p: (
            _i(p.get("visitas_7d")) > 0,
            -_i(p.get("quantidade_vendida")),
            -_i(p.get("avaliacoes")),
        )
    )
    flat = candidatos[: max(0, limite)]
    n = enriquecer_visitas_lista(flat, limite=limite)
    # propaga para todas as cópias nos resultados
    mapa = {
        str(p.get("item_id") or "").strip(): p
        for p in flat
        if p.get("visitas_disponivel") or _i(p.get("visitas_7d")) > 0
    }
    for resultado in resultados or []:
        for p in resultado.get("produtos") or []:
            iid = str(p.get("item_id") or "").strip()
            src = mapa.get(iid)
            if not src:
                continue
            p["visitas_7d"] = _i(src.get("visitas_7d"))
            p["visitas_30d"] = _i(src.get("visitas_30d"))
            p["visitas_disponivel"] = True
    return n


def top_por_visitas(produtos: list[dict[str, Any]], *, top_n: int = 8) -> list[dict[str, Any]]:
    com = [p for p in (produtos or []) if _i(p.get("visitas_7d")) > 0 or _i(p.get("visitas_30d")) > 0]
    com.sort(key=lambda p: (_i(p.get("visitas_7d")), _i(p.get("visitas_30d"))), reverse=True)
    return com[: max(0, top_n)]


def coletar_funil_proprio(
    *,
    dias: int = 7,
    max_anuncios: int = 25,
    filtro_titulo: str | None = None,
    min_visitas_conv: int | None = None,
) -> dict[str, Any]:
    """
    Visitas → unidades pedidas (pedidos pagos) → conversão nos seus anúncios.
    conversao_pct só é confiável com visitas >= min_visitas_conv.
    visitas_convertidas_proxy ≈ unidades (não é atribuição visita-a-visita).
    """
    try:
        from core.config import FUNIL_ML_MIN_VISITAS_CONV

        min_vis = int(
            min_visitas_conv if min_visitas_conv is not None else FUNIL_ML_MIN_VISITAS_CONV
        )
    except Exception:
        min_vis = int(min_visitas_conv if min_visitas_conv is not None else 10)

    if not ml_client._enabled():
        return {
            "ok": False,
            "motivo": "ML não configurado",
            "dias": dias,
            "pedidos_ok": False,
            "visitas_ok": False,
            "totais": {},
            "itens": [],
        }

    anuncios = ml_client.listar_meus_anuncios(statuses=("active", "paused"))
    if filtro_titulo:
        anuncios = [
            a for a in anuncios if _titulo_bate(str(a.get("titulo") or ""), filtro_titulo)
        ]
    anuncios = anuncios[: max(0, max_anuncios)]

    pedidos, pedidos_ok = ml_client.listar_pedidos_detalhado(dias=dias)
    vendas_por_item: dict[str, int] = defaultdict(int)
    receita_por_item: dict[str, float] = defaultdict(float)
    for ped in pedidos:
        for it in ped.get("itens") or []:
            iid = str(it.get("item_id") or "").strip()
            if not iid:
                continue
            qtd = _i(it.get("quantidade"))
            vendas_por_item[iid] += qtd
            receita_por_item[iid] += qtd * float(it.get("preco_unitario") or 0)

    itens: list[dict[str, Any]] = []
    visitas_ok = False
    total_visitas = 0
    total_unidades = 0
    for an in anuncios:
        iid = str(an.get("item_id") or "").strip()
        if not iid:
            continue
        visitas = ml_client.buscar_visitas_item(iid)
        v7 = _i(visitas.get("visitas_7d")) if visitas.get("disponivel") else 0
        v30 = _i(visitas.get("visitas_30d")) if visitas.get("disponivel") else 0
        if visitas.get("disponivel"):
            visitas_ok = True
        un = vendas_por_item.get(iid, 0)
        confiavel = bool(visitas.get("disponivel")) and v7 >= max(1, min_vis)
        conv = round((un / v7) * 100.0, 2) if v7 > 0 else None
        total_visitas += v7
        total_unidades += un
        itens.append(
            {
                "item_id": iid,
                "titulo": str(an.get("titulo") or "")[:80],
                "sku": str(an.get("sku") or ""),
                "status": str(an.get("status") or ""),
                "visitas_7d": v7 if visitas.get("disponivel") else None,
                "visitas_30d": v30 if visitas.get("disponivel") else None,
                "unidades_pedidos": un,
                "visitas_convertidas_proxy": un,
                "receita_pedidos": round(receita_por_item.get(iid, 0.0), 2),
                "conversao_pct": conv,
                "conversao_confiavel": confiavel,
                "sold_quantity": _i(an.get("sold_quantity")),
            }
        )

    itens.sort(
        key=lambda x: (
            _i(x.get("unidades_pedidos")),
            _i(x.get("visitas_7d")),
        ),
        reverse=True,
    )
    conv_tot = round((total_unidades / total_visitas) * 100.0, 2) if total_visitas > 0 else None
    conv_tot_confiavel = total_visitas >= max(1, min_vis)
    return {
        "ok": True,
        "dias": dias,
        "filtro_titulo": filtro_titulo,
        "anuncios_avaliados": len(itens),
        "pedidos_ok": bool(pedidos_ok),
        "visitas_ok": bool(visitas_ok),
        "pedidos_count": len(pedidos),
        "min_visitas_conv": min_vis,
        "totais": {
            "visitas_7d": total_visitas,
            "unidades_7d": total_unidades,
            "visitas_convertidas_proxy": total_unidades,
            "conversao_pct": conv_tot,
            "conversao_confiavel": conv_tot_confiavel,
            "receita_7d": round(sum(receita_por_item.values()), 2),
        },
        "itens": itens,
    }


def montar_pontos_cegos(
    *,
    consolidado: dict[str, Any] | None = None,
    funil: dict[str, Any] | None = None,
    visitas_enriquecidas: int = 0,
    contexto: str = "mercado",
) -> dict[str, Any]:
    """Flags estruturados do que a API entrega vs ponto cego."""
    cons = consolidado or {}
    fun = funil or {}
    vendas_api = _i(cons.get("anuncios_com_vendas_api") or cons.get("vendas_totais"))
    com_aval = _i(cons.get("anuncios_com_avaliacoes"))
    com_vis = _i(cons.get("anuncios_com_visitas")) or _i(visitas_enriquecidas)

    itens = [
        {
            "id": "vendas_concorrente",
            "rotulo": "Vendas concorrente (sold_quantity)",
            "status": "ok" if vendas_api > 0 else "cego",
            "detalhe": (
                f"{vendas_api} anúncio(s) com dado"
                if vendas_api > 0
                else "API /items e search de rivais → 403 / n/d"
            ),
        },
        {
            "id": "reviews_concorrente",
            "rotulo": "Reviews concorrente",
            "status": "ok" if com_aval > 0 else "cego",
            "detalhe": (
                f"{com_aval} anúncio(s) com avaliações"
                if com_aval > 0
                else "/reviews/item de rivais → 403"
            ),
        },
        {
            "id": "visitas_rivais",
            "rotulo": "Visitas rivais",
            "status": "ok" if com_vis > 0 else "parcial",
            "detalhe": (
                f"{com_vis} anúncio(s) com visitas (proxy de demanda)"
                if com_vis > 0
                else "endpoint /visits existe; amostra sem dado nesta rodada"
            ),
        },
        {
            "id": "busca_oficial",
            "rotulo": "Busca oficial /sites/MLB/search",
            "status": "cego",
            "detalhe": "403 no app atual — usa fallback externo (preço/título sem vendas)",
        },
        {
            "id": "funil_proprio",
            "rotulo": "Funil próprio (visitas→pedidos)",
            "status": (
                "ok"
                if fun.get("ok") and fun.get("pedidos_ok") and fun.get("visitas_ok")
                else ("parcial" if fun.get("ok") else "cego")
            ),
            "detalhe": (
                f"{(fun.get('totais') or {}).get('visitas_7d', 0)} visitas → "
                f"{(fun.get('totais') or {}).get('unidades_7d', 0)} un. "
                f"({(fun.get('totais') or {}).get('conversao_pct', 'n/d')}%)"
                if fun.get("ok")
                else str(fun.get("motivo") or "não coletado")
            ),
        },
        {
            "id": "claims",
            "rotulo": "Claims / pós-venda",
            "status": "cego",
            "detalhe": "escopo claims indisponível neste app",
        },
    ]
    cegos = sum(1 for x in itens if x["status"] == "cego")
    return {
        "contexto": contexto,
        "cegos": cegos,
        "parciais": sum(1 for x in itens if x["status"] == "parcial"),
        "oks": sum(1 for x in itens if x["status"] == "ok"),
        "itens": itens,
        "ranking_fonte_sugerida": (
            "vendas"
            if vendas_api > 0
            else ("visitas" if com_vis > 0 else ("avaliacoes" if com_aval > 0 else "presenca"))
        ),
    }


def formatar_secao_funil(funil: dict[str, Any] | None) -> list[str]:
    if not funil:
        return []
    linhas = ["", "*Funil próprio (seus anúncios)*"]
    if not funil.get("ok"):
        linhas.append(f"_{funil.get('motivo') or 'indisponível'}_")
        return linhas
    dias = _i(funil.get("dias"), 7)
    tot = funil.get("totais") or {}
    conv = tot.get("conversao_pct")
    conv_txt = f"{conv}%" if conv is not None else "n/d"
    if tot.get("conversao_confiavel") is False and conv is not None:
        conv_txt += " _(amostra pequena)_"
    avisos = []
    if not funil.get("pedidos_ok"):
        avisos.append("pedidos degradado")
    if not funil.get("visitas_ok"):
        avisos.append("visitas degradado")
    aviso = f" _(⚠ {' | '.join(avisos)})_" if avisos else ""
    linhas.append(
        f"• {dias}d: *{_i(tot.get('visitas_7d'))}* visitas → "
        f"*{_i(tot.get('unidades_7d'))}* un. convertidas (proxy) | "
        f"taxa *{conv_txt}*{aviso}"
    )
    for item in (funil.get("itens") or [])[:5]:
        titulo = str(item.get("titulo") or "?")[:45]
        v7 = item.get("visitas_7d")
        v_txt = str(v7) if v7 is not None else "n/d"
        c = item.get("conversao_pct")
        c_txt = f"{c}%" if c is not None else "n/d"
        if item.get("conversao_confiavel") is False and c is not None:
            c_txt += "*"
        linhas.append(
            f"• {titulo} — vis {v_txt} → {_i(item.get('unidades_pedidos'))} un. ({c_txt})"
        )
    return linhas


def formatar_secao_visitas_rivais(produtos: list[dict[str, Any]] | None, *, top_n: int = 5) -> list[str]:
    top = top_por_visitas(produtos or [], top_n=top_n)
    if not top:
        return []
    linhas = ["", "*Rivais com mais visitas (proxy demanda)*"]
    for p in top:
        titulo = str(p.get("titulo") or "?")[:50]
        linhas.append(
            f"• {titulo} — {_i(p.get('visitas_7d'))} vis/7d | "
            f"R$ {float(p.get('preco') or 0):.2f}"
        )
    return linhas


def formatar_secao_pontos_cegos(pontos: dict[str, Any] | None) -> list[str]:
    if not pontos:
        return []
    linhas = [
        "",
        f"*Pontos cegos API* _(cego={_i(pontos.get('cegos'))} | "
        f"parcial={_i(pontos.get('parciais'))} | ok={_i(pontos.get('oks'))})_",
    ]
    for item in pontos.get("itens") or []:
        st = str(item.get("status") or "?")
        marca = {"ok": "✅", "parcial": "🟡", "cego": "Blind"}.get(st, "•")
        if marca == "Blind":
            marca = "⛔"
        linhas.append(f"• {marca} {item.get('rotulo')}: {item.get('detalhe')}")
    fonte = pontos.get("ranking_fonte_sugerida")
    if fonte:
        linhas.append(f"_Ranking desta rodada: *{fonte}*_")
    return linhas


def emitir_metricas_demanda(
    prefixo: str,
    *,
    funil: dict[str, Any] | None = None,
    pontos_cegos: dict[str, Any] | None = None,
    visitas_enriquecidas: int = 0,
) -> None:
    """Gauges Datadog sob robo.{prefixo}.*"""
    pref = str(prefixo or "").strip().strip(".")
    if not pref:
        return
    fun = funil or {}
    tot = fun.get("totais") or {}
    visitas = _i(tot.get("visitas_7d"))
    unidades = _i(tot.get("unidades_7d"))
    gauge(f"{pref}.funil.visitas_7d", float(visitas))
    gauge(f"{pref}.funil.unidades_7d", float(unidades))
    gauge(f"{pref}.funil.visitas_convertidas_proxy", float(unidades))
    conv = tot.get("conversao_pct")
    if conv is not None:
        gauge(f"{pref}.funil.conversao_pct", float(conv))
    elif visitas > 0:
        # Visitas sem venda no período → taxa 0 (evita widget vazio no Datadog)
        gauge(f"{pref}.funil.conversao_pct", 0.0)
    gauge(
        f"{pref}.funil.conversao_confiavel",
        1.0 if tot.get("conversao_confiavel") else 0.0,
    )
    gauge(f"{pref}.funil.pedidos_ok", 1.0 if fun.get("pedidos_ok") else 0.0)
    gauge(f"{pref}.funil.visitas_ok", 1.0 if fun.get("visitas_ok") else 0.0)
    gauge(f"{pref}.rivais.visitas_amostra", float(_i(visitas_enriquecidas)))
    pc = pontos_cegos or {}
    gauge(f"{pref}.blindspot.cegos", float(_i(pc.get("cegos"))))
    gauge(f"{pref}.blindspot.parciais", float(_i(pc.get("parciais"))))
    gauge(f"{pref}.blindspot.oks", float(_i(pc.get("oks"))))
    for item in pc.get("itens") or []:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id") or "").strip()
        if not bid:
            continue
        st = str(item.get("status") or "")
        if st == "cego":
            val = 1.0
        elif st == "parcial":
            val = 0.5
        else:
            val = 0.0
        gauge(f"{pref}.blindspot.{bid}", val)
    vendas_cego = 1.0
    for item in pc.get("itens") or []:
        if item.get("id") == "vendas_concorrente":
            vendas_cego = 0.0 if item.get("status") == "ok" else 1.0
            break
    gauge(f"{pref}.blindspot.vendas_api", vendas_cego)
    try:
        from integracoes.esmaltes.metricas_progresso_24m import (
            emitir_petg_funil,
            prefixo_emite_petg,
        )

        if prefixo_emite_petg(pref):
            emitir_petg_funil(float(unidades))
    except Exception as exc:
        logger.debug("progresso petg: %s", exc)


_TENDENCIA_NUM = {"alta": 1.0, "estavel": 0.0, "queda": -1.0}


def emitir_metricas_tendencia_demanda(
    termo: str,
    out: dict[str, Any],
    *,
    produto_id: str = "",
) -> None:
    """Gauges robo.demanda.* (não confundir com ml_tendencias_importacao)."""
    tag = tag_produto(produto_id or termo)
    tags = [tag] if tag else []
    bloco = out if isinstance(out, dict) else {}
    tendencia = str(bloco.get("tendencia") or "")
    hist_ok = 1.0 if tendencia in _TENDENCIA_NUM else 0.0
    gauge("demanda.historico_ok", hist_ok, tags=tags)
    if not hist_ok:
        return
    gauge("demanda.tendencia", _TENDENCIA_NUM[tendencia], tags=tags)
    var = bloco.get("variacao_pct")
    if var is not None:
        try:
            gauge("demanda.variacao_pct", float(var), tags=tags)
        except (TypeError, ValueError):
            pass
    conf = str(bloco.get("confiabilidade") or "")
    if conf == "alta":
        conf_n = 1.0
    elif conf == "media":
        conf_n = 0.5
    else:
        conf_n = 0.0
    gauge("demanda.confiavel", conf_n, tags=tags)


def _preco_medio_produtos(produtos: list[dict[str, Any]]) -> float | None:
    precos: list[float] = []
    for prod in produtos or []:
        if not isinstance(prod, dict):
            continue
        try:
            p = float(prod.get("preco") or prod.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            precos.append(p)
    if not precos:
        return None
    return round(sum(precos) / len(precos), 2)


def _soma_avaliacoes_visiveis(produtos: list[dict[str, Any]]) -> int:
    total = 0
    for prod in produtos or []:
        if not isinstance(prod, dict):
            continue
        met = prod.get("metricas") if isinstance(prod.get("metricas"), dict) else {}
        n = prod.get("avaliacoes")
        if n is None:
            n = met.get("avaliacoes")
        total += _i(n)
    return total


def registrar_snapshot_demanda(termo: str, produtos: list[dict[str, Any]]) -> dict[str, Any]:
    """Append em logs/demanda_historico.json. Nunca lança."""
    chave = str(termo or "").strip()
    from datetime import datetime, timezone

    snap = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "termo": chave,
        "total_resultados": len([p for p in (produtos or []) if isinstance(p, dict)]),
        "preco_medio": _preco_medio_produtos(produtos),
        "soma_avaliacoes_visiveis": _soma_avaliacoes_visiveis(produtos),
    }
    if not chave:
        return snap
    try:
        hist = ler_json(DEMANDA_HIST_PATH, default={})
        if not isinstance(hist, dict):
            hist = {}
        bloco = hist.get(chave) if isinstance(hist.get(chave), dict) else {}
        snaps = list(bloco.get("snapshots") or [])
        snaps.append(snap)
        hist[chave] = {"snapshots": snaps[-_MAX_DEMAND_SNAPS:]}
        escrever_json_atomico(DEMANDA_HIST_PATH, hist)
        return snap
    except Exception as exc:
        logger.warning("registrar snapshot demanda %s: %s", chave, exc)
        return snap


def calcular_tendencia_demanda(
    termo: str,
    dias: int = 14,
    *,
    produto_id: str = "",
) -> dict[str, Any]:
    """
    Variação de soma_avaliacoes_visiveis no período (proxy de atividade).
    confiabilidade=baixa se houver menos de 5 snapshots na janela.
    Sem histórico: tendencia=indeterminado — nunca inventa.
    """
    chave = str(termo or "").strip()
    insuficiente = {
        "tendencia": "indeterminado",
        "motivo": "historico insuficiente",
        "variacao_pct": None,
        "confiabilidade": "baixa",
    }
    if not chave:
        emitir_metricas_tendencia_demanda(termo, insuficiente, produto_id=produto_id)
        return insuficiente
    try:
        from datetime import datetime, timedelta, timezone

        hist = ler_json(DEMANDA_HIST_PATH, default={})
        bloco = hist.get(chave) if isinstance(hist, dict) and isinstance(hist.get(chave), dict) else {}
        snaps = [s for s in (bloco.get("snapshots") or []) if isinstance(s, dict)]

        def _ts(raw: Any) -> datetime | None:
            texto = str(raw or "").strip().replace("Z", "+00:00")
            if not texto:
                return None
            try:
                dt = datetime.fromisoformat(texto)
            except (TypeError, ValueError):
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        corte = datetime.now(timezone.utc) - timedelta(days=max(1, int(dias)))
        janela: list[dict[str, Any]] = []
        for snap in snaps:
            ts = _ts(snap.get("timestamp"))
            if ts is None or ts < corte:
                continue
            janela.append(snap)
        janela.sort(key=lambda s: _ts(s.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
        if len(janela) < 2:
            emitir_metricas_tendencia_demanda(chave, insuficiente, produto_id=produto_id)
            return insuficiente
        antigo = _i(janela[0].get("soma_avaliacoes_visiveis"))
        novo = _i(janela[-1].get("soma_avaliacoes_visiveis"))
        if antigo <= 0:
            emitir_metricas_tendencia_demanda(chave, insuficiente, produto_id=produto_id)
            return insuficiente
        variacao = round(100.0 * (novo - antigo) / antigo, 1)
        if abs(variacao) < 5:
            tendencia = "estavel"
        elif variacao > 0:
            tendencia = "alta"
        else:
            tendencia = "queda"
        n = len(janela)
        if n < 5:
            conf = "baixa"
        elif n < 10:
            conf = "media"
        else:
            conf = "alta"
        saida = {
            "tendencia": tendencia,
            "variacao_pct": variacao,
            "confiabilidade": conf,
            "snapshots": n,
            "dias": int(dias),
            "soma_inicial": antigo,
            "soma_atual": novo,
        }
        emitir_metricas_tendencia_demanda(chave, saida, produto_id=produto_id)
        return saida
    except Exception as exc:
        logger.warning("tendencia demanda %s: %s", chave, exc)
        emitir_metricas_tendencia_demanda(chave, insuficiente, produto_id=produto_id)
        return insuficiente
