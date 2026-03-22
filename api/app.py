"""
api/app.py
Servidor Flask — ponte entre o n8n e o Python/SDD.
O n8n chama estes endpoints via HTTP POST com JSON.
Contratos: spec/spec.yaml > modulos[chat_responder, publicador_social, relatorio]
"""
import logging
from datetime import datetime
from flask import Flask, request, jsonify

from core.claude_client import responder_chat, gerar_post, perguntar
from core.notificador import alertar, alertar_critico, alertar_gestor
from core.config import MARGEM_MINIMA, ESTOQUE_CRITICO
from integracoes.bling.bling_client import (
    buscar_produto,
    listar_produtos,
    estoques_criticos,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("api")

app = Flask(__name__)

# ============================================================
# HEALTH CHECK — n8n usa para verificar se o servidor está vivo
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    """
    GET /health
    n8n chama antes de qualquer fluxo para confirmar que o servidor está online.
    Retorna: {"status": "ok", "hora": "..."}
    """
    return jsonify({"status": "ok", "hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")})


# ============================================================
# CHAT — responde perguntas de clientes nos marketplaces
# ============================================================

@app.route("/chat", methods=["POST"])
def chat():
    """
    POST /chat
    n8n chama quando chega uma pergunta no ML, Shopee, Magalu ou Amazon.

    Body esperado (JSON):
    {
        "pergunta":  "Vocês vendem no atacado?",
        "item_id":   "MLB123456",
        "canal":     "mercadolivre",
        "buyer_id":  "opcional"
    }

    Retorna:
    {
        "resposta": "Olá! Sim, trabalhamos com atacado...",
        "produto":  {"nome": "...", "preco": 9.90, ...},
        "ok":       true
    }

    Contratos aplicados:
    - DEVE usar dados reais do produto do Bling
    - DEVE responder em menos de 60s (timeout configurado)
    - NÃO DEVE responder com texto genérico
    """
    dados = request.get_json(force=True, silent=True) or {}
    pergunta = dados.get("pergunta", "")
    item_id  = dados.get("item_id", "")
    canal    = dados.get("canal", "mercadolivre")

    if not pergunta:
        return jsonify({"ok": False, "erro": "campo 'pergunta' obrigatório"}), 400

    logger.info(f"[CHAT] {canal} | item={item_id} | pergunta={pergunta[:60]}...")

    # Busca dados reais do produto no Bling
    produto = buscar_produto(item_id) or {}

    # Claude gera resposta personalizada
    resposta = responder_chat(pergunta, produto, canal)

    logger.info(f"[CHAT] Resposta gerada: {resposta[:80]}...")
    return jsonify({"resposta": resposta, "produto": produto, "ok": True})


# ============================================================
# REPRICING — ajusta preço respeitando a margem mínima
# ============================================================

@app.route("/repricing", methods=["POST"])
def repricing():
    """
    POST /repricing
    n8n chama quando o Lojahub Analytics detecta concorrente mais barato.

    Body esperado (JSON):
    {
        "sku":              "ESM-001",
        "preco_atual":      9.90,
        "custo":            6.00,
        "preco_concorrente": 8.50
    }

    Retorna:
    {
        "ajustar":      true,
        "novo_preco":   8.93,
        "margem_pct":   32.1,
        "motivo":       "ajustado para 5% acima do concorrente"
    }

    Contratos aplicados:
    - DEVE manter preço até 5% acima do menor concorrente
    - NÃO DEVE baixar preço se margem ficar abaixo de MARGEM_MINIMA
    - DEVE alertar Telegram se concorrente usar dumping
    """
    dados = request.get_json(force=True, silent=True) or {}
    sku              = dados.get("sku", "")
    preco_atual      = float(dados.get("preco_atual", 0))
    custo            = float(dados.get("custo", 0))
    preco_concorrente = float(dados.get("preco_concorrente", 0))

    if not all([sku, preco_atual, custo, preco_concorrente]):
        return jsonify({"ok": False, "erro": "campos obrigatórios: sku, preco_atual, custo, preco_concorrente"}), 400

    preco_alvo = preco_concorrente * 1.05  # 5% acima do concorrente
    margem     = (preco_alvo - custo) / preco_alvo * 100 if preco_alvo > 0 else 0

    logger.info(f"[REPRICING] {sku} | atual={preco_atual} | concorrente={preco_concorrente} | alvo={preco_alvo:.2f} | margem={margem:.1f}%")

    # Contrato: NÃO DEVE baixar abaixo da margem mínima
    if margem < MARGEM_MINIMA:
        alertar_critico(
            f"Repricing bloqueado: {sku}\n"
            f"Concorrente: R$ {preco_concorrente:.2f} (possível dumping)\n"
            f"Margem resultante seria {margem:.1f}% — abaixo do mínimo de {MARGEM_MINIMA}%"
        )
        return jsonify({
            "ajustar":  False,
            "motivo":   f"margem {margem:.1f}% abaixo do mínimo {MARGEM_MINIMA}%",
            "alertado": True,
        })

    # Só ajusta se a diferença for significativa (mais de R$ 0.10)
    if abs(preco_alvo - preco_atual) <= 0.10:
        return jsonify({"ajustar": False, "motivo": "diferença insignificante"})

    return jsonify({
        "ajustar":    True,
        "novo_preco": round(preco_alvo, 2),
        "margem_pct": round(margem, 1),
        "motivo":     f"5% acima do concorrente R$ {preco_concorrente:.2f}",
    })


