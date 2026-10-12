"""
integracoes/empresa/ponto_ruptura_segundo_cnpj.py
Cruza saúde do CNPJ Impala (fase 2) com preparação CNAE/seller do Masterprint.

Vereditos:
  ainda_nao    — Impala não passou na checklist
  aproximando  — anúncio foco no ar E (≥10 reviews da conta OU MLB+estoque+maioria)
  liberado     — todos os checks de ruptura ok → segundo CNPJ pode entrar em ação
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import ler_json
from core.config import (
    ACOS_MAXIMO,
    AVALIACOES_PARA_ADS,
    NOTA_MINIMA_PARA_ADS,
    PONTO_RUPTURA_ESTOQUE_MIN,
    ROOT,
)
from core.empresa.cnpj_utils import formatar_cnpj, norm_cnae

logger = logging.getLogger("ponto_ruptura_segundo_cnpj")

# Kits de validação com margem real ≥ piso (~15%). SORT-006 (~8%) fica para fase 2.
KITS_VALIDACAO = ("IMP-MIMO-003", "IMP-PERL-004")
CNAE_IMPALA_COSMETICO = "4772500"  # 4772-5/00
CNAES_MASTERPRINT = {
    "informatica": "4751201",  # 4751-2/01
    "resinas": "4689302",  # 4689-3/02 — filamento
    "papelaria": "4761003",  # 4761-0/03 — apagador
}

SNAPSHOT_MARGEM = ROOT / "logs" / "margem_vendas_ultima.json"
SNAPSHOT_ADS = ROOT / "logs" / "ads_gatilho_ultima.json"
SNAPSHOT_RESUMO = ROOT / "logs" / "resumo_conta_ml_ultima.json"


def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def mlb_preenchido(item_id: Any) -> bool:
    s = str(item_id or "").strip().upper()
    return bool(s) and s != "MLB_PREENCHER" and s.startswith("MLB")


_CORES_RUINS = frozenset({"laranja", "vermelho", "2_orange", "1_red"})


def _estoque_produto(produto: dict[str, Any]) -> int:
    """Estoque do anúncio ML quando há MLB; catálogo não mascara ML=0."""
    canais = produto.get("canais") if isinstance(produto.get("canais"), dict) else {}
    ml = canais.get("mercadolivre") if isinstance(canais.get("mercadolivre"), dict) else {}
    mlb = str(ml.get("item_id") or produto.get("item_id") or "")
    if mlb_preenchido(mlb):
        return _i(ml.get("estoque"))
    return _i(produto.get("estoque_total"))


def _saude_conta_ok(
    *,
    cor: str,
    atraso_rate: float,
    cancelamentos_rate: float,
    claims_rate: float,
) -> tuple[bool, str]:
    """Cor laranja/vermelha ou taxa ≥5% bloqueia. Sem cor / taxa 0 passa."""
    cor_l = str(cor or "").strip().lower()
    if any(tok in cor_l for tok in _CORES_RUINS) or cor_l in _CORES_RUINS:
        return False, cor or "cor ruim"
    if atraso_rate >= 0.05:
        return False, f"atraso {atraso_rate:.1%}"
    if cancelamentos_rate >= 0.05:
        return False, f"cancel {cancelamentos_rate:.1%}"
    if claims_rate >= 0.05:
        return False, f"claims_rate {claims_rate:.1%}"
    return True, cor or "sem cor"


def _mlb_produto(produto: dict[str, Any]) -> str:
    canais = produto.get("canais") if isinstance(produto.get("canais"), dict) else {}
    ml = canais.get("mercadolivre") if isinstance(canais.get("mercadolivre"), dict) else {}
    return str(ml.get("item_id") or produto.get("item_id") or "")


def _cnaes_empresa(emp: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for c in (emp or {}).get("cnaes") or []:
        if isinstance(c, dict):
            n = norm_cnae(str(c.get("codigo") or c.get("codigo_norm") or ""))
        else:
            n = norm_cnae(str(c))
        if n:
            out.add(n)
    return out


def _check(cid: str, ok: bool, rotulo: str, atual: Any, minimo: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "ok": bool(ok),
        "rotulo": rotulo,
        "atual": atual,
        "minimo": minimo,
    }


def coletar_sinais_impala(
    *,
    reputacao: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
    margem: dict[str, Any] | None = None,
    ads: dict[str, Any] | None = None,
    resumo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sinais do seller Impala. Aceita injeção para testes."""
    if reputacao is None:
        try:
            from integracoes.ml.ml_client import buscar_reputacao_vendedor

            reputacao = buscar_reputacao_vendedor() or {}
        except Exception as exc:
            logger.debug("reputacao live: %s", exc)
            reputacao = {}
    if not reputacao:
        resumo = resumo if resumo is not None else ler_json(SNAPSHOT_RESUMO, default={})
        reputacao = (resumo or {}).get("reputacao") if isinstance(resumo, dict) else {}
        reputacao = reputacao if isinstance(reputacao, dict) else {}

    metrics = reputacao.get("metrics") if isinstance(reputacao.get("metrics"), dict) else {}
    avaliacoes = _i(metrics.get("total_ratings"), _i(reputacao.get("vendas_completadas")))
    nota = _f(metrics.get("average_rating"))
    vendas_completadas = _i(
        (metrics.get("transactions") or {}).get("completed")
        if isinstance(metrics.get("transactions"), dict)
        else reputacao.get("vendas_completadas")
    )
    claims_rate = _f(
        (metrics.get("claims") or {}).get("rate")
        if isinstance(metrics.get("claims"), dict)
        else 0
    )

    if produtos is None:
        try:
            from core.catalogo_produtos import carregar_produtos_para_operacao

            produtos = carregar_produtos_para_operacao(merge_bling=False)
        except Exception as exc:
            logger.debug("catalogo: %s", exc)
            produtos = []
    por_sku = {
        str(p.get("sku") or "").upper(): p
        for p in (produtos or [])
        if isinstance(p, dict) and p.get("sku")
    }
    kits: list[dict[str, Any]] = []
    for sku in KITS_VALIDACAO:
        p = por_sku.get(sku) or {}
        mlb = _mlb_produto(p)
        kits.append(
            {
                "sku": sku,
                "mlb": mlb,
                "mlb_ok": mlb_preenchido(mlb),
                "estoque": _estoque_produto(p),
                "encontrado": bool(p),
            }
        )

    if margem is None:
        margem = ler_json(SNAPSHOT_MARGEM, default={})
    analise = (margem or {}).get("analise") if isinstance(margem, dict) else {}
    analise = analise if isinstance(analise, dict) else {}
    itens_margem = _i(analise.get("total_itens"))
    receita = _f(analise.get("receita_bruta"))

    if ads is None:
        ads = ler_json(SNAPSHOT_ADS, default={})
    ads = ads if isinstance(ads, dict) else {}
    acos = _f(ads.get("acos_atual"))
    decisao_ads = str(ads.get("decisao") or "").strip()
    ads_fonte_ok = bool(decisao_ads) or "acos_atual" in ads

    if resumo is None:
        resumo = ler_json(SNAPSHOT_RESUMO, default={})
    resumo = resumo if isinstance(resumo, dict) else {}
    claims = _i(resumo.get("pos_venda_claims"))
    claims_fonte_ok = bool(resumo.get("pos_venda_ok"))
    anuncios_ativos_foco = _i(resumo.get("anuncios_ativos"))
    rep_resumo = resumo.get("reputacao") if isinstance(resumo.get("reputacao"), dict) else {}
    delayed = (
        metrics.get("delayed_handling_time")
        if isinstance(metrics.get("delayed_handling_time"), dict)
        else {}
    )
    cancel = (
        metrics.get("cancellations") if isinstance(metrics.get("cancellations"), dict) else {}
    )
    atraso_rate = _f(delayed.get("rate"), _f(rep_resumo.get("atraso_rate")))
    cancelamentos_rate = _f(cancel.get("rate"), _f(rep_resumo.get("cancelamentos_rate")))
    if claims_rate <= 0:
        claims_rate = _f(rep_resumo.get("claims_rate"))
    cor = str(reputacao.get("cor") or rep_resumo.get("cor") or reputacao.get("level_id") or "")

    return {
        "avaliacoes": avaliacoes,
        "nota": nota,
        "vendas_completadas": vendas_completadas,
        "claims_rate": claims_rate,
        "claims": claims,
        "claims_fonte_ok": claims_fonte_ok,
        "anuncios_ativos_foco": anuncios_ativos_foco,
        "kits": kits,
        "itens_margem": itens_margem,
        "receita_bruta": receita,
        "acos": acos,
        "decisao_ads": decisao_ads,
        "ads_fonte_ok": ads_fonte_ok,
        "reputacao_cor": cor,
        "atraso_rate": atraso_rate,
        "cancelamentos_rate": cancelamentos_rate,
    }


