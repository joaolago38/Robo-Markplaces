"""
core/claude_client.py
Cliente centralizado para o Claude (Anthropic).
Nunca lança exceção — erro retorna string de fallback.
"""
import logging
import time

from core.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_ECONOMICO,
    CLAUDE_MODELO,
    CLAUDE_MODELO_RAPIDO,
)
from core.datadog_metrics import gauge, incrementar
from core.http_client import request

logger = logging.getLogger("claude")
API_URL = "https://api.anthropic.com/v1/messages"
# Preferir CLAUDE_MODELO / CLAUDE_MODELO_RAPIDO no .env; CLAUDE_ECONOMICO=1 força o barato.
MODELO = CLAUDE_MODELO
MODELO_RAPIDO = CLAUDE_MODELO_RAPIDO


def _modelo_efetivo(modelo: str | None = None, *, forcar_modelo: bool = False) -> str:
    """
    Resolve o modelo da chamada.
    CLAUDE_ECONOMICO=1 força Haiku — exceto quando forcar_modelo=True
    (escalonamento de vendas ML via claude_roteador).
    """
    escolhido = (modelo or "").strip()
    if forcar_modelo and escolhido:
        return escolhido
    if CLAUDE_ECONOMICO:
        return MODELO_RAPIDO
    return escolhido or MODELO


def _status_http_erro(exc: Exception) -> int | None:
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None):
        return int(resp.status_code)
    texto = str(exc).lower()
    if "401" in texto and "unauthorized" in texto:
        return 401
    if "403" in texto and "forbidden" in texto:
        return 403
    return None


def _log_erro_claude(exc: Exception, *, contexto: str) -> None:
    from core.log_opcional import erro_opcional, log_erros_claude_ativos

    status = _status_http_erro(exc)
    if status in (401, 403):
        logger.warning(
            "Claude indisponível — %s (HTTP %s — configure ANTHROPIC_API_KEY)",
            contexto,
            status,
        )
        return
    erro_opcional(
        logger,
        log_erros_claude_ativos(),
        "Claude erro — %s: %s",
        contexto,
        exc,
        flag_hint="LOG_ERROS_CLAUDE",
        extra={"error_kind": type(exc).__name__, "error_message": str(exc)},
    )


SYSTEM = """
Você é o agente de vendas de uma distribuidora de esmaltes para manicures.
Tom: profissional, próximo, linguagem de salão de beleza.
Use sempre dados reais do contexto fornecido.
Nunca invente informações. Nunca prometa o que não pode cumprir.
"""

# Contexto JSON/texto curto demais → não gasta Claude (cai assertividade com falha/vazio).
CONTEXTO_MINIMO_CHARS = 80


def contexto_suficiente(contexto: str | None, *, minimo: int = CONTEXTO_MINIMO_CHARS) -> bool:
    return len((contexto or "").strip()) >= int(minimo)


def _extrair_tokens_usage(uso: dict | None) -> tuple[int, int]:
    """Soma input (incl. cache) + output do usage Anthropic."""
    if not isinstance(uso, dict):
        return 0, 0
    tin = int(uso.get("input_tokens") or 0)
    tin += int(uso.get("cache_creation_input_tokens") or 0)
    tin += int(uso.get("cache_read_input_tokens") or 0)
    tout = int(uso.get("output_tokens") or 0)
    return tin, tout


def mlb_invalido(item_id: str | None) -> bool:
    """True se item_id vazio, placeholder MLB_PREENCHER ou não começa com MLB."""
    u = str(item_id or "").strip().upper().replace("-", "")
    return (not u) or u in {"MLB_PREENCHER", "MLBPREENCHER"} or not u.startswith("MLB")


