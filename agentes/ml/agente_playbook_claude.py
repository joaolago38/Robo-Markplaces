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
from core.datadog_metrics import gauge
from core.claude_client import mlb_invalido
from core.claude_contexto_ml import enriquecer_contexto_claude
from core.claude_ml.playbooks import PLAYBOOKS, montar_instrucoes
from core.config import ROOT
from core.resumo_ia import sintetizar_claude

logger = logging.getLogger("agente_playbook_claude")

SNAPSHOT_PATH = ROOT / "logs" / "playbook_claude_ml_ultima.json"
LOTE_PATH = ROOT / "logs" / "playbook_claude_lote_ultima.json"
PLAYBOOKS_OPERACAO = (
    "demanda_alta",
    "inteligencia_competitiva",
    "padroes_avaliacao",
    "pricing_faixas",
    "panorama_categoria",
)
_PROPOSITO = {
    "demanda_alta": "descoberta_produtos",
    "inteligencia_competitiva": "monitor_concorrentes",
    "padroes_avaliacao": "avaliacoes_concorrente",
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
    n_pub = sum(1 for p in top if p.get("publicado"))
    from integracoes.ml.contexto_playbook_operacao import montar_contexto_operacao

    operacao = montar_contexto_operacao()
    if n_pub == 0:
        aviso = (
            "Nenhum candidato tem MLB publicado. "
            "Não trate vd_dia_ml_ref como demanda ao vivo. Sinal fraco até existir anúncio."
        )
        momento = "começando agora no ML (anúncios ainda sem MLB válido)"
    else:
        aviso = (
            f"{n_pub} candidato(s) com MLB. "
            + str((operacao.get("fontes") or {}).get("aviso") or "")
        )
        momento = "já vendendo nesse nicho"
    return {
        "nicho": "esmaltes Impala / kits manicure — Mercado Livre Brasil",
        "momento": momento,
        "capital_teste": "validação por SKU no catálogo (invest_validacao_reais quando houver)",
        "categoria": "MLB1430 esmaltes / kits",
        "produtos_candidatos": top,
        "operacao_ml": operacao,
        "aviso": aviso,
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


def fallback_playbook(playbook_id: str, payload: dict[str, Any]) -> str:
    """Texto local quando Claude está off ou falha — só com o JSON, sem inventar JoomPulse."""
    if playbook_id == "demanda_alta":
        return fallback_demanda_alta(payload)
    op = payload.get("operacao_ml") if isinstance(payload.get("operacao_ml"), dict) else {}
    aviso = str(payload.get("aviso") or "")
    linhas = [f"*Playbook {playbook_id}*", "", aviso, ""]
    if playbook_id == "padroes_avaliacao":
        pad = op.get("padroes_reclamacao_agregados") or []
        linhas.append("Padrão | Frequência | Impacto | Diferencial")
        if not pad:
            linhas.append("n/d | 0 | n/d | sem texto de review (403 ou histórico curto)")
        for p in pad[:5]:
            linhas.append(
                f"{p.get('padrao')} | {p.get('frequencia')} | n/d (só palavra-chave) | revisar operação"
            )
        linhas.append("")
        linhas.append("Atacar primeiro: o padrão de maior frequência no JSON; impacto semântico exige revisão humana.")
        return "\n".join(linhas)
    if playbook_id == "pricing_faixas":
        faixas = op.get("faixas_preco") or {}
        linhas.append("Faixa | Preço | Volume | Margem")
        if faixas.get("fraco") or not faixas:
            linhas.append("Dados fracos demais pra fatiar entrada/intermediária/premium.")
        else:
            for nome in ("entrada", "intermediaria", "premium"):
                par = faixas.get(nome) or []
                if len(par) == 2:
                    linhas.append(f"{nome} | {par[0]:.2f}–{par[1]:.2f} | n/d ao vivo | n/d")
        linhas.append(f"Pontos observados: {faixas.get('n_pontos') or len(op.get('precos_observados') or [])}")
        return "\n".join(linhas)
    if playbook_id == "inteligencia_competitiva":
        termos = op.get("termos_monitorados") or []
        loja = next((t for t in termos if t.get("tipo") == "loja"), None)
        linhas.append("Dimensão | O que ele faz | Como eu reagiria")
        if not loja:
            linhas.append("n/d | sem loja no JSON operacional | —")
        else:
            linhas.append(
                f"preço | menor amostrado R$ {loja.get('menor_preco')} | "
                f"não copiar se margem_real indisponível"
            )
        linhas.append("")
        linhas.append("Se eu só pudesse fazer UMA coisa: publicar MLB do kit P0 e medir gap com anúncio vivo.")
        return "\n".join(linhas)
    termos = op.get("termos_monitorados") or []
    linhas.append("Panorama só com proxy do robô (não JoomPulse).")
    for t in termos[:8]:
        td = t.get("tendencia_demanda") or {}
        linhas.append(
            f"• {t.get('nome')}: tendência {td.get('tendencia', 'n/d')} | "
            f"menor R$ {t.get('menor_preco')} | cego={t.get('amostra_cega')}"
        )
    linhas.append("")
    linhas.append("Se eu fosse entrar hoje, eu faria o kit P0 no ar antes de escalar copy/ads.")
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
        fallback_playbook(pid, payload),
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
        "usou_fallback": texto.strip().startswith("*Playbook "),
    }
    escrever_json_atomico(SNAPSHOT_PATH, out)
    return out


def executar_lote(*, enviar_alerta: bool = True, limite: int = 10) -> dict[str, Any]:
    """Roda os 5 playbooks com dado operacional. Copy/vídeo/marca ficam no --playbook avulso."""
    pecas: list[dict[str, Any]] = []
    try:
        for pid in PLAYBOOKS_OPERACAO:
            pecas.append(executar(playbook_id=pid, limite=limite))
        blocos = ["📋 *Playbooks ML (dado do robô, não JoomPulse)*", ""]
        for r in pecas:
            txt = str(r.get("texto") or "")[:900]
            blocos.append(f"*{r.get('playbook_id')}*")
            blocos.append(txt)
            blocos.append("")
        texto = "\n".join(blocos).strip()
        enviado = False
        if enviar_alerta and texto:
            from core.notificador import alertar_gestor, chave_resumo_periodo

            enviado = bool(
                alertar_gestor(
                    texto[:3500],
                    chave=chave_resumo_periodo("ml:playbook:lote", horas_por_bucket=20),
                    cooldown_segundos=20 * 3600,
                    agente_id="agente_playbook_claude",
                )
            )
        n_ok = sum(1 for p in pecas if p.get("ok"))
        out = {
            "ok": all(p.get("ok") for p in pecas) if pecas else False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playbooks": [p.get("playbook_id") for p in pecas],
            "enviado": enviado,
            "texto": texto,
        }
        gauge("playbook.lote.ok", 1.0 if out["ok"] else 0.0)
        gauge("playbook.lote.n_ok", float(n_ok))
        gauge("playbook.lote.n_total", float(len(pecas)))
        escrever_json_atomico(LOTE_PATH, {**out, "pecas": pecas})
        return out
    except Exception as exc:
        logger.warning("executar_lote: %s", exc)
        gauge("playbook.lote.ok", 0.0)
        return {"ok": False, "erro": str(exc), "playbooks": []}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Executa playbook Claude × Mercado Livre")
    p.add_argument("--playbook", default="demanda_alta")
    p.add_argument("--lote", action="store_true", help="5 playbooks operacionais (demanda, rival, reclamação, preço, panorama)")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--limite", type=int, default=10)
    args = p.parse_args()
    if args.listar:
        print("\n".join(sorted(PLAYBOOKS)))
        return 0
    if args.lote:
        r = executar_lote(enviar_alerta=True, limite=args.limite)
    else:
        r = executar(playbook_id=args.playbook, limite=args.limite)
    print(r.get("texto") or r.get("erro") or r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
