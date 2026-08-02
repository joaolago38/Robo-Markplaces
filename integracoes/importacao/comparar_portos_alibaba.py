"""
integracoes/importacao/comparar_portos_alibaba.py
Compara condições de importação aéreo/marítimo em qualquer porto/aeroporto
do Brasil, sempre com estrutura Alibaba (FOB USD) como referência.

Qualquer produto ofertado no território brasileiro (ou via catálogo Alibaba)
pode ser avaliado: calcula landed por gateway e ranqueia condições atrativas.
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.horario import agora_brasil
from integracoes.importacao.custo_landed import calcular_custo_landed
from integracoes.importacao.portos_brasil import (
    distancia_km_para_cep,
    gateway_por_codigo,
    icms_gateway,
    listar_gateways,
    resumo_estrutura_gateway,
)

logger = logging.getLogger("comparar_portos_alibaba")

SNAPSHOT_PATH = ROOT / "logs" / "comparar_portos_alibaba_ultima.json"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
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


def normalizar_produto_alibaba(produto: dict[str, Any] | None) -> dict[str, Any]:
    """
    Aceita produto do catálogo Alibaba, oportunidade de busca ou
    oferta genérica em território BR (preço FOB/USD + peso).
    """
    p = dict(produto or {})
    preco = p.get("preco_fob_usd")
    if preco is None:
        preco = p.get("preco_usd") or p.get("price_usd") or p.get("fob_usd")
    unidade = max(1, _i(p.get("unidade_por_preco"), 1))
    fob = _f(preco)
    if fob > 0 and unidade > 1:
        fob = fob / unidade

    return {
        "id": p.get("id") or p.get("sku") or p.get("product_id") or "produto",
        "nome": p.get("nome") or p.get("titulo") or p.get("title") or "Produto Alibaba",
        "preco_fob_usd": fob,
        "peso_kg": max(0.01, _f(p.get("peso_kg") or p.get("weight_kg"), 1.0)),
        "quantidade": _i(p.get("moq") or p.get("moq_referencia") or p.get("quantidade"), 1),
        "ncm": str(p.get("ncm") or ""),
        "ii_pct": _f(p.get("ii_pct"), 16.0),
        "ipi_pct": _f(p.get("ipi_pct"), 0.0),
        "icms_pct": p.get("icms_pct"),
        "origem": "alibaba" if (
            p.get("termo_busca") or p.get("alibaba") or "alibaba" in str(p.get("fonte") or "").lower()
        ) else str(p.get("fonte") or "territorio_br_ou_alibaba"),
        "territorio": "BR",
        "raw_keys": sorted(p.keys())[:20],
    }


def calcular_landed_no_gateway(
    produto_norm: dict[str, Any],
    gateway: dict[str, Any],
    *,
    cambio_usd_brl: float,
    cep_destino: str | None = None,
    uf_destino: str | None = None,
) -> dict[str, Any]:
    """Landed cost no gateway (aéreo ou marítimo) com estrutura Alibaba."""
    modal = str(gateway.get("tipo") or "maritimo")
    if modal not in ("aereo", "maritimo"):
        modal = "maritimo"

    km = distancia_km_para_cep(str(gateway.get("codigo") or ""), cep_destino)
    custos = gateway.get("custos_locais_brl") or {}
    from integracoes.importacao.siscomex import calcular_taxa_siscomex

    try:
        adicoes = int(getattr(_cfg(), "IMPORTACAO_SISCOMEX_ADICOES", 1) or 1)
    except (TypeError, ValueError):
        adicoes = 1
    adicoes = max(1, adicoes)
    siscomex_detalhe = calcular_taxa_siscomex(adicoes=adicoes)
    # Catálogo pode ter legado 214.50 — ignora e usa regra vigente
    siscomex_cat = _f(custos.get("siscomex"))
    if siscomex_cat > 0 and abs(siscomex_cat - 214.5) >= 0.01 and abs(siscomex_cat - 154.23) >= 0.01:
        # valor customizado explícito (não legado nem default 1 adição)
        siscomex_brl = siscomex_cat
    else:
        siscomex_brl = float(siscomex_detalhe["total_brl"])

    locais_sem_siscomex = sum(
        _f(custos.get(k))
        for k in ("armazenagem", "desembaraco", "thc_manuseio", "outros")
    )
    locais = locais_sem_siscomex + siscomex_brl
    frete_interno_unit = (km * _f(gateway.get("frete_interno_brl_por_km"), 5.0)) / max(
        1, _i(produto_norm.get("quantidade"))
    )
    qty = _i(produto_norm.get("quantidade"))

    icms = _f(produto_norm.get("icms_pct"))
    if icms <= 0:
        icms = icms_gateway(gateway, uf_destino)

    frete_usd_kg = _f(gateway.get("frete_internacional_usd_kg"), 0.85 if modal == "maritimo" else 5.5)
    afrmm_pct = float(getattr(_cfg(), "IMPORTACAO_AFRMM_PCT", 8.0)) if modal == "maritimo" else 0.0

    landed = calcular_custo_landed(
        produto_norm["preco_fob_usd"],
        cambio_usd_brl=cambio_usd_brl,
        peso_kg_unit=produto_norm["peso_kg"],
        quantidade=qty,
        modo_frete=modal,  # type: ignore[arg-type]
        ii_pct=_f(produto_norm.get("ii_pct"), 16.0),
        ipi_pct=_f(produto_norm.get("ipi_pct"), 0.0),
        pis_pct=float(getattr(_cfg(), "IMPORTACAO_PIS_PCT", 2.1)),
        cofins_pct=float(getattr(_cfg(), "IMPORTACAO_COFINS_PCT", 9.65)),
        icms_pct=icms,
        frete_maritimo_usd_kg=frete_usd_kg if modal == "maritimo" else 0.85,
        frete_aereo_usd_kg=frete_usd_kg if modal == "aereo" else 5.5,
        siscomex_brl=siscomex_brl,
        siscomex_adicoes=adicoes,
        desembaraco_brl=locais_sem_siscomex,
        frete_nacional_brl_unit=frete_interno_unit,
        afrmm_pct=afrmm_pct,
    )
    if not landed.get("ok"):
        return {**landed, "gateway": resumo_estrutura_gateway(gateway)}

    detalhe_custos = _detalhar_custos(
        landed,
        locais=locais,
        frete_interno_total=frete_interno_unit * qty,
    )
    score_atrativo = _score_atratividade(
        landed_unit=_f(landed.get("custo_unitario_brl")),
        fob_usd=_f(produto_norm.get("preco_fob_usd")),
        cambio=cambio_usd_brl,
        atratividade_cat=_f(gateway.get("atratividade"), 50),
        modal=modal,
        detalhe_custos=detalhe_custos,
    )
    assertividade = _assertividade_pct(score_atrativo, detalhe_custos)

    return {
        "ok": True,
        "referencia": "alibaba",
        "modal": modal,
        "gateway": resumo_estrutura_gateway(gateway),
        "cep_destino": cep_destino,
        "distancia_km": round(km, 1),
        "frete_interno_brl_unit": round(frete_interno_unit, 2),
        "custos_locais_brl": round(locais, 2),
        "custo_unitario_brl": landed.get("custo_unitario_brl"),
        "custo_total_brl": landed.get("custo_total_brl"),
        "cif_brl": landed.get("cif_brl"),
        "valor_aduaneiro_cif_brl": landed.get("valor_aduaneiro_cif_brl") or landed.get("cif_brl"),
        "impostos_total_brl": landed.get("impostos_total_brl"),
        "frete_internacional_brl": landed.get("frete_internacional_brl"),
        "despesas_aduaneiras_inclusas": True,
        "despesas_aduaneiras": {
            "ii_brl": landed.get("ii_brl"),
            "ipi_brl": landed.get("ipi_brl"),
            "pis_brl": landed.get("pis_brl"),
            "cofins_brl": landed.get("cofins_brl"),
            "pis_cofins_brl": landed.get("pis_cofins_brl"),
            "icms_brl": landed.get("icms_brl"),
            "siscomex_brl": siscomex_brl,
            "siscomex_adicoes": adicoes,
            "siscomex_detalhe": siscomex_detalhe,
            "armazenagem_thc_desembaraco_brl": round(locais_sem_siscomex, 2),
            "afrmm_brl": landed.get("afrmm_brl"),
            "afrmm_pct": landed.get("afrmm_pct"),
            "total_impostos_brl": landed.get("impostos_total_brl"),
            "total_despesas_aduaneiras_brl": landed.get("despesas_aduaneiras_brl"),
        },
        "referencia_legislacao_br": landed.get("referencia_legislacao_br"),
        "detalhe_custos": detalhe_custos,
        "custos_considerados": bool(detalhe_custos.get("completo")),
        "score_atratividade": score_atrativo,
        "assertividade_pct": assertividade,
        "exige_revisao_custo": assertividade < _assertividade_alvo(),
        "landed": landed,
    }


def _assertividade_alvo() -> float:
    return float(getattr(_cfg(), "IMPORTACAO_PORTOS_ASSERTIVIDADE_ALVO", 90.0))


def _detalhar_custos(
    landed: dict[str, Any],
    *,
    locais: float,
    frete_interno_total: float,
) -> dict[str, Any]:
    """Quebra o landed para garantir que cada bloco de custo entra na assertividade."""
    total = _f(landed.get("custo_total_brl"))
    frete_int = _f(landed.get("frete_internacional_brl"))
    impostos = _f(landed.get("impostos_total_brl"))
    seguro = _f(landed.get("seguro_brl"))
    fob = _f(landed.get("fob_brl_total"))
    frete_nac = _f(landed.get("frete_nacional_brl"), frete_interno_total)

    def _pct(v: float) -> float:
        return round(v / total * 100.0, 2) if total > 0 else 0.0

    blocos = {
        "fob_brl": round(fob, 2),
        "frete_internacional_brl": round(frete_int, 2),
        "seguro_brl": round(seguro, 2),
        "impostos_brl": round(impostos, 2),
        "afrmm_brl": round(_f(landed.get("afrmm_brl")), 2),
        "custos_locais_brl": round(locais, 2),
        "frete_nacional_brl": round(frete_nac, 2),
    }
    # Completo = todos os blocos estruturais presentes (podem ser 0 só se qty inválida)
    completo = total > 0 and all(
        k in blocos for k in (
            "fob_brl",
            "frete_internacional_brl",
            "impostos_brl",
            "custos_locais_brl",
            "frete_nacional_brl",
        )
    )
    # Soma coerente (tolerância 2%)
    soma = sum(blocos.values())
    coerente = total > 0 and abs(soma - total) / total <= 0.05

    return {
        "completo": completo,
        "coerente": coerente,
        "custo_total_brl": round(total, 2),
        "blocos": blocos,
        "pct": {k: _pct(v) for k, v in blocos.items()},
        "markup_sobre_fob": round(
            _f(landed.get("custo_unitario_brl"))
            / max(0.01, _f(landed.get("fob_usd_unit")) * _f(landed.get("cambio_usd_brl"))),
            3,
        ),
    }


def _score_atratividade(
    *,
    landed_unit: float,
    fob_usd: float,
    cambio: float,
    atratividade_cat: float,
    modal: str,
    detalhe_custos: dict[str, Any] | None = None,
) -> float:
    """
    Score 0–100 baseado em custos.
    Se assertividade de custo puro < 90%, o peso do custo sobe (≥85%) e
    o hub do catálogo quase não conta — evita decisão 'bonita' sem landed real.
    """
    fob_brl = max(0.01, fob_usd * cambio)
    markup = landed_unit / fob_brl if fob_brl else 99.0
    # markup 1.3 → bom; 2.5+ → ruim
    score_custo = max(0.0, min(100.0, 100.0 - (markup - 1.2) * 80.0))

    det = detalhe_custos or {}
    if not det.get("completo"):
        score_custo *= 0.5  # sem detalhe de custo → assertividade cai
    elif not det.get("coerente"):
        score_custo *= 0.75

    # Assertividade preliminar só de custo
    if score_custo < _assertividade_alvo():
        peso_custo = float(getattr(_cfg(), "IMPORTACAO_PORTOS_PESO_CUSTO_BAIXA_ASSERT", 0.85))
        peso_custo = min(0.95, max(0.85, peso_custo))
        peso_cat = 1.0 - peso_custo
    else:
        peso_custo = 0.65
        peso_cat = 0.35

    base = peso_custo * score_custo + peso_cat * atratividade_cat
    if modal == "maritimo" and markup < 1.8:
        base += 3.0
    if modal == "aereo" and markup < 1.6:
        base += 2.0
    # Sem custos locais/frete considerados, cap abaixo de 90
    if not det.get("completo"):
        base = min(base, _assertividade_alvo() - 0.1)
    return round(min(100.0, max(0.0, base)), 1)


def _assertividade_pct(score: float, detalhe_custos: dict[str, Any]) -> float:
    """
    Assertividade final: não passa de 90% se custos incompletos ou markup alto.
    """
    alvo = _assertividade_alvo()
    a = float(score)
    if not detalhe_custos.get("completo") or not detalhe_custos.get("coerente"):
        a = min(a, alvo - 0.1)
    markup = _f(detalhe_custos.get("markup_sobre_fob"), 99.0)
    max_markup = float(getattr(_cfg(), "IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA", 2.2))
    if markup > max_markup:
        a = min(a, alvo - 5.0)
    return round(min(100.0, max(0.0, a)), 1)


def eh_condicao_atrativa(cenario: dict[str, Any]) -> bool:
    """
    Atrativa de verdade:
      - score mínimo
      - markup dentro do limite
      - custos detalhados considerados
      - se assertividade < 90%, só atrativa_condicional (retorna False para 'top atrativos'
        de alta confiança; use eh_condicao_atrativa_condicional)
    """
    cfg = _cfg()
    min_score = float(getattr(cfg, "IMPORTACAO_PORTOS_SCORE_MIN_ATRATIVA", 55.0))
    max_markup = float(getattr(cfg, "IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA", 2.2))
    alvo = _assertividade_alvo()
    if not cenario.get("ok"):
        return False
    if not cenario.get("custos_considerados", True):
        return False
    det = cenario.get("detalhe_custos") or {}
    if not det.get("completo"):
        return False
    if _f(cenario.get("score_atratividade")) < min_score:
        return False
    landed = cenario.get("landed") or {}
    fob = _f(landed.get("fob_usd_unit"))
    cambio = _f(landed.get("cambio_usd_brl"), 1.0)
    unit = _f(cenario.get("custo_unitario_brl"))
    if fob > 0 and cambio > 0 and unit / (fob * cambio) > max_markup:
        return False
    # Alta confiança só com assertividade ≥ 90%
    assertiv = _f(cenario.get("assertividade_pct"), _f(cenario.get("score_atratividade")))
    return assertiv >= alvo


def eh_condicao_atrativa_condicional(cenario: dict[str, Any]) -> bool:
    """Abaixo de 90%: ainda útil, mas só se custos completos e markup ok."""
    if eh_condicao_atrativa(cenario):
        return True
    if not cenario.get("ok") or not cenario.get("custos_considerados"):
        return False
    det = cenario.get("detalhe_custos") or {}
    if not det.get("completo"):
        return False
    min_score = float(getattr(_cfg(), "IMPORTACAO_PORTOS_SCORE_MIN_ATRATIVA", 55.0))
    if _f(cenario.get("score_atratividade")) < min_score:
        return False
    max_markup = float(getattr(_cfg(), "IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA", 2.2))
    if _f(det.get("markup_sobre_fob")) > max_markup:
        return False
    assertiv = _f(cenario.get("assertividade_pct"))
    return 0 < assertiv < _assertividade_alvo()


def comparar_portos_para_produto_alibaba(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float | None = None,
    cep_destino: str | None = None,
    uf_destino: str | None = None,
    modal: str = "todos",
    codigos: list[str] | None = None,
    top_n: int = 8,
    rota_china_regional: bool | None = None,
) -> dict[str, Any]:
    """
    Ranqueia portos/aeroportos do BR para o produto Alibaba.

    Marítimo China (padrão):
      - Sudeste/Centro-Oeste → Santos
      - Nordeste → portos NE
      - Compara tributação com portos do Sul
    """
    from integracoes.cambio.cotacao_usd import (
        cotacao_confiavel_para_margem,
        obter_cotacao_usd,
    )
    from integracoes.importacao.operacao_destino import normalizar_cep, resumo_destino
    from integracoes.importacao.rotas_regionais_china import (
        codigos_para_avaliacao_china,
        comparar_tributacao_regional,
        portos_preferidos_china,
    )

    prod = normalizar_produto_alibaba(produto)
    if prod["preco_fob_usd"] <= 0:
        return {"ok": False, "motivo": "produto_sem_fob_usd_alibaba", "produto": prod}

    dest = resumo_destino()
    cep = normalizar_cep(cep_destino or dest.get("destino_cep") or "13467-694")
    uf = (uf_destino or dest.get("destino_uf") or "SP").upper()

    cfg = _cfg()
    usar_rota = (
        bool(getattr(cfg, "IMPORTACAO_CHINA_ROTA_REGIONAL", True))
        if rota_china_regional is None
        else bool(rota_china_regional)
    )

    if cambio_usd_brl is None:
        cot = obter_cotacao_usd(usar_cache=True)
        if not cotacao_confiavel_para_margem(cot):
            return {
                "ok": False,
                "motivo": "cambio_nao_confiavel",
                "produto": prod,
                "cambio": cot,
            }
        cambio = _f(cot.get("usd_brl"))
        cambio_meta = cot
    else:
        cambio = float(cambio_usd_brl)
        cambio_meta = {"ok": True, "usd_brl": cambio, "fonte": "parametro"}

    gateways: list[dict[str, Any]] = []
    if codigos:
        for c in codigos:
            g = gateway_por_codigo(c)
            if g and g.get("ativo", True):
                gateways.append(g)
    else:
        modal_f = modal if modal in ("aereo", "maritimo", "todos") else "todos"
        if modal_f in ("maritimo", "todos") and usar_rota:
            # Marítimo China: só hubs regionais + Sul (tributação)
            for c in codigos_para_avaliacao_china(uf, incluir_sul_comparativo=True):
                g = gateway_por_codigo(c)
                if g and g.get("ativo", True):
                    gateways.append(g)
            if modal_f == "todos":
                for g in listar_gateways(modal="aereo"):
                    gateways.append(g)
        else:
            gateways = listar_gateways(modal=modal_f)  # type: ignore[arg-type]

    # Dedup por código
    vistos: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for g in gateways:
        cod = str(g.get("codigo") or "").upper()
        if cod and cod not in vistos:
            vistos.add(cod)
            uniq.append(g)
    gateways = uniq

    cenarios: list[dict[str, Any]] = []
    for g in gateways:
        try:
            cenarios.append(
                calcular_landed_no_gateway(
                    prod, g, cambio_usd_brl=cambio, cep_destino=cep, uf_destino=uf
                )
            )
        except Exception as exc:
            logger.debug("gateway %s: %s", g.get("codigo"), exc)

    ok_list = [c for c in cenarios if c.get("ok")]
    # Ranking: quem exige revisão de custo (<90%) ordena primeiro por custo unitário
    ok_list.sort(
        key=lambda c: (
            0 if c.get("exige_revisao_custo") else 1,
            _f(c.get("custo_unitario_brl"), 1e9) if c.get("exige_revisao_custo") else 0,
            -_f(c.get("assertividade_pct"), _f(c.get("score_atratividade"))),
            _f(c.get("custo_unitario_brl"), 1e9),
        )
    )

    atrativas = [c for c in ok_list if eh_condicao_atrativa(c)]
    condicionais = [
        c for c in ok_list
        if eh_condicao_atrativa_condicional(c) and not eh_condicao_atrativa(c)
    ]
    melhor_aereo = next((c for c in ok_list if c.get("modal") == "aereo"), None)

    trib_china = comparar_tributacao_regional(ok_list, uf_destino=uf) if usar_rota else {"ok": False}
    rota_pref = portos_preferidos_china(uf)

    # Marítimo: prioriza hub regional (Santos no SE / NE ports) se existir
    melhor_maritimo = None
    if trib_china.get("ok") and trib_china.get("melhor_regiao"):
        cod_reg = str((trib_china["melhor_regiao"] or {}).get("codigo") or "")
        melhor_maritimo = next(
            (
                c for c in ok_list
                if c.get("modal") == "maritimo"
                and str((c.get("gateway") or {}).get("codigo") or "").upper() == cod_reg
            ),
            None,
        )
    if melhor_maritimo is None:
        melhor_maritimo = next((c for c in ok_list if c.get("modal") == "maritimo"), None)

    melhor_geral = atrativas[0] if atrativas else next(
        (c for c in ok_list if c.get("custos_considerados")), None
    )
    # Se marítimo regional for o foco China e assertividade ok, prefira-o no geral quando modal marítimo
    if usar_rota and modal in ("maritimo", "todos") and melhor_maritimo and melhor_maritimo.get("custos_considerados"):
        if not melhor_geral or melhor_geral.get("modal") != "maritimo":
            melhor_geral = melhor_maritimo

    from integracoes.importacao.portos_brasil import cobertura_costa_brasil

    costa = cobertura_costa_brasil()

    # Corredor Paraguai terrestre (se ativo)
    py_terrestre: dict[str, Any] = {"ok": False}
    try:
        from core import config as cfg

        if bool(getattr(cfg, "IMPORTACAO_PY_ATIVO", True)):
            from integracoes.importacao.corredor_paraguai_terrestre import (
                montar_cenario_py_terrestre_br,
            )

            fob = _f(prod.get("preco_fob_usd"))
            qty = _i(prod.get("quantidade"))
            py_terrestre = montar_cenario_py_terrestre_br(
                valor_mercadoria_brl=fob * qty * cambio,
                quantidade=qty,
                cep_destino=cep,
                fob_usd=fob,
                cambio_usd_brl=cambio,
            )
    except Exception as exc:
        logger.debug("py terrestre: %s", exc)
        py_terrestre = {"ok": False, "erro": str(exc)}

    out = {
        "ok": bool(ok_list),
        "gerado_em": agora_brasil().isoformat(),
        "referencia": "alibaba",
        "territorio": "BR",
        "assertividade_alvo_pct": _assertividade_alvo(),
        "cobertura_costa_brasil": costa,
        "rota_china_regional": {
            "ativa": usar_rota,
            "regiao": rota_pref.get("regiao"),
            "porto_principal": rota_pref.get("porto_principal"),
            "motivo": rota_pref.get("motivo"),
            "portos_preferidos": rota_pref.get("portos_preferidos"),
            "portos_sul_comparativo": rota_pref.get("portos_sul_comparativo_tributacao"),
        },
        "tributacao_regiao_vs_sul": trib_china,
        "produto": prod,
        "cambio": {"usd_brl": cambio, **{k: cambio_meta.get(k) for k in ("fonte", "confiavel", "ok")}},
        "destino": {"cep": cep, "uf": uf},
        "total_gateways_avaliados": len(cenarios),
        "total_atrativos": len(atrativas),
        "total_condicionais_custo": len(condicionais),
        "melhor_geral": _resumo_cenario(melhor_geral),
        "melhor_aereo": _resumo_cenario(melhor_aereo),
        "melhor_maritimo": _resumo_cenario(melhor_maritimo),
        "top_atrativos": [_resumo_cenario(c) for c in atrativas[:top_n]],
        "top_condicionais": [_resumo_cenario(c) for c in condicionais[:top_n]],
        "ranking": [_resumo_cenario(c) for c in ok_list[: max(top_n, 12)]],
        "paraguai_terrestre": {
            "ok": bool(py_terrestre.get("ok")),
            "endereco": ((py_terrestre.get("paraguai_endereco_comercial") or {}).get("endereco")),
            "melhor_corredor": py_terrestre.get("melhor_corredor"),
            "cobertura_costa_pct": py_terrestre.get("cobertura_costa_brasil_pct"),
        },
        "aviso": (
            "Custos estimados por porto/aeroporto BR · referência FOB Alibaba. "
            f"Costa BR coberta: {costa.get('cobertura_pct')}% dos hubs de referência. "
            f"Assertividade ≥{_assertividade_alvo():.0f}% = alta confiança; "
            "abaixo disso a decisão exige detalhe de custo. "
            "Corredor PY terrestre disponível (Ciudad del Este → Foz → CEP BR). "
            f"Rota China: {rota_pref.get('motivo')} · "
            f"tributação vs Sul: {trib_china.get('veredito') or 'n/d'}."
        ),
    }

    _emitir_metricas(out)
    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out


def _resumo_cenario(c: dict[str, Any] | None) -> dict[str, Any] | None:
    if not c or not c.get("ok"):
        return None
    g = c.get("gateway") or {}
    det = c.get("detalhe_custos") or {}
    return {
        "codigo": g.get("codigo"),
        "nome": g.get("nome"),
        "cidade": g.get("cidade"),
        "uf": g.get("uf"),
        "modal": c.get("modal"),
        "custo_unitario_brl": c.get("custo_unitario_brl"),
        "custo_total_brl": c.get("custo_total_brl"),
        "score_atratividade": c.get("score_atratividade"),
        "assertividade_pct": c.get("assertividade_pct"),
        "custos_considerados": c.get("custos_considerados"),
        "exige_revisao_custo": c.get("exige_revisao_custo"),
        "atrativa": eh_condicao_atrativa(c),
        "atrativa_condicional": eh_condicao_atrativa_condicional(c),
        "markup_sobre_fob": det.get("markup_sobre_fob"),
        "detalhe_custos_pct": det.get("pct"),
        "distancia_km": c.get("distancia_km"),
        "frete_internacional_brl": c.get("frete_internacional_brl"),
        "custos_locais_brl": c.get("custos_locais_brl"),
    }


def _emitir_metricas(out: dict[str, Any]) -> None:
    tags = ["referencia:alibaba", "territorio:BR"]
    melhor = out.get("melhor_geral") or {}
    if melhor.get("modal"):
        tags.append(f"modal:{melhor['modal']}")
    if melhor.get("codigo"):
        tags.append(f"gateway:{str(melhor['codigo'])[:12]}")
    gauge("portos_alibaba.gateways_avaliados", float(out.get("total_gateways_avaliados") or 0), tags)
    gauge("portos_alibaba.atrativos", float(out.get("total_atrativos") or 0), tags)
    gauge(
        "portos_alibaba.condicionais_custo",
        float(out.get("total_condicionais_custo") or 0),
        tags,
    )
    if melhor.get("custo_unitario_brl") is not None:
        gauge("portos_alibaba.melhor_custo_unit", float(melhor["custo_unitario_brl"]), tags)
    if melhor.get("score_atratividade") is not None:
        gauge("portos_alibaba.melhor_score", float(melhor["score_atratividade"]), tags)
    if melhor.get("assertividade_pct") is not None:
        gauge("portos_alibaba.melhor_assertividade", float(melhor["assertividade_pct"]), tags)
    gauge(
        "portos_alibaba.assertividade_alvo",
        float(out.get("assertividade_alvo_pct") or 90),
        tags,
    )
    costa = out.get("cobertura_costa_brasil") or {}
    if costa.get("cobertura_pct") is not None:
        gauge("portos_alibaba.cobertura_costa_pct", float(costa["cobertura_pct"]), tags)
    incrementar("portos_alibaba.comparacao_ok" if out.get("ok") else "portos_alibaba.comparacao_erro", tags=tags)


def formatar_comparacao_telegram(resultado: dict[str, Any], *, max_linhas: int = 6) -> str:
    """Card curto para Telegram."""
    if not resultado.get("ok"):
        return f"_Comparação portos Alibaba falhou: `{resultado.get('motivo')}`_"

    prod = resultado.get("produto") or {}
    linhas = [
        "🚢✈️ *Portos BR × Alibaba*",
        f"Produto: *{prod.get('nome')}* · FOB US$ {prod.get('preco_fob_usd')}",
        f"USD R$ {(resultado.get('cambio') or {}).get('usd_brl')} · "
        f"CEP `{(resultado.get('destino') or {}).get('cep')}`",
        f"Avaliados: *{resultado.get('total_gateways_avaliados')}* · "
        f"Costa BR: *{(resultado.get('cobertura_costa_brasil') or {}).get('cobertura_pct')}%* · "
        f"Atrativos (≥{resultado.get('assertividade_alvo_pct') or 90}%): "
        f"*{resultado.get('total_atrativos')}* · "
        f"Condicionais: *{resultado.get('total_condicionais_custo')}*",
    ]
    melhor = resultado.get("melhor_geral")
    if melhor:
        rev = " · _revisar custo_" if melhor.get("exige_revisao_custo") else ""
        linhas.append(
            f"✅ Melhor: *{melhor.get('codigo')}* {melhor.get('nome')} "
            f"({melhor.get('modal')}) · R$ {melhor.get('custo_unitario_brl')}/un · "
            f"assert. {melhor.get('assertividade_pct')}%{rev}"
        )
        pct = melhor.get("detalhe_custos_pct") or {}
        if pct:
            linhas.append(
                f"  Custos: frete {pct.get('frete_internacional_brl', 0)}% · "
                f"impostos {pct.get('impostos_brl', 0)}% · "
                f"locais {pct.get('custos_locais_brl', 0)}% · "
                f"FOB {pct.get('fob_brl', 0)}%"
            )
    ma = resultado.get("melhor_aereo")
    mm = resultado.get("melhor_maritimo")
    if ma:
        linhas.append(
            f"✈️ Aéreo: `{ma.get('codigo')}` R$ {ma.get('custo_unitario_brl')}/un "
            f"(assert. {ma.get('assertividade_pct')}%)"
        )
    if mm:
        linhas.append(
            f"🚢 Marítimo: `{mm.get('codigo')}` R$ {mm.get('custo_unitario_brl')}/un "
            f"(assert. {mm.get('assertividade_pct')}%)"
        )
    rota = resultado.get("rota_china_regional") or {}
    trib = resultado.get("tributacao_regiao_vs_sul") or {}
    if rota.get("ativa"):
        linhas.append(
            f"🇨🇳 Rota: *{rota.get('regiao')}* → hub `{rota.get('porto_principal')}` "
            f"— _{rota.get('motivo')}_"
        )
    if trib.get("ok"):
        hub = trib.get("hub_principal") or trib.get("melhor_regiao") or {}
        sul = trib.get("melhor_sul_tributacao") or {}
        linhas.append(
            f"📊 Tributação: hub R$ {hub.get('custo_unitario_brl')}/un "
            f"(impostos {hub.get('impostos_total_brl')}) vs Sul "
            f"`{sul.get('codigo')}` R$ {sul.get('custo_unitario_brl')}/un "
            f"(impostos {sul.get('impostos_total_brl')}) · "
            f"Δ custo {trib.get('delta_custo_unit_sul_menos_regiao_brl')} · "
            f"*{trib.get('veredito')}*"
        )
    if resultado.get("top_atrativos"):
        linhas.append("*Top atrativos (≥90%)*")
        for c in (resultado.get("top_atrativos") or [])[:max_linhas]:
            linhas.append(
                f"• `{c.get('codigo')}` {c.get('modal')} · "
                f"R$ {c.get('custo_unitario_brl')} · assert. {c.get('assertividade_pct')}%"
            )
    elif resultado.get("top_condicionais"):
        linhas.append("*Condicionais (<90% — custo manda)*")
        for c in (resultado.get("top_condicionais") or [])[:max_linhas]:
            linhas.append(
                f"• `{c.get('codigo')}` {c.get('modal')} · "
                f"R$ {c.get('custo_unitario_brl')} · assert. {c.get('assertividade_pct')}% · "
                f"markup {c.get('markup_sobre_fob')}"
            )
    py = resultado.get("paraguai_terrestre") or {}
    if py.get("ok") and py.get("melhor_corredor"):
        end = py.get("endereco") or {}
        mc = py.get("melhor_corredor") or {}
        linhas.extend(
            [
                "",
                "🇵🇾 *Endereço comercial Paraguai + terrestre BR*",
                f"  {end.get('cidade')}: {end.get('endereco')}",
                f"  Corredor `{mc.get('corredor_id')}` · ~{mc.get('km_total')} km · "
                f"terrestre R$ {mc.get('custo_total_brl')}",
            ]
        )
    linhas.append(f"_{resultado.get('aviso')}_")
    return "\n".join(linhas)
