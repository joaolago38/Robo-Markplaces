"""
agentes/social/agente_necessidade_manicures.py
Lê necessidade das manicures, valida catálogo ML e oferece condições
nos canais WA/TG somente após SIM do gestor.

Uso:
  python -m agentes.social.agente_necessidade_manicures
  python -m agentes.social.agente_necessidade_manicures --sem-envio
  python -m agentes.social.agente_necessidade_manicures --sem-confirmacao
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import (
    NECESSIDADE_MANICURES_ALERTA,
    NECESSIDADE_MANICURES_ATIVO,
    NECESSIDADE_MANICURES_COOLDOWN_SEG,
    NECESSIDADE_MANICURES_ENVIAR_CANAIS,
    NECESSIDADE_MANICURES_PEDIR_CONFIRMACAO,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import (
    alertar_gestor,
    chave_resumo_periodo,
    enviar_telegram_manicures,
    manicures_telegram_configurado,
    perguntar_gestor_e_aguardar,
)
from core.whatsapp import enviar_grupo_manicures, whatsapp_grupo_manicures_configurado
from integracoes.social.necessidade_manicures import (
    casar_necessidades_com_ml,
    montar_mensagem_gestor,
)

logger = logging.getLogger("agente_necessidade_manicures")

SNAPSHOT_PATH = ROOT / "logs" / "necessidade_manicures_ultima.json"
HISTORY_PATH = ROOT / "logs" / "necessidade_manicures_historico.json"


def _cooldown_ativo(historico: dict[str, Any]) -> tuple[bool, str]:
    ultimo = historico.get("ultimo_envio_ativo_em")
    if not ultimo:
        return False, ""
    try:
        dt = datetime.fromisoformat(str(ultimo).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        restante = NECESSIDADE_MANICURES_COOLDOWN_SEG - (
            datetime.now(timezone.utc) - dt
        ).total_seconds()
        if restante > 0:
            return True, f"cooldown ({int(restante // 60)}min)"
    except Exception:
        return False, ""
    return False, ""


def _enviar_canais(escolhida: dict[str, Any]) -> dict[str, Any]:
    out = {"whatsapp": False, "telegram": False, "motivo": ""}
    wa = str(escolhida.get("copy_whatsapp") or "").strip()
    tg = str(escolhida.get("copy_telegram") or wa).strip()
    if not wa and not tg:
        out["motivo"] = "copy_vazia"
        return out
    if whatsapp_grupo_manicures_configurado() and wa:
        out["whatsapp"] = bool(enviar_grupo_manicures(wa))
    if manicures_telegram_configurado() and tg:
        out["telegram"] = bool(
            enviar_telegram_manicures(
                tg,
                chave=f"necessidade_manicures:tg:{escolhida.get('campanha_id')}",
                cooldown_segundos=NECESSIDADE_MANICURES_COOLDOWN_SEG,
            )
        )
    if not out["whatsapp"] and not out["telegram"]:
        out["motivo"] = "canais_indisponiveis_ou_falha"
    return out


def executar(
    *,
    enviar: bool = True,
    pedir_confirmacao: bool | None = None,
    enviar_alerta: bool = True,
) -> dict[str, Any]:
    """Pipeline necessidade → match ML → confirmação → canais. Nunca lança."""
    try:
        if not NECESSIDADE_MANICURES_ATIVO:
            return {"ok": False, "motivo": "agente_desligado"}

        confirmar = (
            NECESSIDADE_MANICURES_PEDIR_CONFIRMACAO
            if pedir_confirmacao is None
            else bool(pedir_confirmacao)
        )

        plano = casar_necessidades_com_ml()
        msg = montar_mensagem_gestor(plano)
        escolhida = plano.get("escolhida")

        historico = ler_json(HISTORY_PATH, default={})
        if not isinstance(historico, dict):
            historico = {}

        envios: dict[str, Any] = {"whatsapp": False, "telegram": False, "adiado": True}
        confirmado: bool | None = None
        motivo_envio = ""

        if enviar_alerta and NECESSIDADE_MANICURES_ALERTA and msg:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo("necessidade_manicures", horas_por_bucket=6),
                cooldown_segundos=min(3600, NECESSIDADE_MANICURES_COOLDOWN_SEG),
                agente_id="necessidade_manicures",
            )

        if not enviar:
            motivo_envio = "dry_run"
        elif not NECESSIDADE_MANICURES_ENVIAR_CANAIS:
            motivo_envio = "envio_canais_desligado"
        elif not escolhida or not escolhida.get("pode_enviar"):
            motivo_envio = "sem_match_enviavel"
        else:
            aguarda, motivo_cd = _cooldown_ativo(historico)
            if aguarda:
                motivo_envio = motivo_cd
            elif confirmar:
                pergunta = (
                    f"Confirma enviar oferta *{escolhida.get('campanha_nome')}* "
                    f"(ângulo {(escolhida.get('condicoes') or {}).get('angulo')}) "
                    f"no WhatsApp/Telegram manicures?\n\n"
                    f"{(escolhida.get('condicoes') or {}).get('cta')}"
                )
                confirmado = bool(
                    perguntar_gestor_e_aguardar(
                        pergunta,
                        timeout_segundos=600,
                        contexto_decisao={
                            "decisao": "enviar_necessidade_manicures",
                            "campanha_id": escolhida.get("campanha_id"),
                            "score": escolhida.get("score"),
                            "angulo": (escolhida.get("condicoes") or {}).get("angulo"),
                        },
                    )
                )
                if confirmado:
                    envios = _enviar_canais(escolhida)
                    envios["adiado"] = False
                    motivo_envio = envios.get("motivo") or "enviado"
                else:
                    motivo_envio = "gestor_negou_ou_timeout"
            else:
                # --sem-confirmacao: só em dry local explícito
                envios = _enviar_canais(escolhida)
                envios["adiado"] = False
                motivo_envio = envios.get("motivo") or "enviado_sem_confirmacao"
                confirmado = True

        if envios.get("whatsapp") or envios.get("telegram"):
            historico["ultimo_envio_ativo_em"] = datetime.now(timezone.utc).isoformat()
            historico["ultima_campanha_id"] = escolhida.get("campanha_id") if escolhida else None
            escrever_json_atomico(HISTORY_PATH, historico)

        payload = {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "plano": {
                "sinais_lidos": plano.get("sinais_lidos"),
                "pronto_enviar": plano.get("pronto_enviar"),
                "sustentabilidade": plano.get("sustentabilidade"),
                "escolhida": escolhida,
                "matches": plano.get("matches"),
                "gaps": plano.get("gaps"),
            },
            "confirmado": confirmado,
            "envios": {**envios, "motivo": motivo_envio},
            "mensagem": msg,
            "modo": "dry_run" if not enviar else "envio",
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        gauge("necessidade_manicures.sinais", float(plano.get("sinais_lidos") or 0))
        gauge(
            "necessidade_manicures.score",
            float((escolhida or {}).get("score") or 0),
        )
        if envios.get("whatsapp") or envios.get("telegram"):
            incrementar("necessidade_manicures.envio_ok")
        else:
            incrementar("necessidade_manicures.sem_envio")

        return {
            "ok": True,
            "pronto_enviar": plano.get("pronto_enviar"),
            "campanha_id": (escolhida or {}).get("campanha_id"),
            "confirmado": confirmado,
            "envios": payload["envios"],
            "gaps": plano.get("gaps"),
            "resumo_orquestrador": (
                f"match={(escolhida or {}).get('campanha_id') or 'n/d'} "
                f"envio={motivo_envio}"
            )[:120],
        }
    except Exception as exc:
        logger.error("agente_necessidade_manicures erro: %s", exc)
        incrementar("necessidade_manicures.erro")
        return {"ok": False, "erro": str(exc)[:200]}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Necessidade manicures × ML × canais")
    parser.add_argument("--sem-envio", action="store_true", help="Não envia WA/TG")
    parser.add_argument(
        "--sem-confirmacao",
        action="store_true",
        help="Não pede SIM/NÃO (só use em dry local consciente)",
    )
    parser.add_argument("--sem-alerta", action="store_true")
    args = parser.parse_args()
    out = executar(
        enviar=not args.sem_envio,
        pedir_confirmacao=False if args.sem_confirmacao else None,
        enviar_alerta=not args.sem_alerta,
    )
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro") or out.get("motivo"),
            "campanha_id": out.get("campanha_id"),
            "pronto_enviar": out.get("pronto_enviar"),
            "confirmado": out.get("confirmado"),
            "envios": out.get("envios"),
            "gaps": out.get("gaps"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
