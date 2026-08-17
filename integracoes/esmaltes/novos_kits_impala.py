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


def _cfg_rank_n() -> int:
    from core.config import NOVOS_KITS_IMPALA_RANK_N

    return max(1, int(NOVOS_KITS_IMPALA_RANK_N))


def _cfg_rank_cooldown() -> int:
    from core.config import NOVOS_KITS_IMPALA_RANK_COOLDOWN_SEG

    return max(60, int(NOVOS_KITS_IMPALA_RANK_COOLDOWN_SEG))


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


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _i(val: Any, default: int = 0) -> int:
    try:
        if val is None:
            return default
        return int(float(val))
    except (TypeError, ValueError):
        return default


_COLECAO_NOME = {
    "mimo": "Mimo + Carmed",
    "perolado": "Perolado",
    "ju_paes": "Ju Paes",
    "bailarina": "Bailarina",
    "francesinha": "Francesinha",
    "tratamento": "Tratamento",
    "outro": "",
}


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


def nome_kit(anuncio: dict[str, Any]) -> str:
    """Nome curto do kit para Telegram (tamanho + coleção, senão o título)."""
    titulo = str(anuncio.get("titulo") or "").strip()
    q = qtd_kit(anuncio)
    col = colecao_kit(titulo)
    rotulo = _COLECAO_NOME.get(col) or ""
    if q and rotulo:
        return f"Kit {q} Impala {rotulo}"
    if q:
        return f"Kit {q} Impala"
    if rotulo:
        return f"Kit Impala {rotulo}"
    if titulo:
        return titulo[:55]
    return "Kit Impala"


def _campo(anuncio: dict[str, Any], *chaves: str) -> Any:
    met = anuncio.get("metricas") if isinstance(anuncio.get("metricas"), dict) else {}
    for chave in chaves:
        if anuncio.get(chave) is not None:
            return anuncio.get(chave)
        if met.get(chave) is not None:
            return met.get(chave)
    return None


def saude_anuncio(anuncio: dict[str, Any]) -> dict[str, Any]:
    """
    Saúde 0–100 do anúncio rival (estimativa).
    Reviews/visitas de rival no ML costumam vir vazios (403) — aí o score
    cai em vendas, preço e clareza do título.
    """
    vendas = max(0, _i(_campo(anuncio, "quantidade_vendida", "sold_quantity", "vendas")))
    vpd = _campo(anuncio, "vendas_por_dia")
    vpd_f = _f(vpd) if vpd is not None else 0.0
    nota = _campo(anuncio, "nota")
    nota_f = _f(nota) if nota is not None else 0.0
    aval = max(0, _i(_campo(anuncio, "avaliacoes")))
    vis7 = _campo(anuncio, "visitas_7d")
    vis7_i = max(0, _i(vis7)) if vis7 is not None else 0
    preco = _f(_campo(anuncio, "preco", "price"))
    frete = bool(anuncio.get("frete_gratis") or (anuncio.get("metricas") or {}).get("frete_gratis"))
    q = qtd_kit(anuncio)
    col = colecao_kit(str(anuncio.get("titulo") or ""))

    if vendas <= 0:
        pts_vendas = 0.0
    elif vendas < 10:
        pts_vendas = min(12.0, vendas * 1.2)
    else:
        pts_vendas = min(40.0, 12.0 + min(28.0, (vendas - 10) / 15.0))

    pts_vpd = min(15.0, vpd_f * 5.0) if vpd_f > 0 else 0.0
    pts_nota = min(20.0, (nota_f / 5.0) * 20.0) if nota_f > 0 else 0.0
    pts_aval = min(15.0, aval / 20.0 * 15.0) if aval > 0 else 0.0
    pts_vis = min(10.0, vis7_i / 80.0 * 10.0) if vis7_i > 0 else 0.0
    pts_base = (4.0 if preco > 0 else 0.0) + (3.0 if q else 0.0) + (3.0 if col != "outro" else 0.0)
    pts_frete = 5.0 if frete else 0.0
    score = round(
        min(100.0, pts_vendas + pts_vpd + pts_nota + pts_aval + pts_vis + pts_base + pts_frete),
        1,
    )
    if score >= 70:
        faixa = "boa"
        emoji = "🟢"
    elif score >= 40:
        faixa = "media"
        emoji = "🟡"
    elif score > 0:
        faixa = "fraca"
        emoji = "🔴"
    else:
        faixa = "sem_sinal"
        emoji = "⚪"
    return {
        "score": score,
        "faixa": faixa,
        "emoji": emoji,
        "vendas": vendas if vendas > 0 else None,
        "vendas_por_dia": round(vpd_f, 2) if vpd_f > 0 else None,
        "nota": round(nota_f, 1) if nota_f > 0 else None,
        "avaliacoes": aval if aval > 0 else None,
        "visitas_7d": vis7_i if vis7_i > 0 else None,
        "preco": preco if preco > 0 else None,
    }


