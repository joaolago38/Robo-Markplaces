"""
integracoes/ml/referencia_copy_legado.py
Bolsas/legado da conta como referência de COPY (estrutura de título),
não como catálogo operacional.

Ruptura/foco continuam ignorando esses anúncios.
Aqui eles ensinam como o algoritmo desta conta já impulsiona busca:
ordem das palavras, densidade, uso dos 60 caracteres.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge
from integracoes.ml.filtro_anuncios_conta import (
    carregar_regras_ignorar,
    filtrar_anuncios_legado,
    palavras_nao_transferir,
)

logger = logging.getLogger("referencia_copy_legado")

SNAPSHOT_PATH = ROOT / "logs" / "referencia_copy_legado_ultima.json"

_SYSTEM_PADROES = (
    "Você extrai padrões de COPY de anúncios de bolsas/legado DESTA conta ML "
    "que já vendem. O objetivo é transferir ESTRUTURA de título para kits Impala "
    "(esmalte), não o produto. Nunca sugira palavras de bolsa, couro, mariart, "
    "shopper, transversal, carteira, sapato ou scarpin em título de esmalte. "
    "Foque em: substantivo de busca na frente, atributo, marca, público, "
    "preencher ~60 caracteres sem emoji/pontuação. Cite evidência nos títulos."
)

_SCHEMA_PADROES = {
    "type": "object",
    "properties": {
        "estrutura": {
            "type": "string",
            "description": "Fórmula curta da ordem das palavras no título.",
        },
        "regras": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "regra": {"type": "string"},
                    "evidencia": {"type": "string"},
                },
                "required": ["regra"],
            },
        },
        "aviso": {
            "type": "string",
            "description": "Lembrete de não copiar o produto bolsa.",
        },
    },
    "required": ["estrutura", "regras"],
}


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _titulo(anuncio: dict[str, Any]) -> str:
    return str(anuncio.get("titulo") or anuncio.get("family_name") or "").strip()


def extrair_padroes_titulo(
    anuncios: list[dict[str, Any]],
    *,
    top_n: int = 12,
) -> dict[str, Any]:
    """Estatística determinística dos títulos legado (sem Claude)."""
    rows = [a for a in anuncios if isinstance(a, dict) and _titulo(a)]
    rows.sort(key=lambda a: (-_i(a.get("sold_quantity")), _titulo(a)))
    n = len(rows)
    lens = [len(_titulo(a)) for a in rows]
    cheios = sum(1 for c in lens if c >= 50)
    top = [
        {
            "item_id": str(a.get("item_id") or ""),
            "titulo": _titulo(a)[:60],
            "vendidos": _i(a.get("sold_quantity")),
            "status": str(a.get("status") or ""),
            "chars": len(_titulo(a)),
        }
        for a in rows[: max(1, int(top_n or 12))]
    ]
    return {
        "n": n,
        "chars_medio": round(sum(lens) / n, 1) if n else 0.0,
        "chars_max": max(lens) if lens else 0,
        "pct_titulo_cheio": round(100.0 * cheios / n, 1) if n else 0.0,
        "top": top,
        "nao_transferir": palavras_nao_transferir(),
    }


def analisar_padroes_com_claude(padroes: dict[str, Any]) -> dict[str, Any] | None:
    """Claude lê os títulos que vendem e devolve regras de estrutura."""
    top = padroes.get("top") or []
    if not top:
        return None
    linhas = [
        f"{i}. {_titulo(t) or t.get('titulo')} | vendidos={t.get('vendidos')} | chars={t.get('chars')}"
        for i, t in enumerate(top, start=1)
        if isinstance(t, dict)
    ]
    if not linhas:
        return None
    try:
        from core.claude_client import perguntar_estruturado

        ctx = (
            "Títulos legado/bolsa desta conta (amostra por vendas):\n"
            + "\n".join(linhas)
            + "\nNão transferir para Impala: "
            + ", ".join(padroes.get("nao_transferir") or [])
        )
        out = perguntar_estruturado(
            "Extraia a estrutura de título que o algoritmo ML desta conta já recompensa. "
            "Regras transferíveis para kit de esmalte Impala. Sem palavras de bolsa.",
            _SCHEMA_PADROES,
            tool_name="registrar_padroes_copy_legado",
            max_tokens=500,
            contexto=ctx,
            system=_SYSTEM_PADROES,
            origem="ml.referencia_copy_legado",
            exigir_contexto=True,
        )
        return out if isinstance(out, dict) else None
    except Exception as exc:
        logger.warning("Claude padrões copy legado: %s", exc)
        return None


def montar_bloco_contexto(ref: dict[str, Any] | None) -> str:
    """Texto para o Claude do otimizador de listing."""
    if not isinstance(ref, dict) or _i(ref.get("n")) <= 0:
        return ""
    linhas = [
        "=== REFERÊNCIA DE COPY DA CONTA (bolsas/legado que já vendem) ===",
        "Use só a ESTRUTURA (ordem, densidade de busca, ~60 caracteres, público). "
        "NÃO copie o produto bolsa para esmalte Impala.",
        (
            f"Amostra: {ref.get('n')} anúncios · chars médio {ref.get('chars_medio')} · "
            f"{ref.get('pct_titulo_cheio')}% com título ≥50 caracteres"
        ),
        "Não transferir: " + ", ".join(ref.get("nao_transferir") or []),
        "",
        "Top por vendas:",
    ]
    for i, t in enumerate(ref.get("top") or [], start=1):
        if not isinstance(t, dict):
            continue
        linhas.append(
            f"{i}. {t.get('titulo')} | vendidos={t.get('vendidos')} | chars={t.get('chars')}"
        )
    claude = ref.get("regras_claude") if isinstance(ref.get("regras_claude"), dict) else {}
    if claude.get("estrutura"):
        linhas.extend(["", f"Estrutura (Claude): {claude.get('estrutura')}"])
    for regra in claude.get("regras") or []:
        if not isinstance(regra, dict) or not regra.get("regra"):
            continue
        ev = str(regra.get("evidencia") or "").strip()
        linhas.append(f"- {regra.get('regra')}" + (f" (ex.: {ev})" if ev else ""))
    if claude.get("aviso"):
        linhas.append(str(claude.get("aviso")))
    return "\n".join(linhas)


def bloco_contexto_salvo() -> str:
    snap = ler_json(SNAPSHOT_PATH, default={})
    return montar_bloco_contexto(snap if isinstance(snap, dict) else {})


def coletar_referencia_copy_legado(
    *,
    ao_vivo: bool = True,
    usar_claude: bool = True,
    top_n: int = 12,
) -> dict[str, Any]:
    """
    Lista bolsas/legado (aplicar_foco=False), extrai padrões e opcionalmente
    pede regras ao Claude. Snapshot em logs/. Nunca lança.
    """
    anuncios: list[dict[str, Any]] = []
    fonte = "vazio"
    if ao_vivo:
        try:
            from integracoes.ml import ml_client

            todos = ml_client.listar_meus_anuncios(
                statuses=("active", "paused"),
                aplicar_foco=False,
            )
            anuncios, _ = filtrar_anuncios_legado(todos, regras=carregar_regras_ignorar())
            if anuncios:
                fonte = "ml_ao_vivo"
        except Exception as exc:
            logger.warning("listar legado copy: %s", exc)
    if not anuncios:
        snap = ler_json(SNAPSHOT_PATH, default={})
        if isinstance(snap, dict) and _i(snap.get("n")) > 0:
            fonte = str(snap.get("fonte") or "snapshot")
            try:
                gauge("ml.listing.referencia_legado", float(_i(snap.get("n"))))
            except Exception:
                pass
            return snap

    padroes = extrair_padroes_titulo(anuncios, top_n=top_n)
    regras_claude = analisar_padroes_com_claude(padroes) if usar_claude else None
    payload = {
        "ok": padroes["n"] > 0,
        "fonte": fonte,
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        **padroes,
        "regras_claude": regras_claude,
    }
    try:
        escrever_json_atomico(SNAPSHOT_PATH, payload)
    except Exception as exc:
        logger.warning("snapshot copy legado: %s", exc)
    try:
        gauge("ml.listing.referencia_legado", float(padroes["n"]))
        gauge("ml.listing.referencia_legado_claude", 1.0 if regras_claude else 0.0)
    except Exception:
        pass
    return payload


_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9]+")


def titulo_tem_palavra_bolsa(titulo: str, stop: list[str] | None = None) -> bool:
    """True se o título Impala copiou palavra de bolsa/legado."""
    toks = {t.lower() for t in _TOKEN.findall(titulo or "")}
    bloqueio = stop if stop is not None else palavras_nao_transferir()
    for raw in bloqueio:
        n = str(raw or "").strip().lower()
        if not n:
            continue
        if " " in n:
            if n in (titulo or "").lower():
                return True
        elif n in toks:
            return True
    return False