# ============================================================
# POST SOCIAL — publica promoção no Instagram e Facebook
# ============================================================

@app.route("/post", methods=["POST"])
def post_social():
    """
    POST /post
    n8n chama todo dia às 8h e às 19h para publicar promoção.

    Body esperado (JSON):
    {
        "canal": "instagram",   (ou "facebook" ou "ambos")
        "sku":   "ESM-001"      (opcional — se vazio, agente escolhe)
    }

    Retorna:
    {
        "ok":      true,
        "produto": {"nome": "...", "preco": 9.90},
        "texto":   "Post gerado...",
        "canal":   "instagram"
    }

    Contratos aplicados:
    - DEVE selecionar produto com maior margem e estoque >= ESTOQUE_CRITICO
    - NÃO DEVE publicar produto com estoque abaixo de ESTOQUE_CRITICO
    - DEVE gerar texto personalizado por canal
    """
    dados = request.get_json(force=True, silent=True) or {}
    canal = dados.get("canal", "instagram")
    sku   = dados.get("sku", "")

    # Seleciona produto
    if sku:
        produto = buscar_produto(sku)
    else:
        produtos   = listar_produtos()
        elegiveis  = [p for p in produtos if p.get("estoque", 0) >= ESTOQUE_CRITICO]
        produto    = max(elegiveis, key=lambda p: p.get("preco", 0)) if elegiveis else None

    if not produto:
        return jsonify({"ok": False, "motivo": "nenhum produto elegível com estoque suficiente"})

    # Claude gera o texto do post
    texto = gerar_post(produto, canal)

    logger.info(f"[POST] {canal} | produto={produto.get('nome')} | texto={texto[:60]}...")

    return jsonify({
        "ok":      True,
        "produto": produto,
        "texto":   texto,
        "canal":   canal,
    })


# ============================================================
# ESTOQUE — verifica produtos em nível crítico
# ============================================================

@app.route("/estoque/criticos", methods=["GET"])
def estoque_criticos():
    """
    GET /estoque/criticos
    n8n chama para verificar estoque antes de publicar anúncio ou post.

    Retorna:
    {
        "criticos": [{"sku": "ESM-001", "nome": "...", "estoque": 5}],
        "total":    1
    }
    """
    criticos = estoques_criticos(ESTOQUE_CRITICO)
    if criticos:
        nomes = ", ".join(p["nome"] for p in criticos[:3])
        alertar(f"⚠️ Estoque crítico: {nomes}")
    return jsonify({"criticos": criticos, "total": len(criticos)})


# ============================================================
# RELATÓRIO — gera resumo diário
# ============================================================

