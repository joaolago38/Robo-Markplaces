"""
agentes/escritorio/agente_monitor_masterprint_escritorio.py
Monitora pincéis recarregáveis e apagadores Masterprint no Mercado Livre.

Entrega no Telegram:
  - total de anúncios ativos (por tipo)
  - mais rentáveis por margem real (tabela Masterprint − taxa ML)
  - maior ganho (Δ vendas vs rodada anterior)

Uso:
  python -m agentes.escritorio.agente_monitor_masterprint_escritorio
  python -m agentes.escritorio.agente_monitor_masterprint_escritorio --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    MASTERPRINT_ESCRITORIO_ALERTA_COOLDOWN_SEG,
    MASTERPRINT_ESCRITORIO_ALERTA_RESUMO,
    MASTERPRINT_ESCRITORIO_CATALOGO,
    MASTERPRINT_ESCRITORIO_PAUSA_SEG,
    MASTERPRINT_ESCRITORIO_TOP_N,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.escritorio.analise_masterprint_escritorio import (
    consolidar_masterprint_escritorio,
    processar_termo_escritorio,
)
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_masterprint_escritorio")

SNAPSHOT_PATH = ROOT / "logs" / "masterprint_escritorio_ultima.json"
HISTORY_PATH = ROOT / "logs" / "masterprint_escritorio_history.json"


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / MASTERPRINT_ESCRITORIO_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
        return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))
    except Exception as exc:
        logger.error("Erro ao carregar catálogo Masterprint escritório: %s", exc)
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
    tipo = str(p.get("tipo") or "").replace("_", " ")
    margem = p.get("margem_brl")
    custo = p.get("custo_unitario_brl")
    prefix = f"[{tipo}] " if tipo else ""
    if margem is not None and custo is not None:
        base = (
            f"• {prefix}{_fmt_brl(p.get('preco'))} | custo {_fmt_brl(custo)} | "
            f"margem {_fmt_brl(margem)} ({p.get('margem_pct', '?')}%) | "
            f"{int(p.get('quantidade_vendida') or 0)} vendas | "
            f"lucro {_fmt_brl(p.get('lucro_proxy'))} — {titulo}"
        )
    else:
        base = (
            f"• {prefix}{_fmt_brl(p.get('preco'))} | {int(p.get('quantidade_vendida') or 0)} vendas | "
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

    por = consolidado.get("por_tipo") or {}
    por_txt = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(por.items())) or "n/d"
    ref = consolidado.get("custos_referencia") or {}

    linhas = [
        cabecalho_agente(
            "monitor_masterprint_escritorio",
            "✏️ *Masterprint — pincéis recarregáveis & apagadores*",
        ),
        linha_identidade_telegram(),
        "",
        f"Anúncios ativos: *{consolidado.get('total_anuncios_ativos', 0)}* _( {por_txt} )_",
        f"Preços: {_fmt_brl(consolidado.get('preco_min'))} – "
        f"{_fmt_brl(consolidado.get('preco_max'))} | média {_fmt_brl(consolidado.get('preco_medio'))}",
        f"Custo tabela: permanente cx12 {_fmt_brl(ref.get('pincel_permanente_recarregavel_caixa12_brl'))} | "
        f"quadro cx12 {_fmt_brl(ref.get('pincel_quadro_branco_recarregavel_caixa12_brl'))} | "
        f"apagador {_fmt_brl(ref.get('apagador_quadro_ima_brl'))}",
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
        linhas.append("_Nenhum anúncio encontrado nesta rodada._")

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
            logger.warning("Telegram gestor não configurado — alertas escritório não serão entregues")

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
            logger.info("Varredura Masterprint escritório: %s", termo)
            anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
            resultado = processar_termo_escritorio(segmento, anuncios)
            resultados.append(resultado)
            incrementar(
                "masterprint_escritorio.varreduras",
                tags=[f"termo:{segmento.get('id', '?')}"],
            )
            if i < len(termos) - 1 and MASTERPRINT_ESCRITORIO_PAUSA_SEG > 0:
                time.sleep(MASTERPRINT_ESCRITORIO_PAUSA_SEG)

        consolidado = consolidar_masterprint_escritorio(
            resultados,
            produtos_anteriores=produtos_ant if isinstance(produtos_ant, list) else None,
            top_n=MASTERPRINT_ESCRITORIO_TOP_N,
        )

        from integracoes.masterprint.avaliacao_ia_secundaria import avaliar_masterprint_secundario

        avaliacao_ia = avaliar_masterprint_secundario(
            escopo="escritorio", consolidado=consolidado
        )

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
                "lucro_proxy_total": consolidado.get("lucro_proxy_total"),
                "margem_media_brl": consolidado.get("margem_media_brl"),
                "por_tipo": consolidado.get("por_tipo"),
            }
        )
        hist["rodadas"] = rodadas[-40:]
        hist["ultima"] = agora
        escrever_json_atomico(HISTORY_PATH, hist)

        gauge("masterprint_escritorio.anuncios", float(consolidado.get("total_anuncios_ativos") or 0))
        gauge("masterprint_escritorio.vendas", float(consolidado.get("vendas_totais") or 0))
        gauge("masterprint_escritorio.lucro_proxy", float(consolidado.get("lucro_proxy_total") or 0))

        alerta_enviado = False
        from integracoes.masterprint.ramo import chat_gestor_masterprint

        chat_mp = chat_gestor_masterprint()
        if (
            enviar_alerta
            and MASTERPRINT_ESCRITORIO_ALERTA_RESUMO
            and gestor_telegram_configurado(chat_mp)
        ):
            msg = montar_mensagem_telegram(consolidado, avaliacao_ia=avaliacao_ia)
            chave = chave_resumo_periodo("masterprint:escritorio", horas_por_bucket=6)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave,
                    cooldown_segundos=MASTERPRINT_ESCRITORIO_ALERTA_COOLDOWN_SEG,
                    agente_id="monitor_masterprint_escritorio",
                    chat_id=chat_mp,
                )
            )

        incrementar("masterprint_escritorio.rodadas")
        return {
            "ok": True,
            "total_termos": len(resultados),
            "consolidado": consolidado,
            "avaliacao_ia": avaliacao_ia,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente Masterprint escritório erro: %s", exc)
        incrementar("masterprint_escritorio.erro")
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Monitor Masterprint pincéis/apagadores no ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    c = out.get("consolidado") or {}
    logger.info(
        "Concluído: %s anúncio(s) ativos, lucro proxy=%s, alerta=%s",
        c.get("total_anuncios_ativos"),
        c.get("lucro_proxy_total"),
        out.get("alerta_enviado"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
