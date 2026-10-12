"""
integracoes/filamentos/golpe_guerra_masterprint.py
Golpe da frente PETG no CNPJ Masterprint. Telegram só no disparo. Não altera preço.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import GOLPE_GUERRA_CLAUDE, ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.golpe_guerra_impala import fallback_fazer
from integracoes.esmaltes.golpe_guerra_impala import montar_golpe as _montar
from integracoes.filamentos.doutrina_guerra_masterprint import (
    CNPJ_MASTERPRINT,
    TAGS_CNPJ,
    carregar_doutrina,
)

logger = logging.getLogger("golpe_guerra_masterprint")

SNAPSHOT_PATH = ROOT / "logs" / "golpe_guerra_masterprint_ultima.json"
PREFIXO = "masterprint.guerra"


def montar_golpe(
    batalha: dict[str, Any] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = _montar(
        batalha,
        produtos=produtos,
        doutrina=carregar_doutrina(),
    )
    payload["ramo"] = "masterprint"
    payload["cnpj"] = CNPJ_MASTERPRINT
    return payload


def emitir_metricas_golpe(payload: dict[str, Any] | None) -> None:
    data = payload if isinstance(payload, dict) else {}
    golpe = data.get("golpe") if isinstance(data.get("golpe"), dict) else {}
    classif = str(golpe.get("classificacao") or "nenhum")
    tags = list(TAGS_CNPJ) + [
        f"classif:{classif}",
        f"arma:{golpe.get('arma') or 'nenhuma'}",
    ]
    if golpe.get("kit_tag"):
        tags.append(str(golpe["kit_tag"]))
    gauge(f"{PREFIXO}.golpe_disparar", 1.0 if data.get("disparar") else 0.0, tags=tags)
    gauge(f"{PREFIXO}.golpe_score", float(golpe.get("score") or 0), tags=tags)
    incrementar(f"{PREFIXO}.golpe_rodadas", tags=tags)
    if data.get("disparar"):
        incrementar(f"{PREFIXO}.golpe_disparos", tags=tags)


def sintetizar_golpe_claude(payload: dict[str, Any]) -> str:
    if not GOLPE_GUERRA_CLAUDE or not payload.get("disparar"):
        return ""
    golpe = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    fallback = fallback_fazer(golpe)
    try:
        from core.claude_ml.dosagem import SYSTEM_GUERRA
        from core.resumo_ia import sintetizar_claude

        return sintetizar_claude(
            (
                "Classifique este golpe da frente PETG Masterprint (2º CNPJ). "
                "Uma classificação, um FAZER, duas recusas, uma arma. "
                "Não invente número fora do JSON."
            ),
            {
                "golpe": golpe,
                "frente": payload.get("frente"),
                "cnpj": CNPJ_MASTERPRINT,
            },
            fallback,
            max_tokens=180,
            origem="golpe_guerra_masterprint",
            proposito="guerra_filamento",
            system=SYSTEM_GUERRA,
            temperature=0.0,
        )
    except Exception as exc:
        logger.info("Claude golpe masterprint: %s", exc)
        return fallback


def formatar_mensagem_golpe(payload: dict[str, Any], *, texto_ia: str = "") -> str:
    from core.telegram_explicacao import cabecalho_agente

    g = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    classif = str(g.get("classificacao") or "ignorar")
    linhas = [
        cabecalho_agente("golpe_guerra_masterprint", "⚔ *Masterprint — golpe PETG*"),
        f"CNPJ `{CNPJ_MASTERPRINT}`",
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
    linhas.append(
        "_Não altera preço sozinho. Só PETG Branco (231020002) iguala na faixa._"
    )
    return "\n".join(linhas)


def processar_golpe_batalha(
    batalha: dict[str, Any] | None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    enviar_alerta: bool = False,
) -> dict[str, Any]:
    try:
        payload = montar_golpe(batalha, produtos=produtos)
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()
        emitir_metricas_golpe(payload)
        texto_ia = sintetizar_golpe_claude(payload)
        if texto_ia:
            payload["resumo_claude"] = texto_ia
        payload["mensagem"] = formatar_mensagem_golpe(payload, texto_ia=texto_ia)
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception as exc:
            logger.warning("snapshot golpe masterprint: %s", exc)
        if enviar_alerta and payload.get("disparar"):
            payload["alerta_enviado"] = _alertar_golpe(payload)
        else:
            payload["alerta_enviado"] = False
        return payload
    except Exception as exc:
        logger.warning("processar_golpe_batalha masterprint: %s", exc)
        incrementar("masterprint.guerra.golpe_erro")
        return {"ok": False, "erro": str(exc), "disparar": False, "golpe": None}


def processar_de_snapshot_batalha(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or "logs/filamentos_batalha_ultima.json")
    data = ler_json(path, default={})
    if not isinstance(data, dict):
        return {"ok": False, "erro": "snapshot_invalido", "disparar": False}
    batalha = data.get("batalha") if isinstance(data.get("batalha"), dict) else data
    return processar_golpe_batalha(batalha)


def _alertar_golpe(payload: dict[str, Any]) -> bool:
    from core.config import (
        GOLPE_GUERRA_MASTERPRINT_ALERTA,
        GOLPE_GUERRA_MASTERPRINT_ATIVO,
        GOLPE_GUERRA_MASTERPRINT_COOLDOWN_SEG,
    )
    from core.notificador import alertar_gestor, gestor_telegram_configurado
    from core.prontidao import pode_alertar_esmaltes
    from integracoes.masterprint.ramo import chat_gestor_masterprint

    if not GOLPE_GUERRA_MASTERPRINT_ATIVO or not GOLPE_GUERRA_MASTERPRINT_ALERTA:
        return False
    pode, motivo = pode_alertar_esmaltes()
    if not pode:
        logger.warning("Telegram bloqueado: %s", motivo)
        return False
    chat_mp = chat_gestor_masterprint()
    if not gestor_telegram_configurado(chat_mp):
        return False
    golpe = payload.get("golpe") if isinstance(payload.get("golpe"), dict) else {}
    sku = str(golpe.get("sku") or "x")
    classif = str(golpe.get("classificacao") or "x")
    return bool(
        alertar_gestor(
            payload.get("mensagem") or "",
            chave=f"golpe_guerra_mp:{sku}:{classif}",
            cooldown_segundos=GOLPE_GUERRA_MASTERPRINT_COOLDOWN_SEG,
            agente_id="golpe_guerra_masterprint",
            chat_id=chat_mp,
        )
    )
