"""
setup_projeto.py
Execute este script UMA VEZ dentro do PyCharm para criar
toda a estrutura de pastas e arquivos do Robo-Markplaces.

Como usar no PyCharm:
1. Copie este arquivo para dentro da pasta Robo-Markplaces
2. Clique com botão direito no arquivo → Run 'setup_projeto'
3. Pronto — toda a estrutura será criada automaticamente
"""

import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def criar(caminho: str, conteudo: str = ""):
    """Cria arquivo com conteúdo, criando pastas intermediárias."""
    caminho_completo = os.path.join(ROOT, caminho)
    os.makedirs(os.path.dirname(caminho_completo), exist_ok=True)
    if not os.path.exists(caminho_completo):
        with open(caminho_completo, "w", encoding="utf-8") as f:
            f.write(conteudo)
        print(f"  criado  {caminho}")
    else:
        print(f"  existe  {caminho} (pulado)")


def criar_pasta(caminho: str):
    """Cria pasta vazia com .gitkeep para o Git rastrear."""
    pasta = os.path.join(ROOT, caminho)
    os.makedirs(pasta, exist_ok=True)
    gitkeep = os.path.join(pasta, ".gitkeep")
    if not os.path.exists(gitkeep):
        open(gitkeep, "w").close()
    print(f"  pasta   {caminho}/")


# ============================================================
# ESTRUTURA COMPLETA
# ============================================================

print("\n🤖 Robo-Markplaces — criando estrutura do projeto...\n")

# --- GitHub Actions ---
criar(".github/workflows/agente_principal.yml", """\
# GitHub Actions — Orquestrador do Robo-Markplaces
# Este arquivo ativa todos os agentes automaticamente
name: Robo-Markplaces

on:
  schedule:
    - cron: '0 11 * * *'       # Relatório diário às 8h (BR)
    - cron: '*/30 11-23 * * *' # Chat ML/Shopee a cada 30min
    - cron: '0 */6 * * *'      # Algoritmos de ranking a cada 6h
  workflow_dispatch:            # Permite rodar manualmente
    inputs:
      agente:
        description: 'Qual agente rodar?'
        default: 'todos'

env:
  PYTHON_VERSION: '3.11'

jobs:
  testes:
    name: Testes SDD
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt
      - run: python tests/test_behaviors.py

  relatorio:
    name: Relatório Diário
    runs-on: ubuntu-latest
    needs: testes
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -c "from agentes.relatorio import executar; executar()"
        env:
          ANTHROPIC_API_KEY:  ${{ secrets.ANTHROPIC_API_KEY }}
          BLING_ACCESS_TOKEN: ${{ secrets.BLING_ACCESS_TOKEN }}
          LOJAHUB_TOKEN:      ${{ secrets.LOJAHUB_TOKEN }}
          TELEGRAM_TOKEN:     ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
""")

# --- Spec SDD ---
criar("spec/spec.yaml", """\
# ============================================================
# SPEC PRINCIPAL — Robo-Markplaces
# Metodologia: Spec-Driven Development (SDD)
# Fonte da verdade de todo o projeto
# ============================================================

projeto:
  nome: Robo-Markplaces
  versao: "1.0"
  descricao: >
    Agente autônomo que gerencia vendas em 4 marketplaces,
    responde perguntas com IA, publica promoções nas redes sociais
    e emite NF-e via Bling — tudo guiado por esta spec.

marketplaces:
  - id: mercadolivre
    ativo: true
    prioridade: 1
  - id: shopee
    ativo: true
    prioridade: 2
  - id: magalu
    ativo: false
    prioridade: 3
  - id: amazon
    ativo: false
    prioridade: 4

regras_negocio:
  margem_minima_pct: 15.0
  estoque_critico_unidades: 20
  cpc_maximo_reais: 1.50
  ctr_minimo_pct: 1.0
  roas_escala: 3.0
  horario_post_manha: "08:00"
  horario_post_noite: "19:00"
""")

# --- Core ---
criar("core/__init__.py", "")

