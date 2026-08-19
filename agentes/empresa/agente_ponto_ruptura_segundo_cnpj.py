"""
agentes/empresa/agente_ponto_ruptura_segundo_cnpj.py
Informa no Telegram + Datadog quando o Impala libera o segundo CNPJ
e quando falta preparar CNAE/seller Masterprint.

Uso:
  python -m agentes.empresa.agente_ponto_ruptura_segundo_cnpj
  python -m agentes.empresa.agente_ponto_ruptura_segundo_cnpj --sem-alerta
  python -m agentes.empresa.agente_ponto_ruptura_segundo_cnpj --forcar
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    PONTO_RUPTURA_ALERTA,
    PONTO_RUPTURA_ATIVO,
    PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG,
    PONTO_RUPTURA_COOLDOWN_CNAE_SEG,
    PONTO_RUPTURA_COOLDOWN_LIBERADO_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from core.notificador import alertar_gestor, gestor_telegram_configurado
from integracoes.empresa.ponto_ruptura_segundo_cnpj import avaliar_ponto_ruptura
from integracoes.esmaltes.briefing_ruptura_impala import anexar_briefing, formatar_secao_briefing

logger = logging.getLogger("agente_ponto_ruptura_segundo_cnpj")

SNAPSHOT_PATH = ROOT / "logs" / "ponto_ruptura_segundo_cnpj_ultima.json"
HEARTBEAT_PATH = SNAPSHOT_PATH


def _ok_txt(ok: bool) -> str:
    return "ok" if ok else "falta"


def montar_mensagem(resultado: dict[str, Any], *, modo: str) -> str:
    from core.telegram_explicacao import cabecalho_agente

    ver = str(resultado.get("veredito") or "ainda_nao")
    cnae = resultado.get("cnae_preparacao") or {}
    titulos = {
        "liberado": "Ponto de ruptura — segundo CNPJ LIBERADO",
        "aproximando": "Ponto de ruptura — Impala aproximando",
        "cnae": "CNAE / seller — prepare o segundo CNPJ",
        "ainda_nao": "Ponto de ruptura — ainda não",
    }
    linhas = [
        cabecalho_agente(
            "ponto_ruptura_segundo_cnpj",
            f"*{titulos.get(modo, titulos['ainda_nao'])}*",
        ),
        "",
        f"Veredito Impala: *{ver}* · progresso *{resultado.get('progresso_pct')}%* "
        f"({resultado.get('checks_ok')}/{resultado.get('checks_total')} checks)",
        f"_CNAE Masterprint: {'pronto' if cnae.get('pronto') else str(cnae.get('gaps_n') or 0) + ' gap(s)'}_",
        "",
        "*Checklist Impala*",
    ]
    for c in resultado.get("checks") or []:
        linhas.append(
            f"• {_ok_txt(c.get('ok'))} — {c.get('rotulo')}: `{c.get('atual')}` "
            f"(mín `{c.get('minimo')}`)"
        )
    linhas.extend(["", "*Preparar CNAE / KYC (23.811.261/0001-97)*"])
    for c in cnae.get("itens") or []:
        linhas.append(f"• {_ok_txt(c.get('ok'))} — {c.get('rotulo')}")
    if modo == "liberado":
        linhas.extend(
            [
                "",
                "*Ação:* Bling + token ML deste CNPJ, 1 filamento (PLA/PETG preto) "
                "com estoque, chat separado. Ads Masterprint só depois. "
                "Não ligue CNPJ_DONO_PRODUTOS_USAR_ALVO ainda.",
            ]
        )
    elif modo == "cnae":
        linhas.extend(
            [
                "",
                "*Ação agora:* confirmar CNAEs na Junta/Receita, KYC do seller "
                "Masterprint no ML (seller_id no catálogo/env). "
                "Isso é preparação — não publicar 192 SKUs.",
            ]
        )
    elif modo == "aproximando":
        linhas.extend(
            [
                "",
                "*Ação:* a ruptura Impala está perto. Use a prévia ML e os kits "
                "com margem segura abaixo — não escale Ads nem outra marca ainda.",
            ]
        )
        if not cnae.get("pronto"):
            linhas.append(
                "_CNAE/KYC Masterprint ainda tem gap — prepare o seller agora, "
                "sem esperar o Telegram semanal de CNAE._"
            )
    linhas.extend(formatar_secao_briefing(resultado.get("briefing")))
    return "\n".join(linhas)


def _emitir_metricas(resultado: dict[str, Any]) -> None:
    cnae = resultado.get("cnae_preparacao") or {}
    sinais = resultado.get("sinais") or {}
    tags = [f"veredito:{resultado.get('veredito') or 'ainda_nao'}"]
    incrementar("ponto_ruptura.rodadas", tags=tags)
    gauge("ponto_ruptura.liberado", 1.0 if resultado.get("liberado") else 0.0)
    gauge("ponto_ruptura.aproximando", 1.0 if resultado.get("aproximando") else 0.0)
    gauge("ponto_ruptura.progresso_pct", float(resultado.get("progresso_pct") or 0))
    gauge("ponto_ruptura.checks_ok", float(resultado.get("checks_ok") or 0))
    gauge("ponto_ruptura.checks_total", float(resultado.get("checks_total") or 0))
    gauge("ponto_ruptura.avaliacoes", float(sinais.get("avaliacoes") or 0))
    gauge("ponto_ruptura.nota", float(sinais.get("nota") or 0))
    gauge("ponto_ruptura.ads_fonte_ok", 1.0 if sinais.get("ads_fonte_ok") else 0.0)
    try:
        foco_n = int(float(sinais.get("anuncios_ativos_foco") or 0))
    except (TypeError, ValueError):
        foco_n = 0
    gauge("ponto_ruptura.foco_vazio", 1.0 if foco_n <= 0 else 0.0)
    gauge("cnae_preparacao.pronto", 1.0 if cnae.get("pronto") else 0.0)
    # Monitor CNAE olha só códigos fiscais; KYC vai em cnae_preparacao.kyc_gaps.
    gauge("cnae_preparacao.gaps", float(cnae.get("gaps_cnae_n") or 0))
    gauge("cnae_preparacao.kyc_gaps", float(cnae.get("gaps_kyc_n") or 0))
    gauge(
        "cnae_preparacao.seller_masterprint",
        1.0 if cnae.get("seller_masterprint") else 0.0,
    )


def executar(*, enviar_alerta: bool = True, forcar: bool = False) -> dict[str, Any]:
    """Avalia ruptura + CNAE. Nunca lança."""
    try:
        if not PONTO_RUPTURA_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        resultado = avaliar_ponto_ruptura()
        resultado = anexar_briefing(resultado)
        resultado["timestamp"] = datetime.now(timezone.utc).isoformat()
        resultado["gerado_em"] = agora_brasil().isoformat()
        _emitir_metricas(resultado)

        ver = str(resultado.get("veredito") or "ainda_nao")
        cnae = resultado.get("cnae_preparacao") or {}
        gaps_n = int(cnae.get("gaps_n") or 0)

        modo = "ainda_nao"
        cooldown = PONTO_RUPTURA_COOLDOWN_CNAE_SEG
        chave = "ponto_ruptura:status"
        deve = False
        if ver == "liberado":
            modo = "liberado"
            cooldown = PONTO_RUPTURA_COOLDOWN_LIBERADO_SEG
            chave = "ponto_ruptura:liberado"
            deve = True
        elif ver == "aproximando":
            modo = "aproximando"
            cooldown = PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG
            chave = "ponto_ruptura:aproximando"
            deve = True
        elif gaps_n > 0:
            modo = "cnae"
            cooldown = PONTO_RUPTURA_COOLDOWN_CNAE_SEG
            chave = "ponto_ruptura:cnae_prep"
            deve = True
        if forcar:
            deve = True
            cooldown = 0
            if modo == "ainda_nao" and gaps_n > 0:
                modo = "cnae"

        msg = montar_mensagem(resultado, modo=modo)
        resultado["mensagem"] = msg
        resultado["modo_alerta"] = modo

        enviado = False
        if enviar_alerta and PONTO_RUPTURA_ALERTA and deve:
            if not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado — ponto de ruptura sem envio")
            else:
                enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave if not forcar else "ponto_ruptura:forcar",
                        cooldown_segundos=0 if forcar else cooldown,
                        agente_id="ponto_ruptura_segundo_cnpj",
                        _ignorar_cooldown=forcar,
                    )
                )
                if enviado:
                    incrementar("ponto_ruptura.telegram_ok", tags=[f"modo:{modo}"])
                else:
                    incrementar("ponto_ruptura.telegram_skip", tags=[f"modo:{modo}"])

        resultado["alerta_enviado"] = enviado
        escrever_json_atomico(SNAPSHOT_PATH, resultado)
        return resultado
    except Exception as exc:
        logger.exception("ponto ruptura: %s", exc)
        incrementar("ponto_ruptura.falha")
        payload = {
            "ok": False,
            "erro": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alerta_enviado": False,
        }
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception:
            pass
        return payload


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Ponto de ruptura Impala → segundo CNPJ + CNAE")
    p.add_argument("--sem-alerta", action="store_true")
    p.add_argument("--forcar", action="store_true")
    args = p.parse_args()
    out = executar(enviar_alerta=not args.sem_alerta, forcar=args.forcar)
    texto = str(out.get("mensagem") or out)
    try:
        print(texto)
    except UnicodeEncodeError:
        print(texto.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    main()
