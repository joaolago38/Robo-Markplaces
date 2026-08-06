"""
integracoes/meta/meta_ads_client.py
Cliente de leitura de métricas de campanhas na Meta Ads API (Facebook + Instagram).
"""
import logging

from core.config import META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_API_VERSION
from core.http_client import request

logger = logging.getLogger("meta_ads_client")
BASE = f"https://graph.facebook.com/{META_API_VERSION}"

CAMPOS_INSIGHTS = [
    "campaign_id",
    "campaign_name",
    "spend",
    "cpc",
    "ctr",
    "frequency",
    "impressions",
    "actions",
    "action_values",
]


def _enabled() -> bool:
    return bool(META_ACCESS_TOKEN and META_AD_ACCOUNT_ID)


def _conta_normalizada() -> str:
    return str(META_AD_ACCOUNT_ID).replace("act_", "")


def _periodo_params(periodo_dias: int, data_inicio: str = "", data_fim: str = "") -> dict:
    """
    Monta o parâmetro de período. Datas custom (YYYY-MM-DD) têm prioridade;
    caso contrário usa date_preset (today / last_7d / last_30d).
    """
    if data_inicio and data_fim:
        return {"time_range": f'{{"since":"{data_inicio}","until":"{data_fim}"}}'}
    if periodo_dias <= 1:
        preset = "today"
    elif periodo_dias <= 7:
        preset = "last_7d"
    else:
        preset = "last_30d"
    return {"date_preset": preset}


def _coletar_paginas(url: str, params: dict, max_paginas: int = 10) -> list[dict]:
    """
    Faz a chamada e segue paging.next até max_paginas. Retorna a lista agregada
    do campo 'data'. Em qualquer falha, devolve o que já tiver coletado.
    """
    coletado: list[dict] = []
    proximo_url = url
    proximos_params = params
    paginas = 0

    while proximo_url and paginas < max_paginas:
        r = request("GET", proximo_url, params=proximos_params, timeout=30)
        r.raise_for_status()
        corpo = r.json()
        coletado.extend(corpo.get("data", []))

        proximo_url = (corpo.get("paging", {}) or {}).get("next")
        proximos_params = None  # a URL 'next' já vem com a querystring completa
        paginas += 1

    return coletado


def listar_metricas_campanhas(
    periodo_dias: int = 1,
    limite: int = 50,
    data_inicio: str = "",
    data_fim: str = "",
) -> list[dict]:
    """
    Retorna métricas por campanha (nível campaign). Suporta período por preset
    ou intervalo custom (data_inicio/data_fim em YYYY-MM-DD) e paginação.
    """
    if not _enabled():
        logger.info("Meta Ads não configurado (META_ACCESS_TOKEN/META_AD_ACCOUNT_ID).")
        return []

    try:
        url = f"{BASE}/act_{_conta_normalizada()}/insights"
        params = {
            "access_token": META_ACCESS_TOKEN,
            "level": "campaign",
            "fields": ",".join(CAMPOS_INSIGHTS),
            "limit": limite,
        }
        params.update(_periodo_params(periodo_dias, data_inicio, data_fim))
        return _coletar_paginas(url, params)
    except Exception as exc:
        logger.error("Meta Ads listar_metricas_campanhas erro: %s", exc)
        return []


def listar_metricas_por_plataforma(
    periodo_dias: int = 1,
    limite: int = 50,
    data_inicio: str = "",
    data_fim: str = "",
) -> list[dict]:
    """
    Igual a listar_metricas_campanhas, mas com breakdown por plataforma
    (publisher_platform = facebook / instagram / audience_network / messenger).
    Cada linha retornada contém a chave 'publisher_platform'.
    """
    if not _enabled():
        logger.info("Meta Ads não configurado (META_ACCESS_TOKEN/META_AD_ACCOUNT_ID).")
        return []

    try:
        url = f"{BASE}/act_{_conta_normalizada()}/insights"
        params = {
            "access_token": META_ACCESS_TOKEN,
            "level": "campaign",
            "fields": ",".join(CAMPOS_INSIGHTS),
            "breakdowns": "publisher_platform",
            "limit": limite,
        }
        params.update(_periodo_params(periodo_dias, data_inicio, data_fim))
        return _coletar_paginas(url, params)
    except Exception as exc:
        logger.error("Meta Ads listar_metricas_por_plataforma erro: %s", exc)
        return []