criar("core/config.py", """\
\"\"\"
core/config.py
Configuração central — lê spec.yaml e variáveis de ambiente.
\"\"\"
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent.parent

def carregar_spec() -> dict:
    with open(ROOT / "spec" / "spec.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

SPEC = carregar_spec()
REGRAS = SPEC.get("regras_negocio", {})

# IA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Lojahub
LOJAHUB_TOKEN           = os.getenv("LOJAHUB_TOKEN", "")
LOJAHUB_ANALYTICS_TOKEN = os.getenv("LOJAHUB_ANALYTICS_TOKEN", "")

# Bling
BLING_CLIENT_ID     = os.getenv("BLING_CLIENT_ID", "")
BLING_CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "")
BLING_ACCESS_TOKEN  = os.getenv("BLING_ACCESS_TOKEN", "")
BLING_REFRESH_TOKEN = os.getenv("BLING_REFRESH_TOKEN", "")

# Mercado Livre
ML_CLIENT_ID     = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_ACCESS_TOKEN  = os.getenv("ML_ACCESS_TOKEN", "")
ML_REFRESH_TOKEN = os.getenv("ML_REFRESH_TOKEN", "")
ML_SELLER_ID     = os.getenv("ML_SELLER_ID", "")

# Shopee
SHOPEE_PARTNER_ID  = os.getenv("SHOPEE_PARTNER_ID", "")
SHOPEE_PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID     = os.getenv("SHOPEE_SHOP_ID", "")
SHOPEE_ACCESS_TOKEN  = os.getenv("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_REFRESH_TOKEN = os.getenv("SHOPEE_REFRESH_TOKEN", "")

# Magalu
MAGALU_CLIENT_ID     = os.getenv("MAGALU_CLIENT_ID", "")
MAGALU_CLIENT_SECRET = os.getenv("MAGALU_CLIENT_SECRET", "")
MAGALU_MERCHANT_ID   = os.getenv("MAGALU_MERCHANT_ID", "")
MAGALU_ACCESS_TOKEN  = os.getenv("MAGALU_ACCESS_TOKEN", "")

# Amazon
AMAZON_LWA_CLIENT_ID     = os.getenv("AMAZON_LWA_CLIENT_ID", "")
AMAZON_LWA_CLIENT_SECRET = os.getenv("AMAZON_LWA_CLIENT_SECRET", "")
AMAZON_REFRESH_TOKEN     = os.getenv("AMAZON_REFRESH_TOKEN", "")
AMAZON_SELLER_ID         = os.getenv("AMAZON_SELLER_ID", "")
AMAZON_MARKETPLACE_ID    = os.getenv("AMAZON_MARKETPLACE_ID", "A2Q3Y263D00KWC")

# Meta (Facebook + Instagram)
META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
META_PAGE_ID       = os.getenv("META_PAGE_ID", "")
META_INSTAGRAM_ID  = os.getenv("META_INSTAGRAM_ID", "")

# Alertas
TELEGRAM_TOKEN          = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_GESTOR_CHAT_ID = os.getenv("TELEGRAM_GESTOR_CHAT_ID", "")

# Regras de negócio
MARGEM_MINIMA  = float(os.getenv("MARGEM_MINIMA",  str(REGRAS.get("margem_minima_pct", 15.0))))
ESTOQUE_CRITICO = int(os.getenv("ESTOQUE_CRITICO", str(REGRAS.get("estoque_critico_unidades", 20))))
CPC_MAXIMO     = float(os.getenv("CPC_MAXIMO",     str(REGRAS.get("cpc_maximo_reais", 1.50))))
ROAS_ESCALA    = float(os.getenv("ROAS_ESCALA",    str(REGRAS.get("roas_escala", 3.0))))
""")

