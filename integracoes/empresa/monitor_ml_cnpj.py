"""
integracoes/empresa/monitor_ml_cnpj.py
Quando o CNPJ muda (ou a cada N dias), inicia monitoramento ML e monta
subsídio de decisão para o Telegram.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from core.empresa.cnpj_utils import digitos, formatar_cnpj
from core.horario import agora_brasil
from integracoes.empresa.vinculo_cnae_cnpj_produtos import (
    carregar_monitorados,
    registrar_monitoramento,
)

logger = logging.getLogger("monitor_ml_cnpj")


def _parse_iso(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except Exception:
        return None


def intervalo_dias_cfg() -> int:
    from core import config as cfg

    return max(1, int(getattr(cfg, "MONITOR_CNPJ_CNAE_INTERVALO_DIAS", 10)))


def cnpj_devido_monitor_ml(
    registro: dict[str, Any] | None,
    *,
    forcar_alteracao: bool = False,
    intervalo_dias: int | None = None,
) -> bool:
    """True se alteração acabou de ocorrer ou se passaram N dias desde a última rodada ML."""
    if forcar_alteracao:
        return True
    dias = intervalo_dias if intervalo_dias is not None else intervalo_dias_cfg()
    reg = registro or {}
    if not reg.get("ativo"):
        return False
    ultima = _parse_iso(reg.get("ultima_monitorizacao_ml"))
    if ultima is None:
        return True
    agora = agora_brasil()
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=agora.tzinfo)
    return (agora - ultima) >= timedelta(days=dias)


def marcar_rodada_ml(cnpj: str, *, motivo: str) -> dict[str, Any]:
    """Atualiza registro do CNPJ com monitoramento ML ativo e timestamp da rodada."""
    cnpj_d = digitos(cnpj)
    data = carregar_monitorados()
    itens = data.get("cnpjs") if isinstance(data.get("cnpjs"), dict) else {}
    prev = itens.get(cnpj_d) if isinstance(itens.get(cnpj_d), dict) else {}
    agora = agora_brasil().isoformat()

    # Garante entrada base via registrar_monitoramento se ainda não existe
    if not prev:
        prev = registrar_monitoramento(cnpj_d, motivo) or {}
        data = carregar_monitorados()
        itens = data.get("cnpjs") if isinstance(data.get("cnpjs"), dict) else {}
        prev = itens.get(cnpj_d) if isinstance(itens.get(cnpj_d), dict) else prev

    itens[cnpj_d] = {
        **prev,
        "cnpj": cnpj_d,
        "cnpj_formatado": formatar_cnpj(cnpj_d),
        "ativo": True,
        "monitoramento_ml_ativo": True,
        "marketplace_foco": "mercadolivre",
        "ultima_monitorizacao_ml": agora,
        "motivo_ultima_ml": motivo,
        "rodadas_ml": int(prev.get("rodadas_ml") or 0) + 1,
    }
    from core.atomic_io import escrever_json_atomico
    from integracoes.empresa.vinculo_cnae_cnpj_produtos import MONITORADOS_PATH

    escrever_json_atomico(
        MONITORADOS_PATH,
        {"cnpjs": itens, "atualizado_em": agora},
    )
    return itens[cnpj_d]


def coletar_subsidio_ml(
    vinculo: dict[str, Any],
    *,
    ao_vivo: bool = True,
) -> dict[str, Any]:
    """
    Dados ML necessários para decisão vinculados ao CNPJ:
    resumo da conta (ao vivo se possível) + estado ML + produtos/CNAE do vínculo.
    """
    out: dict[str, Any] = {
        "ok": False,
        "cnpj": vinculo.get("cnpj"),
        "cnpj_formatado": vinculo.get("cnpj_formatado"),
        "empresa_id": vinculo.get("empresa_id"),
        "marketplace": "mercadolivre",
    }
    resumo: dict[str, Any] = {}
    estado: dict[str, Any] = {}

    if ao_vivo:
        try:
            from integracoes.ml.resumo_conta import coletar_resumo_conta

            from core import config as cfg

            max_perf = int(getattr(cfg, "RESUMO_CONTA_ML_MAX_PERFORMANCE", 40))
            # Amostra menor neste ciclo 10d para não estourar timeout do workflow
            resumo = coletar_resumo_conta(max_anuncios_performance=min(40, max_perf))
        except Exception as exc:
            logger.warning("subsidio ML resumo: %s", exc)
            resumo = {"ok": False, "erro": str(exc)}

    try:
        from core.claude_contexto_ml import carregar_estado_ml

        estado = carregar_estado_ml(ao_vivo=bool(ao_vivo and not resumo.get("ok")))
    except Exception as exc:
        logger.debug("subsidio estado_ml: %s", exc)
        estado = {}

    prods = vinculo.get("produtos") or {}
    mk = vinculo.get("marketplaces") or {}
    acoes = _acoes_decisao(vinculo, resumo, estado)
    limites = None
    try:
        from integracoes.empresa.decision_limits import (
            aplicar_limites_nas_acoes,
            computar_e_emitir,
        )

        limites = computar_e_emitir(
            vinculo=vinculo,
            resumo_ml=resumo if isinstance(resumo, dict) else None,
            cambio_ao_vivo=False,
        )
        acoes = aplicar_limites_nas_acoes(acoes, limites, registrar=True)
    except Exception as exc:
        logger.warning("decision_limits no subsidio: %s", exc)

    out.update(
        {
            "ok": bool(resumo.get("ok") or estado),
            "resumo_conta": {
                "ok": bool(resumo.get("ok")),
                "erro": resumo.get("erro"),
                "nickname": resumo.get("nickname"),
                "reputacao": resumo.get("reputacao"),
                "anuncios_ativos": resumo.get("anuncios_ativos"),
                "anuncios_pausados": resumo.get("anuncios_pausados"),
                "anuncios_a_melhorar_total": resumo.get("anuncios_a_melhorar_total"),
                "perguntas_pendentes": resumo.get("perguntas_pendentes"),
                "precos_pendencias_total": resumo.get("precos_pendencias_total"),
                "envios_pendentes": resumo.get("envios_pendentes"),
                "pos_venda_claims": resumo.get("pos_venda_claims"),
                "publicidade_recomendacoes": resumo.get("publicidade_recomendacoes"),
                "a_melhorar_top": (resumo.get("anuncios_a_melhorar") or [])[:3],
                "precos_top": (resumo.get("precos_pendencias") or [])[:3],
            },
            "estado_ml": {
                "nivel": estado.get("nivel"),
                "score_algoritmo": estado.get("score_algoritmo"),
                "alertas": estado.get("alertas") or [],
                "sinais_recentes": estado.get("sinais_recentes") or {},
            },
            "vinculo_resumo": {
                "cnae_principal": vinculo.get("cnae_principal"),
                "ramos": vinculo.get("ramos") or [],
                "total_skus": prods.get("total_skus"),
                "eh_dono": prods.get("eh_dono_produtos_efetivo"),
                "agentes_prioritarios": vinculo.get("agentes_prioritarios") or [],
                "ml_foco": mk.get("prioriza_mercadolivre"),
                "marketplaces_abertos": mk.get("abertos_para_expansao") or [],
            },
            "acoes": acoes,
            "decision_limits": {
                "resumo": (limites or {}).get("resumo_humano"),
                "bloqueios": (limites or {}).get("bloqueios") or [],
                "max_fazer": ((limites or {}).get("limites") or {}).get("max_acoes_fazer"),
                "permitidos": ((limites or {}).get("limites") or {}).get("permitidos"),
            }
            if limites
            else None,
        }
    )
    return out


def _acoes_decisao(
    vinculo: dict[str, Any],
    resumo: dict[str, Any],
    estado: dict[str, Any],
) -> dict[str, Any]:
    """Traduz sinais ML + vínculo em FAZER / NÃO FAZER / CUSTO para o Telegram."""
    fazer: list[str] = []
    nao_fazer: list[str] = []
    custo: list[str] = []

    perguntas = int(resumo.get("perguntas_pendentes") or 0)
    a_melhorar = int(resumo.get("anuncios_a_melhorar_total") or 0)
    precos = int(resumo.get("precos_pendencias_total") or 0)
    claims = int(resumo.get("pos_venda_claims") or 0)
    envios = int(resumo.get("envios_pendentes") or 0)
    ads = int(resumo.get("publicidade_recomendacoes") or 0)
    nivel = str((estado or {}).get("nivel") or "desconhecido")

    if perguntas >= 1:
        fazer.append(f"Responder *{perguntas}* pergunta(s) pendente(s) no ML")
    if a_melhorar >= 1:
        fazer.append(f"Corrigir *{a_melhorar}* anúncio(s) a melhorar (qualidade/catálogo)")
    if precos >= 1:
        fazer.append(f"Revisar *{precos}* sugestão(ões) de preço do ML")
    if claims >= 1:
        fazer.append(f"Tratar *{claims}* claim(s) / pós-venda aberto(s)")
    if envios >= 1:
        fazer.append(f"Despachar *{envios}* envio(s) pendente(s)")

    agentes = list(vinculo.get("agentes_prioritarios") or [])[:3]
    if agentes:
        fazer.append(f"Rodar agentes do ramo: {', '.join(agentes)}")

    if not fazer:
        fazer.append("Manter rotina — sem pendência crítica detectada nesta rodada")

    if nivel == "critico":
        nao_fazer.append("Não impulsionar Ads até reputação/claims estabilizarem")
    elif ads >= 3:
        nao_fazer.append("Não abrir campanhas novas sem revisar as idle/pausadas")
    else:
        nao_fazer.append("Não migrar dono de produtos sem checklist (CNPJ alvo)")

    if ads >= 1:
        custo.append(f"Ads: {ads} campanha(s) idle/pausada(s) — revisar antes de gastar")
    skus = int((vinculo.get("produtos") or {}).get("total_skus") or 0)
    if skus:
        custo.append(f"Portfólio vinculado: *{skus}* SKU(s) neste CNPJ")

    return {
        "fazer": fazer[:5],
        "nao_fazer": nao_fazer[:3],
        "custo": custo[:3],
        "urgencia": "alta"
        if nivel == "critico" or perguntas >= 5 or claims >= 2
        else ("media" if a_melhorar or precos or perguntas else "baixa"),
    }


def montar_ciclo_monitor_ml(
    vinculos: list[dict[str, Any]],
    alteracoes: list[dict[str, Any]],
    *,
    ao_vivo: bool = True,
    intervalo_dias: int | None = None,
    forcar_todos: bool = False,
) -> dict[str, Any]:
    """
    Para cada CNPJ com alteração OU devido no ciclo de N dias,
    inicia/atualiza monitoramento ML e coleta subsídio.
    """
    dias = intervalo_dias if intervalo_dias is not None else intervalo_dias_cfg()
    mon = carregar_monitorados()
    mon_map = mon.get("cnpjs") if isinstance(mon.get("cnpjs"), dict) else {}
    alt_por_cnpj = {
        digitos(str(a.get("cnpj") or "")): a for a in alteracoes if a.get("cnpj")
    }

    subsidios: list[dict[str, Any]] = []
    for v in vinculos:
        cnpj_d = digitos(str(v.get("cnpj") or ""))
        if not cnpj_d:
            continue
        alt = alt_por_cnpj.get(cnpj_d)
        reg = mon_map.get(cnpj_d) if isinstance(mon_map.get(cnpj_d), dict) else {}
        forcar = bool(alt) or forcar_todos
        # Sem alteração/forçar: só CNPJs já no radar de monitoramento
        if not forcar and not reg.get("ativo") and not reg.get("monitoramento_ml_ativo"):
            continue
        if not cnpj_devido_monitor_ml(reg, forcar_alteracao=forcar, intervalo_dias=dias):
            continue

        motivo = (
            f"alteracao:{alt.get('motivo')}"
            if alt
            else ("forcar_manual" if forcar_todos else f"ciclo_{dias}d")
        )
        marcar_rodada_ml(cnpj_d, motivo=motivo)
        sub = coletar_subsidio_ml(v, ao_vivo=ao_vivo)
        sub["motivo_ciclo"] = motivo
        sub["teve_alteracao"] = bool(alt)
        if alt:
            sub["deltas"] = alt.get("deltas") or []
        subsidios.append(sub)

    return {
        "intervalo_dias": dias,
        "total_monitorados_ml": len(subsidios),
        "subsidios": subsidios,
        "forcado": forcar_todos,
    }
