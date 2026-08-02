"""
agentes/esmaltes/agente_esmaltes_operacao.py
Consolida em um run: crescimento (KPI) → decisão do dia → ecossistema.

Telegram: card de decisão (FAZER primeiro), depois evidências curtas.
Os três agentes individuais continuam para testes/manual;
aqui rodam com enviar_alerta=False e um único alerta é enviado.

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
    """
    Card organizado para decisão:
      1) AGIR AGORA (FAZER / NÃO FAZER / CUSTO)
      2) Panorama (KPI + score)
      3) Gaps / próximos 7 dias
    """
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "esmaltes_operacao",
            "🎯 *Impala — operação do dia*",
        ),
        "",
        "*1) AGIR AGORA*",
    ]

    if _ok(decisao):
        fazer_t = decisao.get("fazer_titulo") or decisao.get("fazer") or "—"
        fazer_d = decisao.get("fazer_detalhe") or ""
        nao_t = decisao.get("nao_fazer_titulo") or decisao.get("nao_fazer") or "—"
        nao_d = decisao.get("nao_fazer_detalhe") or ""
        custo_t = decisao.get("custo_titulo") or ""
        custo_d = decisao.get("custo_detalhe") or ""
        linhas.append(f"✅ *FAZER:* {fazer_t}")
        if fazer_d:
            linhas.append(f"   _{fazer_d}_")
        linhas.append(f"🛑 *NÃO FAZER:* {nao_t}")
        if nao_d:
            linhas.append(f"   _{nao_d}_")
        if custo_t:
            linhas.append(f"💸 *CUSTO DE NÃO FAZER:* {custo_t}")
            if custo_d:
                linhas.append(f"   _{custo_d}_")
        lib = decisao.get("liberados")
        bloq = decisao.get("bloqueados")
        if lib is not None or bloq is not None:
            linhas.append(
                f"Guerra: *{lib or 0}* liberado(s) / *{bloq or 0}* bloqueado(s)"
            )
        for s in (decisao.get("skus_guerra") or [])[:3]:
            if not isinstance(s, dict):
                continue
            emoji = "🟢" if s.get("pode_impulsionar") else "🔴"
            status = "OK" if s.get("pode_impulsionar") else "/".join(s.get("bloqueios") or ["bloqueado"])
            linhas.append(f"{emoji} `{s.get('sku')}` ({s.get('papel')}) {status}")
    elif decisao and not decisao.get("ok"):
        linhas.append(
            f"_Decisão falhou: `{decisao.get('erro') or decisao.get('motivo') or '?'}`_"
        )
    else:
        linhas.append("_Sem decisão nesta rodada._")

    # --- Panorama ---
    linhas.extend(["", "*2) PANORAMA*"])
    kpis = {}
    if _ok(decisao) and isinstance(decisao.get("kpis"), dict):
        kpis = decisao["kpis"]
    elif _ok(crescimento) and isinstance(crescimento.get("kpis"), dict):
        kpis = crescimento["kpis"]

    partes_kpi: list[str] = []
    if kpis and not kpis.get("sem_vendas_periodo"):
        if kpis.get("kits_pct_receita") is not None:
            ok_k = "✅" if kpis.get("kits_meta_ok") else "⚠️"
            partes_kpi.append(f"{ok_k} kits *{kpis.get('kits_pct_receita')}%*")
        if kpis.get("margem_media_pct") is not None:
            ok_m = "✅" if kpis.get("margem_meta_ok") else "⚠️"
            partes_kpi.append(f"{ok_m} margem *{kpis.get('margem_media_pct')}%*")
    if partes_kpi:
        linhas.append("KPI: " + " · ".join(partes_kpi))
    elif _ok(crescimento) and crescimento.get("critico"):
        linhas.append("KPI: 🚨 gaps críticos de publicação/canal")
    else:
        linhas.append("KPI: _sem dado de margem no período_")

    score = None
    if _ok(ecossistema):
        score = ecossistema.get("score_ecossistema")
    elif _ok(crescimento):
        score = crescimento.get("score_ecossistema")
    cob = (ecossistema or {}).get("cobertura_fontes_pct") if _ok(ecossistema) else None
    if score is not None:
        extra = f" · cobertura *{cob}%*" if cob is not None else ""
        linhas.append(f"Ecossistema: score *{score}*{extra}")

    if _ok(crescimento) and crescimento.get("kits_sem_mlb") is not None:
        n = crescimento.get("kits_sem_mlb")
        flag = "🚨" if crescimento.get("critico") else "•"
        linhas.append(f"{flag} Kits sem MLB: *{n}*")

    # --- Próximos passos (evidência curta) ---
    linhas.extend(["", "*3) PRÓXIMOS PASSOS*"])
    passos: list[str] = []

    if _ok(crescimento):
        for c in (crescimento.get("checklist") or [])[:3]:
            if not isinstance(c, dict):
                continue
            titulo = c.get("titulo") or c.get("tipo") or "?"
            passos.append(f"• [gap] {titulo}")
        for k in (crescimento.get("kits_sem_mlb_lista") or [])[:2]:
            if isinstance(k, dict) and k.get("sku"):
                passos.append(f"• [MLB] `{k.get('sku')}` — {k.get('nome') or ''}".rstrip(" —"))

    if _ok(ecossistema):
        for i, a in enumerate((ecossistema.get("top_7d") or [])[:3], 1):
            if not isinstance(a, dict):
                continue
            passos.append(
                f"• [7d-{i}] {a.get('titulo') or '?'}"
                + (f" _(score {a.get('score')})_" if a.get("score") is not None else "")
            )

    if passos:
        linhas.extend(passos)
    else:
        linhas.append("_Nenhum gap/ação 7d listado nesta rodada._")

    linhas.extend(
        [
            "",
            "_Leitura:_ execute só o *FAZER* de hoje; gaps e 7d são fila, não competem com a decisão._",
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
                "acoes": len((out_eco or {}).get("acoes") or [])
                if isinstance((out_eco or {}).get("acoes"), list)
                else (out_eco or {}).get("acoes"),
            }
            if out_eco is not None
            else None,
            "mensagem": msg,
        }
        escrever_json_atomico(SNAPSHOT_PATH, payload)

        partes_ok = sum(1 for o in (out_cre, out_dia, out_eco) if o is not None and _ok(o))
        partes_total = sum(1 for o in (out_cre, out_dia, out_eco) if o is not None)
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
