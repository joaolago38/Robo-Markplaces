"""
agentes/esmaltes/agente_esmaltes_operacao.py
Consolida em um run: crescimento (KPI) → decisão do dia → ecossistema.

Os três agentes individuais continuam existentes para testes/manual;
aqui eles rodam com enviar_alerta=False e um único Telegram é enviado.

Uso:
  python -m agentes.esmaltes.agente_esmaltes_operacao
  python -m agentes.esmaltes.agente_esmaltes_operacao --sem-alerta
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import (
    ESMALTES_OPERACAO_ALERTA,
    ESMALTES_OPERACAO_ATIVO,
    ESMALTES_OPERACAO_COOLDOWN_SEG,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from core.prontidao import pode_alertar_esmaltes

logger = logging.getLogger("agente_esmaltes_operacao")

SNAPSHOT_PATH = ROOT / "logs" / "esmaltes_operacao_ultima.json"


def _ok(out: dict[str, Any] | None) -> bool:
    return bool(out and out.get("ok"))


def montar_mensagem_consolidada(
    *,
    crescimento: dict[str, Any] | None,
    decisao: dict[str, Any] | None,
    ecossistema: dict[str, Any] | None,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "esmaltes_operacao",
            "🎯 *Impala — operação do dia (consolidado)*",
        ),
        "",
        "_Crescimento → Decisão → Ecossistema em um único alerta._",
    ]

    if _ok(decisao) and decisao.get("mensagem"):
        linhas.extend(["", "─── *1) Decisão do dia* ───", str(decisao["mensagem"]).strip()])
    elif decisao and not decisao.get("ok"):
        linhas.extend(
            [
                "",
                "─── *1) Decisão do dia* ───",
                f"_Falhou: `{decisao.get('erro') or decisao.get('motivo') or '?'}`_",
            ]
        )

    if _ok(crescimento) and crescimento.get("mensagem"):
        # evita repetir cabeçalho enorme: pega corpo se possível
        msg = str(crescimento["mensagem"]).strip()
        linhas.extend(["", "─── *2) Crescimento / KPI* ───", msg])
    elif crescimento and not crescimento.get("ok"):
        linhas.extend(
            [
                "",
                "─── *2) Crescimento / KPI* ───",
                f"_Falhou: `{crescimento.get('erro') or crescimento.get('motivo') or '?'}`_",
            ]
        )

    if _ok(ecossistema) and ecossistema.get("mensagem"):
        linhas.extend(
            ["", "─── *3) Ecossistema* ───", str(ecossistema["mensagem"]).strip()]
        )
    elif ecossistema and not ecossistema.get("ok"):
        linhas.extend(
            [
                "",
                "─── *3) Ecossistema* ───",
                f"_Falhou: `{ecossistema.get('erro') or ecossistema.get('motivo') or '?'}`_",
            ]
        )

    return "\n".join(linhas).strip()


def executar(
    *,
    enviar_alerta: bool = True,
    rodar_crescimento: bool = True,
    rodar_decisao: bool = True,
    rodar_ecossistema: bool = True,
) -> dict[str, Any]:
    """Orquestra os 3 agentes sem alertas individuais. Nunca lança."""
    try:
        if not ESMALTES_OPERACAO_ATIVO:
            return {"ok": False, "motivo": "agente_desligado", "alerta_enviado": False}

        from agentes.esmaltes import agente_crescimento_esmaltes as cre
        from agentes.esmaltes import agente_decisao_dia_esmaltes as dia
        from agentes.esmaltes import agente_ecossistema_esmaltes as eco

        pode_alertar, motivo = (True, "ok")
        if enviar_alerta:
            pode_alertar, motivo = pode_alertar_esmaltes()
            if not pode_alertar:
                logger.warning("Telegram esmaltes bloqueado: %s", motivo)
            elif not gestor_telegram_configurado():
                logger.warning("Telegram gestor não configurado")

        # Ordem: crescimento grava snapshot usado pela decisão; eco lê vários logs.
        out_cre: dict[str, Any] | None = None
        out_dia: dict[str, Any] | None = None
        out_eco: dict[str, Any] | None = None

        if rodar_crescimento:
            logger.info("esmaltes_operacao: crescimento")
            out_cre = cre.executar(enviar_alerta=False)
        if rodar_decisao:
            logger.info("esmaltes_operacao: decisao_dia")
            out_dia = dia.executar(enviar_alerta=False)
        if rodar_ecossistema:
            logger.info("esmaltes_operacao: ecossistema")
            out_eco = eco.executar(enviar_alerta=False)

        msg = montar_mensagem_consolidada(
            crescimento=out_cre, decisao=out_dia, ecossistema=out_eco
        )

        agora = datetime.now(timezone.utc).isoformat()
        payload = {
            "timestamp": agora,
            "ok": True,
            "crescimento": {
                "ok": _ok(out_cre),
                "critico": (out_cre or {}).get("critico"),
                "kits_sem_mlb": (out_cre or {}).get("kits_sem_mlb"),
            }
            if out_cre is not None
            else None,
            "decisao": {
                "ok": _ok(out_dia),
                "fazer": (out_dia or {}).get("fazer"),
                "nao_fazer": (out_dia or {}).get("nao_fazer"),
            }
            if out_dia is not None
            else None,
            "ecossistema": {
                "ok": _ok(out_eco),
                "score": (out_eco or {}).get("score_ecossistema"),
                "acoes": (out_eco or {}).get("acoes"),
            }
            if out_eco is not None
            else None,
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        partes_ok = sum(
            1
            for o in (out_cre, out_dia, out_eco)
            if o is not None and _ok(o)
        )
        partes_total = sum(
            1 for o in (out_cre, out_dia, out_eco) if o is not None
        )
        gauge("esmaltes_operacao.partes_ok", float(partes_ok))
        gauge("esmaltes_operacao.partes_total", float(partes_total))

        enviado = False
        algum_ok = partes_ok > 0
        if (
            enviar_alerta
            and ESMALTES_OPERACAO_ALERTA
            and pode_alertar
            and algum_ok
            and msg
        ):
            enviado = bool(
                alertar_gestor(
                    msg,
                    chave=chave_resumo_periodo("esmaltes_operacao", horas_por_bucket=20),
                    cooldown_segundos=ESMALTES_OPERACAO_COOLDOWN_SEG,
                    agente_id="esmaltes_operacao",
                )
            )

        incrementar("esmaltes_operacao.ok")
        return {
            "ok": algum_ok,
            "alerta_enviado": enviado,
            "partes_ok": partes_ok,
            "partes_total": partes_total,
            "crescimento": out_cre,
            "decisao": out_dia,
            "ecossistema": out_eco,
            "mensagem": msg,
        }
    except Exception as exc:
        logger.error("agente_esmaltes_operacao erro: %s", exc)
        incrementar("esmaltes_operacao.erro")
        return {"ok": False, "erro": str(exc), "alerta_enviado": False}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Operação esmaltes consolidada")
    parser.add_argument("--sem-alerta", action="store_true")
    parser.add_argument("--sem-crescimento", action="store_true")
    parser.add_argument("--sem-decisao", action="store_true")
    parser.add_argument("--sem-ecossistema", action="store_true")
    args = parser.parse_args(argv)
    out = executar(
        enviar_alerta=not args.sem_alerta,
        rodar_crescimento=not args.sem_crescimento,
        rodar_decisao=not args.sem_decisao,
        rodar_ecossistema=not args.sem_ecossistema,
    )
    print(
        {
            "ok": out.get("ok"),
            "erro": out.get("erro"),
            "motivo": out.get("motivo"),
            "alerta_enviado": out.get("alerta_enviado"),
            "partes_ok": out.get("partes_ok"),
            "partes_total": out.get("partes_total"),
        }
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
