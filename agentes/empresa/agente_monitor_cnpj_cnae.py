"""
agentes/empresa/agente_monitor_cnpj_cnae.py
Monitora vínculos CNAE → CNPJ → produtos a cada ~10 dias.

- Resolve qual CNPJ se encaixa no CNAE
- Lista produtos vinculados a esse CNPJ
- Se houver alteração (ou ciclo de 10 dias), inicia monitoramento Mercado Livre
- Telegram em formato de decisão: AGIR → PANORAMA ML → PRÓXIMOS PASSOS
- Demais marketplaces ficam abertos no perfil

Uso:
  python -m agentes.empresa.agente_monitor_cnpj_cnae
  python -m agentes.empresa.agente_monitor_cnpj_cnae --cnae 4772-5/00
  python -m agentes.empresa.agente_monitor_cnpj_cnae --cnpj 52668583000127
  python -m agentes.empresa.agente_monitor_cnpj_cnae --forcar-ml
"""
from __future__ import annotations

import argparse
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from core.notificador import alertar_gestor, chave_resumo_periodo, gestor_telegram_configurado
from integracoes.empresa.monitor_ml_cnpj import montar_ciclo_monitor_ml
from integracoes.empresa.vinculo_cnae_cnpj_produtos import (
    detectar_alteracoes,
    montar_vinculo,
    salvar_snapshot,
)

logger = logging.getLogger("agente_monitor_cnpj_cnae")

SNAPSHOT_PATH = ROOT / "logs" / "monitor_cnpj_cnae_ultima.json"


def _cfg():
    from core import config as cfg

    return cfg


