"""
agentes/ml/agente_otimizador_listing.py
Sugestões de título e descrição para anúncios do Mercado Livre via Claude.

Travas de escrita no ML:
- Descrição: NUNCA publicada (só preview no Telegram).
- Título: só se OTIMIZADOR_LISTING_APLICAR=1 E confirmação SIM no Telegram
  (fail-closed se token/gestor indisponível). Placeholder MLB_PREENCHER nunca aplica.
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
    "com base em dados reais (próprio anúncio, concorrentes e, quando houver, "
    "anúncios de bolsas/legado DESTA MESMA CONTA que já vendem). "
    "Use as bolsas só como REFERÊNCIA DE ESTRUTURA: substantivo de busca na frente, "
    "atributo, marca, público, preencher ~60 caracteres sem emoji. "
    "NUNCA copie palavras de bolsa/couro/mariart/shopper/transversal/carteira/"
    "scarpin/sapato para kit Impala. "
    "Nunca invente especificações, certificações ou características do produto "
    "que não estejam no contexto fornecido. Seja objetivo: até 3 sugestões de "
    "título alternativo (respeitando o limite de 60 caracteres do Mercado Livre) "
    "e um motivo curto para cada sugestão, baseado em padrões dos concorrentes "
    "e da copy que já impulsiona esta conta."
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


def _listar_itens_pre_publicacao(catalogo: list[dict]) -> list[dict]:
    """Kits Impala ativos no catálogo ainda sem MLB — título proposto."""
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
        if _item_id_valido(item_id):
            continue
        titulo = str(
            ml.get("titulo_anuncio")
            or produto.get("titulo_sugerido_ml")
            or produto.get("nome")
            or ""
        ).strip()
        if not titulo:
            continue
        itens.append(
            {
                "sku": str(produto.get("sku") or "").strip(),
                "nome": str(produto.get("nome") or "").strip(),
                "titulo": titulo,
                "preco": ml.get("preco") or produto.get("preco") or 0,
            }
        )
    return itens


def _montar_contexto(
    metricas: dict,
    concorrentes: list[dict],
    descricao_atual: str = "",
    referencia_copy: str = "",
) -> str:
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
    ref = str(referencia_copy or "").strip()
    if ref:
        linhas.extend(["", ref])
    return "\n".join(linhas)


def _ia_falhou(resposta: str) -> bool:
    return str(resposta or "").strip().startswith("⚠️")


def _primeira_sugestao(resposta: str) -> str:
    for linha in str(resposta or "").splitlines():
        texto = linha.strip()
        if texto and not texto.startswith("⚠️"):
            return texto[:200]
    return ""


def _referencia_copy_txt(referencia_copy: str = "") -> str:
    txt = str(referencia_copy or "").strip()
    if txt:
        return txt
    try:
        from integracoes.ml.referencia_copy_legado import bloco_contexto_salvo

        return bloco_contexto_salvo()
    except Exception:
        return ""


def _pedir_sugestoes_claude(
    *,
    contexto_txt: str,
    metricas: dict,
    origem: str,
) -> tuple[list[dict], str, str, bool, bool]:
    from core.claude_client import perguntar_estruturado
    from core.claude_contexto_ml import (
        enriquecer_contexto_claude,
        max_tokens_dosados,
        system_com_decisao,
    )

    ctx, dosagem = enriquecer_contexto_claude(
        {"anuncio_e_concorrentes": contexto_txt},
        produto={
            "titulo": metricas.get("titulo"),
            "preco": metricas.get("preco"),
            "quantidade_vendida": metricas.get("quantidade_vendida"),
        },
        proposito="otimizar_listing",
    )
    contexto = json.dumps(ctx, ensure_ascii=False, indent=2)
    sugestoes_estruturadas = perguntar_estruturado(
        (
            f"{_PROMPT_SUGESTOES}\n"
            f"Considere estado_ml (nivel={dosagem.get('nivel_ml')}) e "
            f"profundidade={dosagem.get('profundidade')}. "
            "Se houver referência de copy das bolsas da conta, aplique a estrutura "
            "sem copiar palavras de bolsa."
        ),
        _SCHEMA_SUGESTOES_TITULO,
        tool_name="registrar_sugestoes_titulo",
        max_tokens=max_tokens_dosados(600, dosagem),
        contexto=contexto,
        system=system_com_decisao(SYSTEM_OTIMIZADOR, dosagem),
        origem=origem,
        exigir_contexto=True,
    )
    lista_sugestoes = (sugestoes_estruturadas or {}).get("sugestoes") or []
    try:
        from integracoes.ml.referencia_copy_legado import titulo_tem_palavra_bolsa

        lista_sugestoes = [
            s
            for s in lista_sugestoes
            if isinstance(s, dict)
            and s.get("titulo")
            and not titulo_tem_palavra_bolsa(str(s.get("titulo") or ""))
        ]
    except Exception:
        lista_sugestoes = [
            s for s in lista_sugestoes if isinstance(s, dict) and s.get("titulo")
        ]
    sugestoes_titulo = "\n".join(
        f"{s.get('titulo', '')} — {s.get('motivo', '')}" for s in lista_sugestoes
    )
    sugestao_descricao = perguntar(
        (
            f"{_PROMPT_DESCRICAO}\n"
            f"ML={dosagem.get('nivel_ml')}; foque decisão de listing."
        ),
        max_tokens=max_tokens_dosados(900, dosagem),
        contexto=contexto,
        system=system_com_decisao(SYSTEM_DESCRICAO, dosagem),
        origem=origem,
        exigir_contexto=True,
    )
    ia_titulo = sugestoes_estruturadas is None
    ia_desc = _ia_falhou(sugestao_descricao)
    return lista_sugestoes, sugestoes_titulo, sugestao_descricao, ia_titulo, ia_desc


def analisar_item(item_id: str, *, referencia_copy: str = "") -> dict:
    """
    Busca métricas do próprio item + concorrentes, pede ao Claude sugestões
    de título, e retorna um dict estruturado. Nunca lança exceção.
    """
    item_id = str(item_id or "").strip()
    from core.claude_client import mlb_invalido

    if mlb_invalido(item_id):
        return {
            "ok": False,
            "erro": "item_id inválido ou placeholder (MLB_PREENCHER)",
            "pulado": True,
            "motivo": "sem_mlb_publicado",
        }

    try:
        metricas = ml_client.buscar_metricas_item(item_id) or {}
        if not metricas:
            return {"ok": False, "erro": f"item não encontrado ou indisponível: {item_id}"}

        descricao_atual = ml_client.buscar_descricao_item(item_id)
        concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        ref_txt = _referencia_copy_txt(referencia_copy)
        contexto_txt = _montar_contexto(
            metricas, concorrentes, descricao_atual, referencia_copy=ref_txt
        )
        _origem = "ml.agente_otimizador_listing"
        lista_sugestoes, sugestoes_titulo, sugestao_descricao, ia_titulo, ia_desc = (
            _pedir_sugestoes_claude(
                contexto_txt=contexto_txt,
                metricas=metricas,
                origem=_origem,
            )
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
            "usou_referencia_legado": bool(ref_txt),
        }
        if ia_titulo:
            resultado["ia_falhou"] = True
        if ia_desc:
            resultado["ia_falhou_descricao"] = True
        return resultado
    except Exception as exc:
        logger.error("analisar_item erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "erro": str(exc)}


def analisar_titulo_proposto(
    *,
    sku: str,
    nome: str,
    titulo: str,
    preco: Any = 0,
    referencia_copy: str = "",
) -> dict:
    """Claude no título de catálogo ainda sem MLB. Nunca publica."""
    titulo = str(titulo or "").strip()
    if not titulo:
        return {"ok": False, "erro": "título de catálogo vazio", "pre_publicacao": True}
    try:
        metricas = {
            "titulo": titulo,
            "preco": preco or 0,
            "estoque": 0,
            "visitas_7d": 0,
            "visitas_30d": 0,
            "status": "pre_publicacao",
        }
        ref_txt = _referencia_copy_txt(referencia_copy)
        contexto_txt = _montar_contexto(
            metricas,
            [],
            "",
            referencia_copy=ref_txt,
        )
        contexto_txt = (
            "ANÚNCIO AINDA SEM MLB — título proposto no catálogo Impala.\n"
            + contexto_txt
        )
        lista_sugestoes, sugestoes_titulo, sugestao_descricao, ia_titulo, ia_desc = (
            _pedir_sugestoes_claude(
                contexto_txt=contexto_txt,
                metricas=metricas,
                origem="ml.agente_otimizador_listing",
            )
        )
        resultado: dict[str, Any] = {
            "ok": True,
            "item_id": "",
            "sku": sku,
            "nome": nome,
            "pre_publicacao": True,
            "titulo_atual": titulo,
            "visitas_7d": 0,
            "sugestoes_texto": sugestoes_titulo,
            "sugestoes_estruturadas": lista_sugestoes,
            "sugestao_descricao": sugestao_descricao,
            "concorrentes_analisados": 1 if ref_txt else 0,
            "usou_referencia_legado": bool(ref_txt),
        }
        if ia_titulo:
            resultado["ia_falhou"] = True
        if ia_desc:
            resultado["ia_falhou_descricao"] = True
        return resultado
    except Exception as exc:
        logger.error("analisar_titulo_proposto sku=%s: %s", sku, exc)
        return {"ok": False, "erro": str(exc), "pre_publicacao": True}


def _montar_resumo_telegram(resultados: list[dict]) -> str:
    linhas = ["📝 Sugestões de título ML — Robo-Markplaces", ""]
    incluidos = 0
    for r in resultados:
        if not r.get("ok"):
            continue
        if int(r.get("concorrentes_analisados") or 0) < 1 and not r.get("usou_referencia_legado"):
            continue
        sugestao = _primeira_sugestao(str(r.get("sugestoes_texto") or ""))
        if not sugestao:
            continue
        incluidos += 1
        descricao_preview = str(r.get("sugestao_descricao") or "").strip().replace("\n", " ")[:120]
        rotulo = r.get("item_id") or r.get("sku") or "?"
        if r.get("pre_publicacao"):
            rotulo = f"[pré-pub] {r.get('sku') or rotulo}"
        linhas.append(f"• {rotulo} — {r.get('titulo_atual', '')[:50]}")
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


def _titulo_aplicavel(titulo: str, item_id: str) -> str | None:
    """Valida título sugerido antes de qualquer escrita no ML."""
    novo = str(titulo or "").strip()[:60]
    iid = str(item_id or "").strip()
    if not novo or not iid:
        return None
    if not _item_id_valido(iid):
        return None
    if "PREENCHER" in novo.upper():
        return None
    return novo


def analisar_catalogo(limite_itens: int = 10) -> dict:
    """
    Analisa até `limite_itens` anúncios ML ativos no catálogo e envia resumo ao gestor.
    Prioriza item_ids liberados pelo contrato de impulso (SKUs guerra).
    Escrita de título só com flag + SIM Telegram; descrição nunca é aplicada.
    Nunca lança exceção.
    """
    limite = max(1, int(limite_itens or 10))
    try:
        catalogo = _carregar_catalogo()
        itens_ml = _listar_itens_ml_ativos(catalogo)
        ref_txt = ""
        try:
            from integracoes.ml.referencia_copy_legado import (
                coletar_referencia_copy_legado,
                montar_bloco_contexto,
            )

            ref = coletar_referencia_copy_legado()
            ref_txt = montar_bloco_contexto(ref)
        except Exception as exc:
            logger.warning("referencia copy legado: %s", exc)

        # Prioriza guerra liberados + itens do funil (visitas sem conversão / listing)
        try:
            from integracoes.ml.acoes_funil_ml import listar_item_ids_prioridade_funil
            from integracoes.ml.contrato_impulso_ml import listar_item_ids_para_otimizacao, montar_contrato

            montar_contrato()
            prioridade = {i.upper() for i in listar_item_ids_para_otimizacao()}
            prioridade |= {i.upper() for i in listar_item_ids_prioridade_funil()}
            if prioridade:
                itens_ml = sorted(
                    itens_ml,
                    key=lambda e: (0 if str(e.get("item_id") or "").upper() in prioridade else 1),
                )
        except Exception as exc:
            logger.warning("contrato impulso listing: %s", exc)

        itens_ml = itens_ml[:limite]
        resultados: list[dict] = []

        for entrada in itens_ml:
            item_id = entrada["item_id"]
            resultado = analisar_item(item_id, referencia_copy=ref_txt)
            resultado["sku"] = entrada.get("sku", "")
            resultado["nome"] = entrada.get("nome", "")
            resultados.append(resultado)

        vagas = max(0, limite - len(itens_ml))
        if vagas:
            for entrada in _listar_itens_pre_publicacao(catalogo)[:vagas]:
                resultado = analisar_titulo_proposto(
                    sku=str(entrada.get("sku") or ""),
                    nome=str(entrada.get("nome") or ""),
                    titulo=str(entrada.get("titulo") or ""),
                    preco=entrada.get("preco") or 0,
                    referencia_copy=ref_txt,
                )
                resultados.append(resultado)

        from core.config import OTIMIZADOR_LISTING_APLICAR
        from core.notificador import alertar_gestor, perguntar_gestor_e_aguardar

        aplicados: list[str] = []
        recusados: list[str] = []
        modo = "sugestao"
        if OTIMIZADOR_LISTING_APLICAR:
            modo = "sugestao_com_confirmacao_telegram"
            for r in resultados:
                if not r.get("ok") or r.get("pre_publicacao"):
                    continue
                sug = r.get("sugestoes_estruturadas") or []
                if not sug or not isinstance(sug[0], dict):
                    continue
                item_id = str(r.get("item_id") or "")
                novo = _titulo_aplicavel(str(sug[0].get("titulo") or ""), item_id)
                if not novo:
                    continue
                ok_g = perguntar_gestor_e_aguardar(
                    f"⚠️ Aplicar novo título no ML? (Claude só sugeriu)\n\n"
                    f"Item: `{item_id}`\n"
                    f"Atual: {r.get('titulo_atual')}\n"
                    f"Novo: {novo}\n\n"
                    f"Motivo: {sug[0].get('motivo')}\n\n"
                    f"Descrição sugerida NÃO será publicada — só o título se você responder SIM.",
                    timeout_segundos=300,
                    contexto_decisao={
                        "decisao": "aplicar_titulo_listing",
                        "item_id": item_id,
                        "titulo_novo": novo,
                        "descricao_nunca_aplicada": True,
                    },
                )
                if not ok_g:
                    recusados.append(item_id)
                    r["titulo_recusado_gestor"] = True
                    continue
                if ml_client.atualizar_titulo_item(item_id, novo):
                    aplicados.append(item_id)
                    r["titulo_aplicado"] = novo
                else:
                    r["titulo_aplicacao_falhou"] = True

        msg = _montar_resumo_telegram(resultados)
        if OTIMIZADOR_LISTING_APLICAR:
            msg += (
                "\n\n_Modo:_ flag `OTIMIZADOR_LISTING_APLICAR=1` — "
                "título só com SIM no Telegram; descrição nunca publicada."
            )
        else:
            msg += (
                "\n\n_Modo:_ somente sugestão "
                "(defina `OTIMIZADOR_LISTING_APLICAR=1` + SIM no Telegram para publicar título)."
            )
        if aplicados:
            msg += f"\n\n✅ Títulos aplicados: {', '.join(aplicados)}"
        if recusados:
            msg += f"\n⏭ Sem confirmação / recusados: {', '.join(recusados)}"
        if ref_txt:
            msg += (
                "\n\n_Copy:_ estrutura das bolsas/legado desta conta "
                "(palavras de bolsa não entram no título Impala)."
            )
        alerta_enviado = bool(alertar_gestor(msg, agente_id="otimizador_listing"))

        return {
            "ok": True,
            "modo": modo,
            "aplicacao_habilitada": bool(OTIMIZADOR_LISTING_APLICAR),
            "descricao_nunca_aplicada": True,
            "usou_referencia_legado": bool(ref_txt),
            "total_analisados": len(resultados),
            "limite_itens": limite,
            "titulos_aplicados": aplicados,
            "titulos_recusados": recusados,
            "alerta_enviado": alerta_enviado,
            "resultados": resultados,
        }
    except Exception as exc:
        logger.error("analisar_catalogo erro: %s", exc)
        return {"ok": False, "erro": str(exc), "resultados": []}


def executar(limite_itens: int = 10) -> bool:
    """Entrada para cron/workflow — analisa catálogo e notifica gestor."""
    logger.info("=== Otimizador de listing ML ===")
    resultado = analisar_catalogo(limite_itens=limite_itens)
    if not resultado.get("ok"):
        logger.error("Otimizador listing falhou: %s", resultado.get("erro"))
        return False
    logger.info(
        "Otimizador listing: %s itens analisados, aplicados=%s, alerta=%s",
        resultado.get("total_analisados"),
        len(resultado.get("titulos_aplicados") or []),
        resultado.get("alerta_enviado"),
    )
    return True


def main() -> int:
    return 0 if executar() else 1


if __name__ == "__main__":
    raise SystemExit(main())
