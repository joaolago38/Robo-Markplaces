"""
agentes/repricing/agente_repricing_marketplaces.py
Monitora produtos nos marketplaces e ajusta preço com lucro mínimo.
"""
from __future__ import annotations

import json
import logging

from core.config import (
    LUCRO_MINIMO_REPRICING_PCT,
    MARGEM_FASE_1_PCT,
    MARGEM_FASE_2_PCT,
    MARGEM_FASE_3_PCT,
    MONITOR_CONCORRENTES_ARQUIVO,
    PRECIFICACAO_COMPORTAMENTO_ATIVO,
    REPRICING_ABAIXO_CONCORRENTE_PCT,
    REPRICING_DIFERENCA_MINIMA,
    ROOT,
    TAXA_CANAL_PADRAO_PCT,
)
from core.datadog_metrics import incrementar
from core.notificador import alertar_critico, alertar_gestor
from core.precificacao_comportamento import calcular_preco_ideal
from integracoes.amazon.amazon_client import atualizar_preco_item as atualizar_preco_amazon
from integracoes.bling.bling_client import listar_produtos_por_sku
from integracoes.magalu.magalu_client import atualizar_preco_item as atualizar_preco_magalu
from integracoes.ml.ml_client import atualizar_preco_item as atualizar_preco_ml
from integracoes.ml.ml_client import buscar_menor_preco_concorrente
from integracoes.shopee.shopee_client import atualizar_preco_item as atualizar_preco_shopee

logger = logging.getLogger("agente_repricing_marketplaces")


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _margem_minima_por_fase(fase_atual: int | str | None) -> float:
    fase = str(fase_atual or "1").strip()
    if fase == "2":
        return MARGEM_FASE_2_PCT
    if fase == "3":
        return MARGEM_FASE_3_PCT
    return MARGEM_FASE_1_PCT


def _calcular_preco_piso(custo: float, taxa_canal_pct: float, margem_minima_pct: float) -> float:
    taxa = max(0.0, min(99.0, taxa_canal_pct)) / 100.0
    margem = max(0.0, min(99.0, margem_minima_pct)) / 100.0
    denominador = 1 - taxa - margem
    if custo <= 0 or denominador <= 0:
        return 0.0
    return custo / denominador


def _faixa_bloqueada(nome: str, preco: float) -> str | None:
    nome_lower = (nome or "").lower()
    if ("kit 3" in nome_lower or "kit 4" in nome_lower or "kit 5" in nome_lower) and preco < 22:
        return "kit 3-5 abaixo de R$22 bloqueado"
    if ("kit 10" in nome_lower or "kit 12" in nome_lower) and preco < 38:
        return "kit 10-12 abaixo de R$38 bloqueado"
    if "alicate" in nome_lower and "kit" in nome_lower and preco < 55:
        return "bundle alicate+esmalte abaixo de R$55 bloqueado"
    return None


def _calcular_novo_preco(
    preco_atual: float,
    custo: float,
    preco_concorrente: float | None,
    margem_minima_pct: float,
    taxa_canal_pct: float,
    *,
    sinais: dict | None = None,
    preco_fase: float | None = None,
) -> tuple[float, float, float, dict | None]:
    if PRECIFICACAO_COMPORTAMENTO_ATIVO or sinais:
        ideal = calcular_preco_ideal(
            preco_atual=preco_atual,
            custo=custo,
            preco_concorrente=preco_concorrente,
            margem_minima_pct=margem_minima_pct,
            taxa_canal_pct=taxa_canal_pct,
            abaixo_concorrente_pct=REPRICING_ABAIXO_CONCORRENTE_PCT,
            sinais=sinais,
            preco_fase=preco_fase,
        )
        return (
            ideal["preco_sugerido"],
            ideal["margem_pct"],
            ideal["preco_piso"],
            ideal,
        )

    preco_piso = _calcular_preco_piso(custo, taxa_canal_pct, margem_minima_pct)
    alvo_concorrencia = 0.0
    if preco_concorrente and preco_concorrente > 0:
        alvo_concorrencia = preco_concorrente * (1 - REPRICING_ABAIXO_CONCORRENTE_PCT / 100.0)

    base = max(preco_piso, alvo_concorrencia if alvo_concorrencia > 0 else preco_atual, custo)
    novo_preco = round(max(0.01, base), 2)
    margem = ((novo_preco - custo) / novo_preco * 100) if novo_preco > 0 else 0.0
    return novo_preco, margem, round(preco_piso, 2), None


