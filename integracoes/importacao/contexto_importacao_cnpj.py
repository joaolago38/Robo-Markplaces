"""
integracoes/importacao/contexto_importacao_cnpj.py
Contexto padronizado para agentes de importação:

- CEP de teste/destino: 13467-694 (sobrescritível)
- CNPJ importador + CNAEs validados × marketplaces (foco ML)
- Custos aduaneiros detalhados + nome do responsável
"""
from __future__ import annotations

import logging
from typing import Any

from core.empresa.cnpj_utils import digitos, formatar_cnpj, norm_cnae
from core.horario import agora_brasil

logger = logging.getLogger("contexto_importacao_cnpj")

CEP_TESTE_PADRAO = "13467-694"


def _cfg():
    from core import config as cfg

    return cfg


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def responsavel_importacao() -> dict[str, Any]:
    """Pessoa responsável pela operação (despacho / acompanhamento)."""
    from core.atomic_io import ler_json
    from core.config import ROOT

    cfg = _cfg()
    path = getattr(cfg, "IMPORTACAO_OPERACAO_FIXA_CATALOGO", "catalogo/importacao_operacao_fixa.json")
    fixa = ler_json(ROOT / path, default={})
    resp = fixa.get("responsavel") if isinstance(fixa.get("responsavel"), dict) else {}

    nome = (
        str(getattr(cfg, "IMPORTACAO_RESPONSAVEL_NOME", "") or "").strip()
        or str(resp.get("nome") or "").strip()
        or "Responsável não cadastrado"
    )
    return {
        "nome": nome,
        "cargo": str(
            getattr(cfg, "IMPORTACAO_RESPONSAVEL_CARGO", "") or resp.get("cargo") or "Responsável importação"
        ).strip(),
        "contato": str(
            getattr(cfg, "IMPORTACAO_RESPONSAVEL_CONTATO", "") or resp.get("contato") or ""
        ).strip(),
        "documento": str(resp.get("documento") or "").strip(),
    }


def cnpj_importacao() -> str:
    cfg = _cfg()
    return digitos(
        str(
            getattr(cfg, "IMPORTACAO_CNPJ", "")
            or getattr(cfg, "CNPJ_DONO_PRODUTOS", "")
            or getattr(cfg, "ESMALTES_CNPJ", "")
            or "52668583000127"
        )
    )


def validar_cnaes_marketplaces(cnpj: str | None = None) -> dict[str, Any]:
    """
    Atrela CNPJ → CNAEs do catálogo e marketplaces (ativos + abertos).
    Valida se há CNAE principal e foco Mercado Livre.
    """
    from core.empresa_contexto import empresa_por_cnpj
    from integracoes.empresa.vinculo_cnae_cnpj_produtos import montar_vinculo, perfil_marketplace

    cnpj_d = digitos(cnpj or cnpj_importacao())
    emp = empresa_por_cnpj(cnpj_d) or {}
    vinculos = (montar_vinculo(cnpj=cnpj_d).get("vinculos") or []) if cnpj_d else []
    v = vinculos[0] if vinculos else {}
    mk = perfil_marketplace(emp) if emp else (v.get("marketplaces") or {})

    cnaes = list(emp.get("cnaes") or v.get("cnaes") or [])
    cnae_p = emp.get("cnae_principal") or {}
    if isinstance(cnae_p, dict):
        cnae_codigo = cnae_p.get("codigo")
        cnae_desc = cnae_p.get("descricao")
    else:
        cnae_codigo = v.get("cnae_principal")
        cnae_desc = v.get("cnae_descricao")

    problemas: list[str] = []
    if not cnpj_d or len(cnpj_d) != 14:
        problemas.append("cnpj_invalido")
    if not emp and not v:
        problemas.append("cnpj_sem_empresa_no_catalogo")
    if not cnae_codigo and not cnaes:
        problemas.append("cnae_ausente")
    if not mk.get("prioriza_mercadolivre") and "mercadolivre" not in (mk.get("ativos") or []):
        problemas.append("marketplace_ml_nao_vinculado")

    return {
        "ok": not problemas,
        "cnpj": cnpj_d,
        "cnpj_formatado": formatar_cnpj(cnpj_d),
        "empresa_id": emp.get("id") or v.get("empresa_id"),
        "nome_fantasia": emp.get("nome_fantasia") or v.get("nome_fantasia"),
        "cnae_principal": cnae_codigo,
        "cnae_descricao": cnae_desc,
        "cnaes": [
            {
                "codigo": c.get("codigo"),
                "descricao": c.get("descricao"),
                "principal": bool(c.get("principal")),
                "norm": norm_cnae(str(c.get("codigo") or "")),
            }
            for c in cnaes
            if isinstance(c, dict)
        ],
        "ramos": list(emp.get("ramos") or v.get("ramos") or []),
        "marketplaces": mk,
        "problemas": problemas,
        "validacao": "ok" if not problemas else "pendencias",
    }


