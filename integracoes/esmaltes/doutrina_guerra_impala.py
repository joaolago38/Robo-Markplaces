"""
integracoes/esmaltes/doutrina_guerra_impala.py
Regra de engajamento: guerra por faixa. Só PERL iguala preço.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from core.atomic_io import ler_json
from core.config import DOUTRINA_GUERRA_IMPALA_CATALOGO, ROOT
from core.datadog_metrics import gauge

logger = logging.getLogger("doutrina_guerra_impala")

CLASSIF_IGNORAR = "ignorar"
CLASSIF_DIFERENCIAR = "diferenciar"
CLASSIF_IGUALAR = "igualar_faixa"
CLASSIF_NAO_PERSEGUIR = "nao_perseguir"

_PRIORIDADE = {
    CLASSIF_IGUALAR: 40,
    CLASSIF_NAO_PERSEGUIR: 30,
    CLASSIF_DIFERENCIAR: 20,
    CLASSIF_IGNORAR: 0,
}

_TAXA_ML_PADRAO = 0.18
_MARGEM_FASE_PADRAO = {1: 0.10, 2: 0.18, 3: 0.25}
CANAIS = ("mercadolivre", "shopee", "magalu", "amazon")
CANAL_REFERENTE = "mercadolivre"

# Título ML da entrada (≤60): busca + marca + coleção + extra + público.
TITULO_MIMO_ML = "Kit 3 Esmaltes Impala Mimo + Carmed Manicure"
_PECAS_TITULO_MIMO = (
    "kit3",
    "esmaltes",
    "impala",
    "mimo",
    "carmed",
    "manicure",
    "sem_francesinha",
)


def pecas_titulo_mimo(titulo: str) -> dict[str, bool]:
    """O que o listing MIMO precisa para atrair manicure (não kit 3 genérico)."""
    t = str(titulo or "").lower()
    return {
        "kit3": bool(re.search(r"\bkit\s*3\b", t)),
        "esmaltes": "esmalte" in t,
        "impala": "impala" in t,
        "mimo": "mimo" in t,
        "carmed": "carmed" in t,
        "manicure": "manicure" in t,
        "sem_francesinha": "francesinha" not in t,
    }


def titulo_mimo_atracao_ok(titulo: str) -> bool:
    pecas = pecas_titulo_mimo(titulo)
    return all(bool(pecas.get(k)) for k in _PECAS_TITULO_MIMO)


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def carregar_doutrina(caminho: str | None = None) -> dict[str, Any]:
    path = ROOT / (caminho or DOUTRINA_GUERRA_IMPALA_CATALOGO)
    data = ler_json(path, default={})
    return data if isinstance(data, dict) else {}


def frente_skus(doutrina: dict[str, Any] | None = None) -> set[str]:
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    return {str(s).strip().upper() for s in (d.get("skus_frente") or []) if str(s).strip()}


def sku_preco_guerra(doutrina: dict[str, Any] | None = None) -> str:
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    return str(d.get("sku_preco") or "IMP-PERL-004").strip().upper()


def sku_pode_mexer_preco(sku: str, doutrina: dict[str, Any] | None = None) -> bool:
    """
    PERL é o único IMP-* que iguala preço.
    SKU fora de IMP-/frente (testes genéricos) não é restringido.
    """
    sku_u = (sku or "").strip().upper()
    if not sku_u:
        return False
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    preco = sku_preco_guerra(d)
    if sku_u.startswith("IMP-"):
        return sku_u == preco
    frente = frente_skus(d)
    if sku_u in frente:
        return sku_u == preco
    return True


def piso_preco(produto: dict[str, Any] | None, doutrina: dict[str, Any] | None = None) -> float | None:
    """Preço mínimo da fase: custo / (1 - taxa ML - margem da fase)."""
    if not isinstance(produto, dict):
        return None
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    custo = _f(produto.get("custo_total") or produto.get("custo"))
    if custo <= 0:
        return None
    try:
        fase = int(produto.get("fase_atual") or 1)
    except (TypeError, ValueError):
        fase = 1
    margens = d.get("margem_por_fase") or {}
    margem = _f(margens.get(str(fase)) or margens.get(fase), _MARGEM_FASE_PADRAO.get(fase, 0.10))
    taxa = _f(d.get("taxa_ml"), _TAXA_ML_PADRAO)
    denom = 1.0 - taxa - margem
    if denom <= 0:
        return None
    return round(custo / denom, 2)


def _rival_ao_vivo(comp: dict[str, Any]) -> bool:
    fonte = str(comp.get("fonte_rival") or "").strip().lower()
    if fonte == "ao_vivo":
        return True
    if fonte in ("ausente", "catalogo"):
        return False
    return comp.get("gap_pct") is not None and int(comp.get("rivais_no_tam") or 0) > 0


def _row(
    *,
    sku: str,
    classificacao: str,
    arma: str,
    fazer: str,
    nao_fazer: str,
    motivo: str,
    disparar: bool,
    gap_pct: float,
    rival_min: float | None,
    piso: float | None,
    nosso_preco: float,
    mlb_ok: bool,
    kit_tag: str,
) -> dict[str, Any]:
    return {
        "sku": sku,
        "classificacao": classificacao,
        "arma": arma,
        "fazer": fazer,
        "nao_fazer": nao_fazer,
        "motivo": motivo,
        "disparar": disparar,
        "score": _PRIORIDADE.get(classificacao, 0) + max(0.0, gap_pct),
        "gap_pct": gap_pct,
        "rival_min": rival_min,
        "piso_preco": piso,
        "nosso_preco": nosso_preco,
        "mlb_ok": mlb_ok,
        "kit_tag": kit_tag,
    }


def classificar_golpe(
    comp: dict[str, Any],
    *,
    produto: dict[str, Any] | None = None,
    doutrina: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Um kit da frente → classificação do golpe (ou None se fora da guerra)."""
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    sku = str(comp.get("sku") or "").strip().upper()
    if not sku:
        return None
    frente = frente_skus(d)
    if frente and sku not in frente:
        return None

    gap = comp.get("gap_pct")
    gap_f = _f(gap) if gap is not None else 0.0
    gap_min = _f(d.get("gap_igualar_pct") or (d.get("gatilhos") or {}).get("gap_pct_min"), 3.0)
    rival_min = _f(comp.get("rival_min")) or None
    nosso = _f(comp.get("nosso_preco"))
    mlb_ok = bool(comp.get("mlb_ok"))
    ao_vivo = _rival_ao_vivo(comp)
    piso = piso_preco(produto, d)
    preco_sku = sku_preco_guerra(d)
    kit_tag = str(comp.get("kit_tag") or f"kit:{sku.lower()}")
    base = dict(
        sku=sku,
        gap_pct=gap_f,
        rival_min=rival_min if rival_min and rival_min > 0 else None,
        piso=piso,
        nosso_preco=nosso,
        mlb_ok=mlb_ok,
        kit_tag=kit_tag,
    )

    if not mlb_ok:
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Publicar MLB da frente (decisão do dia) — golpe de preço não se aplica",
            nao_fazer="Reagir a rival sem anúncio próprio; Ads; 2º CNPJ",
            motivo="sem MLB — guerra de preço ainda não começou",
            disparar=False,
            **base,
        )
    if not ao_vivo or gap is None:
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Manter preço e chat. Esperar rival ao vivo no tamanho",
            nao_fazer="Tratar preço de planilha como guerra",
            motivo="sem rival ao vivo no tamanho",
            disparar=False,
            **base,
        )

    rival = _f(rival_min)
    abaixo_do_piso = bool(piso and rival > 0 and rival < piso)

    if sku == preco_sku:
        if abaixo_do_piso:
            return _row(
                classificacao=CLASSIF_NAO_PERSEGUIR,
                arma="observar",
                fazer=f"Manter `{sku}` no piso da fase (R$ {piso:.2f})",
                nao_fazer="Igualar dump abaixo do custo+taxa; mexer MIMO/JUPAES",
                motivo=f"rival R$ {rival:.2f} < piso R$ {piso:.2f}",
                disparar=True,
                **base,
            )
        if gap_f >= gap_min:
            return _row(
                classificacao=CLASSIF_IGUALAR,
                arma="preco",
                fazer=f"Igualar `{sku}` na faixa (nosso R$ {nosso:.2f} vs rival R$ {rival:.2f})",
                nao_fazer="Furar o piso; baixar MIMO; Ads neste golpe",
                motivo=f"gap {gap_f:.1f}% ≥ {gap_min:.0f}% e rival ≥ piso",
                disparar=True,
                **base,
            )
        return _row(
            classificacao=CLASSIF_IGNORAR,
            arma="observar",
            fazer="Nada. Próxima leitura do radar",
            nao_fazer="Repricing no mesmo dia por variação pontual",
            motivo=f"gap {gap_f:.1f}% < {gap_min:.0f}%",
            disparar=False,
            **base,
        )

    if gap_f >= gap_min:
        return _row(
            classificacao=CLASSIF_DIFERENCIAR,
            arma="listing",
            fazer=f"Diferenciar `{sku}` (título/foto/chat) — preço firme",
            nao_fazer="Baixar este SKU; igualar kit 10/15 no prejuízo",
            motivo=f"gap {gap_f:.1f}% — arma é diferencial, não preço",
            disparar=True,
            **base,
        )
    return _row(
        classificacao=CLASSIF_IGNORAR,
        arma="observar",
        fazer="Nada. Chat segue no ciclo 30 min",
        nao_fazer="Abrir 4º SKU; perseguir centavos",
        motivo=f"gap {gap_f:.1f}% sem urgência",
        disparar=False,
        **base,
    )


