"""
integracoes/esmaltes/ecossistema_esmaltes.py
Monta o plano de ecossistema de esmaltes a partir dos snapshots já
coletados (sem re-scrape): cor atrai; kit + anexos + B2B pagam.

Camadas:
  core      — cores/esmaltes âncora (tráfego)
  anexos    — base, top coat, removedor, acetona (margem)
  kits      — AOV (iniciante / profissional / reposição)
  b2b       — manicures, atacado, reposição
  conteudo  — tendência / cor do mês
  marca     — Impala vs Anita, diferenciação
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT

logger = logging.getLogger("ecossistema_esmaltes")

# Snapshots produzidos por outros agentes
_PATHS = {
    "tendencias": ROOT / "logs" / "esmaltes_tendencias_ultima.json",
    "busca_kit": ROOT / "logs" / "esmaltes_busca_kit_ultima.json",
    "anita": ROOT / "logs" / "anita_esmaltes_ultima.json",
    "kits": ROOT / "logs" / "esmaltes_kits_monitor_ultima.json",
    "montar_kits": ROOT / "logs" / "montar_kits_impala_ultima.json",
    "removedores": ROOT / "logs" / "removedores_unha_ultima.json",
    "acetona": ROOT / "logs" / "acetona_cruzeiro_ultima.json",
    "necessidade": ROOT / "logs" / "necessidade_manicures_ultima.json",
    "conversao": ROOT / "logs" / "conversao_manicures_ultima.json",
    "mercado": ROOT / "logs" / "esmaltes_mercado_ultima.json",
}

_CAMADAS = ("core", "anexos", "kits", "b2b", "conteudo", "marca")


def _snap(chave: str) -> dict[str, Any]:
    data = ler_json(_PATHS[chave], default={})
    return data if isinstance(data, dict) else {}


def _fonte_ok(data: dict[str, Any]) -> bool:
    if not data:
        return False
    if data.get("ok") is False:
        return False
    return True


def _acao(
    *,
    camada: str,
    titulo: str,
    detalhe: str,
    prioridade: int,
    horizonte: str,
    score: float,
    evidencias: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "camada": camada,
        "titulo": titulo,
        "detalhe": detalhe,
        "prioridade": prioridade,  # 1 = urgente
        "horizonte": horizonte,  # 7d | 30d | 90d
        "score": round(float(score), 1),
        "evidencias": evidencias or [],
    }


def coletar_fontes() -> dict[str, Any]:
    """Carrega snapshots e marca quais estão disponíveis."""
    fontes: dict[str, Any] = {}
    for chave in _PATHS:
        data = _snap(chave)
        fontes[chave] = {
            "disponivel": _fonte_ok(data),
            "timestamp": data.get("timestamp"),
            "dados": data,
        }
    return fontes


def _acoes_core(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    montar = (fontes.get("montar_kits") or {}).get("dados") or {}
    cruz = montar.get("cruzamento") or {}
    top = cruz.get("top_cores") or []
    if top:
        nomes = [str(c.get("nome_cor") or "?") for c in top[:5]]
        out.append(
            _acao(
                camada="core",
                titulo="Cores âncora (planilha × demanda kits ML)",
                detalhe=f"Priorize estoque/ads em: {', '.join(nomes)}",
                prioridade=1,
                horizonte="7d",
                score=80 + min(15, float(top[0].get("score_demanda") or 0)),
                evidencias=[
                    f"{c.get('nome_cor')} score={c.get('score_demanda')}" for c in top[:3]
                ],
            )
        )

    anita = (fontes.get("anita") or {}).get("dados") or {}
    cons = anita.get("consolidado_impala") or {}
    if cons:
        share = cons.get("share_impala_global_pct")
        margem = cons.get("margem_media_pct")
        out.append(
            _acao(
                camada="core",
                titulo="Posição Impala vs Anita (kits monitorados)",
                detalhe=(
                    f"Share Impala {share}% | margem média {margem}% — "
                    "use cores líderes como isca; não dependa só do unitário."
                ),
                prioridade=2,
                horizonte="7d",
                score=70 + (5 if float(share or 0) >= 50 else 0),
                evidencias=[
                    f"vendas_impala={cons.get('unidades_vendidas_impala')}",
                    f"vendas_anita={cons.get('unidades_vendidas_anita')}",
                ],
            )
        )
    return out


def _acoes_anexos(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rem = (fontes.get("removedores") or {}).get("dados") or {}
    cons = rem.get("consolidado") or rem
    if (fontes.get("removedores") or {}).get("disponivel"):
        top = cons.get("ranking_fabricantes") or cons.get("top_produtos") or []
        nome = ""
        if top and isinstance(top[0], dict):
            nome = str(top[0].get("fabricante") or top[0].get("nome") or top[0].get("titulo") or "")
        out.append(
            _acao(
                camada="anexos",
                titulo="Removedor — anexo de margem no funil",
                detalhe=(
                    "Ofereça combo esmalte + removedor"
                    + (f" (líder: {nome[:40]})" if nome else "")
                    + ". Anexo paga o negócio; cor só atrai."
                ),
                prioridade=1,
                horizonte="7d",
                score=78,
                evidencias=["snapshot removedores_unha"],
            )
        )
    else:
        out.append(
            _acao(
                camada="anexos",
                titulo="Rodar monitor de removedores",
                detalhe="Sem snapshot de removedores — rode o agente para destravar a camada anexos.",
                prioridade=2,
                horizonte="7d",
                score=40,
                evidencias=["fonte_ausente"],
            )
        )

    acet = (fontes.get("acetona") or {}).get("dados") or {}
    if (fontes.get("acetona") or {}).get("disponivel") or acet.get("consolidado"):
        out.append(
            _acao(
                camada="anexos",
                titulo="Acetona / removedor profissional (Cruzeiro)",
                detalhe="Empurre acetona/removedor com kits B2B — recompra do salão.",
                prioridade=2,
                horizonte="30d",
                score=72,
                evidencias=["snapshot acetona_cruzeiro"],
            )
        )
    return out


def _acoes_kits(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    montar = (fontes.get("montar_kits") or {}).get("dados") or {}
    cruz = montar.get("cruzamento") or {}
    sugeridos = cruz.get("kits_sugeridos") or []
    tamanhos = cruz.get("tamanhos_quentes_ml") or []

    if sugeridos:
        for i, s in enumerate(sugeridos[:3]):
            nomes = ", ".join(str(c.get("nome_cor") or "") for c in (s.get("cores") or [])[:5])
            horizonte = "7d" if i == 0 else "30d"
            out.append(
                _acao(
                    camada="kits",
                    titulo=str(s.get("nome_sugerido") or f"Kit sugerido {i+1}"),
                    detalhe=f"Cores: {nomes} | faixa {s.get('preco_sugerido_faixa') or 'n/d'}",
                    prioridade=1 if i == 0 else 2,
                    horizonte=horizonte,
                    score=85 - i * 5 + float(s.get("score_medio") or 0) / 10,
                    evidencias=[f"score_medio={s.get('score_medio')}"],
                )
            )
    else:
        out.append(
            _acao(
                camada="kits",
                titulo="Montar 3 kits padrão do ecossistema",
                detalhe=(
                    "Iniciante (3–5 cores) · Profissional (10–15) · Reposição (atacado). "
                    "Rode montar_kits_impala se o snapshot estiver vazio."
                ),
                prioridade=1,
                horizonte="7d",
                score=55,
                evidencias=["sem_kits_sugeridos"],
            )
        )

    if tamanhos:
        partes = [f"kit {t.get('qtd')} ({t.get('vendas')} vend.)" for t in tamanhos[:4]]
        out.append(
            _acao(
                camada="kits",
                titulo="Tamanhos quentes no ML",
                detalhe=" · ".join(partes),
                prioridade=2,
                horizonte="30d",
                score=68,
                evidencias=["tamanhos_quentes_ml"],
            )
        )
    return out


def _acoes_b2b(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    nec = (fontes.get("necessidade") or {}).get("dados") or {}
    escolhida = nec.get("escolhida") or (nec.get("plano") or {}).get("escolhida")
    if isinstance(escolhida, dict) and escolhida:
        out.append(
            _acao(
                camada="b2b",
                titulo=f"Oferta manicures: {escolhida.get('campanha_nome') or 'campanha'}",
                detalhe=str(
                    (escolhida.get("condicoes") or {}).get("cta")
                    or escolhida.get("copy_whatsapp")
                    or "Validar match e enviar após SIM do gestor"
                )[:200],
                prioridade=1,
                horizonte="7d",
                score=float(escolhida.get("score") or 75),
                evidencias=[f"angulo={(escolhida.get('condicoes') or {}).get('angulo')}"],
            )
        )
    else:
        out.append(
            _acao(
                camada="b2b",
                titulo="Canal manicure — reposição semanal",
                detalhe=(
                    "Defina pacote atacado (20–50 un.) + frete. "
                    "Use necessidade_manicures / promocoes para validar demanda."
                ),
                prioridade=2,
                horizonte="30d",
                score=60,
                evidencias=["sem_escolhida_necessidade"],
            )
        )

    conv = (fontes.get("conversao") or {}).get("dados") or {}
    diag = (conv.get("diagnostico") or {}).get("canais") or {}
    pendentes = (conv.get("diagnostico") or {}).get("pendentes") or []
    if pendentes:
        out.append(
            _acao(
                camada="b2b",
                titulo="Destravar canais de conversão manicures",
                detalhe=f"Pendentes: {', '.join(str(p) for p in pendentes[:5])}",
                prioridade=2,
                horizonte="7d",
                score=65,
                evidencias=[f"{k}={v.get('status')}" for k, v in list(diag.items())[:4] if isinstance(v, dict)],
            )
        )
    return out


def _acoes_conteudo(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tend = (fontes.get("tendencias") or {}).get("dados") or {}
    segs = tend.get("segmentos") or tend.get("resultados") or []
    quentes = [
        s
        for s in segs
        if isinstance(s, dict)
        and str(s.get("status") or "").lower() in ("oportunidade", "emergente", "confirmada")
    ]
    if quentes:
        nomes = [str(s.get("nome") or s.get("id") or "?") for s in quentes[:4]]
        out.append(
            _acao(
                camada="conteudo",
                titulo="Cor / tendência do mês",
                detalhe=f"Campanha conteúdo + combo: {', '.join(nomes)}",
                prioridade=1,
                horizonte="7d",
                score=76,
                evidencias=[str(s.get("status")) for s in quentes[:3]],
            )
        )
    else:
        out.append(
            _acao(
                camada="conteudo",
                titulo="Definir cor do mês + combo obrigatório",
                detalhe="Esmalte âncora + base/top em toda campanha Meta/WA. Rode tendências se vazio.",
                prioridade=2,
                horizonte="30d",
                score=50,
                evidencias=["sem_tendencia_quente"],
            )
        )

    busca = (fontes.get("busca_kit") or {}).get("dados") or {}
    itens = busca.get("resultados") or busca.get("kits") or []
    if itens:
        top = itens[0] if isinstance(itens[0], dict) else {}
        out.append(
            _acao(
                camada="conteudo",
                titulo="Demanda de busca kit (frequência ML)",
                detalhe=(
                    f"Mais buscado: {top.get('nome') or top.get('id')} "
                    f"(vol={top.get('volume') or top.get('frequencia') or 'n/d'})"
                ),
                prioridade=2,
                horizonte="7d",
                score=70,
                evidencias=[str(top.get("marca") or "")],
            )
        )
    return out


def _acoes_marca(fontes: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    anita = (fontes.get("anita") or {}).get("dados") or {}
    cons = anita.get("consolidado_impala") or {}
    if cons:
        lider = float(cons.get("share_impala_global_pct") or 0) >= 50
        out.append(
            _acao(
                camada="marca",
                titulo="Defesa de marca Impala no ecossistema",
                detalhe=(
                    "Mantenha kits exclusivos + anexos Cruzeiro/Impala"
                    if lider
                    else "Diferencie por kit/anexo — preço unitário sozinho perde para Anita"
                ),
                prioridade=2,
                horizonte="90d",
                score=70 if lider else 62,
                evidencias=[f"share_impala={cons.get('share_impala_global_pct')}"],
            )
        )
    else:
        out.append(
            _acao(
                camada="marca",
                titulo="Linha própria / exclusividade de coleção",
                detalhe="Meta 90d: kit ou cor exclusivos para sair da guerra só de preço no ML.",
                prioridade=3,
                horizonte="90d",
                score=45,
                evidencias=["sem_comparativo_anita"],
            )
        )
    return out


def montar_plano(fontes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gera plano completo do ecossistema com ações priorizadas."""
    fontes = fontes or coletar_fontes()
    acoes: list[dict[str, Any]] = []
    acoes.extend(_acoes_core(fontes))
    acoes.extend(_acoes_anexos(fontes))
    acoes.extend(_acoes_kits(fontes))
    acoes.extend(_acoes_b2b(fontes))
    acoes.extend(_acoes_conteudo(fontes))
    acoes.extend(_acoes_marca(fontes))

    acoes.sort(key=lambda a: (int(a.get("prioridade") or 9), -float(a.get("score") or 0)))

    por_camada: dict[str, list[dict[str, Any]]] = {c: [] for c in _CAMADAS}
    for a in acoes:
        por_camada.setdefault(a["camada"], []).append(a)

    por_horizonte = {"7d": [], "30d": [], "90d": []}
    for a in acoes:
        h = a.get("horizonte") or "30d"
        por_horizonte.setdefault(h, []).append(a)

    disponiveis = [k for k, v in fontes.items() if v.get("disponivel")]
    ausentes = [k for k, v in fontes.items() if not v.get("disponivel")]

    score_ecossistema = 0.0
    if acoes:
        # média ponderada: prioridade 1 pesa mais
        pesos = []
        vals = []
        for a in acoes:
            p = int(a.get("prioridade") or 3)
            w = 3 if p == 1 else (2 if p == 2 else 1)
            pesos.append(w)
            vals.append(float(a.get("score") or 0) * w)
        score_ecossistema = sum(vals) / max(1, sum(pesos))

    cobertura = round(100.0 * len(disponiveis) / max(1, len(_PATHS)), 1)

    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tese": (
            "O esmalte atrai; o kit, o B2B e a reposição (anexos) pagam o negócio. "
            "Não viva só do hit de cor."
        ),
        "score_ecossistema": round(score_ecossistema, 1),
        "cobertura_fontes_pct": cobertura,
        "fontes_disponiveis": disponiveis,
        "fontes_ausentes": ausentes,
        "acoes": acoes,
        "por_camada": por_camada,
        "por_horizonte": por_horizonte,
        "top_7d": por_horizonte.get("7d", [])[:6],
        "regra": "core=tráfego · anexos=margem · kits=AOV · b2b=recorrência · conteudo=demanda · marca=defesa",
    }