def coletar_preparacao_cnae(
    *,
    esmaltes: dict[str, Any] | None = None,
    masterprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gaps de CNAE/seller para o segundo CNPJ entrar depois da ruptura."""
    try:
        from core.empresa.catalogo import empresa_por_id
        from core.empresa.overrides import aplicar_overrides_env

        if esmaltes is None:
            esmaltes = aplicar_overrides_env(empresa_por_id("esmaltes_impala") or {})
        if masterprint is None:
            masterprint = aplicar_overrides_env(empresa_por_id("masterprint") or {})
    except Exception as exc:
        logger.debug("empresas: %s", exc)
        esmaltes = esmaltes or {}
        masterprint = masterprint or {}

    cnaes_i = _cnaes_empresa(esmaltes)
    cnaes_m = _cnaes_empresa(masterprint)
    seller_mp = str((masterprint.get("ml") or {}).get("seller_id") or "").strip()
    seller_imp = str((esmaltes.get("ml") or {}).get("seller_id") or "").strip()

    ambiguo = bool(seller_mp and seller_imp and seller_mp == seller_imp)

    itens = [
        _check(
            "impala_cnae_cosmetico",
            CNAE_IMPALA_COSMETICO in cnaes_i,
            "Impala CNAE 4772-5/00 (cosmético)",
            ",".join(sorted(cnaes_i)) or "—",
            CNAE_IMPALA_COSMETICO,
        ),
        _check(
            "masterprint_cnae_informatica",
            CNAES_MASTERPRINT["informatica"] in cnaes_m,
            "Masterprint CNAE 4751-2/01 (informática / filamento)",
            ",".join(sorted(cnaes_m)) or "—",
            CNAES_MASTERPRINT["informatica"],
        ),
        _check(
            "masterprint_cnae_resinas",
            CNAES_MASTERPRINT["resinas"] in cnaes_m,
            "Masterprint CNAE 4689-3/02 (resinas / PETG)",
            ",".join(sorted(cnaes_m)) or "—",
            CNAES_MASTERPRINT["resinas"],
        ),
        _check(
            "masterprint_cnae_papelaria",
            CNAES_MASTERPRINT["papelaria"] in cnaes_m,
            "Masterprint CNAE 4761-0/03 (papelaria / apagador)",
            ",".join(sorted(cnaes_m)) or "—",
            CNAES_MASTERPRINT["papelaria"],
        ),
        _check(
            "masterprint_seller_ml",
            bool(seller_mp),
            "Seller ML do CNPJ 23.811.261/0001-97 (KYC)",
            seller_mp or "vazio",
            "preenchido",
        ),
        _check(
            "cnpjs_nao_ambiguos",
            not ambiguo,
            "Sellers Impala e Masterprint distintos",
            "mesmo seller" if ambiguo else "ok ou Masterprint ainda sem seller",
            "IDs diferentes",
        ),
    ]
    gaps = [c for c in itens if not c["ok"]]
    gaps_cnae = [
        c
        for c in gaps
        if "_cnae_" in str(c.get("id") or "") or str(c.get("id") or "").endswith("_cnae_cosmetico")
    ]
    gaps_kyc = [c for c in gaps if str(c.get("id") or "") == "masterprint_seller_ml"]
    return {
        "itens": itens,
        "gaps": gaps,
        "gaps_n": len(gaps),
        "gaps_cnae_n": len(gaps_cnae),
        "gaps_kyc_n": len(gaps_kyc),
        "pronto": len(gaps) == 0,
        "seller_masterprint": seller_mp,
        "cnpj_masterprint": formatar_cnpj(str(masterprint.get("cnpj") or "23811261000197")),
        "cnpj_impala": formatar_cnpj(str(esmaltes.get("cnpj") or "52668583000127")),
    }


def avaliar_ponto_ruptura(
    *,
    sinais: dict[str, Any] | None = None,
    cnae: dict[str, Any] | None = None,
    avaliacoes_min: int | None = None,
    nota_min: float | None = None,
    estoque_min: int | None = None,
    acos_max: float | None = None,
    aproximando_avaliacoes: int | None = None,
) -> dict[str, Any]:
    """Monta veredito + checklist. Nunca lança."""
    from core.config import PONTO_RUPTURA_APROXIMANDO_AVALIACOES

    av_min = int(avaliacoes_min if avaliacoes_min is not None else AVALIACOES_PARA_ADS)
    nt_min = float(nota_min if nota_min is not None else NOTA_MINIMA_PARA_ADS)
    est_min = int(estoque_min if estoque_min is not None else PONTO_RUPTURA_ESTOQUE_MIN)
    ac_max = float(acos_max if acos_max is not None else ACOS_MAXIMO)
    aprox_av = int(
        aproximando_avaliacoes
        if aproximando_avaliacoes is not None
        else PONTO_RUPTURA_APROXIMANDO_AVALIACOES
    )

    sinais = sinais if sinais is not None else coletar_sinais_impala()
    cnae = cnae if cnae is not None else coletar_preparacao_cnae()

    kits = list(sinais.get("kits") or [])
    mlb_ok = all(bool(k.get("mlb_ok")) for k in kits) and len(kits) == len(KITS_VALIDACAO)
    estoque_ok = all(_i(k.get("estoque")) >= est_min for k in kits) and len(kits) == len(
        KITS_VALIDACAO
    )
    avaliacoes = _i(sinais.get("avaliacoes"))
    nota = _f(sinais.get("nota"))
    ativos_foco = _i(sinais.get("anuncios_ativos_foco"))
    foco_ok = ativos_foco >= 1
    # Review/venda da conta só conta como Impala com anúncio foco no ar (senão é bolsa/legado).
    pedidos_ok = _i(sinais.get("itens_margem")) > 0 or (
        _i(sinais.get("vendas_completadas")) > 0 and foco_ok
    )
    acos = _f(sinais.get("acos"))
    if "ads_fonte_ok" in sinais:
        fonte_ads = bool(sinais.get("ads_fonte_ok"))
    else:
        fonte_ads = bool(str(sinais.get("decisao_ads") or "").strip())
    ads_ok = fonte_ads and acos <= ac_max
    claims = _i(sinais.get("claims"))
    fonte_claims = sinais.get("claims_fonte_ok")
    if fonte_claims is None:
        fonte_claims = True
    claims_ok = claims < 2 and bool(fonte_claims)
    nota_ok = foco_ok and avaliacoes > 0 and nota >= nt_min
    avaliacoes_ok = foco_ok and avaliacoes >= av_min
    saude_ok, saude_atual = _saude_conta_ok(
        cor=str(sinais.get("reputacao_cor") or ""),
        atraso_rate=_f(sinais.get("atraso_rate")),
        cancelamentos_rate=_f(sinais.get("cancelamentos_rate")),
        claims_rate=_f(sinais.get("claims_rate")),
    )

    checks = [
        _check(
            "avaliacoes",
            avaliacoes_ok,
            "Avaliações Impala (com anúncio foco)",
            avaliacoes if foco_ok else f"{avaliacoes} conta/legado",
            av_min,
        ),
        _check("nota", nota_ok, "Nota média (≥1 review no foco)", round(nota, 2), nt_min),
        _check(
            "mlb",
            mlb_ok,
            "MLB dos kits MIMO-003 e PERL-004 (margem ≥ piso)",
            ",".join(f"{k.get('sku')}={'ok' if k.get('mlb_ok') else 'falta'}" for k in kits),
            "ambos MLB",
        ),
        _check(
            "estoque",
            estoque_ok,
            f"Estoque >= {est_min} nos dois kits",
            ",".join(f"{k.get('sku')}={k.get('estoque')}" for k in kits),
            est_min,
        ),
        _check(
            "pedidos",
            pedidos_ok,
            "Pedido próprio (margem 24h Impala; venda da conta só com foco)",
            f"itens={sinais.get('itens_margem')} completadas={sinais.get('vendas_completadas')}",
            ">=1",
        ),
        _check(
            "ads_acos",
            ads_ok,
            "ACOS ≤ teto (snapshot Ads visível)",
            round(acos, 3) if fonte_ads else "n/d",
            ac_max,
        ),
        _check(
            "claims",
            claims_ok,
            "Claims baixos (API visível)",
            claims if fonte_claims else "n/d",
            "<2",
        ),
        _check(
            "anuncios_foco",
            foco_ok,
            "Há anúncio Impala (kit) ativo no ML",
            ativos_foco,
            ">=1",
        ),
        _check(
            "saude_conta",
            saude_ok,
            "Reputação sem laranja/vermelho e taxas <5%",
            saude_atual,
            "ok",
        ),
    ]
    ok_n = sum(1 for c in checks if c["ok"])
    total = len(checks)
    liberado = ok_n == total
    # Reviews da conta sem anúncio foco não são progresso Impala (bolsas/legado).
    aproximando = (not liberado) and foco_ok and (
        avaliacoes >= aprox_av
        or (ok_n >= 5 and mlb_ok and estoque_ok)
    )
    if liberado:
        veredito = "liberado"
    elif aproximando:
        veredito = "aproximando"
    else:
        veredito = "ainda_nao"

    progresso = round(100.0 * ok_n / max(1, total), 1)
    return {
        "ok": True,
        "veredito": veredito,
        "liberado": liberado,
        "aproximando": aproximando,
        "progresso_pct": progresso,
        "checks": checks,
        "checks_ok": ok_n,
        "checks_total": total,
        "sinais": sinais,
        "cnae_preparacao": cnae,
        "limites": {
            "avaliacoes_min": av_min,
            "nota_min": nt_min,
            "estoque_min": est_min,
            "acos_max": ac_max,
            "aproximando_avaliacoes": aprox_av,
        },
    }