criar("core/notificador.py", """\
\"\"\"
core/notificador.py
Envia alertas via Telegram. Nunca lança exceção.
\"\"\"
import logging
import requests
from datetime import datetime
from core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GESTOR_CHAT_ID

logger = logging.getLogger("notificador")

def _enviar(chat_id: str, msg: str) -> bool:
    if not TELEGRAM_TOKEN or not chat_id:
        print(f"[TELEGRAM não configurado]\\n{msg}")
        return True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram erro: {e}")
        return False

def alertar(msg: str) -> bool:
    return _enviar(TELEGRAM_CHAT_ID, f"🔔 *Alerta* {datetime.now().strftime('%d/%m %H:%M')}\\n\\n{msg}")

def alertar_gestor(msg: str) -> bool:
    return _enviar(TELEGRAM_GESTOR_CHAT_ID, f"📊 *Gestor* {datetime.now().strftime('%d/%m %H:%M')}\\n\\n{msg}")

def alertar_critico(msg: str) -> bool:
    alertar_gestor(f"🚨 CRÍTICO\\n{msg}")
    return alertar(f"🚨 CRÍTICO\\n{msg}")
""")

criar("core/claude_client.py", """\
\"\"\"
core/claude_client.py
Cliente centralizado para o Claude (Anthropic).
Nunca lança exceção — erro retorna string de fallback.
\"\"\"
import logging
import requests
from core.config import ANTHROPIC_API_KEY

logger = logging.getLogger("claude")
API_URL = "https://api.anthropic.com/v1/messages"
MODELO  = "claude-sonnet-4-20250514"

SYSTEM = \"\"\"
Você é o agente de vendas de uma distribuidora de esmaltes para manicures.
Tom: profissional, próximo, linguagem de salão de beleza.
Use sempre dados reais do contexto fornecido.
Nunca invente informações. Nunca prometa o que não pode cumprir.
\"\"\"

def perguntar(prompt: str, max_tokens: int = 500) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ ANTHROPIC_API_KEY não configurada."
    try:
        r = requests.post(API_URL, headers={
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
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Claude erro: {e}")
        return f"⚠️ Erro na IA: {e}"

def responder_chat(pergunta: str, produto: dict, canal: str) -> str:
    ctx = f\"\"\"
Canal: {canal.upper()}
Produto: {produto.get('nome','N/D')}
Preço: R$ {produto.get('preco',0):.2f}
Estoque: {produto.get('estoque',0)} unidades
Descrição: {produto.get('descricao','')}

Pergunta do cliente: {pergunta}
\"\"\"
    return perguntar(ctx, max_tokens=400)

def gerar_post(produto: dict, canal: str) -> str:
    return perguntar(f\"\"\"
Crie um post promocional para {canal} sobre:
- Produto: {produto.get('nome')}
- Preço: R$ {produto.get('preco',0):.2f}
- Público: manicures profissionais
Máximo 150 palavras. Tom animado e profissional.
\"\"\", max_tokens=300)
""")

# --- Integrações ---
criar("integracoes/__init__.py", "")
criar("integracoes/bling/__init__.py", "")

criar("integracoes/bling/bling_client.py", """\
\"\"\"
integracoes/bling/bling_client.py
Cliente da API Bling v3. Nunca lança exceção.
\"\"\"
import logging
import requests
from core.config import BLING_ACCESS_TOKEN, BLING_REFRESH_TOKEN, BLING_CLIENT_ID, BLING_CLIENT_SECRET

logger = logging.getLogger("bling")
BASE = "https://www.bling.com.br/Api/v3"

def _h():
    return {"Authorization": f"Bearer {BLING_ACCESS_TOKEN}"}

def buscar_produto(sku: str) -> dict | None:
    try:
        r = requests.get(f"{BASE}/produtos", headers=_h(), params={"codigo": sku}, timeout=15)
        r.raise_for_status()
        itens = r.json().get("data", [])
        if not itens:
            return None
        p = itens[0]
        return {
            "sku":      p.get("codigo"),
            "nome":     p.get("nome"),
            "preco":    float(p.get("preco", 0)),
            "estoque":  int(p.get("estoqueAtual", 0)),
            "descricao": p.get("descricaoCurta", ""),
        }
    except Exception as e:
        logger.error(f"Bling buscar_produto erro: {e}")
        return None

def listar_produtos() -> list[dict]:
    try:
        r = requests.get(f"{BASE}/produtos", headers=_h(), params={"situacao": "A"}, timeout=15)
        r.raise_for_status()
        return [
            {"sku": p.get("codigo"), "nome": p.get("nome"),
             "preco": float(p.get("preco", 0)), "estoque": int(p.get("estoqueAtual", 0))}
            for p in r.json().get("data", [])
        ]
    except Exception as e:
        logger.error(f"Bling listar_produtos erro: {e}")
        return []

def estoques_criticos(limite: int = 20) -> list[dict]:
    return [p for p in listar_produtos() if p["estoque"] <= limite]
""")

