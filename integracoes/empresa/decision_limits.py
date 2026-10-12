"""
integracoes/empresa/decision_limits.py
Limites de tomada de decisão por CNPJ/CNAE para o ecossistema não
se atropelar no mesmo tema (importar, Ads, preço, saúde de anúncio).

Sinais considerados:
  - Alibaba (snapshots de importação/cruzamento)
  - Cotação USD/BRL
  - Saúde das vendas (margem)
  - Saúde do produto/anúncio no Mercado Livre
  - CNAEs e produtos vinculados ao CNPJ

Emite gauges/counts no Datadog (`robo.decision_limits.*`).
"""
from __future__ import annotations

import logging
from typing import Any

from core.atomic_io import escrever_json_atomico, ler_json
from core.config import ROOT
from core.datadog_metrics import gauge, incrementar
from core.empresa.cnpj_utils import digitos, formatar_cnpj, norm_cnae
from core.horario import agora_brasil

logger = logging.getLogger("decision_limits")

SNAPSHOT_PATH = ROOT / "logs" / "decision_limits_ultima.json"
CUPOS_PATH = ROOT / "logs" / "decision_limits_cupos.json"

# Temas canônicos — um cupo por tema evita o ecossistema repetir a mesma decisão
TEMAS = (
    "responder_perguntas",
    "corrigir_anuncio",
    "ajustar_preco",
    "tratar_claims",
    "despachar_envios",
    "impulsionar_ads",
    "importar_alibaba",
    "migrar_dono",
    "rodar_agentes_ramo",
)

_NIVEL_ORD = {"desconhecido": 0, "ok": 1, "atencao": 2, "critico": 3}


def _cfg():
    from core import config as cfg

    return cfg


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _ler_snap(nome: str) -> dict[str, Any]:
    data = ler_json(ROOT / "logs" / nome, default={})
    return data if isinstance(data, dict) else {}


def _tags_base(ctx: dict[str, Any]) -> list[str]:
    """Tags de baixa cardinalidade para Datadog."""
    tags = [
        "marketplace:mercadolivre",
        f"empresa:{ctx.get('empresa_id') or 'desconhecida'}",
    ]
    cnae = norm_cnae(str(ctx.get("cnae_principal") or ""))
    if cnae:
        # só dígitos do CNAE (ex. 4772500) — baixa cardinalidade
        tags.append(f"cnae:{cnae[:8]}")
    ramo = ""
    ramos = ctx.get("ramos") or []
    if ramos:
        ramo = str(ramos[0]).lower()[:24]
        tags.append(f"ramo:{ramo}")
    return tags


