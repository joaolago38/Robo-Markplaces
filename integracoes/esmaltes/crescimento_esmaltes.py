"""
integracoes/esmaltes/crescimento_esmaltes.py
Fecha o loop do plano anual:
  - kits sugeridos / catálogo sem MLB real
  - KPI kits % receita + margem
  - checklist humano
  - combo anexo no copy de ofertas
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ROOT

MONTAR_KITS_PATH = ROOT / "logs" / "montar_kits_impala_ultima.json"
MARGEM_PATH = ROOT / "logs" / "margem_vendas_ultima.json"
ECOSSISTEMA_PATH = ROOT / "logs" / "ecossistema_esmaltes_ultima.json"
CONVERSAO_PATH = ROOT / "logs" / "conversao_manicures_ultima.json"

_ITEM_INVALIDO = frozenset({"", "MLB_PREENCHER", "MLB-PREENCHER"})
_KIT_RE = re.compile(r"\bkit\b|imp-", re.I)
_COMBO_RE = re.compile(r"removedor|acetona|base\s*\+?\s*top|top\s*coat|anexo", re.I)

COMBO_LINHA_TELEGRAM = (
    "🧴 *Combo salão:* leve também removedor ou base+top — reposição com margem."
)
COMBO_LINHA_WHATSAPP = (
    "🧴 Combo salão: leve também removedor ou base+top — reposição com margem."
)


def _item_id_ml(produto: dict[str, Any]) -> str:
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    return str(ml.get("item_id") or "").strip().upper().replace("-", "")


def _mlb_valido(item_id: str) -> bool:
    iid = (item_id or "").strip().upper().replace("-", "")
    if not iid or iid in _ITEM_INVALIDO:
        return False
    return iid.startswith("MLB") and len(iid) >= 8 and iid[3:].isdigit()


def eh_kit_catalogo(produto: dict[str, Any]) -> bool:
    sku = str(produto.get("sku") or "")
    nome = str(produto.get("nome") or "")
    titulo = str(
        ((produto.get("canais") or {}).get("mercadolivre") or {}).get("titulo_anuncio") or ""
    )
    return bool(_KIT_RE.search(f"{sku} {nome} {titulo}"))


def anexar_combo_oferta(texto: str, *, whatsapp: bool = False) -> str:
    """Garante linha de combo anexo no copy (idempotente)."""
    base = (texto or "").rstrip()
    if not base:
        return COMBO_LINHA_WHATSAPP if whatsapp else COMBO_LINHA_TELEGRAM
    if _COMBO_RE.search(base):
        return base
    linha = COMBO_LINHA_WHATSAPP if whatsapp else COMBO_LINHA_TELEGRAM
    return f"{base}\n\n{linha}"


def listar_kits_catalogo_sem_mlb(
    produtos: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Kits ativos no catálogo sem item_id MLB real."""
    out: list[dict[str, Any]] = []
    for p in produtos if produtos is not None else carregar_produtos_catalogo():
        if not isinstance(p, dict) or not eh_kit_catalogo(p):
            continue
        ml = (p.get("canais") or {}).get("mercadolivre") or {}
        if ml.get("ativo") is False:
            continue
        iid = _item_id_ml(p)
        if _mlb_valido(iid):
            continue
        out.append(
            {
                "sku": p.get("sku"),
                "nome": p.get("nome"),
                "item_id": iid or "MLB_PREENCHER",
                "titulo_anuncio": ml.get("titulo_anuncio"),
                "motivo": "mlb_ausente_ou_placeholder",
            }
        )
    return out


