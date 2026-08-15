"""
agentes/esmaltes/agente_montar_kits_impala.py
Lê planilha Impala, varre kits mais vendidos no ML e sugere montagem de kits
com as cores que você tem e que estão quentes no mercado.

Uso:
  python -m agentes.esmaltes.agente_montar_kits_impala
  python -m agentes.esmaltes.agente_montar_kits_impala --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ESMALTES_KITS_MONITOR_CATALOGO,
    ESMALTES_KITS_MONITOR_PAUSA_SEG,
    MONTAR_KITS_IMPALA_ALERTA,
    MONTAR_KITS_IMPALA_COOLDOWN_SEG,
    MONTAR_KITS_IMPALA_PLANILHA,
    MONTAR_KITS_IMPALA_TOP_KITS,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes
from integracoes.esmaltes.analise_kits_esmaltes import consolidar_varredura, processar_termo
from integracoes.esmaltes.cruzamento_kits_planilha import cruzar_planilha_com_mercado
from integracoes.esmaltes.kits_compativeis_manicures import (
    formatar_secao_manicure,
    montar_ofertas_manicure,
)
from integracoes.esmaltes.planilha_impala import carregar_kits_planilha, carregar_produtos_planilha
from integracoes.marketplaces.busca_multi_marketplace import resolver_fn_busca_esmaltes

logger = logging.getLogger("agente_montar_kits_impala")

SNAPSHOT_PATH = ROOT / "logs" / "montar_kits_impala_ultima.json"


def _carregar_termos() -> list[dict[str, Any]]:
    caminho = ROOT / ESMALTES_KITS_MONITOR_CATALOGO
    data = ler_json(caminho, default=[])
    if not isinstance(data, list):
        return []
    ativos = [t for t in data if isinstance(t, dict) and t.get("ativo")]
    return sorted(ativos, key=lambda x: int(x.get("prioridade") or 99))


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def montar_mensagem_telegram(cruzamento: dict[str, Any], consolidado: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "montar_kits_impala",
            "🧪 *Montar kits Impala — planilha × ML*",
        ),
        "",
        f"_Cores na planilha: *{cruzamento.get('total_cores_planilha', 0)}* | "
        f"com sinal no ML: *{cruzamento.get('cores_com_demanda', 0)}* | "
        f"kits ML analisados: *{cruzamento.get('total_kits_ml', 0)}*_",
        f"_Preço médio kits ML: {_fmt_brl(consolidado.get('preco_medio'))}_",
        "",
        "*Top cores Impala (demanda nos kits mais vendidos)*",
    ]
    top = cruzamento.get("top_cores") or []
    if not top:
        linhas.append("_Nenhuma cor cruzada nesta rodada — verifique planilha/API ML._")
    for i, cor in enumerate(top[:10], 1):
        linhas.append(
            f"{i}. *{cor.get('nome_cor') or '?'}* — score {float(cor.get('score_demanda') or 0):.1f} | "
            f"{int(cor.get('kits_mencionam') or 0)} kit(s) | "
            f"{int(cor.get('vendas_proxy') or 0)} vendas proxy"
        )
        for ex in (cor.get("exemplos_kits") or [])[:1]:
            linhas.append(f"    _{str(ex.get('titulo') or '')[:55]}_")

    sug = cruzamento.get("kits_sugeridos") or []
    if sug:
        linhas.extend(["", "*Kits sugeridos (cores quentes que você tem)*"])
        for s in sug[:4]:
            nomes = ", ".join(str(c.get("nome_cor") or "") for c in (s.get("cores") or [])[:5])
            linhas.append(
                f"• *{s.get('nome_sugerido')}* — score médio {s.get('score_medio')} | "
                f"faixa {s.get('preco_sugerido_faixa')}"
            )
            linhas.append(f"  Cores: {nomes}")

    cadastrados = cruzamento.get("kits_cadastrados_avaliados") or []
    if cadastrados:
        linhas.extend(["", "*Seus kits da planilha × demanda ML*"])
        for k in cadastrados[:6]:
            emoji = "🟢" if k.get("demanda") == "alta" else ("🟡" if k.get("demanda") == "media" else "⚪")
            linhas.append(
                f"{emoji} {k.get('nome')} — {k.get('demanda')} "
                f"({int(k.get('hits_ml') or 0)} hits | {int(k.get('vendas_proxy') or 0)} vendas)"
            )

    tamanhos = cruzamento.get("tamanhos_quentes_ml") or []
    if tamanhos:
        partes = [
            f"kit {t.get('qtd')} ({int(t.get('vendas') or 0)} vend.)" for t in tamanhos[:5]
        ]
        linhas.extend(["", "*Tamanhos quentes no ML:* " + " · ".join(partes)])

    ofertas_m = cruzamento.get("ofertas_manicure") or {}
    linhas.extend(
        formatar_secao_manicure(
            ofertas_m.get("ofertas_condicao") or ofertas_m.get("ofertas") or []
        )
    )

    linhas.extend(
        [
            "",
            "*Próximo passo:* monte/reative no ML os kits sugeridos, cole o `item_id` em "
            "`catalogo/produtos.json` e rode o monitor Anita/kits.",
        ]
    )
    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre ML + planilha e sugere kits. Nunca lança."""
    try:
        pode_alertar, motivo = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")

        planilha = Path(ROOT / MONTAR_KITS_IMPALA_PLANILHA)
        produtos = carregar_produtos_planilha(planilha)
        kits_p = carregar_kits_planilha(planilha)
        if not produtos:
            incrementar("montar_kits_impala.planilha_vazia")
            return {"ok": False, "erro": "planilha_vazia_ou_ausente", "alerta_enviado": False}

        termos = _carregar_termos()
        buscar = resolver_fn_busca_esmaltes()
        resultados: list[dict[str, Any]] = []
        for i, termo in enumerate(termos):
            try:
                anuncios = buscar(
                    str(termo.get("termo_busca") or ""),
                    limite=int(termo.get("limite_resultados") or 25),
                )
                resultados.append(processar_termo(termo, anuncios or []))
            except Exception as exc:
                logger.error("busca termo %s: %s", termo.get("id"), exc)
                resultados.append({"ok": False, "id": termo.get("id"), "erro": str(exc)})
            if i < len(termos) - 1 and ESMALTES_KITS_MONITOR_PAUSA_SEG > 0:
                time.sleep(ESMALTES_KITS_MONITOR_PAUSA_SEG)

        consolidado = consolidar_varredura(resultados)
        kits_ml = consolidado.get("top_vendas") or []
        # amplia: todos kits únicos do consolidado se houver
        if consolidado.get("total_kits_unicos"):
            # reconstruir lista a partir dos resultados
            por_id: dict[str, dict] = {}
            for r in resultados:
                for kit in r.get("kits") or []:
                    iid = str(kit.get("item_id") or "")
                    if not iid:
                        continue
                    ant = por_id.get(iid)
                    if not ant or int(kit.get("quantidade_vendida") or 0) > int(
                        ant.get("quantidade_vendida") or 0
                    ):
                        por_id[iid] = kit
            if por_id:
                kits_ml = list(por_id.values())

        cruzamento = cruzar_planilha_com_mercado(
            kits_ml,
            produtos=produtos,
            kits_cadastrados=kits_p,
            top_kits=MONTAR_KITS_IMPALA_TOP_KITS,
        )
        ofertas_m = montar_ofertas_manicure(anuncios=kits_ml)
        cruzamento["ofertas_manicure"] = ofertas_m
        msg = montar_mensagem_telegram(cruzamento, consolidado)

        payload = {
            "ok": bool(cruzamento.get("ok")),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "planilha": str(planilha),
            "produtos_planilha": len(produtos),
            "kits_planilha": len(kits_p),
            "consolidado_ml": {
                "total_kits_unicos": consolidado.get("total_kits_unicos"),
                "total_vendas": consolidado.get("total_vendas"),
                "preco_medio": consolidado.get("preco_medio"),
            },
            "cruzamento": cruzamento,
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        gauge("montar_kits_impala.cores_demanda", float(cruzamento.get("cores_com_demanda") or 0))
        gauge("montar_kits_impala.kits_ml", float(cruzamento.get("total_kits_ml") or 0))

        enviado = False
        if (
            enviar_alerta
            and MONTAR_KITS_IMPALA_ALERTA
            and pode_alertar
            and cruzamento.get("ok")
            and msg
        ):
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("montar_kits_impala", horas_por_bucket=12),
                    cooldown_segundos=MONTAR_KITS_IMPALA_COOLDOWN_SEG,
                    agente_id="montar_kits_impala",
                )
            )

        incrementar("montar_kits_impala.ok" if cruzamento.get("ok") else "montar_kits_impala.erro")
        return {
            "ok": bool(cruzamento.get("ok")),
            "alerta_enviado": enviado,
            "cores_com_demanda": cruzamento.get("cores_com_demanda"),
            "kits_sugeridos": len(cruzamento.get("kits_sugeridos") or []),
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("agente_montar_kits_impala erro: %s", exc)
        incrementar("montar_kits_impala.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Montar kits Impala — planilha × ML")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta)
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "alerta_enviado": out.get("alerta_enviado"),
            "cores_com_demanda": out.get("cores_com_demanda"),
            "kits_sugeridos": out.get("kits_sugeridos"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