def perguntar(
    prompt: str,
    max_tokens: int = 500,
    contexto: str | None = None,
    system: str | None = None,
    imagens: list[str] | None = None,
    modelo: str | None = None,
    *,
    forcar_modelo: bool = False,
    origem: str | None = None,
    exigir_contexto: bool = False,
    forcar_chamada: bool = False,
    temperature: float | None = None,
) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY não configurada."
    if exigir_contexto and not contexto_suficiente(contexto):
        logger.info("Claude pulado: contexto insuficiente (origem=%s)", origem or "?")
        return "⚠️ Claude pulado: contexto insuficiente."
    modelo_efetivo = _modelo_efetivo(modelo, forcar_modelo=forcar_modelo)
    try:
        from core.claude_orcamento import pode_chamar, registrar_uso

        ok_orc, motivo_orc = pode_chamar(origem=origem, forcar=forcar_chamada)
        if not ok_orc:
            logger.warning("Claude bloqueado por orçamento: %s", motivo_orc)
            registrar_uso(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo="perguntar",
                resultado="bloqueado",
                origem=origem,
            )
            return f"⚠️ Claude pausado: {motivo_orc}"
    except Exception as exc:
        # Fail-closed: sem gate confiável não chama a API (evita gastar USD).
        logger.warning("Gate Claude falhou — bloqueando: %s", exc)
        return f"⚠️ Claude pausado: gate_indisponivel ({exc})"

    mensagem_texto = f"{contexto}\n\n{prompt}" if contexto else prompt

    content: list[dict] = []
    for url in (imagens or [])[:5]:
        url = (url or "").strip()
        if not url:
            continue
        content.append(
            {
                "type": "image",
                "source": {"type": "url", "url": url},
            }
        )
    content.append({"type": "text", "text": mensagem_texto})

    _tags = [f"modelo:{modelo_efetivo}", f"com_imagem:{bool(imagens)}"]
    inicio = time.monotonic()
    payload: dict = {
        "model": modelo_efetivo,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": system or SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": content}],
    }
    if temperature is not None:
        payload["temperature"] = max(0.0, min(1.0, float(temperature)))
    try:
        r = request("POST", API_URL, headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        }, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        duracao_ms = (time.monotonic() - inicio) * 1000
        gauge("ia.latencia_ms", duracao_ms, tags=_tags)
        uso = data.get("usage") or {}
        tin, tout = _extrair_tokens_usage(uso)
        if uso:
            incrementar("ia.tokens_entrada", tin, tags=_tags)
            incrementar("ia.tokens_saida", tout, tags=_tags)
        conteudo_resposta = data.get("content", [])
        if not conteudo_resposta:
            incrementar("ia.resposta_vazia", tags=_tags)
            logger.error("Claude sem conteúdo na resposta: %s", data)
            texto = "⚠️ Erro na IA: resposta vazia."
        else:
            texto = conteudo_resposta[0].get("text", "").strip() or "⚠️ Erro na IA: resposta sem texto."
        try:
            from core.claude_orcamento import classificar_resultado_texto as _cls
            from core.claude_orcamento import registrar_uso as _reg

            resultado = _cls(texto)
            # Texto útil conta como ok mesmo se usage vier sem tokens (API/cache).
            _reg(
                modelo=modelo_efetivo,
                input_tokens=tin,
                output_tokens=tout,
                tipo="perguntar",
                resultado=resultado,
                origem=origem,
            )
        except Exception:
            pass
        return texto
    except ValueError as e:
        incrementar("ia.erro", tags=[*_tags, "tipo:json_invalido"])
        logger.error(
            "Claude retornou JSON inválido: %s", e,
            extra={"error_kind": type(e).__name__, "error_message": str(e)},
        )
        try:
            from core.claude_orcamento import registrar_uso as _reg

            _reg(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo="perguntar",
                resultado="falha",
                origem=origem,
            )
        except Exception:
            pass
        return "⚠️ Erro na IA: resposta inválida."
    except Exception as e:
        incrementar("ia.erro", tags=[*_tags, "tipo:comunicacao"])
        _log_erro_claude(e, contexto="texto livre")
        try:
            from core.claude_orcamento import registrar_uso as _reg

            _reg(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo="perguntar",
                resultado="falha",
                origem=origem,
            )
        except Exception:
            pass
        return "⚠️ Erro na IA: falha de comunicação com o provedor."


