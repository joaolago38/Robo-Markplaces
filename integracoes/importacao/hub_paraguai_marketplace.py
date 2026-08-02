"""
integracoes/importacao/hub_paraguai_marketplace.py
Estrutura de cálculos do hub comercial no Paraguai (futuro):

1. Custo validado no endereço PY + corredor terrestre → CEP BR
2. Comparação com importação direta BR (landed)
3. Possibilidade multi-cliente: taxa de serviço / handling → lucro logístico
4. Lucro potencial em marketplaces (ML etc.)

Status: planejamento. Não substitui assessoria fiscal/aduaneira Mercosul.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.corredor_paraguai_terrestre import montar_cenario_py_terrestre_br
from integracoes.importacao.custo_landed import calcular_custo_landed, calcular_margem_revenda
from integracoes.importacao.portos_brasil import endereco_comercial_paraguai
from integracoes.importacao.siscomex import taxa_siscomex_brl

logger = logging.getLogger("hub_paraguai_marketplace")

SNAPSHOT_PATH = ROOT / "logs" / "hub_paraguai_marketplace_ultima.json"
CATALOGO_REL = "catalogo/hub_paraguai_clientes.json"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 1) -> int:
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return default


def _cfg():
    from core import config as cfg

    return cfg


def carregar_catalogo_hub(caminho: str | None = None) -> dict[str, Any]:
    rel = caminho or getattr(_cfg(), "HUB_PARAGUAI_CATALOGO", CATALOGO_REL)
    data = ler_json(ROOT / rel, default={})
    return data if isinstance(data, dict) else {}


def endereco_hub_efetivo(catalogo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Endereço PY: env IMPORTACAO_PY_* > catálogo hub > portos_brasil."""
    cat = catalogo or carregar_catalogo_hub()
    hub = dict(cat.get("hub") or {})
    end_portos = endereco_comercial_paraguai()
    base = dict(end_portos.get("endereco") or {})
    # Hub catalogo preenche defaults se portos vazio
    for k in ("pais", "cidade", "departamento", "endereco", "codigo_postal", "lat", "lng"):
        if not base.get(k) and hub.get(k) is not None:
            base[k] = hub[k]
    return {
        "ok": bool(base.get("cidade") or base.get("endereco")),
        "status_hub": cat.get("status") or "planejado",
        "hub_id": hub.get("id") or "hub_py_cde",
        "endereco": base,
        "usos": list(hub.get("uso") or []),
        "cep_destino_br_padrao": hub.get("cep_destino_br_padrao") or "13467-694",
        "via_env": bool(end_portos.get("via_env")),
        "aviso_legal": cat.get("aviso_legal") or "",
    }


