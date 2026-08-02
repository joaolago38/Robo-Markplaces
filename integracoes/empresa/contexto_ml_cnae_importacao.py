"""
integracoes/empresa/contexto_ml_cnae_importacao.py
Associa produto ML ↔ CNAE/CNPJ e monta o quadro de decisão de importação:
  Alibaba + USD + cálculo aéreo Viracopos (CEP destino configurável)
  + quantidade/volume de vendas no Mercado Livre no mesmo CNAE.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.empresa.cnpj_utils import digitos, formatar_cnpj, norm_cnae
from core.horario import agora_brasil

logger = logging.getLogger("contexto_ml_cnae_importacao")

SNAPSHOT_PATH = ROOT / "logs" / "contexto_ml_cnae_importacao_ultima.json"

# Snapshots de monitores com quantidade_vendida / vendas_totais
_SNAPS_VOLUME = (
    "monitor_masterprint_petg_ultima.json",
    "monitor_masterprint_escritorio_ultima.json",
    "monitor_filamentos_ml_ultima.json",
    "monitor_kits_esmaltes_ultima.json",
    "monitor_mercado_esmaltes_ultima.json",
    "resumo_conta_ml_ultima.json",
)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _ler(nome: str) -> dict[str, Any]:
    data = ler_json(ROOT / "logs" / nome, default={})
    return data if isinstance(data, dict) else {}


def associar_produto_a_cnae(
    *,
    sku: str | None = None,
    item_id: str | None = None,
    produto: dict[str, Any] | None = None,
    cnpj: str | None = None,
    cnae: str | None = None,
    ramo: str | None = None,
) -> dict[str, Any]:
    """
    Resolve produto → CNPJ dono → CNAE(s) / ramos.
    Aceita hint explícito no produto (cnae, cnae_hint, ramo, empresa_id).
    """
    from core.empresa_contexto import empresa_por_cnpj, empresa_por_id, empresas_por_cnae
    from integracoes.empresa.vinculo_cnae_cnpj_produtos import (
        montar_vinculo,
        produtos_vinculados_ao_cnpj,
    )

    prod = dict(produto or {})
    if sku and not prod:
        try:
            from core.catalogo_produtos import carregar_produtos_para_operacao

            for p in carregar_produtos_para_operacao(merge_bling=False):
                if str(p.get("sku") or "") == str(sku):
                    prod = dict(p)
                    break
        except Exception as exc:
            logger.debug("catalogo produto: %s", exc)

    if item_id and not prod.get("mercadolivre"):
        prod.setdefault("mercadolivre", {})["item_id"] = item_id

    cnae_hint = norm_cnae(
        str(cnae or prod.get("cnae") or prod.get("cnae_hint") or "")
    )
    ramo_hint = str(ramo or prod.get("ramo") or "").strip().lower()
    empresa_id = str(prod.get("empresa_id") or "").strip()
    cnpj_d = digitos(str(cnpj or prod.get("cnpj_dono") or ""))

    emp: dict[str, Any] = {}
    if empresa_id:
        emp = empresa_por_id(empresa_id) or {}
    elif cnpj_d:
        emp = empresa_por_cnpj(cnpj_d) or {}
    elif cnae_hint:
        lista = empresas_por_cnae(cnae_hint) or []
        emp = lista[0] if lista else {}
    elif ramo_hint:
        from core.empresa_contexto import listar_empresas

        for e in listar_empresas(apenas_ativas=True) or []:
            ramos = [str(r).lower() for r in (e.get("ramos") or [])]
            if ramo_hint in ramos:
                emp = e
                break

    if not emp and prod.get("cnpj_dono"):
        emp = empresa_por_cnpj(str(prod.get("cnpj_dono"))) or {}

    cnpj_final = digitos(str(emp.get("cnpj") or cnpj_d))
    cnae_p = emp.get("cnae_principal") or {}
    if isinstance(cnae_p, dict):
        cnae_codigo = cnae_p.get("codigo") or cnae_hint
    else:
        cnae_codigo = cnae_hint

    vinculo = {}
    if cnpj_final:
        base = montar_vinculo(cnpj=cnpj_final)
        vinculo = (base.get("vinculos") or [{}])[0] if base.get("vinculos") else {}
        if not prod.get("sku"):
            # tenta achar SKU no vínculo
            for s in (produtos_vinculados_ao_cnpj(cnpj_final).get("skus") or []):
                if sku and str(s.get("sku")) == str(sku):
                    prod = {**prod, **s}
                    break

    return {
        "ok": bool(emp or cnae_codigo),
        "produto": {
            "sku": prod.get("sku") or sku,
            "nome": prod.get("nome") or prod.get("titulo"),
            "item_id": item_id
            or (prod.get("mercadolivre") or {}).get("item_id")
            or prod.get("item_id"),
            "cnpj_dono": digitos(str(prod.get("cnpj_dono") or cnpj_final)),
        },
        "empresa_id": emp.get("id"),
        "cnpj": cnpj_final,
        "cnpj_formatado": emp.get("cnpj_formatado") or formatar_cnpj(cnpj_final),
        "cnae_principal": cnae_codigo,
        "cnaes": emp.get("cnaes") or [],
        "ramos": emp.get("ramos") or ([ramo_hint] if ramo_hint else []),
        "vinculo": vinculo,
    }


def coletar_volume_vendas_ml_por_cnae(
    *,
    cnae: str | None = None,
    ramos: list[str] | None = None,
) -> dict[str, Any]:
    """
    Agrega quantidade e volume (proxy receita) de vendas ML
    a partir dos snapshots dos monitores do ramo/CNAE.
    """
    ramos_l = {str(r).lower() for r in (ramos or []) if r}
    cnae_n = norm_cnae(cnae or "")

    qtd_total = 0
    receita_proxy = 0.0
    itens_amostra: list[dict[str, Any]] = []
    fontes: list[str] = []

    for nome in _SNAPS_VOLUME:
        snap = _ler(nome)
        if not snap:
            continue
        # Filtro leve por ramo no path/nome do arquivo
        nome_l = nome.lower()
        if ramos_l:
            if not any(r in nome_l for r in ramos_l) and "resumo_conta" not in nome_l:
                # ainda lê resumo_conta; monitores só se ramo casa
                if not any(
                    r in ("esmaltes", "impala", "manicures") and "esmalte" in nome_l
                    for r in ramos_l
                ) and not any(
                    r in ("filamentos", "petg", "masterprint", "escritorio")
                    and ("filamento" in nome_l or "petg" in nome_l or "escritorio" in nome_l or "masterprint" in nome_l)
                    for r in ramos_l
                ):
                    continue

        fontes.append(nome)
        # Campos agregados
        for chave in ("vendas_totais", "quantidade_vendida", "total_vendas"):
            if snap.get(chave) is not None:
                qtd_total += int(_num(snap.get(chave)))
        for chave in ("receita_proxy", "receita_total", "faturamento_proxy"):
            if snap.get(chave) is not None:
                receita_proxy += _num(snap.get(chave))

        # Listas de itens
        for lista_chave in ("itens", "produtos", "anuncios_amostra", "top_itens", "skus"):
            lista = snap.get(lista_chave)
            if not isinstance(lista, list):
                continue
            for it in lista[:30]:
                if not isinstance(it, dict):
                    continue
                q = int(
                    _num(
                        it.get("quantidade_vendida")
                        or it.get("sold_quantity")
                        or it.get("vendidos")
                        or it.get("vendas")
                    )
                )
                preco = _num(it.get("preco") or it.get("price"))
                if q <= 0 and preco <= 0:
                    continue
                qtd_total += q
                receita_proxy += q * preco if q and preco else _num(it.get("receita_proxy"))
                if len(itens_amostra) < 8:
                    itens_amostra.append(
                        {
                            "item_id": it.get("item_id") or it.get("id"),
                            "titulo": str(it.get("titulo") or it.get("nome") or "")[:60],
                            "quantidade_vendida": q,
                            "preco": preco,
                        }
                    )

    # Se CNAE informado mas zero volume, ainda reporta ok=False parcial
    return {
        "ok": bool(fontes),
        "cnae": cnae_n or None,
        "ramos": sorted(ramos_l),
        "quantidade_vendida": qtd_total,
        "volume_receita_proxy": round(receita_proxy, 2),
        "itens_amostra": itens_amostra,
        "fontes": fontes,
    }


def montar_quadro_importacao_cnae(
    *,
    sku: str | None = None,
    item_id: str | None = None,
    produto: dict[str, Any] | None = None,
    cnpj: str | None = None,
    cnae: str | None = None,
    ramo: str | None = None,
    oportunidade_alibaba: dict[str, Any] | None = None,
    cambio_ao_vivo: bool = False,
) -> dict[str, Any]:
    """
    Quadro único: produto→CNAE + USD + Alibaba + custo VCP (CEP destino)
    + volume/qtd vendas ML no CNAE.
    """
    from integracoes.cambio.cotacao_usd import (
        cotacao_confiavel_para_margem,
        obter_cotacao_usd,
    )
    from integracoes.empresa.decision_limits import coletar_sinais_alibaba
    from integracoes.importacao.calculo_importacao_aerea import (
        calcular_custo_importacao_aerea_formal,
        montar_entradas_de_produto,
    )
    from integracoes.importacao.operacao_destino import (
        carregar_operacao_destino,
        resumo_destino,
    )

    assoc = associar_produto_a_cnae(
        sku=sku,
        item_id=item_id,
        produto=produto,
        cnpj=cnpj,
        cnae=cnae,
        ramo=ramo,
    )
    operacao = carregar_operacao_destino()
    destino = resumo_destino(operacao)
    cotacao = obter_cotacao_usd(usar_cache=not cambio_ao_vivo)
    cambio_ok = cotacao_confiavel_para_margem(cotacao)
    usd = _num(cotacao.get("usd_brl"))

    alibaba = coletar_sinais_alibaba()
    volume = coletar_volume_vendas_ml_por_cnae(
        cnae=str(assoc.get("cnae_principal") or cnae or ""),
        ramos=list(assoc.get("ramos") or []),
    )

    calc: dict[str, Any] = {"ok": False, "motivo": "sem_produto_alibaba"}
    prod_calc = dict(produto or assoc.get("produto") or {})
    # Se oportunidade veio, calcula formal VCP
    if oportunidade_alibaba or prod_calc.get("preco_fob_usd") or prod_calc.get("peso_kg"):
        try:
            entradas = montar_entradas_de_produto(
                prod_calc,
                oportunidade_alibaba,
                cambio_usd_brl=usd if usd > 0 else 5.5,
                operacao=operacao,
            )
            calc = calcular_custo_importacao_aerea_formal(entradas)
        except Exception as exc:
            logger.warning("calc VCP quadro: %s", exc)
            calc = {"ok": False, "motivo": str(exc)}

    # Regras de decisão no mesmo frame
    recomendacoes: list[str] = []
    bloqueios: list[str] = []
    if not cambio_ok:
        bloqueios.append("cambio_nao_confiavel")
        recomendacoes.append("Não fechar importação até cotação USD confiável")
    if alibaba.get("bloqueado"):
        bloqueios.append("alibaba_bloqueado")
    if volume.get("quantidade_vendida", 0) <= 0 and assoc.get("ramos"):
        recomendacoes.append(
            "Volume ML no CNAE sem sinal claro — validar demanda antes de importar"
        )
    elif volume.get("quantidade_vendida", 0) > 0:
        recomendacoes.append(
            f"Demanda ML no CNAE: qtd={volume.get('quantidade_vendida')} · "
            f"volume≈R$ {volume.get('volume_receita_proxy')}"
        )
    if calc.get("ok"):
        recomendacoes.append(
            f"Custo unitário formal VCP: R$ {calc.get('custo_unitario_brl')} "
            f"(CEP {destino.get('destino_cep')})"
        )

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "marketplace": "mercadolivre",
        "associacao": assoc,
        "destino_operacao": destino,
        "cambio": {
            "ok": bool(cotacao.get("ok")),
            "usd_brl": usd,
            "confiavel": cambio_ok,
            "fonte": cotacao.get("fonte"),
        },
        "alibaba": alibaba,
        "volume_ml_cnae": volume,
        "calculo_importacao_vcp": {
            "ok": bool(calc.get("ok")),
            "custo_unitario_brl": calc.get("custo_unitario_brl"),
            "custo_total_brl": calc.get("custo_total_brl"),
            "destino_cep": calc.get("destino_cep") or destino.get("destino_cep"),
            "aeroporto": calc.get("aeroporto") or destino.get("aeroporto_label"),
            "quantidade": calc.get("quantidade"),
            "motivo": calc.get("motivo"),
        },
        "recomendacoes": recomendacoes,
        "bloqueios": bloqueios,
    }

    # Datadog
    tags = [
        "marketplace:mercadolivre",
        f"empresa:{assoc.get('empresa_id') or 'desconhecida'}",
        f"aeroporto:{destino.get('aeroporto_codigo') or 'VCP'}",
    ]
    if assoc.get("cnae_principal"):
        tags.append(f"cnae:{norm_cnae(str(assoc['cnae_principal']))[:8]}")
    gauge("importacao_cnae.usd_brl", usd, tags)
    gauge(
        "importacao_cnae.volume_qtd",
        float(volume.get("quantidade_vendida") or 0),
        tags,
    )
    gauge(
        "importacao_cnae.volume_receita",
        float(volume.get("volume_receita_proxy") or 0),
        tags,
    )
    if calc.get("ok"):
        gauge(
            "importacao_cnae.custo_unitario_brl",
            float(calc.get("custo_unitario_brl") or 0),
            tags,
        )
    incrementar("importacao_cnae.quadro_ok", tags=tags)
    for b in bloqueios:
        incrementar("importacao_cnae.bloqueio", tags=[*tags, f"motivo:{b[:40]}"])

    from core.atomic_io import escrever_json_atomico

    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out