def ficha_anuncio(anuncio: dict[str, Any]) -> dict[str, Any]:
    iid = str(anuncio.get("item_id") or anuncio.get("id") or "").strip().upper().replace("-", "")
    titulo = str(anuncio.get("titulo") or "").strip()
    saude = saude_anuncio(anuncio)
    return {
        "item_id": iid,
        "titulo": titulo[:90],
        "nome_kit": nome_kit(anuncio),
        "preco": saude.get("preco") or anuncio.get("preco"),
        "qtd_kit": qtd_kit(anuncio),
        "colecao": colecao_kit(titulo),
        "assinatura": assinatura_kit(anuncio),
        "dias": idade_dias(anuncio),
        "permalink": _permalink(anuncio, iid),
        "saude": saude["score"],
        "saude_faixa": saude["faixa"],
        "saude_emoji": saude["emoji"],
        "vendas": saude["vendas"],
        "vendas_por_dia": saude["vendas_por_dia"],
        "nota": saude["nota"],
        "avaliacoes": saude["avaliacoes"],
        "hash": iid,
    }


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

    row = ficha_anuncio(anuncio)
    row["motivos"] = motivos
    row["fora_frente"] = fora_frente
    return row


def _linha_anuncio(row: dict[str, Any], *, incluir_idade: bool = False) -> str:
    nome = str(row.get("nome_kit") or row.get("titulo") or "?")[:60]
    emoji = str(row.get("saude_emoji") or "")
    saude = row.get("saude")
    saude_txt = f"{emoji} {saude:.0f}/100" if isinstance(saude, (int, float)) else "saúde n/d"
    partes = [f"*{nome}*", saude_txt, _fmt_brl(row.get("preco"))]
    if row.get("vendas"):
        partes.append(f"{int(row['vendas'])} vend.")
    if row.get("nota"):
        aval = f" ({row['avaliacoes']})" if row.get("avaliacoes") else ""
        partes.append(f"★{row['nota']}{aval}")
    if incluir_idade:
        dias = row.get("dias")
        partes.append(f"{dias}d no ar" if dias is not None else "idade n/d")
    extra = " · fora da frente" if row.get("fora_frente") else ""
    iid = str(row.get("item_id") or "")
    link = str(row.get("permalink") or "").strip()
    sufixo = f" {link}" if link else ""
    return f"{' · '.join(partes)} (`{iid}`){extra}{sufixo}"


def formatar_alerta(row: dict[str, Any]) -> str:
    return f"{TAG_ALERTA} {_linha_anuncio(row, incluir_idade=True)}"


def montar_ranking(anuncios: list[dict[str, Any]] | None, *, limite: int | None = None) -> list[dict[str, Any]]:
    """Melhores anúncios Impala da amostra (saúde, depois vendas)."""
    top = limite if limite is not None else _cfg_rank_n()
    fichas = [ficha_anuncio(a) for a in filtrar_kits_impala(anuncios)]

    def _chave(r: dict[str, Any]) -> tuple[float, int]:
        try:
            score = float(r.get("saude") or 0)
        except (TypeError, ValueError):
            score = 0.0
        vend = int(r.get("vendas") or 0)
        return (score, vend)

    fichas.sort(key=_chave, reverse=True)
    return fichas[: max(1, top)]


def nomes_kits_a_venda(anuncios: list[dict[str, Any]] | None) -> list[str]:
    vistos: set[str] = set()
    out: list[str] = []
    for a in filtrar_kits_impala(anuncios):
        nome = nome_kit(a)
        chave = nome.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(nome)
    return out


