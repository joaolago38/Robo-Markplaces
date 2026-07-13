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


def perguntar(
    prompt: str,
    max_tokens: int = 500,
    contexto: str | None = None,
    system: str | None = None,
    imagens: list[str] | None = None,
    modelo: str | None = None,
    *,
    forcar_modelo: bool = False,
) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY não configurada."
    modelo_efetivo = _modelo_efetivo(modelo, forcar_modelo=forcar_modelo)
    try:
        from core.claude_orcamento import pode_chamar, registrar_uso

        ok_orc, motivo_orc = pode_chamar()
        if not ok_orc:
            logger.warning("Claude bloqueado por orçamento: %s", motivo_orc)
            registrar_uso(
                modelo=modelo_efetivo,
                input_tokens=0,
                output_tokens=0,
                tipo="perguntar",
                resultado="bloqueado",
            )
            return f"⚠️ Claude pausado: {motivo_orc}"
    except Exception:
        pass

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
            "messages": [{"role": "user", "content": content}],
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        duracao_ms = (time.monotonic() - inicio) * 1000
        gauge("ia.latencia_ms", duracao_ms, tags=_tags)
        uso = data.get("usage") or {}
        tin = int(uso.get("input_tokens") or 0) if uso else 0
        tout = int(uso.get("output_tokens") or 0) if uso else 0
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

            _reg(
                modelo=modelo_efetivo,
                input_tokens=tin,
                output_tokens=tout,
                tipo="perguntar",
                resultado=_cls(texto),
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

            _reg(modelo=modelo_efetivo, input_tokens=0, output_tokens=0, tipo="perguntar", resultado="falha")
        except Exception:
            pass
        return "⚠️ Erro na IA: resposta inválida."
    except Exception as e:
        incrementar("ia.erro", tags=[*_tags, "tipo:comunicacao"])
        _log_erro_claude(e, contexto="texto livre")
        try:
            from core.claude_orcamento import registrar_uso as _reg

            _reg(modelo=modelo_efetivo, input_tokens=0, output_tokens=0, tipo="perguntar", resultado="falha")
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
            )
            return None
    except Exception:
        pass
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
        tin = int(uso.get("input_tokens") or 0) if uso else 0
        tout = int(uso.get("output_tokens") or 0) if uso else 0
        if uso:
            incrementar("ia.tokens_entrada", tin, tags=_tags)
            incrementar("ia.tokens_saida", tout, tags=_tags)
        resultado_final = "falha"
        payload_out = None
        for bloco in data.get("content", []):
            if bloco.get("type") == "tool_use" and bloco.get("name") == tool_name:
                payload_out = bloco.get("input") or {}
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
            )
        except Exception:
            pass
        return None

def responder_chat(pergunta: str, produto: dict, canal: str) -> str:
    pergunta_txt = (pergunta or "").strip()
    if len(pergunta_txt) < 3:
        return ""

    if not produto:
        return "Vou confirmar os detalhes e já te respondo"

    estoque = int(produto.get("estoque", produto.get("estoque_total", 0)) or 0)
    if estoque <= 0:
        return "Produto indisponível no momento"

    pergunta_lower = pergunta_txt.lower()
    nome = str(produto.get("nome", "")).lower()
    descricao = str(produto.get("descricao", "")).lower()
    contexto = f"{nome} {descricao}"

    lista_cores = (
        "Preto, Vinho, Beterraba, Branco, Nude Clássico, Inocense, Tomate, Gatinha, Zaz, "
        "Patins, Le Rose, Donata, Amante, Atração, Vibrações, Fascinação, Boneca de Luxo, Dádiva, "
        "Serena, Café Café, Coffee, Sutileza, Lua, Sonho, Polar, Dengo, Caricia, Buquê"
    )

    if "cor" in pergunta_lower and any(term in pergunta_lower for term in ["qual", "quais", "tem", "kit"]):
        cores = produto.get("cores")
        if isinstance(cores, list) and cores:
            return (
                f"As cores deste kit são: {', '.join(str(c) for c in cores)}. "
                "Todas com alta pigmentação e secagem rápida. Posso confirmar mais detalhes se precisar!"
            )
    if "escolher" in pergunta_lower or "escolho" in pergunta_lower or "montar" in pergunta_lower:
        return (
            "Pode sim! Deixe no campo de mensagem quais cores prefere da nossa lista. "
            f"Vou separar exatamente o que você escolher. Lista completa: {lista_cores}."
        )
    if "foto" in pergunta_lower or "real" in pergunta_lower:
        return "Sim, as fotos mostram as cores reais. Cada frasco está identificado pelo nome Impala. O que você vê é o que recebe."
    if "entrega" in pergunta_lower or "cep" in pergunta_lower or "full" in pergunta_lower:
        return "Com Full ativo chegará grátis amanhã para a maioria das regiões. Confirme seu CEP para verificar disponibilidade."
    if "atacado" in pergunta_lower or "revendedor" in pergunta_lower:
        return "Temos preço especial para kits a partir de 3 unidades. Qual quantidade você precisa? Posso calcular o melhor preço."
    if "profissional" in pergunta_lower:
        return "Sim, usado por manicures profissionais. Secagem rápida, alta pigmentação, sem tolueno, sem formaldeído."
    if "alicate" in pergunta_lower or "mundial 777" in contexto:
        return "Alicate Mundial 777 em aço inox cirúrgico. Pode ser autoclavado para uso em clínicas e salões. Corte preciso sem necessidade de afiar."
    if "validade" in pergunta_lower:
        return "Validade de 24 a 30 meses a partir da fabricação. Lote e validade impressos em cada frasco."

    ctx = f"""
Canal: {canal.upper()}
Produto: {produto.get('nome','N/D')}
Preço: R$ {produto.get('preco',0):.2f}
Estoque: {estoque} unidades
Descrição: {produto.get('descricao','')}

Pergunta do cliente: {pergunta_txt}
"""
    try:
        preco = float(produto.get("preco") or 0)
    except (TypeError, ValueError):
        preco = 0.0
    from core.claude_roteador import resolver_modelo_vendas

    rota = resolver_modelo_vendas(
        proposito="chat_ml",
        canal=canal,
        texto=pergunta_txt,
        preco_produto=preco,
    )
    resposta = perguntar(
        ctx,
        max_tokens=300,
        modelo=rota["modelo"],
        forcar_modelo=bool(rota.get("forcar_modelo")),
    )
    if resposta.startswith("⚠️"):
        return "Já vou te responder melhor"
    return resposta


def gerar_post(produto: dict, canal: str) -> str:
    return perguntar(f"""
Crie um post promocional para {canal} sobre:
- Produto: {produto.get('nome')}
- Preço: R$ {produto.get('preco',0):.2f}
- Público: manicures profissionais
Máximo 150 palavras. Tom animado e profissional.
""", max_tokens=300)