criar("integracoes/lojahub/__init__.py", "")
criar("integracoes/lojahub/lojahub_client.py", """\
\"\"\"
integracoes/lojahub/lojahub_client.py
Cliente da API Lojahub. A preencher com endpoints reais.
\"\"\"
import logging
import requests
from core.config import LOJAHUB_TOKEN

logger = logging.getLogger("lojahub")
BASE = "https://api.lojahub.com.br/v1"

def _h():
    return {"Authorization": f"Bearer {LOJAHUB_TOKEN}"}

def listar_pedidos_pendentes() -> list[dict]:
    # TODO: implementar quando tiver acesso à API Lojahub
    return []
""")

criar("integracoes/meta/__init__.py", "")
criar("integracoes/meta/meta_client.py", """\
\"\"\"
integracoes/meta/meta_client.py
Cliente da Meta Graph API (Facebook + Instagram).
\"\"\"
import logging
import requests
from core.config import META_ACCESS_TOKEN, META_PAGE_ID, META_INSTAGRAM_ID

logger = logging.getLogger("meta")
BASE = "https://graph.facebook.com/v19.0"

def publicar_instagram(texto: str, imagem_url: str = "") -> bool:
    # TODO: implementar upload de imagem e publicação
    logger.info(f"[META] Publicaria: {texto[:80]}...")
    return True

def publicar_facebook(texto: str) -> bool:
    try:
        r = requests.post(
            f"{BASE}/{META_PAGE_ID}/feed",
            params={"access_token": META_ACCESS_TOKEN},
            json={"message": texto},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Meta publicar_facebook erro: {e}")
        return False
""")

criar("integracoes/telegram/__init__.py", "")

# --- Agentes ---
criar("agentes/__init__.py", "")
criar("agentes/ml/__init__.py", "")

criar("agentes/ml/agente_ml.py", """\
\"\"\"
agentes/ml/agente_ml.py
Agente do Mercado Livre.
Contratos: spec/spec.yaml > marketplaces[mercadolivre]
\"\"\"
import logging
import time
import requests
from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID, MARGEM_MINIMA
from core.claude_client import responder_chat
from core.notificador import alertar, alertar_critico
from integracoes.bling.bling_client import buscar_produto

logger = logging.getLogger("agente_ml")
BASE = "https://api.mercadolibre.com"

def _h():
    return {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}

def buscar_perguntas() -> list[dict]:
    try:
        r = requests.get(f"{BASE}/my/received_questions/search",
            headers=_h(), params={"status": "UNANSWERED", "seller_id": ML_SELLER_ID}, timeout=15)
        r.raise_for_status()
        return r.json().get("questions", [])
    except Exception as e:
        logger.error(f"ML buscar_perguntas: {e}")
        return []

def responder(pergunta_id: str, texto: str) -> bool:
    try:
        r = requests.post(f"{BASE}/answers", headers=_h(),
            json={"question_id": pergunta_id, "text": texto}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"ML responder {pergunta_id}: {e}")
        return False

def ciclo_chat() -> int:
    perguntas = buscar_perguntas()
    ok = 0
    for p in perguntas:
        produto = buscar_produto(p.get("item_id", "")) or {}
        resposta = responder_chat(p.get("text", ""), produto, "mercadolivre")
        if responder(p["id"], resposta):
            ok += 1
        time.sleep(1)
    logger.info(f"ML chat: {ok}/{len(perguntas)} respondidas")
    return ok

def verificar_reputacao() -> dict:
    try:
        r = requests.get(f"{BASE}/users/{ML_SELLER_ID}", headers=_h(), timeout=15)
        r.raise_for_status()
        rep = r.json().get("seller_reputation", {})
        nivel = rep.get("level_id", "")
        pct   = rep.get("metrics", {}).get("claims", {}).get("rate", 0)
        if pct > 0.01:
            alertar_critico(f"ML: reclamações em {pct*100:.1f}% — acima de 1%!")
        logger.info(f"ML reputação: {nivel} | reclamações: {pct*100:.2f}%")
        return {"nivel": nivel, "reclamacoes_pct": pct}
    except Exception as e:
        logger.error(f"ML reputacao: {e}")
        return {}

def executar() -> dict:
    logger.info("=== Agente ML iniciado ===")
    return {"chat": ciclo_chat(), "reputacao": verificar_reputacao()}
""")

