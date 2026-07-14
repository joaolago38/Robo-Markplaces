"""
integracoes/social/necessidade_manicures.py
Cruza sinais de necessidade das manicures com o que temos no catálogo/ML
e monta plano de condições para oferta nos canais (WA/TG).

Não efetiva Ads nem FB/IG. Não inventa MLB / estoque positivo.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.atomic_io import ler_json
from core.config import ROOT
from integracoes.social.promocoes_manicures import carregar_campanhas, montar_mensagem_campanha

logger = logging.getLogger("necessidade_manicures")

TENDENCIAS_PATH = ROOT / "logs" / "esmaltes_tendencias_ultima.json"
BUSCA_KIT_PATH = ROOT / "logs" / "esmaltes_busca_kit_ultima.json"
ANITA_PATH = ROOT / "logs" / "anita_esmaltes_ultima.json"
LEADS_PATH = ROOT / "logs" / "leads_manicures.json"
CONVERSAO_PATH = ROOT / "logs" / "conversao_manicures_ultima.json"
KITS_PATH = ROOT / "logs" / "esmaltes_kits_monitor_ultima.json"

_KW_ATACADO = re.compile(r"atacado|revend|estoque|kit\s*10|kit\s*15|kit\s*30", re.I)
_KW_KIT_PEQ = re.compile(r"kit\s*[3-6]\b|entrada|mimo|bailarina|sortido", re.I)
_KW_COR = re.compile(
    r"nude|vermelho|rosa|vinho|preto|branco|coffee|esmalte|cor\b|cores",
    re.I,
)
_KW_FULL = re.compile(r"full|frete|entrega", re.I)
_KW_ANITA = re.compile(r"anita|concorr", re.I)


def _txt(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, dict):
        return " ".join(_txt(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return " ".join(_txt(v) for v in obj)
    return str(obj)


def coletar_sinais() -> list[dict[str, Any]]:
    """Extrai sinais leves dos snapshots (sem re-scrape)."""
    sinais: list[dict[str, Any]] = []

    tend = ler_json(TENDENCIAS_PATH, default={})
    if isinstance(tend, dict):
        for seg in (tend.get("segmentos") or tend.get("resultados") or [])[:12]:
            if not isinstance(seg, dict):
                continue
            status = str(seg.get("status") or "").lower()
            nome = str(seg.get("nome") or seg.get("id") or "tendencia")
            peso = 35
            if status in ("oportunidade", "emergente"):
                peso = 55
            elif status == "confirmada":
                peso = 45
            sinais.append(
                {
                    "fonte": "tendencias",
                    "rotulo": nome,
                    "texto": _txt(seg)[:400],
                    "peso": peso,
                    "meta": {"status": status},
                }
            )

    busca = ler_json(BUSCA_KIT_PATH, default={})
    if isinstance(busca, dict):
        for item in (busca.get("resultados") or busca.get("kits") or [])[:15]:
            if not isinstance(item, dict):
                continue
            sinais.append(
                {
                    "fonte": "busca_kit",
                    "rotulo": str(item.get("nome") or item.get("id") or "busca"),
                    "texto": _txt(item)[:400],
                    "peso": 40
                    + min(20, int(item.get("volume") or item.get("frequencia") or 0) // 10),
                    "meta": {
                        "marca": item.get("marca"),
                        "cor_foco": item.get("cor_foco"),
                    },
                }
            )

    anita = ler_json(ANITA_PATH, default={})
    if isinstance(anita, dict):
        for r in (anita.get("resultados") or [])[:10]:
            if not isinstance(r, dict):
                continue
            peso = 30
            if r.get("diff_preco_impala_vs_meu_pct") is not None:
                try:
                    if float(r["diff_preco_impala_vs_meu_pct"]) < -5:
                        peso = 50  # mercado mais barato → pressão competitiva
                except (TypeError, ValueError):
                    pass
            sinais.append(
                {
                    "fonte": "anita",
                    "rotulo": str(r.get("nome") or r.get("termo_busca") or "anita"),
                    "texto": _txt(r)[:400],
                    "peso": peso,
                    "meta": {
                        "share_impala": r.get("share_impala_pct"),
                        "tipo": r.get("tipo"),
                    },
                }
            )

    leads = ler_json(LEADS_PATH, default={})
    lead_list = leads.get("leads") if isinstance(leads, dict) else leads
    if isinstance(lead_list, list):
        contagem: dict[str, int] = {}
        amostras: dict[str, str] = {}
        for lead in lead_list[-40:]:
            if not isinstance(lead, dict):
                continue
            intencao = str(lead.get("intencao") or "interesse").lower()
            contagem[intencao] = contagem.get(intencao, 0) + 1
            if intencao not in amostras:
                amostras[intencao] = str(lead.get("texto") or lead.get("mensagem") or "")[:200]
        for intencao, n in contagem.items():
            sinais.append(
                {
                    "fonte": "leads",
                    "rotulo": f"lead:{intencao}",
                    "texto": f"{intencao} x{n} {amostras.get(intencao, '')}",
                    "peso": 25 + min(30, n * 5),
                    "meta": {"intencao": intencao, "count": n},
                }
            )

    kits = ler_json(KITS_PATH, default={})
    if isinstance(kits, dict):
        for k in (kits.get("resultados") or [])[:8]:
            if not isinstance(k, dict):
                continue
            sinais.append(
                {
                    "fonte": "kits_monitor",
                    "rotulo": str(k.get("nome") or k.get("id") or "kit"),
                    "texto": _txt(k)[:300],
                    "peso": 28,
                    "meta": {},
                }
            )

    return sinais


def _angulo_do_texto(texto: str) -> str:
    if _KW_ATACADO.search(texto):
        return "atacado"
    if _KW_ANITA.search(texto):
        return "competicao_anita"
    if _KW_KIT_PEQ.search(texto):
        return "kit_entrada"
    if _KW_FULL.search(texto):
        return "full_entrega"
    if _KW_COR.search(texto):
        return "cores"
    return "geral"


def _score_campanha_vs_sinal(campanha: dict[str, Any], montado: dict[str, Any], sinal: dict[str, Any]) -> int:
    blob = " ".join(
        [
            str(campanha.get("id") or ""),
            str(campanha.get("nome") or ""),
            str(campanha.get("sku") or ""),
            str(montado.get("texto") or "")[:200],
            str(sinal.get("texto") or ""),
            str(sinal.get("rotulo") or ""),
        ]
    ).lower()
    score = int(sinal.get("peso") or 20)
    angulo = _angulo_do_texto(str(sinal.get("texto") or ""))

    if angulo == "atacado" and ("atac" in blob or "10" in blob or "15" in blob):
        score += 25
    if angulo == "kit_entrada" and any(x in blob for x in ("mimo", "bailarina", "kit 3", "kit 5", "kit 6")):
        score += 22
    if angulo == "competicao_anita" and ("bailarina" in blob or "kit 5" in blob or "impala" in blob):
        score += 20
    if angulo == "cores" and any(x in blob for x in ("sortido", "cores", "bailarina")):
        score += 12
    if angulo == "full_entrega":
        score += 8

    if montado.get("link_valido"):
        score += 15
    else:
        score -= 40

    try:
        est = int(montado.get("estoque") or 0)
    except (TypeError, ValueError):
        est = 0
    # montar_mensagem não traz estoque — usamos meta do produto se injetarmos
    if est > 0:
        score += 10
    elif est == 0 and montado.get("_estoque_conhecido"):
        score -= 15

    return score


def _estoque_campanha(sku: str) -> tuple[int | None, bool]:
    """Retorna (estoque, conhecido). Preferência: Bling via lookup por SKU."""
    sku = (sku or "").strip()
    if not sku:
        return None, False
    try:
        from integracoes.bling.bling_client import buscar_produto

        p = buscar_produto(sku) or {}
        if p:
            return int(p.get("estoque") or 0), True
    except Exception as exc:
        logger.debug("estoque Bling indisponível sku=%s: %s", sku, exc)
    try:
        from core.catalogo_produtos import carregar_produtos_catalogo

        for prod in carregar_produtos_catalogo():
            if str(prod.get("sku") or "").strip().upper() == sku.upper():
                ml = (prod.get("canais") or {}).get("mercadolivre") or {}
                try:
                    return int(ml.get("estoque") if ml.get("estoque") is not None else prod.get("estoque") or 0), True
                except (TypeError, ValueError):
                    return 0, True
    except Exception:
        pass
    return None, False


def _status_sustentabilidade() -> dict[str, Any]:
    conv = ler_json(CONVERSAO_PATH, default={})
    if not isinstance(conv, dict):
        return {"status": "insuficiente_dados", "permitido_impulsionar": True}
    ads = conv.get("ads") if isinstance(conv.get("ads"), dict) else {}
    sust = ads.get("sustentabilidade") or conv.get("sustentabilidade") or {}
    if not isinstance(sust, dict):
        sust = {}
    status = str(sust.get("status") or "insuficiente_dados")
    permitido = status in ("sustentavel", "insuficiente_dados", "")
    if status == "critico":
        permitido = False
    return {
        "status": status or "insuficiente_dados",
        "permitido_impulsionar": permitido,
        "roas_real": sust.get("roas_real"),
        "recomendacao": sust.get("recomendacao"),
    }


def casar_necessidades_com_ml(
    sinais: list[dict[str, Any]] | None = None,
    *,
    top_n: int = 5,
) -> dict[str, Any]:
    """
    Retorna plano com matches ordenados por score.
    Cada match: campanha + condições + se pode_enviar.
    """
    sinais = sinais if sinais is not None else coletar_sinais()
    campanhas = carregar_campanhas()
    sust = _status_sustentabilidade()

    candidatos: list[dict[str, Any]] = []
    gaps: list[str] = []

    if not sinais:
        gaps.append("sem_sinais_nos_snapshots")
    if not campanhas:
        gaps.append("sem_campanhas_ativas")

    for campanha in campanhas:
        montado = montar_mensagem_campanha(campanha)
        if not montado.get("ok"):
            gaps.append(f"campanha_invalida:{campanha.get('id')}:{montado.get('motivo')}")
            continue

        sku = str(montado.get("sku") or campanha.get("sku") or "")
        estoque, est_conhecido = _estoque_campanha(sku)
        montado = dict(montado)
        if est_conhecido and estoque is not None:
            montado["estoque"] = estoque
            montado["_estoque_conhecido"] = True

        melhor_sinal: dict[str, Any] | None = None
        melhor_score = -999
        for sinal in sinais or [{"fonte": "fallback", "rotulo": "giro", "texto": "kit manicure", "peso": 15}]:
            sc = _score_campanha_vs_sinal(campanha, montado, sinal)
            if sc > melhor_score:
                melhor_score = sc
                melhor_sinal = sinal

        link_ok = bool(montado.get("link_valido"))
        pode_enviar = (
            link_ok
            and bool(sust.get("permitido_impulsionar"))
            and (not est_conhecido or (estoque or 0) > 0 or estoque is None)
        )
        # Se estoque conhecido e 0 → não enviar
        if est_conhecido and estoque is not None and estoque <= 0:
            pode_enviar = False
            gaps.append(f"estoque_zero:{sku}")

        if not link_ok:
            gaps.append(f"link_invalido:{campanha.get('id')}")

        angulo = _angulo_do_texto(
            f"{(melhor_sinal or {}).get('texto', '')} {campanha.get('nome', '')}"
        )
        condicoes = {
            "preco_brl": montado.get("preco_brl"),
            "link_ml": montado.get("link_ml") if link_ok else "",
            "angulo": angulo,
            "canais_sugeridos": ["whatsapp", "telegram"],
            "cta": (
                f"Kit no Mercado Livre por R$ {montado.get('preco_brl')} — "
                f"{'link pronto' if link_ok else 'aguardando MLB real'}"
            ),
            "obs_estoque": (
                f"estoque={estoque}" if est_conhecido else "estoque não confirmado (Bling/catálogo)"
            ),
            "sust_ads": sust.get("status"),
        }

        copy = str(montado.get("texto_whatsapp") or montado.get("texto") or "").strip()
        if link_ok and montado.get("link_ml") and montado["link_ml"] not in copy:
            copy = f"{copy}\n\n{montado['link_ml']}".strip()

        candidatos.append(
            {
                "campanha_id": campanha.get("id"),
                "campanha_nome": montado.get("campanha_nome") or campanha.get("nome"),
                "sku": sku,
                "score": melhor_score,
                "sinal": {
                    "fonte": (melhor_sinal or {}).get("fonte"),
                    "rotulo": (melhor_sinal or {}).get("rotulo"),
                },
                "link_valido": link_ok,
                "pode_enviar": pode_enviar,
                "condicoes": condicoes,
                "copy_whatsapp": copy,
                "copy_telegram": str(montado.get("texto_telegram") or montado.get("texto") or copy),
                "aviso_link": montado.get("aviso_link") or "",
            }
        )

    candidatos.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    top = candidatos[: max(1, top_n)]
    atendiveis = [c for c in top if c.get("pode_enviar")]
    escolhida = atendiveis[0] if atendiveis else (top[0] if top else None)

    return {
        "ok": True,
        "sinais_lidos": len(sinais or []),
        "campanhas_avaliadas": len(campanhas),
        "sustentabilidade": sust,
        "matches": top,
        "escolhida": escolhida,
        "gaps": list(dict.fromkeys(gaps))[:20],
        "pronto_enviar": bool(escolhida and escolhida.get("pode_enviar")),
    }


def montar_mensagem_gestor(plano: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    esc = plano.get("escolhida") or {}
    sust = plano.get("sustentabilidade") or {}
    linhas = [
        cabecalho_agente(
            "necessidade_manicures",
            "🎯 *Necessidade manicures × ML*",
        ),
        "",
        f"_Sinais lidos: {plano.get('sinais_lidos', 0)} | "
        f"Campanhas: {plano.get('campanhas_avaliadas', 0)}_",
        f"_Ads×ML: {sust.get('status') or 'n/d'} (ROAS {sust.get('roas_real') or 'n/d'})_",
        "",
    ]
    if esc:
        cond = esc.get("condicoes") or {}
        linhas.extend(
            [
                f"*Melhor match:* {esc.get('campanha_nome') or esc.get('campanha_id')}",
                f"Score {esc.get('score')} · sinal {(esc.get('sinal') or {}).get('fonte')}/"
                f"{(esc.get('sinal') or {}).get('rotulo')}",
                f"Ângulo: {cond.get('angulo')} | {cond.get('cta')}",
                f"Estoque: {cond.get('obs_estoque')}",
                f"Pode enviar canais: {'SIM' if esc.get('pode_enviar') else 'NÃO'}",
            ]
        )
        if esc.get("aviso_link"):
            linhas.append(f"⚠️ {esc.get('aviso_link')}")
    else:
        linhas.append("_Nenhum match com o catálogo atual._")

    gaps = plano.get("gaps") or []
    if gaps:
        linhas.extend(["", "*Gaps:*", *[f"• {g}" for g in gaps[:8]]])

    outros = [m for m in (plano.get("matches") or []) if m is not esc][:3]
    if outros:
        linhas.append("")
        linhas.append("*Outros candidatos:*")
        for m in outros:
            linhas.append(
                f"• {m.get('campanha_nome')} (score {m.get('score')}, "
                f"{'ok' if m.get('pode_enviar') else 'bloqueado'})"
            )

    linhas.extend(
        [
            "",
            "_Se confirmar SIM: envia oferta no WhatsApp grupo e/ou Telegram manicures._",
            "_Não publica FB/IG nem altera Product Ads._",
        ]
    )
    return "\n".join(linhas).strip()