def perguntar_estruturado(
    prompt: str,
    schema: dict,
    tool_name: str,
    *,
    max_tokens: int = 600,
    contexto: str | None = None,
    system: str | None = None,
    modelo: str | None = None,
    forcar_modelo: bool = False,
    origem: str | None = None,
    exigir_contexto: bool = False,
) -> dict | None:
    """
    Como `perguntar`, mas força a resposta a seguir `schema` (JSON Schema
    de um único tool) via tool use, em vez de texto livre. Retorna o dict
    já parseado, ou None em caso de falha (nunca lança exceção).
    Use quando o consumidor da resposta precisa de campos previsíveis
    (ex.: lista de sugestões) em vez de um texto pra exibir direto.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("perguntar_estruturado sem ANTHROPIC_API_KEY.")
        return None
    if exigir_contexto and not contexto_suficiente(contexto):
        logger.info("Claude estruturado pulado: contexto insuficiente (origem=%s)", origem or "?")
        return None
    modelo_efetivo = _modelo_efetivo(modelo, forcar_modelo=forcar_modelo)
    try:
        from core.claude_orcamento import pode_chamar, registrar_uso

        ok_orc, motivo_orc = pode_chamar()
        if not ok_orc:
            logger.warning("Claude estruturado bloqueado: %s", motivo_orc)
            registrar_uso(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo=f"estruturado:{tool_name}",
                resultado="bloqueado",
                origem=origem,
            )
            return None
    except Exception as exc:
        logger.warning("Gate Claude estruturado falhou — bloqueando: %s", exc)
        return None
    mensagem_texto = f"{contexto}\n\n{prompt}" if contexto else prompt
    _tags = [f"modelo:{modelo_efetivo}", f"tool:{tool_name}"]
    inicio = time.monotonic()
    try:
        r = request("POST", API_URL, headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        }, json={
            "model": modelo_efetivo,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": system or SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": mensagem_texto}],
            "tools": [
                {
                    "name": tool_name,
                    "description": f"Preenche a estrutura de saída para {tool_name}.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        duracao_ms = (time.monotonic() - inicio) * 1000
        gauge("ia.latencia_ms", duracao_ms, tags=_tags)
        uso = data.get("usage") or {}
        tin, tout = _extrair_tokens_usage(uso)
        if uso:
            incrementar("ia.tokens_entrada", tin, tags=_tags)
            incrementar("ia.tokens_saida", tout, tags=_tags)
        resultado_final = "falha"
        payload_out = None
        for bloco in data.get("content", []):
            if bloco.get("type") == "tool_use" and bloco.get("name") == tool_name:
                payload_out = bloco.get("input") or {}
                # Payload estruturado útil = ok (não castigar por usage sem tokens).
                resultado_final = "ok" if payload_out else "vazio"
                break
        if payload_out is None:
            incrementar("ia.resposta_vazia", tags=_tags)
            logger.error("Claude não retornou tool_use esperado (%s): %s", tool_name, data)
            resultado_final = "falha"
        try:
            from core.claude_orcamento import registrar_uso

            registrar_uso(
                modelo=modelo_efetivo,
                input_tokens=tin,
                output_tokens=tout,
                tipo=f"estruturado:{tool_name}",
                resultado=resultado_final,
                origem=origem,
            )
        except Exception:
            pass
        return payload_out
    except Exception as e:
        incrementar("ia.erro", tags=[*_tags, "tipo:estruturado"])
        _log_erro_claude(e, contexto=f"estruturado tool={tool_name}")
        try:
            from core.claude_orcamento import registrar_uso

            registrar_uso(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo=f"estruturado:{tool_name}",
                resultado="falha",
                origem=origem,
            )
        except Exception:
            pass
        return None

def responder_chat(
    pergunta: str,
    produto: dict,
    canal: str,
    *,
    sinal_ads: dict | None = None,
    oferta_ctx: dict | None = None,
) -> str:
    from core.chat_seguro_ml import (
        MSG_CONSULTAR_ANUNCIO,
        MSG_INDISPONIVEL,
        MSG_SEM_DESCONTO,
        prompt_sistema_chat,
        sanitizar_resposta_chat_ml,
    )

    pergunta_txt = (pergunta or "").strip()
    if len(pergunta_txt) < 3:
        return ""

    if not produto:
        return "Vou confirmar os detalhes e já te respondo"

    estoque = int(produto.get("estoque", produto.get("estoque_total", 0)) or 0)
    if estoque <= 0:
        return MSG_INDISPONIVEL

    try:
        preco = float(produto.get("preco") or 0)
    except (TypeError, ValueError):
        preco = 0.0

    from core.claude_analise_vendas import analisar_oportunidade_ml
    from core.claude_roteador import resolver_modelo_vendas
    from core.config import CLAUDE_ANALISE_FURA_TEMPLATE

    if sinal_ads is None:
        try:
            from core.contexto_fechamento_ml import carregar_contexto_fechamento_ml

            ctx_f = carregar_contexto_fechamento_ml()
            sinal_ads = ctx_f.get("sinal_ads")
            if oferta_ctx is None:
                oferta_ctx = ctx_f.get("oferta")
        except Exception:
            pass

    analise = analisar_oportunidade_ml(
        texto=pergunta_txt,
        canal=canal,
        preco_produto=preco,
        estoque=estoque,
        proposito="chat_ml",
        sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
    )
    rota = resolver_modelo_vendas(
        proposito="chat_ml",
        canal=canal,
        texto=pergunta_txt,
        preco_produto=preco,
        estoque=estoque,
        sinal_ads=sinal_ads if isinstance(sinal_ads, dict) else None,
        analise=analise,
    )
    # Se calor alto → pula templates e sobe IA (Sonnet)
    usar_ia_direto = bool(
        CLAUDE_ANALISE_FURA_TEMPLATE and analise.get("deve_aumentar_ia")
    )

    pergunta_lower = pergunta_txt.lower()
    nome = str(produto.get("nome", "")).lower()
    descricao = str(produto.get("descricao", "")).lower()
    contexto = f"{nome} {descricao}"

    lista_cores = (
        "Preto, Vinho, Beterraba, Branco, Nude Clássico, Inocense, Tomate, Gatinha, Zaz, "
        "Patins, Le Rose, Donata, Amante, Atração, Vibrações, Fascinação, Boneca de Luxo, Dádiva, "
        "Serena, Café Café, Coffee, Sutileza, Lua, Sonho, Polar, Dengo, Caricia, Buquê"
    )

    if not usar_ia_direto:
        if "cor" in pergunta_lower and any(term in pergunta_lower for term in ["qual", "quais", "tem", "kit"]):
            cores = produto.get("cores")
            if isinstance(cores, list) and cores:
                return (
                    f"As cores deste kit são: {', '.join(str(c) for c in cores)}. "
                    "Todas as cores estão identificadas no anúncio. Posso confirmar mais detalhes se precisar!"
                )
        if "escolher" in pergunta_lower or "escolho" in pergunta_lower or "montar" in pergunta_lower:
            return (
                "Pode sim! Deixe no campo de mensagem quais cores prefere da nossa lista. "
                f"Vou separar exatamente o que você escolher. Lista completa: {lista_cores}."
            )
        if "foto" in pergunta_lower or "real" in pergunta_lower:
            return "Sim, as fotos mostram as cores reais. Cada frasco está identificado pelo nome Impala. O que você vê é o que recebe."
        # Frete/prazo/CEP: nunca inventar — orientar anúncio
        if any(k in pergunta_lower for k in ("entrega", "cep", "full", "frete", "prazo")):
            return MSG_CONSULTAR_ANUNCIO
        # Atacado/desconto: sem preço especial inventado
        if any(k in pergunta_lower for k in ("atacado", "revendedor", "desconto", "promo")):
            return MSG_SEM_DESCONTO
        if "profissional" in pergunta_lower:
            return (
                "Sim, usado por manicures profissionais. "
                "As cores do kit estão na foto e na descrição do anúncio."
            )
        if "alicate" in pergunta_lower or "mundial 777" in contexto:
            return "Alicate Mundial 777 em aço inox cirúrgico. Pode ser autoclavado para uso em clínicas e salões. Corte preciso sem necessidade de afiar."
        if "validade" in pergunta_lower:
            # Só afirma se estiver na descrição do produto
            if "validade" in descricao or "meses" in descricao:
                return str(produto.get("descricao") or "")[:280]
            return "A validade e o lote vêm impressos em cada frasco. Confira também na descrição do anúncio."

    oferta_txt = ""
    canal_norm = str(canal or "mercadolivre").strip().lower()
    if (
        canal_norm in {"", "mercadolivre", "ml"}
        and isinstance(oferta_ctx, dict)
        and oferta_ctx.get("link_ml")
    ):
        oferta_txt = (
            f"Oferta ativa (captação Meta→ML): {oferta_ctx.get('campanha_nome') or 'kit'} "
            f"| link {oferta_ctx.get('link_ml')} "
            f"| sku {oferta_ctx.get('sku') or 'n/d'}"
        )

    ctx = f"""