def montar_mensagem(resultado: dict[str, Any]) -> str:
    """Card de decisão: AGIR AGORA → PANORAMA ML × CNPJ → PRÓXIMOS PASSOS."""
    from core.telegram_explicacao import cabecalho_agente

    intervalo = int(
        (resultado.get("ciclo_ml") or {}).get("intervalo_dias")
        or getattr(_cfg(), "MONITOR_CNPJ_CNAE_INTERVALO_DIAS", 10)
    )
    linhas = [
        cabecalho_agente(
            "monitor_cnpj_cnae",
            "🏢 *CNPJ × CNAE × ML — decisão*",
        ),
        "",
        f"_Ciclo *{intervalo} dias* · foco *Mercado Livre* · demais MKs abertos_",
        f"CNPJs verificados: *{resultado.get('total', 0)}* · "
        f"ML nesta rodada: *{(resultado.get('ciclo_ml') or {}).get('total_monitorados_ml', 0)}*",
    ]

    alteracoes = resultado.get("alteracoes") or []
    subsidios = (resultado.get("ciclo_ml") or {}).get("subsidios") or []

    # --- 1) AGIR AGORA ---
    linhas.extend(["", "*1) AGIR AGORA*"])
    if alteracoes:
        linhas.append(f"⚠️ *{len(alteracoes)}* alteração(ões) de CNPJ — monitoramento ML ativado")
        for a in alteracoes[:4]:
            linhas.append(
                f"• *{a.get('nome_fantasia') or a.get('empresa_id')}* "
                f"`{a.get('cnpj_formatado')}` — `{a.get('motivo')}`"
            )
            for d in (a.get("deltas") or [])[:2]:
                linhas.append(f"   _{d}_")
    elif not subsidios:
        linhas.append("_Sem alteração e sem CNPJ devido no ciclo — nada a forçar agora._")

    urgencias = []
    for sub in subsidios:
        acoes = sub.get("acoes") or {}
        urg = acoes.get("urgencia") or "baixa"
        urgencias.append(urg)
        prefix = "🔴" if urg == "alta" else ("🟡" if urg == "media" else "🟢")
        nome = sub.get("empresa_id") or sub.get("cnpj_formatado")
        linhas.append(f"{prefix} *{nome}* (`{sub.get('cnpj_formatado')}`)")
        for f in (acoes.get("fazer") or [])[:3]:
            linhas.append(f"  ✅ {f}")
        for n in (acoes.get("nao_fazer") or [])[:2]:
            linhas.append(f"  ⛔ {n}")
        for c in (acoes.get("custo") or [])[:2]:
            linhas.append(f"  💰 {c}")
        dl = sub.get("decision_limits") or {}
        if dl.get("resumo"):
            linhas.append(f"  _Limites: {dl['resumo']}_")

    # --- 2) PANORAMA ---
    linhas.extend(["", "*2) PANORAMA ML × CNPJ*"])
    if subsidios:
        for sub in subsidios[:4]:
            rc = sub.get("resumo_conta") or {}
            em = sub.get("estado_ml") or {}
            vr = sub.get("vinculo_resumo") or {}
            linhas.append(
                f"*{sub.get('empresa_id') or 'CNPJ'}* · `{sub.get('cnpj_formatado')}` · "
                f"motivo `{sub.get('motivo_ciclo')}`"
            )
            linhas.append(
                f"  CNAE `{vr.get('cnae_principal') or '—'}` · "
                f"SKUs *{vr.get('total_skus') or 0}*"
                + (" · dono" if vr.get("eh_dono") else "")
            )
            if rc.get("ok"):
                linhas.append(
                    f"  ML: ativos *{rc.get('anuncios_ativos') or 0}* · "
                    f"a melhorar *{rc.get('anuncios_a_melhorar_total') or 0}* · "
                    f"perguntas *{rc.get('perguntas_pendentes') or 0}* · "
                    f"claims *{rc.get('pos_venda_claims') or 0}*"
                )
                if rc.get("reputacao"):
                    linhas.append(f"  Reputação: _{rc.get('reputacao')}_")
                for item in (rc.get("a_melhorar_top") or [])[:2]:
                    linhas.append(
                        f"    · `{item.get('item_id')}` {item.get('titulo') or ''} "
                        f"(score {item.get('score') or 0})"
                    )
            else:
                linhas.append(
                    f"  ML ao vivo: _{rc.get('erro') or 'indisponível'}_ — "
                    f"nível snapshot `{em.get('nivel') or '—'}`"
                )
            for al in (em.get("alertas") or [])[:2]:
                linhas.append(f"  ⚠ _{al}_")
            abertos = vr.get("marketplaces_abertos") or []
            if abertos:
                linhas.append(f"  Abertos (não foco): {', '.join(abertos[:4])}")
    else:
        for v in (resultado.get("vinculos") or [])[:4]:
            prods = v.get("produtos") or {}
            linhas.append(
                f"*{v.get('nome_fantasia') or v.get('empresa_id')}* · "
                f"`{v.get('cnpj_formatado')}` · CNAE `{v.get('cnae_principal') or '—'}` · "
                f"SKUs *{prods.get('total_skus') or 0}*"
            )

    dono = resultado.get("dono_produtos_global") or {}
    if dono:
        linhas.extend(
            [
                "",
                f"_Dono produtos: `{dono.get('cnpj_formatado')}`"
                + (" (alvo)_" if dono.get("usando_alvo") else " (atual)_")
                + f" · migração `{dono.get('cnpj_alvo')}`_",
            ]
        )

    # --- 3) PRÓXIMOS PASSOS ---
    linhas.extend(["", "*3) PRÓXIMOS PASSOS*"])
    passos: list[str] = []
    if alteracoes:
        passos.append("Acompanhar este CNPJ no radar — fingerprint mudou; ML já ligado")
    for sub in subsidios[:3]:
        agentes = (sub.get("vinculo_resumo") or {}).get("agentes_prioritarios") or []
        if agentes:
            passos.append(f"Priorizar: {', '.join(agentes[:3])}")
        for item in ((sub.get("resumo_conta") or {}).get("precos_top") or [])[:1]:
            passos.append(
                f"Preço ML `{item.get('item_id')}`: "
                f"{item.get('preco_atual')} → sugerido {item.get('preco_sugerido')}"
            )
        for b in (sub.get("decision_limits") or {}).get("bloqueios") or []:
            if b.get("acao") == "bloquear":
                passos.append(f"Bloqueado `{b.get('tema')}`: {b.get('motivo')}")
                break
    if not passos:
        passos.append(f"Próxima varredura completa em até {intervalo} dias (ou na próxima alteração)")
    for p in passos[:6]:
        linhas.append(f"• {p}")

    linhas.extend(
        [
            "",
            "_Subsídio: Alibaba + USD + vendas + saúde do produto → limites Datadog "
            "por CNAE/CNPJ; ecossistema não repete o mesmo tema na janela._",
        ]
    )
    return "\n".join(linhas)


