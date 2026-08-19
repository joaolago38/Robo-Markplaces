"""
agentes/operacao_24h.py
Rotina contínua de monitoramento + faturamento (Lojahub -> Bling).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from agentes.algoritmo_marketplaces import executar as executar_algoritmo_marketplaces
from agentes.faturamento.agente_faturamento import emitir_nfe_pedido
from agentes.ml.agente_ads_gatilho import executar as verificar_gatilho_ads
from agentes.repricing.agente_repricing_impala import executar as repricing_impala
from agentes.repricing.agente_repricing_marketplaces import executar as executar_repricing_marketplaces
from core.alertas_esmaltes import verificar_todos as verificar_alertas_esmaltes
from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor
from core.resumo_ia import sintetizar_claude
from integracoes.bling.bling_client import listar_produtos
from integracoes.lojahub.lojahub_client import listar_pedidos_prontos_faturar, listar_resumo_vendas_24h
from integracoes.ml.ml_product_ads import listar_campanhas

logger = logging.getLogger("operacao_24h")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _index_custo_por_sku(produtos: list[dict]) -> dict:
    return {str(p.get("sku", "")).strip(): _to_float(p.get("custo", 0.0)) for p in produtos if p.get("sku")}


def _normalizar_pedido_lojahub(pedido: dict) -> dict:
    cliente = pedido.get("cliente", {})
    itens = pedido.get("itens", pedido.get("items", []))
    return {
        "pedido_id": str(pedido.get("id", pedido.get("pedido_id", ""))),
        "cliente": {
            "nome": cliente.get("nome", cliente.get("name", "Consumidor Final")),
            "documento": cliente.get("documento", cliente.get("document", "")),
            "email": cliente.get("email", ""),
            "telefone": cliente.get("telefone", ""),
            "endereco": cliente.get("endereco", {}),
        },
        "itens": [
            {
                "sku": i.get("sku", i.get("codigo")),
                "quantidade": i.get("quantidade", i.get("quantity", 1)),
                "valor_unitario": i.get("valor_unitario", i.get("price", 0)),
                "descricao": i.get("descricao", i.get("name", "")),
                "ncm": i.get("ncm"),
            }
            for i in itens
        ],
        "observacoes": pedido.get("observacoes", pedido.get("notes", "")),
    }


def _calcular_kpis_24h(produtos_bling: list[dict], pedidos_faturar: list[dict], analytics_24h: dict) -> dict:
    preco_medio = 0.0
    if produtos_bling:
        preco_medio = sum(_to_float(p.get("preco", 0.0)) for p in produtos_bling) / len(produtos_bling)

    custo_por_sku = _index_custo_por_sku(produtos_bling)
    receita = 0.0
    custo = 0.0
    itens_vendidos = 0

    for pedido in pedidos_faturar:
        for item in pedido.get("itens", pedido.get("items", [])):
            sku = str(item.get("sku", item.get("codigo", ""))).strip()
            qtd = _to_float(item.get("quantidade", item.get("quantity", 1)), 1)
            valor = _to_float(item.get("valor_unitario", item.get("price", 0.0)), 0.0)
            receita += valor * qtd
            custo += _to_float(custo_por_sku.get(sku, 0.0)) * qtd
            itens_vendidos += int(qtd)

    ticket_medio = (receita / max(1, len(pedidos_faturar))) if pedidos_faturar else 0.0
    lucro = receita - custo
    margem_pct = (lucro / receita * 100) if receita > 0 else 0.0

    # Se analytics da API existir, usa como referência complementar.
    analytics_data = analytics_24h.get("data", {}) if analytics_24h.get("ok") else {}
    receita_ref = _to_float(analytics_data.get("receita", receita))
    pedidos_ref = int(_to_float(analytics_data.get("pedidos", len(pedidos_faturar))))

    return {
        "preco_medio_cadastrado": round(preco_medio, 2),
        "media_venda_24h": round(receita_ref / max(1, pedidos_ref), 2),
        "receita_24h": round(receita_ref, 2),
        "lucro_estimado_24h": round(lucro, 2),
        "margem_estimada_24h_pct": round(margem_pct, 2),
        "pedidos_24h": pedidos_ref,
        "itens_vendidos_24h": itens_vendidos,
        "ticket_medio_24h": round(ticket_medio, 2),
    }


def _faturar_pedidos_lojahub(dry_run_nfe: bool = True, limite: int = 20) -> dict:
    pedidos_raw = listar_pedidos_prontos_faturar(limit=limite)
    pedidos = [_normalizar_pedido_lojahub(p) for p in pedidos_raw]
    resultados = []
    sucesso = 0
    for pedido in pedidos:
        if not pedido.get("pedido_id"):
            continue
        out = emitir_nfe_pedido(pedido, dry_run=dry_run_nfe)
        if out.get("ok"):
            sucesso += 1
        resultados.append({"pedido_id": pedido["pedido_id"], "ok": out.get("ok"), "resultado": out})
    payload = {
        "total": len(resultados),
        "sucesso": sucesso,
        "falhas": len(resultados) - sucesso,
        "itens": resultados,
    }
    try:
        incrementar("nfe.rodadas", tags=[f"dry_run:{str(bool(dry_run_nfe)).lower()}"])
        escrever_json_atomico(
            ROOT / "logs" / "nfe_ultima.json",
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": payload["falhas"] == 0,
                "dry_run": dry_run_nfe,
                "total": payload["total"],
                "sucesso": sucesso,
                "falhas": payload["falhas"],
            },
        )
    except Exception as exc:
        logger.warning("NF-e heartbeat: %s", exc)
    return payload


def _payload_para_contexto_claude(payload: dict) -> dict:
    """Extrai só dados já calculados — nunca inventa métricas novas."""
    mp = payload.get("marketplaces") or {}
    gatilho = payload.get("gatilho_ads") or {}
    repricing = payload.get("repricing") or {}
    ciclo = payload.get("ciclo_meta") if isinstance(payload.get("ciclo_meta"), dict) else {}
    return {
        "kpis_24h": payload.get("kpis_24h"),
        "ciclo_meta": {
            "pronto": ciclo.get("pronto"),
            "motivo": ciclo.get("motivo"),
            "fase": ciclo.get("fase"),
        },
        "marketplaces_resumo": mp.get("resumo") or {},
        "marketplaces_status": {
            nome: {"status": av.get("status"), "score": av.get("score")}
            for nome, av in (mp.get("marketplaces") or {}).items()
        },
        "repricing_total_ajustes": repricing.get("total_ajustes"),
        "gatilho_ads": {
            "decisao": gatilho.get("decisao"),
            "acos_atual": gatilho.get("acos_atual"),
            "motivos": gatilho.get("motivos"),
        },
        "alertas_esmaltes_qtd": len(payload.get("alertas_esmaltes") or []),
    }


def _fallback_resumo_operacao(payload: dict) -> str:
    mp = (payload.get("marketplaces") or {}).get("resumo") or {}
    gatilho = payload.get("gatilho_ads") or {}
    linhas: list[str] = []
    if mp.get("critico", 0) > 0:
        linhas.append(f"{mp['critico']} marketplace(s) em estado crítico — priorizar estabilização.")
    if mp.get("atencao", 0) > 0:
        linhas.append(f"{mp['atencao']} marketplace(s) em atenção.")
    decisao = gatilho.get("decisao")
    if decisao and decisao not in ("aguardar", "manter"):
        linhas.append(f"Gatilho de ads: {decisao} — revisar nas próximas horas.")
    if not linhas:
        linhas.append("Operação 24h sem sinais críticos imediatos; manter monitoramento.")
    return "\n".join(linhas[:5])


def _sintetizar_claude_operacao(payload: dict) -> str:
    contexto = _payload_para_contexto_claude(payload)
    fallback = _fallback_resumo_operacao(payload)
    # Dry-run total: regras locais bastam; evita Claude sem sinal operacional real.
    modo = payload.get("modo") or {}
    if modo.get("repricing_dry_run") and modo.get("nfe_dry_run"):
        kpis = payload.get("kpis_24h") or {}
        if float(kpis.get("receita_24h") or 0) <= 0 and not (payload.get("alertas_esmaltes") or []):
            return fallback
    prompt = (
        "Com base no contexto JSON acima, escreva um resumo executivo de NO MÁXIMO 5 linhas, "
        "objetivo, priorizando o que muda receita ou risco nas próximas horas. "
        "Não repita números brutos que já aparecem no relatório detalhado; foque em interpretação "
        "(ex.: vendas 24h abaixo da média, ACOS subindo, estoque crítico bloqueando repricing)."
    )
    return sintetizar_claude(
        prompt,
        contexto,
        fallback,
        max_tokens=400,
        origem="operacao_24h",
    )


def _formatar_notas_repricing(repricing: dict) -> str:
    notas = [
        str(a.get("nota_concorrencia")).strip()
        for a in (repricing.get("ajustes") or [])
        if a.get("nota_concorrencia")
    ]
    if not notas:
        return ""
    return "Notas concorrência:\n" + "\n".join(f"• {n}" for n in notas[:5])


def _gravar_heartbeat_operacao(payload: dict) -> None:
    """Heartbeat com semântica de escrita (ok ≠ só 'rodou')."""
    try:
        bloqueado = bool(payload.get("bloqueado"))
        repricing = payload.get("repricing") if isinstance(payload.get("repricing"), dict) else {}
        faturamento = payload.get("faturamento") if isinstance(payload.get("faturamento"), dict) else {}
        falhas_rep = int(repricing.get("total_falhas_aplicacao") or 0)
        falhas_nfe = int(faturamento.get("falhas") or faturamento.get("erro") or 0)
        if isinstance(faturamento.get("falhas"), list):
            falhas_nfe = len(faturamento["falhas"])
        ok = (not bloqueado) and falhas_rep == 0 and falhas_nfe == 0 and payload.get("ok") is not False
        modo = payload.get("modo") if isinstance(payload.get("modo"), dict) else {}
        escrever_json_atomico(
            ROOT / "logs" / "operacao_24h_ultima.json",
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": bool(ok),
                "bloqueado": bloqueado,
                "motivo": payload.get("erro") or payload.get("motivo"),
                "dry_run_repricing": bool(modo.get("repricing_dry_run")),
                "dry_run_nfe": bool(modo.get("nfe_dry_run")),
                "total_ajustes_preco": int(repricing.get("total_ajustes") or 0),
                "total_aplicados_preco": int(repricing.get("total_aplicados_sucesso") or 0),
                "total_falhas_preco": falhas_rep,
                "nfe_sucesso": int(faturamento.get("sucesso") or 0),
                "nfe_total": int(faturamento.get("total") or 0),
            },
        )
        incrementar("operacao_24h.rodadas", tags=[f"ok:{str(bool(ok)).lower()}"])
    except Exception as exc:
        logger.warning("Operacao24h: falha ao gravar heartbeat: %s", exc)


def executar(dry_run_repricing: bool = True, dry_run_nfe: bool = True) -> dict:
    if not dry_run_repricing or not dry_run_nfe:
        from core.guardrails import alertar_bloqueio_escrita_global, bloqueio_escrita_global

        if bloqueio := bloqueio_escrita_global():
            alertar_bloqueio_escrita_global()
            payload_bloqueio = {
                **bloqueio,
                "ok": False,
                "bloqueado": True,
                "modo": {"repricing_dry_run": dry_run_repricing, "nfe_dry_run": dry_run_nfe},
            }
            _gravar_heartbeat_operacao(payload_bloqueio)
            return payload_bloqueio

    produtos = listar_produtos()
    analytics = listar_resumo_vendas_24h()
    pedidos_faturar = listar_pedidos_prontos_faturar(limit=100)
    kpis = _calcular_kpis_24h(produtos, pedidos_faturar, analytics)

    # Reputação da conta e Full logístico (não confundir Full com Mercado Líder).
    _total_avaliacoes = 0
    _nota_media = 0.0
    _full_ativo = False
    try:
        from integracoes.ml.ml_client import buscar_reputacao_vendedor
        _rep = buscar_reputacao_vendedor()
        _metrics = _rep.get("metrics", {})
        _total_avaliacoes = int(_metrics.get("total_ratings", 0) or 0)
        _nota_media = float(_metrics.get("average_rating", 0.0) or 0.0)
    except Exception as _e:
        logger.warning("Não foi possível buscar reputação ML: %s", _e)
    try:
        from integracoes.ml.ml_client import listar_meus_anuncios
        from integracoes.ml.tipo_anuncio_ml import algum_anuncio_full

        _full_ativo = algum_anuncio_full(listar_meus_anuncios())
    except Exception as _e:
        logger.warning("Não foi possível detectar Full nos anúncios ML: %s", _e)
        _full_ativo = False

    try:
        _campanhas = listar_campanhas(dias=14)
        _campanhas_com_gasto = [c for c in _campanhas if c.get("cost", 0) > 0]
        if _campanhas_com_gasto:
            _gasto_total = sum(c["cost"] for c in _campanhas_com_gasto)
            _acos_atual = sum(c["acos"] * c["cost"] for c in _campanhas_com_gasto) / _gasto_total
        else:
            _acos_atual = 0.0
    except Exception as _e:
        logger.warning("Não foi possível calcular ACOS agregado de Product Ads: %s", _e)
        _acos_atual = 0.0

    # Alertas específicos de esmaltes com dados reais
    alertas_esmaltes = verificar_alertas_esmaltes(
        total_avaliacoes=_total_avaliacoes,
        kits=produtos,
    )

    # Verificar se é hora de ligar/escalar/pausar ads com dados reais
    gatilho_ads = verificar_gatilho_ads(acos_atual=_acos_atual, full_ativo=_full_ativo)

    # Repricing consciente de fase
    repricing_fases = repricing_impala(dry_run=dry_run_repricing)

    monitor_marketplaces = executar_algoritmo_marketplaces(alertar_quando_atencao=False)
    repricing = executar_repricing_marketplaces(produtos=produtos, dry_run=dry_run_repricing)
    faturamento = _faturar_pedidos_lojahub(dry_run_nfe=dry_run_nfe, limite=30)

    payload = {
        "kpis_24h": kpis,
        "marketplaces": monitor_marketplaces,
        "repricing": repricing,
        "repricing_fases": repricing_fases,
        "faturamento": faturamento,
        "alertas_esmaltes": alertas_esmaltes,
        "gatilho_ads": gatilho_ads,
        "modo": {"repricing_dry_run": dry_run_repricing, "nfe_dry_run": dry_run_nfe},
    }

    try:
        from integracoes.meta.ciclo_campanhas import avaliar_momento_ciclo_meta
        from integracoes.meta.claude_ciclo_meta import auxiliar_digest_bloqueio

        ciclo_meta = avaliar_momento_ciclo_meta()
        payload["ciclo_meta"] = {
            "pronto": bool(ciclo_meta.get("pronto")),
            "motivo": ciclo_meta.get("motivo"),
            "fase": ciclo_meta.get("fase"),
        }
        payload["claude_ciclo_meta"] = auxiliar_digest_bloqueio(ciclo_meta)
    except Exception as exc:
        logger.warning("Operacao24h ciclo Meta Claude: %s", exc)
    resumo_ia = _sintetizar_claude_operacao(payload)
    bloco_notas = _formatar_notas_repricing(repricing)
    aplicados = int(repricing.get("total_aplicados_sucesso") or 0)
    candidatos = int(repricing.get("total_ajustes") or 0)
    falhas_preco = int(repricing.get("total_falhas_aplicacao") or 0)
    modo_rep = "dry-run" if dry_run_repricing else "live"
    modo_nfe = "dry-run" if dry_run_nfe else "live"
    msg_bruta = (
        f"Operação 24h:\n"
        f"Receita: R$ {kpis['receita_24h']:.2f} | Lucro estimado: R$ {kpis['lucro_estimado_24h']:.2f}\n"
        f"Preço médio: R$ {kpis['preco_medio_cadastrado']:.2f} | Ticket médio: R$ {kpis['ticket_medio_24h']:.2f}\n"
        f"NF ({modo_nfe}): {faturamento['sucesso']}/{faturamento['total']} | "
        f"Preço ({modo_rep}): {aplicados}/{candidatos} aplicados"
        + (f" | {falhas_preco} falha(s)" if falhas_preco else "")
    )
    if bloco_notas:
        msg_bruta = f"{msg_bruta}\n{bloco_notas}"
    alertar_gestor(f"📝 *Resumo IA*\n{resumo_ia}\n\n{msg_bruta}")
    logger.info("Operacao24h: %s", payload)
    _gravar_heartbeat_operacao(payload)
    return payload


if __name__ == "__main__":
    # Emissão real de NF-e só com dry_run_nfe=False explícito ou NFE_EMITIR_REAL=true
    emitir_real = os.getenv("NFE_EMITIR_REAL", "").strip().lower() in ("1", "true", "yes")
    print(executar(dry_run_repricing=True, dry_run_nfe=not emitir_real))