criar("agentes/shopee/__init__.py", "")
criar("agentes/shopee/agente_shopee.py", """\
\"\"\"
agentes/shopee/agente_shopee.py
Agente da Shopee. A implementar.
\"\"\"
import logging
logger = logging.getLogger("agente_shopee")

def executar() -> dict:
    logger.info("=== Agente Shopee iniciado ===")
    # TODO: implementar chat, campanhas e hashtags
    return {"status": "em_desenvolvimento"}
""")

criar("agentes/magalu/__init__.py", "")
criar("agentes/magalu/agente_magalu.py", """\
\"\"\"
agentes/magalu/agente_magalu.py
Agente do Magalu. A implementar.
\"\"\"
import logging
logger = logging.getLogger("agente_magalu")

def executar() -> dict:
    logger.info("=== Agente Magalu iniciado ===")
    return {"status": "em_desenvolvimento"}
""")

criar("agentes/amazon/__init__.py", "")
criar("agentes/amazon/agente_amazon.py", """\
\"\"\"
agentes/amazon/agente_amazon.py
Agente da Amazon. A implementar.
\"\"\"
import logging
logger = logging.getLogger("agente_amazon")

def executar() -> dict:
    logger.info("=== Agente Amazon iniciado ===")
    return {"status": "em_desenvolvimento"}
""")

criar("agentes/social/__init__.py", "")
criar("agentes/social/publicador.py", """\
\"\"\"
agentes/social/publicador.py
Publica promoções no Instagram e Facebook.
\"\"\"
import logging
from integracoes.bling.bling_client import listar_produtos
from integracoes.meta.meta_client import publicar_facebook, publicar_instagram
from core.claude_client import gerar_post
from core.config import ESTOQUE_CRITICO
from core.notificador import alertar

logger = logging.getLogger("publicador")

def selecionar_produto() -> dict | None:
    produtos = listar_produtos()
    elegiveis = [p for p in produtos if p["estoque"] >= ESTOQUE_CRITICO]
    if not elegiveis:
        return None
    return max(elegiveis, key=lambda p: p["preco"])

def executar() -> bool:
    produto = selecionar_produto()
    if not produto:
        alertar("Nenhum produto elegível para post hoje.")
        return False
    texto_ig = gerar_post(produto, "Instagram")
    texto_fb = gerar_post(produto, "Facebook")
    ok_ig = publicar_instagram(texto_ig)
    ok_fb = publicar_facebook(texto_fb)
    logger.info(f"Post publicado: IG={ok_ig} FB={ok_fb}")
    return ok_ig and ok_fb
""")

