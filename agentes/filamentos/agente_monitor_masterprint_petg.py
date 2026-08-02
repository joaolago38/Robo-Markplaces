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


def _linha_anuncio(p: dict[str, Any], *, com_delta: bool = False) -> str:
    titulo = str(p.get("titulo") or "?")[:55]
    margem = p.get("margem_brl")
    custo = p.get("custo_unitario_brl")
    if margem is not None and custo is not None:
        base = (
            f"• {_fmt_brl(p.get('preco'))} | custo {_fmt_brl(custo)} | "
            f"margem {_fmt_brl(margem)} ({p.get('margem_pct', '?')}%) | "
            f"{int(p.get('quantidade_vendida') or 0)} vendas | "
            f"lucro {_fmt_brl(p.get('lucro_proxy'))} — {titulo}"
        )
    else:
        base = (
            f"• {_fmt_brl(p.get('preco'))} | {int(p.get('quantidade_vendida') or 0)} vendas | "
            f"rec. {_fmt_brl(p.get('receita_proxy'))} — {titulo}"
        )
    if com_delta:
        dv = int(p.get("delta_vendas") or 0)
        dr = p.get("delta_receita")
        base += f" | Δvendas +{dv} Δrec {_fmt_brl(dr)}"
    iid = str(p.get("item_id") or "").strip()
    if iid:
        base += f"\n  `{iid}`"
    return base


def montar_mensagem_telegram(
    consolidado: dict[str, Any],
    *,
    avaliacao_ia: dict[str, Any] | None = None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente
    from integracoes.masterprint.avaliacao_ia_secundaria import formatar_secao_ia_masterprint
    from integracoes.masterprint.ramo import linha_identidade_telegram

    linhas = [
        cabecalho_agente(
            "monitor_masterprint_petg",
            "🧵 *Masterprint PETG — Mercado Livre*",
        ),
        linha_identidade_telegram(),
        "",
        f"Anúncios ativos: *{consolidado.get('total_anuncios_ativos', 0)}*",
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Custo tabela 1kg: {_fmt_brl(consolidado.get('custo_padrao_1kg_brl'))} "
        f"_(válida {consolidado.get('tabela_valida_em') or 'n/d'})_",
        f"Margem média: {_fmt_brl(consolidado.get('margem_media_brl'))} | "
        f"Lucro proxy: {_fmt_brl(consolidado.get('lucro_proxy_total'))}",
        f"Vendas (proxy): *{consolidado.get('vendas_totais', 0)}* | "
        f"Receita proxy: {_fmt_brl(consolidado.get('receita_proxy_total'))}",
        f"Termos varridos: {consolidado.get('termos_varridos', 0)}",
        "",
        "*Mais rentáveis* _(margem real = líquido ML − custo tabela)_",
    ]
    rent = consolidado.get("mais_rentaveis") or []
    if rent:
        for p in rent[:8]:
            linhas.append(_linha_anuncio(p))
    else:
        linhas.append("_Nenhum anúncio Masterprint PETG encontrado nesta rodada._")

    linhas.extend(["", "*Maior ganho* _(Δ vendas vs rodada anterior)_"])
    ganhos = consolidado.get("maior_ganho") or []
    if ganhos:
        fonte = ganhos[0].get("ganho_fonte")
        if fonte == "sem_historico_usa_vendas":
            linhas.append("_Sem histórico ainda — ranking por vendas atuais._")
        for p in ganhos[:8]:
            linhas.append(_linha_anuncio(p, com_delta=True))
    else:
        linhas.append("_Sem ganho detectado vs rodada anterior._")

    linhas.extend(["", "*Mais vendidos*"])
    for p in (consolidado.get("mais_vendidos") or [])[:5]:
        linhas.append(_linha_anuncio(p))

    secao_ia = formatar_secao_ia_masterprint(avaliacao_ia)
    if secao_ia:
        linhas.append(secao_ia)

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
