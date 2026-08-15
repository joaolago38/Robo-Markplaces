"""
integracoes/esmaltes/golpe_guerra_impala.py
Compila o golpe da frente Impala: um FAZER + uma arma. Claude só no disparo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import GOLPE_GUERRA_CLAUDE, ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.doutrina_guerra_impala import (
    carregar_doutrina,
    classificar_golpe,
    frente_skus,
)
from integracoes.esmaltes.metricas_catalogo_impala import kit_tag

logger = logging.getLogger("golpe_guerra_impala")

SNAPSHOT_PATH = ROOT / "logs" / "golpe_guerra_impala_ultima.json"


def _produto_por_sku(sku: str, produtos: list[dict[str, Any]]) -> dict[str, Any] | None:
    alvo = (sku or "").strip().upper()
    for p in produtos:
        if isinstance(p, dict) and str(p.get("sku") or "").strip().upper() == alvo:
            return p
    return None


def montar_golpe(
    batalha: dict[str, Any] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    doutrina: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Escolhe o golpe de maior prioridade na frente. Nunca lança."""
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    bat = batalha if isinstance(batalha, dict) else {}
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    golpes: list[dict[str, Any]] = []
    for c in bat.get("comparacoes") or []:
        if not isinstance(c, dict):
            continue
        sku = str(c.get("sku") or "").strip().upper()
        if sku and not c.get("kit_tag"):
            c = {**c, "kit_tag": kit_tag(sku)}
        row = classificar_golpe(c, produto=_produto_por_sku(sku, prods), doutrina=d)
        if row:
            golpes.append(row)
    golpes.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    top = golpes[0] if golpes else None
    disparar = bool(top and top.get("disparar"))
    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "doutrina": str(d.get("nome") or "guerra_por_faixa"),
        "frente": sorted(frente_skus(d)),
        "disparar": disparar,
        "golpe": top,
        "golpes": golpes,
        "n_frente": len(golpes),
    }


def emitir_metricas_golpe(payload: dict[str, Any] | None) -> None:
    data = payload if isinstance(payload, dict) else {}
    golpe = data.get("golpe") if isinstance(data.get("golpe"), dict) else {}
    classif = str(golpe.get("classificacao") or "nenhum")
    tags = [f"classif:{classif}", f"arma:{golpe.get('arma') or 'nenhuma'}"]
    if golpe.get("kit_tag"):
        tags.append(str(golpe["kit_tag"]))
    gauge("impala.guerra.golpe_disparar", 1.0 if data.get("disparar") else 0.0, tags=tags)
    gauge("impala.guerra.golpe_score", float(golpe.get("score") or 0), tags=tags)
    incrementar("impala.guerra.golpe_rodadas", tags=tags)
    if data.get("disparar"):
        incrementar("impala.guerra.golpe_disparos", tags=tags)


def fallback_fazer(golpe: dict[str, Any] | None) -> str:
    g = golpe if isinstance(golpe, dict) else {}
    sku = g.get("sku") or "n/d"
    classif = str(g.get("classificacao") or "ignorar").upper()
    return (
        f"FAZER: {g.get('fazer') or 'observar'}\n"
        f"NÃO FAZER: {g.get('nao_fazer') or 'perseguir dump'}\n"
        f"Classificação: {classif} · SKU `{sku}` · arma {g.get('arma') or 'observar'}"
    )


def sintetizar_golpe_claude(payload: dict[str, Any]) -> str:
    """Claude só quando há golpe a disparar. SYSTEM_GUERRA. Nunca inventa."""
    if not GOLPE_GUERRA_CLAUDE or not payload.get("disparar"):
        return ""
    golpe = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    fallback = fallback_fazer(golpe)
    try:
        from core.claude_ml.dosagem import SYSTEM_GUERRA
        from core.resumo_ia import sintetizar_claude

        return sintetizar_claude(
            (
                "Classifique este golpe da frente Impala. "
                "Uma classificação, um FAZER, duas recusas, uma arma. "
                "Não invente número fora do JSON."
            ),
            {
                "golpe": golpe,
                "frente": payload.get("frente"),
                "cnpj": "52.668.583/0001-27",
            },
            fallback,
            max_tokens=180,
            origem="golpe_guerra_impala",
            proposito="guerra_impala",
            system=SYSTEM_GUERRA,
            temperature=0.0,
        )
    except Exception as exc:
        logger.info("Claude golpe guerra: %s", exc)
        return fallback