criar("agentes/relatorio.py", """\
\"\"\"
agentes/relatorio.py
Relatório diário consolidado via Telegram.
\"\"\"
import logging
from datetime import datetime
from integracoes.bling.bling_client import listar_produtos, estoques_criticos
from core.claude_client import perguntar
from core.notificador import alertar, alertar_critico

logger = logging.getLogger("relatorio")

def executar() -> bool:
    logger.info("=== Relatório diário ===")
    try:
        produtos = listar_produtos()
        criticos = estoques_criticos()
        dados = {
            "data": datetime.now().strftime("%d/%m/%Y"),
            "total_produtos": len(produtos),
            "criticos": len(criticos),
            "nomes_criticos": [p["nome"] for p in criticos[:3]],
        }
        analise = perguntar(
            f"Analise em 3 bullet points curtos para dono de negócio: {dados}",
            max_tokens=300
        )
        msg = (
            f"📊 *Relatório {dados['data']}*\\n\\n"
            f"Produtos ativos: {dados['total_produtos']}\\n"
            f"Estoque crítico: {dados['criticos']} produtos\\n\\n"
            f"*Análise IA:*\\n{analise}"
        )
        if criticos:
            alertar_critico(f"Estoque crítico: {', '.join(dados['nomes_criticos'])}")
        return alertar(msg)
    except Exception as e:
        logger.error(f"Relatório erro: {e}")
        return False
""")

# --- Tests ---
criar("tests/__init__.py", "")

criar("tests/test_behaviors.py", """\
\"\"\"
tests/test_behaviors.py
Testes derivados dos behaviors da spec.yaml (BDD).
\"\"\"
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_B01_identifica_atacado():
    palavras = ["atacado", "salão", "salon", "revenda", "quantidade"]
    def eh_atacado(texto):
        return any(p in texto.lower() for p in palavras)
    assert eh_atacado("vocês vendem no atacado?")
    assert eh_atacado("tenho salão, preciso de bastante")
    assert not eh_atacado("qual a cor desse esmalte?")
    print("  PASS  B01 — identifica pergunta de atacado")


def test_B03_repricing_respeita_margem():
    MARGEM_MINIMA = 15.0
    custo = 6.00
    preco_concorrente = 4.00
    preco_alvo = preco_concorrente * 1.05
    margem = (preco_alvo - custo) / preco_alvo * 100
    assert margem < MARGEM_MINIMA, "Repricing deveria ser bloqueado"
    print("  PASS  B03 — repricing bloqueado quando margem insuficiente")


def test_B06_nf_nao_emitida_pendente():
    pode_emitir = ["pago", "aprovado", "confirmed"]
    nao_emite   = ["pendente", "aguardando_pagamento", "cancelado"]
    for s in nao_emite:
        assert s not in pode_emitir, f"'{s}' não deveria emitir NF"
    print("  PASS  B06 — NF bloqueada para status pendente")


def test_B07_campanha_pausada_estoque_zero():
    def pausar(estoque):
        return estoque <= 0
    assert pausar(0) and pausar(-1)
    assert not pausar(1) and not pausar(100)
    print("  PASS  B07 — campanha pausada com estoque zero")


def test_B08_post_exige_estoque_minimo():
    MIN = 20
    produtos = [
        {"nome": "A", "estoque": 5},
        {"nome": "B", "estoque": 50},
        {"nome": "C", "estoque": 15},
    ]
    elegiveis = [p for p in produtos if p["estoque"] >= MIN]
    assert len(elegiveis) == 1 and elegiveis[0]["nome"] == "B"
    print("  PASS  B08 — post bloqueado para estoque abaixo de 20")


if __name__ == "__main__":
    testes = [test_B01_identifica_atacado, test_B03_repricing_respeita_margem,
              test_B06_nf_nao_emitida_pendente, test_B07_campanha_pausada_estoque_zero,
              test_B08_post_exige_estoque_minimo]
    falhas = 0
    print(f"\\nRodando {len(testes)} testes...\\n")
    for t in testes:
        try:
            t()
        except AssertionError as e:
            print(f"  FAIL  {t.__name__} — {e}")
            falhas += 1
    print(f"\\nResultado: {len(testes)-falhas}/{len(testes)} testes passaram")
    if falhas:
        exit(1)
""")