def custos_operacao_hub(
    *,
    quantidade: int = 1,
    volume_m3_unit: float | None = None,
    dias_armazenagem: int | None = None,
    valor_carga_brl: float = 0.0,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Custos no hub PY (armazenagem + handling + seguro local) — validados por fórmula."""
    cat = catalogo or carregar_catalogo_hub()
    op = cat.get("custos_operacionais_brl") or {}
    qty = _i(quantidade)
    vol_u = _f(volume_m3_unit, _f(op.get("volume_m3_padrao_por_unidade"), 0.004))
    dias = max(1, int(dias_armazenagem or op.get("dias_armazenagem_padrao") or 7))
    vol_total = vol_u * qty

    armazenagem = vol_total * _f(op.get("armazenagem_dia_m3"), 8.0) * dias
    por_un = _f(op.get("handling_por_unidade_brl"), _f(op.get("handling_por_volume_brl"), 3.5))
    handling = max(
        _f(op.get("handling_minimo_embarque_brl"), 80.0),
        qty * por_un,
    )

    seguro = valor_carga_brl * (_f(op.get("seguro_hub_pct_sobre_carga"), 0.2) / 100.0)
    total = armazenagem + handling + seguro
    capacidade = _f(op.get("capacidade_m3_estimada"), 40.0)
    ocupacao_pct = round(100.0 * vol_total / capacidade, 2) if capacidade > 0 else 0.0

    return {
        "ok": True,
        "quantidade": qty,
        "volume_m3_total": round(vol_total, 4),
        "dias_armazenagem": dias,
        "armazenagem_brl": round(armazenagem, 2),
        "handling_brl": round(handling, 2),
        "seguro_hub_brl": round(seguro, 2),
        "custo_hub_total_brl": round(total, 2),
        "custo_hub_unitario_brl": round(total / qty, 2),
        "ocupacao_capacidade_pct": ocupacao_pct,
        "overhead_mensal_hub_brl": _f(op.get("overhead_mensal_hub_brl")),
        "validacao": {
            "volume_positivo": vol_total > 0,
            "dentro_capacidade": ocupacao_pct <= 100.0,
            "handling_minimo_aplicado": handling >= _f(op.get("handling_minimo_embarque_brl"), 80.0),
        },
    }


def taxa_servico_cliente(
    custo_base_brl: float,
    *,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Receita do hub cobrada de cliente terceiro (markup logístico)."""
    cat = catalogo or carregar_catalogo_hub()
    tx = cat.get("taxa_servico_multi_cliente") or {}
    base = max(0.0, _f(custo_base_brl))
    pct = _f(tx.get("pct_sobre_custo_operacao"), 12.0)
    bruto = base * (pct / 100.0)
    minimo = _f(tx.get("minimo_por_embarque_brl"), 150.0)
    maximo = _f(tx.get("maximo_por_embarque_brl"), 5000.0)
    cobrado = min(maximo, max(minimo, bruto)) if base > 0 else 0.0
    return {
        "ok": True,
        "pct": pct,
        "base_brl": round(base, 2),
        "taxa_calculada_brl": round(bruto, 2),
        "taxa_cobrada_brl": round(cobrado, 2),
        "lucro_servico_brl": round(cobrado, 2),
        "minimo_brl": minimo,
        "maximo_brl": maximo,
    }


def custo_rota_hub_py(
    *,
    fob_usd: float,
    cambio_usd_brl: float,
    quantidade: int = 1,
    peso_kg_unit: float = 1.0,
    volume_m3_unit: float | None = None,
    cep_destino: str | None = None,
    dias_armazenagem: int | None = None,
    frete_china_py_usd_kg: float | None = None,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Custo unitário via hub PY:
      mercadoria (FOB+frete China→PY estimado) + hub + terrestre PY→BR.
    Impostos BR formais NÃO são inventados aqui — ficam em 'pendencia_fiscal_br'.
    """
    cat = catalogo or carregar_catalogo_hub()
    hub = endereco_hub_efetivo(cat)
    qty = _i(quantidade)
    cambio = _f(cambio_usd_brl)
    fob = _f(fob_usd)
    if fob <= 0 or cambio <= 0:
        return {"ok": False, "motivo": "FOB ou câmbio inválido"}

    frete_usd_kg = _f(
        frete_china_py_usd_kg,
        getattr(_cfg(), "HUB_PY_FRETE_CHINA_USD_KG", 1.2),
    )
    peso = max(0.01, _f(peso_kg_unit, 1.0))
    frete_china_py_brl = peso * qty * frete_usd_kg * cambio
    mercadoria_brl = fob * qty * cambio
    valor_carga = mercadoria_brl + frete_china_py_brl

    hub_custos = custos_operacao_hub(
        quantidade=qty,
        volume_m3_unit=volume_m3_unit,
        dias_armazenagem=dias_armazenagem,
        valor_carga_brl=valor_carga,
        catalogo=cat,
    )
    cep = cep_destino or hub.get("cep_destino_br_padrao") or "13467-694"
    terrestre = montar_cenario_py_terrestre_br(
        valor_mercadoria_brl=valor_carga,
        quantidade=qty,
        cep_destino=cep,
        fob_usd=fob,
        cambio_usd_brl=cambio,
    )
    melhor = terrestre.get("melhor_corredor") or {}
    frete_py_br = _f(melhor.get("custo_total_brl"))

    total = valor_carga + _f(hub_custos.get("custo_hub_total_brl")) + frete_py_br
    unit = total / qty

    return {
        "ok": True,
        "rota": "china_hub_py_terrestre_br",
        "hub": hub,
        "fob_usd_unit": round(fob, 4),
        "cambio_usd_brl": round(cambio, 4),
        "quantidade": qty,
        "cep_destino_br": cep,
        "mercadoria_brl": round(mercadoria_brl, 2),
        "frete_china_py_brl": round(frete_china_py_brl, 2),
        "frete_china_py_usd_kg": frete_usd_kg,
        "hub_custos": hub_custos,
        "terrestre_py_br": {
            "ok": terrestre.get("ok"),
            "corredor_id": melhor.get("corredor_id"),
            "custo_total_brl": frete_py_br,
            "km_total": melhor.get("km_total"),
            "dias_transito_estim": melhor.get("dias_transito_estim"),
        },
        "custo_total_brl": round(total, 2),
        "custo_unitario_brl": round(unit, 2),
        "pendencia_fiscal_br": (
            "Impostos/ICMS/DI na entrada BR via Mercosul devem ser confirmados com "
            "despachante — não embutidos nesta estimativa de hub."
        ),
        "despesas_validadas": {
            "mercadoria_e_frete_china_py": True,
            "hub_armazenagem_handling": bool(hub_custos.get("validacao", {}).get("volume_positivo")),
            "terrestre_py_br": bool(melhor.get("ok")),
            "siscomex_referencia_di_br_se_formal": taxa_siscomex_brl(adicoes=1),
        },
    }


def custo_rota_import_direta_br(
    *,
    fob_usd: float,
    cambio_usd_brl: float,
    quantidade: int = 1,
    peso_kg_unit: float = 1.0,
    modo_frete: str = "maritimo",
) -> dict[str, Any]:
    """Baseline: China → porto/aeroporto BR (landed completo com tributos)."""
    landed = calcular_custo_landed(
        fob_usd,
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=peso_kg_unit,
        quantidade=quantidade,
        modo_frete=modo_frete if modo_frete in ("maritimo", "aereo") else "maritimo",  # type: ignore[arg-type]
    )
    return {
        "ok": bool(landed.get("ok")),
        "rota": f"china_direto_{modo_frete}_br",
        "custo_unitario_brl": landed.get("custo_unitario_brl"),
        "custo_total_brl": landed.get("custo_total_brl"),
        "impostos_total_brl": landed.get("impostos_total_brl"),
        "siscomex_brl": landed.get("siscomex_brl"),
        "afrmm_brl": landed.get("afrmm_brl"),
        "landed": landed,
    }


def custo_maximo_para_lucro_pct(
    preco_venda_brl: float,
    *,
    taxa_marketplace_pct: float = 16.0,
    lucro_alvo_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Custo unitário máximo para lucro líquido = lucro_alvo_pct % do preço de venda,
    após taxa do marketplace.

    liquido = venda * (1 - taxa)
    lucro = liquido - custo >= venda * (lucro_alvo/100)
    => custo <= venda * (1 - taxa/100 - lucro_alvo/100)
    """
    venda = _f(preco_venda_brl)
    if venda <= 0:
        return {"ok": False, "motivo": "preço venda inválido"}
    taxa = _f(taxa_marketplace_pct) / 100.0
    lucro = _f(lucro_alvo_pct) / 100.0
    fator = 1.0 - taxa - lucro
    if fator <= 0:
        return {"ok": False, "motivo": "taxa+lucro >= 100%"}
    custo_max = round(venda * fator, 2)
    liquido = round(venda * (1.0 - taxa), 2)
    lucro_min_brl = round(venda * lucro, 2)
    return {
        "ok": True,
        "preco_venda_brl": round(venda, 2),
        "taxa_marketplace_pct": round(taxa * 100, 2),
        "lucro_alvo_pct": round(lucro * 100, 2),
        "liquido_apos_taxa_brl": liquido,
        "lucro_alvo_brl": lucro_min_brl,
        "custo_unitario_maximo_brl": custo_max,
    }


def preco_minimo_venda_para_lucro_pct(
    custo_unitario_brl: float,
    *,
    taxa_marketplace_pct: float = 16.0,
    lucro_alvo_pct: float = 20.0,
) -> dict[str, Any]:
    """
    Preço mínimo de venda no marketplace para atingir lucro_alvo % sobre a venda.
    venda * (1 - taxa - lucro) >= custo  =>  venda >= custo / (1 - taxa - lucro)
    """
    custo = _f(custo_unitario_brl)
    if custo < 0:
        return {"ok": False, "motivo": "custo inválido"}
    taxa = _f(taxa_marketplace_pct) / 100.0
    lucro = _f(lucro_alvo_pct) / 100.0
    denom = 1.0 - taxa - lucro
    if denom <= 0:
        return {"ok": False, "motivo": "taxa+lucro >= 100%"}
    venda_min = round(custo / denom, 2)
    return {
        "ok": True,
        "custo_unitario_brl": round(custo, 2),
        "taxa_marketplace_pct": round(taxa * 100, 2),
        "lucro_alvo_pct": round(lucro * 100, 2),
        "preco_venda_minimo_brl": venda_min,
    }


def carregar_produtos_marketplace_hub(
    catalogo: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Produtos do hub cruzados com catálogo Alibaba (filamentos nos marketplaces).
    Preço ML: snapshot filamentos se existir; senão preço do hub/catalogo.
    """
    cat = catalogo or carregar_catalogo_hub()
    base = [p for p in (cat.get("produtos_candidato_exemplo") or []) if isinstance(p, dict) and p.get("ativo", True)]

    # Preços ML do último monitor (se houver)
    precos_ml: dict[str, float] = {}
    try:
        snap = ler_json(ROOT / "logs" / "filamentos_ml_ultima.json", default={})
        for r in (snap.get("resultados") or []) if isinstance(snap, dict) else []:
            if not isinstance(r, dict) or not r.get("ok"):
                continue
            mat = str(r.get("material") or "").upper()
            medio = _f(r.get("preco_medio"))
            if mat and medio > 0:
                precos_ml[mat] = medio
        cons = snap.get("consolidado") if isinstance(snap, dict) else {}
        if isinstance(cons, dict):
            for t in cons.get("por_termo") or []:
                mat = str(t.get("material") or "").upper()
                medio = _f(t.get("preco_medio"))
                if mat and medio > 0 and mat not in precos_ml:
                    precos_ml[mat] = medio
    except Exception as exc:
        logger.debug("snapshot ML filamentos: %s", exc)

    # FOB do catálogo Alibaba quando faltar
    fob_ali: dict[str, float] = {}
    try:
        from core.config import ALIBABA_IMPORTACAO_CATALOGO

        ali = ler_json(ROOT / ALIBABA_IMPORTACAO_CATALOGO, default=[])
        for p in ali if isinstance(ali, list) else []:
            if not isinstance(p, dict) or not p.get("ativo"):
                continue
            pid = str(p.get("id") or "")
            if "filamento" not in pid and str(p.get("ramo") or "") != "filamentos":
                continue
            # sem preco_fob no catalogo — usa preco_max_usd * 0.55 como proxy conservador se não houver fob
            fob = _f(p.get("preco_fob_usd") or p.get("fob_usd"))
            if fob <= 0 and _f(p.get("preco_max_usd")) > 0:
                fob = round(_f(p.get("preco_max_usd")) * 0.55, 2)
            if fob > 0:
                fob_ali[pid] = fob
                mat = str(p.get("material") or "").upper()
                if mat and mat not in fob_ali:
                    fob_ali[mat] = fob
    except Exception as exc:
        logger.debug("alibaba filamentos: %s", exc)

    out: list[dict[str, Any]] = []
    for p in base:
        item = dict(p)
        mat = str(item.get("material") or "").upper()
        pid = str(item.get("id") or "")
        if _f(item.get("preco_venda_ml_brl")) <= 0 and mat in precos_ml:
            item["preco_venda_ml_brl"] = precos_ml[mat]
            item["preco_ml_fonte"] = "snapshot_filamentos_ml"
        elif _f(item.get("preco_venda_ml_brl")) > 0:
            item["preco_ml_fonte"] = item.get("preco_ml_fonte") or "catalogo_hub"
        if _f(item.get("fob_usd")) <= 0:
            item["fob_usd"] = fob_ali.get(pid) or fob_ali.get(mat) or 0
        item["fonte_marketplace"] = item.get("fonte_marketplace") or "mercadolivre"
        out.append(item)
    return out


def verificar_custos_operacionais_lucro(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float,
    lucro_alvo_pct: float | None = None,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Verifica se custos operacionais do hub PY permitem margem de trabalho
    com lucro_alvo_pct (default 20%) no preço de marketplace.
    """
    cat = catalogo or carregar_catalogo_hub()
    mk = cat.get("marketplace") or {}
    lucro_alvo = _f(lucro_alvo_pct, _f(mk.get("margem_alvo_lucro_pct"), 20.0))
    taxa = _f(produto.get("taxa_marketplace_pct"), _f(mk.get("taxa_padrao_pct"), 16.0))
    venda = _f(produto.get("preco_venda_ml_brl") or produto.get("preco_venda_brl"))

    aval = avaliar_produto_hub_vs_marketplace(
        produto, cambio_usd_brl=cambio_usd_brl, catalogo=cat
    )
    hub = aval.get("rota_hub_py") or {}
    custo_u = _f(hub.get("custo_unitario_brl"))
    hub_op = hub.get("hub_custos") or {}
    terrestre = hub.get("terrestre_py_br") or {}

    teto = custo_maximo_para_lucro_pct(venda, taxa_marketplace_pct=taxa, lucro_alvo_pct=lucro_alvo)
    piso_venda = preco_minimo_venda_para_lucro_pct(
        custo_u, taxa_marketplace_pct=taxa, lucro_alvo_pct=lucro_alvo
    )

    margem = calcular_margem_revenda(
        venda, custo_u, taxa_marketplace_pct=taxa, margem_minima_pct=lucro_alvo
    ) if venda > 0 and custo_u > 0 else {"ok": False}

    custo_max = _f(teto.get("custo_unitario_maximo_brl"))
    folga_custo = round(custo_max - custo_u, 2) if custo_max > 0 and custo_u > 0 else None
    atinge_20 = bool(margem.get("ok") and _f(margem.get("margem_pct")) >= lucro_alvo)

    # Quebra: quanto do custo é operacional (hub+terrestre+frete china) vs mercadoria
    qty = _i(hub.get("quantidade") or produto.get("quantidade") or 1)
    merc_u = _f(hub.get("mercadoria_brl")) / qty if qty else 0
    frete_china_u = _f(hub.get("frete_china_py_brl")) / qty if qty else 0
    hub_u = _f(hub_op.get("custo_hub_unitario_brl"))
    terr_u = _f(terrestre.get("custo_total_brl")) / qty if qty else 0
    operacional_u = round(frete_china_u + hub_u + terr_u, 2)

    # Overhead mensal diluído no volume do hub (não só neste lote)
    overhead = _f((cat.get("custos_operacionais_brl") or {}).get("overhead_mensal_hub_brl"))
    vol_mes_hub = max(500, qty * 3)  # hipótese: hub gira ≥500 un/mês (multi-SKU)
    overhead_u = round(overhead / vol_mes_hub, 2)
    custo_com_overhead = round(custo_u + overhead_u, 2)
    atinge_20_com_overhead = custo_com_overhead <= custo_max if custo_max > 0 else False

    # Quantidade mínima para atingir lucro alvo (dilui frete terrestre + handling mínimo)
    qty_min = None
    if venda > 0:
        qty_min = _buscar_qty_minima_lucro(
            produto,
            cambio_usd_brl=cambio_usd_brl,
            lucro_alvo_pct=lucro_alvo,
            taxa=taxa,
            catalogo=cat,
        )

    return {
        "ok": bool(aval.get("ok")),
        "produto_id": produto.get("id"),
        "nome": produto.get("nome"),
        "material": produto.get("material"),
        "fonte_marketplace": produto.get("fonte_marketplace") or "mercadolivre",
        "preco_venda_ml_brl": round(venda, 2) if venda > 0 else None,
        "preco_ml_fonte": produto.get("preco_ml_fonte"),
        "lucro_alvo_pct": lucro_alvo,
        "taxa_marketplace_pct": taxa,
        "custo_hub_unitario_brl": round(custo_u, 2),
        "custo_com_overhead_unitario_brl": custo_com_overhead,
        "quebra_custo_unitario_brl": {
            "mercadoria": round(merc_u, 2),
            "frete_china_py": round(frete_china_u, 2),
            "hub_operacional": hub_u,
            "terrestre_py_br": round(terr_u, 2),
            "overhead_mensal_diluido": overhead_u,
            "operacional_sem_mercadoria": operacional_u,
        },
        "teto_custo_para_lucro_alvo": teto,
        "preco_minimo_venda_para_lucro_alvo": piso_venda,
        "quantidade_atual": qty,
        "quantidade_minima_lucro_alvo": qty_min,
        "folga_custo_brl": folga_custo,
        "margem_atual": margem,
        "atinge_lucro_alvo": atinge_20,
        "atinge_lucro_alvo_com_overhead": atinge_20_com_overhead,
        "veredito_operacional": (
            "OK_20PCT"
            if atinge_20_com_overhead
            else ("OK_20PCT_SEM_OVERHEAD" if atinge_20 else "AJUSTAR_CUSTO_OU_PRECO")
        ),
        "avaliacao_completa": aval,
    }


def _buscar_qty_minima_lucro(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float,
    lucro_alvo_pct: float,
    taxa: float,
    catalogo: dict[str, Any],
    qty_max: int = 2000,
) -> int | None:
    """Busca menor quantidade em que custo hub unitário cabe no teto do lucro alvo."""
    venda = _f(produto.get("preco_venda_ml_brl") or produto.get("preco_venda_brl"))
    teto = _f(
        custo_maximo_para_lucro_pct(
            venda, taxa_marketplace_pct=taxa, lucro_alvo_pct=lucro_alvo_pct
        ).get("custo_unitario_maximo_brl")
    )
    if teto <= 0:
        return None
    for q in (50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000):
        if q > qty_max:
            break
        hub = custo_rota_hub_py(
            fob_usd=_f(produto.get("fob_usd")),
            cambio_usd_brl=cambio_usd_brl,
            quantidade=q,
            peso_kg_unit=_f(produto.get("peso_kg"), 1.0),
            volume_m3_unit=_f(produto.get("volume_m3")) if produto.get("volume_m3") is not None else None,
            cep_destino=produto.get("cep_destino"),
            catalogo=catalogo,
        )
        if hub.get("ok") and _f(hub.get("custo_unitario_brl")) <= teto:
            return q
    return None


def verificar_hub_lucro_20_marketplace(
    *,
    cambio_usd_brl: float | None = None,
    lucro_alvo_pct: float = 20.0,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Varre produtos dos marketplaces (filamentos) e valida lucro operacional 20% via hub PY."""
    cat = catalogo or carregar_catalogo_hub()
    if cambio_usd_brl is None:
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            cambio_usd_brl = _f(obter_cotacao_usd().get("usd_brl"), 5.5)
        except Exception:
            cambio_usd_brl = 5.5

    produtos = carregar_produtos_marketplace_hub(cat)
    verificacoes = [
        verificar_custos_operacionais_lucro(
            p, cambio_usd_brl=float(cambio_usd_brl), lucro_alvo_pct=lucro_alvo_pct, catalogo=cat
        )
        for p in produtos
    ]
    ok_20 = [v for v in verificacoes if v.get("atinge_lucro_alvo")]
    ok_oh = [v for v in verificacoes if v.get("atinge_lucro_alvo_com_overhead")]
    hub = endereco_hub_efetivo(cat)

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "lucro_alvo_pct": lucro_alvo_pct,
        "cambio_usd_brl": round(float(cambio_usd_brl), 4),
        "hub": hub,
        "total_produtos_marketplace": len(verificacoes),
        "atingem_lucro_alvo": len(ok_20),
        "atingem_lucro_alvo_com_overhead": len(ok_oh),
        "verificacoes": verificacoes,
        "resumo": {
            "ok_ids": [v.get("produto_id") for v in ok_oh],
            "ajustar_ids": [
                v.get("produto_id")
                for v in verificacoes
                if not v.get("atinge_lucro_alvo_com_overhead")
            ],
        },
        "aviso": (
            f"Lucro alvo {lucro_alvo_pct:.0f}% sobre preço ML após taxa marketplace. "
            "Custos hub PY + terrestre validados por fórmula; impostos Mercosul BR pendentes."
        ),
    }
    gauge("hub_py.lucro20_ok", float(len(ok_oh)))
    gauge("hub_py.lucro20_total", float(len(verificacoes)))
    try:
        escrever_json_atomico(ROOT / "logs" / "hub_paraguai_lucro20_ultima.json", out)
    except OSError as exc:
        logger.debug("snapshot lucro20: %s", exc)
    return out


def avaliar_produto_hub_vs_marketplace(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float,
    catalogo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Para um produto/cliente: calcula hub PY, import direta, margem ML e veredito.
    """
    cat = catalogo or carregar_catalogo_hub()
    mk = cat.get("marketplace") or {}
    fob = _f(produto.get("fob_usd") or produto.get("preco_fob_usd"))
    qty = _i(produto.get("quantidade") or produto.get("moq") or 1)
    peso = _f(produto.get("peso_kg"), 1.0)
    vol = produto.get("volume_m3")
    venda = _f(produto.get("preco_venda_ml_brl") or produto.get("preco_venda_brl"))
    taxa_mk = _f(produto.get("taxa_marketplace_pct"), _f(mk.get("taxa_padrao_pct"), 16.0))
    margem_min = _f(mk.get("margem_alvo_lucro_pct") or mk.get("margem_minima_pct"), 20.0)

    hub = custo_rota_hub_py(
        fob_usd=fob,
        cambio_usd_brl=cambio_usd_brl,
        quantidade=qty,
        peso_kg_unit=peso,
        volume_m3_unit=_f(vol) if vol is not None else None,
        cep_destino=produto.get("cep_destino"),
        catalogo=cat,
    )
    direta = custo_rota_import_direta_br(
        fob_usd=fob,
        cambio_usd_brl=cambio_usd_brl,
        quantidade=qty,
        peso_kg_unit=peso,
        modo_frete=str(produto.get("frete_preferido") or "maritimo"),
    )

    custo_hub_u = _f(hub.get("custo_unitario_brl"))
    custo_dir_u = _f(direta.get("custo_unitario_brl"))
    economia_hub_vs_direta = (
        round(custo_dir_u - custo_hub_u, 2) if custo_hub_u > 0 and custo_dir_u > 0 else None
    )

    margem_hub = (
        calcular_margem_revenda(
            venda, custo_hub_u, taxa_marketplace_pct=taxa_mk, margem_minima_pct=margem_min
        )
        if venda > 0 and custo_hub_u > 0
        else {"ok": False}
    )
    margem_dir = (
        calcular_margem_revenda(
            venda, custo_dir_u, taxa_marketplace_pct=taxa_mk, margem_minima_pct=margem_min
        )
        if venda > 0 and custo_dir_u > 0
        else {"ok": False}
    )

    teto = custo_maximo_para_lucro_pct(venda, taxa_marketplace_pct=taxa_mk, lucro_alvo_pct=margem_min)
    atinge_lucro = bool(margem_hub.get("ok") and _f(margem_hub.get("margem_pct")) >= margem_min)

    if atinge_lucro:
        veredito = "HUB_PY_LUCRO_20"
    elif margem_hub.get("lucro_razoavel"):
        veredito = "HUB_PY_VIAVEL_ML"
    elif margem_dir.get("lucro_razoavel"):
        veredito = "IMPORT_DIRETA_MELHOR"
    elif economia_hub_vs_direta and economia_hub_vs_direta > 0 and venda > 0:
        veredito = "HUB_PY_MAIS_BARATO_MAS_MARGEM_APERTADA"
    else:
        veredito = "REVISAR_PRECO_OU_CUSTO"

    tipo = str(produto.get("tipo_cliente") or "proprio")
    servico = None
    if tipo == "terceiro" and hub.get("ok"):
        base_op = _f(hub.get("custo_total_brl")) - _f(hub.get("mercadoria_brl"))
        servico = taxa_servico_cliente(max(0.0, base_op), catalogo=cat)

    # Cruzamento tributário PY × BR (Mercosul II=0 vs sem origem vs China)
    trib_cruz = None
    try:
        from integracoes.importacao.tributacao_py_br import cruzar_tributacao_py_br_produto

        frete_cn = _f(hub.get("frete_china_py_brl"))
        hub_tot = _f((hub.get("hub_custos") or {}).get("custo_hub_total_brl"))
        terr_tot = _f((hub.get("terrestre_py_br") or {}).get("custo_total_brl"))
        log_u = (hub_tot + terr_tot) / qty if qty > 0 else 0.0
        trib_cruz = cruzar_tributacao_py_br_produto(
            fob_usd=fob,
            cambio_usd_brl=cambio_usd_brl,
            quantidade=qty,
            peso_kg_unit=peso,
            frete_internacional_brl=frete_cn,
            ii_pct_china=_f(produto.get("ii_pct"), 12.6),
            ipi_pct=_f(produto.get("ipi_pct"), 0.0),
            icms_pct=_f(produto.get("icms_pct"), 18.0),
            preco_venda_ml_brl=venda if venda > 0 else None,
            taxa_marketplace_pct=taxa_mk,
            lucro_alvo_pct=margem_min,
            custos_logistica_py_br_unit=log_u,
            regime_maquila=bool(produto.get("regime_maquila")),
        )
        rec = (trib_cruz or {}).get("recomendacao") or {}
        if rec.get("cenario_sugerido") == "py_origem_mercosul" and atinge_lucro:
            veredito = "HUB_PY_ORIGEM_MERCOSUL_LUCRO"
        elif rec.get("cenario_sugerido") == "py_origem_mercosul":
            veredito = "HUB_PY_ORIGEM_MERCOSUL_PREFERIVEL"
    except Exception as exc:
        logger.debug("cruzamento trib PY×BR: %s", exc)

    return {
        "ok": bool(hub.get("ok")),
        "produto_id": produto.get("id"),
        "nome": produto.get("nome"),
        "cliente_id": produto.get("cliente_id"),
        "tipo_cliente": tipo,
        "preco_venda_ml_brl": round(venda, 2) if venda > 0 else None,
        "lucro_alvo_pct": margem_min,
        "custo_maximo_para_lucro_alvo_brl": teto.get("custo_unitario_maximo_brl"),
        "atinge_lucro_alvo": atinge_lucro,
        "rota_hub_py": hub,
        "rota_import_direta_br": direta,
        "economia_hub_vs_direta_unit_brl": economia_hub_vs_direta,
        "margem_marketplace_hub": margem_hub,
        "margem_marketplace_direta": margem_dir,
        "tributacao_py_br": trib_cruz,
        "taxa_servico_terceiro": servico,
        "veredito": veredito,
        "possibilidades": list(cat.get("possibilidades") or []),
    }


def avaliar_hub_multi_cliente(
    *,
    cambio_usd_brl: float | None = None,
    produtos: list[dict[str, Any]] | None = None,
    catalogo: dict[str, Any] | None = None,
    lucro_alvo_pct: float = 20.0,
) -> dict[str, Any]:
    """Varredura do catálogo hub: produtos marketplace × custos × lucro 20%."""
    cat = catalogo or carregar_catalogo_hub()
    if cambio_usd_brl is None:
        try:
            from integracoes.cambio.cotacao_usd import obter_cotacao_usd

            cambio_usd_brl = _f(obter_cotacao_usd().get("usd_brl"), 5.5)
        except Exception:
            cambio_usd_brl = 5.5

    hub = endereco_hub_efetivo(cat)
    if produtos is None:
        itens_src = carregar_produtos_marketplace_hub(cat)
    else:
        itens_src = list(produtos)
    clientes = {c.get("id"): c for c in (cat.get("clientes_exemplo") or []) if isinstance(c, dict)}

    analises = []
    verificacoes = []
    for p in itens_src:
        if not isinstance(p, dict) or not p.get("ativo", True):
            continue
        cli = clientes.get(p.get("cliente_id")) or {}
        prod = {
            **p,
            "tipo_cliente": cli.get("tipo") or p.get("tipo_cliente") or "proprio",
        }
        analises.append(
            avaliar_produto_hub_vs_marketplace(prod, cambio_usd_brl=float(cambio_usd_brl), catalogo=cat)
        )
        verificacoes.append(
            verificar_custos_operacionais_lucro(
                prod,
                cambio_usd_brl=float(cambio_usd_brl),
                lucro_alvo_pct=lucro_alvo_pct,
                catalogo=cat,
            )
        )

    lucro_servico = sum(
        _f((a.get("taxa_servico_terceiro") or {}).get("lucro_servico_brl"))
        for a in analises
    )
    lucrativos_ml = sum(1 for a in analises if a.get("atinge_lucro_alvo"))
    hub_mais_barato = sum(
        1
        for a in analises
        if a.get("economia_hub_vs_direta_unit_brl") is not None
        and _f(a.get("economia_hub_vs_direta_unit_brl")) > 0
    )

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "status_hub": hub.get("status_hub"),
        "hub": hub,
        "cambio_usd_brl": round(float(cambio_usd_brl), 4),
        "lucro_alvo_pct": lucro_alvo_pct,
        "total_produtos": len(analises),
        "lucrativos_marketplace_hub": lucrativos_ml,
        "atingem_lucro_20_com_overhead": sum(
            1 for v in verificacoes if v.get("atinge_lucro_alvo_com_overhead")
        ),
        "hub_mais_barato_que_direta": hub_mais_barato,
        "receita_servico_terceiros_brl": round(lucro_servico, 2),
        "analises": analises,
        "verificacao_custos_operacionais": verificacoes,
        "clientes": list(clientes.values()),
        "possibilidades": cat.get("possibilidades") or [],
        "aviso_legal": cat.get("aviso_legal")
        or hub.get("aviso_legal")
        or "Estimativa de planejamento — validar compliance Mercosul.",
    }

    tags = ["hub:py", "cidade:cde"]
    gauge("hub_py.produtos", float(len(analises)), tags)
    gauge("hub_py.lucrativos_ml", float(lucrativos_ml), tags)
    gauge("hub_py.receita_servico_brl", float(lucro_servico), tags)
    incrementar("hub_py.avaliacao_ok", tags=tags)
    try:
        escrever_json_atomico(SNAPSHOT_PATH, out)
    except OSError as exc:
        logger.debug("snapshot hub: %s", exc)
    return out


def formatar_hub_py_telegram(resultado: dict[str, Any], *, max_itens: int = 6) -> str:
    if not resultado.get("ok"):
        return f"Hub PY: falhou — {resultado.get('motivo', '?')}"

    hub = (resultado.get("hub") or {}).get("endereco") or {}
    lucro_alvo = resultado.get("lucro_alvo_pct") or 20
    linhas = [
        "🇵🇾 *Hub Paraguai × Marketplaces*",
        f"Status: `{resultado.get('status_hub')}` · "
        f"{hub.get('cidade')} — {hub.get('endereco')}",
        f"CEP BR: `{(resultado.get('hub') or {}).get('cep_destino_br_padrao')}` · "
        f"lucro alvo *{lucro_alvo:.0f}%*",
        f"Câmbio: R$ {resultado.get('cambio_usd_brl')}",
        f"Produtos MK: {resultado.get('total_produtos')} · "
        f"≥{lucro_alvo:.0f}%: *{resultado.get('lucrativos_marketplace_hub')}* · "
        f"c/ overhead: {resultado.get('atingem_lucro_20_com_overhead')}",
        "",
    ]
    verifs = resultado.get("verificacao_custos_operacionais") or []
    fonte = verifs if verifs else (resultado.get("analises") or [])
    for v in fonte[:max_itens]:
        if "quebra_custo_unitario_brl" in v:
            q = v.get("quebra_custo_unitario_brl") or {}
            m = v.get("margem_atual") or {}
            linhas.append(
                f"{'✅' if v.get('atinge_lucro_alvo_com_overhead') else '⚠️'} "
                f"*{v.get('nome') or v.get('produto_id')}* → `{v.get('veredito_operacional')}`\n"
                f"  Venda ML R$ {v.get('preco_venda_ml_brl')} · custo hub R$ {v.get('custo_hub_unitario_brl')} "
                f"(teto R$ {(v.get('teto_custo_para_lucro_alvo') or {}).get('custo_unitario_maximo_brl')})\n"
                f"  Op: freteCN R$ {q.get('frete_china_py')} · hub R$ {q.get('hub_operacional')} · "
                f"terr R$ {q.get('terrestre_py_br')} · margem {m.get('margem_pct')}%\n"
                f"  Preço mín p/ {lucro_alvo:.0f}%: R$ "
                f"{(v.get('preco_minimo_venda_para_lucro_alvo') or {}).get('preco_venda_minimo_brl')}"
                + (
                    f" · qty mín {v.get('quantidade_minima_lucro_alvo')}"
                    if v.get("quantidade_minima_lucro_alvo")
                    else ""
                )
            )
        else:
            hub_c = (v.get("rota_hub_py") or {}).get("custo_unitario_brl")
            m = v.get("margem_marketplace_hub") or {}
            linhas.append(
                f"• *{v.get('nome') or v.get('produto_id')}* → `{v.get('veredito')}`\n"
                f"  Hub R$ {hub_c} · margem ML R$ {m.get('margem_brl')} ({m.get('margem_pct')}%)"
            )
    linhas.append(f"_{resultado.get('aviso_legal') or resultado.get('aviso')}_")
    return "\n".join(linhas)

