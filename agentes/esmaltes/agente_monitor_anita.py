"""
agentes/esmaltes/agente_monitor_anita.py
Monitora anúncios de esmaltes Anita no ML: diferença de cores/kits vs preferência,
ranking de marcas por vendas e margem de lucro.

Catálogo: catalogo/anita_esmaltes_monitorados.json

Uso:
  python -m agentes.esmaltes.agente_monitor_anita
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ANITA_ALERTA_RESUMO,
    ANITA_ALERTA_RESUMO_COOLDOWN_SEG,
    ANITA_ESMALTES_CATALOGO,
    ANITA_PAUSA_ENTRE_BUSCAS_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.esmaltes.analise_anita import analisar_produto
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_anita")

HISTORY_PATH = ROOT / "logs" / "anita_esmaltes_history.json"


def _carregar_produtos() -> list[dict[str, Any]]:
    caminho = ROOT / ANITA_ESMALTES_CATALOGO
    try:
        data = ler_json(caminho, default=[])
        if not isinstance(data, list):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("ativo")]
    except Exception as exc:
        logger.error("Erro ao carregar catálogo Anita: %s", exc)
        return []


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _fmt_pct(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"{float(valor):+.1f}%"
    except (TypeError, ValueError):
        return "n/d"


def _montar_resumo_produto(r: dict[str, Any]) -> list[str]:
    linhas = [f"*{r.get('nome', r.get('id', '?'))}*"]
    margem = r.get("margem_minha") or {}
    meu = r.get("meu_preco")
    linhas.append(
        f"  Seu preço {_fmt_brl(meu)} | margem {margem.get('margem_operacional_pct', 'n/d')}% "
        f"({_fmt_brl(margem.get('lucro_reais'))} lucro)"
    )

    linhas.append(
        f"  Anúncios: {r.get('total_anuncios', 0)} | Anita: {r.get('total_anita', 0)} | "
        f"Líder vendas: *{r.get('marca_mais_vendida', '?')}*"
    )
    if r.get("menor_preco_anita"):
        diff = None
        if meu and r["menor_preco_anita"]:
            diff = round((float(r["menor_preco_anita"]) - float(meu)) / float(meu) * 100, 1)
        linhas.append(
            f"  Menor Anita: {_fmt_brl(r['menor_preco_anita'])} ({_fmt_pct(diff)} vs seu preço)"
        )

    if r.get("tipo") == "kit":
        qtd_pref = None
        for a in r.get("analises") or []:
            if a.get("qtd_kit_preferencia"):
                qtd_pref = a.get("qtd_kit_preferencia")
                break
        if qtd_pref:
            linhas.append(f"  Kit preferência: {qtd_pref} esmaltes | divergências kit: {r.get('divergencias_kit', 0)}")
    if r.get("divergencias_cor", 0) > 0:
        linhas.append(f"  ⚠️ Divergências de cor: {r['divergencias_cor']}")

    ranking = r.get("ranking_marcas") or []
    if ranking:
        top3 = ranking[:3]
        partes = [f"{x['marca']} ({x['vendidos']} vend.)" for x in top3]
        linhas.append(f"  Top marcas: {', '.join(partes)}")

    # Destaque anúncios Anita fora da preferência
    for a in (r.get("analises") or [])[:4]:
        if a.get("marca_detectada") != "Anita":
            continue
        if a.get("conforme_preferencia"):
            continue
        titulo = str(a.get("titulo") or "")[:55]
        detalhes: list[str] = []
        if a.get("diff_qtd_kit") not in (None, 0):
            detalhes.append(f"kit {a.get('qtd_kit_detectada')} vs pref {a.get('qtd_kit_preferencia')}")
        if a.get("cores_faltando"):
            detalhes.append(f"falta: {', '.join(a['cores_faltando'][:3])}")
        if detalhes:
            linhas.append(f"  • {titulo} — {'; '.join(detalhes)}")
    return linhas


def _montar_painel(resultados: list[dict[str, Any]]) -> str:
    linhas = ["💅 *Anita — painel de anúncios (cores, kits, margem)*", ""]
    ranking_global: dict[str, int] = {}
    for r in resultados:
        for item in r.get("ranking_marcas") or []:
            marca = str(item.get("marca") or "?")
            ranking_global[marca] = ranking_global.get(marca, 0) + int(item.get("vendidos") or 0)

    if ranking_global:
        ordenado = sorted(ranking_global.items(), key=lambda x: x[1], reverse=True)
        linhas.append("*Marca mais vendida no mercado (soma dos termos):*")
        for marca, vend in ordenado[:5]:
            linhas.append(f"  • {marca}: {vend} vendas")
        linhas.append("")

    for r in sorted(resultados, key=lambda x: int(x.get("prioridade") or 99)):
        linhas.extend(_montar_resumo_produto(r))
        linhas.append("")

    return "\n".join(linhas).strip()


def _monitorar_produto(produto: dict[str, Any]) -> dict[str, Any]:
    termo = str(produto.get("termo_busca") or "").strip()
    limite = int(produto.get("limite_resultados") or 12)
    if not termo:
        return {"id": produto.get("id"), "ok": False, "motivo": "termo vazio"}

    anuncios = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    analise = analisar_produto(produto, anuncios)
    analise["ok"] = True
    analise["prioridade"] = int(produto.get("prioridade") or 99)
    analise["meu_preco"] = produto.get("meu_preco")

    pid = str(produto.get("id") or "")
    gauge("anita.total_anuncios", float(len(anuncios)), tags=[f"produto:{pid}"])
    gauge("anita.total_anita", float(analise.get("total_anita") or 0), tags=[f"produto:{pid}"])
    margem = analise.get("margem_minha") or {}
    if margem.get("margem_operacional_pct") is not None:
        gauge("anita.margem_pct", float(margem["margem_operacional_pct"]), tags=[f"produto:{pid}"])

    logger.info(
        "Anita %s: %s anúncio(s), %s Anita, líder %s, margem %.1f%%",
        produto.get("nome"),
        len(anuncios),
        analise.get("total_anita"),
        analise.get("marca_mais_vendida"),
        float(margem.get("margem_operacional_pct") or 0),
    )
    return analise


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas Anita não serão entregues")

        produtos = sorted(_carregar_produtos(), key=lambda p: int(p.get("prioridade") or 99))
        if not produtos:
            return {"ok": True, "total_produtos": 0, "resultados": []}

        resultados: list[dict[str, Any]] = []
        agora = datetime.now(timezone.utc).isoformat()

        for i, produto in enumerate(produtos):
            if i > 0 and ANITA_PAUSA_ENTRE_BUSCAS_SEG > 0:
                time.sleep(ANITA_PAUSA_ENTRE_BUSCAS_SEG)
            resultados.append(_monitorar_produto(produto))

        historico = ler_json(HISTORY_PATH, default={})
        historico["ultima_varredura"] = agora
        historico["produtos"] = {
            str(r.get("id")): {
                "marca_mais_vendida": r.get("marca_mais_vendida"),
                "menor_preco_anita": r.get("menor_preco_anita"),
                "margem_pct": (r.get("margem_minha") or {}).get("margem_operacional_pct"),
                "divergencias_kit": r.get("divergencias_kit"),
                "divergencias_cor": r.get("divergencias_cor"),
            }
            for r in resultados
            if r.get("ok")
        }
        escrever_json_atomico(HISTORY_PATH, historico)

        alerta_enviado = False
        if enviar_alerta and ANITA_ALERTA_RESUMO and resultados:
            painel = _montar_painel(resultados)
            alerta_enviado = bool(
                alertar_gestor(
                    painel,
                    chave=chave_resumo_periodo("anita:esmaltes", horas_por_bucket=2),
                    cooldown_segundos=ANITA_ALERTA_RESUMO_COOLDOWN_SEG,
                )
            )

        incrementar("anita.rodadas", tags=[f"produtos:{len(resultados)}"])
        return {
            "ok": True,
            "total_produtos": len(resultados),
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("Agente monitor Anita erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Anita esmaltes ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor Anita esmaltes ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    logger.info("Concluído: %s produto(s), alerta=%s", out.get("total_produtos"), out.get("alerta_enviado"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