def destino_cep_importacao() -> dict[str, Any]:
    """CEP de teste/operação — default 13467-694."""
    from integracoes.importacao.operacao_destino import carregar_operacao_destino, resumo_destino

    # Garante default de teste se env vazio
    cfg = _cfg()
    if not getattr(cfg, "IMPORTACAO_DESTINO_CEP", ""):
        # overlay via catalog already has 13467-694
        pass
    op = carregar_operacao_destino()
    r = resumo_destino(op)
    if not r.get("destino_cep"):
        r["destino_cep"] = CEP_TESTE_PADRAO
    r["cep_teste"] = CEP_TESTE_PADRAO
    r["usando_cep_teste"] = str(r.get("destino_cep")) == CEP_TESTE_PADRAO
    return r


def calculo_desde_cenario_porto(cenario: dict[str, Any] | None) -> dict[str, Any]:
    """Converte melhor cenário de comparar_portos em shape de custos."""
    c = cenario if isinstance(cenario, dict) else {}
    if not c:
        return {}
    impostos = _f(c.get("impostos_total_brl") or c.get("impostos_brl"))
    return {
        "ok": True,
        "custo_total_brl": c.get("custo_total_brl"),
        "custo_unitario_brl": c.get("custo_unitario_brl"),
        "frete_internacional_brl": c.get("frete_internacional_brl"),
        "frete_rodoviario_brl": c.get("custos_locais_brl") or c.get("frete_interno_brl"),
        "impostos_total_brl": impostos,
        "landed": {
            "custo_total_brl": c.get("custo_total_brl"),
            "custo_unitario_brl": c.get("custo_unitario_brl"),
            "impostos_total_brl": impostos,
            "frete_internacional_brl": c.get("frete_internacional_brl"),
        },
        "gateway": c.get("codigo") or (c.get("gateway") or {}).get("codigo"),
        "modal": c.get("modal"),
    }


