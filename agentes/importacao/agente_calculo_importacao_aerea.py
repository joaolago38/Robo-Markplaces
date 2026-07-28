"""
agentes/importacao/agente_calculo_importacao_aerea.py
Calculadora formal de importação aérea CNPJ (Viracopos → Americana-SP).

Integrado ao pipeline Alibaba; também executável isolado:

  python -m agentes.importacao.agente_calculo_importacao_aerea
  python -m agentes.importacao.agente_calculo_importacao_aerea --produto filamento-impressora-3d-pla
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.config import ALIBABA_IMPORTACAO_CATALOGO, ROOT
from integracoes.alibaba.busca import buscar_oportunidades
from integracoes.cambio.cotacao_usd import cotacao_confiavel_para_margem, obter_cotacao_usd
from integracoes.importacao.calculo_importacao_aerea import (
    calcular_para_produto_alibaba,
    exportar_csv_resultado,
)
from integracoes.importacao.perfil_empresa_importacao import obter_perfil_importador

logger = logging.getLogger("agente_calculo_importacao_aerea")

LOG_DIR = ROOT / "logs"
SNAPSHOT_PATH = LOG_DIR / "importacao_aerea_ultima.json"


def _cambio_para_calculo(cambio_usd_brl: float | None = None) -> tuple[float, dict[str, Any] | None, str | None]:
    """
    Retorna (cambio, cotacao_ou_None, erro_ou_None).
    Cotação automática só segue se for confiável (não fallback).
    Câmbio explícito do caller é aceito (override consciente).
    """
    if cambio_usd_brl is not None and float(cambio_usd_brl) > 0:
        return float(cambio_usd_brl), None, None
    cotacao = obter_cotacao_usd()
    cambio = float(cotacao.get("usd_brl") or 0)
    if cambio <= 0:
        return 0.0, cotacao, "câmbio inválido"
    if not cotacao_confiavel_para_margem(cotacao):
        motivo = str(cotacao.get("fonte") or cotacao.get("erro") or "fallback/desatualizada")
        return 0.0, cotacao, f"câmbio não confiável para margem ({motivo})"
    return cambio, cotacao, None



def _carregar_produtos() -> list[dict[str, Any]]:
    from agentes.importacao.agente_alibaba_importacao import _carregar_produtos as carregar

    return carregar()


def _fmt_brl(valor: Any) -> str:
    if valor is None:
        return "n/d"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def executar_para_oportunidade(
    produto: dict[str, Any],
    oportunidade: dict[str, Any],
    *,
    cambio_usd_brl: float | None = None,
    salvar_csv: bool = True,
) -> dict[str, Any]:
    """Calcula custo formal aéreo para um produto + listing Alibaba."""
    cambio, _cotacao, erro_cambio = _cambio_para_calculo(cambio_usd_brl)
    if erro_cambio:
        return {"ok": False, "motivo": erro_cambio, "cotacao": _cotacao}

    perfil = obter_perfil_importador()
    resultado = calcular_para_produto_alibaba(produto, oportunidade, cambio_usd_brl=cambio)
    if not resultado.get("ok"):
        return resultado

    resultado["perfil_importador"] = perfil
    resultado["cambio_usd_brl"] = cambio
    resultado["timestamp"] = datetime.now(timezone.utc).isoformat()

    if salvar_csv:
        pid = str(produto.get("id") or "produto")
        csv_path = LOG_DIR / f"importacao_aerea_{pid}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(exportar_csv_resultado(resultado), encoding="utf-8")
        resultado["csv_path"] = str(csv_path)

    return resultado


def executar_para_produto(
    produto: dict[str, Any],
    *,
    cambio_usd_brl: float | None = None,
    buscar_alibaba: bool = True,
) -> dict[str, Any]:
    """Usa a melhor oportunidade Alibaba (menor preço) ou dados do catálogo."""
    oportunidade: dict[str, Any] = {
        "preco_usd": produto.get("preco_fob_usd"),
        "moq": produto.get("moq_referencia") or 1,
        "titulo": produto.get("nome"),
    }

    if buscar_alibaba:
        ops = buscar_oportunidades(produto, pausa_seg=0)
        com_preco = [o for o in ops if o.get("preco_usd") is not None]
        com_preco.sort(key=lambda x: float(x.get("preco_usd") or 9999))
        if com_preco:
            oportunidade = com_preco[0]

    return executar_para_oportunidade(produto, oportunidade, cambio_usd_brl=cambio_usd_brl)


def executar(
    *,
    produto_id: str | None = None,
    buscar_alibaba: bool = True,
) -> dict[str, Any]:
    produtos = _carregar_produtos()
    if produto_id:
        produtos = [p for p in produtos if str(p.get("id")) == produto_id]
    if not produtos:
        return {"ok": False, "motivo": f"produto não encontrado: {produto_id or 'catálogo vazio'}"}

    cambio, cotacao, erro_cambio = _cambio_para_calculo(None)
    if erro_cambio:
        return {"ok": False, "motivo": erro_cambio, "cotacao": cotacao}
    cotacao = cotacao or {"usd_brl": cambio}
    resultados: list[dict[str, Any]] = []

    for produto in produtos:
        out = executar_para_produto(produto, cambio_usd_brl=cambio, buscar_alibaba=buscar_alibaba)
        resultados.append(out)
        if out.get("ok"):
            logger.info(
                "Importação aérea formal %s: custo unit. %s | total %s",
                produto.get("id"),
                _fmt_brl(out.get("custo_unitario_brl")),
                _fmt_brl(out.get("custo_total_brl")),
            )

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cotacao": cotacao,
        "catalogo": ALIBABA_IMPORTACAO_CATALOGO,
        "resultados": resultados,
    }
    escrever_json_atomico(SNAPSHOT_PATH, snapshot)

    return {
        "ok": True,
        "cotacao": cotacao,
        "total": len(resultados),
        "resultados": resultados,
        "snapshot": str(SNAPSHOT_PATH),
    }


def formatar_resumo_telegram(resultado: dict[str, Any]) -> str:
    if not resultado.get("ok"):
        return f"Importação aérea: falhou — {resultado.get('motivo', '?')}"

    perfil = resultado.get("perfil_importador") or {}
    linhas = [
        "✈️ *Importação formal aérea — Viracopos (VCP)*",
        f"CNPJ: {perfil.get('cnpj', '?')} — {perfil.get('razao_social') or 'razão social n/d'}",
        f"Produto: {resultado.get('produto_nome', '?')}",
        f"Listing: {str(resultado.get('listing_titulo') or '')[:60]}",
        "",
        f"CIF aduaneiro: {_fmt_brl(resultado.get('valor_aduaneiro_cif_brl'))}",
        f"Custo total: {_fmt_brl(resultado.get('custo_total_brl'))}",
        f"Custo/unidade (qty {resultado.get('quantidade', '?')}): {_fmt_brl(resultado.get('custo_unitario_brl'))}",
        "",
        "_Estimativa — confirme NCM/II/IPI com despachante._",
    ]
    if resultado.get("listing_url"):
        linhas.append(f"🔗 {resultado['listing_url']}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cálculo formal importação aérea CNPJ (VCP)")
    parser.add_argument("--produto", help="ID do produto no catálogo Alibaba")
    parser.add_argument("--sem-alibaba", action="store_true", help="Usa só preço FOB do catálogo")
    args = parser.parse_args(argv)

    logger.info("=== Cálculo importação aérea formal ===")
    out = executar(produto_id=args.produto, buscar_alibaba=not args.sem_alibaba)
    if not out.get("ok"):
        logger.error("Falhou: %s", out.get("motivo"))
        return 1
    logger.info("Concluído: %s produto(s). Snapshot: %s", out.get("total"), out.get("snapshot"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