def _estoque(produto: dict[str, Any] | None) -> int:
    if not isinstance(produto, dict):
        return 0
    ml = (produto.get("canais") or {}).get("mercadolivre") or {}
    try:
        return max(int(produto.get("estoque_total") or 0), int(ml.get("estoque") or 0))
    except (TypeError, ValueError):
        return 0


def _mlb_ok(produto: dict[str, Any] | None) -> bool:
    from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
    from integracoes.esmaltes.decisao_dia_esmaltes import _item_id

    if not isinstance(produto, dict):
        return False
    return bool(_mlb_valido(_item_id(produto)))


def _carregar_resumo_conta() -> dict[str, Any]:
    snap = ler_json(ROOT / "logs" / "resumo_conta_ml_ultima.json", default={})
    if not isinstance(snap, dict):
        return {}
    out = dict(snap)
    if isinstance(snap.get("reputacao"), dict):
        out.update(snap["reputacao"])
    return out


def _reviews_nota(conta: dict[str, Any]) -> tuple[int, float]:
    reviews = int(
        conta.get("avaliacoes")
        or conta.get("quantidade_avaliacoes")
        or 0
    )
    nota = _f(conta.get("nota") or conta.get("nota_media") or conta.get("rating_average"))
    return reviews, nota


def _proximo_gate(fase: int, checks: dict[str, Any], gat: dict[str, Any]) -> str:
    if fase <= 0:
        if not checks.get("mlb_mimo"):
            return f"Publicar MIMO R$44,90 com titulo {TITULO_MIMO_ML} (estoque 10)"
        return "Entrar estoque MIMO (10 validacao, depois 30)"
    if fase == 1:
        if not checks.get("mlb_perl"):
            return "Publicar PERL R$39,90 no mesmo ciclo (preco congelado)"
        return "Fechar 1o pedido vencedor (chat/perguntas em dia)"
    if fase == 2:
        if not checks.get("mlb_jupaes"):
            return "Publicar JUPAES R$64,90 + combo removedor no copy"
        return (
            f"Juntar {int(gat.get('reviews_ads') or 20)} reviews e nota "
            f"{_f(gat.get('nota_ads'), 4.8):.1f} para Ads"
        )
    if fase == 3:
        return "Amostra ML viva (hoje busca 403) — Ads pode ligar; preco ainda nao"
    if fase == 4:
        return "Estoque MIMO 30+ com frente viva para ruptura"
    return "Outra marca / 2o CNPJ liberados pela doutrina"


