"""
agentes/descoberta/agente_descoberta_produtos.py
Analisa cada marketplace, identifica público-alvo + oportunidades e cruza com Alibaba.

Catálogo: catalogo/descoberta_nichos.json
Somente leitura + recomendações — não publica anúncios nem compra.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.claude_client import perguntar_estruturado
from core.config import (
    DESCOBERTA_ALERTA_PAINEL_COOLDOWN_SEG,
    DESCOBERTA_ALIBABA_MAX_POR_OPORTUNIDADE,
    DESCOBERTA_ALIBABA_PAUSA_SEG,
    DESCOBERTA_BUSCAR_ALIBABA,
    DESCOBERTA_NICHOS_CATALOGO,
    DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG,
    ROOT,
    SPEC,
)
from core.datadog_metrics import gauge, incrementar
from core.ddg_lite import mensagem_circuit_breaker
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.descoberta.alibaba_cruzamento import (
    cruzar_oportunidades_com_alibaba,
    estimar_margem_importacao,
    formatar_fornecedor_log,
)
from integracoes.descoberta.coletores import coletar

logger = logging.getLogger("agente_descoberta_produtos")

HISTORY_PATH = ROOT / "logs" / "descoberta_produtos_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "descoberta_produtos_ultima_rodada.json"

_SCHEMA_ANALISE = {
    "type": "object",
    "properties": {
        "publico_alvo": {
            "type": "string",
            "description": "Quem compra neste marketplace para este nicho (perfil, necessidade, faixa).",
        },
        "perfil_comprador": {
            "type": "string",
            "description": "Comportamento de compra observado ou inferido dos dados.",
        },
        "tendencias": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Até 4 tendências curtas vistas nos títulos/preços.",
        },
        "oportunidades": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "sinal": {"type": "string"},
                    "faixa_preco_sugerida": {"type": "string"},
                    "termo_alibaba": {
                        "type": "string",
                        "description": "Termo em inglês para buscar fornecedor no Alibaba.",
                    },
                    "confianca": {"type": "string", "enum": ["baixa", "media", "alta"]},
                    "acao": {"type": "string"},
                },
                "required": ["produto", "sinal", "confianca"],
            },
        },
    },
    "required": ["publico_alvo", "oportunidades"],
}

_SYSTEM_ANALISE = (
    "Você é analista de e-commerce brasileiro. Com base APENAS nos dados JSON fornecidos "
    "(resultados de busca, preços, títulos, hints de nicho), identifique o público-alvo "
    "e oportunidades de produto específicas para aquele marketplace. "
    "Para cada oportunidade, inclua termo_alibaba em inglês para buscar fornecedor. "
    "Não invente vendas, marcas ou preços que não apareçam nos dados. "
    "Se a busca por termo não estiver disponível (Shopee/Magalu/Amazon), infira o público "
    "a partir do hint do catálogo e do perfil típico da plataforma no Brasil."
)

_MARKETPLACES_ATIVOS: set[str] = {
    str(m.get("id") or "").lower()
    for m in SPEC.get("marketplaces", [])
    if m.get("ativo")
}


def _carregar_nichos() -> list[dict[str, Any]]:
    caminho = ROOT / DESCOBERTA_NICHOS_CATALOGO
    try:
        if not caminho.is_file():
            logger.warning("Catálogo descoberta não encontrado: %s", caminho)
            return []
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [n for n in data if isinstance(n, dict) and n.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar descoberta_nichos: %s", exc)
        return []


def _marketplaces_do_nicho(nicho: dict[str, Any]) -> list[str]:
    brutos = nicho.get("marketplaces") or ["mercadolivre"]
    resultado: list[str] = []
    for mp in brutos:
        nome = str(mp or "").strip().lower()
        if not nome:
            continue
        if nome == "ml":
            nome = "mercadolivre"
        if _MARKETPLACES_ATIVOS and nome not in _MARKETPLACES_ATIVOS:
            continue
        resultado.append(nome)
    return resultado


def _analise_fallback(coleta: dict[str, Any], nicho: dict[str, Any]) -> dict[str, Any]:
    stats = coleta.get("estatisticas") or {}
    publico = str(nicho.get("publico_alvo_hint") or "Consumidoras do segmento — configure IA para detalhar")
    termo_ali = str(nicho.get("termo_alibaba_en") or nicho.get("termo_busca") or "")
    oportunidades: list[dict[str, str]] = []
    if stats.get("preco_medio"):
        oportunidades.append(
            {
                "produto": str(nicho.get("nome") or nicho.get("id") or "nicho"),
                "sinal": (
                    f"Faixa observada R${stats.get('preco_min')}–R${stats.get('preco_max')} "
                    f"(média R${stats.get('preco_medio')}) em {stats.get('total_anuncios', 0)} anúncios"
                ),
                "faixa_preco_sugerida": f"R$ {nicho.get('preco_alvo_min', '?')}–{nicho.get('preco_alvo_max', '?')}",
                "termo_alibaba": termo_ali,
                "confianca": "media",
                "acao": "Validar anúncio teste na faixa observada",
            }
        )
    elif not coleta.get("configurado"):
        oportunidades.append(
            {
                "produto": str(nicho.get("nome") or "?"),
                "sinal": str(coleta.get("motivo") or "marketplace não configurado"),
                "termo_alibaba": termo_ali,
                "confianca": "baixa",
                "acao": "Configurar credenciais do marketplace",
            }
        )
    return {
        "publico_alvo": publico,
        "perfil_comprador": "Análise automática (sem Claude)",
        "tendencias": [],
        "oportunidades": oportunidades,
    }


def _analisar_com_ia(coleta: dict[str, Any], nicho: dict[str, Any]) -> dict[str, Any]:
    contexto = {
        "nicho": {
            "id": nicho.get("id"),
            "nome": nicho.get("nome"),
            "categoria": nicho.get("categoria"),
            "publico_alvo_hint": nicho.get("publico_alvo_hint"),
            "preco_alvo_min": nicho.get("preco_alvo_min"),
            "preco_alvo_max": nicho.get("preco_alvo_max"),
            "termo_alibaba_en": nicho.get("termo_alibaba_en"),
        },
        "coleta": coleta,
        "fase_operacao": SPEC.get("fase_operacao", {}),
        "kits_prioritarios": SPEC.get("kits_prioritarios", {}),
    }
    prompt = (
        f"Analise o marketplace '{coleta.get('marketplace')}' para o nicho '{nicho.get('nome')}'. "
        "Retorne público-alvo, perfil do comprador, tendências nos títulos/preços e até 5 "
        "oportunidades de produto específicas para ESTE marketplace. "
        "Em cada oportunidade, preencha termo_alibaba em inglês para buscar fornecedor."
    )
    estruturado = perguntar_estruturado(
        prompt,
        _SCHEMA_ANALISE,
        "analise_descoberta_produtos",
        max_tokens=900,
        contexto=json.dumps(contexto, ensure_ascii=False, indent=2),
        system=_SYSTEM_ANALISE,
    )
    if isinstance(estruturado, dict) and estruturado.get("publico_alvo"):
        return estruturado
    return _analise_fallback(coleta, nicho)


def _hash_analise(nicho_id: str, marketplace: str, analise: dict[str, Any]) -> str:
    blob = json.dumps(
        {
            "nicho": nicho_id,
            "marketplace": marketplace,
            "publico": analise.get("publico_alvo"),
            "oportunidades": analise.get("oportunidades"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _hash_alibaba(cruzamento: dict[str, Any]) -> str:
    blob = json.dumps(cruzamento.get("oportunidades") or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _logar_analise(resultado: dict[str, Any]) -> None:
    nome = resultado.get("nicho_nome", "?")
    mp = resultado.get("marketplace", "?")
    analise = resultado.get("analise") or {}
    stats = (resultado.get("coleta") or {}).get("estatisticas") or {}

    logger.info(
        "Descoberta %s / %s — público: %s",
        nome,
        mp,
        analise.get("publico_alvo", "?"),
    )
    if stats:
        logger.info(
            "  Mercado: %s anúncios | preço R$%s–%s (média R$%s)",
            stats.get("total_anuncios", 0),
            stats.get("preco_min", "?"),
            stats.get("preco_max", "?"),
            stats.get("preco_medio", "?"),
        )
    for tend in (analise.get("tendencias") or [])[:4]:
        logger.info("  Tendência: %s", tend)
    for op in (analise.get("oportunidades") or [])[:5]:
        logger.info(
            "  Oportunidade [%s]: %s — %s | ação: %s",
            op.get("confianca", "?"),
            op.get("produto", "?"),
            op.get("sinal", ""),
            op.get("acao", "—"),
        )

    cruz = resultado.get("cruzamento_alibaba") or {}
    if not cruz.get("total_fornecedores"):
        logger.info("  Alibaba: nenhum fornecedor encontrado nesta rodada")
        return

    logger.info(
        "  Alibaba: %s fornecedor(es) em %s oportunidade(s)",
        cruz.get("total_fornecedores"),
        cruz.get("total_oportunidades"),
    )
    for bloco in cruz.get("oportunidades") or []:
        logger.info("  🌐 %s (termo: %s)", bloco.get("produto", "?"), bloco.get("termo_alibaba", "?"))
        for f in (bloco.get("fornecedores") or [])[:4]:
            logger.info("    • %s", formatar_fornecedor_log(f))
            margem = bloco.get("margem_estimada")
            if margem and margem.get("ok"):
                logger.info(
                    "      Margem est.: R$%s (%.1f%%) venda R$%s vs custo import R$%s",
                    margem.get("margem_brl"),
                    margem.get("margem_pct"),
                    margem.get("preco_venda_brl"),
                    margem.get("custo_import_brl"),
                )


def _enriquecer_margens(cruzamento: dict[str, Any], preco_medio_ml: float | None) -> dict[str, Any]:
    if not preco_medio_ml or preco_medio_ml <= 0:
        return cruzamento
    for bloco in cruzamento.get("oportunidades") or []:
        fornecedores = bloco.get("fornecedores") or []
        if not fornecedores:
            continue
        melhor = fornecedores[0]
        preco_usd = melhor.get("preco_usd")
        if preco_usd is None:
            continue
        margem = estimar_margem_importacao(preco_medio_ml, float(preco_usd))
        if margem.get("ok"):
            bloco["margem_estimada"] = margem
    return cruzamento


def _analisar_par(nicho: dict[str, Any], marketplace: str, historico: dict[str, Any]) -> dict[str, Any]:
    import time

    nid = str(nicho.get("id") or "").strip()
    chave_hist = f"{nid}:{marketplace}"
    coleta = coletar(marketplace, nicho)
    analise = _analisar_com_ia(coleta, nicho)

    cruzamento: dict[str, Any] = {"total_fornecedores": 0, "oportunidades": []}
    if DESCOBERTA_BUSCAR_ALIBABA and (analise.get("oportunidades") or []):
        cruzamento = cruzar_oportunidades_com_alibaba(
            nicho,
            analise,
            max_por_oportunidade=DESCOBERTA_ALIBABA_MAX_POR_OPORTUNIDADE,
            pausa_seg=DESCOBERTA_ALIBABA_PAUSA_SEG,
        )
        stats = coleta.get("estatisticas") or {}
        preco_medio = stats.get("preco_medio")
        try:
            preco_medio_f = float(preco_medio) if preco_medio is not None else None
        except (TypeError, ValueError):
            preco_medio_f = None
        cruzamento = _enriquecer_margens(cruzamento, preco_medio_f)

    h = _hash_analise(nid, marketplace, analise)
    h_ali = _hash_alibaba(cruzamento)
    agora = datetime.now(timezone.utc).isoformat()
    entrada = historico.get(chave_hist) if isinstance(historico.get(chave_hist), dict) else {}
    vistos: dict[str, Any] = dict(entrada.get("analises") or {})
    novo = h not in vistos
    alibaba_novo = h_ali not in (entrada.get("hashes_alibaba") or [])

    registro = {
        "hash": h,
        "hash_alibaba": h_ali,
        "analise": analise,
        "cruzamento_alibaba": cruzamento,
        "coleta_resumo": {
            "configurado": coleta.get("configurado"),
            "total_anuncios": (coleta.get("estatisticas") or {}).get("total_anuncios"),
            "termos": coleta.get("termos"),
            "estatisticas": coleta.get("estatisticas"),
        },
        "analisado_em": agora,
    }
    vistos[h] = registro
    hashes_ali = list(entrada.get("hashes_alibaba") or [])
    if alibaba_novo and cruzamento.get("total_fornecedores"):
        hashes_ali.append(h_ali)
        hashes_ali = hashes_ali[-20:]

    historico[chave_hist] = {
        "nicho": str(nicho.get("nome") or nid),
        "marketplace": marketplace,
        "analises": vistos,
        "hashes_alibaba": hashes_ali,
        "ultima_analise": agora,
    }

    gauge(
        "descoberta.oportunidades",
        len(analise.get("oportunidades") or []),
        tags=[f"marketplace:{marketplace}", f"nicho:{nid}"],
    )
    gauge(
        "descoberta.alibaba_fornecedores",
        cruzamento.get("total_fornecedores", 0),
        tags=[f"marketplace:{marketplace}", f"nicho:{nid}"],
    )
    if novo:
        incrementar("descoberta.novas_analises", tags=[f"marketplace:{marketplace}", f"nicho:{nid}"])
    if alibaba_novo and cruzamento.get("total_fornecedores"):
        incrementar("descoberta.novos_fornecedores_alibaba", tags=[f"nicho:{nid}"])

    resultado = {
        "nicho_id": nid,
        "nicho_nome": str(nicho.get("nome") or nid),
        "marketplace": marketplace,
        "novo": novo,
        "alibaba_novo": alibaba_novo,
        "hash": h,
        "hash_alibaba": h_ali,
        "analise": analise,
        "coleta": coleta,
        "cruzamento_alibaba": cruzamento,
        "ok": True,
    }
    _logar_analise(resultado)

    if DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG > 0:
        time.sleep(DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG)

    return resultado


def _formatar_bloco_alibaba(bloco: dict[str, Any]) -> list[str]:
    linhas = [f"  🌐 *{bloco.get('produto', '?')}* (busca: {bloco.get('termo_alibaba', '?')})"]
    margem = bloco.get("margem_estimada")
    if margem and margem.get("ok"):
        linhas.append(
            f"  📊 Margem est.: R${margem['margem_brl']} ({margem['margem_pct']}%) "
            f"venda R${margem['preco_venda_brl']} − import R${margem['custo_import_brl']}"
        )
    for f in (bloco.get("fornecedores") or [])[:3]:
        preco = f.get("preco_usd")
        preco_txt = f"US${preco:.2f}" if preco is not None else "preço n/d"
        moq = f.get("moq")
        moq_txt = f"MOQ {moq}" if moq is not None else "MOQ n/d"
        dist = f.get("distribuidor") or "distribuidor n/d"
        linhas.append(f"  • {preco_txt} | {moq_txt} | {dist}")
        if f.get("url"):
            linhas.append(f"    {f['url']}")
    return linhas


def _montar_painel_decisao(resultados: list[dict[str, Any]]) -> str:
    linhas = ["📋 *Painel de decisão — Descoberta + Importação*", ""]
    total_ali = sum((r.get("cruzamento_alibaba") or {}).get("total_fornecedores", 0) for r in resultados)
    linhas.append(f"Análises: {len(resultados)} | Fornecedores Alibaba: {total_ali}")
    linhas.append("")

    for r in resultados:
        a = r.get("analise") or {}
        stats = (r.get("coleta") or {}).get("estatisticas") or {}
        mp = str(r.get("marketplace") or "?").upper()
        linhas.append(f"*{r.get('nicho_nome')}* — {mp}")
        linhas.append(f"👥 {a.get('publico_alvo', '?')}")
        if a.get("perfil_comprador"):
            linhas.append(f"🛒 {a['perfil_comprador']}")
        if stats.get("preco_medio"):
            linhas.append(
                f"💰 Mercado: R${stats.get('preco_min')}–{stats.get('preco_max')} "
                f"(média R${stats.get('preco_medio')}) — {stats.get('total_anuncios', 0)} anúncios"
            )
        for op in (a.get("oportunidades") or [])[:3]:
            linhas.append(f"• [{op.get('confianca', '?')}] {op.get('produto')} — {op.get('sinal', '')}")
            if op.get("acao"):
                linhas.append(f"  → {op['acao']}")

        cruz = r.get("cruzamento_alibaba") or {}
        if cruz.get("total_fornecedores"):
            linhas.append("*Importação Alibaba:*")
            for bloco in cruz.get("oportunidades") or []:
                if bloco.get("fornecedores"):
                    linhas.extend(_formatar_bloco_alibaba(bloco))
        else:
            linhas.append("_Sem fornecedor Alibaba nesta rodada._")
        linhas.append("")

    ddg = mensagem_circuit_breaker("descoberta")
    if ddg:
        linhas.append(f"⚠️ {ddg}")
    return "\n".join(linhas).strip()[:3900]


def _montar_alerta_alibaba_novos(resultados: list[dict[str, Any]]) -> str:
    linhas = ["🌐 *Alibaba — novos fornecedores para importar*", ""]
    tem = False
    for r in resultados:
        if not r.get("alibaba_novo"):
            continue
        cruz = r.get("cruzamento_alibaba") or {}
        if not cruz.get("total_fornecedores"):
            continue
        tem = True
        linhas.append(f"*{r.get('nicho_nome')}* ({r.get('marketplace')})")
        for bloco in cruz.get("oportunidades") or []:
            linhas.extend(_formatar_bloco_alibaba(bloco))
        linhas.append("")
    return "\n".join(linhas).strip() if tem else ""


def _montar_alerta_novos(resultados: list[dict[str, Any]]) -> str:
    linhas = ["🔍 *Nova análise de marketplace*", ""]
    for r in resultados:
        if not r.get("novo"):
            continue
        a = r.get("analise") or {}
        mp = str(r.get("marketplace") or "?").upper()
        linhas.append(f"*{r.get('nicho_nome')}* — {mp}")
        linhas.append(f"👥 {a.get('publico_alvo', '?')}")
        for op in (a.get("oportunidades") or [])[:4]:
            linhas.append(f"• [{op.get('confianca')}] {op.get('produto')} — {op.get('sinal')}")
        linhas.append("")
    return "\n".join(linhas).strip()


def _salvar_snapshot(resultados: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": meta,
        "resultados": resultados,
    }
    try:
        escrever_json_atomico(SNAPSHOT_PATH, payload)
        logger.info("Snapshot salvo em %s", SNAPSHOT_PATH)
    except Exception as exc:
        logger.warning("Falha ao salvar snapshot descoberta: %s", exc)


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre nichos × marketplaces ativos. Nunca lança exceção."""
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning(
                "Telegram gestor não configurado — alertas de descoberta não serão entregues"
            )

        nichos = _carregar_nichos()
        if not nichos:
            logger.info("Descoberta: nenhum nicho ativo em %s", DESCOBERTA_NICHOS_CATALOGO)
            return {"ok": True, "total_nichos": 0, "resultados": [], "alerta_enviado": False}

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}

        resultados: list[dict[str, Any]] = []
        for nicho in nichos:
            for mp in _marketplaces_do_nicho(nicho):
                logger.info("Iniciando descoberta: %s em %s", nicho.get("nome"), mp)
                resultados.append(_analisar_par(nicho, mp, historico))

        escrever_json_atomico(HISTORY_PATH, historico)

        com_novos = [r for r in resultados if r.get("novo")]
        com_alibaba_novos = [r for r in resultados if r.get("alibaba_novo")]
        total_fornecedores = sum(
            (r.get("cruzamento_alibaba") or {}).get("total_fornecedores", 0) for r in resultados
        )

        meta = {
            "total_nichos": len(nichos),
            "pares_analisados": len(resultados),
            "com_novos": len(com_novos),
            "com_alibaba_novos": len(com_alibaba_novos),
            "total_fornecedores_alibaba": total_fornecedores,
        }
        _salvar_snapshot(resultados, meta)

        alerta_novos = False
        alerta_alibaba = False
        alerta_painel = False

        if enviar_alerta and com_novos:
            msg = _montar_alerta_novos(com_novos)
            if msg:
                alerta_novos = bool(
                    alertar_gestor(
                        msg,
                        chave=chave_itens_novos(
                            "descoberta:novos",
                            [{"hash": r.get("hash")} for r in com_novos],
                        ),
                        cooldown_segundos=86400,
                    )
                )

        if enviar_alerta and com_alibaba_novos:
            msg_ali = _montar_alerta_alibaba_novos(com_alibaba_novos)
            if msg_ali:
                alerta_alibaba = bool(
                    alertar_gestor(
                        msg_ali,
                        chave=chave_itens_novos(
                            "descoberta:alibaba",
                            [{"hash": r.get("hash_alibaba")} for r in com_alibaba_novos],
                        ),
                        cooldown_segundos=86400,
                    )
                )

        if enviar_alerta and resultados:
            painel = _montar_painel_decisao(resultados)
            if painel:
                alerta_painel = bool(
                    alertar_gestor(
                        painel,
                        chave=chave_resumo_periodo("descoberta:painel", horas_por_bucket=24),
                        cooldown_segundos=DESCOBERTA_ALERTA_PAINEL_COOLDOWN_SEG,
                    )
                )
                if not alerta_painel:
                    logger.info("Painel decisão não enviado (cooldown ou Telegram indisponível)")

        logger.info(
            "Descoberta concluída: %s pares | %s novos | %s fornecedores Alibaba | "
            "alertas painel=%s alibaba=%s novos=%s",
            len(resultados),
            len(com_novos),
            total_fornecedores,
            alerta_painel,
            alerta_alibaba,
            alerta_novos,
        )

        return {
            "ok": True,
            **meta,
            "alerta_enviado": alerta_novos or alerta_alibaba or alerta_painel,
            "alerta_novos_enviado": alerta_novos,
            "alerta_alibaba_enviado": alerta_alibaba,
            "alerta_painel_enviado": alerta_painel,
            "snapshot": str(SNAPSHOT_PATH),
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente descoberta produtos erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Descoberta de produtos por marketplace ===")
    out = executar(enviar_alerta=True)
    if not out.get("ok"):
        return 1
    logger.info(
        "Descoberta: %s pares, %s fornecedores Alibaba, alerta=%s, snapshot=%s",
        out.get("pares_analisados"),
        out.get("total_fornecedores_alibaba"),
        out.get("alerta_enviado"),
        out.get("snapshot"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