def listar_kits_sugeridos_pendentes(
    *,
    montar: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Kits sugeridos pelo montar_kits_impala sem correspondente MLB no catálogo.
    Match por cores do kit vs nome/título do produto.
    """
    data = montar if montar is not None else ler_json(MONTAR_KITS_PATH, default={})
    if not isinstance(data, dict):
        data = {}
    cruz = data.get("cruzamento") or {}
    sugeridos = cruz.get("kits_sugeridos") or []
    catalogo = produtos if produtos is not None else carregar_produtos_catalogo()
    kits_cat = [p for p in catalogo if isinstance(p, dict) and eh_kit_catalogo(p)]

    pendentes: list[dict[str, Any]] = []
    for sug in sugeridos:
        if not isinstance(sug, dict):
            continue
        cores = [
            str(c.get("nome_cor") or "").strip().lower()
            for c in (sug.get("cores") or [])
            if isinstance(c, dict) and c.get("nome_cor")
        ]
        nome_sug = str(sug.get("nome_sugerido") or "kit sugerido")
        match = None
        for p in kits_cat:
            blob = " ".join(
                [
                    str(p.get("nome") or ""),
                    str(
                        ((p.get("canais") or {}).get("mercadolivre") or {}).get("titulo_anuncio")
                        or ""
                    ),
                ]
            ).lower()
            hits = sum(1 for cor in cores if cor and cor in blob)
            if cores and hits >= max(1, (len(cores) + 1) // 2):
                match = p
                break
            # nome sugerido parcial
            if any(tok and tok in blob for tok in re.split(r"\W+", nome_sug.lower()) if len(tok) > 3):
                if _mlb_valido(_item_id_ml(p)):
                    match = p
                    break

        if match and _mlb_valido(_item_id_ml(match)):
            continue

        pendentes.append(
            {
                "nome_sugerido": nome_sug,
                "cores": [c.get("nome_cor") for c in (sug.get("cores") or []) if isinstance(c, dict)][
                    :6
                ],
                "faixa": sug.get("preco_sugerido_faixa"),
                "sku_parcial": (match or {}).get("sku") if match else None,
                "motivo": (
                    "catalogo_sem_mlb"
                    if match
                    else "sem_anuncio_no_catalogo"
                ),
            }
        )
    return pendentes


def calcular_kpis(
    *,
    margem_snap: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
    meta_kits_pct: float = 40.0,
    meta_margem_pct: float = 15.0,
) -> dict[str, Any]:
    """KPIs a partir do snapshot de margem + classificação kit no catálogo."""
    snap = margem_snap if margem_snap is not None else ler_json(MARGEM_PATH, default={})
    if not isinstance(snap, dict):
        snap = {}
    analise = snap.get("analise") or {}
    linhas = snap.get("linhas") or []
    catalogo = produtos if produtos is not None else carregar_produtos_catalogo()
    kits_sku = {
        str(p.get("sku") or "").strip().upper()
        for p in catalogo
        if isinstance(p, dict) and eh_kit_catalogo(p)
    }

    receita_total = float(analise.get("receita_bruta") or 0)
    if receita_total <= 0:
        receita_total = sum(float(lin.get("receita_bruta") or 0) for lin in linhas if isinstance(lin, dict))

    receita_kits = 0.0
    for lin in linhas:
        if not isinstance(lin, dict):
            continue
        sku = str(lin.get("sku") or "").strip().upper()
        if sku in kits_sku or _KIT_RE.search(sku):
            receita_kits += float(lin.get("receita_bruta") or 0)

    kits_pct = round(100.0 * receita_kits / receita_total, 1) if receita_total > 0 else None
    try:
        margem_media_f = (
            float(analise["margem_media_pct"])
            if analise.get("margem_media_pct") is not None
            else None
        )
    except (TypeError, ValueError):
        margem_media_f = None

    return {
        "receita_bruta": round(receita_total, 2),
        "receita_kits": round(receita_kits, 2),
        "kits_pct_receita": kits_pct,
        "margem_media_pct": margem_media_f,
        "meta_kits_pct": meta_kits_pct,
        "meta_margem_pct": meta_margem_pct,
        "kits_meta_ok": (kits_pct is not None and kits_pct >= meta_kits_pct),
        "margem_meta_ok": (
            margem_media_f is not None and margem_media_f >= meta_margem_pct
        ),
        "itens_analisados": int(analise.get("total_itens") or len(linhas) or 0),
        "sem_vendas_periodo": receita_total <= 0,
    }


def diagnostico_canais(
    conversao: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = conversao if conversao is not None else ler_json(CONVERSAO_PATH, default={})
    if not isinstance(data, dict):
        data = {}
    diag = (data.get("diagnostico") or {}).get("canais") or {}
    pendentes = list((data.get("diagnostico") or {}).get("pendentes") or [])
    return {
        "pendentes": pendentes,
        "whatsapp_ok": (diag.get("whatsapp") or {}).get("pronto") is True,
        "instagram_ok": (diag.get("instagram") or {}).get("pronto") is True,
        "telegram_manicures_ok": (diag.get("telegram_manicures") or {}).get("pronto") is True,
    }


def montar_checklist(
    *,
    sem_mlb: list[dict[str, Any]],
    sugeridos: list[dict[str, Any]],
    canais: dict[str, Any],
    kpis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Checklist ordenado do que falta fazer (humano + config)."""
    itens: list[dict[str, Any]] = []
    if sem_mlb:
        skus = [str(k.get("sku") or "").upper() for k in sem_mlb if k.get("sku")]
        primeiro = "IMP-MIMO-003" if "IMP-MIMO-003" in skus else (skus[0] if skus else "")
        itens.append(
            {
                "id": "publicar_kits_mlb",
                "prioridade": 1,
                "titulo": (
                    f"Abrir frente: publicar `{primeiro}` "
                    f"(faltam {len(sem_mlb)} MLB no catálogo)"
                ),
                "detalhe": (
                    "Ordem doutrina: MIMO (Mimo+Carmed) → PERL mesmo ciclo → "
                    "JUPAES após 1o pedido. Não abrir 4o SKU."
                ),
                "tipo": "ops",
            }
        )
    if sugeridos:
        itens.append(
            {
                "id": "criar_kits_sugeridos",
                "prioridade": 1,
                "titulo": f"Criar/publicar {len(sugeridos)} kit(s) sugeridos sem anúncio",
                "detalhe": ", ".join(str(s.get("nome_sugerido")) for s in sugeridos[:3]),
                "tipo": "ops",
            }
        )
    if not canais.get("whatsapp_ok"):
        itens.append(
            {
                "id": "config_whatsapp",
                "prioridade": 1,
                "titulo": "Configurar WhatsApp grupo manicures",
                "detalhe": "WHATSAPP_* + WHATSAPP_GRUPO_MANICURES_ID",
                "tipo": "config",
            }
        )
    if not canais.get("instagram_ok"):
        itens.append(
            {
                "id": "config_instagram",
                "prioridade": 2,
                "titulo": "Configurar Instagram conversão manicures",
                "detalhe": "META_INSTAGRAM_ID + imagem IG + PUBLICAR_IG=1",
                "tipo": "config",
            }
        )
    if kpis.get("sem_vendas_periodo"):
        itens.append(
            {
                "id": "gerar_venda_kit",
                "prioridade": 2,
                "titulo": "Sem vendas no período — impulsionar kit com MLB válido",
                "detalhe": "Rode promoções/necessidade após preencher MLB",
                "tipo": "ops",
            }
        )
    elif kpis.get("kits_pct_receita") is not None and not kpis.get("kits_meta_ok"):
        itens.append(
            {
                "id": "subir_share_kits",
                "prioridade": 2,
                "titulo": (
                    f"Kits em {kpis.get('kits_pct_receita')}% da receita "
                    f"(meta {kpis.get('meta_kits_pct')}%)"
                ),
                "detalhe": "Priorizar ads/promo só em kits",
                "tipo": "kpi",
            }
        )
    if (
        kpis.get("margem_media_pct") is not None
        and not kpis.get("margem_meta_ok")
        and not kpis.get("sem_vendas_periodo")
    ):
        itens.append(
            {
                "id": "recuperar_margem",
                "prioridade": 1,
                "titulo": (
                    f"Margem média {kpis.get('margem_media_pct')}% "
                    f"< meta {kpis.get('meta_margem_pct')}%"
                ),
                "detalhe": "Pausar SKU abaixo do piso / subir combo anexo",
                "tipo": "kpi",
            }
        )
    itens.sort(key=lambda x: int(x.get("prioridade") or 9))
    return itens


def montar_relatorio(
    *,
    meta_kits_pct: float = 40.0,
    meta_margem_pct: float = 15.0,
) -> dict[str, Any]:
    produtos = carregar_produtos_catalogo()
    sem_mlb = listar_kits_catalogo_sem_mlb(produtos)
    sugeridos = listar_kits_sugeridos_pendentes(produtos=produtos)
    kpis = calcular_kpis(
        produtos=produtos,
        meta_kits_pct=meta_kits_pct,
        meta_margem_pct=meta_margem_pct,
    )
    canais = diagnostico_canais()
    checklist = montar_checklist(
        sem_mlb=sem_mlb, sugeridos=sugeridos, canais=canais, kpis=kpis
    )
    eco = ler_json(ECOSSISTEMA_PATH, default={})
    score_eco = (eco or {}).get("score_ecossistema") if isinstance(eco, dict) else None

    critico = bool(sem_mlb or sugeridos or not canais.get("whatsapp_ok"))
    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "critico": critico,
        "kits_sem_mlb": sem_mlb,
        "kits_sugeridos_pendentes": sugeridos,
        "kpis": kpis,
        "canais": canais,
        "checklist": checklist,
        "score_ecossistema": score_eco,
        "resumo": {
            "kits_sem_mlb": len(sem_mlb),
            "kits_sugeridos_pendentes": len(sugeridos),
            "checklist": len(checklist),
            "whatsapp_ok": canais.get("whatsapp_ok"),
        },
    }


