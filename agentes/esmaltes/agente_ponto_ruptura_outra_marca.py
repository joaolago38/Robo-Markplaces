"""
agentes/esmaltes/agente_ponto_ruptura_outra_marca.py
Datadog + Telegram: ponto de ruptura para outra marca de esmalte no
CNPJ Impala (52.668.583/0001-27), com Mercado Livre como referente.

Uso:
  python -m agentes.esmaltes.agente_ponto_ruptura_outra_marca
  python -m agentes.esmaltes.agente_ponto_ruptura_outra_marca --sem-alerta
  python -m agentes.esmaltes.agente_ponto_ruptura_outra_marca --forcar
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
from integracoes.esmaltes.briefing_ruptura_impala import anexar_briefing, formatar_secao_briefing
from integracoes.esmaltes.ponto_ruptura_outra_marca import avaliar_ruptura_outra_marca

logger = logging.getLogger("agente_ponto_ruptura_outra_marca")

SNAPSHOT_PATH = ROOT / "logs" / "ponto_ruptura_outra_marca_ultima.json"
HEARTBEAT_PATH = SNAPSHOT_PATH
CNPJ_TAG = "cnpj:52668583000127"


def _ok_txt(ok: bool) -> str:
    return "ok" if ok else "falta"


def montar_mensagem(resultado: dict[str, Any], *, modo: str) -> str:
    from core.telegram_explicacao import cabecalho_agente

    ver = str(resultado.get("veredito") or "ainda_nao")
    top = str(resultado.get("top_marca") or "")
    titulos = {
        "liberado": "Outra marca de esmalte — LIBERADO",
        "aproximando": "Outra marca de esmalte — aproximando",
        "ainda_nao": "Outra marca de esmalte — ainda não",
        "radar": "Outra marca de esmalte — radar ML cego",
    }
    linhas = [
        cabecalho_agente(
            "ponto_ruptura_outra_marca",
            f"*{titulos.get(modo, titulos['ainda_nao'])}*",
        ),
        "",
        f"CNPJ *{resultado.get('cnpj_formatado')}* · referente *ML*",
        f"Veredito: *{ver}* · progresso *{resultado.get('progresso_pct')}%* "
        f"({resultado.get('checks_ok')}/{resultado.get('checks_total')} checks)",
        f"Top candidata: *{top or 'nenhuma'}* (score `{resultado.get('top_score')}`)",
        "",
        "*Checklist (mesmo CNPJ Impala)*",
    ]
    for c in resultado.get("checks") or []:
        linhas.append(
            f"• {_ok_txt(c.get('ok'))} — {c.get('rotulo')}: `{c.get('atual')}` "
            f"(mín `{c.get('minimo')}`)"
        )
    linhas.extend(["", "*CNPJ nos marketplaces*"])
    canais = resultado.get("canais") or {}
    for c in canais.get("itens") or []:
        linhas.append(f"• {_ok_txt(c.get('ok'))} — {c.get('rotulo')}: `{c.get('atual')}`")
    linhas.extend(["", "*Ranking ML (outras marcas)*"])
    for m in (resultado.get("candidatas") or [])[:8]:
        if not m.get("score") and not m.get("elegivel"):
            continue
        linhas.append(
            f"• {m.get('marca')}: score `{m.get('score')}` · "
            f"anúncios `{m.get('anuncios')}` · vendidos `{m.get('vendidos')}`"
        )
    if resultado.get("radar_cego"):
        linhas.append("_Radar ML cego (busca 403 / amostra insuficiente) — ranking não é decisão._")
    if modo == "liberado":
        linhas.extend(
            [
                "",
                f"*Ação:* entrar com *{top or 'a top1'}* no mesmo CNPJ, começando no ML. "
                "Shopee/Magalu/Amazon usam o mesmo CNPJ quando o canal ligar. "
                "Não publique ainda no 2º CNPJ (Masterprint).",
            ]
        )
    elif modo == "aproximando":
        linhas.extend(
            [
                "",
                "*Ação:* a ruptura Impala está perto. Feche MLB/estoque/anúncio "
                "ativo com os kits de margem segura abaixo, antes de comprar outra marca.",
            ]
        )
    linhas.extend(formatar_secao_briefing(resultado.get("briefing")))
    return "\n".join(linhas)


def _emitir_metricas(resultado: dict[str, Any]) -> None:
    tags = [CNPJ_TAG, f"veredito:{resultado.get('veredito') or 'ainda_nao'}"]
    incrementar("marca_esmalte.ruptura.rodadas", tags=tags)
    gauge("marca_esmalte.ruptura.liberado", 1.0 if resultado.get("liberado") else 0.0, tags=tags)
    gauge(
        "marca_esmalte.ruptura.aproximando",
        1.0 if resultado.get("aproximando") else 0.0,
        tags=tags,
    )
    gauge("marca_esmalte.ruptura.progresso_pct", float(resultado.get("progresso_pct") or 0), tags=tags)
    gauge("marca_esmalte.ruptura.checks_ok", float(resultado.get("checks_ok") or 0), tags=tags)
    gauge("marca_esmalte.ruptura.checks_total", float(resultado.get("checks_total") or 0), tags=tags)
    gauge("marca_esmalte.ruptura.radar_cego", 1.0 if resultado.get("radar_cego") else 0.0, tags=tags)
    gauge("marca_esmalte.ruptura.anuncios_foco", float(resultado.get("anuncios_foco") or 0), tags=tags)
    gauge("marca_esmalte.ruptura.top_score", float(resultado.get("top_score") or 0), tags=tags)
    for m in resultado.get("candidatas") or []:
        slug = str(m.get("slug") or "indefinida")
        mt = [CNPJ_TAG, f"marca:{slug}"]
        gauge("marca_esmalte.candidata.score", float(m.get("score") or 0), tags=mt)
        gauge("marca_esmalte.candidata.anuncios", float(m.get("anuncios") or 0), tags=mt)
        gauge("marca_esmalte.candidata.vendidos", float(m.get("vendidos") or 0), tags=mt)
    canais = resultado.get("canais") or {}
    for c in canais.get("itens") or []:
        canal = str(c.get("id") or "").replace("cnpj_", "") or "desconhecido"
        gauge(
            "marca_esmalte.cnpj_canal",
            1.0 if c.get("ok") else 0.0,
            tags=[CNPJ_TAG, f"marketplace:{canal}"],
        )


def executar(*, enviar_alerta: bool = True, forcar: bool = False) -> dict[str, Any]:
    """Avalia ruptura de outra marca. Nunca lança."""
    try:
        if not PONTO_RUPTURA_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        resultado = avaliar_ruptura_outra_marca()
        resultado = anexar_briefing(resultado)
        resultado["timestamp"] = datetime.now(timezone.utc).isoformat()
        resultado["gerado_em"] = agora_brasil().isoformat()
        _emitir_metricas(resultado)

        ver = str(resultado.get("veredito") or "ainda_nao")
        modo = "ainda_nao"
        cooldown = PONTO_RUPTURA_COOLDOWN_CNAE_SEG
        chave = "marca_esmalte:ainda_nao"
        deve = False
        if ver == "liberado":
            modo = "liberado"
            cooldown = PONTO_RUPTURA_COOLDOWN_LIBERADO_SEG
            chave = "marca_esmalte:liberado"
            deve = True
        elif resultado.get("radar_cego") and ver == "aproximando":
            modo = "radar"
            chave = "marca_esmalte:radar"
            cooldown = PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG
            deve = True
        elif ver == "aproximando":
            modo = "aproximando"
            chave = "marca_esmalte:aproximando"
            cooldown = PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG
            deve = True
        if forcar:
            deve = True
            cooldown = 0

        msg = montar_mensagem(resultado, modo=modo)
        resultado["mensagem"] = msg
        resultado["modo_alerta"] = modo

        enviado = False
        if enviar_alerta and PONTO_RUPTURA_ALERTA and deve:
            if not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado — ruptura outra marca sem envio")
            else:
                enviado = bool(
                    alertar_gestor(
                        msg,
                        chave=chave if not forcar else "marca_esmalte:forcar",
                        cooldown_segundos=0 if forcar else cooldown,
                        agente_id="ponto_ruptura_outra_marca",
                        _ignorar_cooldown=forcar,
                    )
                )
                if enviado:
                    incrementar("marca_esmalte.ruptura.telegram_ok", tags=[f"modo:{modo}"])
                else:
                    incrementar("marca_esmalte.ruptura.telegram_skip", tags=[f"modo:{modo}"])

        resultado["alerta_enviado"] = enviado
        escrever_json_atomico(SNAPSHOT_PATH, resultado)
        return resultado
    except Exception as exc:
        logger.exception("ponto ruptura outra marca: %s", exc)
        incrementar("marca_esmalte.ruptura.falha")
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
    p = argparse.ArgumentParser(description="Ponto de ruptura Impala → outra marca de esmalte")
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
