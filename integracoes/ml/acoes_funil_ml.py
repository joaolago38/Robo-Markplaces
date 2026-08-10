"""
Ações a partir do funil próprio (visitas → pedidos → conversão).

Liga diagnóstico a prioridades acionáveis:
  - sem visitas → ads / republicar
  - poucas visitas → título + ads
  - visitas sem venda / conversão baixa → preço / listing
  - conversão boa → manter / escalar

Persiste fila para o otimizador_listing priorizar.
Não aplica escrita sozinho (gestor / agentes existentes decidem).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge

logger = logging.getLogger("acoes_funil_ml")

ACOES_PATH = ROOT / "logs" / "funil_ml_acoes_ultima.json"

# Prioridade: menor = mais urgente
_PRIORIDADE = {
    "baixar_preco_ou_listing": 1,
    "melhorar_conversao_listing": 2,
    "melhorar_titulo_e_ads": 3,
    "republicar_ou_ads": 4,
    "escalar_ou_manter": 5,
    "aguardar_amostra": 6,
}

_ROTULO = {
    "baixar_preco_ou_listing": "Visitas sem conversão → preço / frete / fotos",
    "melhorar_conversao_listing": "Converte pouco → listing (fotos/descrição/preço)",
    "melhorar_titulo_e_ads": "Poucas visitas → título + Product Ads leve",
    "republicar_ou_ads": "Sem visitas → ads ou republicar",
    "escalar_ou_manter": "Conversão ok → manter / escalar o que funciona",
    "aguardar_amostra": "Amostra pequena → aguardar mais visitas",
}

_AGENTE_SUGERIDO = {
    "baixar_preco_ou_listing": "monitor_sem_venda_ml|inteligencia_precos|otimizador_listing",
    "melhorar_conversao_listing": "otimizador_listing|inteligencia_precos",
    "melhorar_titulo_e_ads": "otimizador_listing|ads_gatilho",
    "republicar_ou_ads": "ads_gatilho|otimizador_listing",
    "escalar_ou_manter": "ads_gatilho",
    "aguardar_amostra": "",
}


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _f(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def classificar_item_funil(
    item: dict[str, Any],
    *,
    visitas_altas: int = 20,
    min_visitas_conv: int = 10,
    conv_baixa_pct: float = 2.0,
    conv_boa_pct: float = 5.0,
) -> dict[str, Any]:
    """Classifica um item do funil e devolve ação sugerida."""
    v7 = item.get("visitas_7d")
    visitas = _i(v7) if v7 is not None else 0
    visitas_disp = v7 is not None
    un = _i(item.get("unidades_pedidos"))
    conv = _f(item.get("conversao_pct"))
    confiavel = bool(item.get("conversao_confiavel"))
    if item.get("conversao_confiavel") is None and visitas_disp:
        confiavel = visitas >= max(1, min_visitas_conv)

    if not visitas_disp:
        acao = "aguardar_amostra"
        motivo = "visitas indisponíveis nesta coleta"
    elif visitas <= 0:
        acao = "republicar_ou_ads"
        motivo = "0 visitas no período"
    elif un <= 0 and visitas >= visitas_altas:
        acao = "baixar_preco_ou_listing"
        motivo = f"{visitas} visitas sem venda"
    elif un <= 0:
        acao = "melhorar_titulo_e_ads"
        motivo = f"só {visitas} visitas e 0 vendas"
    elif not confiavel:
        acao = "aguardar_amostra"
        motivo = f"amostra pequena ({visitas} vis < {min_visitas_conv})"
    elif conv is not None and conv < conv_baixa_pct:
        acao = "melhorar_conversao_listing"
        motivo = f"conversão {conv}% abaixo de {conv_baixa_pct}%"
    elif conv is not None and conv >= conv_boa_pct:
        acao = "escalar_ou_manter"
        motivo = f"conversão {conv}% ok"
    else:
        acao = "aguardar_amostra"
        motivo = f"conversão intermediária ({conv}%) — observar"

    return {
        "item_id": str(item.get("item_id") or ""),
        "sku": str(item.get("sku") or ""),
        "titulo": str(item.get("titulo") or "")[:80],
        "visitas_7d": visitas if visitas_disp else None,
        "unidades_pedidos": un,
        "conversao_pct": conv,
        "conversao_confiavel": confiavel,
        "visitas_convertidas_proxy": un,
        "acao": acao,
        "acao_rotulo": _ROTULO.get(acao, acao),
        "prioridade": _PRIORIDADE.get(acao, 99),
        "motivo": motivo,
        "agente_sugerido": _AGENTE_SUGERIDO.get(acao, ""),
        "critica": acao in ("baixar_preco_ou_listing", "melhorar_conversao_listing"),
    }


def gerar_acoes_funil(
    funil: dict[str, Any] | None,
    *,
    visitas_altas: int = 20,
    min_visitas_conv: int = 10,
    conv_baixa_pct: float = 2.0,
    conv_boa_pct: float = 5.0,
    max_acoes: int = 25,
    contexto: str = "funil_ml",
) -> dict[str, Any]:
    """Gera lista de ações priorizadas a partir do funil próprio."""
    if not funil or not funil.get("ok"):
        return {
            "ok": False,
            "motivo": (funil or {}).get("motivo") or "funil indisponível",
            "contexto": contexto,
            "acoes": [],
            "por_acao": {},
            "criticas": 0,
            "totais_funil": {},
        }

    acoes: list[dict[str, Any]] = []
    for item in funil.get("itens") or []:
        if not isinstance(item, dict):
            continue
        row = classificar_item_funil(
            item,
            visitas_altas=visitas_altas,
            min_visitas_conv=min_visitas_conv,
            conv_baixa_pct=conv_baixa_pct,
            conv_boa_pct=conv_boa_pct,
        )
        if row.get("item_id"):
            acoes.append(row)

    acoes.sort(
        key=lambda x: (
            int(x.get("prioridade") or 99),
            -_i(x.get("visitas_7d")),
            -_i(x.get("unidades_pedidos")),
        )
    )
    if max_acoes > 0:
        acoes = acoes[:max_acoes]

    por_acao: dict[str, int] = {}
    for row in acoes:
        por_acao[row["acao"]] = por_acao.get(row["acao"], 0) + 1

    criticas = sum(1 for r in acoes if r.get("critica"))
    return {
        "ok": True,
        "contexto": contexto,
        "dias": funil.get("dias"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "acoes": acoes,
        "por_acao": por_acao,
        "criticas": criticas,
        "totais_funil": funil.get("totais") or {},
        "item_ids_prioridade": [
            r["item_id"]
            for r in acoes
            if r.get("acao")
            in (
                "baixar_preco_ou_listing",
                "melhorar_conversao_listing",
                "melhorar_titulo_e_ads",
                "republicar_ou_ads",
            )
        ],
    }


def persistir_acoes_funil(acoes: dict[str, Any], *, caminho: Any = None) -> bool:
    """Persiste por contexto e mescla item_ids_prioridade de todas as fontes."""
    path = caminho or ACOES_PATH
    try:
        atual = ler_json(path, default={})
        if not isinstance(atual, dict):
            atual = {}
        por_ctx = atual.get("por_contexto") if isinstance(atual.get("por_contexto"), dict) else {}
        contexto = str(acoes.get("contexto") or "geral")
        por_ctx[contexto] = dict(acoes)

        ids: list[str] = []
        seen: set[str] = set()
        criticas = 0
        for ctx_acoes in por_ctx.values():
            if not isinstance(ctx_acoes, dict):
                continue
            criticas += _i(ctx_acoes.get("criticas"))
            for raw in ctx_acoes.get("item_ids_prioridade") or []:
                iid = str(raw or "").strip().upper()
                if iid and iid not in seen:
                    seen.add(iid)
                    ids.append(iid)

        payload = {
            **acoes,
            "por_contexto": por_ctx,
            "item_ids_prioridade": ids,
            "criticas_total": criticas,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        escrever_json_atomico(path, payload)
        return True
    except Exception as exc:
        logger.warning("persistir acoes funil: %s", exc)
        return False


def carregar_acoes_funil(*, caminho: Any = None) -> dict[str, Any]:
    data = ler_json(caminho or ACOES_PATH, default={})
    return data if isinstance(data, dict) else {}


def listar_item_ids_prioridade_funil(*, caminho: Any = None) -> list[str]:
    """IDs para o otimizador priorizar (fail-open: lista vazia se sem arquivo)."""
    data = carregar_acoes_funil(caminho=caminho)
    ids = data.get("item_ids_prioridade") or []
    out: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        iid = str(raw or "").strip().upper()
        if iid and iid not in seen:
            seen.add(iid)
            out.append(iid)
    return out


def formatar_secao_acoes_funil(acoes: dict[str, Any] | None, *, top_n: int = 8) -> list[str]:
    if not acoes or not acoes.get("ok"):
        return []
    lista = acoes.get("acoes") or []
    if not lista:
        return []
    linhas = [
        "",
        f"*AGIR — funil próprio* _(críticas: {_i(acoes.get('criticas'))})_",
    ]
    por = acoes.get("por_acao") or {}
    if por:
        resumo = ", ".join(f"{k.replace('_', ' ')}={v}" for k, v in sorted(por.items()))
        linhas.append(f"• Distribuição: {resumo}")

    # Só mostra ações que pedem intervenção (não aguardar/escalar no topo)
    urgentes = [r for r in lista if r.get("acao") not in ("aguardar_amostra",)]
    if not urgentes:
        urgentes = lista[:3]
    for row in urgentes[: max(0, top_n)]:
        tit = str(row.get("titulo") or row.get("item_id") or "?")[:45]
        v = row.get("visitas_7d")
        v_txt = str(v) if v is not None else "n/d"
        c = row.get("conversao_pct")
        c_txt = f"{c}%" if c is not None else "n/d"
        marca = "🔴" if row.get("critica") else "•"
        linhas.append(
            f"{marca} {tit} — vis {v_txt} → {_i(row.get('unidades_pedidos'))} un "
            f"({c_txt}) | {row.get('acao_rotulo')}"
        )
        iid = str(row.get("item_id") or "").strip()
        if iid:
            linhas.append(f"  `{iid}` → _{row.get('motivo')}_")
    return linhas


def emitir_metricas_acoes_funil(prefixo: str, acoes: dict[str, Any] | None) -> None:
    pref = str(prefixo or "").strip().strip(".")
    if not pref or not acoes:
        return
    gauge(f"{pref}.funil.acoes_total", float(len(acoes.get("acoes") or [])))
    gauge(f"{pref}.funil.acoes_criticas", float(_i(acoes.get("criticas"))))
    por = acoes.get("por_acao") or {}
    for chave in (
        "baixar_preco_ou_listing",
        "melhorar_conversao_listing",
        "melhorar_titulo_e_ads",
        "republicar_ou_ads",
        "escalar_ou_manter",
        "aguardar_amostra",
    ):
        gauge(f"{pref}.funil.acao.{chave}", float(por.get(chave) or 0))


def processar_e_persistir_acoes(
    funil: dict[str, Any] | None,
    *,
    contexto: str = "funil_ml",
    prefixo_metricas: str | None = None,
    enviar_alerta_criticas: bool = False,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """
    Gera ações do funil, persiste fila, emite métricas e (opcional) alerta críticas.
    """
    from core.config import (
        FUNIL_ML_ACOES_ALERTA,
        FUNIL_ML_ACOES_COOLDOWN_SEG,
        FUNIL_ML_ACOES_MAX,
        FUNIL_ML_CONV_BAIXA_PCT,
        FUNIL_ML_CONV_BOA_PCT,
        FUNIL_ML_MIN_VISITAS_CONV,
        FUNIL_ML_VISITAS_ALTAS,
    )

    acoes = gerar_acoes_funil(
        funil,
        visitas_altas=FUNIL_ML_VISITAS_ALTAS,
        min_visitas_conv=FUNIL_ML_MIN_VISITAS_CONV,
        conv_baixa_pct=FUNIL_ML_CONV_BAIXA_PCT,
        conv_boa_pct=FUNIL_ML_CONV_BOA_PCT,
        max_acoes=FUNIL_ML_ACOES_MAX,
        contexto=contexto,
    )
    persistir_acoes_funil(acoes)
    if prefixo_metricas:
        emitir_metricas_acoes_funil(prefixo_metricas, acoes)

    alerta_enviado = False
    if (
        enviar_alerta_criticas
        and FUNIL_ML_ACOES_ALERTA
        and acoes.get("ok")
        and _i(acoes.get("criticas")) > 0
    ):
        try:
            from core.notificador import (
                alertar_gestor,
                chave_resumo_periodo,
                gestor_telegram_configurado,
            )

            if gestor_telegram_configurado(chat_id):
                linhas = [
                    f"🔴 *Funil ML — {_i(acoes.get('criticas'))} ação(ões) crítica(s)*",
                    f"Contexto: `{contexto}`",
                ]
                linhas.extend(formatar_secao_acoes_funil(acoes, top_n=6))
                linhas.append("")
                linhas.append(
                    "_Próximo:_ otimizador_listing prioriza estes IDs; "
                    "sem_venda/ads cobrem tráfego e preço."
                )
                alerta_enviado = bool(
                    alertar_gestor(
                        "\n".join(linhas).strip(),
                        chave=chave_resumo_periodo(
                            f"funil_acoes:{contexto}",
                            horas_por_bucket=max(1, FUNIL_ML_ACOES_COOLDOWN_SEG // 3600),
                        ),
                        cooldown_segundos=FUNIL_ML_ACOES_COOLDOWN_SEG,
                        agente_id="funil_ml_acoes",
                        chat_id=chat_id,
                    )
                )
        except Exception as exc:
            logger.warning("alerta acoes funil: %s", exc)
    acoes["alerta_enviado"] = alerta_enviado
    return acoes