def _id_fase(row: dict[str, Any]) -> int | None:
    if not isinstance(row, dict) or row.get("id") is None:
        return None
    try:
        return int(row["id"])
    except (TypeError, ValueError):
        return None


def sku_pode_publicar_agora(
    sku: str,
    *,
    condicoes: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Frente em ordem: MIMO → PERL (MIMO no ar) → JUPAES (1o pedido).
    Outro IMP-* fica fora até a ruptura.
    """
    sku_u = (sku or "").strip().upper()
    if not sku_u:
        return False, "sku_vazio"
    if not sku_u.startswith("IMP-"):
        return True, "fora_impala"
    cond = condicoes if isinstance(condicoes, dict) else avaliar_condicoes_guerra()
    checks = cond.get("checks") if isinstance(cond.get("checks"), dict) else {}
    if sku_u == "IMP-MIMO-003":
        if checks.get("mlb_mimo"):
            return False, "mimo_ja_no_ar"
        return True, "abrir_frente_mimo_carmed"
    if sku_u == "IMP-PERL-004":
        if not checks.get("mlb_mimo") or int(checks.get("estoque_mimo") or 0) <= 0:
            return False, "esperar_mimo_no_ar"
        if checks.get("mlb_perl"):
            return False, "perl_ja_no_ar"
        return True, "perl_mesmo_ciclo"
    if sku_u == "IMP-JUPAES-006":
        if int(checks.get("reviews") or 0) < 1:
            return False, "esperar_primeiro_pedido"
        if checks.get("mlb_jupaes"):
            return False, "jupaes_ja_no_ar"
        return True, "giro_apos_pedido"
    return False, "fora_frente_nao_abrir_4o_sku"


def canal_pode_entrar(
    marketplace: str,
    *,
    condicoes: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """ML é o referente. Shopee/Magalu/Amazon só depois da fase 3 (saúde ML)."""
    canal = str(marketplace or "").strip().lower()
    if canal not in CANAIS:
        return False, "canal_desconhecido"
    cond = (
        condicoes
        if isinstance(condicoes, dict) and condicoes.get("fase") is not None
        else avaliar_condicoes_guerra()
    )
    if canal == CANAL_REFERENTE:
        return sku_pode_publicar_agora("IMP-MIMO-003", condicoes=cond)
    d = carregar_doutrina()
    canais_cfg = d.get("canais") if isinstance(d.get("canais"), dict) else {}
    try:
        fase_min = int(canais_cfg.get("fase_minima_secundario") or 3)
    except (TypeError, ValueError):
        fase_min = 3
    fase = int(cond.get("fase") or 0)
    if fase < fase_min:
        return False, f"aguardar_ml_fase_{fase_min}"
    return True, "ml_referente_saudavel"


def avaliar_condicoes_guerra(
    *,
    produtos: list[dict[str, Any]] | None = None,
    radar: dict[str, Any] | None = None,
    resumo_conta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Melhor cenário possível com os dados atuais: fase 0–5 e o próximo gate.
    Não inventa MLB nem amostra viva.
    """
    from core.catalogo_produtos import carregar_produtos_catalogo

    d = carregar_doutrina()
    gat = d.get("gatilhos") or {}
    est_min = int(gat.get("estoque_ml_min") or 30)
    reviews_ads = int(gat.get("reviews_ads") or 20)
    nota_ads = _f(gat.get("nota_ads"), 4.8)
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    por = {
        str(p.get("sku") or "").strip().upper(): p
        for p in prods
        if isinstance(p, dict) and p.get("sku")
    }
    mimo = por.get("IMP-MIMO-003")
    perl = por.get("IMP-PERL-004")
    jupaes = por.get("IMP-JUPAES-006")
    titulo_mimo = str(
        ((mimo or {}).get("canais") or {}).get("mercadolivre", {}).get("titulo_anuncio")
        or (mimo or {}).get("nome")
        or ""
    ).lower()
    radar = radar if isinstance(radar, dict) else {}
    conta = resumo_conta if isinstance(resumo_conta, dict) else _carregar_resumo_conta()
    reviews, nota = _reviews_nota(conta if isinstance(conta, dict) else {})
    checks = {
        "mlb_mimo": _mlb_ok(mimo),
        "mlb_perl": _mlb_ok(perl),
        "mlb_jupaes": _mlb_ok(jupaes),
        "estoque_mimo": _estoque(mimo),
        "carmed_titulo": "carmed" in titulo_mimo and "mimo" in titulo_mimo,
        "titulo_pecas": pecas_titulo_mimo(titulo_mimo),
        "titulo_atracao": titulo_mimo_atracao_ok(titulo_mimo),
        "mercado_confiavel": bool(radar.get("mercado_confiavel")),
        "reviews": reviews,
        "nota": nota,
    }
    est_mimo = int(checks["estoque_mimo"])
    ads_ok = reviews >= reviews_ads and nota >= nota_ads
    if not checks["mlb_mimo"] or est_mimo <= 0:
        fase = 0
    elif not checks["mlb_perl"] or reviews < 1:
        fase = 1
    elif not checks["mlb_jupaes"] or not ads_ok:
        fase = 2
    elif not checks["mercado_confiavel"]:
        fase = 3
    elif est_mimo < est_min:
        fase = 4
    else:
        fase = 5
    fases = d.get("fases") or []
    atual = next((f for f in fases if _id_fase(f) == fase), {})
    proxima = next((f for f in fases if _id_fase(f) == fase + 1), {})
    return {
        "ok": True,
        "cenario": str(d.get("cenario_mais_possivel") or "abrir_frente_mimo_carmed"),
        "fase": fase,
        "fase_nome": str(atual.get("nome") or f"fase_{fase}"),
        "fazer": str(atual.get("fazer") or ""),
        "proximo": _proximo_gate(fase, checks, gat),
        "proxima_fase": str(proxima.get("nome") or ""),
        "agentes": list(atual.get("agentes") or []),
        "checks": checks,
        "estoque_min_guerra": est_min,
        "liberar": {
            "mimo": not bool(checks["mlb_mimo"]),
            "perl": bool(checks["mlb_mimo"] and est_mimo > 0 and not checks["mlb_perl"]),
            "jupaes": fase >= 2 and not bool(checks["mlb_jupaes"]),
            "ads": fase >= 3,
            "golpe_preco": fase >= 4,
            "ruptura": fase >= 5,
        },
        "nao_fazer": list(d.get("nao_fazer_global") or []),
    }


def calcular_opex_payback(doutrina: dict[str, Any] | None = None) -> dict[str, Any]:
    """R$ 800 operacional → meses/kits no ritmo da doutrina (não sobe preço)."""
    d = doutrina if isinstance(doutrina, dict) else carregar_doutrina()
    opex = d.get("opex") if isinstance(d.get("opex"), dict) else {}
    valor = _f(opex.get("valor_brl"), 800.0)
    lucro_mimo = _f(opex.get("lucro_mimo"), 10.83)
    lucro_perl = _f(opex.get("lucro_perl"), 6.49)
    ritmo_mimo = max(0, int(_f(opex.get("ritmo_mimo_mes"), 30)))
    ritmo_perl = max(0, int(_f(opex.get("ritmo_perl_mes"), 30)))
    lucro_mes = round(ritmo_mimo * lucro_mimo + ritmo_perl * lucro_perl, 2)
    meses_ritmo = round(valor / lucro_mes, 2) if lucro_mes > 0 else 0.0
    kits_mimo = int(math.ceil(valor / lucro_mimo)) if lucro_mimo > 0 else 0
    lucro_par = lucro_mimo + lucro_perl
    pares_mix = int(math.ceil(valor / lucro_par)) if lucro_par > 0 else 0
    return {
        "valor_brl": valor,
        "tipo": str(opex.get("tipo") or "unico"),
        "lucro_mimo": lucro_mimo,
        "lucro_perl": lucro_perl,
        "ritmo_mimo_mes": ritmo_mimo,
        "ritmo_perl_mes": ritmo_perl,
        "lucro_mes_ritmo": lucro_mes,
        "meses_payback_ritmo": meses_ritmo,
        "kits_payback_mimo": kits_mimo,
        "pares_payback_mix": pares_mix,
    }


def emitir_metricas_opex(payback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gauges robo.impala.opex.* — heartbeat do catálogo / decisão de guerra."""
    try:
        pb = payback if isinstance(payback, dict) and "valor_brl" in payback else calcular_opex_payback()
        gauge("impala.opex.valor", float(pb["valor_brl"]))
        gauge("impala.opex.lucro_kit", float(pb["lucro_mimo"]), tags=["kit:mimo003"])
        gauge("impala.opex.lucro_kit", float(pb["lucro_perl"]), tags=["kit:perl004"])
        gauge("impala.opex.lucro_mes_ritmo", float(pb["lucro_mes_ritmo"]))
        gauge("impala.opex.meses_payback_ritmo", float(pb["meses_payback_ritmo"]))
        gauge("impala.opex.kits_payback_mimo", float(pb["kits_payback_mimo"]))
        gauge("impala.opex.pares_payback_mix", float(pb["pares_payback_mix"]))
        gauge("impala.opex.ritmo_mimo_mes", float(pb["ritmo_mimo_mes"]))
        gauge("impala.opex.ritmo_perl_mes", float(pb["ritmo_perl_mes"]))
        return {"ok": True, **pb}
    except Exception as exc:
        logger.warning("emitir_metricas_opex: %s", exc)
        return {"ok": False, "erro": str(exc)}


_FRENTE_KIT_TAGS = (
    ("IMP-MIMO-003", "kit:mimo003"),
    ("IMP-PERL-004", "kit:perl004"),
    ("IMP-JUPAES-006", "kit:jupaes006"),
)


def emitir_metricas_condicoes(condicoes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Gauges de fase/liberar/publicar para o grupo Decisão guerra.

    O heartbeat do catálogo também chama isto: o radar sozinho não basta,
    porque métricas novas (fase, liberar_*) só entram no Datadog quando
    algum caminho que já roda com frequência as envia.
    """
    try:
        cond = (
            condicoes
            if isinstance(condicoes, dict) and condicoes.get("fase") is not None
            else avaliar_condicoes_guerra()
        )
        gauge("impala.guerra.fase", float(cond.get("fase") or 0))
        lib = cond.get("liberar") if isinstance(cond.get("liberar"), dict) else {}
        for chave in ("mimo", "perl", "jupaes", "ads", "golpe_preco", "ruptura"):
            gauge(f"impala.guerra.liberar_{chave}", 1.0 if lib.get(chave) else 0.0)
        n_pub = 0.0
        for sku, tag in _FRENTE_KIT_TAGS:
            ok, _motivo = sku_pode_publicar_agora(sku, condicoes=cond)
            if ok:
                n_pub += 1.0
            gauge("impala.guerra.publicar_sku", 1.0 if ok else 0.0, tags=[tag])
        gauge("impala.guerra.publicar_agora", n_pub)
        checks = cond.get("checks") if isinstance(cond.get("checks"), dict) else {}
        gauge(
            "impala.guerra.titulo_atracao",
            1.0 if checks.get("titulo_atracao") else 0.0,
        )
        gauge(
            "impala.guerra.carmed_titulo",
            1.0 if checks.get("carmed_titulo") else 0.0,
        )
        pecas = checks.get("titulo_pecas") if isinstance(checks.get("titulo_pecas"), dict) else {}
        for peca in _PECAS_TITULO_MIMO:
            gauge(
                "impala.guerra.titulo_peca",
                1.0 if pecas.get(peca) else 0.0,
                tags=[f"peca:{peca}"],
            )
        for canal in CANAIS:
            ok, _motivo = canal_pode_entrar(canal, condicoes=cond)
            gauge(
                "impala.guerra.canal_liberado",
                1.0 if ok else 0.0,
                tags=[f"marketplace:{canal}"],
            )
        try:
            from integracoes.meta.ciclo_campanhas import (
                avaliar_momento_ciclo_meta,
                emitir_metricas_ciclo_meta,
            )

            emitir_metricas_ciclo_meta(avaliar_momento_ciclo_meta(condicoes=cond))
        except Exception as exc:
            logger.warning("ciclo_campanhas_meta via doutrina: %s", exc)
        try:
            from integracoes.meta.claude_ciclo_meta import auxiliar_listing_mimo

            auxiliar_listing_mimo(cond)
        except Exception as exc:
            logger.warning("claude listing MIMO via doutrina: %s", exc)
        emitir_metricas_opex()
        return cond
    except Exception as exc:
        logger.warning("emitir_metricas_condicoes: %s", exc)
        return {"ok": False, "erro": str(exc)}
