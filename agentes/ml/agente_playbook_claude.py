"""
agentes/ml/agente_playbook_claude.py
Executa um playbook Claude × ML com catálogo + anúncios (não cola prompt vazio).

Uso:
  python -m agentes.ml.agente_playbook_claude
  python -m agentes.ml.agente_playbook_claude --playbook demanda_alta
  python -m agentes.ml.agente_playbook_claude --listar
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico
from core.catalogo_produtos import carregar_produtos_catalogo
from core.claude_client import mlb_invalido
from core.claude_contexto_ml import enriquecer_contexto_claude
from core.claude_ml.playbooks import PLAYBOOKS, montar_instrucoes
from core.config import ROOT
from core.resumo_ia import sintetizar_claude

logger = logging.getLogger("agente_playbook_claude")

SNAPSHOT_PATH = ROOT / "logs" / "playbook_claude_ml_ultima.json"
_PROPOSITO = {
    "demanda_alta": "descoberta_produtos",
    "inteligencia_competitiva": "monitor_concorrentes",
    "seo_titulo": "otimizar_listing",
    "auditor_anuncio": "auditor_anuncio",
    "atendimento_chat": "chat_ml",
    "panorama_categoria": "analise_ml",
    "viabilidade_nicho": "viabilidade_nicho",
    "pricing_faixas": "inteligencia_precos",
    "cross_sell": "montar_kits_impala",
}


def _linha_catalogo(p: dict[str, Any]) -> dict[str, Any]:
    ml = (p.get("canais") or {}).get("mercadolivre") or {}
    mlb = str(ml.get("item_id") or "")
    return {
        "sku": p.get("sku"),
        "nome": p.get("nome"),
        "prioridade": p.get("prioridade"),
        "segmento": p.get("segmento"),
        "preco_entrada": p.get("preco"),
        "preco_ml_mercado_ref": p.get("preco_ml_mercado"),
        "vd_dia_ml_ref": p.get("vd_dia_ml_ref"),
        "vendas_historico_ml": p.get("vendas_historico_ml"),
        "margem_trabalho_pct": p.get("margem_trabalho_pct"),
        "custo_total": p.get("custo_total"),
        "estoque_total": p.get("estoque_total"),
        "mlb": mlb,
        "publicado": bool(mlb) and not mlb_invalido(mlb),
        "titulo_anuncio": ml.get("titulo_anuncio") or p.get("titulo_sugerido_ml"),
        "sinal_demanda": "ref_catalogo_nao_ao_vivo",
        "nota": "vd_dia_ml_ref/historico são referência de catálogo, não venda ao vivo.",
    }


def payload_entrada(*, limite: int = 10) -> dict[str, Any]:
    produtos = carregar_produtos_catalogo()
    linhas = [_linha_catalogo(p) for p in produtos if isinstance(p, dict)]
    prio = {"P0": 0, "P1": 1, "P2": 2}

    def _ord(row: dict[str, Any]) -> tuple:
        return (
            prio.get(str(row.get("prioridade") or "P9"), 9),
            -float(row.get("vd_dia_ml_ref") or 0),
        )

    top = sorted(linhas, key=_ord)[: max(1, limite)]
    return {
        "nicho": "esmaltes Impala / kits manicure — Mercado Livre Brasil",
        "momento": "começando agora no ML (anúncios ainda sem MLB válido)",
        "capital_teste": "validação por SKU no catálogo (invest_validacao_reais quando houver)",
        "categoria": "MLB1430 esmaltes / kits",
        "produtos_candidatos": top,
        "aviso": (
            "Nenhum candidato tem MLB publicado. "
            "Não trate vd_dia_ml_ref como demanda ao vivo. Sinal fraco até existir anúncio."
        ),
    }


def fallback_demanda_alta(payload: dict[str, Any]) -> str:
    linhas = [
        "*Playbook demanda_alta — entrada ML*",
        "",
        str(payload.get("aviso") or ""),
        "",
        "Produto | Sinal de demanda | Concorrência | Perfil | Faixa de preço",
        "---|---|---|---|---",
    ]
    for p in payload.get("produtos_candidatos") or []:
        sinal = "fraco (só ref. catálogo; sem MLB)"
        conc = "n/d ao vivo"
        perfil = "manicure / revenda salão"
        faixa = f"R$ {p.get('preco_entrada')} (entrada) / mercado ref. R$ {p.get('preco_ml_mercado_ref')}"
        linhas.append(
            f"{p.get('sku')} {p.get('nome')} | {sinal} | {conc} | {perfil} | {faixa}"
        )
    linhas += [
        "",
        "*Top 3 pra testar primeiro* (operação, não demanda ao vivo):",
        "1. IMP-MIMO-003 — kit de validação da guerra; publicar MLB antes de escalar.",
        "2. IMP-PERL-004 — P0 com preço de fase 1 definido; mesmo ciclo após MIMO no ar.",
        "3. IMP-JUPAES-006 — só depois do 1º pedido (regra do catálogo); não lançar SORT agora.",
        "",
        "_Assertividade de anúncio no ar: 0%. Claude/API não substitui MLB._",
    ]
    return "\n".join(linhas)


def executar(
    *,
    playbook_id: str = "demanda_alta",
    limite: int = 10,
) -> dict[str, Any]:
    pid = (playbook_id or "demanda_alta").strip()
    if pid not in PLAYBOOKS:
        return {"ok": False, "erro": f"playbook desconhecido: {pid}", "ids": sorted(PLAYBOOKS)}
    payload = payload_entrada(limite=limite)
    proposito = _PROPOSITO.get(pid, "descoberta_produtos")
    ctx, dosagem = enriquecer_contexto_claude(
        payload,
        consolidado={"categoria": payload["categoria"], "nicho": payload["nicho"]},
        proposito=proposito,
    )
    instrucoes = montar_instrucoes(pid, campos=(ctx.get("playbook_ml") or {}).get("campos"))
    texto = sintetizar_claude(
        instrucoes,
        ctx,
        fallback_demanda_alta(payload) if pid == "demanda_alta" else fallback_demanda_alta(payload),
        max_tokens=2200,
        enriquecer_ml=False,
        consolidado={"categoria": payload["nicho"]},
        origem="agentes.ml.agente_playbook_claude",
        proposito=proposito,
        exigir_contexto=True,
        system=instrucoes,
    )
    out = {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "playbook_id": pid,
        "proposito": proposito,
        "dosagem": {
            "profundidade": dosagem.get("profundidade"),
            "playbook_id": dosagem.get("playbook_id"),
        },
        "anuncios_ml_resumo": ctx.get("anuncios_ml_resumo"),
        "candidatos": payload.get("produtos_candidatos"),
        "texto": texto,
        "usou_fallback": texto.strip().startswith("*Playbook demanda_alta"),
    }
    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Executa playbook Claude × Mercado Livre")
    p.add_argument("--playbook", default="demanda_alta")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--limite", type=int, default=10)
    args = p.parse_args()
    if args.listar:
        print("\n".join(sorted(PLAYBOOKS)))
        return 0
    r = executar(playbook_id=args.playbook, limite=args.limite)
    print(r.get("texto") or r.get("erro") or r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