def executar(
    *,
    cnae: str | None = None,
    cnpj: str | None = None,
    empresa_id: str | None = None,
    enviar_alerta: bool | None = None,
    forcar_ml: bool = False,
    ml_ao_vivo: bool | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    ativo = bool(getattr(cfg, "MONITOR_CNPJ_CNAE_ATIVO", True))
    if not ativo:
        return {"ok": False, "motivo": "MONITOR_CNPJ_CNAE_ATIVO=0"}

    alerta = (
        bool(getattr(cfg, "MONITOR_CNPJ_CNAE_ALERTA", True))
        if enviar_alerta is None
        else enviar_alerta
    )
    intervalo = max(1, int(getattr(cfg, "MONITOR_CNPJ_CNAE_INTERVALO_DIAS", 10)))
    # Cooldown alinhado ao ciclo (evita spam entre workflow_dispatch e schedule)
    cooldown = int(getattr(cfg, "MONITOR_CNPJ_CNAE_COOLDOWN_SEG", intervalo * 24 * 3600))
    ao_vivo = (
        bool(getattr(cfg, "MONITOR_CNPJ_CNAE_ML_AO_VIVO", True))
        if ml_ao_vivo is None
        else ml_ao_vivo
    )

    base = montar_vinculo(cnae=cnae, cnpj=cnpj, empresa_id=empresa_id)
    alteracoes = detectar_alteracoes(base.get("vinculos") or [])

    # Forçar ciclo ML em todos os vínculos desta rodada
    ciclo = montar_ciclo_monitor_ml(
        base.get("vinculos") or [],
        alteracoes,
        ao_vivo=ao_vivo,
        intervalo_dias=intervalo,
        forcar_todos=forcar_ml,
    )

    from integracoes.empresa.vinculo_cnae_cnpj_produtos import carregar_monitorados

    mon = carregar_monitorados()
    mon_itens = [
        v
        for v in (mon.get("cnpjs") or {}).values()
        if isinstance(v, dict) and v.get("ativo")
    ]

    resultado = {
        **base,
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "alteracoes": alteracoes,
        "monitorados_ativos": mon_itens,
        "tem_alteracao": bool(alteracoes),
        "ciclo_ml": ciclo,
        "intervalo_dias": intervalo,
    }
    salvar_snapshot(resultado)
    escrever_json_atomico(SNAPSHOT_PATH, resultado)

    gauge("monitor_cnpj_cnae.vinculos", float(resultado.get("total") or 0))
    gauge("monitor_cnpj_cnae.alteracoes", float(len(alteracoes)))
    gauge("monitor_cnpj_cnae.ml_rodadas", float(ciclo.get("total_monitorados_ml") or 0))
    incrementar("monitor_cnpj_cnae.rodadas")

    msg = montar_mensagem(resultado)
    resultado["mensagem"] = msg

    so_alteracao = bool(getattr(cfg, "MONITOR_CNPJ_CNAE_ALERTA_SO_ALTERACAO", False))
    # Alerta se: alteração OU houve coleta ML no ciclo (subsídio de decisão)
    teve_ml = bool(ciclo.get("total_monitorados_ml"))
    deve_alertar = alerta and (
        alteracoes or teve_ml or (not so_alteracao)
    )
    # Se flag SO_ALTERACAO e não houve alteração nem ML, não envia
    if so_alteracao and not alteracoes and not teve_ml:
        deve_alertar = False

    if deve_alertar and gestor_telegram_configurado():
        try:
            alertar_gestor(
                msg,
                chave=chave_resumo_periodo(
                    "monitor_cnpj_cnae",
                    horas_por_bucket=max(1, min(cooldown // 3600, intervalo * 24)),
                ),
                cooldown_segundos=cooldown,
                agente_id="monitor_cnpj_cnae",
            )
            incrementar("monitor_cnpj_cnae.telegram_ok")
        except Exception as exc:
            logger.warning("Telegram monitor CNPJ/CNAE: %s", exc)
            incrementar("monitor_cnpj_cnae.telegram_erro")

    return resultado


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Monitor CNPJ × CNAE × ML (ciclo 10d)")
    p.add_argument("--cnae", default="", help="CNAE para resolver CNPJ(s)")
    p.add_argument("--cnpj", default="", help="CNPJ específico")
    p.add_argument("--empresa-id", default="", help="ID no catálogo (esmaltes_impala|masterprint)")
    p.add_argument("--sem-alerta", action="store_true")
    p.add_argument("--forcar-ml", action="store_true", help="Força coleta ML mesmo fora do ciclo")
    p.add_argument("--sem-ml-ao-vivo", action="store_true", help="Só snapshots (sem API ML)")
    args = p.parse_args()
    out = executar(
        cnae=args.cnae or None,
        cnpj=args.cnpj or None,
        empresa_id=args.empresa_id or None,
        enviar_alerta=not args.sem_alerta,
        forcar_ml=args.forcar_ml,
        ml_ao_vivo=not args.sem_ml_ao_vivo,
    )
    print(out.get("mensagem") or out)


if __name__ == "__main__":
    main()