def formatar_mensagem(
    *,
    novos: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
    nomes: list[str],
    n_amostra: int,
    baseline: bool = False,
) -> str:
    from core.telegram_explicacao import cabecalho_agente

    linhas = [
        cabecalho_agente("novos_kits_impala", "💅 *Kits Impala no Mercado Livre*"),
        "",
        f"_Amostra: *{n_amostra}* anúncio(s) Impala kit._",
    ]
    if nomes:
        linhas.append("*Kits à venda:* " + ", ".join(f"*{n}*" for n in nomes[:10]))
    linhas.append("")

    if novos:
        linhas.append(f"*Novos nesta rodada ({len(novos)})*")
        for i, row in enumerate(novos, 1):
            linhas.append(f"{i}. {_linha_anuncio(row, incluir_idade=True)}")
        linhas.append("")
    elif baseline:
        linhas.append("_Primeira rodada: base gravada, sem alerta de kit antigo._")
        linhas.append("")

    if ranking:
        linhas.append("*Ranking — melhores anúncios (saúde)*")
        for i, row in enumerate(ranking, 1):
            linhas.append(f"{i}. {_linha_anuncio(row)}")
        linhas.append("")
        linhas.append(
            "_Saúde 0–100: vendas, nota, avaliações e visitas quando a API devolver. "
            "Rival no ML costuma omitir review — aí o score usa vendas + título._"
        )
    return "\n".join(linhas).strip()


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
        return (recente, dias_i, -_f(r.get("saude")))

    novos.sort(key=_chave)
    ranking = montar_ranking(kits, limite=_cfg_rank_n())
    nomes = nomes_kits_a_venda(kits)
    ids_unidos = list(dict.fromkeys(ids_lista + ids_agora))
    return {
        "ok": True,
        "baseline": baseline,
        "n_kits_impala": len(kits),
        "n_novos": len(novos),
        "n_recentes": sum(1 for r in novos if "recente" in (r.get("motivos") or [])),
        "n_fora_frente": sum(1 for r in novos if r.get("fora_frente")),
        "novos": novos,
        "ranking": ranking,
        "nomes_kits": nomes,
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
    ranking = data.get("ranking") or []
    if ranking:
        top = ranking[0] if isinstance(ranking[0], dict) else {}
        gauge("impala.novos_kits.rank_saude_top", float(top.get("saude") or 0))
    gauge("impala.novos_kits.rank_n", float(len(ranking)))
    gauge("impala.novos_kits.nomes_n", float(len(data.get("nomes_kits") or [])))


def _enviar_telegram(payload: dict[str, Any]) -> tuple[bool, str]:
    from core.notificador import (
        alertar_gestor,
        chave_itens_novos,
        chave_resumo_periodo,
        gestor_telegram_configurado,
    )
    from core.prontidao import pode_alertar_esmaltes
    from core.telegram_gate import pode_enviar

    if not _cfg_alerta():
        return False, "alerta_desligado"
    msg = str(payload.get("mensagem") or "").strip()
    if not msg:
        return False, "sem_mensagem"
    novos = payload.get("novos") or []
    ranking = payload.get("ranking") or []
    if not novos and not ranking:
        return False, "sem_conteudo"
    pode, motivo = pode_alertar_esmaltes()
    if not pode:
        logger.warning("Telegram esmaltes bloqueado: %s", motivo)
        return False, motivo
    if not gestor_telegram_configurado():
        return False, "telegram_nao_configurado"
    if not pode_enviar():
        return False, "telegram_circuito"

    if novos:
        chave = chave_itens_novos("esmaltes:novos_kits_impala", novos)
        cooldown = 60
    else:
        chave = chave_resumo_periodo("esmaltes:rank_kits_impala", horas_por_bucket=6)
        cooldown = _cfg_rank_cooldown()
    ok = bool(
        alertar_gestor(
            msg,
            chave=chave,
            cooldown_segundos=cooldown,
            agente_id="novos_kits_impala",
        )
    )
    return ok, "enviado" if ok else "cooldown_ou_falha"


def processar(
    anuncios: list[dict[str, Any]] | None,
    *,
    persistir: bool = True,
    enviar_alerta: bool = True,
) -> dict[str, Any]:
    """Classifica, persiste, manda Telegram (novos + ranking) e devolve o card. Nunca lança."""
    try:
        if not _cfg_ativo():
            return {
                "ok": True,
                "desligado": True,
                "alertas": [],
                "n_novos": 0,
                "alerta_enviado": False,
            }
        estado = _carregar_vistos() if persistir else {"ids": [], "assinaturas": []}
        out = montar_novos(anuncios, vistos=estado)
        top_novos = (out.get("novos") or [])[: _cfg_top_n()]
        ranking = out.get("ranking") or []
        mensagem = formatar_mensagem(
            novos=top_novos,
            ranking=ranking,
            nomes=out.get("nomes_kits") or [],
            n_amostra=int(out.get("n_kits_impala") or 0),
            baseline=bool(out.get("baseline")),
        )
        alertas = [formatar_alerta(r) for r in top_novos]
        payload = {
            **out,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alertas": alertas,
            "novos": top_novos,
            "ranking": ranking,
            "mensagem": mensagem,
            "alerta_enviado": False,
            "alerta_motivo": "",
        }
        if persistir:
            _salvar_vistos(out.get("ids_unidos") or [], out.get("assinaturas_unidas") or [])
            escrever_json_atomico(SNAPSHOT_PATH, payload)
        emitir_metricas(payload)
        incrementar("impala.novos_kits.ok")
        if enviar_alerta:
            enviado, motivo = _enviar_telegram(payload)
            payload["alerta_enviado"] = enviado
            payload["alerta_motivo"] = motivo
            if enviado:
                incrementar("impala.novos_kits.alertas", float(max(1, len(alertas))))
        return payload
    except Exception as exc:
        logger.warning("novos_kits_impala: %s", exc)
        incrementar("impala.novos_kits.erro")
        return {
            "ok": False,
            "erro": str(exc),
            "alertas": [],
            "n_novos": 0,
            "alerta_enviado": False,
        }
