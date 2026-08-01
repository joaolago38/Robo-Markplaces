"""
integracoes/ml/contrato_impulso_ml.py
Contrato único: o que pode receber ads/promo/impulso no ML.

Fonte: decisão do dia (SKUs guerra) + identidade MLB válida.
Fail-closed: sem MLB real → não impulsiona.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import (
    CONTRATO_IMPULSO_ML_ATIVO,
    DECISAO_DIA_ESMALTES_GUERRA_CATALOGO,
    ROOT,
)
from integracoes.esmaltes.crescimento_esmaltes import _item_id_ml, _mlb_valido
from integracoes.esmaltes.decisao_dia_esmaltes import (
    avaliar_skus_guerra,
    carregar_skus_guerra,
)

logger = logging.getLogger("contrato_impulso_ml")

DECISAO_PATH = ROOT / "logs" / "decisao_dia_esmaltes_ultima.json"
CONTRATO_PATH = ROOT / "logs" / "contrato_impulso_ml_ultima.json"


def identidade_ml_ok(produto: dict[str, Any] | None) -> bool:
    if not produto:
        return False
    return _mlb_valido(_item_id_ml(produto))


def _produto_por_sku(sku: str, produtos: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    alvo = (sku or "").strip().upper()
    if not alvo:
        return None
    for p in produtos if produtos is not None else carregar_produtos_catalogo():
        if str(p.get("sku") or "").strip().upper() == alvo:
            return p
    return None


def montar_contrato(
    *,
    margem_piso_pct: float = 15.0,
    forcar_recalculo: bool = False,
) -> dict[str, Any]:
    """
    Contrato do dia: SKUs liberados para impulso + bloqueios.
    Preferência: snapshot decisão do dia; senão recalcula guerra.
    """
    if not CONTRATO_IMPULSO_ML_ATIVO:
        return {
            "ok": True,
            "ativo": False,
            "motivo": "contrato_desligado",
            "liberados": [],
            "bloqueados": [],
            "skus_liberados": set(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    produtos = carregar_produtos_catalogo()
    guerra = carregar_skus_guerra(DECISAO_DIA_ESMALTES_GUERRA_CATALOGO)
    status = avaliar_skus_guerra(
        guerra=guerra, produtos=produtos, margem_piso_pct=margem_piso_pct
    )

    # Se há snapshot fresco da decisão, alinhar códigos
    snap = {} if forcar_recalculo else ler_json(DECISAO_PATH, default={})
    if isinstance(snap, dict) and snap.get("skus_guerra"):
        status = snap["skus_guerra"]

    liberados = [s for s in status if isinstance(s, dict) and s.get("pode_impulsionar")]
    bloqueados = [s for s in status if isinstance(s, dict) and not s.get("pode_impulsionar")]

    fazer = (snap.get("fazer") if isinstance(snap, dict) else None) or {}
    nao_fazer = (snap.get("nao_fazer") if isinstance(snap, dict) else None) or {}

    contrato = {
        "ok": True,
        "ativo": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fonte_decisao": bool(isinstance(snap, dict) and snap.get("skus_guerra")),
        "fazer": fazer,
        "nao_fazer": nao_fazer,
        "liberados": liberados,
        "bloqueados": bloqueados,
        "skus_liberados": [str(s.get("sku") or "").upper() for s in liberados],
        "item_ids_liberados": [
            str(s.get("item_id") or "").upper()
            for s in liberados
            if _mlb_valido(str(s.get("item_id") or ""))
        ],
        "regras": [
            "Só SKUs de guerra com MLB + margem + diferencial",
            "Sem MLB → fail-closed (sem ads/promo)",
            "Fora da lista de guerra → sem impulso pago",
        ],
    }
    # Persist sem set (JSON)
    payload = dict(contrato)
    escrever_json_atomico(CONTRATO_PATH, payload)
    return contrato


def carregar_contrato(*, refresh: bool = False) -> dict[str, Any]:
    if not refresh:
        data = ler_json(CONTRATO_PATH, default={})
        if isinstance(data, dict) and data.get("ok") and data.get("timestamp"):
            return data
    return montar_contrato()


def sku_pode_impulsionar(sku: str, *, contrato: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Fail-closed: só libera se contrato ativo e SKU na lista liberados."""
    c = contrato if contrato is not None else carregar_contrato()
    if not c.get("ativo", True):
        # contrato desligado = não bloqueia (compat)
        p = _produto_por_sku(sku)
        if identidade_ml_ok(p):
            return True, "contrato_desligado_mlb_ok"
        return False, "contrato_desligado_sem_mlb"
    alvo = (sku or "").strip().upper()
    if not alvo:
        return False, "sku_vazio"
    if alvo in {str(x).upper() for x in (c.get("skus_liberados") or [])}:
        return True, "liberado_guerra"
    # Em guerra mas bloqueado?
    for b in c.get("bloqueados") or []:
        if str(b.get("sku") or "").upper() == alvo:
            return False, "bloqueado:" + ",".join(b.get("bloqueios") or ["guerra"])
    return False, "fora_skus_guerra"


def campanha_pode_enviar(sku: str, *, link_valido: bool, contrato: dict[str, Any] | None = None) -> tuple[bool, str]:
    if not link_valido:
        return False, "link_mlb_invalido"
    ok, motivo = sku_pode_impulsionar(sku, contrato=contrato)
    if ok:
        return True, motivo
    # Promoções: se contrato exige guerra, bloqueia; se SKU não é guerra mas tem MLB,
    # ainda bloqueia para não diluir (regra de foco).
    return False, motivo


def ads_pode_ligar(*, contrato: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Product Ads só se houver ao menos 1 SKU guerra liberado."""
    c = contrato if contrato is not None else carregar_contrato()
    if not c.get("ativo", True):
        return True, "contrato_desligado"
    liberados = c.get("skus_liberados") or []
    if liberados:
        return True, f"liberados={len(liberados)}"
    return False, "nenhum_sku_guerra_liberado"


def listar_item_ids_para_otimizacao(*, contrato: dict[str, Any] | None = None) -> list[str]:
    """Prioriza itens liberados; senão vazia (fail-closed para apply)."""
    c = contrato if contrato is not None else carregar_contrato()
    return [str(i) for i in (c.get("item_ids_liberados") or []) if i]
