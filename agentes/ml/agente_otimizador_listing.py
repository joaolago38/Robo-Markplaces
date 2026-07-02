"""
agentes/ml/agente_otimizador_listing.py
Sugestões de título e descrição para anúncios do Mercado Livre via Claude.
Somente leitura + recomendação — NÃO altera título nem descrição no ML.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.claude_client import perguntar
from integracoes.ml import ml_client

logger = logging.getLogger("agente_otimizador_listing")

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOGO_PATH = ROOT / "catalogo" / "produtos.json"

SYSTEM_OTIMIZADOR = (
    "Você analisa anúncios do Mercado Livre e sugere melhorias de título "
    "com base em dados reais fornecidos (próprio anúncio e concorrentes). "
    "Nunca invente especificações, certificações ou características do produto "
    "que não estejam no contexto fornecido. Seja objetivo: até 3 sugestões de "
    "título alternativo (respeitando o limite de 60 caracteres do Mercado Livre) "
    "e um motivo curto para cada sugestão, baseado em padrões observados nos "
    "concorrentes com mais vendas/visitas."
)

_PROMPT_SUGESTOES = (
    "Com base nos dados acima, sugira até 3 títulos alternativos (máx. 60 caracteres cada) "
    "e um motivo curto para cada um, observando padrões dos concorrentes com mais vendas."
)

_SCHEMA_SUGESTOES_TITULO = {
    "type": "object",
    "properties": {
        "sugestoes": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {
                        "type": "string",
                        "maxLength": 60,
                        "description": "Título alternativo, até 60 caracteres.",
                    },
                    "motivo": {
                        "type": "string",
                        "description": "Motivo curto baseado em padrões dos concorrentes.",
                    },
                },
                "required": ["titulo", "motivo"],
            },
        }
    },
    "required": ["sugestoes"],
}

SYSTEM_DESCRICAO = (
    "Você escreve descrições de anúncio para o Mercado Livre com base em dados reais "
    "fornecidos (próprio anúncio, descrição atual se houver, e concorrentes). "
    "Nunca invente especificações, certificações, prazos de garantia ou características "
    "do produto que não estejam no contexto fornecido — se faltar informação, escreva a "
    "descrição sem inventar esse dado, em vez de supor. Use linguagem direta, sem emojis, "
    "organizada em parágrafos curtos e, se fizer sentido, uma lista de bullet points com "
    "as principais características. Limite total: até 2000 caracteres."
)

_PROMPT_DESCRICAO = (
    "Com base nos dados acima (anúncio próprio, descrição atual se houver, e concorrentes), "
    "escreva uma sugestão de descrição completa para este anúncio. Se já existir uma "
    "descrição atual, aponte em 1 frase o que está sendo melhorado antes do texto novo."
)


def _item_id_valido(valor: Any) -> bool:
    texto = str(valor or "").strip()
    if not texto or "PREENCHER" in texto.upper():
        return False
    return True


def _carregar_catalogo() -> list[dict]:
    try:
        if not CATALOGO_PATH.is_file():
            logger.warning("catalogo/produtos.json não encontrado")
            return []
        with CATALOGO_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.error("Erro ao carregar catalogo: %s", exc)
        return []


def _listar_itens_ml_ativos(catalogo: list[dict]) -> list[dict]:
    itens: list[dict] = []
    for produto in catalogo:
        if not isinstance(produto, dict):
            continue
        canais = produto.get("canais") or {}
        if not isinstance(canais, dict):
            continue
        ml = canais.get("mercadolivre") or {}
        if not isinstance(ml, dict) or not ml.get("ativo"):
            continue
        item_id = ml.get("item_id")
        if not _item_id_valido(item_id):
            continue
        itens.append(
            {
                "sku": str(produto.get("sku") or "").strip(),
                "nome": str(produto.get("nome") or "").strip(),
                "item_id": str(item_id).strip(),
            }
        )
    return itens


def _montar_contexto(metricas: dict, concorrentes: list[dict], descricao_atual: str = "") -> str:
    linhas = [
        "=== ANÚNCIO PRÓPRIO ===",
        f"Título atual: {metricas.get('titulo', '')}",
        f"Preço: R$ {float(metricas.get('preco', 0) or 0):.2f}",
        f"Estoque: {metricas.get('estoque', 0)}",
        f"Visitas 7 dias: {metricas.get('visitas_7d', 0)}",
        f"Visitas 30 dias: {metricas.get('visitas_30d', 0)}",
        f"Status: {metricas.get('status', '')}",
        f"Descrição atual: {descricao_atual.strip() or '(sem descrição cadastrada)'}",
        "",
        "=== CONCORRENTES (mesmo catálogo) ===",
    ]
    if not concorrentes:
        linhas.append("(nenhum concorrente encontrado)")
    else:
        for i, c in enumerate(concorrentes, start=1):
            linhas.append(
                f"{i}. Título: {c.get('titulo', '')} | "
                f"Preço: R$ {float(c.get('preco', 0) or 0):.2f} | "
                f"Vendas: {c.get('quantidade_vendida', 0)} | "
                f"Frete grátis: {'sim' if c.get('frete_gratis') else 'não'} | "
                f"Condição: {c.get('condicao', '')}"
            )
    return "\n".join(linhas)


def _ia_falhou(resposta: str) -> bool:
    return str(resposta or "").strip().startswith("⚠️")


def _primeira_sugestao(resposta: str) -> str:
    for linha in str(resposta or "").splitlines():
        texto = linha.strip()
        if texto and not texto.startswith("⚠️"):
            return texto[:200]
    return ""


def analisar_item(item_id: str) -> dict:
    """
    Busca métricas do próprio item + concorrentes, pede ao Claude sugestões
    de título, e retorna um dict estruturado. Nunca lança exceção.
    """
    item_id = str(item_id or "").strip()
    if not item_id:
        return {"ok": False, "erro": "item_id inválido"}

    try:
        metricas = ml_client.buscar_metricas_item(item_id) or {}
        if not metricas:
            return {"ok": False, "erro": f"item não encontrado ou indisponível: {item_id}"}

        descricao_atual = ml_client.buscar_descricao_item(item_id)
        concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        contexto = _montar_contexto(metricas, concorrentes, descricao_atual)

        from core.claude_client import perguntar_estruturado

        sugestoes_estruturadas = perguntar_estruturado(
            _PROMPT_SUGESTOES,
            _SCHEMA_SUGESTOES_TITULO,
            tool_name="registrar_sugestoes_titulo",
            max_tokens=600,
            contexto=contexto,
            system=SYSTEM_OTIMIZADOR,
        )
        lista_sugestoes = (sugestoes_estruturadas or {}).get("sugestoes") or []
        sugestoes_titulo = "\n".join(
            f"{s.get('titulo', '')} — {s.get('motivo', '')}"
            for s in lista_sugestoes
            if isinstance(s, dict) and s.get("titulo")
        )
        sugestao_descricao = perguntar(
            _PROMPT_DESCRICAO,
            max_tokens=900,
            contexto=contexto,
            system=SYSTEM_DESCRICAO,
        )

        resultado: dict[str, Any] = {
            "ok": True,
            "item_id": item_id,
            "titulo_atual": metricas.get("titulo", ""),
            "descricao_atual": descricao_atual,
            "visitas_7d": metricas.get("visitas_7d", 0),
            "visitas_30d": metricas.get("visitas_30d", 0),
            "sugestoes_texto": sugestoes_titulo,
            "sugestoes_estruturadas": lista_sugestoes,
            "sugestao_descricao": sugestao_descricao,
            "concorrentes_analisados": len(concorrentes),
        }
        if sugestoes_estruturadas is None:
            resultado["ia_falhou"] = True
        if _ia_falhou(sugestao_descricao):
            resultado["ia_falhou_descricao"] = True
        return resultado
    except Exception as exc:
        logger.error("analisar_item erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "erro": str(exc)}


def _montar_resumo_telegram(resultados: list[dict]) -> str:
    linhas = ["📝 Sugestões de título ML — Robo-Markplaces", ""]
    incluidos = 0
    for r in resultados:
        if not r.get("ok"):
            continue
        if int(r.get("concorrentes_analisados") or 0) < 1:
            continue
        sugestao = _primeira_sugestao(str(r.get("sugestoes_texto") or ""))
        if not sugestao:
            continue
        incluidos += 1
        descricao_preview = str(r.get("sugestao_descricao") or "").strip().replace("\n", " ")[:120]
        linhas.append(f"• {r.get('item_id')} — {r.get('titulo_atual', '')[:50]}")
        linhas.append(f"  Visitas 7d: {r.get('visitas_7d', 0)}")
        linhas.append(f"  Sugestão título: {sugestao}")
        if descricao_preview:
            linhas.append(f"  Sugestão descrição (preview): {descricao_preview}...")
        linhas.append("")

    if incluidos == 0:
        return (
            "📝 Sugestões de título ML — Robo-Markplaces\n\n"
            "Nenhum item com concorrentes comparáveis nesta rodada."
        )
    return "\n".join(linhas).strip()


def analisar_catalogo(limite_itens: int = 10) -> dict:
    """
    Analisa até `limite_itens` anúncios ML ativos no catálogo e envia resumo ao gestor.
    Nunca lança exceção.
    """
    limite = max(1, int(limite_itens or 10))
    try:
        catalogo = _carregar_catalogo()
        itens_ml = _listar_itens_ml_ativos(catalogo)[:limite]
        resultados: list[dict] = []

        for entrada in itens_ml:
            item_id = entrada["item_id"]
            resultado = analisar_item(item_id)
            resultado["sku"] = entrada.get("sku", "")
            resultado["nome"] = entrada.get("nome", "")
            resultados.append(resultado)

        from core.notificador import alertar_gestor

        msg = _montar_resumo_telegram(resultados)
        alerta_enviado = bool(alertar_gestor(msg))

        return {
            "ok": True,
            "total_analisados": len(resultados),
            "limite_itens": limite,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("analisar_catalogo erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def executar(limite_itens: int = 10) -> bool:
    """Entrada para cron/workflow — analisa catálogo e notifica gestor."""
    logger.info("=== Otimizador de listing ML (somente sugestão) ===")
    resultado = analisar_catalogo(limite_itens=limite_itens)
    if not resultado.get("ok"):
        logger.error("Otimizador listing falhou: %s", resultado.get("erro"))
        return False
    logger.info(
        "Otimizador listing: %s itens analisados, alerta=%s",
        resultado.get("total_analisados"),
        resultado.get("alerta_enviado"),
    )
    return True


def main() -> int:
    return 0 if executar() else 1


if __name__ == "__main__":
    raise SystemExit(main())