def coletar_sinais_volume_ml_cnae(vinculo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Quantidade e volume de vendas ML no CNAE/ramos do vínculo."""
    try:
        from integracoes.empresa.contexto_ml_cnae_importacao import (
            coletar_volume_vendas_ml_por_cnae,
        )

        v = vinculo or {}
        return coletar_volume_vendas_ml_por_cnae(
            cnae=str(v.get("cnae_principal") or ""),
            ramos=list(v.get("ramos") or []),
        )
    except Exception as exc:
        logger.debug("volume ml cnae: %s", exc)
        return {"ok": False, "quantidade_vendida": 0, "volume_receita_proxy": 0.0}


def coletar_sinais_destino_importacao() -> dict[str, Any]:
    """Aeroporto Campinas/VCP + CEP destino (default 13467-694, mutável via env)."""
    try:
        from integracoes.importacao.operacao_destino import resumo_destino

        return resumo_destino()
    except Exception as exc:
        logger.debug("destino importacao: %s", exc)
        return {
            "aeroporto_codigo": "VCP",
            "destino_cep": "13467-694",
            "destino_cidade": "Americana",
        }


def coletar_sinais_alibaba() -> dict[str, Any]:
    """Sinais Alibaba a partir dos últimos snapshots (sem bater API de novo)."""
    intel = _ler_snap("alibaba_inteligencia_ultima.json")
    imp = _ler_snap("alibaba_importacao_ultima.json")
    fil = _ler_snap("monitor_filamentos_ml_ultima.json")
    petg = _ler_snap("monitor_masterprint_petg_ultima.json")

    lucrativos = 0
    for src in (intel, imp, fil, petg):
        for chave in ("lucrativos", "alibaba_lucrativos", "total_lucrativos"):
            if src.get(chave) is not None:
                lucrativos = max(lucrativos, int(_num(src.get(chave))))
        cruz = src.get("cruzamento") if isinstance(src.get("cruzamento"), dict) else {}
        if cruz.get("lucrativos") is not None:
            lucrativos = max(lucrativos, int(_num(cruz.get("lucrativos"))))
        sourcing = src.get("sourcing") if isinstance(src.get("sourcing"), dict) else {}
        for v in sourcing.get("vereditos") or []:
            if str(v).upper() == "IMPORTAR_CHINA":
                lucrativos = max(lucrativos, 1)

    bloqueado = bool(
        intel.get("alibaba_bloqueado")
        or imp.get("alibaba_bloqueado")
        or (fil.get("cruzamento") or {}).get("alibaba_bloqueado")
    )
    return {
        "ok": bool(intel or imp or fil or petg),
        "lucrativos": lucrativos,
        "bloqueado": bloqueado,
        "tem_sinal_importar": lucrativos > 0 and not bloqueado,
        "fontes": [k for k, v in {
            "inteligencia": bool(intel),
            "importacao": bool(imp),
            "filamentos": bool(fil),
            "petg": bool(petg),
        }.items() if v],
    }


def coletar_sinais_cambio(*, ao_vivo: bool = False) -> dict[str, Any]:
    """Cotação USD — cache/histórico; opcionalmente refresh."""
    cfg = _cfg()
    cotacao: dict[str, Any] = {}
    try:
        from integracoes.cambio.cotacao_usd import (
            cotacao_confiavel_para_margem,
            obter_cotacao_usd,
            variacao_desde_ultima_rodada,
        )

        cotacao = obter_cotacao_usd(usar_cache=not ao_vivo)
        confiavel = cotacao_confiavel_para_margem(cotacao)
        var_info = variacao_desde_ultima_rodada() if cotacao.get("ok") else {}
        var_pct_calc = _num((var_info or {}).get("variacao_pct"), default=-999.0)
    except Exception as exc:
        logger.debug("cambio decision_limits: %s", exc)
        cotacao = {"ok": False, "erro": str(exc)}
        confiavel = False
        var_pct_calc = -999.0

    alerta_pct = float(getattr(cfg, "CAMBIO_ALERTA_VARIACAO_PCT", 1.5))
    if var_pct_calc <= -900:
        var_pct = _num(cotacao.get("variacao_pct"), 0.0)
    else:
        var_pct = var_pct_calc
    volatil = abs(var_pct) >= alerta_pct
    return {
        "ok": bool(cotacao.get("ok")),
        "usd_brl": _num(cotacao.get("usd_brl")),
        "fonte": cotacao.get("fonte"),
        "confiavel": confiavel,
        "variacao_pct": var_pct,
        "volatil": volatil,
        "idade_seg": cotacao.get("idade_seg"),
        "bloquear_import_por_fx": (not confiavel) or volatil,
    }


def coletar_sinais_vendas() -> dict[str, Any]:
    margem = _ler_snap("margem_vendas_ultima.json")
    cfg = _cfg()
    min_pct = float(getattr(cfg, "MONITOR_MARGEM_VENDAS_MARGEM_MIN_PCT", 15.0))
    analise = margem.get("analise") if isinstance(margem.get("analise"), dict) else {}
    media = _num(
        margem.get("margem_media_pct")
        or margem.get("margem_media")
        or analise.get("margem_media_pct")
        or (margem.get("resumo") or {}).get("margem_media_pct"),
        default=-1.0,
    )
    alertas = int(
        _num(
            margem.get("total_alertas")
            or margem.get("alertas")
            or analise.get("total_alertas")
            or (margem.get("resumo") or {}).get("total_alertas")
        )
    )
    vendas = int(
        _num(
            margem.get("total_vendas")
            or margem.get("vendas")
            or analise.get("total_itens")
            or (margem.get("resumo") or {}).get("total_vendas")
        )
    )
    saudavel = media < 0 or media >= min_pct
    return {
        "ok": bool(margem),
        "margem_media_pct": None if media < 0 else media,
        "total_alertas": alertas,
        "total_vendas": vendas,
        "abaixo_minimo": media >= 0 and media < min_pct,
        "saudavel": saudavel and alertas == 0,
        "min_pct": min_pct,
    }


def coletar_sinais_saude_produto(resumo: dict[str, Any] | None = None) -> dict[str, Any]:
    """Saúde do produto/anúncio no ML (resumo_conta + sem_venda + estado)."""
    rc = resumo if isinstance(resumo, dict) else _ler_snap("resumo_conta_ml_ultima.json")
    sem = _ler_snap("sem_venda_ml_ultima.json")
    try:
        from core.claude_contexto_ml import carregar_estado_ml

        estado = carregar_estado_ml(ao_vivo=False)
    except Exception:
        estado = {}

    a_melhorar = int(_num(rc.get("anuncios_a_melhorar_total")))
    perguntas = int(_num(rc.get("perguntas_pendentes")))
    claims = int(_num(rc.get("pos_venda_claims")))
    pausados = int(_num(rc.get("anuncios_pausados")))
    ativos = int(_num(rc.get("anuncios_ativos")))
    sem_venda = int(
        _num(
            sem.get("total")
            or sem.get("quantidade")
            or sem.get("itens_sem_venda")
            or len(sem.get("itens") or [])
        )
    )
    nivel = str(estado.get("nivel") or "desconhecido")
    return {
        "ok": bool(rc.get("ok") or estado),
        "degradado": bool(rc) and not rc.get("ok"),
        "a_melhorar": a_melhorar,
        "perguntas": perguntas,
        "claims": claims,
        "pausados": pausados,
        "ativos": ativos,
        "sem_venda": sem_venda,
        "nivel_ml": nivel,
        "nivel_ord": _NIVEL_ORD.get(nivel, 0),
        "score_algoritmo": estado.get("score_algoritmo"),
        "alertas_ml": list(estado.get("alertas") or [])[:4],
    }


def _cupos_ativos() -> dict[str, Any]:
    data = ler_json(CUPOS_PATH, default={})
    return data if isinstance(data, dict) else {}


def _registrar_cupo(tema: str, ctx: dict[str, Any]) -> None:
    """Marca tema como 'em uso' para o CNPJ (anti-atropelo entre agentes)."""
    data = _cupos_ativos()
    temas = data.get("temas") if isinstance(data.get("temas"), dict) else {}
    chave = f"{digitos(str(ctx.get('cnpj') or ''))}:{tema}"
    temas[chave] = {
        "tema": tema,
        "cnpj": digitos(str(ctx.get("cnpj") or "")),
        "empresa_id": ctx.get("empresa_id"),
        "cnae": ctx.get("cnae_principal"),
        "em": agora_brasil().isoformat(),
    }
    # Mantém só últimas 80 entradas
    if len(temas) > 80:
        ordenados = sorted(temas.items(), key=lambda kv: str((kv[1] or {}).get("em") or ""))
        temas = dict(ordenados[-80:])
    escrever_json_atomico(
        CUPOS_PATH,
        {"temas": temas, "atualizado_em": agora_brasil().isoformat()},
    )


def tema_em_uso(tema: str, cnpj: str, *, janela_horas: int | None = None) -> bool:
    """True se outro agente já tomou decisão neste tema/CNPJ na janela."""
    cfg = _cfg()
    horas = janela_horas if janela_horas is not None else int(
        getattr(cfg, "DECISION_LIMITS_JANELA_HORAS", 12)
    )
    data = _cupos_ativos()
    temas = data.get("temas") if isinstance(data.get("temas"), dict) else {}
    chave = f"{digitos(cnpj)}:{tema}"
    item = temas.get(chave)
    if not isinstance(item, dict):
        return False
    from datetime import datetime, timedelta

    try:
        em = datetime.fromisoformat(str(item.get("em") or "").replace("Z", "+00:00"))
    except Exception:
        return False
    agora = agora_brasil()
    if em.tzinfo is None:
        em = em.replace(tzinfo=agora.tzinfo)
    return (agora - em) < timedelta(hours=max(1, horas))


def computar_limites(
    *,
    vinculo: dict[str, Any] | None = None,
    cnpj: str | None = None,
    cnae: str | None = None,
    resumo_ml: dict[str, Any] | None = None,
    cambio_ao_vivo: bool = False,
) -> dict[str, Any]:
    """
    Calcula limites e bloqueios para decisões ML referenciadas ao CNAE/CNPJ.
    """
    cfg = _cfg()
    v = dict(vinculo or {})
    if not v and (cnpj or cnae):
        try:
            from integracoes.empresa.vinculo_cnae_cnpj_produtos import montar_vinculo

            base = montar_vinculo(cnpj=cnpj, cnae=cnae)
            v = (base.get("vinculos") or [{}])[0] if base.get("vinculos") else {}
        except Exception as exc:
            logger.debug("vinculo decision_limits: %s", exc)

    ctx = {
        "cnpj": digitos(str(v.get("cnpj") or cnpj or "")),
        "cnpj_formatado": v.get("cnpj_formatado") or formatar_cnpj(cnpj or ""),
        "empresa_id": v.get("empresa_id"),
        "cnae_principal": v.get("cnae_principal") or cnae,
        "ramos": list(v.get("ramos") or []),
        "agentes_prioritarios": list(v.get("agentes_prioritarios") or []),
        "total_skus": int(_num((v.get("produtos") or {}).get("total_skus"))),
    }

    alibaba = coletar_sinais_alibaba()
    cambio = coletar_sinais_cambio(ao_vivo=cambio_ao_vivo)
    vendas = coletar_sinais_vendas()
    saude = coletar_sinais_saude_produto(resumo_ml)
    volume_ml = coletar_sinais_volume_ml_cnae(v)
    destino = coletar_sinais_destino_importacao()

    max_fazer = max(1, int(getattr(cfg, "DECISION_LIMITS_MAX_FAZER", 3)))
    max_importar = max(0, int(getattr(cfg, "DECISION_LIMITS_MAX_IMPORTAR", 1)))
    max_ads = max(0, int(getattr(cfg, "DECISION_LIMITS_MAX_ADS", 1)))

    bloqueios: list[dict[str, str]] = []
    permitidos: dict[str, bool] = {t: True for t in TEMAS}

    # --- Condições ---
    if saude.get("degradado"):
        bloqueios.append(
            {"tema": "*", "motivo": "dados_ml_degradados", "acao": "reduzir_decisoes"}
        )
        max_fazer = min(max_fazer, 2)

    if saude.get("nivel_ml") == "critico" or int(saude.get("claims") or 0) >= 2:
        permitidos["impulsionar_ads"] = False
        bloqueios.append(
            {"tema": "impulsionar_ads", "motivo": "saude_ml_critica", "acao": "bloquear"}
        )

    if cambio.get("bloquear_import_por_fx"):
        permitidos["importar_alibaba"] = False
        bloqueios.append(
            {
                "tema": "importar_alibaba",
                "motivo": "cambio_instavel_ou_nao_confiavel",
                "acao": "bloquear",
            }
        )
        permitidos["ajustar_preco"] = permitidos["ajustar_preco"] and not cambio.get("volatil")
        if cambio.get("volatil"):
            bloqueios.append(
                {"tema": "ajustar_preco", "motivo": "dolar_volatil", "acao": "adiar"}
            )

    if alibaba.get("bloqueado"):
        permitidos["importar_alibaba"] = False
        bloqueios.append(
            {"tema": "importar_alibaba", "motivo": "alibaba_bloqueado", "acao": "bloquear"}
        )

    if not alibaba.get("tem_sinal_importar"):
        # Sem oportunidade clara — não gastar cupo de importação
        if max_importar > 0 and not alibaba.get("lucrativos"):
            permitidos["importar_alibaba"] = False
            bloqueios.append(
                {
                    "tema": "importar_alibaba",
                    "motivo": "sem_sinal_lucrativo_alibaba",
                    "acao": "adiar",
                }
            )

    if vendas.get("abaixo_minimo"):
        # Vendas ruins: priorizar correção, não Ads/import
        permitidos["impulsionar_ads"] = False
        bloqueios.append(
            {
                "tema": "impulsionar_ads",
                "motivo": "margem_vendas_abaixo_minimo",
                "acao": "bloquear",
            }
        )
        if not cambio.get("confiavel"):
            permitidos["importar_alibaba"] = False

    if int(saude.get("perguntas") or 0) >= 5 or int(saude.get("a_melhorar") or 0) >= 5:
        # Saúde do produto manda — Ads e import ficam para depois
        permitidos["impulsionar_ads"] = False
        permitidos["importar_alibaba"] = False
        bloqueios.append(
            {
                "tema": "impulsionar_ads",
                "motivo": "saude_produto_prioriza_operacao",
                "acao": "bloquear",
            }
        )

    # Volume ML no CNAE: sem demanda medida → adiar import
    qtd_vol = int(volume_ml.get("quantidade_vendida") or 0)
    if permitidos.get("importar_alibaba") and qtd_vol <= 0 and (ctx.get("ramos") or []):
        bloqueios.append(
            {
                "tema": "importar_alibaba",
                "motivo": "volume_ml_cnae_sem_sinal",
                "acao": "adiar",
            }
        )

    # Anti-atropelo: temas já usados na janela
    cnpj_d = ctx["cnpj"]
    cupos_restantes = {}
    for tema in TEMAS:
        em_uso = bool(cnpj_d and tema_em_uso(tema, cnpj_d))
        if em_uso:
            permitidos[tema] = False
            bloqueios.append(
                {"tema": tema, "motivo": "tema_ja_decidido_na_janela", "acao": "bloquear"}
            )
        cupos_restantes[tema] = 0 if not permitidos.get(tema) else (
            max_importar if tema == "importar_alibaba"
            else max_ads if tema == "impulsionar_ads"
            else 1
        )

    # Cap global de FAZER
    temas_livres = [t for t, ok in permitidos.items() if ok]
    if len(temas_livres) > max_fazer:
        # Mantém ordem de prioridade operacional ML
        prioridade = [
            "responder_perguntas",
            "tratar_claims",
            "despachar_envios",
            "corrigir_anuncio",
            "ajustar_preco",
            "rodar_agentes_ramo",
            "importar_alibaba",
            "impulsionar_ads",
            "migrar_dono",
        ]
        ordenados = [t for t in prioridade if t in temas_livres]
        cortados = set(ordenados[max_fazer:])
        for t in cortados:
            permitidos[t] = False
            cupos_restantes[t] = 0
            bloqueios.append(
                {"tema": t, "motivo": "cap_max_fazer", "acao": "adiar"}
            )

    out = {
        "ok": True,
        "gerado_em": agora_brasil().isoformat(),
        "marketplace_foco": "mercadolivre",
        "contexto": ctx,
        "limites": {
            "max_acoes_fazer": max_fazer,
            "max_importar_alibaba": max_importar,
            "max_impulsionar_ads": max_ads,
            "permitidos": permitidos,
            "cupos_restantes": cupos_restantes,
        },
        "sinais": {
            "alibaba": alibaba,
            "cambio": cambio,
            "vendas": vendas,
            "saude_produto": saude,
            "volume_ml_cnae": volume_ml,
            "destino_importacao": destino,
        },
        "bloqueios": bloqueios[:20],
        "resumo_humano": _resumo_humano(
            ctx, bloqueios, alibaba, cambio, vendas, saude, volume_ml, destino
        ),
    }
    return out


def _resumo_humano(
    ctx: dict[str, Any],
    bloqueios: list[dict[str, str]],
    alibaba: dict[str, Any],
    cambio: dict[str, Any],
    vendas: dict[str, Any],
    saude: dict[str, Any],
    volume_ml: dict[str, Any] | None = None,
    destino: dict[str, Any] | None = None,
) -> str:
    volume_ml = volume_ml or {}
    destino = destino or {}
    partes = [
        f"CNPJ `{ctx.get('cnpj_formatado') or ctx.get('cnpj')}`",
        f"CNAE `{ctx.get('cnae_principal') or '—'}`",
        f"ML nível `{saude.get('nivel_ml')}`",
        f"USD {cambio.get('usd_brl') or '—'} ({'ok' if cambio.get('confiavel') else 'fx!'})",
        f"Alibaba lucrativos={alibaba.get('lucrativos', 0)}",
        f"vol.ML qtd={volume_ml.get('quantidade_vendida') or 0}",
        f"VCP→CEP `{destino.get('destino_cep') or '13467-694'}`",
    ]
    margem = vendas.get("margem_media_pct")
    partes.append(
        "margem vendas=n/d" if margem is None else f"margem vendas={float(margem):.1f}%"
    )
    if bloqueios:
        motivos = sorted({b.get("motivo") or "" for b in bloqueios if b.get("motivo")})
        partes.append(f"bloqueios: {', '.join(motivos[:4])}")
    return " · ".join(partes)


def emitir_metricas(limites: dict[str, Any]) -> None:
    """Publica limites e sinais no Datadog."""
    ctx = limites.get("contexto") or {}
    tags = _tags_base(ctx)
    lim = limites.get("limites") or {}
    sinais = limites.get("sinais") or {}
    saude = sinais.get("saude_produto") or {}
    cambio = sinais.get("cambio") or {}
    vendas = sinais.get("vendas") or {}
    alibaba = sinais.get("alibaba") or {}

    gauge("decision_limits.max_acoes_fazer", float(lim.get("max_acoes_fazer") or 0), tags)
    gauge(
        "decision_limits.cupos_livres",
        float(sum(1 for v in (lim.get("cupos_restantes") or {}).values() if v)),
        tags,
    )
    gauge("decision_limits.nivel_ml_ord", float(saude.get("nivel_ord") or 0), tags)
    gauge("decision_limits.a_melhorar", float(saude.get("a_melhorar") or 0), tags)
    gauge("decision_limits.perguntas", float(saude.get("perguntas") or 0), tags)
    gauge("decision_limits.claims", float(saude.get("claims") or 0), tags)
    gauge("decision_limits.sem_venda", float(saude.get("sem_venda") or 0), tags)
    gauge("decision_limits.usd_brl", float(cambio.get("usd_brl") or 0), tags)
    gauge(
        "decision_limits.cambio_confiavel",
        1.0 if cambio.get("confiavel") else 0.0,
        tags,
    )
    gauge(
        "decision_limits.alibaba_lucrativos",
        float(alibaba.get("lucrativos") or 0),
        tags,
    )
    if vendas.get("margem_media_pct") is not None:
        gauge(
            "decision_limits.margem_vendas_pct",
            float(vendas.get("margem_media_pct") or 0),
            tags,
        )
    gauge("decision_limits.skus_cnpj", float(ctx.get("total_skus") or 0), tags)
    volume = sinais.get("volume_ml_cnae") or {}
    gauge(
        "decision_limits.volume_ml_qtd",
        float(volume.get("quantidade_vendida") or 0),
        tags,
    )
    gauge(
        "decision_limits.volume_ml_receita",
        float(volume.get("volume_receita_proxy") or 0),
        tags,
    )
    destino = sinais.get("destino_importacao") or {}
    if destino.get("distancia_km") is not None:
        gauge(
            "decision_limits.destino_km_vcp",
            float(destino.get("distancia_km") or 0),
            tags,
        )
    incrementar("decision_limits.computado", tags=tags)

    for b in limites.get("bloqueios") or []:
        motivo = str(b.get("motivo") or "outro")[:48]
        incrementar(
            "decision_limits.bloqueio",
            tags=[*tags, f"motivo:{motivo}", f"tema:{b.get('tema') or '*'}"],
        )


def pode_decidir(tema: str, limites: dict[str, Any] | None) -> tuple[bool, str]:
    """Gate para agentes: pode tomar decisão neste tema?"""
    if not limites or not limites.get("ok"):
        return True, "limites_indisponiveis"
    permitidos = (limites.get("limites") or {}).get("permitidos") or {}
    if tema not in TEMAS:
        return True, "tema_desconhecido"
    if not permitidos.get(tema, True):
        motivo = next(
            (
                b.get("motivo")
                for b in (limites.get("bloqueios") or [])
                if b.get("tema") in (tema, "*")
            ),
            "bloqueado",
        )
        return False, str(motivo)
    return True, "ok"


def aplicar_limites_nas_acoes(
    acoes: dict[str, Any],
    limites: dict[str, Any],
    *,
    registrar: bool = True,
) -> dict[str, Any]:
    """
    Filtra FAZER/NÃO FAZER conforme limites; registra cupos usados.
    Mapeia linhas de ação → temas.
    """
    cfg = _cfg()
    if not bool(getattr(cfg, "DECISION_LIMITS_ATIVO", True)):
        return {**acoes, "limites_aplicados": False}

    permitidos = (limites.get("limites") or {}).get("permitidos") or {}
    max_fazer = int((limites.get("limites") or {}).get("max_acoes_fazer") or 3)
    ctx = limites.get("contexto") or {}

    mapa_prefixo = [
        ("Responder", "responder_perguntas"),
        ("Corrigir", "corrigir_anuncio"),
        ("Revisar", "ajustar_preco"),
        ("Tratar", "tratar_claims"),
        ("Despachar", "despachar_envios"),
        ("Rodar agentes", "rodar_agentes_ramo"),
        ("Importar", "importar_alibaba"),
        ("Impulsionar", "impulsionar_ads"),
        ("migrar dono", "migrar_dono"),
    ]

    fazer_novo: list[str] = []
    temas_usados: list[str] = []
    for linha in acoes.get("fazer") or []:
        tema = None
        low = linha.lower()
        for pref, t in mapa_prefixo:
            if pref.lower() in low:
                tema = t
                break
        if tema and not permitidos.get(tema, True):
            continue
        if tema and tema in temas_usados:
            continue
        fazer_novo.append(linha)
        if tema:
            temas_usados.append(tema)
        if len(fazer_novo) >= max_fazer:
            break

    if not fazer_novo:
        fazer_novo = ["Aguardar — limites do ecossistema bloquearam novas ações nesta janela"]

    nao_fazer = list(acoes.get("nao_fazer") or [])
    for b in limites.get("bloqueios") or []:
        if b.get("acao") != "bloquear":
            continue
        tema = b.get("tema")
        motivo = b.get("motivo")
        if tema and tema != "*":
            msg = f"Não `{tema}` agora ({motivo})"
            if msg not in nao_fazer:
                nao_fazer.append(msg)

    # Sinais extras no CUSTO
    custo = list(acoes.get("custo") or [])
    sinais = limites.get("sinais") or {}
    cambio = sinais.get("cambio") or {}
    alibaba = sinais.get("alibaba") or {}
    vendas = sinais.get("vendas") or {}
    if cambio.get("usd_brl"):
        custo.append(
            f"USD R$ {cambio.get('usd_brl'):.2f}"
            + (" · fx instável" if cambio.get("bloquear_import_por_fx") else "")
        )
    if alibaba.get("lucrativos"):
        custo.append(f"Alibaba: {alibaba.get('lucrativos')} lucrativo(s) no radar")
    if vendas.get("margem_media_pct") is not None:
        custo.append(f"Margem vendas: {vendas['margem_media_pct']:.1f}%")

    if registrar:
        for t in temas_usados:
            _registrar_cupo(t, ctx)

    urgencia = acoes.get("urgencia") or "baixa"
    saude = sinais.get("saude_produto") or {}
    if saude.get("degradado") or saude.get("nivel_ml") == "critico":
        urgencia = "alta"
    elif (limites.get("bloqueios") or []) and urgencia == "baixa":
        urgencia = "media"

    return {
        **acoes,
        "fazer": fazer_novo[:max_fazer],
        "nao_fazer": nao_fazer[:5],
        "custo": custo[:5],
        "urgencia": urgencia,
        "limites_aplicados": True,
        "temas_usados": temas_usados,
        "bloqueios": limites.get("bloqueios") or [],
        "resumo_limites": limites.get("resumo_humano"),
    }


def computar_e_emitir(
    *,
    vinculo: dict[str, Any] | None = None,
    resumo_ml: dict[str, Any] | None = None,
    cambio_ao_vivo: bool = False,
) -> dict[str, Any]:
    """Atalho: computa, grava snapshot e emite Datadog."""
    lim = computar_limites(
        vinculo=vinculo,
        resumo_ml=resumo_ml,
        cambio_ao_vivo=cambio_ao_vivo,
    )
    emitir_metricas(lim)
    escrever_json_atomico(SNAPSHOT_PATH, lim)
    return lim
