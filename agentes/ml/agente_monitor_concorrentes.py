"""
agentes/ml/agente_monitor_concorrentes.py
Monitor de concorrentes ML por termo de busca (catalogo/concorrentes_monitorados.json).
Somente leitura — não altera preços nem anúncios.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.config import (
    MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO,
    MONITOR_CONCORRENTES_ARQUIVO,
    MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT,
    ROOT,
)
from core.datadog_metrics import gauge, incrementar
from core.notificador import alertar_gestor
from integracoes.ml import ml_client

logger = logging.getLogger("agente_monitor_concorrentes")

HISTORY_PATH = ROOT / "logs" / "concorrentes_ml_history.json"


def _carregar_lista() -> list[dict]:
    caminho = ROOT / MONITOR_CONCORRENTES_ARQUIVO
    try:
        if not caminho.is_file():
            logger.warning("Arquivo de monitoramento não encontrado: %s", caminho)
            return []
        with caminho.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar %s: %s", caminho, exc)
        return []


def _carregar_historico() -> dict[str, Any]:
    try:
        if not HISTORY_PATH.is_file():
            return {}
        with HISTORY_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error("Erro ao carregar histórico: %s", exc)
        return {}


def _salvar_historico(historico: dict[str, Any]) -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp.replace(HISTORY_PATH)
    except Exception as exc:
        logger.error("Erro ao salvar histórico: %s", exc)


def _pct_variacao(anterior: float, atual: float) -> float:
    if anterior <= 0 or atual <= 0:
        return 0.0
    return abs(atual - anterior) / anterior * 100.0


def _menor_preco(concorrentes: list[dict]) -> float:
    precos = [float(c.get("preco") or 0) for c in concorrentes if float(c.get("preco") or 0) > 0]
    return min(precos) if precos else 0.0


def _item_id_ml_valido(valor: Any) -> bool:
    texto = str(valor or "").strip()
    if not texto or "PREENCHER" in texto.upper():
        return False
    up = texto.upper().replace("-", "")
    if not up.startswith("MLB"):
        return False
    digits = up[3:]
    return digits.isdigit() and len(digits) >= 6


def _rotulo_preco_referencia(origem: str) -> str:
    """Evita 'seu preço' quando não há anúncio vivo — usa 'preço alvo' do catálogo/JSON."""
    if origem == "anuncio_vivo":
        return "seu anúncio"
    return "preço alvo"


def _resolver_preco_referencia(entrada: dict) -> tuple[float, str]:
    """
    Resolve preço de comparação nesta ordem:
    1) preço vivo do anúncio ML (item_id válido)
    2) preço do canal ML em produtos.json (por SKU)
    3) meu_preco do JSON de concorrentes (alvo cadastrado)
    """
    fallback = 0.0
    try:
        fallback = float(entrada.get("meu_preco") or 0)
    except (TypeError, ValueError):
        fallback = 0.0

    item_id = str(entrada.get("item_id") or "").strip()
    sku = str(entrada.get("sku") or "").strip()
    catalogo_preco = 0.0

    if sku:
        try:
            from core.catalogo_produtos import carregar_produtos_catalogo

            for produto in carregar_produtos_catalogo():
                if str(produto.get("sku") or "").strip() != sku:
                    continue
                ml = (produto.get("canais") or {}).get("mercadolivre") or {}
                if not item_id:
                    item_id = str(ml.get("item_id") or "").strip()
                try:
                    catalogo_preco = float(ml.get("preco") or produto.get("preco") or 0)
                except (TypeError, ValueError):
                    catalogo_preco = 0.0
                break
        except Exception as exc:
            logger.debug("catálogo indisponível para preço alvo sku=%s: %s", sku, exc)

    if _item_id_ml_valido(item_id):
        try:
            metricas = ml_client.buscar_metricas_item(item_id)
            vivo = float((metricas or {}).get("preco") or 0)
            if vivo > 0:
                return vivo, "anuncio_vivo"
        except Exception as exc:
            logger.debug("preço vivo indisponível item_id=%s: %s", item_id, exc)

    if catalogo_preco > 0:
        return catalogo_preco, "catalogo"
    if fallback > 0:
        return fallback, "alvo_json"
    return 0.0, "indefinido"


def _pode_alertar_gap_preco(origem_preco: str) -> bool:
    """Gap vs preço alvo só alerta com anúncio vivo (evita Telegram fictício)."""
    if not MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO:
        return True
    return origem_preco == "anuncio_vivo"


def _leituras_recentes(entrada_hist: dict, limite: int = 5) -> list[dict]:
    leituras = entrada_hist.get("leituras")
    if isinstance(leituras, list) and leituras:
        return [x for x in leituras if isinstance(x, dict)][-limite:]
    if entrada_hist.get("menor_preco"):
        return [{"menor_preco": float(entrada_hist["menor_preco"]), "ts": entrada_hist.get("atualizado_em")}]
    return []


def _classificar_variacao_preco(
    eid: str,
    nome: str,
    termo: str,
    menor_atual: float,
    historico: dict[str, Any],
) -> str | None:
    """
    Classifica padrão de variação com histórico (3-5 leituras). Retorna None se <2 pontos.
    """
    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    leituras = _leituras_recentes(anterior, limite=5)
    if len(leituras) < 2:
        return None
    contexto = {
        "produto": nome,
        "termo_busca": termo,
        "menor_preco_atual": menor_atual,
        "leituras_recentes": leituras,
    }
    quedas = 0
    for i in range(1, len(leituras)):
        p_ant = float(leituras[i - 1].get("menor_preco") or 0)
        p_at = float(leituras[i].get("menor_preco") or 0)
        if p_ant > 0 and p_at < p_ant:
            quedas += 1
    fallback = "queda pontual"
    if quedas >= 3:
        fallback = f"tendência de baixa ({quedas}ª queda seguida)"
    elif quedas >= 2:
        fallback = "tendência de baixa (2 quedas seguidas)"
    from core.claude_client import MODELO_RAPIDO
    from core.resumo_ia import sintetizar_claude

    prompt = (
        "Em UMA linha, classifique o padrão da variação de preço do concorrente "
        "(ex.: 'queda pontual' vs 'tendência de baixa (3ª queda seguida)')."
    )
    texto = sintetizar_claude(
        prompt, contexto, fallback, max_tokens=60, modelo=MODELO_RAPIDO
    )
    return (texto or "").strip() or None


def _monitorar_loja(entrada: dict, historico: dict[str, Any]) -> dict[str, Any]:
    """Monitora uma loja concorrente (seller_id) via análise por termos."""
    from integracoes.ml.analise_loja_concorrente import analisar_loja

    eid = str(entrada.get("id") or "").strip()
    nome = str(entrada.get("nome") or eid)
    seller_id = str(entrada.get("seller_id") or "").strip()
    nickname = str(entrada.get("nickname") or "").strip() or None
    termos = entrada.get("termos_busca")
    if not isinstance(termos, list):
        termos = None
    meu_preco, origem_preco = _resolver_preco_referencia(entrada)
    rotulo = _rotulo_preco_referencia(origem_preco)
    limite = int(entrada.get("limite_resultados") or 20)

    if not seller_id:
        return {"id": eid, "ok": False, "erro": "seller_id vazio", "alertas": [], "tipo": "loja"}

    analise = analisar_loja(
        seller_id,
        nickname=nickname,
        termos=termos,
        limite_por_termo=limite,
    )
    anuncios = analise.get("anuncios") or []
    # analisar_loja já enriquece métricas; garante amostra se veio sem
    if anuncios and not any(a.get("metricas") for a in anuncios[:3]):
        try:
            from integracoes.ml.analise_anuncio_concorrente import enriquecer_lista

            anuncios = enriquecer_lista(anuncios)
            analise["anuncios"] = anuncios
        except Exception as exc:
            logger.warning("enriquecer métricas loja %s: %s", eid, exc)
    menor = float(analise.get("preco_min") or 0)
    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    menor_ant = float(anterior.get("menor_preco") or 0)

    alertas: list[str] = []
    if _pode_alertar_gap_preco(origem_preco):
        for ameaca in analise.get("ameacas_preco") or []:
            alertas.append(
                f"{nome}: {ameaca.get('sku')} {rotulo} R$ {ameaca.get('meu_preco'):.2f} está "
                f"{ameaca.get('gap_pct')}% acima do anúncio da loja "
                f"(R$ {ameaca.get('menor_preco_loja'):.2f})."
            )

    if menor_ant > 0 and menor > 0:
        var = _pct_variacao(menor_ant, menor)
        if var >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            direcao = "caiu" if menor < menor_ant else "subiu"
            alertas.append(
                f"{nome}: menor preço amostrado {direcao} de R$ {menor_ant:.2f} "
                f"para R$ {menor:.2f} ({var:.1f}%)."
            )

    if (
        _pode_alertar_gap_preco(origem_preco)
        and meu_preco > 0
        and menor > 0
        and meu_preco > menor
    ):
        diff = (meu_preco - menor) / menor * 100.0
        if diff >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            alertas.append(
                f"{nome}: {rotulo} R$ {meu_preco:.2f} está {diff:.1f}% acima "
                f"do menor anúncio amostrado da loja (R$ {menor:.2f})."
            )

    leituras_ant = _leituras_recentes(anterior, limite=4)
    leituras_ant.append(
        {"menor_preco": menor, "ts": datetime.now(timezone.utc).isoformat()}
    )
    historico[eid] = {
        "menor_preco": menor,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "total_concorrentes": len(anuncios),
        "seller_id": seller_id,
        "nickname": analise.get("nickname") or nickname,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "leituras": leituras_ant[-5:],
        "perfil": analise.get("perfil"),
    }

    _tags = [f"produto:{eid}", f"seller:{seller_id}", "tipo:loja", f"origem_preco:{origem_preco}"]
    if menor > 0:
        gauge("mercado.menor_preco_concorrente", menor, tags=_tags)
    gauge("mercado.total_concorrentes", float(len(anuncios)), tags=_tags)
    if alertas:
        incrementar("mercado.alertas_preco", float(len(alertas)), tags=_tags)

    return {
        "id": eid,
        "ok": True,
        "tipo": "loja",
        "nome": nome,
        "seller_id": seller_id,
        "nickname": analise.get("nickname") or nickname,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "menor_preco": menor,
        "total_concorrentes": len(anuncios),
        "concorrentes_amostra": anuncios[:5],
        "ameacas_preco": analise.get("ameacas_preco") or [],
        "perfil": analise.get("perfil"),
        "alertas": alertas,
    }


def _monitorar_item_watchlist(
    entrada: dict,
    historico: dict[str, Any],
    *,
    enriquecer_metricas: bool = True,
) -> dict[str, Any]:
    """
    Watchlist de alta confiança: MLB fixo do concorrente via GET /items/{id}.
    Alertas: variação de preço, mudança de status (active/paused/closed).
    """
    eid = str(entrada.get("id") or "").strip()
    nome = str(entrada.get("nome") or eid)
    # item_id_concorrente = anúncio rival; item_id = nosso (opcional, para gap)
    watch_id = str(
        entrada.get("item_id_concorrente")
        or entrada.get("watch_item_id")
        or entrada.get("mlb_concorrente")
        or ""
    ).strip()
    meu_preco, origem_preco = _resolver_preco_referencia(entrada)
    rotulo = _rotulo_preco_referencia(origem_preco)

    if not _item_id_ml_valido(watch_id):
        return {
            "id": eid,
            "ok": False,
            "tipo": "item",
            "erro": "item_id_concorrente inválido ou MLB_PREENCHER",
            "alertas": [],
        }

    pub = ml_client.buscar_item_publico(watch_id)
    if not pub:
        return {
            "id": eid,
            "ok": False,
            "tipo": "item",
            "nome": nome,
            "item_id_concorrente": watch_id,
            "erro": "falha ao ler item na API ML",
            "alertas": [],
        }

    preco = float(pub.get("preco") or 0)
    status = str(pub.get("status") or "").strip().lower()
    titulo = str(pub.get("titulo") or nome)[:60]
    sold = int(pub.get("sold_quantity") or 0)

    avaliacoes = None
    nota = None
    if enriquecer_metricas:
        try:
            from integracoes.ml.analise_anuncio_concorrente import enriquecer_anuncio

            row = enriquecer_anuncio(
                {
                    "item_id": watch_id,
                    "preco": preco,
                    "quantidade_vendida": sold,
                    "titulo": titulo,
                    "seller_id": pub.get("seller_id"),
                },
                buscar_reviews=True,
                buscar_catalogo=False,
                buscar_visitas=False,
            )
            avaliacoes = row.get("avaliacoes")
            nota = row.get("nota")
            if int(row.get("quantidade_vendida") or 0) > sold:
                sold = int(row["quantidade_vendida"])
        except Exception as exc:
            logger.debug("enrich watchlist %s: %s", watch_id, exc)

    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    preco_ant = float(anterior.get("preco") or 0)
    status_ant = str(anterior.get("status") or "").strip().lower()

    alertas: list[str] = []
    if preco_ant > 0 and preco > 0:
        var = _pct_variacao(preco_ant, preco)
        if var >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            direcao = "caiu" if preco < preco_ant else "subiu"
            alertas.append(
                f"[watchlist] {nome}: preço {direcao} de R$ {preco_ant:.2f} "
                f"para R$ {preco:.2f} ({var:.1f}%) — `{watch_id}`"
            )

    if status_ant and status and status_ant != status:
        alertas.append(
            f"[watchlist] {nome}: status `{status_ant}` → `{status}` — `{watch_id}`"
        )

    if (
        _pode_alertar_gap_preco(origem_preco)
        and meu_preco > 0
        and preco > 0
        and meu_preco > preco
    ):
        diff = (meu_preco - preco) / preco * 100.0
        if diff >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            alertas.append(
                f"[watchlist] {nome}: {rotulo} R$ {meu_preco:.2f} está {diff:.1f}% acima "
                f"do rival R$ {preco:.2f} (`{watch_id}`)"
            )

    leituras_ant = _leituras_recentes(anterior, limite=4)
    leituras_ant.append({"preco": preco, "status": status, "ts": datetime.now(timezone.utc).isoformat()})
    # Compatível com _leituras_recentes (menor_preco) para classificação futura
    for L in leituras_ant:
        if "menor_preco" not in L and L.get("preco") is not None:
            L["menor_preco"] = L["preco"]

    historico[eid] = {
        "tipo": "item",
        "item_id_concorrente": watch_id,
        "preco": preco,
        "menor_preco": preco,
        "status": status,
        "titulo": titulo,
        "sold_quantity": sold,
        "avaliacoes": avaliacoes,
        "nota": nota,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "leituras": leituras_ant[-5:],
    }

    _tags = [
        f"produto:{eid}",
        f"watch:{watch_id}",
        "tipo:item",
        f"origem_preco:{origem_preco}",
    ]
    if preco > 0:
        gauge("mercado.menor_preco_concorrente", preco, tags=_tags)
    gauge("mercado.total_concorrentes", 1.0, tags=_tags)
    if alertas:
        incrementar("mercado.alertas_preco", float(len(alertas)), tags=_tags)

    return {
        "id": eid,
        "ok": True,
        "tipo": "item",
        "nome": nome,
        "item_id_concorrente": watch_id,
        "titulo": titulo,
        "preco": preco,
        "menor_preco": preco,
        "status": status,
        "sold_quantity": sold,
        "avaliacoes": avaliacoes,
        "nota": nota,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "alertas": alertas,
        "permalink": pub.get("permalink"),
    }


def _monitorar_entrada(
    entrada: dict,
    historico: dict[str, Any],
    *,
    enriquecer_metricas: bool = True,
) -> dict[str, Any]:
    tipo = str(entrada.get("tipo") or "").lower()
    if tipo == "loja":
        return _monitorar_loja(entrada, historico)
    if tipo == "item":
        return _monitorar_item_watchlist(
            entrada, historico, enriquecer_metricas=enriquecer_metricas
        )

    eid = str(entrada.get("id") or "").strip()
    nome = str(entrada.get("nome") or eid)
    termo = str(entrada.get("termo_busca") or "").strip()
    meu_preco, origem_preco = _resolver_preco_referencia(entrada)
    rotulo = _rotulo_preco_referencia(origem_preco)
    limite = int(entrada.get("limite_resultados") or 10)

    if not termo:
        return {"id": eid, "ok": False, "erro": "termo_busca vazio", "alertas": []}

    concorrentes = ml_client.buscar_concorrentes_por_termo(termo, limite=limite)
    try:
        from integracoes.ml.busca_termo_ml import filtrar_por_relevancia_titulo

        concorrentes = filtrar_por_relevancia_titulo(termo, concorrentes)
    except Exception as exc:
        logger.debug("filtro relevância termo: %s", exc)
    # Filtro opcional: só anúncios de um seller específico no termo
    seller_filtro = str(entrada.get("seller_id") or "").strip()
    if seller_filtro:
        concorrentes = [
            c for c in concorrentes if str(c.get("seller_id") or "") == seller_filtro
        ]
    if enriquecer_metricas:
        try:
            from integracoes.ml.analise_anuncio_concorrente import enriquecer_lista

            concorrentes = enriquecer_lista(concorrentes, limite=min(5, max(1, limite)))
        except Exception as exc:
            logger.warning("enriquecer métricas termo %r: %s", termo[:40], exc)
    menor = _menor_preco(concorrentes)
    anterior = historico.get(eid) if isinstance(historico.get(eid), dict) else {}
    menor_ant = float(anterior.get("menor_preco") or 0)

    alertas: list[str] = []
    if (
        _pode_alertar_gap_preco(origem_preco)
        and menor > 0
        and meu_preco > menor
    ):
        diff = (meu_preco - menor) / menor * 100.0
        if diff >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            alertas.append(
                f"{nome}: {rotulo} R$ {meu_preco:.2f} está {diff:.1f}% acima do menor "
                f"concorrente (R$ {menor:.2f}) no termo '{termo}'."
            )

    if menor_ant > 0 and menor > 0:
        var = _pct_variacao(menor_ant, menor)
        if var >= MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT:
            direcao = "caiu" if menor < menor_ant else "subiu"
            linha = (
                f"{nome}: menor preço do termo '{termo}' {direcao} de R$ {menor_ant:.2f} "
                f"para R$ {menor:.2f} ({var:.1f}%)."
            )
            classificacao = _classificar_variacao_preco(eid, nome, termo, menor, historico)
            if classificacao:
                linha += f" [{classificacao}]"
            alertas.append(linha)

    leituras_ant = _leituras_recentes(anterior, limite=4)
    leituras_ant.append(
        {"menor_preco": menor, "ts": datetime.now(timezone.utc).isoformat()}
    )
    historico[eid] = {
        "menor_preco": menor,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "total_concorrentes": len(concorrentes),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "leituras": leituras_ant[-5:],
    }

    # ── Datadog ──────────────────────────────────────────────────────────
    # tag `produto` usa o `id` do JSON (ex.: "kit3-mimo-carmed") para
    # aparecer como facet no Metrics Explorer e facilitar filtrar por SKU.
    _tags = [f"produto:{eid}", f"origem_preco:{origem_preco}"]
    if meu_preco > 0:
        gauge("mercado.meu_preco", meu_preco, tags=_tags)
    if menor > 0:
        gauge("mercado.menor_preco_concorrente", menor, tags=_tags)
    if meu_preco > 0 and menor > 0:
        gap_pct = (meu_preco - menor) / menor * 100.0
        gauge("mercado.gap_preco_pct", gap_pct, tags=_tags)
    gauge("mercado.total_concorrentes", float(len(concorrentes)), tags=_tags)
    if alertas:
        incrementar("mercado.alertas_preco", float(len(alertas)), tags=_tags)
    # ─────────────────────────────────────────────────────────────────────

    return {
        "id": eid,
        "ok": True,
        "tipo": "termo",
        "nome": nome,
        "sku": str(entrada.get("sku") or "").strip(),
        "termo_busca": termo,
        "meu_preco": meu_preco,
        "origem_preco": origem_preco,
        "menor_preco": menor,
        "total_concorrentes": len(concorrentes),
        "concorrentes_amostra": concorrentes[:5],
        "anuncios": concorrentes,
        "alertas": alertas,
    }


def executar(
    enviar_alerta: bool = True,
    *,
    enriquecer_metricas: bool = True,
) -> dict[str, Any]:
    """Monitora todos os itens ativos da lista. Nunca lança exceção."""
    try:
        lista = _carregar_lista()
        historico = _carregar_historico()
        resultados: list[dict[str, Any]] = []
        alertas_todos: list[str] = []

        for entrada in lista:
            if not isinstance(entrada, dict) or not entrada.get("ativo"):
                continue
            resultado = _monitorar_entrada(
                entrada, historico, enriquecer_metricas=enriquecer_metricas
            )
            resultados.append(resultado)
            alertas_todos.extend(resultado.get("alertas") or [])

        _salvar_historico(historico)

        amostra: list[dict[str, Any]] = []
        for r in resultados:
            amostra.extend(r.get("anuncios") or r.get("concorrentes_amostra") or [])

        try:
            from integracoes.esmaltes.metricas_batalha_impala import processar_e_persistir

            # Amostra vazia (403/busca cega) ainda precisa do radar: senão
            # os gauges de guerra ficam congelados no último valor.
            processar_e_persistir(amostra, origem="monitor_concorrentes")
        except Exception as exc:
            logger.warning("batalha Impala apos concorrentes: %s", exc)

        try:
            from integracoes.esmaltes.novos_kits_impala import processar as processar_novos_kits

            novos = processar_novos_kits(amostra, persistir=True, enviar_alerta=enviar_alerta)
            alertas_todos.extend(novos.get("alertas") or [])
        except Exception as exc:
            logger.warning("novos kits Impala apos concorrentes: %s", exc)

        enviado = False
        if enviar_alerta and alertas_todos:
            from core.telegram_explicacao import cabecalho_agente

            watch = [a for a in alertas_todos if "[watchlist]" in a]
            novos_kits = [a for a in alertas_todos if "[novos-kits-impala]" in a]
            demais = [
                a
                for a in alertas_todos
                if "[watchlist]" not in a and "[novos-kits-impala]" not in a
            ]
            blocos = [
                cabecalho_agente("monitor_concorrentes", "🔎 *Monitor concorrentes ML*"),
                "",
            ]
            if novos_kits:
                blocos.append("*Novos kits Impala no ML*")
                blocos.extend(f"• {a}" for a in novos_kits)
                blocos.append("")
            if watch:
                blocos.append("*Watchlist MLB (alta confiança — preço/status)*")
                blocos.extend(f"• {a}" for a in watch)
                blocos.append("")
            if demais:
                blocos.append("*Radar por termo / loja*")
                blocos.extend(f"• {a}" for a in demais)
            msg = "\n".join(blocos).strip()
            enviado = bool(alertar_gestor(msg, agente_id="monitor_concorrentes"))

        payload = {
            "ok": True,
            "total_monitorados": len(resultados),
            "total_alertas": len(alertas_todos),
            "alertas": alertas_todos,
            "resultados": resultados,
            "enviado": enviado,
        }
        logger.info(
            "Monitor concorrentes: %s itens, %s alertas, enviado=%s",
            len(resultados),
            len(alertas_todos),
            enviado,
        )
        return payload
    except Exception as exc:
        logger.error("Monitor concorrentes erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def main() -> int:
    logger.info("=== Monitor concorrentes ML ===")
    resultado = executar(enviar_alerta=True)
    if not resultado.get("ok"):
        logger.error("Falha: %s", resultado.get("erro"))
        return 1
    if resultado.get("alertas"):
        for linha in resultado["alertas"]:
            print(f"[ALERTA] {linha}")
    else:
        print(f"[OK] {resultado.get('total_monitorados', 0)} item(ns) monitorado(s), sem alertas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