def _updater(canal: str):
    return {
        "mercadolivre": atualizar_preco_ml,
        "shopee": atualizar_preco_shopee,
        "magalu": atualizar_preco_magalu,
        "amazon": atualizar_preco_amazon,
    }.get(canal)


def _item_ref(canal: str, canal_data: dict, sku: str):
    if canal == "mercadolivre":
        return canal_data.get("item_id") or sku
    if canal == "shopee":
        return canal_data.get("item_id")
    return canal_data.get("sku") or sku


def _calcular_economia_estimada_piso_margem(ajustes: list[dict]) -> float:
    """
    Estimativa de margem protegida pelo piso/faixas (por unidade, não é receita real).
    - Faixa bloqueada: evitou baixar de preco_atual até o preço que seria aplicado.
    - Piso de margem: concorrente abaixo do piso — diferença entre piso e alvo competitivo.
    """
    total = 0.0
    for a in ajustes:
        preco_atual = _to_float(a.get("preco_atual"))
        novo_preco = _to_float(a.get("novo_preco"))
        preco_piso = _to_float(a.get("preco_piso"))
        preco_conc = _to_float(a.get("preco_concorrente"))
        motivo = str(a.get("motivo") or "")

        if motivo.endswith("bloqueado") and novo_preco < preco_atual:
            total += preco_atual - novo_preco
            continue

        if preco_piso > 0 and preco_conc > 0:
            alvo = preco_conc * (1 - REPRICING_ABAIXO_CONCORRENTE_PCT / 100.0)
            if alvo < preco_piso and abs(novo_preco - preco_piso) < 0.02:
                total += preco_piso - alvo

    return round(total, 2)


def _carregar_monitor_por_sku() -> dict[str, dict]:
    caminho = ROOT / MONITOR_CONCORRENTES_ARQUIVO
    try:
        if not caminho.is_file():
            return {}
        data = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return {}
        out: dict[str, dict] = {}
        for ent in data:
            if isinstance(ent, dict) and ent.get("ativo") and ent.get("sku"):
                out[str(ent["sku"]).strip()] = ent
        return out
    except Exception as exc:
        logger.warning("repricing monitor por sku: %s", exc)
        return {}


def _amostra_concorrente_monitor(entrada: dict) -> dict | None:
    termo = str(entrada.get("termo_busca") or "").strip()
    if not termo:
        return None
    try:
        from integracoes.ml.ml_client import buscar_concorrentes_por_termo

        limite = int(entrada.get("limite_resultados") or 10)
        concorrentes = buscar_concorrentes_por_termo(termo, limite=limite)
        precos = [c for c in concorrentes if _to_float(c.get("preco"), 0) > 0]
        if not precos:
            return None
        return min(precos, key=lambda c: _to_float(c.get("preco"), 0))
    except Exception as exc:
        logger.warning("repricing amostra concorrente: %s", exc)
        return None