def formatar_mensagem_golpe(payload: dict[str, Any], *, texto_ia: str = "") -> str:
    from core.telegram_explicacao import cabecalho_agente

    g = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    classif = str(g.get("classificacao") or "ignorar")
    titulo = (
        "*IMPALA ON* — golpe da guerra"
        if payload.get("visao_operacional")
        else "⚔ *Impala — golpe da guerra*"
    )
    linhas = [
        cabecalho_agente("golpe_guerra_impala", titulo),
        f"Classificação: *{classif}*",
        f"SKU: `{g.get('sku') or 'n/d'}` · arma *{g.get('arma') or 'observar'}*",
        f"FAZER: {g.get('fazer') or '—'}",
        f"NÃO FAZER: {g.get('nao_fazer') or '—'}",
    ]
    if g.get("rival_min") is not None:
        linhas.append(
            f"_Rival ao vivo R$ {float(g['rival_min']):.2f} · "
            f"nosso R$ {float(g.get('nosso_preco') or 0):.2f} · "
            f"piso R$ {float(g.get('piso_preco') or 0):.2f}_"
        )
    if texto_ia:
        linhas.extend(["", texto_ia.strip()])
    linhas.append("_Não altera preço sozinho. PERL é o único kit que iguala na faixa._")
    return "\n".join(linhas)


def processar_golpe_batalha(
    batalha: dict[str, Any] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    """Monta, persiste, métricas, Claude no disparo. Nunca lança."""
    try:
        payload = montar_golpe(batalha, produtos=produtos)
        if isinstance(batalha, dict) and batalha.get("visao_operacional"):
            payload["visao_operacional"] = True
            payload["disparar"] = False
            payload["overlay_sem_golpe"] = True
        emitir_metricas_golpe(payload)
        texto_ia = sintetizar_golpe_claude(payload)
        if texto_ia:
            payload["resumo_claude"] = texto_ia
        payload["mensagem"] = formatar_mensagem_golpe(payload, texto_ia=texto_ia)
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception as exc:
            logger.warning("snapshot golpe: %s", exc)
        if enviar_alerta and payload.get("disparar"):
            payload["alerta_enviado"] = _alertar_golpe(payload)
        else:
            payload["alerta_enviado"] = False
        return payload
    except Exception as exc:
        logger.warning("processar_golpe_batalha: %s", exc)
        incrementar("impala.guerra.golpe_erro")
        return {"ok": False, "erro": str(exc), "disparar": False, "golpe": None}


def _alertar_golpe(payload: dict[str, Any]) -> bool:
    from core.config import (
        GOLPE_GUERRA_IMPALA_ALERTA,
        GOLPE_GUERRA_IMPALA_ATIVO,
        GOLPE_GUERRA_IMPALA_COOLDOWN_SEG,
    )
    from core.notificador import alertar_gestor, gestor_telegram_configurado
    from core.prontidao import pode_alertar_esmaltes

    if not GOLPE_GUERRA_IMPALA_ATIVO or not GOLPE_GUERRA_IMPALA_ALERTA:
        return False
    pode, motivo = pode_alertar_esmaltes()
    if not pode:
        logger.warning("Telegram esmaltes bloqueado: %s", motivo)
        return False
    if not gestor_telegram_configurado():
        return False
    golpe = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    sku = str(golpe.get("sku") or "x")
    classif = str(golpe.get("classificacao") or "x")
    return bool(
        alertar_gestor(
            payload.get("mensagem") or "",
            chave=f"golpe_guerra:{sku}:{classif}",
            cooldown_segundos=GOLPE_GUERRA_IMPALA_COOLDOWN_SEG,
            agente_id="golpe_guerra_impala",
        )
    )


def processar_de_snapshot_batalha(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or "logs/impala_batalha_ultima.json")
    data = ler_json(path, default={})
    if not isinstance(data, dict):
        return {"ok": False, "erro": "snapshot_invalido", "disparar": False}
    batalha = data.get("batalha") if isinstance(data.get("batalha"), dict) else data
    return processar_golpe_batalha(batalha)
