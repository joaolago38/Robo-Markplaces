"""
core/empresa/contas_masterprint.py
Grava seller/shop da Masterprint no catálogo somente quando o ID veio
do ambiente e não é a conta da Impala. Não inventa ID.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.empresa.marketplace import norm_marketplace

_CANAIS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...]]] = {
    # marketplace: (bloco_json, chave, envs_masterprint, envs_impala)
    "mercadolivre": (
        "ml",
        "seller_id",
        ("MASTERPRINT_ML_SELLER_ID", "ML_SELLER_ID_MASTERPRINT"),
        ("ML_SELLER_ID",),
    ),
    "shopee": (
        "shopee",
        "shop_id",
        ("MASTERPRINT_SHOPEE_SHOP_ID",),
        ("SHOPEE_SHOP_ID",),
    ),
    "magalu": (
        "magalu",
        "seller_id",
        ("MASTERPRINT_MAGALU_SELLER_ID",),
        ("MAGALU_SELLER_ID",),
    ),
    "amazon": (
        "amazon",
        "seller_id",
        ("MASTERPRINT_AMAZON_SELLER_ID",),
        ("AMAZON_SELLER_ID",),
    ),
}


def _vivo(*nomes: str) -> str:
    import core.config as cfg

    for nome in nomes:
        v = os.getenv(nome, "").strip()
        if v:
            return v
    for nome in nomes:
        v = str(getattr(cfg, nome, "") or "").strip()
        if v:
            return v
    return ""


def _empresa(doc: dict[str, Any], empresa_id: str) -> dict[str, Any] | None:
    for emp in doc.get("empresas") or []:
        if isinstance(emp, dict) and str(emp.get("id") or "") == empresa_id:
            return emp
    return None


def ids_impala_no_documento(doc: dict[str, Any], marketplace: str) -> set[str]:
    mp = norm_marketplace(marketplace)
    bloco, chave, _mp_envs, imp_envs = _CANAIS[mp]
    ids = {_vivo(nome) for nome in imp_envs}
    impala = _empresa(doc, "esmaltes_impala") or {}
    cat = impala.get(bloco) if isinstance(impala.get(bloco), dict) else {}
    ids.add(str((cat or {}).get(chave) or "").strip())
    return {i for i in ids if i}


def coletar_contas_env() -> dict[str, str]:
    """IDs Masterprint presentes no ambiente. Canal sem secret fica de fora."""
    out: dict[str, str] = {}
    for mp, (_bloco, _chave, envs, _imp) in _CANAIS.items():
        valor = _vivo(*envs)
        if valor:
            out[mp] = valor
    nick = _vivo("MASTERPRINT_ML_NICKNAME")
    if nick:
        out["nickname"] = nick
    return out


def gravar_contas_distintas(
    caminho_catalogo: Path | str | None = None,
    caminho_ramo: Path | str | None = None,
) -> dict[str, Any]:
    """
    Persiste no JSON só IDs Masterprint não vazios e diferentes da Impala.
    ID igual ao da Impala entra em recusados e não é gravado.
    """
    from core.atomic_io import escrever_json_atomico
    from core.empresa.catalogo import limpar_cache_empresas

    path = Path(caminho_catalogo or (ROOT / "catalogo" / "empresas_cnae_cnpj.json"))
    doc = ler_json(path, default={})
    if not isinstance(doc, dict):
        return {"ok": False, "motivo": "catalogo_invalido", "gravados": {}, "recusados": {}}

    master = _empresa(doc, "masterprint")
    if master is None:
        return {"ok": False, "motivo": "sem_masterprint", "gravados": {}, "recusados": {}}

    contas = coletar_contas_env()
    gravados: dict[str, str] = {}
    recusados: dict[str, str] = {}
    for mp, (bloco, chave, _envs, _imp) in _CANAIS.items():
        valor = str(contas.get(mp) or "").strip()
        if not valor:
            continue
        if valor in ids_impala_no_documento(doc, mp):
            recusados[mp] = valor
            continue
        slot = master.get(bloco) if isinstance(master.get(bloco), dict) else {}
        slot = dict(slot)
        slot[chave] = valor
        master[bloco] = slot
        gravados[mp] = valor

    nick = str(contas.get("nickname") or "").strip()
    if nick and "mercadolivre" in gravados:
        ml = dict(master.get("ml") or {})
        if not str(ml.get("nickname") or "").strip():
            ml["nickname"] = nick
            master["ml"] = ml

    if gravados:
        escrever_json_atomico(path, doc)
        limpar_cache_empresas()
        padrao = (ROOT / "catalogo" / "empresas_cnae_cnpj.json").resolve()
        if caminho_ramo is not None:
            ramo_path: Path | None = Path(caminho_ramo)
        elif path.resolve() == padrao:
            ramo_path = ROOT / "catalogo" / "masterprint_ramo.json"
        else:
            ramo_path = None
        if ramo_path is not None and "mercadolivre" in gravados and ramo_path.is_file():
            ramo = ler_json(ramo_path, default={})
            if isinstance(ramo, dict):
                ramo["ml_seller_id"] = gravados["mercadolivre"]
                if nick and not str(ramo.get("ml_nickname") or "").strip():
                    ramo["ml_nickname"] = nick
                escrever_json_atomico(ramo_path, ramo)

    return {
        "ok": True,
        "gravados": gravados,
        "recusados": recusados,
        "sem_id": [mp for mp in _CANAIS if mp not in gravados and mp not in recusados],
    }
