"""
agentes/social/agente_promocoes_manicures.py
Divulga promoções de esmaltes Impala no Mercado Livre para manicures
via grupo WhatsApp e canal Telegram, com mensagens pré-definidas no catálogo.

Catálogo: catalogo/promocoes_manicures_ml.json

Uso:
  python -m agentes.social.agente_promocoes_manicures
  python -m agentes.social.agente_promocoes_manicures --sem-envio
  python -m agentes.social.agente_promocoes_manicures --campanha kit-3-mimo-manicure
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import PROMOCOES_MANICURES_COOLDOWN_SEG, PROMOCOES_MANICURES_INTERVALO_SEG, ROOT
from core.datadog_metrics import incrementar
from core.notificador import alertar_gestor, enviar_telegram_manicures, gestor_telegram_configurado
from core.prontidao import pode_divulgar_promocoes_manicures
from core.whatsapp import enviar_grupo_manicures, whatsapp_grupo_manicures_configurado
from integracoes.social.promocoes_manicures import (
    carregar_campanhas,
    escolher_campanha,
    montar_mensagem_campanha,
)

logger = logging.getLogger("agente_promocoes_manicures")

HISTORY_PATH = ROOT / "logs" / "promocoes_manicures_historico.json"
SNAPSHOT_PATH = ROOT / "logs" / "promocoes_manicures_ultima.json"


def _carregar_historico() -> dict[str, Any]:
    data = ler_json(HISTORY_PATH, default={})
    return data if isinstance(data, dict) else {}


def _intervalo_pendente(historico: dict[str, Any]) -> tuple[bool, str]:
    """True se ainda não passou o intervalo mínimo desde o último envio."""
    ultimo = historico.get("ultimo_envio_em")
    if not ultimo:
        return False, ""
    try:
        dt = datetime.fromisoformat(str(ultimo).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        restante = PROMOCOES_MANICURES_INTERVALO_SEG - (datetime.now(timezone.utc) - dt).total_seconds()
        if restante > 0:
            horas = int(restante // 3600)
            mins = int((restante % 3600) // 60)
            return True, f"intervalo_minimo ({horas}h{mins:02d}m restantes)"
    except Exception:
        return False, ""
    return False, ""


def _selecionar_campanha(
    campanhas: list[dict[str, Any]],
    *,
    campanha_id: str | None,
    ultimo_id: str | None,
) -> dict[str, Any] | None:
    if campanha_id:
        for c in campanhas:
            if str(c.get("id") or "") == campanha_id:
                return c
        return None
    return escolher_campanha(campanhas, ultimo_id=ultimo_id)


def _montar_com_fallback(
    campanhas: list[dict[str, Any]],
    *,
    campanha_id: str | None,
    ultimo_id: str | None,
) -> dict[str, Any]:
    escolhida = _selecionar_campanha(campanhas, campanha_id=campanha_id, ultimo_id=ultimo_id)
    if not escolhida:
        return {"ok": False, "motivo": "nenhuma campanha disponível"}

    tentativas: list[dict[str, Any]] = []
    fila = [escolhida]
    if not campanha_id:
        ids_vistos = {str(escolhida.get("id") or "")}
        for c in sorted(campanhas, key=lambda x: int(x.get("prioridade") or 99)):
            cid = str(c.get("id") or "")
            if cid and cid not in ids_vistos:
                fila.append(c)
                ids_vistos.add(cid)

    for campanha in fila:
        out = montar_mensagem_campanha(campanha)
        tentativas.append({"id": campanha.get("id"), "ok": out.get("ok"), "motivo": out.get("motivo")})
        if not out.get("ok"):
            continue
        from integracoes.ml.contrato_impulso_ml import campanha_pode_enviar, carregar_contrato

        contrato = carregar_contrato()
        pode, motivo_c = campanha_pode_enviar(
            str(out.get("sku") or ""),
            link_valido=bool(out.get("link_valido")),
            contrato=contrato,
        )
        if not pode:
            tentativas.append(
                {"id": campanha.get("id"), "ok": False, "motivo": f"contrato:{motivo_c}"}
            )
            logger.info("Campanha %s bloqueada pelo contrato: %s", campanha.get("id"), motivo_c)
            continue
        out["contrato_motivo"] = motivo_c
        return out

    falhas = [t for t in tentativas if not t.get("ok")]
    so_sem_mlb = bool(falhas) and all(
        "link_mlb_invalido" in str(t.get("motivo") or "") for t in falhas
    )
    return {
        "ok": False,
        "motivo": "sem_mlb_publicado" if so_sem_mlb else "nenhuma campanha montou mensagem válida",
        "pulado_esperado": so_sem_mlb,
        "tentativas": tentativas,
    }


def executar(
    *,
    enviar: bool = True,
    campanha_id: str | None = None,
    forcar: bool = False,
) -> dict[str, Any]:
    pode, motivo_prontidao = pode_divulgar_promocoes_manicures()
    if not pode:
        logger.warning("Promoções manicures bloqueadas: %s", motivo_prontidao)
        return {"ok": False, "motivo": motivo_prontidao, "enviado": False}

    campanhas = carregar_campanhas()
    if not campanhas:
        logger.warning("Nenhuma campanha ativa em promocoes_manicures_ml.json")
        return {"ok": False, "motivo": "catalogo_vazio", "enviado": False}

    historico = _carregar_historico()
    if enviar and not forcar and not campanha_id:
        aguardando, motivo_intervalo = _intervalo_pendente(historico)
        if aguardando:
            logger.info("Envio adiado: %s", motivo_intervalo)
            return {"ok": True, "enviado": False, "motivo": motivo_intervalo, "adiado": True}

    ultimo_id = str(historico.get("ultima_campanha_id") or "") or None

    montado = _montar_com_fallback(campanhas, campanha_id=campanha_id, ultimo_id=ultimo_id)
    if not montado.get("ok"):
        motivo = str(montado.get("motivo") or "falha_montar")
        # Sem MLB real no catálogo = estado esperado até publicar anúncios (não falha vermelha no Actions).
        if montado.get("pulado_esperado") or motivo == "sem_mlb_publicado":
            logger.warning(
                "Promoções manicures pausadas: kits sem MLB (preencha item_id em catalogo/produtos.json)"
            )
            if gestor_telegram_configurado():
                try:
                    alertar_gestor(
                        "⏸️ *Promoções manicures pausadas*\n\n"
                        "Nenhum kit com *MLB real* no catálogo (`MLB_PREENCHER`).\n"
                        "Publique os anúncios Impala e atualize `canais.mercadolivre.item_id` "
                        "para retomar WhatsApp/Telegram.",
                        chave="promocoes_manicures:sem_mlb",
                        cooldown_segundos=86400,
                        agente_id="promocoes_manicures",
                    )
                except Exception as exc:
                    logger.debug("alerta gestor sem_mlb: %s", exc)
            incrementar("promocoes_manicures.pulado_sem_mlb")
            return {
                "ok": True,
                "pulado": True,
                "motivo": "sem_mlb_publicado",
                "enviado": False,
                "detalhe": montado,
            }
        logger.error("Falha ao montar promoção: %s", motivo)
        return {"ok": False, "motivo": motivo, "enviado": False, "detalhe": montado}

    cid = str(montado.get("campanha_id") or "")
    chave_cooldown = f"promocoes_manicures:{cid}"

    resultado = {
        "ok": True,
        "campanha_id": cid,
        "campanha_nome": montado.get("campanha_nome"),
        "sku": montado.get("sku"),
        "link_ml": montado.get("link_ml"),
        "whatsapp": False,
        "telegram": False,
        "enviado": False,
    }

    if not enviar:
        resultado["modo"] = "dry_run"
        escrever_json_atomico(SNAPSHOT_PATH, montado)
        return resultado

    if whatsapp_grupo_manicures_configurado():
        resultado["whatsapp"] = bool(enviar_grupo_manicures(str(montado.get("texto_whatsapp") or "")))

    resultado["telegram"] = bool(
        enviar_telegram_manicures(
            str(montado.get("texto_telegram") or montado.get("texto") or ""),
            chave=chave_cooldown,
            cooldown_segundos=PROMOCOES_MANICURES_COOLDOWN_SEG,
        )
    )

    resultado["enviado"] = resultado["whatsapp"] or resultado["telegram"]
    if not resultado["enviado"]:
        logger.warning(
            "Nenhum canal entregou a promoção (WA=%s TG=%s)",
            resultado["whatsapp"],
            resultado["telegram"],
        )
        incrementar("promocoes_manicures.falha_envio")
        return {**resultado, "ok": False, "motivo": "nenhum_canal_entregou"}

    agora = datetime.now(timezone.utc).isoformat()
    historico.update(
        {
            "ultima_campanha_id": cid,
            "ultimo_envio_em": agora,
            "ultimo_sku": montado.get("sku"),
            "whatsapp": resultado["whatsapp"],
            "telegram": resultado["telegram"],
        }
    )
    escrever_json_atomico(HISTORY_PATH, historico)
    escrever_json_atomico(SNAPSHOT_PATH, montado)
    incrementar("promocoes_manicures.enviado")
    logger.info(
        "Promoção enviada: %s (%s) WA=%s TG=%s",
        cid,
        montado.get("sku"),
        resultado["whatsapp"],
        resultado["telegram"],
    )
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Divulga promoções ML para manicures (WhatsApp + Telegram)")
    parser.add_argument("--sem-envio", action="store_true", help="Monta mensagem sem enviar")
    parser.add_argument("--campanha", default="", help="ID fixo da campanha (opcional)")
    parser.add_argument("--forcar", action="store_true", help="Ignora intervalo mínimo entre envios")
    args = parser.parse_args(argv)

    logger.info("=== Agente promoções manicures (Mercado Livre) ===")
    out = executar(
        enviar=not args.sem_envio,
        campanha_id=(args.campanha or None) or None,
        forcar=args.forcar,
    )
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("motivo"))
        return 1
    if out.get("pulado") or out.get("adiado"):
        logger.info("Adiado/pausado: %s", out.get("motivo"))
        return 0
    logger.info(
        "Concluído: campanha=%s enviado=%s (WA=%s TG=%s)",
        out.get("campanha_id"),
        out.get("enviado"),
        out.get("whatsapp"),
        out.get("telegram"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
