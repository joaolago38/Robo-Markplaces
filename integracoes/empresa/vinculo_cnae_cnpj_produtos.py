"""
integracoes/empresa/vinculo_cnae_cnpj_produtos.py
Resolve CNAE → CNPJ → produtos e detecta alterações para monitoramento.

Foco: Mercado Livre (priário); demais marketplaces ficam abertos no perfil.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.empresa.cnpj_utils import digitos, formatar_cnpj, norm_cnae
from core.empresa_contexto import (
    empresa_por_cnpj,
    empresa_por_id,
    empresas_por_cnae,
    listar_empresas,
    situacao_dono_produtos,
)

logger = logging.getLogger("vinculo_cnae_cnpj")

SNAPSHOT_PATH = ROOT / "logs" / "monitor_cnpj_cnae_ultima.json"
MONITORADOS_PATH = ROOT / "logs" / "cnpjs_monitorados.json"
HISTORY_PATH = ROOT / "logs" / "monitor_cnpj_cnae_historico.json"

# Catálogos auxiliares por ramo (além de produtos.json)
_CATALOGOS_POR_RAMO: dict[str, tuple[str, ...]] = {
    "esmaltes": ("catalogo/produtos.json",),
    "manicures": ("catalogo/produtos.json",),
    "impala": ("catalogo/produtos.json",),
    "anita": ("catalogo/produtos.json",),
    "acetona": ("catalogo/acetona_cruzeiro_monitor.json",),
    "removedores": ("catalogo/removedores_unha_monitor.json",),
    "filamentos": (
        "catalogo/masterprint_petg_custos.json",
        "catalogo/masterprint_petg_monitor.json",
    ),
    "petg": (
        "catalogo/masterprint_petg_custos.json",
        "catalogo/masterprint_petg_monitor.json",
    ),
    "masterprint": (
        "catalogo/masterprint_petg_custos.json",
        "catalogo/masterprint_escritorio_custos.json",
    ),
    "escritorio": (
        "catalogo/masterprint_escritorio_custos.json",
        "catalogo/masterprint_escritorio_monitor.json",
    ),
    "demais_produtos": (
        "catalogo/masterprint_petg_custos.json",
        "catalogo/masterprint_escritorio_custos.json",
    ),
}


def _hash_obj(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def resolver_por_cnae(codigo: str) -> list[dict[str, Any]]:
    """Empresas/CNPJs que se encaixam no CNAE informado."""
    return list(empresas_por_cnae(codigo) or [])


def produtos_vinculados_ao_cnpj(cnpj: str) -> dict[str, Any]:
    """
    Produtos/catálogos ligados ao CNPJ:
      1) itens de produtos.json com cnpj_dono = este CNPJ (ou dono efetivo)
      2) catálogos auxiliares pelos ramos da empresa
    """
    cnpj_d = digitos(cnpj)
    emp = empresa_por_cnpj(cnpj_d) or {}
    dono = situacao_dono_produtos()
    eh_dono_efetivo = digitos(str(dono.get("cnpj_efetivo") or "")) == cnpj_d

    skus: list[dict[str, Any]] = []
    try:
        from core.catalogo_produtos import carregar_produtos_para_operacao

        for p in carregar_produtos_para_operacao(merge_bling=False):
            dono_p = digitos(str(p.get("cnpj_dono") or ""))
            if dono_p == cnpj_d or (eh_dono_efetivo and not dono_p):
                skus.append(
                    {
                        "sku": p.get("sku"),
                        "nome": str(p.get("nome") or "")[:80],
                        "cnpj_dono": dono_p or cnpj_d,
                    }
                )
    except Exception as exc:
        logger.debug("produtos.json: %s", exc)

    catalogos: list[str] = []
    for ramo in emp.get("ramos") or []:
        for path in _CATALOGOS_POR_RAMO.get(str(ramo).lower(), ()):
            if path not in catalogos and (ROOT / path).is_file():
                catalogos.append(path)

    # Se é dono efetivo dos produtos, garante produtos.json
    if eh_dono_efetivo and "catalogo/produtos.json" not in catalogos:
        if (ROOT / "catalogo/produtos.json").is_file():
            catalogos.insert(0, "catalogo/produtos.json")

    return {
        "cnpj": cnpj_d,
        "cnpj_formatado": formatar_cnpj(cnpj_d),
        "empresa_id": emp.get("id"),
        "total_skus": len(skus),
        "skus": skus[:40],
        "catalogos": catalogos,
        "eh_dono_produtos_efetivo": eh_dono_efetivo,
    }


def perfil_marketplace(empresa: dict[str, Any] | None) -> dict[str, Any]:
    """ML como foco; demais marketplaces abertos no perfil."""
    emp = empresa or {}
    mk = emp.get("marketplaces") if isinstance(emp.get("marketplaces"), dict) else {}
    foco = str(mk.get("foco_principal") or "mercadolivre")
    ativos = list(mk.get("ativos") or ["mercadolivre"])
    secundarios = list(mk.get("secundarios") or [])
    abertos = sorted({*ativos, *secundarios, "mercadolivre", "shopee", "magalu", "amazon"})
    return {
        "foco_principal": foco,
        "prioriza_mercadolivre": foco == "mercadolivre",
        "ativos": ativos,
        "secundarios": secundarios,
        "abertos_para_expansao": [m for m in abertos if m not in ativos],
        "ml": emp.get("ml") or {},
    }


def fingerprint_cnpj(empresa: dict[str, Any], produtos: dict[str, Any]) -> dict[str, Any]:
    """Assinatura do estado do CNPJ para detectar alteração."""
    cnaes = [
        {"codigo": c.get("codigo"), "principal": c.get("principal")}
        for c in (empresa.get("cnaes") or [])
    ]
    base = {
        "cnpj": empresa.get("cnpj"),
        "empresa_id": empresa.get("id"),
        "cnaes": cnaes,
        "ramos": sorted(empresa.get("ramos") or []),
        "agentes": sorted(empresa.get("agentes_prioritarios") or []),
        "marketplaces": perfil_marketplace(empresa),
        "produtos_total": produtos.get("total_skus"),
        "produtos_skus": sorted(str(s.get("sku") or "") for s in (produtos.get("skus") or [])),
        "catalogos": sorted(produtos.get("catalogos") or []),
        "dono_efetivo": produtos.get("eh_dono_produtos_efetivo"),
        "ml_seller": (empresa.get("ml") or {}).get("seller_id"),
        "telegram": empresa.get("telegram_gestor_chat_id"),
    }
    return {"assinatura": _hash_obj(base), "dados": base}


def montar_vinculo(
    *,
    cnae: str | None = None,
    cnpj: str | None = None,
    empresa_id: str | None = None,
) -> dict[str, Any]:
    """Monta o vínculo completo CNAE ↔ CNPJ ↔ produtos ↔ marketplaces."""
    empresas: list[dict[str, Any]] = []
    if empresa_id:
        emp = empresa_por_id(empresa_id)
        if emp:
            empresas = [emp]
    elif cnpj:
        emp = empresa_por_cnpj(cnpj)
        if emp:
            empresas = [emp]
    elif cnae:
        empresas = resolver_por_cnae(cnae)
    else:
        empresas = listar_empresas(apenas_ativas=True)

    vinculos = []
    for emp in empresas:
        prods = produtos_vinculados_ao_cnpj(str(emp.get("cnpj") or ""))
        fp = fingerprint_cnpj(emp, prods)
        cnae_p = emp.get("cnae_principal") or {}
        vinculos.append(
            {
                "empresa_id": emp.get("id"),
                "nome_fantasia": emp.get("nome_fantasia"),
                "cnpj": emp.get("cnpj"),
                "cnpj_formatado": emp.get("cnpj_formatado"),
                "cnae_consulta": norm_cnae(cnae) if cnae else None,
                "cnae_principal": cnae_p.get("codigo"),
                "cnae_descricao": cnae_p.get("descricao"),
                "cnaes": emp.get("cnaes") or [],
                "ramos": emp.get("ramos") or [],
                "agentes_prioritarios": emp.get("agentes_prioritarios") or [],
                "marketplaces": perfil_marketplace(emp),
                "produtos": prods,
                "fingerprint": fp,
            }
        )
    return {
        "ok": True,
        "filtro": {"cnae": cnae, "cnpj": digitos(cnpj or ""), "empresa_id": empresa_id},
        "total": len(vinculos),
        "vinculos": vinculos,
        "dono_produtos_global": situacao_dono_produtos(),
    }


def carregar_monitorados() -> dict[str, Any]:
    data = ler_json(MONITORADOS_PATH, default={})
    return data if isinstance(data, dict) else {}


def registrar_monitoramento(cnpj: str, motivo: str) -> dict[str, Any]:
    """Marca CNPJ como monitorado após alteração detectada."""
    cnpj_d = digitos(cnpj)
    data = carregar_monitorados()
    itens = data.get("cnpjs") if isinstance(data.get("cnpjs"), dict) else {}
    from core.horario import agora_brasil

    agora = agora_brasil().isoformat()
    prev = itens.get(cnpj_d) if isinstance(itens.get(cnpj_d), dict) else {}
    itens[cnpj_d] = {
        "cnpj": cnpj_d,
        "cnpj_formatado": formatar_cnpj(cnpj_d),
        "ativo": True,
        "motivo": motivo,
        "primeira_vez": prev.get("primeira_vez") or agora,
        "ultima_alteracao": agora,
        "alertas": int(prev.get("alertas") or 0) + 1,
    }
    data = {"cnpjs": itens, "atualizado_em": agora}
    escrever_json_atomico(MONITORADOS_PATH, data)
    return itens[cnpj_d]


def detectar_alteracoes(vinculos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compara fingerprint atual × snapshot anterior; registra monitoramento."""
    anterior = ler_json(SNAPSHOT_PATH, default={})
    ant_map = {}
    if isinstance(anterior, dict):
        for v in anterior.get("vinculos") or []:
            if isinstance(v, dict) and v.get("cnpj"):
                ant_map[digitos(str(v["cnpj"]))] = v

    mudancas = []
    for v in vinculos:
        cnpj_d = digitos(str(v.get("cnpj") or ""))
        if not cnpj_d:
            continue
        fp_novo = (v.get("fingerprint") or {}).get("assinatura")
        ant = ant_map.get(cnpj_d) or {}
        fp_ant = ((ant.get("fingerprint") or {}).get("assinatura"))
        primeira = not bool(ant)
        alterou = primeira or (fp_novo != fp_ant)
        if not alterou:
            continue
        motivo = "primeira_verificacao" if primeira else "fingerprint_alterado"
        mon = registrar_monitoramento(cnpj_d, motivo)
        deltas = _diff_campos(ant, v)
        mudancas.append(
            {
                "cnpj": cnpj_d,
                "cnpj_formatado": v.get("cnpj_formatado"),
                "empresa_id": v.get("empresa_id"),
                "nome_fantasia": v.get("nome_fantasia"),
                "motivo": motivo,
                "deltas": deltas,
                "monitoramento": mon,
                "vinculo": v,
            }
        )
    return mudancas