def _gerar_nota_concorrencia(
    nome: str,
    preco_atual: float,
    preco_concorrente: float,
    novo_preco: float,
    sku: str,
    monitor_por_sku: dict[str, dict],
) -> str | None:
    entrada = monitor_por_sku.get(sku)
    if not entrada:
        return None
    amostra = _amostra_concorrente_monitor(entrada)
    contexto = {
        "produto": nome,
        "preco_atual": round(preco_atual, 2),
        "preco_concorrente": round(preco_concorrente, 2),
        "novo_preco_calculado": round(novo_preco, 2),
        "monitor": {
            "termo_busca": entrada.get("termo_busca"),
            "nome": entrada.get("nome"),
        },
    }
    if amostra:
        contexto["concorrente_destaque"] = {
            "frete_gratis": amostra.get("frete_gratis"),
            "quantidade_vendida": amostra.get("quantidade_vendida"),
            "condicao": amostra.get("condicao"),
            "preco": amostra.get("preco"),
        }
    fallback = (
        f"{nome}: concorrente R$ {preco_concorrente:.2f}, "
        f"novo preço calculado R$ {novo_preco:.2f}."
    )
    from core.resumo_ia import sintetizar_claude

    prompt = (
        "Em UMA linha curta, comente a nuance competitiva para o gestor "
        "(ex.: concorrente sem frete grátis e baixo volume — considere manter preço). "
        "Não altere nem recomende bloquear o ajuste — apenas informe."
    )
    nota = sintetizar_claude(prompt, contexto, fallback, max_tokens=80)
    return (nota or "")[:200] or None