def _to_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _extrair_compras_receita(row: dict) -> tuple[float, float]:
    actions = row.get("actions") or []
    action_values = row.get("action_values") or []
    tipos = ("purchase", "offsite_conversion.purchase")

    compras = 0.0
    receita = 0.0
    for a in actions:
        if a.get("action_type") in tipos:
            compras += _to_float(a.get("value", 0))
    for v in action_values:
        if v.get("action_type") in tipos:
            receita += _to_float(v.get("value", 0))
    return compras, receita


def normalizar_metrica_campanha(row: dict) -> dict:
    """Normaliza uma linha da API para a estrutura padrão do projeto."""
    compras, receita = _extrair_compras_receita(row)
    gasto = _to_float(row.get("spend", 0))
    roas = (receita / gasto) if gasto > 0 else 0.0

    return {
        "id": row.get("campaign_id"),
        "nome": row.get("campaign_name", "campanha"),
        "gasto": round(gasto, 2),
        "cpc": _to_float(row.get("cpc", 0)),
        "ctr": _to_float(row.get("ctr", 0)),
        "frequencia": _to_float(row.get("frequency", 0)),
        "impressoes": int(_to_float(row.get("impressions", 0))),
        "compras": compras,
        "receita": round(receita, 2),
        "roas": round(roas, 2),
    }


def normalizar_por_plataforma(rows: list[dict]) -> dict:
    """
    Agrega linhas (com breakdown publisher_platform) por plataforma, devolvendo
    gasto, compras, receita, impressões e ROAS de cada uma (Instagram x Facebook etc.).
    """
    agregado: dict[str, dict] = {}

    for row in rows:
        plataforma = (row.get("publisher_platform") or "desconhecida").lower()
        compras, receita = _extrair_compras_receita(row)
        gasto = _to_float(row.get("spend", 0))
        impressoes = int(_to_float(row.get("impressions", 0)))

        bucket = agregado.setdefault(
            plataforma,
            {"gasto": 0.0, "compras": 0.0, "receita": 0.0, "impressoes": 0, "campanhas": 0},
        )
        bucket["gasto"] += gasto
        bucket["compras"] += compras
        bucket["receita"] += receita
        bucket["impressoes"] += impressoes
        bucket["campanhas"] += 1

    for bucket in agregado.values():
        bucket["gasto"] = round(bucket["gasto"], 2)
        bucket["receita"] = round(bucket["receita"], 2)
        bucket["roas"] = round(bucket["receita"] / bucket["gasto"], 2) if bucket["gasto"] > 0 else 0.0

    return agregado


def validar_conexao() -> dict:
    """
    Verifica se o token e a conta de anúncios estão acessíveis.
    Retorna {ok, usuario, conta, moeda, status_conta, erro}.
    NÃO lança exceção — sempre devolve um dict.
    """
    if not META_ACCESS_TOKEN:
        return {"ok": False, "erro": "META_ACCESS_TOKEN ausente"}
    if not META_AD_ACCOUNT_ID:
        return {"ok": False, "erro": "META_AD_ACCOUNT_ID ausente"}

    try:
        r_me = request(
            "GET",
            f"{BASE}/me",
            params={"access_token": META_ACCESS_TOKEN, "fields": "id,name"},
            timeout=15,
        )
        r_me.raise_for_status()
        me = r_me.json()

        r_conta = request(
            "GET",
            f"{BASE}/act_{_conta_normalizada()}",
            params={
                "access_token": META_ACCESS_TOKEN,
                "fields": "name,currency,account_status",
            },
            timeout=15,
        )
        r_conta.raise_for_status()
        conta = r_conta.json()

        return {
            "ok": True,
            "usuario": me.get("name", ""),
            "usuario_id": me.get("id", ""),
            "conta": conta.get("name", ""),
            "moeda": conta.get("currency", ""),
            "status_conta": conta.get("account_status"),
            "erro": "",
        }
    except Exception as exc:
        logger.error("Meta Ads validar_conexao erro: %s", exc)
        return {"ok": False, "erro": str(exc)}
