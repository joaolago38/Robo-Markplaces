"""
agentes/filamentos/agente_monitor_filamentos_ml.py
Monitora filamentos 3D no Mercado Livre: preços, cores, marcas e cruzamento Alibaba.

Catálogo ML: catalogo/filamentos_3d_monitor.json
Catálogo Alibaba: catalogo/alibaba_produtos_importacao.json (itens filamento)

Uso:
  python -m agentes.filamentos.agente_monitor_filamentos_ml
  python -m agentes.filamentos.agente_monitor_filamentos_ml --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
    FILAMENTOS_ML_ALERTA_RESUMO,
    FILAMENTOS_ML_ALIBABA_MAX_CORES,
    FILAMENTOS_ML_ALIBABA_PAUSA_SEG,
    FILAMENTOS_ML_CATALOGO,
    FILAMENTOS_ML_CRUZAR_ALIBABA,
    FILAMENTOS_ML_PAUSA_SEG,
    FILAMENTOS_SOURCING_ATIVO,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.graficos import grafico_evolucao
from core.notificador import alertar_gestor, chave_resumo_periodo, enviar_foto_gestor, gestor_telegram_configurado
from core.series_historica import formatar_comparativo, registrar_ponto
from integracoes.filamentos.analise_filamentos_ml import (
    consolidar_varredura,
    enriquecer_avaliacoes_amostra,
    fmt_vendas_amostra,
    processar_termo,
    resumo_decisao_filamentos,
)
from integracoes.filamentos.cruzamento_alibaba import cruzar_filamentos_ml_alibaba, formatar_secao_cruzamento
from integracoes.filamentos.sourcing_filamentos import analisar_sourcing, formatar_secao_sourcing
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_filamentos_ml")

# Materiais alvo do monitor (Telegram + catálogo ativo)
MATERIAIS_MONITORADOS = ("TPU", "PLA", "PETG", "ABS")

SNAPSHOT_PATH = ROOT / "logs" / "filamentos_ml_ultima.json"
HISTORY_PATH = ROOT / "logs" / "filamentos_ml_history.json"
SERIES_PATH = ROOT / "logs" / "filamentos_ml_series.json"
GRAFICO_PATH = ROOT / "logs" / "filamentos_ml_grafico.png"

_SERIES_CAMPOS = [
    ("total_filamentos", "Filamentos únicos"),
    ("total_vendas", "Vendas (proxy)"),
    ("preco_medio", "Preço médio"),
]


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / FILAMENTOS_ML_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo filamentos ML: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "n/d"
    if v <= 0:
        return "n/d"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_volume_ranking(item: dict[str, Any]) -> str:
    """Texto de volume: vendas reais, visitas ou n/d (não imprime '0 vendas')."""
    vend = int(item.get("vendidos") or 0)
    if vend > 0:
        return f"{vend} vendas"
    fonte = str(item.get("fonte_volume") or "")
    proxy = int(item.get("volume_proxy") or 0)
    if fonte == "visitas" and proxy > 0:
        return f"{proxy} vis (proxy)"
    return "vendas n/d"


def _custo_masterprint_1kg() -> float | None:
    try:
        from integracoes.filamentos.custos_masterprint_petg import carregar_tabela_custos

        tab = carregar_tabela_custos()
        c = float(tab.get("custo_padrao_1kg_brl") or 0)
        return c if c > 0 else None
    except Exception:
        return None


def _montar_secao_decisao(consolidado: dict[str, Any]) -> list[str]:
    from core.config import FILAMENTOS_SOURCING_TAXA_ML_PCT

    decisao = consolidado.get("decisao") or resumo_decisao_filamentos(
        consolidado,
        custo_1kg_brl=_custo_masterprint_1kg(),
        taxa_ml_pct=FILAMENTOS_SOURCING_TAXA_ML_PCT,
    )
    fonte = str(decisao.get("fonte_cores") or "presenca_anuncios")
    conf = int(decisao.get("confianca_cores_pct") or 25)
    linhas = [
        "",
        "*🎯 Decisão (o que usar / o que ignorar)*",
        f"_Confiança cores: ~{conf}% (fonte: {fonte})_",
        "• *Usar:* faixa de preço, sortimento, custo×margem",
        "• *Não usar:* volume de vendas da API (concorrente = n/d)",
    ]
    top = decisao.get("top_cores") or []
    if top:
        linhas.append(f"• *Cores em evidência:* {', '.join(str(c) for c in top)}")
    sat = decisao.get("cores_saturadas") or []
    if sat:
        linhas.append(f"• *Mais concorridas:* {', '.join(str(c) for c in sat)}")
    nicho = decisao.get("cores_nicho") or []
    if nicho:
        linhas.append(f"• *Nicho (poucos anúncios):* {', '.join(str(c) for c in nicho)}")

    custo = decisao.get("custo_1kg_brl")
    preco_med = float(decisao.get("preco_medio") or 0)
    piso = decisao.get("preco_piso_sugerido")
    margem = decisao.get("margem_no_preco_medio") or {}
    if custo and preco_med > 0:
        linhas.append(
            f"• *Custo Masterprint 1kg:* {_fmt_brl(custo)} | "
            f"mercado médio {_fmt_brl(preco_med)}"
        )
        if margem.get("ok"):
            linhas.append(
                f"• *Margem no preço médio:* {margem.get('margem_pct')}% "
                f"({_fmt_brl(margem.get('margem_brl'))}/un após taxa)"
            )
        if piso:
            linhas.append(
                f"• *Preço piso (~{decisao.get('margem_alvo_pct')}% alvo):* {_fmt_brl(piso)}"
            )
    linhas.append(
        "• *Próximo passo:* comparar margem no preço médio e funil próprio "
        "(visitas→pedidos); visitas de rivais são proxy, não vendas"
    )
    return linhas


def _resumo_por_material(resultados: list[dict[str, Any]]) -> list[str]:
    """Uma linha por material alvo (TPU/PLA/PETG/ABS), agregando termos do mesmo material."""
    por_mat: dict[str, dict[str, Any]] = {}
    for r in resultados:
        if not r.get("ok"):
            continue
        mat = str(r.get("material") or "").strip().upper() or "?"
        if mat == "PLA+":
            mat = "PLA"
        bucket = por_mat.setdefault(
            mat,
            {"anuncios": 0, "precos": [], "termos": 0},
        )
        bucket["termos"] += 1
        bucket["anuncios"] += int(r.get("total_filamentos") or 0)
        for chave in ("preco_min", "preco_max", "preco_medio"):
            try:
                v = float(r.get(chave) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                bucket["precos"].append(v)

    linhas: list[str] = []
    for mat in MATERIAIS_MONITORADOS:
        b = por_mat.get(mat)
        if not b:
            linhas.append(f"• *{mat}*: sem anúncios nesta rodada")
            continue
        precos = b["precos"]
        media = round(sum(precos) / len(precos), 2) if precos else None
        linhas.append(
            f"• *{mat}*: {b['anuncios']} anúncio(s) | "
            f"média {_fmt_brl(media)} | {b['termos']} busca(s)"
        )
    return linhas


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    resultados: list[dict[str, Any]],
    *,
    serie: list[dict[str, Any]] | None = None,
    cruzamento: dict[str, Any] | None = None,
    sourcing: dict[str, Any] | None = None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    mats = " · ".join(MATERIAIS_MONITORADOS)
    vendas_txt = fmt_vendas_amostra(consolidado.get("total_vendas"))
    if vendas_txt == "n/d":
        vendas_linha = "Vendas (API): *n/d* — ranking por presença/avaliações"
    else:
        com_dado = int(consolidado.get("anuncios_com_vendas_api") or 0)
        vendas_linha = (
            f"Vendas (API, {com_dado} anúncio(s)): *{int(consolidado.get('total_vendas') or 0):,}*".replace(
                ",", "."
            )
        )
    linhas = [
        cabecalho_agente(
            "monitor_filamentos_ml",
            "🧵 *Filamentos 3D — Mercado Livre*",
        ),
        "",
        f"*Materiais monitorados:* {mats}",
        f"Anúncios únicos: *{consolidado.get('total_filamentos_unicos', 0)}* | {vendas_linha}",
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Termos varridos: {consolidado.get('termos_varridos', 0)}",
        "",
        "*Por material (TPU / PLA / PETG / ABS)*",
        *_resumo_por_material(resultados),
    ]
    if serie:
        comp = formatar_comparativo(
            serie,
            [
                ("total_filamentos", "Anúncios"),
                ("total_vendas", "Vendas"),
                ("preco_medio", "Preço médio", 2),
            ],
        )
        if comp:
            linhas.extend(["", comp])

    cores = consolidado.get("ranking_cores") or []
    tem_vendas_cores = any(int(c.get("vendidos") or 0) > 0 for c in cores)
    linhas.extend(
        ["", "*Cores mais vendidas (ML)*" if tem_vendas_cores else "*Cores mais presentes (ML — vendas API n/d)*"]
    )
    if cores:
        for item in cores[:8]:
            vol = _fmt_volume_ranking(item)
            linhas.append(
                f"• {item.get('cor', '?')}: {vol} | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma cor detectada nos títulos nesta rodada._")

    ranking = consolidado.get("ranking_marcas") or []
    tem_vendas_marcas = any(int(m.get("vendidos") or 0) > 0 for m in ranking)
    linhas.extend(
        [
            "",
            "*Marcas que mais vendem*"
            if tem_vendas_marcas
            else "*Marcas mais presentes (vendas API n/d)*",
        ]
    )
    if ranking:
        for item in ranking[:8]:
            vol = _fmt_volume_ranking(item)
            linhas.append(
                f"• {item.get('marca', '?')}: {vol} | "
                f"{item.get('anuncios', 0)} anúncio(s) | média {_fmt_brl(item.get('preco_medio'))}"
            )
    else:
        linhas.append("_Nenhuma marca na amostra desta rodada._")

    baratos = consolidado.get("top_baratos") or []
    if baratos:
        linhas.extend(["", "*Mais baratos (1kg proxy)*"])
        for an in baratos[:5]:
            titulo = str(an.get("titulo") or "?")[:50]
            cor = an.get("cor") or "?"
            linhas.append(
                f"• {_fmt_brl(an.get('preco'))} — {titulo} ({an.get('marca', '?')}, {cor})"
            )

    top = consolidado.get("top_vendas") or []
    if top:
        titulo_top = (
            "*Top anúncios (vendas)*"
            if any(int(a.get("quantidade_vendida") or 0) > 0 for a in top)
            else "*Top anúncios (amostra — vendas API n/d)*"
        )
        linhas.extend(["", titulo_top])
        for i, an in enumerate(top[:8], 1):
            titulo = str(an.get("titulo") or "?")[:55]
            vol = fmt_vendas_amostra(an.get("quantidade_vendida"))
            extra = ""
            if vol == "n/d" and an.get("visitas_7d"):
                extra = f" | {int(an.get('visitas_7d') or 0)} vis/7d"
            elif vol == "n/d" and an.get("avaliacoes"):
                extra = f" | {an.get('avaliacoes')} aval."
            linhas.append(
                f"{i}. {titulo} — {_fmt_brl(an.get('preco'))} | "
                f"{vol}{extra} | "
                f"{an.get('marca', '?')} | {an.get('cor', '?')} | {an.get('material', '?')}"
            )

    from integracoes.ml.acoes_funil_ml import formatar_secao_acoes_funil
    from integracoes.ml.coleta_demanda_ml import (
        formatar_secao_funil,
        formatar_secao_pontos_cegos,
        formatar_secao_visitas_rivais,
    )

    linhas.extend(formatar_secao_visitas_rivais(consolidado.get("produtos_unicos") or top))
    linhas.extend(formatar_secao_funil(consolidado.get("funil_proprio")))
    linhas.extend(formatar_secao_acoes_funil(consolidado.get("acoes_funil")))
    linhas.extend(formatar_secao_pontos_cegos(consolidado.get("pontos_cegos")))

    if cruzamento is not None:
        linhas.extend(formatar_secao_cruzamento(cruzamento, fmt_brl=_fmt_brl))

    if sourcing is not None:
        linhas.extend(formatar_secao_sourcing(sourcing, fmt_brl=_fmt_brl))

    linhas.extend(_montar_secao_decisao(consolidado))

    linhas.extend(["", "*Por termo de busca*"])
    for r in resultados:
        if not r.get("ok"):
            continue
        linhas.append(
            f"• {r.get('nome', '?')} ({r.get('material', '?')}): "
            f"{_fmt_brl(r.get('preco_min'))}–{_fmt_brl(r.get('preco_max'))} "
            f"(média {_fmt_brl(r.get('preco_medio'))}) | "
            f"{r.get('total_filamentos', 0)} de {r.get('total_bruto', 0)} anúncio(s)"
        )

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True, *, forcar_telegram: bool = False) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas filamentos ML não serão entregues")

        termos = _carregar_termos()
        if not termos:
            return {"ok": True, "total_termos": 0, "consolidado": {}}

        agora = datetime.now(timezone.utc).isoformat()
        resultados: list[dict[str, Any]] = []

        for i, segmento in enumerate(termos):
            termo = str(segmento.get("termo_busca") or "").strip()
            limite = int(segmento.get("limite_resultados") or 25)
            if not termo:
                continue
            logger.info("Varredura filamentos ML: %s", termo)
            anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
            resultado = processar_termo(segmento, anuncios)
            resultados.append(resultado)

            gauge(
                "filamentos.ml.anuncios",
                float(resultado.get("total_filamentos") or 0),
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            incrementar("filamentos.ml.varreduras", tags=[f"termo:{segmento.get('id', '?')}"])

            if i < len(termos) - 1 and FILAMENTOS_ML_PAUSA_SEG > 0:
                time.sleep(FILAMENTOS_ML_PAUSA_SEG)

        # Avaliações = melhor proxy de demanda quando sold_quantity vem n/d
        n_aval = enriquecer_avaliacoes_amostra(resultados, limite=15)
        logger.info("Enriquecidos com avaliações: %s anúncio(s)", n_aval)

        from integracoes.ml.coleta_demanda_ml import (
            coletar_funil_proprio,
            emitir_metricas_demanda,
            enriquecer_visitas_amostra,
            montar_pontos_cegos,
            registrar_snapshot_demanda,
            calcular_tendencia_demanda,
        )

        n_vis = enriquecer_visitas_amostra(resultados, limite=12)
        logger.info("Enriquecidos com visitas: %s anúncio(s)", n_vis)
        for r in resultados:
            termo_r = str(r.get("termo_busca") or "").strip()
            if not termo_r:
                continue
            registrar_snapshot_demanda(termo_r, r.get("produtos") or [])
            r["tendencia_demanda"] = calcular_tendencia_demanda(termo_r, dias=14)

        consolidado = consolidar_varredura(resultados)
        from core.config import FILAMENTOS_SOURCING_TAXA_ML_PCT

        consolidado["decisao"] = resumo_decisao_filamentos(
            consolidado,
            custo_1kg_brl=_custo_masterprint_1kg(),
            taxa_ml_pct=FILAMENTOS_SOURCING_TAXA_ML_PCT,
        )
        consolidado["avaliacoes_enriquecidas"] = n_aval
        consolidado["visitas_enriquecidas"] = n_vis
        funil = coletar_funil_proprio(
            dias=7,
            max_anuncios=20,
            filtro_titulo=r"filamento|pla|petg|tpu|abs|masterprint",
        )
        consolidado["funil_proprio"] = funil
        consolidado["pontos_cegos"] = montar_pontos_cegos(
            consolidado=consolidado,
            funil=funil,
            visitas_enriquecidas=n_vis,
            contexto="filamentos_ml",
        )
        from integracoes.ml.acoes_funil_ml import processar_e_persistir_acoes

        consolidado["acoes_funil"] = processar_e_persistir_acoes(
            funil,
            contexto="filamentos_ml",
            prefixo_metricas="filamentos.ml",
            enviar_alerta_criticas=bool(enviar_alerta),
        )

        cruzamento: dict[str, Any] | None = None
        if FILAMENTOS_ML_CRUZAR_ALIBABA:
            logger.info(
                "Cruzando ML × Alibaba (top %s cores)",
                FILAMENTOS_ML_ALIBABA_MAX_CORES,
            )
            cruzamento = cruzar_filamentos_ml_alibaba(
                consolidado,
                resultados,
                max_cores=FILAMENTOS_ML_ALIBABA_MAX_CORES,
                pausa_seg=FILAMENTOS_ML_ALIBABA_PAUSA_SEG,
            )
            if not cruzamento.get("ok"):
                logger.warning(
                    "Cruzamento filamentos ML×Alibaba falhou: %s",
                    cruzamento.get("motivo"),
                )
                if enviar_alerta and gestor_telegram_configurado():
                    alertar_gestor(
                        "⚠️ *Filamentos ML × Alibaba*\n"
                        f"Cruzamento sem margem confiável: `{cruzamento.get('motivo', '?')}`\n"
                        "_Câmbio fallback ou catálogo — não use estes números para decisão._",
                        chave="filamentos:cruzamento_cambio_falhou",
                        cooldown_segundos=max(FILAMENTOS_ML_ALERTA_COOLDOWN_SEG, 6 * 3600),
                        agente_id="monitor_filamentos_ml",
                    )
            gauge(
                "filamentos.ml.alibaba_ofertas",
                float(
                    sum(
                        int(c.get("total_oportunidades_alibaba") or 0)
                        for c in (cruzamento.get("cruzamentos") or [])
                    )
                ),
            )
            gauge("filamentos.ml.alibaba_lucrativos", float(cruzamento.get("lucrativos") or 0))

        sourcing: dict[str, Any] | None = None
        if FILAMENTOS_SOURCING_ATIVO:
            cambio_src = None
            if cruzamento and cruzamento.get("cambio_usd_brl"):
                try:
                    cambio_src = float(cruzamento["cambio_usd_brl"])
                except (TypeError, ValueError):
                    cambio_src = None
            sourcing = analisar_sourcing(
                consolidado,
                resultados,
                cruzamento=cruzamento,
                cambio_usd_brl=cambio_src,
            )
            resumo_v = sourcing.get("resumo_vereditos") or {}
            gauge("filamentos.sourcing.comprar_br", float(resumo_v.get("COMPRAR_BR") or 0))
            gauge("filamentos.sourcing.importar_china", float(resumo_v.get("IMPORTAR_CHINA") or 0))
            gauge("filamentos.sourcing.nao_compensa", float(resumo_v.get("NAO_COMPENSA") or 0))

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "consolidado": consolidado,
                "resultados": resultados,
                "cruzamento_alibaba": cruzamento,
                "sourcing": sourcing,
            },
        )

        serie = registrar_ponto(
            SERIES_PATH,
            {
                "ts": agora,
                "total_filamentos": consolidado.get("total_filamentos_unicos") or 0,
                "total_vendas": consolidado.get("total_vendas") or 0,
                "preco_medio": consolidado.get("preco_medio") or 0,
            },
        )

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}
        historico["ultima_varredura"] = agora
        historico["total_filamentos_unicos"] = consolidado.get("total_filamentos_unicos")
        historico["total_vendas"] = consolidado.get("total_vendas")
        historico["lider_marca"] = (consolidado.get("ranking_marcas") or [{}])[0].get("marca")
        historico["lider_cor"] = (consolidado.get("ranking_cores") or [{}])[0].get("cor")
        if cruzamento:
            historico["alibaba_lucrativos"] = cruzamento.get("lucrativos")
        if sourcing:
            historico["sourcing_resumo"] = sourcing.get("resumo_vereditos")
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and FILAMENTOS_ML_ALERTA_RESUMO and gestor_telegram_configurado():
            msg = montar_mensagem_telegram(
                consolidado,
                resultados,
                serie=serie,
                cruzamento=cruzamento,
                sourcing=sourcing,
            )
            chave = chave_resumo_periodo("filamentos:ml_monitor", horas_por_bucket=6)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_filamentos_ml",
                    _ignorar_cooldown=forcar_telegram,
                )
            )
            grafico = grafico_evolucao(
                serie, _SERIES_CAMPOS, GRAFICO_PATH, titulo="Filamentos 3D ML — evolução"
            )
            if grafico:
                enviar_foto_gestor(
                    str(grafico),
                    "📊 Filamentos 3D ML — evolução vs rodadas anteriores",
                    chave=f"{chave}:grafico",
                    cooldown_segundos=FILAMENTOS_ML_ALERTA_COOLDOWN_SEG,
                )

        gauge("filamentos.ml.total_unicos", float(consolidado.get("total_filamentos_unicos") or 0))
        gauge("filamentos.ml.total_vendas", float(consolidado.get("total_vendas") or 0))
        gauge("filamentos.ml.visitas_amostra", float(consolidado.get("total_visitas_7d_amostra") or 0))
        emitir_metricas_demanda(
            "filamentos.ml",
            funil=consolidado.get("funil_proprio"),
            pontos_cegos=consolidado.get("pontos_cegos"),
            visitas_enriquecidas=int(consolidado.get("visitas_enriquecidas") or 0),
        )
        try:
            from integracoes.filamentos.metricas_top_anuncios import (
                emitir_ranking_marcas,
                emitir_top_anuncios,
            )

            emitir_ranking_marcas("filamentos.ml", consolidado.get("ranking_marcas") or [])
            # Só anúncios Masterprint entre os top vendas do mercado
            top = consolidado.get("top_vendas") or []
            mp = [
                p
                for p in top
                if "masterprint" in str(p.get("marca") or "").lower()
                or "masterprint" in str(p.get("titulo") or "").lower()
            ]
            if not mp:
                mp = [
                    p
                    for p in top
                    if "master" in str(p.get("titulo") or "").lower()
                ]
            if mp:
                emitir_top_anuncios(
                    "filamentos.ml.masterprint",
                    mp,
                    top_n=10,
                )
            # Top mercado geral (todas as marcas) — separado do recorte Masterprint
            emitir_top_anuncios(
                "filamentos.ml",
                top,
                top_n=10,
            )
        except Exception as exc:
            logger.debug("metricas top anuncios filamentos: %s", exc)
        incrementar("filamentos.ml.rodadas")

        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "cruzamento_alibaba": cruzamento,
            "sourcing": sourcing,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente filamentos ML erro: %s", exc)
        incrementar("filamentos.ml.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor filamentos 3D ML × Alibaba")
    parser.add_argument("--sem-alerta", action="store_true")
    parser.add_argument(
        "--agora",
        action="store_true",
        help="Envia Telegram ignorando cooldown (pedido manual)",
    )
    args = parser.parse_args(argv)

    logger.info("=== Monitor filamentos 3D ML × Alibaba ===")
    out = executar(
        enviar_alerta=not args.sem_alerta,
        forcar_telegram=bool(args.agora),
    )
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    cruz = out.get("cruzamento_alibaba") or {}
    src = out.get("sourcing") or {}
    logger.info(
        "Concluído: %s termo(s), %s anúncio(s), cor líder=%s, alibaba lucrativos=%s, "
        "sourcing=%s, alerta=%s",
        out.get("total_termos"),
        c.get("total_filamentos_unicos"),
        (c.get("ranking_cores") or [{}])[0].get("cor"),
        cruz.get("lucrativos"),
        src.get("resumo_vereditos"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