def montar_mensagem_telegram(rel: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    kpis = rel.get("kpis") or {}
    linhas = [
        cabecalho_agente(
            "crescimento_esmaltes",
            "📈 *Crescimento esmaltes — KPI + gaps*",
        ),
        "",
        (
            f"Score ecossistema: *{rel.get('score_ecossistema') or 'n/d'}* | "
            f"{'🚨 gaps críticos' if rel.get('critico') else '✅ sem gap crítico de publicação/canal'}"
        ),
        "",
        "*KPIs*",
    ]
    if kpis.get("sem_vendas_periodo"):
        linhas.append("_Sem vendas no período do monitor de margem._")
    else:
        kits_pct = kpis.get("kits_pct_receita")
        meta_k = kpis.get("meta_kits_pct")
        ok_k = "✅" if kpis.get("kits_meta_ok") else "⚠️"
        linhas.append(
            f"{ok_k} Kits na receita: *{kits_pct}%* (meta {meta_k}%) — "
            f"R$ {kpis.get('receita_kits')} / R$ {kpis.get('receita_bruta')}"
        )
        margem = kpis.get("margem_media_pct")
        ok_m = "✅" if kpis.get("margem_meta_ok") else "⚠️"
        linhas.append(
            f"{ok_m} Margem média: *{margem}%* (meta {kpis.get('meta_margem_pct')}%)"
        )

    sem = rel.get("kits_sem_mlb") or []
    if sem:
        linhas.extend(["", f"*Kits no catálogo sem MLB ({len(sem)})*"])
        for k in sem[:6]:
            linhas.append(f"• `{k.get('sku')}` — {k.get('nome')}")

    sug = rel.get("kits_sugeridos_pendentes") or []
    if sug:
        linhas.extend(["", f"*Kits sugeridos sem anúncio ({len(sug)})*"])
        for s in sug[:4]:
            cores = ", ".join(str(c) for c in (s.get("cores") or [])[:4])
            linhas.append(f"• {s.get('nome_sugerido')} — {cores}")

    canais = rel.get("canais") or {}
    pend = canais.get("pendentes") or []
    if pend:
        linhas.extend(["", f"*Canais pendentes:* {', '.join(str(p) for p in pend)}"])

    check = rel.get("checklist") or []
    if check:
        linhas.extend(["", "*Checklist (fazer)*"])
        for i, c in enumerate(check[:6], 1):
            linhas.append(f"{i}. [{c.get('tipo')}] {c.get('titulo')}")
            if c.get("detalhe"):
                linhas.append(f"   _{c.get('detalhe')}_")

    linhas.extend(
        [
            "",
            "_Próximo:_ publique/preencha MLB dos kits → ligue WA → rode promoções com combo anexo._",
        ]
    )
    return "\n".join(linhas).strip()