Canal: {canal.upper()}
Produto: {produto.get('nome','N/D')}
Preço (único permitido citar): R$ {preco:.2f}
Estoque informado: {estoque} unidades
Descrição: {produto.get('descricao','')}
Análise oportunidade: {analise.get('resumo')} (fatores: {', '.join(analise.get('fatores') or [])})
{oferta_txt}
Captação Meta (resumo): {analise.get('captacao_meta') or {}}

Pergunta do cliente: {pergunta_txt}

Responda de forma factual e neutra. Se couber, cite o link da oferta sem inventar preço/frete/prazo/desconto.
"""
    resposta = perguntar(
        ctx,
        max_tokens=320,
        modelo=rota["modelo"],
        forcar_modelo=bool(rota.get("forcar_modelo")),
        system=prompt_sistema_chat(canal_norm if canal_norm not in {"", "ml"} else "mercadolivre"),
        origem=f"{canal_norm or 'mercadolivre'}.chat.responder_chat",
    )
    if resposta.startswith("⚠️"):
        return "Já vou te responder melhor"
    return sanitizar_resposta_chat_ml(resposta, produto)


def gerar_post(produto: dict, canal: str) -> str:
    return perguntar(f"""
Crie um post promocional para {canal} sobre:
- Produto: {produto.get('nome')}
- Preço: R$ {produto.get('preco',0):.2f}
- Público: manicures profissionais
Máximo 150 palavras. Tom animado e profissional.
""", max_tokens=300)
