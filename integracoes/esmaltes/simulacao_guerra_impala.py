"""
integracoes/esmaltes/simulacao_guerra_impala.py
Simula a frente Impala COM anúncios no ar — sem gravar MLB no catálogo real.

IDs MLB9000… são fictícios. Não publica, não altera produtos.json.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.catalogo_produtos import carregar_produtos_catalogo
from core.config import ROOT
from integracoes.esmaltes.decisao_batalha_agir import gerar_acoes_batalha
from integracoes.esmaltes.decisao_dia_esmaltes import avaliar_skus_guerra, carregar_skus_guerra
from integracoes.esmaltes.doutrina_guerra_impala import carregar_doutrina, piso_preco
from integracoes.esmaltes.golpe_guerra_impala import montar_golpe
from integracoes.esmaltes.metricas_batalha_impala import montar_batalha

logger = logging.getLogger("simulacao_guerra_impala")

FIXTURE_PATH = ROOT / "catalogo" / "simulacao_guerra_impala.json"
SNAPSHOT_PATH = ROOT / "logs" / "simulacao_guerra_impala_ultima.json"
ESTOQUE_IDEAL = 60
_FRENTE = ("IMP-MIMO-003", "IMP-PERL-004", "IMP-JUPAES-006")


def carregar_fixture() -> dict[str, Any]:
    data = ler_json(FIXTURE_PATH, default={})
    return data if isinstance(data, dict) else {}


def _filtrar_rivais(
    rivais: list[dict[str, Any]],
    *,
    nossos_mlb: dict[str, str],
    seller_id_nosso: str,
) -> list[dict[str, Any]]:
    """Amostra de rivais — nunca inclui os MLB simulados nem o nosso seller."""
    nossos = {str(v).strip().upper() for v in (nossos_mlb or {}).values() if str(v).strip()}
    seller = str(seller_id_nosso or "").strip()
    out: list[dict[str, Any]] = []
    for r in rivais or []:
        if not isinstance(r, dict):
            continue
        iid = str(r.get("item_id") or "").strip().upper()
        if iid in nossos:
            continue
        sid = str(r.get("seller_id") or "").strip()
        if seller and sid == seller:
            continue
        out.append(r)
    return out


def checklist_go_live(produtos: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """O que falta no catálogo real para a guerra ligar sem overlay."""
    from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
    from integracoes.esmaltes.decisao_dia_esmaltes import _item_id, _produto_por_sku

    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    out: list[dict[str, Any]] = []
    for sku in _FRENTE:
        p = _produto_por_sku(prods, sku)
        ml = ((p or {}).get("canais") or {}).get("mercadolivre") or {}
        iid = _item_id(p)
        est_cat = int((p or {}).get("estoque_total") or 0)
        est_ml = int(ml.get("estoque") or 0)
        out.append(
            {
                "sku": sku,
                "item_id": iid or "MLB_PREENCHER",
                "mlb_ok": _mlb_valido(iid),
                "estoque_catalogo": est_cat,
                "estoque_ml": est_ml,
                "estoque_ok": est_cat >= ESTOQUE_IDEAL and est_ml >= ESTOQUE_IDEAL,
                "preco": float(ml.get("preco") or (p or {}).get("preco") or 0),
            }
        )
    return out


def _qtd_kit_anuncio(anuncio: dict[str, Any]) -> int | None:
    try:
        q = int(anuncio.get("qtd_kit") or 0)
        return q if q >= 2 else None
    except (TypeError, ValueError):
        return None


def frente_tem_mlb_real(
    produtos: list[dict[str, Any]] | None = None,
    fixture: dict[str, Any] | None = None,
) -> bool:
    """True quando a frente já tem MLB verdadeiro (não MLB9000). Overlay desliga."""
    from integracoes.esmaltes.crescimento_esmaltes import _mlb_valido
    from integracoes.esmaltes.decisao_dia_esmaltes import _item_id, _produto_por_sku

    fx = fixture if isinstance(fixture, dict) else carregar_fixture()
    fake = {str(v).strip().upper() for v in (fx.get("nossos_mlb") or {}).values() if str(v).strip()}
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    for sku in _FRENTE:
        iid = _item_id(_produto_por_sku(prods, sku))
        if _mlb_valido(iid) and iid not in fake:
            return True
    return False


def aplicar_visao_operacional(
    anuncios_reais: list[dict[str, Any]] | None = None,
    *,
    produtos: list[dict[str, Any]] | None = None,
    cenario_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """
    Visão de tudo no ar: hidrata MIMO/PERL/JUPAES + completa rivais por tamanho.

    Não grava catálogo. Se já existe MLB real na frente, devolve os dados crus.
    """
    fx = carregar_fixture()
    prods = produtos if produtos is not None else carregar_produtos_catalogo()
    reais = [a for a in (anuncios_reais or []) if isinstance(a, dict)]
    if frente_tem_mlb_real(prods, fx):
        return prods, reais, False
    cid = str(cenario_id or fx.get("cenario_operacional") or "igual_para_igual").strip().lower()
    cenario = next(
        (c for c in (fx.get("cenarios") or []) if str(c.get("id") or "").lower() == cid),
        None,
    )
    if not isinstance(cenario, dict):
        return prods, reais, False
    hidratados = hidratar_produtos_simulados(
        prods,
        nossos_mlb=fx.get("nossos_mlb") or {},
        estoque=int(fx.get("estoque_ideal") or ESTOQUE_IDEAL),
    )
    rivais_fx = _filtrar_rivais(
        [r for r in (cenario.get("rivais") or []) if isinstance(r, dict)],
        nossos_mlb=fx.get("nossos_mlb") or {},
        seller_id_nosso=str(fx.get("seller_id_nosso") or ""),
    )
    tamanhos = {t for a in reais if (t := _qtd_kit_anuncio(a))}
    merged = list(reais)
    for r in rivais_fx:
        t = _qtd_kit_anuncio(r)
        if t is None:
            continue
        if t not in tamanhos:
            merged.append(r)
            tamanhos.add(t)
    return hidratados, merged, True


def sala_operacao(cenario: dict[str, Any] | None) -> dict[str, Any]:
    """Sala de guerra como se a frente já estivesse vendendo."""
    c = cenario if isinstance(cenario, dict) else {}
    g = c.get("golpe") if isinstance(c.get("golpe"), dict) else {}
    status = {str(s.get("sku")): s for s in (c.get("guerra_status") or []) if isinstance(s, dict)}
    frente_ok = all(
        (status.get(sku) or {}).get("mlb_ok") and "estoque_zero" not in ((status.get(sku) or {}).get("bloqueios") or [])
        for sku in _FRENTE
        if status
    ) or bool(c.get("hidratar_nossos"))
    return {
        "modo": "operacional",
        "frente_no_ar": frente_ok,
        "chat_30min": "on",
        "radar_rivais": int(c.get("rivais") or 0),
        "estoque_un": ESTOQUE_IDEAL,
        "ruptura_piso_un": 30,
        "repricing": "perl_apenas",
        "ads": "aguardando_20_avaliacoes_nota_4_8",
        "cnpj_2": "aguardando_20_avaliacoes",
        "golpe": g.get("classificacao"),
        "sku": g.get("sku"),
        "arma": g.get("arma"),
        "fazer": g.get("fazer"),
        "nao_fazer": g.get("nao_fazer"),
    }


def hidratar_produtos_simulados(
    produtos: list[dict[str, Any]],
    *,
    nossos_mlb: dict[str, str],
    estoque: int = ESTOQUE_IDEAL,
) -> list[dict[str, Any]]:
    """Cópia em memória: MLB simulado + estoque. Não persiste."""
    mapa = {str(k).upper(): str(v) for k, v in (nossos_mlb or {}).items()}
    out: list[dict[str, Any]] = []
    for p in produtos or []:
        if not isinstance(p, dict):
            out.append(p)
            continue
        sku = str(p.get("sku") or "").strip().upper()
        if sku not in mapa:
            out.append(p)
            continue
        q = copy.deepcopy(p)
        q["estoque_total"] = int(estoque)
        ml = q.setdefault("canais", {}).setdefault("mercadolivre", {})
        if not isinstance(ml, dict):
            ml = {}
            q["canais"]["mercadolivre"] = ml
        ml["item_id"] = mapa[sku]
        ml["estoque"] = int(estoque)
        ml["ativo"] = True
        q["_simulacao"] = True
        out.append(q)
    return out


def _resumo_frente(golpes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sku": g.get("sku"),
            "classificacao": g.get("classificacao"),
            "arma": g.get("arma"),
            "disparar": g.get("disparar"),
            "fazer": g.get("fazer"),
            "nao_fazer": g.get("nao_fazer"),
            "gap_pct": g.get("gap_pct"),
            "rival_min": g.get("rival_min"),
            "piso_preco": g.get("piso_preco"),
            "nosso_preco": g.get("nosso_preco"),
            "mlb_ok": g.get("mlb_ok"),
        }
        for g in golpes
        if isinstance(g, dict)
    ]


def rodar_cenario(
    cenario: dict[str, Any],
    *,
    fixture: dict[str, Any] | None = None,
    produtos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fx = fixture if isinstance(fixture, dict) else carregar_fixture()
    base = produtos if produtos is not None else carregar_produtos_catalogo()
    hidratar = bool(cenario.get("hidratar_nossos"))
    if hidratar:
        base = hidratar_produtos_simulados(
            base,
            nossos_mlb=fx.get("nossos_mlb") or {},
            estoque=int(fx.get("estoque_ideal") or ESTOQUE_IDEAL),
        )
    rivais = _filtrar_rivais(
        [r for r in (cenario.get("rivais") or []) if isinstance(r, dict)],
        nossos_mlb=fx.get("nossos_mlb") or {},
        seller_id_nosso=str(fx.get("seller_id_nosso") or ""),
    )
    guerra = carregar_skus_guerra()
    doutrina = carregar_doutrina()
    batalha = montar_batalha(anuncios_impala=rivais, produtos=base, guerra=guerra)
    golpe = montar_golpe(batalha, produtos=base, doutrina=doutrina)
    agir = gerar_acoes_batalha(batalha, limite=5)
    status = avaliar_skus_guerra(guerra=guerra, produtos=base, margem_piso_pct=15.0)
    pisos = {
        sku: piso_preco(next((p for p in base if str(p.get("sku") or "").upper() == sku), None), doutrina)
        for sku in _FRENTE
    }
    top = golpe.get("golpe") if isinstance(golpe.get("golpe"), dict) else {}
    out = {
        "id": cenario.get("id"),
        "nome": cenario.get("nome"),
        "hidratar_nossos": hidratar,
        "rivais": len(rivais),
        "pisos_fase1": pisos,
        "batalha": {
            "anuncios_unicos": batalha.get("anuncios_unicos"),
            "sellers_unicos": batalha.get("sellers_unicos"),
            "nossos_acima_rival": batalha.get("nossos_acima_rival"),
            "comparacoes_ao_vivo": batalha.get("comparacoes_ao_vivo"),
        },
        "golpe": {
            "disparar": golpe.get("disparar"),
            "classificacao": top.get("classificacao"),
            "sku": top.get("sku"),
            "arma": top.get("arma"),
            "fazer": top.get("fazer"),
            "nao_fazer": top.get("nao_fazer"),
        },
        "frente": _resumo_frente(golpe.get("golpes") or []),
        "agir_top": (agir.get("top") or [])[:5],
        "guerra_status": [
            {
                "sku": s.get("sku"),
                "mlb_ok": s.get("mlb_ok"),
                "pode_impulsionar": s.get("pode_impulsionar"),
                "bloqueios": s.get("bloqueios"),
            }
            for s in status
            if isinstance(s, dict)
        ],
    }
    out["sala"] = sala_operacao(out)
    return out


def rodar_simulacao(*, cenario_id: str | None = None, todos: bool = False) -> dict[str, Any]:
    """Roda a visão operacional (igual para igual) ou um/todos os cenários. Nunca grava produtos.json."""
    try:
        fx = carregar_fixture()
        produtos = carregar_produtos_catalogo()
        lista = [c for c in (fx.get("cenarios") or []) if isinstance(c, dict)]
        if cenario_id:
            alvo = str(cenario_id).strip().lower()
            lista = [c for c in lista if str(c.get("id") or "").lower() == alvo]
        elif not todos:
            padrao = str(fx.get("cenario_operacional") or "igual_para_igual").strip().lower()
            lista = [c for c in lista if str(c.get("id") or "").lower() == padrao]
        resultados = [rodar_cenario(c, fixture=fx, produtos=produtos) for c in lista]
        top = resultados[0] if resultados else {}
        payload = {
            "ok": True,
            "simulacao": True,
            "visao_operacional": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "aviso": "Visão operacional: frente no ar em memória. Catálogo em disco continua sem MLB real.",
            "quando_mlb_real": fx.get("quando_mlb_real") or [],
            "nossos_mlb_simulados": fx.get("nossos_mlb") or {},
            "estoque_ideal": int(fx.get("estoque_ideal") or ESTOQUE_IDEAL),
            "catalogo_real": checklist_go_live(produtos),
            "sala": (top.get("sala") if isinstance(top, dict) else None) or {},
            "cenarios": resultados,
        }
        try:
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        except Exception as exc:
            logger.warning("snapshot simulacao: %s", exc)
        return payload
    except Exception as exc:
        logger.warning("rodar_simulacao: %s", exc)
        return {"ok": False, "erro": str(exc), "simulacao": True, "cenarios": []}


def formatar_mensagem(payload: dict[str, Any]) -> str:
    from core.telegram_explicacao import cabecalho_agente

    sala = payload.get("sala") if isinstance(payload.get("sala"), dict) else {}
    if not sala:
        for c in payload.get("cenarios") or []:
            if isinstance(c, dict) and isinstance(c.get("sala"), dict):
                sala = c["sala"]
                break
    linhas = [
        cabecalho_agente("simulacao_guerra_impala", "*IMPALA ON* — sala de guerra operacional"),
        "_Chat 30 min, radar, golpe e estoque 60. Overlay em memoria; nao grava MLB no catalogo._",
        "",
        f"*FAZER:* {sala.get('fazer') or 'Diferenciar MIMO (listing)'}",
        f"*NAO FAZER:* {sala.get('nao_fazer') or 'Cortar preco; Ads; 2o CNPJ'}",
        f"Golpe: `{sala.get('sku') or 'IMP-MIMO-003'}` -> *{sala.get('golpe') or 'diferenciar'}* (arma {sala.get('arma') or 'listing'})",
        f"Radar: {sala.get('radar_rivais') or 0} rivais · estoque {sala.get('estoque_un') or 60} · Ads {sala.get('ads') or 'aguardando'}",
        "",
    ]
    for c in payload.get("cenarios") or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("id") or "") in ("hoje",) and len(payload.get("cenarios") or []) > 1:
            continue
        for frow in c.get("frente") or []:
            if not isinstance(frow, dict):
                continue
            gap = frow.get("gap_pct")
            gap_txt = f"{gap:.1f}%" if isinstance(gap, (int, float)) else "—"
            linhas.append(
                f"  `{frow.get('sku')}` {frow.get('classificacao')} "
                f"gap {gap_txt} rival R$ {frow.get('rival_min') or '—'}"
            )
        linhas.append("")
    linhas.append("_Quando publicar: gravar item_id real + estoque 60. O overlay desliga sozinho._")
    return "\n".join(linhas).strip()