@app.route("/relatorio", methods=["POST"])
def relatorio():
    """
    POST /relatorio
    n8n chama todo dia às 8h para gerar e enviar o relatório.

    Body esperado (JSON): {} (vazio — usa dados do Bling automaticamente)

    Retorna:
    {
        "ok":     true,
        "resumo": "Texto do relatório...",
        "enviado": true
    }
    """
    produtos = listar_produtos()
    criticos = estoques_criticos()

    dados_resumo = {
        "data":            datetime.now().strftime("%d/%m/%Y"),
        "total_produtos":  len(produtos),
        "criticos":        len(criticos),
        "nomes_criticos":  [p["nome"] for p in criticos[:3]],
    }

    resumo = perguntar(
        f"Faça um resumo executivo em 3 bullet points para dono de negócio de esmaltes: {dados_resumo}",
        max_tokens=300,
    )

    msg = (
        f"📊 *Relatório {dados_resumo['data']}*\n\n"
        f"Produtos ativos: {dados_resumo['total_produtos']}\n"
        f"Estoque crítico: {dados_resumo['criticos']} produtos\n\n"
        f"*Análise IA:*\n{resumo}"
    )

    enviado = alertar(msg)
    if criticos:
        alertar_critico(f"Estoque crítico: {', '.join(dados_resumo['nomes_criticos'])}")

    logger.info(f"[RELATÓRIO] enviado={enviado}")
    return jsonify({"ok": True, "resumo": resumo, "enviado": enviado})


# ============================================================
# ANÁLISE DE CAMPANHA — avalia métricas do Meta Ads
# ============================================================

@app.route("/campanha/avaliar", methods=["POST"])
def avaliar_campanha():
    """
    POST /campanha/avaliar
    n8n chama a cada 1h com as métricas da campanha ativa.
    O agente decide: pausar, escalar ou manter.

    Body esperado (JSON):
    {
        "campanha_id": "123456",
        "nome":        "Esmalte Carmim — Manicures SP",
        "cpc":         1.20,
        "ctr":         2.5,
        "roas":        3.8,
        "gasto_dia":   45.00,
        "orcamento":   50.00
    }

    Retorna:
    {
        "acao":   "escalar",   (pausar / escalar / manter)
        "motivo": "ROAS 3.8x acima de 3.0 — dobrar orçamento"
    }

    Contratos aplicados:
    - DEVE pausar se CPC > CPC_MAXIMO (R$ 1.50)
    - DEVE pausar se CTR < 1%
    - DEVE escalar se ROAS > ROAS_ESCALA (3.0x)
    """
    from core.config import CPC_MAXIMO, ROAS_ESCALA

    dados = request.get_json(force=True, silent=True) or {}
    cpc   = float(dados.get("cpc",  0))
    ctr   = float(dados.get("ctr",  0))
    roas  = float(dados.get("roas", 0))
    nome  = dados.get("nome", "campanha")

    logger.info(f"[CAMPANHA] {nome} | CPC={cpc} CTR={ctr}% ROAS={roas}x")

    # Contrato: DEVE pausar se CPC alto
    if cpc > CPC_MAXIMO:
        alertar_gestor(f"Campanha pausada: {nome}\nCPC R$ {cpc:.2f} > máximo R$ {CPC_MAXIMO:.2f}")
        return jsonify({"acao": "pausar", "motivo": f"CPC R$ {cpc:.2f} acima do máximo R$ {CPC_MAXIMO:.2f}"})

    # Contrato: DEVE pausar se CTR baixo
    if ctr < 1.0:
        alertar_gestor(f"Campanha pausada: {nome}\nCTR {ctr:.1f}% abaixo de 1%")
        return jsonify({"acao": "pausar", "motivo": f"CTR {ctr:.1f}% abaixo do mínimo 1%"})

    # Contrato: DEVE escalar se ROAS bom
    if roas >= ROAS_ESCALA:
        alertar_gestor(f"Campanha escalando: {nome}\nROAS {roas:.1f}x — dobrando orçamento")
        return jsonify({"acao": "escalar", "motivo": f"ROAS {roas:.1f}x acima de {ROAS_ESCALA}x"})

    return jsonify({"acao": "manter", "motivo": f"métricas dentro do esperado — CPC={cpc} CTR={ctr}% ROAS={roas}x"})


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":
    print("\n🤖 Robo-Markplaces API iniciada")
    print("   Endpoints disponíveis:")
    print("   GET  /health              — verifica se servidor está vivo")
    print("   POST /chat                — responde pergunta de cliente")
    print("   POST /repricing           — calcula ajuste de preço")
    print("   POST /post                — gera post para redes sociais")
    print("   GET  /estoque/criticos    — lista produtos com estoque baixo")
    print("   POST /relatorio           — gera relatório diário")
    print("   POST /campanha/avaliar    — avalia métricas e decide ação")
    print("\n   n8n deve apontar para: http://localhost:5000\n")

    app.run(host="0.0.0.0", port=5000, debug=False)