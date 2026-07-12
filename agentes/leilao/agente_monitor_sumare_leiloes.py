"""
agentes/leilao/agente_monitor_sumare_leiloes.py
Monitora Sumaré Leilões (PREFEITURA/DETRAN): veículos com documento, alerta de lances.

Site oficial: https://www.sumareleiloes.com.br

Uso:
  python -m agentes.leilao.agente_monitor_sumare_leiloes
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    ROOT,
    SUMARE_LEILOES_ALERTA_COOLDOWN_SEG,
    SUMARE_LEILOES_CATALOGO,
    LEILAO_IA_AVALIAR_PARAMETROS,
    SUMARE_LEILOES_LANCE_MIN_BRL,
    SUMARE_LEILOES_PAUSA_ENTRE_LEILOES_SEG,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_itens_novos, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.leilao.avaliacao_ia_parametros import avaliar_parametros_sumare, formatar_secao_ia
from integracoes.leilao.sumare_leiloes import varredura_sumare

logger = logging.getLogger("agente_monitor_sumare_leiloes")

HISTORY_PATH = ROOT / "logs" / "sumare_leiloes_history.json"
SNAPSHOT_PATH = ROOT / "logs" / "sumare_leiloes_ultima.json"


def _carregar_config() -> dict[str, Any]:
    caminho = ROOT / SUMARE_LEILOES_CATALOGO
    cfg = ler_json(caminho, default={})
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg.get("lance_minimo_brl"):
        cfg["lance_minimo_brl"] = SUMARE_LEILOES_LANCE_MIN_BRL
    return cfg


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def _montar_linha_lote(item: dict[str, Any]) -> list[str]:
    tipo = str(item.get("tipo_comitente") or "leilão").upper()
    comitente = str(item.get("comitente") or "")[:50]
    lance = _fmt_brl(item.get("lance_brl"))
    local = item.get("cidade") and item.get("uf")
    loc_txt = f"{item.get('cidade')}/{item.get('uf')}" if local else (item.get("local_data") or "")
    doc = "✅ Com documento" if item.get("tem_documento") else "⚠️ Sem selo DOCUMENTO no card"
    linhas = [
        f"• *LOTE {item.get('numero_lote', '?')}* — {item.get('titulo', '?')}",
        f"  {tipo}: {comitente}",
        f"  💰 Lance: *{lance}*",
    ]
    if loc_txt:
        linhas.append(f"  📍 {loc_txt}")
    if item.get("data_fechamento"):
        linhas.append(f"  📅 Fecha {item['data_fechamento']}")
    linhas.append(f"  {doc}")
    linhas.append(f"  🔗 {item.get('url', '')}")
    return linhas


def _montar_alerta(
    novos: list[dict[str, Any]],
    mudancas: list[dict[str, Any]],
    resumo: dict[str, Any],
    ia: dict[str, Any] | None = None,
) -> str:
    exigir_doc = resumo.get("exigir_documento")
    doc_txt = "só com documento" if exigir_doc else "com ou sem documento"
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("sumare_leiloes", "🏛️ *Sumaré Leilões — PREFEITURA/DETRAN*"),
        "",
        f"_{resumo.get('leiloes_encontrados', 0)} leilão(ões) | "
        f"{resumo.get('lotes_veiculo_documento', 0)} veículo(s) "
        f"({doc_txt}, lance ≥ {_fmt_brl(resumo.get('lance_minimo_brl'))})_",
    ]
    if resumo.get("lotes_sem_documento") is not None:
        linhas.append(
            f"_Com documento: {resumo.get('lotes_com_documento', 0)} | "
            f"Sem selo: {resumo.get('lotes_sem_documento', 0)} | "
            f"Abaixo do mín.: {resumo.get('lotes_abaixo_lance_min', 0)}_"
        )
    linhas.extend(
        [
            "",
            "⚠️ _Site oficial: sumareleiloes.com.br — ignore domínios falsos_",
            "",
        ]
    )

    if novos:
        linhas.append(f"🆕 *Novos lotes ({len(novos)})*")
        for item in sorted(novos, key=lambda x: float(x.get("lance_brl") or 0), reverse=True)[:12]:
            linhas.extend(_montar_linha_lote(item))
            linhas.append("")
    if mudancas:
        linhas.append(f"📈 *Lance alterado ({len(mudancas)})*")
        for item in mudancas[:8]:
            ant = _fmt_brl(item.get("lance_anterior_brl"))
            atu = _fmt_brl(item.get("lance_brl"))
            linhas.append(f"• LOTE {item.get('numero_lote')} — {item.get('titulo', '')[:45]}")
            linhas.append(f"  {ant} → *{atu}*")
            linhas.append(f"  🔗 {item.get('url', '')}")
        linhas.append("")

    if not novos and not mudancas:
        top = resumo.get("lotes_destaque") or []
        if top:
            linhas.append("*Destaques (lances atuais)*")
            for item in top[:8]:
                linhas.extend(_montar_linha_lote(item))
                linhas.append("")
        else:
            linhas.append(
                "_Nenhum veículo acima do lance mínimo nesta rodada "
                "(filtre documento/lance no catálogo sumare_leiloes_monitorados.json)._"
            )

    secao_ia = formatar_secao_ia(ia)
    if secao_ia:
        linhas.append(secao_ia)

    return "\n".join(linhas).strip()


def executar(enviar_alerta: bool = True) -> dict[str, Any]:
    try:
        if enviar_alerta and not gestor_telegram_configurado():
            logger.warning("Telegram gestor não configurado — alertas Sumaré não serão entregues")

        config = _carregar_config()
        if not config.get("ativo", True):
            return {"ok": True, "motivo": "monitor desativado no catálogo", "lotes": []}

        resultado = varredura_sumare(
            config,
            pausa_entre_leiloes_seg=SUMARE_LEILOES_PAUSA_ENTRE_LEILOES_SEG,
        )
        lotes = resultado.get("lotes") or []
        agora = datetime.now(timezone.utc).isoformat()

        historico = ler_json(HISTORY_PATH, default={})
        vistos: dict[str, Any] = dict(historico.get("lotes") or {})

        novos: list[dict[str, Any]] = []
        mudancas: list[dict[str, Any]] = []

        for lote in lotes:
            h = str(lote.get("hash") or "")
            if not h:
                continue
            lance = float(lote.get("lance_brl") or 0)
            anterior = vistos.get(h)
            if not anterior:
                registro = {**lote, "visto_em": agora}
                vistos[h] = registro
                novos.append(registro)
            else:
                lance_ant = float(anterior.get("lance_brl") or 0)
                if lance and lance_ant and abs(lance - lance_ant) >= 1.0:
                    atualizado = {**lote, "lance_anterior_brl": lance_ant, "visto_em": agora}
                    vistos[h] = atualizado
                    if config.get("alertar_mudanca_lance", True):
                        mudancas.append(atualizado)
                else:
                    vistos[h] = {**anterior, **lote, "ultima_varredura": agora}

        historico["lotes"] = vistos
        historico["ultima_varredura"] = agora
        historico["total_lotes"] = len(lotes)
        escrever_json_atomico(HISTORY_PATH, historico)

        lance_min = float(config.get("lance_minimo_brl") or SUMARE_LEILOES_LANCE_MIN_BRL)

        ia_parametros = None
        if LEILAO_IA_AVALIAR_PARAMETROS:
            ia_parametros = avaliar_parametros_sumare(
                config=config,
                lotes=lotes,
                novos=novos,
                mudancas=mudancas,
                leiloes_encontrados=int(resultado.get("leiloes_encontrados") or 0),
            )

        snapshot = {
            "timestamp": agora,
            "leiloes_encontrados": resultado.get("leiloes_encontrados"),
            "lotes_veiculo_documento": len(lotes),
            "lotes_com_documento": resultado.get("lotes_com_documento"),
            "lotes_sem_documento": resultado.get("lotes_sem_documento"),
            "lotes_abaixo_lance_min": resultado.get("lotes_abaixo_lance_min"),
            "exigir_documento": resultado.get("exigir_documento", config.get("exigir_documento")),
            "lance_minimo_brl": lance_min,
            "novos": len(novos),
            "mudancas_lance": len(mudancas),
            "lotes": lotes[:80],
            "avaliacao_ia_parametros": ia_parametros,
        }
        escrever_json_atomico(SNAPSHOT_PATH, snapshot)

        gauge("sumare.leiloes", float(resultado.get("leiloes_encontrados") or 0))
        gauge("sumare.leiloes_coleta_ok", float(resultado.get("leiloes_coletados_ok") or 0))
        incrementar("sumare.leilao_falha", int(resultado.get("leiloes_coleta_falha") or 0))
        gauge("sumare.lotes_documento", float(len(lotes)))
        incrementar("sumare.novos", len(novos))
        incrementar("sumare.mudancas_lance", len(mudancas))

        alerta_enviado = False
        itens_alerta = novos + mudancas
        if enviar_alerta and itens_alerta:
            resumo = {
                **resultado,
                "lance_minimo_brl": lance_min,
                "lotes_destaque": sorted(lotes, key=lambda x: float(x.get("lance_brl") or 0), reverse=True)[:8],
            }
            msg = _montar_alerta(novos, mudancas, resumo, ia_parametros)
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_itens_novos("sumare:leiloes:lances", itens_alerta),
                    cooldown_segundos=SUMARE_LEILOES_ALERTA_COOLDOWN_SEG,
                    agente_id="sumare_leiloes",
                )
            )
        elif enviar_alerta and lotes:
            msg = _montar_alerta(
                [],
                [],
                {
                    **resultado,
                    "lance_minimo_brl": lance_min,
                    "lotes_destaque": sorted(lotes, key=lambda x: float(x.get("lance_brl") or 0), reverse=True)[:8],
                },
                ia_parametros,
            )
            alerta_enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("sumare:leiloes", horas_por_bucket=4),
                    cooldown_segundos=SUMARE_LEILOES_ALERTA_COOLDOWN_SEG,
                    agente_id="sumare_leiloes",
                )
            )

        logger.info(
            "Sumaré: %s leilões (%s OK, %s falha), %s lotes doc, %s novos, %s mudanças, alerta=%s",
            resultado.get("leiloes_encontrados"),
            resultado.get("leiloes_coletados_ok"),
            resultado.get("leiloes_coleta_falha"),
            len(lotes),
            len(novos),
            len(mudancas),
            alerta_enviado,
        )
        return {
            "ok": True,
            "leiloes_encontrados": resultado.get("leiloes_encontrados"),
            "leiloes_coletados_ok": resultado.get("leiloes_coletados_ok"),
            "leiloes_coleta_falha": resultado.get("leiloes_coleta_falha"),
            "lotes_veiculo_documento": len(lotes),
            "novos": novos,
            "mudancas_lance": mudancas,
            "alerta_enviado": alerta_enviado,
            "avaliacao_ia_parametros": ia_parametros,
            "lotes": lotes,
        }
    except Exception as exc:
        logger.error("Agente Sumaré leilões erro: %s", exc)
        incrementar("sumare.erro")
        return {"ok": False, "erro": str(exc), "lotes": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Sumaré Leilões PREFEITURA/DETRAN")
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args(argv)

    logger.info("=== Monitor Sumaré Leilões ===")
    out = executar(enviar_alerta=not args.sem_alerta)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("erro"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
