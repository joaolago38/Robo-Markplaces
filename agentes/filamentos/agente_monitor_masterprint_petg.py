"""
agentes/filamentos/agente_monitor_masterprint_petg.py
Monitora anúncios Masterprint PETG no Mercado Livre.

Entrega no Telegram:
  - total de anúncios ativos
  - mais rentáveis por margem real (tabela Masterprint − taxa ML)
  - maior ganho (Δ vendas vs rodada anterior)

Uso:
  python -m agentes.filamentos.agente_monitor_masterprint_petg
  python -m agentes.filamentos.agente_monitor_masterprint_petg --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    MASTERPRINT_PETG_ALERTA_COOLDOWN_SEG,
    MASTERPRINT_PETG_ALERTA_RESUMO,
    MASTERPRINT_PETG_CATALOGO,
    MASTERPRINT_PETG_PAUSA_SEG,
    MASTERPRINT_PETG_TOP_N,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.filamentos.analise_masterprint_petg import (
    consolidar_masterprint_petg,
    processar_termo_masterprint,
)
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_masterprint_petg")

SNAPSHOT_PATH = ROOT / "logs" / "masterprint_petg_ultima.json"
HISTORY_PATH = ROOT / "logs" / "masterprint_petg_history.json"


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / MASTERPRINT_PETG_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo Masterprint PETG: %s", exc)
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


def _fmt_vendas(valor: Any) -> str:
    try:
        n = int(valor or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "n/d"
    return f"{n} vendas"


def _linha_anuncio(
    p: dict[str, Any],
    *,
    modo: str = "rentavel",
    com_delta: bool = False,
) -> str:
    """modo: rentavel | ganho | vendas | visitas — evita repetir os mesmos campos em toda seção."""
    titulo = str(p.get("titulo") or "?")[:55]
    preco = _fmt_brl(p.get("preco"))
    vend_txt = _fmt_vendas(p.get("quantidade_vendida"))
    vis7 = int(p.get("visitas_7d") or 0)
    if modo == "visitas":
        base = f"• {preco} | {vis7} vis/7d | {vend_txt} — {titulo}"
    elif modo == "vendas":
        rec = p.get("receita_proxy")
        rec_txt = _fmt_brl(rec) if float(rec or 0) > 0 else "n/d"
        base = f"• {preco} | {vend_txt} | rec. {rec_txt} — {titulo}"
    elif modo == "ganho":
        base = f"• {preco} | {vend_txt} — {titulo}"
    else:
        margem = p.get("margem_brl")
        custo = p.get("custo_unitario_brl")
        if margem is not None and custo is not None:
            vis_extra = f" | {vis7} vis/7d" if vis7 > 0 else ""
            base = (
                f"• {preco} | custo {_fmt_brl(custo)} | "
                f"margem {_fmt_brl(margem)} ({p.get('margem_pct', '?')}%) | "
                f"lucro {_fmt_brl(p.get('lucro_proxy'))}{vis_extra} — {titulo}"
            )
        else:
            base = f"• {preco} | {vend_txt} — {titulo}"
    if com_delta:
        dv = int(p.get("delta_vendas") or 0)
        if dv > 0:
            base += f" | Δvendas +{dv}"
    iid = str(p.get("item_id") or "").strip()
    if iid:
        base += f"\n  `{iid}`"
    return base


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    *,
    avaliacao_ia: dict[str, Any] | None = None,
) -> str:
    """
    Card decisão-primeiro:
      1) AGIR — top rentáveis (margem)
      2) ATENÇÃO — maior ganho / anomalias
      3) Panorama + Claude (se houver)
    """
    from core.telegram_explicacao import cabecalho_agente
    from integracoes.masterprint.avaliacao_ia_secundaria import formatar_secao_ia_masterprint
    from integracoes.masterprint.ramo import linha_identidade_telegram

    rent = consolidado.get("mais_rentaveis") or []
    ganhos = consolidado.get("maior_ganho") or []
    sem_historico = bool(ganhos and ganhos[0].get("ganho_fonte") == "sem_historico_usa_vendas")
    vendas_tot = int(consolidado.get("vendas_totais") or 0)
    vendas_panorama = _fmt_vendas(vendas_tot)
    if vendas_panorama == "n/d":
        vendas_panorama = "n/d (API concorrente bloqueada)"

    linhas = [
        cabecalho_agente(
            "monitor_masterprint_petg",
            "🧵 *Masterprint PETG — decisão ML*",
        ),
        linha_identidade_telegram(),
        "",
        (
            f"Panorama: *{consolidado.get('total_anuncios_ativos', 0)}* anúncios | "
            f"margem méd. {_fmt_brl(consolidado.get('margem_media_brl'))} | "
            f"vendas *{vendas_panorama}* | "
            f"custo 1kg {_fmt_brl(consolidado.get('custo_padrao_1kg_brl'))}"
        ),
        (
            f"Preço méd. {_fmt_brl(consolidado.get('preco_medio'))} "
            f"({_fmt_brl(consolidado.get('preco_min'))}–{_fmt_brl(consolidado.get('preco_max'))})"
        ),
        "",
        "*1) AGIR — priorize margem*",
    ]
    if rent:
        for p in rent[:5]:
            linhas.append(_linha_anuncio(p, modo="rentavel"))
    else:
        linhas.append("_Nenhum anúncio Masterprint PETG nesta rodada._")

    linhas.extend(["", "*2) ATENÇÃO — movimento de vendas*"])
    if vendas_tot <= 0:
        linhas.append(
            "_Vendas/receita proxy zeradas: busca `/items` e reviews de terceiros "
            "retornam 403 — use *margem* + *visitas rivais* + funil próprio._"
        )
    elif ganhos:
        if sem_historico:
            linhas.append("_Sem histórico Δ — ranking por vendas atuais._")
        for p in ganhos[:4]:
            linhas.append(_linha_anuncio(p, modo="ganho", com_delta=not sem_historico))
    else:
        linhas.append("_Sem ganho vs rodada anterior._")

    if vendas_tot > 0 and not sem_historico and (consolidado.get("mais_vendidos") or []):
        linhas.extend(["", "*Volume* _(complemento)_"])
        for p in (consolidado.get("mais_vendidos") or [])[:3]:
            linhas.append(_linha_anuncio(p, modo="vendas"))

    from integracoes.ml.coleta_demanda_ml import (
        formatar_secao_funil,
        formatar_secao_pontos_cegos,
        top_por_visitas,
    )
    from integracoes.ml.acoes_funil_ml import formatar_secao_acoes_funil

    rivais_vis = top_por_visitas(consolidado.get("produtos") or [], top_n=5)
    if rivais_vis:
        linhas.extend(["", "*3) DEMANDA — rivais com visitas*"])
        for p in rivais_vis:
            linhas.append(_linha_anuncio(p, modo="visitas"))

    linhas.extend(formatar_secao_funil(consolidado.get("funil_proprio")))
    linhas.extend(formatar_secao_acoes_funil(consolidado.get("acoes_funil")))
    linhas.extend(formatar_secao_pontos_cegos(consolidado.get("pontos_cegos")))

    secao_ia = formatar_secao_ia_masterprint(avaliacao_ia, com_tagline_ramo=False)
    if secao_ia:
        linhas.append(secao_ia)

    linhas.extend(
        [
            "",
            "_Decisão:_ empurre o top de *margem*; use visitas rivais como proxy de demanda; "
            "Δ vendas só quando a API liberar `sold_quantity`.",
        ]
    )
    return "\n".join(linhas).strip()


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas Masterprint não serão entregues")

        termos = _carregar_termos()
        if not termos:
            return {"ok": True, "total_termos": 0, "consolidado": {}}

        snap_ant = ler_json(SNAPSHOT_PATH, default={})
        produtos_ant = None
        if isinstance(snap_ant, dict):
            produtos_ant = (snap_ant.get("consolidado") or {}).get("produtos")

        agora = datetime.now(timezone.utc).isoformat()
        resultados: list[dict[str, Any]] = []

        for i, segmento in enumerate(termos):
            termo = str(segmento.get("termo_busca") or "").strip()
            limite = int(segmento.get("limite_resultados") or 50)
            if not termo:
                continue
            logger.info("Varredura Masterprint PETG: %s", termo)
            anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
            resultado = processar_termo_masterprint(segmento, anuncios)
            resultados.append(resultado)
            incrementar(
                "masterprint_petg.varreduras",
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            if i < len(termos) - 1 and MASTERPRINT_PETG_PAUSA_SEG > 0:
                time.sleep(MASTERPRINT_PETG_PAUSA_SEG)

        consolidado = consolidar_masterprint_petg(
            resultados,
            produtos_anteriores=produtos_ant if isinstance(produtos_ant, list) else None,
            top_n=MASTERPRINT_PETG_TOP_N,
        )

        from integracoes.ml.coleta_demanda_ml import (
            coletar_funil_proprio,
            emitir_metricas_demanda,
            enriquecer_visitas_lista,
            montar_pontos_cegos,
        )

        produtos = consolidado.get("produtos") or []
        # Ordena por margem para priorizar amostra útil
        amostra = sorted(
            produtos,
            key=lambda p: float(p.get("margem_brl") or 0),
            reverse=True,
        )
        n_vis = enriquecer_visitas_lista(amostra, limite=12)
        # Propaga visitas de volta à lista consolidada (mesmos dicts)
        consolidado["visitas_enriquecidas"] = n_vis
        consolidado["anuncios_com_visitas"] = sum(
            1 for p in produtos if int(p.get("visitas_7d") or 0) > 0
        )
        funil = coletar_funil_proprio(
            dias=7,
            max_anuncios=20,
            filtro_titulo=r"petg|masterprint|filamento",
        )
        consolidado["funil_proprio"] = funil
        consolidado["pontos_cegos"] = montar_pontos_cegos(
            consolidado={
                **consolidado,
                "anuncios_com_vendas_api": int(consolidado.get("vendas_totais") or 0),
                "anuncios_com_avaliacoes": 0,
            },
            funil=funil,
            visitas_enriquecidas=n_vis,
            contexto="masterprint_petg",
        )
        from integracoes.ml.acoes_funil_ml import processar_e_persistir_acoes
        from integracoes.masterprint.ramo import chat_gestor_masterprint

        consolidado["acoes_funil"] = processar_e_persistir_acoes(
            funil,
            contexto="masterprint_petg",
            prefixo_metricas="masterprint_petg",
            enviar_alerta_criticas=bool(enviar_alerta),
            chat_id=chat_gestor_masterprint(),
        )

        from integracoes.masterprint.avaliacao_ia_secundaria import avaliar_masterprint_secundario

        avaliacao_ia = avaliar_masterprint_secundario(escopo="petg", consolidado=consolidado)

        escrever_json_atomico(
            SNAPSHOT_PATH,
            {
                "timestamp": agora,
                "consolidado": consolidado,
                "resultados": resultados,
                "avaliacao_ia": avaliacao_ia,
            },
        )

        hist = ler_json(HISTORY_PATH, default={"rodadas": []})
        if not isinstance(hist, dict):
            hist = {"rodadas": []}
        rodadas = list(hist.get("rodadas") or [])
        rodadas.append(
            {
                "timestamp": agora,
                "total_anuncios_ativos": consolidado.get("total_anuncios_ativos"),
                "vendas_totais": consolidado.get("vendas_totais"),
                "receita_proxy_total": consolidado.get("receita_proxy_total"),
                "preco_medio": consolidado.get("preco_medio"),
                "lucro_proxy_total": consolidado.get("lucro_proxy_total"),
                "margem_media_brl": consolidado.get("margem_media_brl"),
            }
        )
        hist["rodadas"] = rodadas[-40:]
        hist["ultima"] = agora
        escrever_json_atomico(HISTORY_PATH, hist)

        gauge("masterprint_petg.anuncios", float(consolidado.get("total_anuncios_ativos") or 0))
        gauge("masterprint_petg.vendas", float(consolidado.get("vendas_totais") or 0))
        gauge("masterprint_petg.receita_proxy", float(consolidado.get("receita_proxy_total") or 0))
        gauge("masterprint_petg.lucro_proxy", float(consolidado.get("lucro_proxy_total") or 0))
        if consolidado.get("margem_media_brl") is not None:
            gauge("masterprint_petg.margem_media_brl", float(consolidado.get("margem_media_brl") or 0))
        if consolidado.get("preco_medio") is not None:
            gauge("masterprint_petg.preco_medio", float(consolidado.get("preco_medio") or 0))
        emitir_metricas_demanda(
            "masterprint_petg",
            funil=consolidado.get("funil_proprio"),
            pontos_cegos=consolidado.get("pontos_cegos"),
            visitas_enriquecidas=int(consolidado.get("visitas_enriquecidas") or 0),
        )
        try:
            from integracoes.filamentos.metricas_top_anuncios import (
                emitir_top_anuncios,
                enriquecer_sellers,
            )

            # Top anúncios + maiores sellers (porte ML quando sold_quantity=0)
            base = consolidado.get("produtos") or consolidado.get("mais_vendidos") or []
            perfis = enriquecer_sellers(base, max_sellers=MASTERPRINT_PETG_TOP_N)
            emitir_top_anuncios(
                "masterprint_petg",
                base,
                top_n=MASTERPRINT_PETG_TOP_N,
                sellers_perfil=perfis,
            )
        except Exception as exc:
            logger.debug("metricas top anuncios petg: %s", exc)

        alerta_enviado = False
        from integracoes.masterprint.ramo import chat_gestor_masterprint

        chat_mp = chat_gestor_masterprint()
        if enviar_alerta and MASTERPRINT_PETG_ALERTA_RESUMO and gestor_telegram_configurado(chat_mp):
            msg = montar_mensagem_telegram(consolidado, avaliacao_ia=avaliacao_ia)
            chave = chave_resumo_periodo("masterprint:petg", horas_por_bucket=6)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=MASTERPRINT_PETG_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_masterprint_petg",
                    chat_id=chat_mp,
                )
            )

        incrementar("masterprint_petg.rodadas")
        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "avaliacao_ia": avaliacao_ia,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente Masterprint PETG erro: %s", exc)
        incrementar("masterprint_petg.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Monitor Masterprint PETG no ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s anúncio(s) ativos, receita proxy=%s, alerta=%s",
        c.get("total_anuncios_ativos"),
        c.get("receita_proxy_total"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