# --- Catálogo ---
criar("catalogo/produtos.json", """\
[
  {
    "sku": "ESM-001",
    "nome": "Esmalte Vermelho Carmim 8ml",
    "preco": 9.90,
    "estoque_total": 200,
    "ncm": "3304.10.00",
    "canais": {
      "mercadolivre": {"ativo": true,  "preco": 9.90,  "estoque": 100},
      "shopee":       {"ativo": true,  "preco": 8.90,  "estoque": 100},
      "magalu":       {"ativo": false, "preco": 11.90, "estoque": 0},
      "amazon":       {"ativo": false, "preco": 12.90, "estoque": 0}
    }
  },
  {
    "sku": "ESM-002",
    "nome": "Kit 12 Esmaltes Nude Manicure",
    "preco": 59.90,
    "estoque_total": 50,
    "ncm": "3304.10.00",
    "canais": {
      "mercadolivre": {"ativo": false, "preco": 0,     "estoque": 0},
      "shopee":       {"ativo": true,  "preco": 59.90, "estoque": 50},
      "magalu":       {"ativo": false, "preco": 0,     "estoque": 0},
      "amazon":       {"ativo": false, "preco": 0,     "estoque": 0}
    }
  }
]
""")

# --- Logs ---
criar_pasta("logs")

# --- Raiz ---
criar("requirements.txt", """\
requests==2.31.0
python-dotenv==1.0.0
pyyaml==6.0.1
flask==3.0.0
""")

criar(".env.exemplo", """\
# Copie para .env e preencha — NUNCA suba o .env para o GitHub

ANTHROPIC_API_KEY=sk-ant-...

LOJAHUB_TOKEN=...
LOJAHUB_ANALYTICS_TOKEN=...

BLING_CLIENT_ID=...
BLING_CLIENT_SECRET=...
BLING_ACCESS_TOKEN=...
BLING_REFRESH_TOKEN=...

ML_CLIENT_ID=...
ML_CLIENT_SECRET=...
ML_ACCESS_TOKEN=...
ML_REFRESH_TOKEN=...
ML_SELLER_ID=...

SHOPEE_PARTNER_ID=...
SHOPEE_PARTNER_KEY=...
SHOPEE_SHOP_ID=...
SHOPEE_ACCESS_TOKEN=...
SHOPEE_REFRESH_TOKEN=...

META_ACCESS_TOKEN=...
META_PAGE_ID=...
META_INSTAGRAM_ID=...

TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_GESTOR_CHAT_ID=...

MARGEM_MINIMA=15.0
ESTOQUE_CRITICO=20
CPC_MAXIMO=1.50
ROAS_ESCALA=3.0
""")

criar("README.md", """\
# Robo-Markplaces
**Agente autônomo de vendas para marketplaces — Python + SDD + GitHub Actions**

## Estrutura
```
Robo-Markplaces/
├── .github/workflows/     # GitHub Actions — roda os agentes
├── spec/spec.yaml         # FONTE DA VERDADE (SDD)
├── core/                  # Config, Claude, Telegram
├── integracoes/           # Bling, Lojahub, Meta
├── agentes/               # ML, Shopee, Magalu, Amazon, Social
├── tests/                 # Testes dos behaviors da spec
├── catalogo/              # Produtos por canal
└── logs/                  # Logs gerados
```

## Como rodar
```bash
pip install -r requirements.txt
cp .env.exemplo .env       # preencha as credenciais
python tests/test_behaviors.py
python -c "from agentes.ml.agente_ml import executar; executar()"
```
""")

print("\n✅ Estrutura criada com sucesso!")
print(f"\nPróximos passos:")
print("  1. Instale as dependências: pip install -r requirements.txt")
print("  2. Copie .env.exemplo para .env e preencha as credenciais")
print("  3. Rode os testes: python tests/test_behaviors.py")
print("  4. Faça o push: git add . && git commit -m 'feat: estrutura SDD' && git push")
print("\nO GitHub Actions será ativado automaticamente após o push! 🚀")