def _preco_fase_produto(produto: dict, fase_atual: int | str | None) -> float | None:
    fase = str(fase_atual or "1").strip()
    por_fase = produto.get("precos_por_fase") or {}
    try:
        v = float(por_fase.get(f"fase{fase}") or 0)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def executar(produtos: list[dict] | None = None, dry_run: bool = True, lucro_minimo_pct: float | None = None) -> dict:
    if not dry_run:
        from core.guardrails import alertar_bloqueio_escrita_global, bloqueio_escrita_global

        if bloqueio := bloqueio_escrita_global():
            alertar_bloqueio_escrita_global()
            return {
                **bloqueio,
                "dry_run": False,
                "lucro_minimo_pct": float(lucro_minimo_pct if lucro_minimo_pct is not None else LUCRO_MINIMO_REPRICING_PCT),
                "total_itens": 0,
                "total_ajustes": 0,
                "economia_estimada_piso_margem": 0.0,
                "ajustes": [],
            }

        from core.algoritmo_eventos import deve_congelar_repricing

        cong, motivo_cong = deve_congelar_repricing("mercadolivre")
        if cong:
            alertar_gestor(
                f"⏸ Repricing marketplaces *congelado* (algoritmo ML)\n_{motivo_cong}_",
                chave="repricing:congelado_algoritmo",
                cooldown_segundos=3600,
                agente_id="repricing",
            )
            return {
                "ok": True,
                "dry_run": False,
                "congelado": True,
                "motivo_congelamento": motivo_cong,
                "lucro_minimo_pct": float(lucro_minimo_pct if lucro_minimo_pct is not None else LUCRO_MINIMO_REPRICING_PCT),
                "total_itens": 0,
                "total_ajustes": 0,
                "economia_estimada_piso_margem": 0.0,
                "ajustes": [],
            }

    lucro_minimo = float(lucro_minimo_pct if lucro_minimo_pct is not None else LUCRO_MINIMO_REPRICING_PCT)
    if produtos is not None:
        produtos_base = produtos
        produtos_bling = listar_produtos_por_sku()
    else:
        from core.catalogo_produtos import carregar_produtos_para_operacao

        produtos_base = carregar_produtos_para_operacao()
        produtos_bling = listar_produtos_por_sku()
    ajustes = []
    monitor_por_sku = _carregar_monitor_por_sku()

    for p in produtos_base:
        sku = p.get("sku")
        if not sku:
            continue
        completo = produtos_bling.get(sku) or {}
        custo = _to_float(p.get("custo", completo.get("custo", 0.0)))
        if custo <= 0:
            continue
        nome = p.get("nome") or completo.get("nome") or sku
        fase_atual = p.get("fase_atual", completo.get("fase_atual", 1))
        margem_fase = _margem_minima_por_fase(fase_atual)
        margem_minima = max(lucro_minimo, margem_fase)

        canais = p.get("canais", {}) if isinstance(p.get("canais", {}), dict) else {}
        for canal, dados in canais.items():
            if not isinstance(dados, dict) or not dados.get("ativo", False):
                continue
            preco_atual = _to_float(dados.get("preco", p.get("preco", 0)))
            preco_concorrente = _to_float(dados.get("preco_concorrente", 0), 0)
            fonte_concorrente = "payload" if preco_concorrente > 0 else "indisponivel"

            # Concorrente AO VIVO: se não veio no payload e for ML com item_id, busca em tempo real
            if preco_concorrente <= 0 and canal == "mercadolivre":
                item_id_ml = dados.get("item_id")
                if item_id_ml:
                    vivo = _to_float(buscar_menor_preco_concorrente(str(item_id_ml)), 0)
                    if vivo > 0:
                        preco_concorrente = vivo
                        fonte_concorrente = "ao_vivo"

            taxa_canal = _to_float(dados.get("taxa_canal_pct", TAXA_CANAL_PADRAO_PCT), TAXA_CANAL_PADRAO_PCT)

            sinais = None
            diagnostico_comportamento = None
            if PRECIFICACAO_COMPORTAMENTO_ATIVO:
                termo = ""
                if sku in monitor_por_sku:
                    termo = str(monitor_por_sku[sku].get("termo_busca") or "").strip()
                try:
                    from integracoes.marketplaces.sinais_comprador import coletar_sinais

                    sinais_raw = coletar_sinais(canal, dados, sku=sku, termo_busca=termo)
                    if preco_concorrente <= 0:
                        vivo_sinais = _to_float(
                            sinais_raw.get("preco_concorrente_vivo") or sinais_raw.get("menor_preco"),
                            0,
                        )
                        if vivo_sinais > 0:
                            preco_concorrente = vivo_sinais
                            fonte_concorrente = "sinais_comprador"
                    sinais = {
                        "visitas_7d": sinais_raw.get("visitas_7d"),
                        "visitas_30d": sinais_raw.get("visitas_30d"),
                        "unidades_vendidas_7d": sinais_raw.get("unidades_vendidas_7d"),
                        "vendas_por_dia": sinais_raw.get("vendas_por_dia"),
                        "preco_sugerido_ml": sinais_raw.get("preco_sugerido_ml"),
                        "quantidade_vendida_lider": sinais_raw.get("quantidade_vendida_lider"),
                    }
                except Exception as exc:
                    logger.warning("repricing sinais %s/%s: %s", sku, canal, exc)

            novo_preco, margem, preco_piso, diagnostico_comportamento = _calcular_novo_preco(
                preco_atual=preco_atual,
                custo=custo,
                preco_concorrente=preco_concorrente,
                margem_minima_pct=margem_minima,
                taxa_canal_pct=taxa_canal,
                sinais=sinais,
                preco_fase=_preco_fase_produto(p, fase_atual),
            )
            bloqueio = _faixa_bloqueada(nome, novo_preco)
            ajustar = abs(novo_preco - preco_atual) >= REPRICING_DIFERENCA_MINIMA and not bloqueio

            nota_concorrencia = None
            if ajustar and fonte_concorrente == "ao_vivo" and sku in monitor_por_sku:
                nota_concorrencia = _gerar_nota_concorrencia(
                    nome, preco_atual, preco_concorrente, novo_preco, sku, monitor_por_sku
                )

            resultado_aplicacao = None
            falhou_aplicacao = False
            if ajustar and not dry_run:
                ref = _item_ref(canal, dados, sku)
                fn = _updater(canal)
                if fn and ref:
                    resultado_aplicacao = fn(ref, novo_preco)
                    if resultado_aplicacao:
                        incrementar("repricing.aplicado", tags=[f"canal:{canal}"])
                    else:
                        falhou_aplicacao = True
                        incrementar("repricing.falha_aplicacao", tags=[f"canal:{canal}"])
                        logger.error(
                            "Repricing: falha ao aplicar novo preço sku=%s canal=%s ref=%s novo_preco=%.2f",
                            sku, canal, ref, novo_preco,
                        )
                else:
                    # Sem updater para o canal, ou sem referência válida do item — não é
                    # "sem ajuste necessário", é uma falha de configuração que precisa ser
                    # visível, não silenciosamente contada como sucesso.
                    falhou_aplicacao = True
                    incrementar(
                        "repricing.falha_aplicacao",
                        tags=[f"canal:{canal}", "motivo:sem_ref_ou_updater"],
                    )
                    logger.error(
                        "Repricing: sem updater/ref válido para aplicar preço sku=%s canal=%s ref=%s",
                        sku, canal, ref,
                    )

            ajustes.append(
                {
                    "sku": sku,
                    "canal": canal,
                    "preco_atual": round(preco_atual, 2),
                    "novo_preco": novo_preco,
                    "preco_piso": preco_piso,
                    "custo": round(custo, 2),
                    "fase_atual": str(fase_atual),
                    "taxa_canal_pct": round(taxa_canal, 2),
                    "margem_pct": round(margem, 2),
                    "preco_concorrente": round(preco_concorrente, 2),
                    "fonte_concorrente": fonte_concorrente,
                    "nota_concorrencia": nota_concorrencia,
                    "ajustar": ajustar,
                    "aplicado": resultado_aplicacao,
                    "falhou_aplicacao": falhou_aplicacao,
                    "motivo": bloqueio
                    or (
                        "; ".join(diagnostico_comportamento.get("motivos", []))
                        if diagnostico_comportamento
                        else f"piso por fase {margem_minima:.1f}% + taxa canal {taxa_canal:.1f}%"
                    ),
                    "comportamento": (
                        diagnostico_comportamento.get("comportamento") if diagnostico_comportamento else None
                    ),
                    "acao_precificacao": (
                        diagnostico_comportamento.get("acao") if diagnostico_comportamento else None
                    ),
                }
            )

    total_ajustes = sum(1 for a in ajustes if a["ajustar"])
    total_aplicados_sucesso = sum(1 for a in ajustes if a["ajustar"] and not dry_run and a["aplicado"])
    total_falhas_aplicacao = sum(1 for a in ajustes if a["falhou_aplicacao"])
    economia_estimada = _calcular_economia_estimada_piso_margem(ajustes)

    if total_ajustes > 0:
        notas = [a["nota_concorrencia"] for a in ajustes if a.get("nota_concorrencia")]
        bloco_notas = ("\n" + "\n".join(f"• {n}" for n in notas[:5])) if notas else ""
        if dry_run:
            alertar_gestor(
                f"Repricing marketplaces: {total_ajustes} ajustes detectados\n"
                f"Modo: simulação | lucro mínimo: {lucro_minimo:.1f}%{bloco_notas}"
            )
        else:
            alertar_gestor(
                f"Repricing marketplaces: {total_aplicados_sucesso}/{total_ajustes} ajustes aplicados com sucesso\n"
                f"Modo: aplicação | lucro mínimo: {lucro_minimo:.1f}%{bloco_notas}"
            )

    if total_falhas_aplicacao > 0:
        skus_falha = sorted({a["sku"] for a in ajustes if a["falhou_aplicacao"]})
        alertar_critico(
            f"⚠️ Repricing: {total_falhas_aplicacao} ajuste(s) de preço FALHARAM ao aplicar "
            f"(preço antigo continua valendo nos marketplaces).\n"
            f"SKUs afetados: {', '.join(skus_falha[:10])}"
        )

    payload = {
        "dry_run": dry_run,
        "lucro_minimo_pct": lucro_minimo,
        "total_itens": len(ajustes),
        "total_ajustes": total_ajustes,
        "total_aplicados_sucesso": total_aplicados_sucesso,
        "total_falhas_aplicacao": total_falhas_aplicacao,
        "economia_estimada_piso_margem": economia_estimada,
        "ajustes": ajustes,
    }
    logger.info("Repricing marketplaces: %s", payload)
    try:
        if total_ajustes:
            incrementar(
                "repricing.ajustes_candidatos",
                float(total_ajustes),
                tags=[f"dry_run:{str(bool(dry_run)).lower()}"],
            )
        incrementar("repricing.rodadas", tags=[f"dry_run:{str(bool(dry_run)).lower()}"])
    except Exception:
        pass
    return payload
