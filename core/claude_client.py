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
    resposta = perguntar(ctx, max_tokens=300)
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