def _diff_campos(ant: dict[str, Any], novo: dict[str, Any]) -> list[str]:
    out = []
    if not ant:
        out.append("CNPJ entrou no radar de monitoramento")
        return out
    if ant.get("cnae_principal") != novo.get("cnae_principal"):
        out.append(f"CNAE principal: {ant.get('cnae_principal')} → {novo.get('cnae_principal')}")
    ant_ramos = set(ant.get("ramos") or [])
    novo_ramos = set(novo.get("ramos") or [])
    if ant_ramos != novo_ramos:
        out.append(f"Ramos: {sorted(ant_ramos)} → {sorted(novo_ramos)}")
    ant_skus = int((ant.get("produtos") or {}).get("total_skus") or 0)
    novo_skus = int((novo.get("produtos") or {}).get("total_skus") or 0)
    if ant_skus != novo_skus:
        out.append(f"SKUs vinculados: {ant_skus} → {novo_skus}")
    ant_mk = (ant.get("marketplaces") or {}).get("foco_principal")
    novo_mk = (novo.get("marketplaces") or {}).get("foco_principal")
    if ant_mk != novo_mk:
        out.append(f"Foco marketplace: {ant_mk} → {novo_mk}")
    if not out:
        out.append("Alteração no fingerprint (seller/Telegram/catálogos/assinatura)")
    return out


def salvar_snapshot(resultado: dict[str, Any]) -> None:
    escrever_json_atomico(SNAPSHOT_PATH, resultado)
    hist = ler_json(HISTORY_PATH, default=[])
    if not isinstance(hist, list):
        hist = []
    hist.append(
        {
            "em": resultado.get("gerado_em"),
            "total": resultado.get("total"),
            "alteracoes": len(resultado.get("alteracoes") or []),
            "assinaturas": [
                {
                    "cnpj": v.get("cnpj"),
                    "fp": (v.get("fingerprint") or {}).get("assinatura"),
                }
                for v in (resultado.get("vinculos") or [])
            ],
        }
    )
    escrever_json_atomico(HISTORY_PATH, hist[-50:])
