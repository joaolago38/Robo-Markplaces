"""
integracoes/esmaltes/novos_kits_impala.py
Detecta kits Impala recém-colocados no Mercado Livre.

Usa a amostra já varrida pelo monitor de concorrentes (não busca ML sozinho).
Compara MLB vistos + idade do anúncio/catálogo. Primeira rodada só grava
baseline (evita Telegram com dezenas de kits antigos).

Nunca lança.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from integracoes.esmaltes.analise_anita import detectar_marca, extrair_qtd_kit
from integracoes.ml.analise_anuncio_concorrente import dias_desde

logger = logging.getLogger("novos_kits_impala")

SNAPSHOT_PATH = ROOT / "logs" / "novos_kits_impala_ultima.json"
VISTOS_PATH = ROOT / "logs" / "novos_kits_impala_vistos.json"
TAG_ALERTA = "[novos-kits-impala]"
_IDS_MAX = 2500
_ITEM_ID_LIXO = re.compile(r"^MLB\d{1,2}$", re.I)

_COLECOES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mimo", re.compile(r"mimo|carmed", re.I)),
    ("perolado", re.compile(r"perol|p[eé]rola|sonho|polar|\blua\b|dengo", re.I)),
    ("ju_paes", re.compile(r"ju\s*paes|jupaes|virando", re.I)),
    ("bailarina", re.compile(r"bailarina", re.I)),
    ("francesinha", re.compile(r"francesinha", re.I)),
    ("tratamento", re.compile(r"tratamento|incolor|base\s*verniz|endurecedor", re.I)),
)

# Frente de guerra + kits Impala já cadastrados (mesmo os desligados).
_ASSINATURAS_CONHECIDAS = frozenset(
    {
        "3:mimo",
        "4:perolado",
        "6:ju_paes",
        "5:bailarina",
        "3:francesinha",
        "3:tratamento",
        "10:outro",
        "15:outro",
        "30:outro",
    }
)


def _cfg_ativo() -> bool:
    from core.config import NOVOS_KITS_IMPALA_ATIVO

    return bool(NOVOS_KITS_IMPALA_ATIVO)


def _cfg_dias() -> int:
    from core.config import NOVOS_KITS_IMPALA_DIAS

    return max(1, int(NOVOS_KITS_IMPALA_DIAS))


def _cfg_alerta() -> bool:
    from core.config import NOVOS_KITS_IMPALA_ALERTA

    return bool(NOVOS_KITS_IMPALA_ALERTA)


def _cfg_top_n() -> int:
    from core.config import NOVOS_KITS_IMPALA_TOP_N

    return max(1, int(NOVOS_KITS_IMPALA_TOP_N))


def _item_id_ok(item_id: str) -> bool:
    iid = (item_id or "").strip().upper().replace("-", "")
    if not iid.startswith("MLB") or "PREENCHER" in iid:
        return False
    return _ITEM_ID_LIXO.fullmatch(iid) is None


def _fmt_brl(valor: Any) -> str:
    try:
        v = float(valor or 0)
    except (TypeError, ValueError):
        return "n/d"
    if v <= 0:
        return "n/d"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def colecao_kit(titulo: str) -> str:
    t = str(titulo or "")
    for nome, rx in _COLECOES:
        if rx.search(t):
            return nome
    return "outro"


def qtd_kit(anuncio: dict[str, Any]) -> int | None:
    try:
        q = int(anuncio.get("qtd_kit") or 0)
        if 2 <= q <= 50:
            return q
    except (TypeError, ValueError):
        pass
    return extrair_qtd_kit(str(anuncio.get("titulo") or ""))


def assinatura_kit(anuncio: dict[str, Any]) -> str:
    q = qtd_kit(anuncio)
    col = colecao_kit(str(anuncio.get("titulo") or ""))
    return f"{q or '?'}:{col}"


def eh_kit_impala(anuncio: dict[str, Any]) -> bool:
    if not isinstance(anuncio, dict):
        return False
    titulo = str(anuncio.get("titulo") or "")
    if detectar_marca(titulo).lower() != "impala":
        return False
    norm = titulo.lower()
    if "kit" not in norm and qtd_kit(anuncio) is None:
        return False
    return _item_id_ok(str(anuncio.get("item_id") or anuncio.get("id") or ""))


def idade_dias(anuncio: dict[str, Any]) -> int | None:
    met = anuncio.get("metricas") if isinstance(anuncio.get("metricas"), dict) else {}
    for chave in ("dias_anuncio", "dias_catalogo"):
        try:
            d = met.get(chave)
            if d is not None:
                return max(0, int(d))
        except (TypeError, ValueError):
            pass
    for chave in ("date_created", "catalog_date_created", "anuncio_criado", "catalogo_criado"):
        d = dias_desde(str(anuncio.get(chave) or met.get(chave) or "") or None)
        if d is not None:
            return d
    return None


def _permalink(anuncio: dict[str, Any], item_id: str) -> str:
    link = str(anuncio.get("permalink") or anuncio.get("url") or "").strip()
    if link.startswith("http"):
        return link
    mlb = item_id.upper().replace("-", "")
    if mlb.startswith("MLB") and len(mlb) > 6:
        return f"https://produto.mercadolivre.com.br/{mlb[:3]}-{mlb[3:]}"
    return ""


def filtrar_kits_impala(anuncios: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    vistos: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in anuncios or []:
        if not eh_kit_impala(a):
            continue
        iid = str(a.get("item_id") or a.get("id") or "").strip().upper().replace("-", "")
        if iid in vistos:
            continue
        vistos.add(iid)
        out.append(a)
    return out


def _carregar_vistos() -> dict[str, Any]:
    data = ler_json(VISTOS_PATH, default={})
    if not isinstance(data, dict):
        return {"ids": [], "assinaturas": []}
    ids = [str(x).upper() for x in (data.get("ids") or []) if str(x).strip()]
    ass = [str(x) for x in (data.get("assinaturas") or []) if str(x).strip()]
    return {"ids": ids, "assinaturas": ass}


def _salvar_vistos(ids: list[str], assinaturas: list[str]) -> None:
    escrever_json_atomico(
        VISTOS_PATH,
        {
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "ids": ids[-_IDS_MAX:],
            "assinaturas": sorted(set(assinaturas))[:400],
        },
    )


def _classificar(
    anuncio: dict[str, Any],
    *,
    ids_vistos: set[str],
    baseline: bool,
    dias_limite: int,
) -> dict[str, Any] | None:
    iid = str(anuncio.get("item_id") or anuncio.get("id") or "").strip().upper().replace("-", "")
    titulo = str(anuncio.get("titulo") or "").strip()
    dias = idade_dias(anuncio)
    ass = assinatura_kit(anuncio)
    recente = dias is not None and dias <= dias_limite
    mlb_novo = iid not in ids_vistos
    fora_frente = ass not in _ASSINATURAS_CONHECIDAS

    if baseline:
        if not recente:
            return None
        motivos = ["recente"]
    else:
        motivos = []
        if mlb_novo:
            motivos.append("anuncio_novo")
        if recente:
            motivos.append("recente")
        if not motivos:
            return None

    if fora_frente:
        motivos.append("fora_frente")

    preco = anuncio.get("preco")
    if preco is None:
        met = anuncio.get("metricas") if isinstance(anuncio.get("metricas"), dict) else {}
        preco = met.get("preco")

    return {
        "item_id": iid,
        "titulo": titulo[:90],
        "preco": preco,
        "qtd_kit": qtd_kit(anuncio),
        "colecao": colecao_kit(titulo),
        "assinatura": ass,
        "dias": dias,
        "motivos": motivos,
        "fora_frente": fora_frente,
        "permalink": _permalink(anuncio, iid),
        "hash": iid,
    }


def formatar_alerta(row: dict[str, Any]) -> str:
    titulo = str(row.get("titulo") or "?")[:70]
    preco = _fmt_brl(row.get("preco"))
    iid = str(row.get("item_id") or "")
    dias = row.get("dias")
    idade = f"{dias}d no ar" if dias is not None else "idade n/d"
    qtd = row.get("qtd_kit")
    tam = f"kit {qtd}" if qtd else "kit"
    col = str(row.get("colecao") or "outro")
    extra = " · fora da frente" if row.get("fora_frente") else ""
    link = str(row.get("permalink") or "").strip()
    sufixo = f" {link}" if link else ""
    return (
        f"{TAG_ALERTA} {tam} {col} — {titulo} | {preco} "
        f"(`{iid}`, {idade}){extra}{sufixo}"
    )


def montar_novos(
    anuncios: list[dict[str, Any]] | None,
    *,
    vistos: dict[str, Any] | None = None,
    dias_limite: int | None = None,
) -> dict[str, Any]:
    """Puro: classifica a amostra contra o conjunto já visto. Não grava disco."""
    kits = filtrar_kits_impala(anuncios)
    estado = vistos if isinstance(vistos, dict) else {"ids": [], "assinaturas": []}
    ids_lista = [str(x).upper() for x in (estado.get("ids") or []) if str(x).strip()]
    ids_vistos = set(ids_lista)
    baseline = len(ids_vistos) == 0
    limite = dias_limite if dias_limite is not None else _cfg_dias()

    novos: list[dict[str, Any]] = []
    ids_agora: list[str] = []
    assinaturas_agora: list[str] = []
    for a in kits:
        iid = str(a.get("item_id") or a.get("id") or "").strip().upper().replace("-", "")
        ids_agora.append(iid)
        assinaturas_agora.append(assinatura_kit(a))
        row = _classificar(a, ids_vistos=ids_vistos, baseline=baseline, dias_limite=limite)
        if row:
            novos.append(row)

    def _chave(r: dict[str, Any]) -> tuple[int, int, float]:
        recente = 0 if "recente" in (r.get("motivos") or []) else 1
        dias = r.get("dias")
        dias_i = int(dias) if isinstance(dias, int) else 9999
        try:
            preco = float(r.get("preco") or 0)
        except (TypeError, ValueError):
            preco = 0.0
        return (recente, dias_i, preco)

    novos.sort(key=_chave)
    ids_unidos = list(dict.fromkeys(ids_lista + ids_agora))
    return {
        "ok": True,
        "baseline": baseline,
        "n_kits_impala": len(kits),
        "n_novos": len(novos),
        "n_recentes": sum(1 for r in novos if "recente" in (r.get("motivos") or [])),
        "n_fora_frente": sum(1 for r in novos if r.get("fora_frente")),
        "novos": novos,
        "ids_unidos": ids_unidos,
        "assinaturas_unidas": sorted(set((estado.get("assinaturas") or []) + assinaturas_agora)),
        "dias_limite": limite,
    }


def emitir_metricas(payload: dict[str, Any] | None) -> None:
    data = payload if isinstance(payload, dict) else {}
    gauge("impala.novos_kits.amostra", float(data.get("n_kits_impala") or 0))
    gauge("impala.novos_kits.n", float(data.get("n_novos") or 0))
    gauge("impala.novos_kits.recentes", float(data.get("n_recentes") or 0))
    gauge("impala.novos_kits.fora_frente", float(data.get("n_fora_frente") or 0))
    gauge("impala.novos_kits.baseline", 1.0 if data.get("baseline") else 0.0)


def processar(
    anuncios: list[dict[str, Any]] | None,
    *,
    persistir: bool = True,
    enviar_alerta: bool = True,
) -> dict[str, Any]:
    """Classifica, persiste vistos/snapshot e devolve linhas de Telegram. Nunca lança."""
    try:
        if not _cfg_ativo():
            return {"ok": True, "desligado": True, "alertas": [], "n_novos": 0}
        estado = _carregar_vistos() if persistir else {"ids": [], "assinaturas": []}
        out = montar_novos(anuncios, vistos=estado)
        top = out.get("novos") or []
        top_n = top[: _cfg_top_n()]
        alertas: list[str] = []
        if enviar_alerta and _cfg_alerta() and top_n:
            alertas = [formatar_alerta(r) for r in top_n]

        payload = {
            **out,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alertas": alertas,
            "novos": top_n,
        }
        if persistir:
            _salvar_vistos(out.get("ids_unidos") or [], out.get("assinaturas_unidas") or [])
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        emitir_metricas(payload)
        incrementar("impala.novos_kits.ok")
        if alertas:
            incrementar("impala.novos_kits.alertas", float(len(alertas)))
        return payload
    except Exception as exc:
        logger.warning("novos_kits_impala: %s", exc)
        incrementar("impala.novos_kits.erro")
        return {"ok": False, "erro": str(exc), "alertas": [], "n_novos": 0}
