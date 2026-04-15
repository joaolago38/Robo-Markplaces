"""
core/claude_client.py
Cliente centralizado para o Claude (Anthropic).
Nunca lança exceção — erro retorna string de fallback.
"""
import logging
from core.config import ANTHROPIC_API_KEY
from core.http_client import request

logger = logging.getLogger("claude")
API_URL = "https://api.anthropic.com/v1/messages"
MODELO  = "claude-sonnet-4-20250514"

SYSTEM = """
Você é o agente de vendas de uma distribuidora de esmaltes para manicures.
Tom: profissional, próximo, linguagem de salão de beleza.
Use sempre dados reais do contexto fornecido.
Nunca invente informações. Nunca prometa o que não pode cumprir.
"""

def perguntar(prompt: str, max_tokens: int = 500) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY não configurada."
    try:
        r = request("POST", API_URL, headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={
            "model": MODELO,
            "max_tokens": max_tokens,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        if not content:
            logger.error("Claude sem conteúdo na resposta: %s", data)
            return "⚠️ Erro na IA: resposta vazia."
        return content[0].get("text", "").strip() or "⚠️ Erro na IA: resposta sem texto."
    except ValueError as e:
        logger.error("Claude retornou JSON inválido: %s", e)
        return "⚠️ Erro na IA: resposta inválida."
    except Exception as e:
        logger.error("Claude erro: %s", e)
        return "⚠️ Erro na IA: falha de comunicação com o provedor."

def responder_chat(pergunta: str, produto: dict, canal: str) -> str:
    ctx = f"""
Canal: {canal.upper()}
Produto: {produto.get('nome','N/D')}
Preço: R$ {produto.get('preco',0):.2f}
Estoque: {produto.get('estoque',0)} unidades
Descrição: {produto.get('descricao','')}

Pergunta do cliente: {pergunta}
"""
    return perguntar(ctx, max_tokens=400)

def gerar_post(produto: dict, canal: str) -> str:
    return perguntar(f"""
Crie um post promocional para {canal} sobre:
- Produto: {produto.get('nome')}
- Preço: R$ {produto.get('preco',0):.2f}
- Público: manicures profissionais
Máximo 150 palavras. Tom animado e profissional.
""", max_tokens=300)