def extrair_custos_aduaneiros(calculo: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normaliza custos aduaneiros a partir de cálculo aéreo formal, landed ou porto.
    """
    c = calculo if isinstance(calculo, dict) else {}
    # Se veio resultado de portos com melhor_geral
    if not c.get("itens") and not c.get("ii_brl") and c.get("melhor_geral"):
        c = {**c, **calculo_desde_cenario_porto(c.get("melhor_geral"))}

    landed = c.get("landed") if isinstance(c.get("landed"), dict) else {}
    itens = c.get("itens") if isinstance(c.get("itens"), list) else []

    por_id = {str(i.get("id")): i for i in itens if isinstance(i, dict)}

    def _item(chave: str, *fallbacks: str) -> float:
        if chave in por_id:
            return _f(por_id[chave].get("brl"))
        for fb in fallbacks:
            if c.get(fb) is not None:
                return _f(c.get(fb))
            if landed.get(fb) is not None:
                return _f(landed.get(fb))
        return 0.0

    aduaneiros = {
        "ii_brl": _item("ii", "ii_brl"),
        "ipi_brl": _item("ipi", "ipi_brl"),
        "pis_cofins_brl": _item("pis_cofins", "pis_cofins_brl")
        or (_f(c.get("pis_brl")) + _f(c.get("cofins_brl"))),
        "icms_brl": _item("icms", "icms_brl"),
        "siscomex_brl": _item("siscomex", "siscomex_brl"),
        "desembaraco_brl": _item("desembaraco", "desembaraco_brl"),
        "armazenagem_brl": _item("armazenagem", "armazenagem_brl"),
        "thc_brl": _item("thc", "thc_brl"),
        "afrmm_brl": _f(c.get("afrmm_brl") or landed.get("afrmm_brl")),
    }
    # Se landed/porto só tem impostos_total
    if not any(aduaneiros.values()):
        agreg = _f(c.get("impostos_total_brl") or landed.get("impostos_total_brl"))
        if agreg:
            aduaneiros["impostos_agregados_brl"] = agreg

    total_adu = sum(aduaneiros.values())
    frete_int = _item("frete_int", "frete_internacional_brl") or _f(c.get("frete_internacional_brl"))
    frete_rod = _item("frete_rod", "frete_rodoviario_brl") or _f(
        c.get("frete_interno_brl_unit"), 0
    ) * max(1, int(c.get("quantidade") or landed.get("quantidade") or 1))
    fob = _item("fob", "fob_brl_total") or _f(landed.get("fob_brl_total") or c.get("fob_brl"))
    seguro = _item("seguro", "seguro_brl") or _f(landed.get("seguro_brl"))
    cif = _f(c.get("valor_aduaneiro_cif_brl") or c.get("cif_brl") or landed.get("cif_brl"))
    custo_total = _f(c.get("custo_total_brl") or landed.get("custo_total_brl"))
    custo_unit = _f(c.get("custo_unitario_brl") or landed.get("custo_unitario_brl"))

    return {
        "ok": custo_total > 0 or total_adu > 0 or cif > 0,
        "cif_aduaneiro_brl": round(cif, 2),
        "fob_brl": round(fob, 2),
        "seguro_brl": round(seguro, 2),
        "frete_internacional_brl": round(frete_int, 2),
        "frete_interno_brl": round(frete_rod, 2),
        "aduaneiros": {k: round(v, 2) for k, v in aduaneiros.items()},
        "total_aduaneiros_brl": round(total_adu, 2),
        "custo_total_brl": round(custo_total, 2),
        "custo_unitario_brl": round(custo_unit, 2),
        "itens_detalhe": [
            {"id": i.get("id"), "label": i.get("label"), "brl": i.get("brl"), "grupo": i.get("grupo")}
            for i in itens[:16]
        ],
    }


def montar_contexto_importacao_cnpj(
    *,
    calculo: dict[str, Any] | None = None,
    cnpj: str | None = None,
) -> dict[str, Any]:
    """Pacote único para anexar em qualquer agente de importação."""
    from integracoes.importacao.perfil_empresa_importacao import obter_perfil_importador

    cnpj_d = digitos(cnpj or cnpj_importacao())
    cnae_mk = validar_cnaes_marketplaces(cnpj_d)
    destino = destino_cep_importacao()
    responsavel = responsavel_importacao()
    perfil = {}
    try:
        perfil = obter_perfil_importador(atualizar_cnpj=False)
    except Exception as exc:
        logger.debug("perfil importador: %s", exc)

    custos = extrair_custos_aduaneiros(calculo)

    return {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "modo": "importacao_cnpj",
        "cep": destino,
        "cnpj": {
            "cnpj": cnpj_d,
            "cnpj_formatado": formatar_cnpj(cnpj_d),
            "razao_social": perfil.get("razao_social") or cnae_mk.get("nome_fantasia"),
            "regime_tributario": perfil.get("regime_tributario"),
            "endereco": perfil.get("endereco"),
        },
        "cnae_marketplaces": cnae_mk,
        "responsavel": responsavel,
        "custos_importacao": custos,
        "aviso": (
            f"Operação CNPJ · CEP teste/destino `{destino.get('destino_cep')}` · "
            "custos aduaneiros estimados — confirme NCM com despachante."
        ),
    }


def formatar_bloco_telegram_contexto(ctx: dict[str, Any]) -> str:
    """Bloco Telegram: CNPJ, CNAE×MK, CEP, responsável, custos aduaneiros."""
    if not ctx or not ctx.get("ok"):
        return ""

    cnpj = ctx.get("cnpj") or {}
    cnae = ctx.get("cnae_marketplaces") or {}
    cep = ctx.get("cep") or {}
    resp = ctx.get("responsavel") or {}
    custos = ctx.get("custos_importacao") or {}
    adu = custos.get("aduaneiros") or {}
    mk = cnae.get("marketplaces") or {}

    def _brl(v: Any) -> str:
        try:
            return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return "n/d"

    linhas = [
        "*Importação CNPJ*",
        f"CNPJ `{cnpj.get('cnpj_formatado')}` — {cnpj.get('razao_social') or '—'}",
        f"CNAE `{cnae.get('cnae_principal') or '—'}` · "
        f"validação *{cnae.get('validacao')}*",
        f"ML foco={'sim' if mk.get('prioriza_mercadolivre') else 'não'} · "
        f"ativos: {', '.join(mk.get('ativos') or []) or '—'} · "
        f"abertos: {', '.join((mk.get('abertos_para_expansao') or [])[:3]) or '—'}",
        f"CEP destino `{cep.get('destino_cep')}` "
        f"({cep.get('destino_cidade')}/{cep.get('destino_uf')})"
        + (" · _CEP teste_" if cep.get("usando_cep_teste") else ""),
        f"Responsável: *{resp.get('nome')}*"
        + (f" ({resp.get('cargo')})" if resp.get("cargo") else ""),
    ]
    if resp.get("contato"):
        linhas.append(f"Contato: {resp.get('contato')}")

    if cnae.get("problemas"):
        linhas.append(f"⚠ Pendências CNAE/MK: {', '.join(cnae['problemas'])}")

    if custos.get("ok"):
        linhas.extend(
            [
                "*Custos aduaneiros*",
                f"  CIF: {_brl(custos.get('cif_aduaneiro_brl'))} · "
                f"FOB {_brl(custos.get('fob_brl'))} · seguro {_brl(custos.get('seguro_brl'))}",
                f"  II {_brl(adu.get('ii_brl'))} · IPI {_brl(adu.get('ipi_brl'))} · "
                f"PIS/COFINS {_brl(adu.get('pis_cofins_brl'))} · ICMS {_brl(adu.get('icms_brl'))}",
                f"  SISCOMEX {_brl(adu.get('siscomex_brl'))} · "
                f"desembaraço {_brl(adu.get('desembaraco_brl'))} · "
                f"armazenagem {_brl(adu.get('armazenagem_brl'))} · THC {_brl(adu.get('thc_brl'))}",
                f"  Frete int. {_brl(custos.get('frete_internacional_brl'))} · "
                f"interno {_brl(custos.get('frete_interno_brl'))}",
                f"  *Total aduaneiros* {_brl(custos.get('total_aduaneiros_brl'))} · "
                f"*Custo total* {_brl(custos.get('custo_total_brl'))} "
                f"(unit. {_brl(custos.get('custo_unitario_brl'))})",
            ]
        )

    for cnae_item in (cnae.get("cnaes") or [])[:3]:
        flag = "★" if cnae_item.get("principal") else "·"
        linhas.append(
            f"  {flag} CNAE `{cnae_item.get('codigo')}` {str(cnae_item.get('descricao') or '')[:50]}"
        )

    return "\n".join(linhas)


def anexar_contexto_ao_resultado(
    resultado: dict[str, Any],
    *,
    calculo: dict[str, Any] | None = None,
    cnpj: str | None = None,
) -> dict[str, Any]:
    """Anexa contexto CNPJ/CEP/CNAE/custos/responsável ao dict do agente."""
    out = dict(resultado or {})
    calc = calculo or out.get("calculo_aereo_formal") or out.get("calculo") or out
    ctx = montar_contexto_importacao_cnpj(calculo=calc if isinstance(calc, dict) else None, cnpj=cnpj)
    out["contexto_importacao_cnpj"] = ctx
    bloco = formatar_bloco_telegram_contexto(ctx)
    out["bloco_telegram_importacao_cnpj"] = bloco
    if bloco and out.get("mensagem"):
        out["mensagem"] = f"{out['mensagem']}\n\n{bloco}"
    return out
