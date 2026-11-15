"""
agentes/precificacao/agente_cenario_macro.py
Leitura do cenário macro: margem, reposição e câmbio.
Não publica anúncio, não altera preço e não reescreve catálogo.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ROOT
from core.datadog_metrics import gauge
from core.notificador import alertar_gestor, chave_resumo_periodo

logger = logging.getLogger("agente_cenario_macro")

SNAPSHOT = ROOT / "logs" / "cenario_macro_ultima.json"
_COOLDOWN_RESUMO_SEG = 6 * 3600
_FRETE_FAIXAS = ROOT / "catalogo" / "frete_faixas_impala.json"
_CAT_ALIBABA = ROOT / "catalogo" / "alibaba_produtos_importacao.json"
_CAT_FILAMENTOS = ROOT / "catalogo" / "filamentos_3d_monitor.json"


def _ler_json(caminho) -> Any:
    try:
        if caminho.is_file():
            return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("cenario_macro: falha ao ler %s: %s", caminho, exc)
    return None


def _frete_faixas_em_memoria(alta_pct: float) -> list[dict[str, Any]]:
    bruto = _ler_json(_FRETE_FAIXAS)
    faixas = list((bruto or {}).get("faixas") or []) if isinstance(bruto, dict) else []
    if alta_pct <= 0:
        return faixas
    fator = 1.0 + alta_pct / 100.0
    ajustadas = []
    for faixa in faixas:
        if not isinstance(faixa, dict):
            continue
        item = dict(faixa)
        try:
            item["frete_reais"] = round(float(faixa.get("frete_reais") or 0) * fator, 2)
        except (TypeError, ValueError):
            pass
        ajustadas.append(item)
    return ajustadas


def _frete_para_peso(faixas: list[dict[str, Any]], peso_g: float) -> float | None:
    if peso_g <= 0:
        return None
    for faixa in faixas:
        try:
            if peso_g <= float(faixa.get("teto_g") or 0):
                return float(faixa.get("frete_reais") or 0)
        except (TypeError, ValueError):
            continue
    return None


def _custo_com_frete(produto: dict[str, Any], faixas: list[dict[str, Any]], alta_pct: float) -> float:
    custo = float(produto.get("custo_total") or produto.get("custo") or 0)
    if alta_pct <= 0 or custo <= 0:
        return custo
    frete = float(produto.get("frete_estimado") or 0)
    if frete <= 0:
        frete_faixa = _frete_para_peso(faixas, float(produto.get("peso_gramas") or 0))
        frete = float(frete_faixa or 0)
    if frete <= 0:
        return custo
    return round(custo - frete + frete * (1.0 + alta_pct / 100.0), 2)


def _vendas_dia(produto: dict[str, Any]) -> float | None:
    for chave in ("vendas_por_dia", "vd_dia_ml_ref"):
        try:
            valor = float(produto.get(chave) or 0)
        except (TypeError, ValueError):
            continue
        if valor > 0:
            return valor
    return None


def _skus_importacao_ativos() -> list[dict[str, Any]]:
    ativos: list[dict[str, Any]] = []
    for caminho in (_CAT_ALIBABA, _CAT_FILAMENTOS):
        bruto = _ler_json(caminho)
        if not isinstance(bruto, list):
            continue
        for item in bruto:
            if isinstance(item, dict) and item.get("ativo") is True:
                ativos.append(item)
    return ativos


def _cambio() -> dict[str, Any]:
    from core.cenario_macro import regime_cambial
    from core.config import CENARIO_CAMBIO_REFERENCIA
    from integracoes.cambio.cotacao_usd import cotacao_confiavel_para_margem, obter_cotacao_usd
    from integracoes.importacao.analise_margem import calcular_sensibilidade_cambio

    cotacao = obter_cotacao_usd()
    confiavel = cotacao_confiavel_para_margem(cotacao)
    usd = float(cotacao.get("usd_brl") or 0)
    regime = regime_cambial(usd, CENARIO_CAMBIO_REFERENCIA)
    bloco: dict[str, Any] = {
        "usd_brl": usd,
        "fonte": cotacao.get("fonte"),
        "confiavel": confiavel,
        "regime": regime["regime"],
        "variacao_vs_referencia_pct": regime["variacao_pct"],
    }
    if not confiavel:
        bloco["cambio_nao_confiavel"] = True
        bloco["sensibilidade"] = []
        return bloco

    sensibilidade = []
    for produto in _skus_importacao_ativos():
        preco_usd = produto.get("preco_usd") or produto.get("preco_usd_unit") or produto.get("preco_max_usd")
        if not preco_usd:
            continue
        amostra = dict(produto)
        amostra["preco_usd"] = preco_usd
        sensibilidade.append(
            {
                "id": produto.get("id") or produto.get("sku"),
                "nome": produto.get("nome"),
                "cenarios": calcular_sensibilidade_cambio(amostra, usd),
            }
        )
    bloco["sensibilidade"] = sensibilidade
    return bloco


def _avisos_congelado(recomendacoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from integracoes.esmaltes.doutrina_guerra_impala import carregar_doutrina

    doutrina = carregar_doutrina()
    congelados = {str(s).strip().upper() for s in (doutrina.get("preco_congelado") or [])}
    avisos = []
    for rec in recomendacoes:
        sku = str(rec.get("sku") or "").strip().upper()
        if sku not in congelados:
            continue
        piso = float(rec.get("preco_equilibrio_reposicao") or 0)
        preco = float(rec.get("preco_atual") or 0)
        if piso > preco > 0:
            avisos.append(
                {
                    "sku": sku,
                    "aviso": "piso_acima_do_congelado",
                    "preco_congelado": preco,
                    "piso": piso,
                }
            )
    return avisos


def _relatorio_shopee(produtos: list[dict[str, Any]], faixas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from core.cenario_macro import margem_exigida_pct, recomendar_sku
    from core.config import (
        CENARIO_FRETE_ALTA_PCT,
        CENARIO_MARGEM_ADICIONAL_PP,
        MARGEM_FASE_1_PCT,
        MARGEM_FASE_2_PCT,
        MARGEM_FASE_3_PCT,
        TAXA_SHOPEE_PADRAO_PCT,
    )

    base = {1: MARGEM_FASE_1_PCT, 2: MARGEM_FASE_2_PCT, 3: MARGEM_FASE_3_PCT}
    fecham = []
    for produto in produtos:
        if str(produto.get("prioridade") or "").upper() != "P0":
            continue
        shopee = ((produto.get("canais") or {}).get("shopee") or {})
        if shopee.get("ativo") is not False:
            continue
        fase = int(produto.get("fase_atual") or 1)
        exigida = margem_exigida_pct(fase, base, CENARIO_MARGEM_ADICIONAL_PP, True)
        custo = _custo_com_frete(produto, faixas, CENARIO_FRETE_ALTA_PCT)
        preco = float(shopee.get("preco") or produto.get("preco") or 0)
        rec = recomendar_sku(
            sku=str(produto.get("sku") or ""),
            custo_total=custo,
            custo_reposicao_unit=custo,
            preco_atual=preco,
            taxa_canal_pct=TAXA_SHOPEE_PADRAO_PCT,
            fase=fase,
            estoque=int(shopee.get("estoque") or 0),
            vendas_dia=None,
            margem_exigida=exigida,
        )
        if (rec.get("margem_atual_pct") or 0) >= exigida:
            fecham.append(
                {
                    "sku": produto.get("sku"),
                    "preco_referencia": preco,
                    "taxa_shopee_pct": TAXA_SHOPEE_PADRAO_PCT,
                    "margem_pct": rec.get("margem_atual_pct"),
                    "margem_exigida_pct": exigida,
                    "nota": "Somente relatório. Canal permanece inativo.",
                }
            )
    return fecham


def _resumo(payload: dict[str, Any]) -> str:
    cambio = payload.get("cambio") or {}
    regime = cambio.get("regime") or "sem_cotacao"
    usd = cambio.get("usd_brl")
    linha_usd = f"Dólar {regime}" + (f" R$ {usd:.2f}" if usd else "")
    riscos = payload.get("skus_em_risco") or []
    top_risco = ", ".join(str(s.get("sku")) for s in riscos[:5]) or "nenhum"
    antecipar = payload.get("antecipar_compra") or []
    top_compra = ", ".join(str(s.get("sku")) for s in antecipar[:3]) or "nenhum"
    avisos = payload.get("piso_acima_do_congelado") or []
    cong = ", ".join(str(a.get("sku")) for a in avisos) or "nenhum"
    return (
        "Cenário macro (somente leitura)\n"
        f"{linha_usd}\n"
        f"Margem em risco: {top_risco}\n"
        f"Antecipar compra: {top_compra}\n"
        f"Piso acima do congelado: {cong}"
    )


def executar(*, enviar_alerta: bool = True) -> dict[str, Any]:
    """Varre catálogo e grava logs/cenario_macro_ultima.json. Não escreve no marketplace."""
    from core.config import CENARIO_MACRO_ATIVO

    if not CENARIO_MACRO_ATIVO:
        return {"ok": True, "ativo": False}

    from core.catalogo_produtos import carregar_produtos_para_operacao
    from core.cenario_macro import custo_reposicao, margem_exigida_pct, recomendar_sku
    from core.config import (
        CENARIO_FRETE_ALTA_PCT,
        CENARIO_MARGEM_ADICIONAL_PP,
        CENARIO_REPOSICAO_ALTA_PCT,
        MARGEM_FASE_1_PCT,
        MARGEM_FASE_2_PCT,
        MARGEM_FASE_3_PCT,
    )

    base = {1: MARGEM_FASE_1_PCT, 2: MARGEM_FASE_2_PCT, 3: MARGEM_FASE_3_PCT}
    faixas = _frete_faixas_em_memoria(CENARIO_FRETE_ALTA_PCT)
    produtos = carregar_produtos_para_operacao()
    recomendacoes: list[dict[str, Any]] = []
    for produto in produtos:
        ml = ((produto.get("canais") or {}).get("mercadolivre") or {})
        if ml.get("ativo") is False:
            continue
        sku = str(produto.get("sku") or "")
        if not sku:
            continue
        fase = int(produto.get("fase_atual") or 1)
        custo = _custo_com_frete(produto, faixas, CENARIO_FRETE_ALTA_PCT)
        reposicao = custo_reposicao(custo, CENARIO_REPOSICAO_ALTA_PCT)
        taxa = float(ml.get("taxa_canal_pct") or 18.0)
        preco = float(ml.get("preco") or produto.get("preco") or 0)
        estoque = int(ml.get("estoque") or produto.get("estoque_total") or 0)
        exigida = margem_exigida_pct(fase, base, CENARIO_MARGEM_ADICIONAL_PP, True)
        rec = recomendar_sku(
            sku=sku,
            custo_total=custo,
            custo_reposicao_unit=reposicao,
            preco_atual=preco,
            taxa_canal_pct=taxa,
            fase=fase,
            estoque=estoque,
            vendas_dia=_vendas_dia(produto),
            margem_exigida=exigida,
        )
        rec["preco_atual"] = preco
        rec["nome"] = produto.get("nome")
        recomendacoes.append(rec)

    riscos = [r for r in recomendacoes if r.get("acao") == "subir_preco_na_reposicao"]
    antecipar = [r for r in recomendacoes if r.get("acao") == "antecipar_compra"]
    cambio = _cambio() if _skus_importacao_ativos() else {"pulado": True, "motivo": "sem_sku_importacao_ativo"}
    payload = {
        "ok": True,
        "ativo": True,
        "somente_leitura": True,
        "frete_alta_pct": CENARIO_FRETE_ALTA_PCT,
        "reposicao_alta_pct": CENARIO_REPOSICAO_ALTA_PCT,
        "margem_adicional_pp": CENARIO_MARGEM_ADICIONAL_PP,
        "skus": recomendacoes,
        "skus_em_risco": riscos,
        "antecipar_compra": antecipar,
        "piso_acima_do_congelado": _avisos_congelado(recomendacoes),
        "shopee_p0_fecha_margem": _relatorio_shopee(produtos, faixas),
        "cambio": cambio,
    }
    escrever_json_atomico(SNAPSHOT, payload)
    gauge("cenario_macro.skus_em_risco", len(riscos))

    if enviar_alerta:
        alertar_gestor(
            _resumo(payload),
            chave=chave_resumo_periodo("cenario_macro", horas_por_bucket=6),
            cooldown_segundos=_COOLDOWN_RESUMO_SEG,
            agente_id="cenario_macro",
        )
    logger.info("cenario_macro: %s SKUs, %s em risco", len(recomendacoes), len(riscos))
    return payload


if __name__ == "__main__":
    executar(enviar_alerta=True)