def montar_mensagem_telegram(plano: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente(
            "ecossistema_esmaltes",
            "💅 *Ecossistema esmaltes — plano de reprodução*",
        ),
        "",
        f"_{plano.get('tese')}_",
        "",
        f"Score ecossistema: *{plano.get('score_ecossistema')}* | "
        f"cobertura fontes: *{plano.get('cobertura_fontes_pct')}%*",
    ]

    ausentes = plano.get("fontes_ausentes") or []
    if ausentes:
        linhas.append(f"_Fontes faltando: {', '.join(ausentes[:6])}_")

    top = plano.get("top_7d") or []
    if top:
        linhas.extend(["", "*Próximos 7 dias (prioridade)*"])
        for i, a in enumerate(top[:5], 1):
            linhas.append(
                f"{i}. [{a.get('camada')}] *{a.get('titulo')}* (score {a.get('score')})"
            )
            if a.get("detalhe"):
                linhas.append(f"   _{str(a['detalhe'])[:120]}_")

    por_h = plano.get("por_horizonte") or {}
    for rotulo, chave in (("30 dias", "30d"), ("90 dias", "90d")):
        items = por_h.get(chave) or []
        if not items:
            continue
        linhas.extend(["", f"*{rotulo}*"])
        for a in items[:3]:
            linhas.append(f"• [{a.get('camada')}] {a.get('titulo')}")

    linhas.extend(
        [
            "",
            f"_Regra:_ {plano.get('regra')}",
            "",
            "*Próximo passo:* execute as ações 7d (kits + combo anexo + oferta manicure); "
            "depois reposição B2B e cor do mês.",
        ]
    )
    return "\n".join(linhas).strip()
