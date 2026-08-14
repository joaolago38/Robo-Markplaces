"""
core/config.py
Configuração central — lê spec.yaml e variáveis de ambiente.
"""
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent.parent
logger = logging.getLogger("config")

def carregar_spec() -> dict:
    spec_path = ROOT / "spec" / "spec.yaml"
    try:
        with open(spec_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("spec.yaml não encontrado em %s; usando defaults.", spec_path)
        return {}
    except yaml.YAMLError as exc:
        logger.error("Erro de parse no spec.yaml: %s; usando defaults.", exc)
        return {}

SPEC = carregar_spec()
REGRAS = SPEC.get("regras_negocio", {})


def marketplace_spec_ativo(marketplace_id: str) -> bool:
    """True só se o canal está `ativo: true` no spec.yaml."""
    mid = (marketplace_id or "").strip().lower()
    if not mid:
        return False
    for item in SPEC.get("marketplaces") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip().lower() == mid:
            return bool(item.get("ativo", False))
    return False


def skip_se_spec_inativo(marketplace_id: str) -> dict | None:
    """Pula API se o canal não está no spec nem no toggle de operação."""
    if marketplace_spec_ativo(marketplace_id):
        return None
    try:
        from core.marketplace_toggle import canal_em_operacao

        if canal_em_operacao(marketplace_id):
            return None
    except Exception:
        pass
    return {
        "ok": True,
        "skipped": True,
        "motivo": "spec.inativo",
        "marketplace": marketplace_id,
    }

# IA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
# Toggle mestre: 0 = pausa TODAS as chamadas Claude (sem gastar token/USD)
# Também existe logs/claude_toggle.json (scripts/toggle_claude.py) para pausa momentânea.
# Default OFF: exige opt-in explícito (CLAUDE_ATIVO=1) para gastar créditos.
CLAUDE_ATIVO = os.getenv("CLAUDE_ATIVO", "0").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
# Modelos Claude — Haiku ≈ bem mais barato que Sonnet
CLAUDE_MODELO = (
    os.getenv("CLAUDE_MODELO", "claude-sonnet-4-5").strip() or "claude-sonnet-4-5"
)
CLAUDE_MODELO_RAPIDO = (
    os.getenv("CLAUDE_MODELO_RAPIDO", "claude-haiku-4-5").strip() or "claude-haiku-4-5"
)
# 1 = força Haiku (MODELO_RAPIDO) em TODAS as chamadas — reduz custo
CLAUDE_ECONOMICO = os.getenv("CLAUDE_ECONOMICO", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Orçamento local (US$) — hard stop + alertas Telegram
CLAUDE_ORCAMENTO_USD = float(os.getenv("CLAUDE_ORCAMENTO_USD", "8.99"))
CLAUDE_ORCAMENTO_ATIVO = os.getenv("CLAUDE_ORCAMENTO_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CLAUDE_ORCAMENTO_ALERTA = os.getenv("CLAUDE_ORCAMENTO_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# 1 = manda Telegram a cada chamada (monitoramento fino nesta fase)
CLAUDE_ORCAMENTO_ALERTA_TODAS = os.getenv("CLAUDE_ORCAMENTO_ALERTA_TODAS", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
CLAUDE_PRECO_HAIKU_IN = float(os.getenv("CLAUDE_PRECO_HAIKU_IN", "1.0"))
CLAUDE_PRECO_HAIKU_OUT = float(os.getenv("CLAUDE_PRECO_HAIKU_OUT", "5.0"))
CLAUDE_PRECO_SONNET_IN = float(os.getenv("CLAUDE_PRECO_SONNET_IN", "3.0"))
CLAUDE_PRECO_SONNET_OUT = float(os.getenv("CLAUDE_PRECO_SONNET_OUT", "15.0"))

# Roteamento Haiku → modelo de vendas (Sonnet) em pontos de alta conversão ML
CLAUDE_MODELO_VENDAS = (
    os.getenv("CLAUDE_MODELO_VENDAS", "claude-sonnet-4-5").strip() or "claude-sonnet-4-5"
)
CLAUDE_ESCALONAR_ML = os.getenv("CLAUDE_ESCALONAR_ML", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Só sobe de modelo se restante do orçamento local >= este piso (US$)
CLAUDE_ESCALONAR_RESTANTE_MIN_USD = float(os.getenv("CLAUDE_ESCALONAR_RESTANTE_MIN_USD", "1.50"))
# Preço do anúncio (R$) a partir do qual chat ML vendedor escala
CLAUDE_ESCALONAR_PRECO_MIN = float(os.getenv("CLAUDE_ESCALONAR_PRECO_MIN", "40.0"))
# 1 = Sonnet na escolha de oferta só se análise alta OU Ads alerta/crítico (não sempre)
CLAUDE_ESCALONAR_OFERTA = os.getenv("CLAUDE_ESCALONAR_OFERTA", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CLAUDE_ESCALONAR_OFERTA_SO_CALOR = os.getenv("CLAUDE_ESCALONAR_OFERTA_SO_CALOR", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# 1 = bloqueia envio WA/TG/FB/IG se link ML inválido (MLB_PREENCHER) — só prepara + avisa gestor
CONVERSAO_BLOQUEAR_LINK_INVALIDO = os.getenv("CONVERSAO_BLOQUEAR_LINK_INVALIDO", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CLAUDE_ESCALONAR_CHAT = os.getenv("CLAUDE_ESCALONAR_CHAT", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Análise de calor da venda ML (0–100). >= ALTO → aumenta IA (Sonnet)
CLAUDE_ANALISE_SCORE_ALTO = int(os.getenv("CLAUDE_ANALISE_SCORE_ALTO", "70"))
CLAUDE_ANALISE_SCORE_MEDIO = int(os.getenv("CLAUDE_ANALISE_SCORE_MEDIO", "40"))
# Captura IG/FB exige score maior para Sonnet (fechamento ML é o termômetro principal)
CLAUDE_ANALISE_SCORE_ALTO_CAPTACAO = int(os.getenv("CLAUDE_ANALISE_SCORE_ALTO_CAPTACAO", "85"))
# Gasto Meta (R$) a partir do qual pressão de captacao sobe dosagem no ML
CLAUDE_ANALISE_GASTO_META_PRESSAO = float(os.getenv("CLAUDE_ANALISE_GASTO_META_PRESSAO", "30"))
# 1 = no chat ML, se análise alta, NÃO usa template fixo (frete/atacado) — vai pro Sonnet
CLAUDE_ANALISE_FURA_TEMPLATE = os.getenv("CLAUDE_ANALISE_FURA_TEMPLATE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Injeta estado_ml + situação do produto nas análises Claude de marketplace
CLAUDE_ML_CONTEXTO_ATIVO = os.getenv("CLAUDE_ML_CONTEXTO_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Dosagem minima/padrao/ampliada conforme saúde ML × stress do produto
CLAUDE_ML_DOSAGEM_ATIVA = os.getenv("CLAUDE_ML_DOSAGEM_ATIVA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Lojahub
LOJAHUB_TOKEN           = os.getenv("LOJAHUB_TOKEN", "").strip()
LOJAHUB_ANALYTICS_TOKEN = os.getenv("LOJAHUB_ANALYTICS_TOKEN", "").strip()

# Bling
BLING_CLIENT_ID     = os.getenv("BLING_CLIENT_ID", "").strip()
BLING_CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "").strip()
BLING_ACCESS_TOKEN  = os.getenv("BLING_ACCESS_TOKEN", "").strip()
BLING_REFRESH_TOKEN = os.getenv("BLING_REFRESH_TOKEN", "").strip()

# Mercado Livre
ML_CLIENT_ID     = os.getenv("ML_CLIENT_ID", "").strip()
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "").strip()
ML_ACCESS_TOKEN  = os.getenv("ML_ACCESS_TOKEN", "").strip()
ML_REFRESH_TOKEN = os.getenv("ML_REFRESH_TOKEN", "").strip()
ML_SELLER_ID     = os.getenv("ML_SELLER_ID", "").strip()
ML_SITE_ID       = (os.getenv("ML_SITE_ID", "MLB").strip() or "MLB")  # MLB = Brasil
# Empresas por CNPJ + CNAE (complementa configs atuais; não as substitui)
EMPRESAS_CNAE_CNPJ_CATALOGO = os.getenv(
    "EMPRESAS_CNAE_CNPJ_CATALOGO", "catalogo/empresas_cnae_cnpj.json"
)
EMPRESA_ATIVA_ID = os.getenv("EMPRESA_ATIVA_ID", "").strip()
EMPRESA_ATIVA_CNPJ = os.getenv("EMPRESA_ATIVA_CNPJ", "").strip()
# Dois CNPJs: esmaltes × demais produtos (Masterprint/filamentos/escritório)
ESMALTES_CNPJ = os.getenv("ESMALTES_CNPJ", "52668583000127").strip()
DEMAIS_PRODUTOS_CNPJ = os.getenv("DEMAIS_PRODUTOS_CNPJ", "23811261000197").strip()
# Dono fiscal/operacional dos dados de produtos (catalogo/produtos.json etc.).
# Hoje: esmaltes (526…). Alvo da migração: demais (238…). Para trocar sem
# reescrever catálogos: CNPJ_DONO_PRODUTOS_USAR_ALVO=1
CNPJ_DONO_PRODUTOS = os.getenv("CNPJ_DONO_PRODUTOS", ESMALTES_CNPJ or "52668583000127").strip()
CNPJ_DONO_PRODUTOS_ALVO = os.getenv(
    "CNPJ_DONO_PRODUTOS_ALVO", DEMAIS_PRODUTOS_CNPJ or "23811261000197"
).strip()
CNPJ_DONO_PRODUTOS_USAR_ALVO = os.getenv(
    "CNPJ_DONO_PRODUTOS_USAR_ALVO", "0"
).strip().lower() in ("1", "true", "yes", "on")
# Monitor CNAE → CNPJ → produtos (alteração ativa monitoramento)
MONITOR_CNPJ_CNAE_ATIVO = os.getenv("MONITOR_CNPJ_CNAE_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
MONITOR_CNPJ_CNAE_ALERTA = os.getenv("MONITOR_CNPJ_CNAE_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Alerta no ciclo 10d mesmo sem alteração (False) ou só quando fingerprint muda (True)
MONITOR_CNPJ_CNAE_ALERTA_SO_ALTERACAO = os.getenv(
    "MONITOR_CNPJ_CNAE_ALERTA_SO_ALTERACAO", "0"
).strip().lower() not in ("0", "false", "no")
# Ciclo de monitoramento ML após alteração / refresh periódico
MONITOR_CNPJ_CNAE_INTERVALO_DIAS = int(os.getenv("MONITOR_CNPJ_CNAE_INTERVALO_DIAS", "10"))
MONITOR_CNPJ_CNAE_ML_AO_VIVO = os.getenv("MONITOR_CNPJ_CNAE_ML_AO_VIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Cooldown Telegram ≈ intervalo (10d); override via env se necessário
MONITOR_CNPJ_CNAE_COOLDOWN_SEG = int(
    os.getenv(
        "MONITOR_CNPJ_CNAE_COOLDOWN_SEG",
        str(MONITOR_CNPJ_CNAE_INTERVALO_DIAS * 24 * 3600),
    )
)
# Ponto de ruptura Impala → segundo CNPJ (Masterprint) + alerta CNAE
PONTO_RUPTURA_ATIVO = os.getenv("PONTO_RUPTURA_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
PONTO_RUPTURA_ALERTA = os.getenv("PONTO_RUPTURA_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
PONTO_RUPTURA_APROXIMANDO_AVALIACOES = int(
    os.getenv("PONTO_RUPTURA_APROXIMANDO_AVALIACOES", "10")
)
PONTO_RUPTURA_ESTOQUE_MIN = int(
    os.getenv(
        "PONTO_RUPTURA_ESTOQUE_MIN",
        str(REGRAS.get("estoque_critico_unidades", 30)),
    )
)
PONTO_RUPTURA_COOLDOWN_LIBERADO_SEG = int(
    os.getenv("PONTO_RUPTURA_COOLDOWN_LIBERADO_SEG", str(7 * 24 * 3600))
)
PONTO_RUPTURA_COOLDOWN_CNAE_SEG = int(
    os.getenv("PONTO_RUPTURA_COOLDOWN_CNAE_SEG", str(7 * 24 * 3600))
)
PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG = int(
    os.getenv("PONTO_RUPTURA_COOLDOWN_APROXIMANDO_SEG", str(24 * 3600))
)
# Claude no briefing de ruptura Impala (análise; não publica anúncio).
RUPTURA_CLAUDE = os.getenv("RUPTURA_CLAUDE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Limites de decisão do ecossistema (Alibaba + USD + vendas + saúde ML × CNAE/CNPJ)
DECISION_LIMITS_ATIVO = os.getenv("DECISION_LIMITS_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
DECISION_LIMITS_MAX_FAZER = int(os.getenv("DECISION_LIMITS_MAX_FAZER", "3"))
DECISION_LIMITS_MAX_IMPORTAR = int(os.getenv("DECISION_LIMITS_MAX_IMPORTAR", "1"))
DECISION_LIMITS_MAX_ADS = int(os.getenv("DECISION_LIMITS_MAX_ADS", "1"))
DECISION_LIMITS_JANELA_HORAS = int(os.getenv("DECISION_LIMITS_JANELA_HORAS", "12"))
# Foco de análise por enquanto: Mercado Livre (Shopee/Magalu permanecem configurados)
MARKETPLACE_FOCO_PRINCIPAL = os.getenv("MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre").strip().lower() or "mercadolivre"
# Resumo da conta (espelho do painel Resumo → Telegram)
RESUMO_CONTA_ML_ALERTA = os.getenv("RESUMO_CONTA_ML_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
RESUMO_CONTA_ML_COOLDOWN_SEG = int(os.getenv("RESUMO_CONTA_ML_COOLDOWN_SEG", "72000"))
RESUMO_CONTA_ML_MAX_PERFORMANCE = int(os.getenv("RESUMO_CONTA_ML_MAX_PERFORMANCE", "80"))
# 1 = ignora bolsas/legado na listagem de anúncios; reputação da conta segue valendo
ML_IGNORAR_ANUNCIOS_FORA_FOCO = os.getenv("ML_IGNORAR_ANUNCIOS_FORA_FOCO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Fallback quando /sites/search retorna 403 (comum desde ~2025)
# O endpoint público /sites/{site}/search costuma 403 mesmo autenticado (PolicyAgent).
# Desligado por padrão: a busca vai direto em /products/search. Ligue só para probe.
ML_BUSCA_TERMO_SITES_SEARCH = os.getenv("ML_BUSCA_TERMO_SITES_SEARCH", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
ML_BUSCA_TERMO_FALLBACK_DDG = os.getenv("ML_BUSCA_TERMO_FALLBACK_DDG", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ML_BUSCA_TERMO_FALLBACK_CATALOGO = os.getenv("ML_BUSCA_TERMO_FALLBACK_CATALOGO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ML_BUSCA_TERMO_FALLBACK_CACHE = os.getenv("ML_BUSCA_TERMO_FALLBACK_CACHE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ML_BUSCA_TERMO_CACHE_TTL_SEG = int(os.getenv("ML_BUSCA_TERMO_CACHE_TTL_SEG", "21600"))
ML_BUSCA_TERMO_MAX_REFS_CATALOGO = int(os.getenv("ML_BUSCA_TERMO_MAX_REFS_CATALOGO", "5"))
# Brave Search API — fallback JSON quando DDG bloqueia (opcional, requer chave)
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
# Cota mensal controlada (free ~2000). Padrão 1800 deixa folga.
BRAVE_QUOTA_MES = int(os.getenv("BRAVE_QUOTA_MES", "1800") or "1800")
BRAVE_QUOTA_ALERTA_PCT = float(os.getenv("BRAVE_QUOTA_ALERTA_PCT", "80") or "80")
BRAVE_QUOTA_HARD_STOP = os.getenv("BRAVE_QUOTA_HARD_STOP", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ML_BUSCA_TERMO_FALLBACK_BRAVE = os.getenv("ML_BUSCA_TERMO_FALLBACK_BRAVE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Catálogo oficial /products/search + /products/{id}/items (funciona quando /sites/search dá 403)
ML_BUSCA_TERMO_FALLBACK_PRODUCTS = os.getenv("ML_BUSCA_TERMO_FALLBACK_PRODUCTS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ML_BUSCA_TERMO_MAX_PRODUCTS = int(os.getenv("ML_BUSCA_TERMO_MAX_PRODUCTS", "8"))

# Métricas estilo LojaHub (estimadas) para anúncios concorrentes
# Taxa usada na receita líquida estimada; visitas só dos próprios anúncios.
ML_ANALISE_ANUNCIO_TAXA_PCT = float(
    os.getenv("ML_ANALISE_ANUNCIO_TAXA_PCT", os.getenv("TAXA_CANAL_PADRAO_PCT", "13.0"))
)
ML_ANALISE_ANUNCIO_MAX_ENRIQUECER = int(os.getenv("ML_ANALISE_ANUNCIO_MAX_ENRIQUECER", "8"))

# Monitor de concorrentes (busca pública por palavra-chave, sem precisar de item próprio)
MONITOR_CONCORRENTES_ARQUIVO = os.getenv(
    "MONITOR_CONCORRENTES_ARQUIVO", "catalogo/concorrentes_monitorados.json"
).strip()
MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT = float(
    os.getenv("MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT", "5.0")
)
# Se 1, alertas de gap vs "preço alvo" só saem com anúncio MLB vivo (não PREENCHER/JSON)
MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO = os.getenv(
    "MONITOR_CONCORRENTES_ALERTAR_GAP_SO_ANUNCIO_VIVO", "1"
).strip().lower() not in ("0", "false", "no")

# Resumo diário Novamix (loja concorrente ML)
NOVAMIX_RESUMO_DIARIO_SELLER_ID = os.getenv("NOVAMIX_RESUMO_DIARIO_SELLER_ID", "1666381510").strip()
NOVAMIX_RESUMO_DIARIO_NICKNAME = os.getenv("NOVAMIX_RESUMO_DIARIO_NICKNAME", "NOVAMIX_COMERCIAL").strip()
NOVAMIX_RESUMO_DIARIO_ALERTA = os.getenv("NOVAMIX_RESUMO_DIARIO_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
NOVAMIX_RESUMO_DIARIO_COOLDOWN_SEG = int(os.getenv("NOVAMIX_RESUMO_DIARIO_COOLDOWN_SEG", "72000"))
NOVAMIX_RESUMO_DIARIO_TOP_N = int(os.getenv("NOVAMIX_RESUMO_DIARIO_TOP_N", "6"))
NOVAMIX_RESUMO_DIARIO_ENRIQUECER = os.getenv("NOVAMIX_RESUMO_DIARIO_ENRIQUECER", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Gap máximo vs Novamix para classificar SKU como "competir" (Ads)
NOVAMIX_GAP_COMPETIR_PCT = float(os.getenv("NOVAMIX_GAP_COMPETIR_PCT", "10.0"))
# Após resumo diário: pedir confirmação e pausar Ads se maioria em guerra
NOVAMIX_AUTO_ADS_PAUSAR = os.getenv("NOVAMIX_AUTO_ADS_PAUSAR", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Ligar Ads automaticamente só se flag explícita (mais agressivo)
NOVAMIX_AUTO_ADS_INVESTIR = os.getenv("NOVAMIX_AUTO_ADS_INVESTIR", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
NOVAMIX_AUTO_ADS_PEDIR_CONFIRMACAO = os.getenv(
    "NOVAMIX_AUTO_ADS_PEDIR_CONFIRMACAO", "1"
).strip().lower() not in ("0", "false", "no")

# Anúncios próprios sem venda recente
MONITOR_SEM_VENDA_DIAS = int(os.getenv("MONITOR_SEM_VENDA_DIAS", "30"))
MONITOR_SEM_VENDA_MAX_ITENS = int(os.getenv("MONITOR_SEM_VENDA_MAX_ITENS", "40"))
MONITOR_SEM_VENDA_ALERTA_RESUMO = os.getenv(
    "MONITOR_SEM_VENDA_ALERTA_RESUMO", "1"
).strip().lower() not in ("0", "false", "no")
MONITOR_SEM_VENDA_COOLDOWN_SEG = int(os.getenv("MONITOR_SEM_VENDA_COOLDOWN_SEG", "14400"))
MONITOR_SEM_VENDA_VISITAS_ALTAS = int(os.getenv("MONITOR_SEM_VENDA_VISITAS_ALTAS", "20"))

# Funil próprio → ações (visitas→pedidos→conversão)
FUNIL_ML_MIN_VISITAS_CONV = int(os.getenv("FUNIL_ML_MIN_VISITAS_CONV", "10"))
FUNIL_ML_CONV_BAIXA_PCT = float(os.getenv("FUNIL_ML_CONV_BAIXA_PCT", "2.0"))
FUNIL_ML_CONV_BOA_PCT = float(os.getenv("FUNIL_ML_CONV_BOA_PCT", "5.0"))
FUNIL_ML_VISITAS_ALTAS = int(
    os.getenv("FUNIL_ML_VISITAS_ALTAS", str(MONITOR_SEM_VENDA_VISITAS_ALTAS))
)
FUNIL_ML_ACOES_MAX = int(os.getenv("FUNIL_ML_ACOES_MAX", "25"))
FUNIL_ML_ACOES_ALERTA = os.getenv("FUNIL_ML_ACOES_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
FUNIL_ML_ACOES_COOLDOWN_SEG = int(os.getenv("FUNIL_ML_ACOES_COOLDOWN_SEG", "14400"))

# Relatório de estratégia de vendas ML (ações a partir de gaps/margem)
ESTRATEGIA_ML_MAX_ACOES = int(os.getenv("ESTRATEGIA_ML_MAX_ACOES", "3"))
ESTRATEGIA_ML_GAP_GUERRA_PCT = float(os.getenv("ESTRATEGIA_ML_GAP_GUERRA_PCT", "25.0"))
ESTRATEGIA_ML_COOLDOWN_SEG = int(os.getenv("ESTRATEGIA_ML_COOLDOWN_SEG", "86400"))

ML_RELATORIO_MANHA_COOLDOWN_SEG = int(os.getenv("ML_RELATORIO_MANHA_COOLDOWN_SEG", "39600"))

# Monitor esmaltes Anita (cores, kits, margem, ranking marcas)
ANITA_ESMALTES_CATALOGO = os.getenv(
    "ANITA_ESMALTES_CATALOGO", "catalogo/anita_esmaltes_monitorados.json"
)
ANITA_PAUSA_ENTRE_BUSCAS_SEG = float(os.getenv("ANITA_PAUSA_ENTRE_BUSCAS_SEG", "1.5"))
ANITA_ALERTA_RESUMO = os.getenv("ANITA_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
ANITA_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("ANITA_ALERTA_RESUMO_COOLDOWN_SEG", "7200"))

# Monitor mercado esmaltes ML (cores, kits, margem viável, competição)
ESMALTES_MERCADO_CATALOGO = os.getenv(
    "ESMALTES_MERCADO_CATALOGO", "catalogo/esmaltes_mercado_segmentos.json"
)
ESMALTES_MERCADO_PAUSA_SEG = float(os.getenv("ESMALTES_MERCADO_PAUSA_SEG", "1.5"))
ESMALTES_MERCADO_ALERTA_RESUMO = os.getenv("ESMALTES_MERCADO_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_MERCADO_ALERTA_COOLDOWN_SEG = int(os.getenv("ESMALTES_MERCADO_ALERTA_COOLDOWN_SEG", "14400"))
ESMALTES_MERCADO_VENDAS_MIN = int(os.getenv("ESMALTES_MERCADO_VENDAS_MIN", "5"))
ESMALTES_MERCADO_ABAIXO_CONCORRENTE_PCT = float(os.getenv("ESMALTES_MERCADO_ABAIXO_CONCORRENTE_PCT", "2.0"))

# Comparativo Anita vs Impala (demanda, consumidor, plano para vencer)
COMPARATIVO_ESMALTES_CATALOGO = os.getenv(
    "COMPARATIVO_ESMALTES_CATALOGO", "catalogo/anita_impala_comparativo_segmentos.json"
)
COMPARATIVO_ESMALTES_PAUSA_SEG = float(os.getenv("COMPARATIVO_ESMALTES_PAUSA_SEG", "1.5"))
COMPARATIVO_ESMALTES_ALERTA_RESUMO = os.getenv("COMPARATIVO_ESMALTES_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
COMPARATIVO_ESMALTES_ALERTA_COOLDOWN_SEG = int(os.getenv("COMPARATIVO_ESMALTES_ALERTA_COOLDOWN_SEG", "14400"))

# Comparativo Mercado Livre × Shopee (esmaltes + filamentos 3D)
COMPARATIVO_ML_SHOPEE_CATALOGO = os.getenv(
    "COMPARATIVO_ML_SHOPEE_CATALOGO", "catalogo/comparativo_ml_shopee_categorias.json"
)
COMPARATIVO_ML_SHOPEE_PAUSA_SEG = float(os.getenv("COMPARATIVO_ML_SHOPEE_PAUSA_SEG", "1.5"))
COMPARATIVO_ML_SHOPEE_ALERTA_RESUMO = os.getenv("COMPARATIVO_ML_SHOPEE_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
COMPARATIVO_ML_SHOPEE_ALERTA_COOLDOWN_SEG = int(os.getenv("COMPARATIVO_ML_SHOPEE_ALERTA_COOLDOWN_SEG", "21600"))

# Monitor filamentos 3D no Mercado Livre (preços, marcas, vendas)
FILAMENTOS_ML_CATALOGO = os.getenv(
    "FILAMENTOS_ML_CATALOGO", "catalogo/filamentos_3d_monitor.json"
)
FILAMENTOS_ML_PAUSA_SEG = float(os.getenv("FILAMENTOS_ML_PAUSA_SEG", "1.5"))
FILAMENTOS_ML_ALERTA_RESUMO = os.getenv("FILAMENTOS_ML_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# 5h — permite 3 janelas/dia (08/14/21 BRT) sem engolir a 2ª/3ª mensagem
FILAMENTOS_ML_ALERTA_COOLDOWN_SEG = int(os.getenv("FILAMENTOS_ML_ALERTA_COOLDOWN_SEG", "18000"))
FILAMENTOS_ML_CRUZAR_ALIBABA = os.getenv("FILAMENTOS_ML_CRUZAR_ALIBABA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
FILAMENTOS_ML_ALIBABA_MAX_CORES = int(os.getenv("FILAMENTOS_ML_ALIBABA_MAX_CORES", "3"))
FILAMENTOS_ML_ALIBABA_PAUSA_SEG = float(os.getenv("FILAMENTOS_ML_ALIBABA_PAUSA_SEG", "1.0"))
# Sourcing filamento: compra BR vs importação China (landed)
FILAMENTOS_SOURCING_ATIVO = os.getenv("FILAMENTOS_SOURCING_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
FILAMENTOS_SOURCING_CATALOGO_BR = os.getenv(
    "FILAMENTOS_SOURCING_CATALOGO_BR", "catalogo/filamentos_fornecedores_br.json"
)
FILAMENTOS_SOURCING_NCM = os.getenv("FILAMENTOS_SOURCING_NCM", "39169090")
FILAMENTOS_SOURCING_II_PCT = float(os.getenv("FILAMENTOS_SOURCING_II_PCT", "12.6"))
FILAMENTOS_SOURCING_IPI_PCT = float(os.getenv("FILAMENTOS_SOURCING_IPI_PCT", "0.0"))
FILAMENTOS_SOURCING_ICMS_PCT = float(os.getenv("FILAMENTOS_SOURCING_ICMS_PCT", "18.0"))
FILAMENTOS_SOURCING_MOQ_CHINA = int(os.getenv("FILAMENTOS_SOURCING_MOQ_CHINA", "20"))
FILAMENTOS_SOURCING_TAXA_ML_PCT = float(os.getenv("FILAMENTOS_SOURCING_TAXA_ML_PCT", "16.0"))
FILAMENTOS_SOURCING_MARGEM_MIN_PCT = float(os.getenv("FILAMENTOS_SOURCING_MARGEM_MIN_PCT", "15.0"))
# Importação filamento: CNPJ Masterprint (demais produtos) — CEP via IMPORTACAO_DESTINO_CEP
FILAMENTOS_IMPORTACAO_CNPJ = os.getenv(
    "FILAMENTOS_IMPORTACAO_CNPJ", DEMAIS_PRODUTOS_CNPJ or "23811261000197"
).strip()
# Monitor Masterprint PETG no ML
MASTERPRINT_PETG_CATALOGO = os.getenv(
    "MASTERPRINT_PETG_CATALOGO", "catalogo/masterprint_petg_monitor.json"
)
MASTERPRINT_PETG_CUSTOS = os.getenv(
    "MASTERPRINT_PETG_CUSTOS", "catalogo/masterprint_petg_custos.json"
)
MASTERPRINT_PETG_PAUSA_SEG = float(os.getenv("MASTERPRINT_PETG_PAUSA_SEG", "1.5"))
MASTERPRINT_PETG_ALERTA_RESUMO = os.getenv("MASTERPRINT_PETG_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
MASTERPRINT_PETG_ALERTA_COOLDOWN_SEG = int(os.getenv("MASTERPRINT_PETG_ALERTA_COOLDOWN_SEG", "18000"))
MASTERPRINT_PETG_TOP_N = int(os.getenv("MASTERPRINT_PETG_TOP_N", "10"))
# Monitor Masterprint pincéis recarregáveis + apagadores
MASTERPRINT_ESCRITORIO_CATALOGO = os.getenv(
    "MASTERPRINT_ESCRITORIO_CATALOGO", "catalogo/masterprint_escritorio_monitor.json"
)
MASTERPRINT_ESCRITORIO_CUSTOS = os.getenv(
    "MASTERPRINT_ESCRITORIO_CUSTOS", "catalogo/masterprint_escritorio_custos.json"
)
MASTERPRINT_ESCRITORIO_PAUSA_SEG = float(os.getenv("MASTERPRINT_ESCRITORIO_PAUSA_SEG", "1.5"))
MASTERPRINT_ESCRITORIO_ALERTA_RESUMO = os.getenv(
    "MASTERPRINT_ESCRITORIO_ALERTA_RESUMO", "1"
).strip().lower() not in (
    "0",
    "false",
    "no",
)
MASTERPRINT_ESCRITORIO_ALERTA_COOLDOWN_SEG = int(
    os.getenv("MASTERPRINT_ESCRITORIO_ALERTA_COOLDOWN_SEG", "18000")
)
MASTERPRINT_ESCRITORIO_TOP_N = int(os.getenv("MASTERPRINT_ESCRITORIO_TOP_N", "10"))
# Claude em Masterprint: 1×/dia por agente (default ON). Reserva orçamento para esmaltes.
MASTERPRINT_CLAUDE_DIARIO = os.getenv("MASTERPRINT_CLAUDE_DIARIO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Alias legado
MASTERPRINT_CLAUDE_SECUNDARIO = os.getenv(
    "MASTERPRINT_CLAUDE_SECUNDARIO",
    "1" if MASTERPRINT_CLAUDE_DIARIO else "0",
).strip().lower() not in (
    "0",
    "false",
    "no",
)
MASTERPRINT_CLAUDE_RESTANTE_MIN_USD = float(os.getenv("MASTERPRINT_CLAUDE_RESTANTE_MIN_USD", "2.50"))
# Nova análise Claude só na janela noturna BRT (20–23); manhã/tarde reusam cache
MASTERPRINT_CLAUDE_SO_NOITE = os.getenv("MASTERPRINT_CLAUDE_SO_NOITE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
MASTERPRINT_CLAUDE_NOITE_HORA_INI = int(os.getenv("MASTERPRINT_CLAUDE_NOITE_HORA_INI", "20"))
MASTERPRINT_CLAUDE_NOITE_HORA_FIM = int(os.getenv("MASTERPRINT_CLAUDE_NOITE_HORA_FIM", "23"))
# Ramo / conta / CNPJ separados do esmaltes (opcional)
MASTERPRINT_RAMO_CATALOGO = os.getenv(
    "MASTERPRINT_RAMO_CATALOGO", "catalogo/masterprint_ramo.json"
)
MASTERPRINT_CNPJ = os.getenv("MASTERPRINT_CNPJ", DEMAIS_PRODUTOS_CNPJ or "23811261000197").strip()
MASTERPRINT_RAZAO_SOCIAL = os.getenv("MASTERPRINT_RAZAO_SOCIAL", "").strip()
MASTERPRINT_NOME_FANTASIA = os.getenv("MASTERPRINT_NOME_FANTASIA", "").strip()
MASTERPRINT_ML_SELLER_ID = os.getenv("MASTERPRINT_ML_SELLER_ID", "").strip()
MASTERPRINT_ML_NICKNAME = os.getenv("MASTERPRINT_ML_NICKNAME", "").strip()
MASTERPRINT_SHOPEE_SHOP_ID = os.getenv("MASTERPRINT_SHOPEE_SHOP_ID", "").strip()
MASTERPRINT_MAGALU_SELLER_ID = os.getenv("MASTERPRINT_MAGALU_SELLER_ID", "").strip()
MASTERPRINT_AMAZON_SELLER_ID = os.getenv("MASTERPRINT_AMAZON_SELLER_ID", "").strip()
# Se vazio, usa TELEGRAM_GESTOR_CHAT_ID (mesmo chat dos esmaltes)
MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID = os.getenv("MASTERPRINT_TELEGRAM_GESTOR_CHAT_ID", "").strip()

# Busca kit esmaltes Anita/Impala — frequência diária + cores
ESMALTES_BUSCA_KIT_CATALOGO = os.getenv(
    "ESMALTES_BUSCA_KIT_CATALOGO", "catalogo/esmaltes_busca_kit_frequencia.json"
)
ESMALTES_BUSCA_KIT_PAUSA_SEG = float(os.getenv("ESMALTES_BUSCA_KIT_PAUSA_SEG", "1.5"))
ESMALTES_BUSCA_KIT_ALERTA_RESUMO = os.getenv("ESMALTES_BUSCA_KIT_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_BUSCA_KIT_ALERTA_COOLDOWN_SEG = int(os.getenv("ESMALTES_BUSCA_KIT_ALERTA_COOLDOWN_SEG", "18000"))
# Tolerância de imprecisão nos anúncios retornados (0.10 = até ~10% fora da marca/kit)
ESMALTES_BUSCA_KIT_TOLERANCIA_ERRO = float(os.getenv("ESMALTES_BUSCA_KIT_TOLERANCIA_ERRO", "0.10"))

# Monitor kits esmaltes — vendas, preços e ranking de marcas no ML
ESMALTES_KITS_MONITOR_CATALOGO = os.getenv(
    "ESMALTES_KITS_MONITOR_CATALOGO", "catalogo/esmaltes_kits_monitor.json"
)
ESMALTES_KITS_MONITOR_PAUSA_SEG = float(os.getenv("ESMALTES_KITS_MONITOR_PAUSA_SEG", "1.5"))
ESMALTES_KITS_MONITOR_ALERTA_RESUMO = os.getenv("ESMALTES_KITS_MONITOR_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG = int(os.getenv("ESMALTES_KITS_MONITOR_ALERTA_COOLDOWN_SEG", "18000"))

# Montar kits Impala — planilha NCM × kits mais vendidos no ML
MONTAR_KITS_IMPALA_PLANILHA = os.getenv(
    "MONTAR_KITS_IMPALA_PLANILHA", "dados/Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx"
)
MONTAR_KITS_IMPALA_ALERTA = os.getenv("MONTAR_KITS_IMPALA_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
MONTAR_KITS_IMPALA_COOLDOWN_SEG = int(os.getenv("MONTAR_KITS_IMPALA_COOLDOWN_SEG", "18000"))
MONTAR_KITS_IMPALA_TOP_KITS = int(os.getenv("MONTAR_KITS_IMPALA_TOP_KITS", "40"))

# Planilhas ecommerce (Consolidado Impala/Cruzeiro) → catálogo + invest validação
PLANILHAS_ECOMMERCE_CONSOLIDADO = os.getenv(
    "PLANILHAS_ECOMMERCE_CONSOLIDADO",
    "planilhas_ecommerce/Consolidado_Impala_Cruzeiro.xlsx",
)
PLANILHAS_ECOMMERCE_SYNC_ATIVO = os.getenv(
    "PLANILHAS_ECOMMERCE_SYNC_ATIVO", "1"
).strip().lower() not in ("0", "false", "no")

# Ecossistema esmaltes — plano consolidado (cor → kit → anexos → B2B)
ECOSSISTEMA_ESMALTES_ATIVO = os.getenv("ECOSSISTEMA_ESMALTES_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ECOSSISTEMA_ESMALTES_ALERTA = os.getenv("ECOSSISTEMA_ESMALTES_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ECOSSISTEMA_ESMALTES_COOLDOWN_SEG = int(os.getenv("ECOSSISTEMA_ESMALTES_COOLDOWN_SEG", "43200"))

# Crescimento esmaltes — KPI + kits sem MLB + checklist
CRESCIMENTO_ESMALTES_ATIVO = os.getenv("CRESCIMENTO_ESMALTES_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CRESCIMENTO_ESMALTES_ALERTA = os.getenv("CRESCIMENTO_ESMALTES_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CRESCIMENTO_ESMALTES_COOLDOWN_SEG = int(os.getenv("CRESCIMENTO_ESMALTES_COOLDOWN_SEG", "86400"))
CRESCIMENTO_ESMALTES_META_KITS_PCT = float(os.getenv("CRESCIMENTO_ESMALTES_META_KITS_PCT", "40"))
CRESCIMENTO_ESMALTES_META_MARGEM_PCT = float(os.getenv("CRESCIMENTO_ESMALTES_META_MARGEM_PCT", "15"))
CRESCIMENTO_ESMALTES_COMBO_ANEXO = os.getenv("CRESCIMENTO_ESMALTES_COMBO_ANEXO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Decisão do dia — um veredito FAZER / NÃO FAZER / CUSTO
DECISAO_DIA_ESMALTES_ATIVO = os.getenv("DECISAO_DIA_ESMALTES_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
DECISAO_DIA_ESMALTES_ALERTA = os.getenv("DECISAO_DIA_ESMALTES_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
DECISAO_DIA_ESMALTES_COOLDOWN_SEG = int(os.getenv("DECISAO_DIA_ESMALTES_COOLDOWN_SEG", "86400"))
DECISAO_DIA_ESMALTES_GUERRA_CATALOGO = os.getenv(
    "DECISAO_DIA_ESMALTES_GUERRA_CATALOGO", "catalogo/skus_guerra_impala.json"
)
# Operação consolidada (crescimento + decisão + ecossistema → 1 Telegram)
ESMALTES_OPERACAO_ATIVO = os.getenv("ESMALTES_OPERACAO_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_OPERACAO_ALERTA = os.getenv("ESMALTES_OPERACAO_ALERTA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_OPERACAO_COOLDOWN_SEG = int(os.getenv("ESMALTES_OPERACAO_COOLDOWN_SEG", "18000"))
# Alibaba busca + inteligência em um run
ALIBABA_SOURCING_ATIVO = os.getenv("ALIBABA_SOURCING_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Contrato impulso ML (ads/promo só com SKU guerra + MLB)
CONTRATO_IMPULSO_ML_ATIVO = os.getenv("CONTRATO_IMPULSO_ML_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Eventos tipados do algoritmo → chat / congelar preço / listing
ALGORITMO_EVENTOS_ATIVO = os.getenv("ALGORITMO_EVENTOS_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Otimizador listing: aplicar título após SIM do gestor (default off)
OTIMIZADOR_LISTING_APLICAR = os.getenv("OTIMIZADOR_LISTING_APLICAR", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Monitor removedores de unha — nomes, fabricantes e ranking por vendas
REMOVEDORES_UNHA_CATALOGO = os.getenv(
    "REMOVEDORES_UNHA_CATALOGO", "catalogo/removedores_unha_monitor.json"
)
REMOVEDORES_UNHA_PAUSA_SEG = float(os.getenv("REMOVEDORES_UNHA_PAUSA_SEG", "1.5"))
REMOVEDORES_UNHA_ALERTA_RESUMO = os.getenv("REMOVEDORES_UNHA_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
REMOVEDORES_UNHA_ALERTA_COOLDOWN_SEG = int(os.getenv("REMOVEDORES_UNHA_ALERTA_COOLDOWN_SEG", "18000"))
REMOVEDORES_UNHA_TOLERANCIA_ERRO = float(os.getenv("REMOVEDORES_UNHA_TOLERANCIA_ERRO", "0.10"))
REMOVEDORES_UNHA_IA_AVALIAR = os.getenv("REMOVEDORES_UNHA_IA_AVALIAR", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Busca multi-marketplace (ML + Magalu + Shopee + Amazon) para esmaltes/removedores
MARKETPLACES_BUSCA_ATIVOS = os.getenv(
    "MARKETPLACES_BUSCA_ATIVOS", "mercadolivre,magalu,shopee,amazon"
).strip()
ESMALTES_BUSCA_MULTI_MARKETPLACE = os.getenv("ESMALTES_BUSCA_MULTI_MARKETPLACE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Monitor tendências esmaltes — web aberta × marketplaces
ESMALTES_TENDENCIAS_CATALOGO = os.getenv(
    "ESMALTES_TENDENCIAS_CATALOGO", "catalogo/esmaltes_tendencias_internet.json"
)
ESMALTES_TENDENCIAS_PAUSA_SEG = float(os.getenv("ESMALTES_TENDENCIAS_PAUSA_SEG", "2.0"))
ESMALTES_TENDENCIAS_ALERTA_RESUMO = os.getenv("ESMALTES_TENDENCIAS_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ESMALTES_TENDENCIAS_ALERTA_COOLDOWN_SEG = int(os.getenv("ESMALTES_TENDENCIAS_ALERTA_COOLDOWN_SEG", "18000"))

# Monitor Acetona Cruzeiro no ML (vendedores, margem, estratégias Claude + Impala)
ACETONA_CRUZEIRO_CATALOGO = os.getenv(
    "ACETONA_CRUZEIRO_CATALOGO", "catalogo/acetona_cruzeiro_monitor.json"
)
ACETONA_CRUZEIRO_MANICURES_CATALOGO = os.getenv(
    "ACETONA_CRUZEIRO_MANICURES_CATALOGO", "catalogo/manicures_brasil_referencia.json"
)
ACETONA_CRUZEIRO_PAUSA_SEG = float(os.getenv("ACETONA_CRUZEIRO_PAUSA_SEG", "1.5"))
ACETONA_CRUZEIRO_ALERTA_RESUMO = os.getenv("ACETONA_CRUZEIRO_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ACETONA_CRUZEIRO_ALERTA_COOLDOWN_SEG = int(os.getenv("ACETONA_CRUZEIRO_ALERTA_COOLDOWN_SEG", "14400"))

LEILAO_VEICULOS_CATALOGO = os.getenv(
    "LEILAO_VEICULOS_CATALOGO", "catalogo/leiloes_veiculos_monitorados.json"
)
LEILAO_PAUSA_ENTRE_FONTES_SEG = float(os.getenv("LEILAO_PAUSA_ENTRE_FONTES_SEG", "3.0"))
LEILAO_DETRAN_POR_RODADA = int(os.getenv("LEILAO_DETRAN_POR_RODADA", "5"))
LEILAO_LEILOEIROS_POR_RODADA = int(os.getenv("LEILAO_LEILOEIROS_POR_RODADA", "5"))
# DETRAN via DDG (site:detran.xx.gov.br). Se 0, só Sumaré/diretos cobrem DETRAN.
LEILAO_DETRAN_VIA_DDG = os.getenv("LEILAO_DETRAN_VIA_DDG", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# 2ª query DETRAN mais ampla se a busca com o veículo específico vier vazia
LEILAO_DETRAN_DDG_AMPLA = os.getenv("LEILAO_DETRAN_DDG_AMPLA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Não martela DDG quando o circuit breaker já está ativo
LEILAO_PULAR_DDG_SE_BREAKER = os.getenv("LEILAO_PULAR_DDG_SE_BREAKER", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_INCLUIR_SUMARE_DIRETO = os.getenv("LEILAO_INCLUIR_SUMARE_DIRETO", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_INCLUIR_COPART_DIRETO = os.getenv("LEILAO_INCLUIR_COPART_DIRETO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_INCLUIR_SUPERBID_DIRETO = os.getenv("LEILAO_INCLUIR_SUPERBID_DIRETO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_INCLUIR_SODRE_DIRETO = os.getenv("LEILAO_INCLUIR_SODRE_DIRETO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_SUMARE_MAX_LEILOES = int(os.getenv("LEILAO_SUMARE_MAX_LEILOES", "10"))
LEILAO_COLETORES_LANCE_MIN_BRL = float(os.getenv("LEILAO_COLETORES_LANCE_MIN_BRL", "500"))
LEILAO_COLETORES_EXIGIR_DOCUMENTO = os.getenv(
    "LEILAO_COLETORES_EXIGIR_DOCUMENTO", "0"
).strip().lower() not in ("0", "false", "no")
COPART_LEILOES_CATALOGO = os.getenv(
    "COPART_LEILOES_CATALOGO", "catalogo/copart_leiloes_monitorados.json"
)
SUPERBID_LEILOES_CATALOGO = os.getenv(
    "SUPERBID_LEILOES_CATALOGO", "catalogo/superbid_leiloes_monitorados.json"
)
SODRE_LEILOES_CATALOGO = os.getenv(
    "SODRE_LEILOES_CATALOGO", "catalogo/sodre_leiloes_monitorados.json"
)
LEILAO_DDG_RETRY_MAX = int(os.getenv("LEILAO_DDG_RETRY_MAX", os.getenv("DDG_RETRY_MAX", "3")))
LEILAO_DDG_RETRY_BASE_SEG = float(os.getenv("LEILAO_DDG_RETRY_BASE_SEG", os.getenv("DDG_RETRY_BASE_SEG", "5")))
LEILAO_ALERTA_RESUMO = os.getenv("LEILAO_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
LEILAO_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("LEILAO_ALERTA_RESUMO_COOLDOWN_SEG", "3600"))
LEILAO_ANO_MIN = int(os.getenv("LEILAO_ANO_MIN", "1995"))
LEILAO_ANO_MAX = int(os.getenv("LEILAO_ANO_MAX", "2020"))
LEILAO_BUSCA_TODOS_VEICULOS = os.getenv("LEILAO_BUSCA_TODOS_VEICULOS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_VARREDURA_TODAS_FONTES = os.getenv("LEILAO_VARREDURA_TODAS_FONTES", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_ALERTAR_TODOS_ACHADOS = os.getenv("LEILAO_ALERTAR_TODOS_ACHADOS", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_ALERTA_TOP_N = int(os.getenv("LEILAO_ALERTA_TOP_N", "8"))
# Haircut na FIPE para veículos sinistrados/recuperados (0–100)
LEILAO_FIPE_HAIRCUT_SINISTRO_PCT = float(os.getenv("LEILAO_FIPE_HAIRCUT_SINISTRO_PCT", "40"))
CARROS_BATIDOS_ALERTA_TOP_N = int(os.getenv("CARROS_BATIDOS_ALERTA_TOP_N", "10"))
CARROS_BATIDOS_FIPE_HAIRCUT_PCT = float(os.getenv("CARROS_BATIDOS_FIPE_HAIRCUT_PCT", "40"))

# Leilão × FIPE (lance + taxas vs tabela)
LEILAO_COMISSAO_PCT = float(os.getenv("LEILAO_COMISSAO_PCT", "5.0"))
LEILAO_TAXA_CADASTRO_BRL = float(os.getenv("LEILAO_TAXA_CADASTRO_BRL", "400.0"))
LEILAO_TAXA_ADMIN_BRL = float(os.getenv("LEILAO_TAXA_ADMIN_BRL", "150.0"))
LEILAO_REMOCAO_ESTADIA_BRL = float(os.getenv("LEILAO_REMOCAO_ESTADIA_BRL", "350.0"))
LEILAO_LAUDO_BRL = float(os.getenv("LEILAO_LAUDO_BRL", "200.0"))
LEILAO_PRECO_MAX_LANCE = float(os.getenv("LEILAO_PRECO_MAX_LANCE", "35000"))
LEILAO_MARGEM_FIPE_MIN_PCT = float(os.getenv("LEILAO_MARGEM_FIPE_MIN_PCT", "10"))
LEILAO_MARGEM_FIPE_MIN_REAIS = float(os.getenv("LEILAO_MARGEM_FIPE_MIN_REAIS", "800"))
_LEILAO_IA_AVALIAR_ENV = os.getenv("LEILAO_IA_AVALIAR_PARAMETROS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LEILAO_IA_AVALIAR_PARAMETROS = _LEILAO_IA_AVALIAR_ENV and bool(ANTHROPIC_API_KEY)

# Sumaré Leilões (PREFEITURA/DETRAN — veículos com documento)
SUMARE_LEILOES_CATALOGO = os.getenv(
    "SUMARE_LEILOES_CATALOGO", "catalogo/sumare_leiloes_monitorados.json"
)
SUMARE_LEILOES_LANCE_MIN_BRL = float(os.getenv("SUMARE_LEILOES_LANCE_MIN_BRL", "500"))
SUMARE_LEILOES_PAUSA_ENTRE_LEILOES_SEG = float(os.getenv("SUMARE_LEILOES_PAUSA_ENTRE_LEILOES_SEG", "2.5"))
SUMARE_LEILOES_PAUSA_PAGINAS_SEG = float(os.getenv("SUMARE_LEILOES_PAUSA_PAGINAS_SEG", "0.8"))
SUMARE_LEILOES_TIMEOUT_SEG = float(os.getenv("SUMARE_LEILOES_TIMEOUT_SEG", "45"))
SUMARE_LEILOES_RETRY_MAX = int(os.getenv("SUMARE_LEILOES_RETRY_MAX", "3"))
SUMARE_LEILOES_ALERTA_COOLDOWN_SEG = int(os.getenv("SUMARE_LEILOES_ALERTA_COOLDOWN_SEG", "7200"))
SUMARE_LEILOES_ALERTA_RESUMO = os.getenv("SUMARE_LEILOES_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# DuckDuckGo Lite (compartilhado leilão + Alibaba)
DDG_MIN_INTERVAL_SEG = float(os.getenv("DDG_MIN_INTERVAL_SEG", "3.0"))
DDG_RETRY_MAX = int(os.getenv("DDG_RETRY_MAX", "3"))
DDG_RETRY_BASE_SEG = float(os.getenv("DDG_RETRY_BASE_SEG", "5"))
DDG_CIRCUIT_BREAKER_SEG = float(os.getenv("DDG_CIRCUIT_BREAKER_SEG", "300"))
DDG_FALHAS_403_PARA_BREAKER = int(os.getenv("DDG_FALHAS_403_PARA_BREAKER", "5"))
# lite = GET lite.duckduckgo.com | html = POST html.duckduckgo.com | auto = lite depois html
DDG_BACKEND = os.getenv("DDG_BACKEND", "lite").strip().lower()
DDG_DISABLED = os.getenv("DDG_DISABLED", "").strip().lower() in ("1", "true", "yes")
# Alibaba: pula DDG só se a busca direta já trouxe muitos itens
DDG_ALIBABA_SKIP_SE_DIRETO = os.getenv("DDG_ALIBABA_SKIP_SE_DIRETO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
DDG_ALIBABA_MIN_DIRETO_PARA_PULAR = int(os.getenv("DDG_ALIBABA_MIN_DIRETO_PARA_PULAR", "12"))

# Telegram — circuit breaker após token inválido (evita centenas de ERROR no Datadog)
TELEGRAM_CIRCUIT_BREAKER_SEG = int(os.getenv("TELEGRAM_CIRCUIT_BREAKER_SEG", "3600"))

ALIBABA_IMPORTACAO_CATALOGO = os.getenv(
    "ALIBABA_IMPORTACAO_CATALOGO", "catalogo/alibaba_produtos_importacao.json"
)
ALIBABA_PAUSA_ENTRE_BUSCAS_SEG = float(os.getenv("ALIBABA_PAUSA_ENTRE_BUSCAS_SEG", "1.0"))
ALIBABA_ALERTA_RESUMO = os.getenv("ALIBABA_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG", "7200"))
# Busca direta: mais resultados/páginas; termo EN principal + PT secundário
ALIBABA_BUSCA_MAX_RESULTADOS = int(os.getenv("ALIBABA_BUSCA_MAX_RESULTADOS", "40"))
ALIBABA_BUSCA_PAGINAS = int(os.getenv("ALIBABA_BUSCA_PAGINAS", "3"))
ALIBABA_PREFERIR_TERMO_PT = os.getenv("ALIBABA_PREFERIR_TERMO_PT", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)
ALIBABA_BUSCAR_TERMO_SECUNDARIO = os.getenv("ALIBABA_BUSCAR_TERMO_SECUNDARIO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ALIBABA_TELEGRAM_MAX_NOVOS = int(os.getenv("ALIBABA_TELEGRAM_MAX_NOVOS", "12"))

# Câmbio USD/BRL
CAMBIO_API_URL = os.getenv(
    "CAMBIO_API_URL", "https://economia.awesomeapi.com.br/json/last/USD-BRL"
).strip()
CAMBIO_HISTORICO_MAX = int(os.getenv("CAMBIO_HISTORICO_MAX", "500"))
CAMBIO_FALLBACK_USD_BRL = float(os.getenv("CAMBIO_FALLBACK_USD_BRL", os.getenv("DESCOBERTA_CAMBIO_USD_BRL", "5.5")))
CAMBIO_ALERTA_VARIACAO_PCT = float(os.getenv("CAMBIO_ALERTA_VARIACAO_PCT", "1.5"))
# Se 1, margem/alertas de importação não usam câmbio fallback (só awesomeapi)
CAMBIO_BLOQUEAR_FALLBACK_MARGEM = os.getenv("CAMBIO_BLOQUEAR_FALLBACK_MARGEM", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CAMBIO_MAX_IDADE_SEG = int(os.getenv("CAMBIO_MAX_IDADE_SEG", "21600"))  # 6h
ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE = os.getenv(
    "ALIBABA_EXIGIR_MOQ_PARA_OPORTUNIDADE", "0"
).strip().lower() not in ("0", "false", "no")

# Custo landed importação (China → Brasil)
IMPORTACAO_II_PCT_DEFAULT = float(os.getenv("IMPORTACAO_II_PCT_DEFAULT", "16.0"))
IMPORTACAO_IPI_PCT_DEFAULT = float(os.getenv("IMPORTACAO_IPI_PCT_DEFAULT", "0.0"))
IMPORTACAO_PIS_PCT = float(os.getenv("IMPORTACAO_PIS_PCT", "2.1"))
IMPORTACAO_COFINS_PCT = float(os.getenv("IMPORTACAO_COFINS_PCT", "9.65"))
IMPORTACAO_ICMS_PCT = float(os.getenv("IMPORTACAO_ICMS_PCT", "18.0"))
IMPORTACAO_SEGURO_PCT = float(os.getenv("IMPORTACAO_SEGURO_PCT", "0.5"))
IMPORTACAO_SISCOMEX_BRL = float(os.getenv("IMPORTACAO_SISCOMEX_BRL", "154.23"))
# Nº de adições na DI/DUIMP (Taxa Siscomex — Portaria ME 4.131/2021 + IN RFB 2.024/2021)
# 1 adição → R$ 115,67 + R$ 38,56 = R$ 154,23 (não usar mais o legado 214,50)
IMPORTACAO_SISCOMEX_ADICOES = int(os.getenv("IMPORTACAO_SISCOMEX_ADICOES", "1") or "1")
IMPORTACAO_DESEMBARACO_BRL = float(os.getenv("IMPORTACAO_DESEMBARACO_BRL", "800.0"))
# AFRMM (Lei 10.893/2004 art. 6º c/ Lei 14.301/2022) — 8% frete longo curso; 0 no aéreo
IMPORTACAO_AFRMM_PCT = float(os.getenv("IMPORTACAO_AFRMM_PCT", "8.0"))
IMPORTACAO_FRETE_MARITIMO_USD_KG = float(os.getenv("IMPORTACAO_FRETE_MARITIMO_USD_KG", "0.85"))
IMPORTACAO_FRETE_AEREO_USD_KG = float(os.getenv("IMPORTACAO_FRETE_AEREO_USD_KG", "5.5"))
IMPORTACAO_FRETE_NACIONAL_BRL = float(os.getenv("IMPORTACAO_FRETE_NACIONAL_BRL", "12.0"))
IMPORTACAO_OPERACAO_FIXA_CATALOGO = os.getenv(
    "IMPORTACAO_OPERACAO_FIXA_CATALOGO", "catalogo/importacao_operacao_fixa.json"
)
# Planilha PLUS BRASIL (custos na importação) — inputs + checklist de despesas
IMPORTACAO_PLANILHA_PLUS = os.getenv(
    "IMPORTACAO_PLANILHA_PLUS", "dados/importacao_simula_plus_brasil.xlsx"
).strip()
IMPORTACAO_DESPESAS_PLUS_CATALOGO = os.getenv(
    "IMPORTACAO_DESPESAS_PLUS_CATALOGO", "catalogo/importacao_despesas_plus.json"
).strip()
# CNPJ importador (default = dono produtos / esmaltes) — atrela CNAE × marketplaces
IMPORTACAO_CNPJ = os.getenv("IMPORTACAO_CNPJ", CNPJ_DONO_PRODUTOS or ESMALTES_CNPJ or "52668583000127").strip()
IMPORTACAO_RESPONSAVEL_NOME = os.getenv("IMPORTACAO_RESPONSAVEL_NOME", "").strip()
IMPORTACAO_RESPONSAVEL_CARGO = os.getenv("IMPORTACAO_RESPONSAVEL_CARGO", "").strip()
IMPORTACAO_RESPONSAVEL_CONTATO = os.getenv("IMPORTACAO_RESPONSAVEL_CONTATO", "").strip()
# Destino da operação formal (default Americana/SP CEP 13467-694) — sobrescreve o JSON
IMPORTACAO_AEROPORTO_CODIGO = os.getenv("IMPORTACAO_AEROPORTO_CODIGO", "").strip().upper()
IMPORTACAO_AEROPORTO_NOME = os.getenv("IMPORTACAO_AEROPORTO_NOME", "").strip()
IMPORTACAO_AEROPORTO_CIDADE = os.getenv("IMPORTACAO_AEROPORTO_CIDADE", "").strip()
IMPORTACAO_AEROPORTO_UF = os.getenv("IMPORTACAO_AEROPORTO_UF", "").strip().upper()
IMPORTACAO_DESTINO_CEP = os.getenv("IMPORTACAO_DESTINO_CEP", "13467-694").strip()
IMPORTACAO_DESTINO_CIDADE = os.getenv("IMPORTACAO_DESTINO_CIDADE", "").strip()
IMPORTACAO_DESTINO_UF = os.getenv("IMPORTACAO_DESTINO_UF", "").strip().upper()
IMPORTACAO_DESTINO_KM_VIRACOPOS = os.getenv("IMPORTACAO_DESTINO_KM_VIRACOPOS", "").strip()
# Importação formal aérea CNPJ (Viracopos) — substitui landed simplificado no modo aéreo
IMPORTACAO_AEREO_FORMAL = os.getenv("IMPORTACAO_AEREO_FORMAL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Portos/aeroportos BR — comparação multi-gateway referenciada em Alibaba
IMPORTACAO_PORTOS_BRASIL_CATALOGO = os.getenv(
    "IMPORTACAO_PORTOS_BRASIL_CATALOGO", "catalogo/portos_aeroportos_brasil.json"
)
IMPORTACAO_PORTOS_SCORE_MIN_ATRATIVA = float(os.getenv("IMPORTACAO_PORTOS_SCORE_MIN_ATRATIVA", "55.0"))
IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA = float(os.getenv("IMPORTACAO_PORTOS_MARKUP_MAX_ATRATIVA", "2.2"))
# Abaixo deste % a decisão exige custo detalhado (frete/impostos/locais) com peso ≥85% no score
IMPORTACAO_PORTOS_ASSERTIVIDADE_ALVO = float(os.getenv("IMPORTACAO_PORTOS_ASSERTIVIDADE_ALVO", "90.0"))
IMPORTACAO_PORTOS_PESO_CUSTO_BAIXA_ASSERT = float(
    os.getenv("IMPORTACAO_PORTOS_PESO_CUSTO_BAIXA_ASSERT", "0.85")
)
IMPORTACAO_PORTOS_COMPARAR_ATIVO = os.getenv("IMPORTACAO_PORTOS_COMPARAR_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# Endereço comercial Paraguai + corredor terrestre → BR (Mercosul)
IMPORTACAO_PY_ATIVO = os.getenv("IMPORTACAO_PY_ATIVO", "1").strip().lower() not in ("0", "false", "no")
IMPORTACAO_PY_ENDERECO = os.getenv("IMPORTACAO_PY_ENDERECO", "").strip()
IMPORTACAO_PY_CIDADE = os.getenv("IMPORTACAO_PY_CIDADE", "").strip()
IMPORTACAO_PY_DEPARTAMENTO = os.getenv("IMPORTACAO_PY_DEPARTAMENTO", "").strip()
IMPORTACAO_PY_CODIGO_POSTAL = os.getenv("IMPORTACAO_PY_CODIGO_POSTAL", "").strip()
# Hub PY multi-cliente / marketplaces (estrutura futura — catalogo/hub_paraguai_clientes.json)
HUB_PARAGUAI_CATALOGO = os.getenv("HUB_PARAGUAI_CATALOGO", "catalogo/hub_paraguai_clientes.json")
HUB_PARAGUAI_ATIVO = os.getenv("HUB_PARAGUAI_ATIVO", "1").strip().lower() not in ("0", "false", "no")
HUB_PY_FRETE_CHINA_USD_KG = float(os.getenv("HUB_PY_FRETE_CHINA_USD_KG", "1.2"))
# Tributação PY × BR (Mercosul / origem) — estimativas de planejamento
HUB_PY_IVA_PCT = float(os.getenv("HUB_PY_IVA_PCT", "10.0"))
HUB_PY_MAQUILA_PCT = float(os.getenv("HUB_PY_MAQUILA_PCT", "1.0"))
HUB_PY_CERTIFICADO_ORIGEM_BRL = float(os.getenv("HUB_PY_CERTIFICADO_ORIGEM_BRL", "180.0"))
# China marítimo: Santos no SE, portos NE no Nordeste, comparar tributação com Sul
IMPORTACAO_CHINA_ROTA_REGIONAL = os.getenv("IMPORTACAO_CHINA_ROTA_REGIONAL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Alibaba inteligência (câmbio + landed + margem)
ALIBABA_MARGEM_MIN_PCT = float(os.getenv("ALIBABA_MARGEM_MIN_PCT", "18.0"))
ALIBABA_MARGEM_MIN_REAIS = float(os.getenv("ALIBABA_MARGEM_MIN_REAIS", "5.0"))
ALIBABA_MARGEM_ALERTA_COOLDOWN_SEG = int(os.getenv("ALIBABA_MARGEM_ALERTA_COOLDOWN_SEG", "7200"))
ALIBABA_INTELIGENCIA_ALERTA_RESUMO = os.getenv("ALIBABA_INTELIGENCIA_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ALIBABA_INTELIGENCIA_COOLDOWN_SEG = int(os.getenv("ALIBABA_INTELIGENCIA_COOLDOWN_SEG", "7200"))
_ALIBABA_IA_AVALIAR_ENV = os.getenv("ALIBABA_IA_AVALIAR_PARAMETROS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
ALIBABA_IA_AVALIAR_PARAMETROS = _ALIBABA_IA_AVALIAR_ENV and bool(ANTHROPIC_API_KEY)

# ML tendências × Alibaba (vale importar?)
ML_TENDENCIAS_IMPORTACAO_ALERTA_RESUMO = os.getenv(
    "ML_TENDENCIAS_IMPORTACAO_ALERTA_RESUMO", "1"
).strip().lower() not in ("0", "false", "no")
ML_TENDENCIAS_IMPORTACAO_COOLDOWN_SEG = int(os.getenv("ML_TENDENCIAS_IMPORTACAO_COOLDOWN_SEG", "14400"))
ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG = float(os.getenv("ML_TENDENCIAS_IMPORTACAO_PAUSA_SEG", "2.0"))

DESCOBERTA_NICHOS_CATALOGO = os.getenv(
    "DESCOBERTA_NICHOS_CATALOGO", "catalogo/descoberta_nichos.json"
)
DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG = float(os.getenv("DESCOBERTA_PAUSA_ENTRE_ANALISES_SEG", "1.0"))
DESCOBERTA_BUSCAR_ALIBABA = os.getenv("DESCOBERTA_BUSCAR_ALIBABA", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
DESCOBERTA_ALIBABA_MAX_POR_OPORTUNIDADE = int(os.getenv("DESCOBERTA_ALIBABA_MAX_POR_OPORTUNIDADE", "3"))
DESCOBERTA_ALIBABA_PAUSA_SEG = float(os.getenv("DESCOBERTA_ALIBABA_PAUSA_SEG", "0.5"))
DESCOBERTA_ALIBABA_PRECO_MAX_USD = float(os.getenv("DESCOBERTA_ALIBABA_PRECO_MAX_USD", "15"))
DESCOBERTA_ALIBABA_MOQ_MAX = int(os.getenv("DESCOBERTA_ALIBABA_MOQ_MAX", "1000"))
DESCOBERTA_CAMBIO_USD_BRL = float(os.getenv("DESCOBERTA_CAMBIO_USD_BRL", "5.5"))
DESCOBERTA_ALERTA_PAINEL_COOLDOWN_SEG = int(os.getenv("DESCOBERTA_ALERTA_PAINEL_COOLDOWN_SEG", "86400"))

LICITACOES_CATALOGO = os.getenv("LICITACOES_CATALOGO", "catalogo/licitacoes_monitoradas.json")
LICITACOES_PAUSA_ENTRE_FONTES_SEG = float(os.getenv("LICITACOES_PAUSA_ENTRE_FONTES_SEG", "1.5"))
LICITACOES_ALERTA_RESUMO = os.getenv("LICITACOES_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
LICITACOES_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("LICITACOES_ALERTA_RESUMO_COOLDOWN_SEG", "14400"))
LICITACOES_DIAS_PROPOSTA_FRENTE = int(os.getenv("LICITACOES_DIAS_PROPOSTA_FRENTE", "45"))
LICITACOES_MAX_PAGINAS_PNCP = int(os.getenv("LICITACOES_MAX_PAGINAS_PNCP", "2"))
LICITACOES_TAMANHO_PAGINA_PNCP = int(os.getenv("LICITACOES_TAMANHO_PAGINA_PNCP", "50"))
LICITACOES_PNCP_TIMEOUT_SEG = int(os.getenv("LICITACOES_PNCP_TIMEOUT_SEG", "30") or "30")
LICITACOES_PNCP_FALHAS_PARA_BREAKER = int(os.getenv("LICITACOES_PNCP_FALHAS_PARA_BREAKER", "3") or "3")
LICITACOES_PNCP_BREAKER_SEG = float(os.getenv("LICITACOES_PNCP_BREAKER_SEG", "900") or "900")
LICITACOES_BUSCAR_PORTAIS_ESTADUAIS = os.getenv("LICITACOES_BUSCAR_PORTAIS_ESTADUAIS", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Lojas de veículos salvados/batidos + comparação FIPE
LOJAS_VEICULOS_PRECO_MAX = float(os.getenv("LOJAS_VEICULOS_PRECO_MAX", "20000"))
LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT = float(os.getenv("LOJAS_VEICULOS_MARGEM_FIPE_MIN_PCT", "25"))
LOJAS_VEICULOS_MARGEM_FIPE_MIN_REAIS = float(os.getenv("LOJAS_VEICULOS_MARGEM_FIPE_MIN_REAIS", "3000"))
LOJAS_VEICULOS_PAUSA_ENTRE_LOJAS_SEG = float(os.getenv("LOJAS_VEICULOS_PAUSA_ENTRE_LOJAS_SEG", "2"))
LOJAS_VEICULOS_ALERTA_RESUMO = os.getenv("LOJAS_VEICULOS_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
LOJAS_VEICULOS_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("LOJAS_VEICULOS_ALERTA_RESUMO_COOLDOWN_SEG", "7200"))

# Monitor carros batidos — todas as lojas, alerta Telegram
CARROS_BATIDOS_CATALOGO = os.getenv("CARROS_BATIDOS_CATALOGO", "catalogo/carros_batidos_fontes.json")
CARROS_BATIDOS_PRECO_MAX = float(os.getenv("CARROS_BATIDOS_PRECO_MAX", "150000"))
CARROS_BATIDOS_ANO_MIN = int(os.getenv("CARROS_BATIDOS_ANO_MIN", "1998"))
CARROS_BATIDOS_PAUSA_ENTRE_LOJAS_SEG = float(os.getenv("CARROS_BATIDOS_PAUSA_ENTRE_LOJAS_SEG", "2"))
CARROS_BATIDOS_INCLUIR_FIPE = os.getenv("CARROS_BATIDOS_INCLUIR_FIPE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CARROS_BATIDOS_ALERTA_RESUMO = os.getenv("CARROS_BATIDOS_ALERTA_RESUMO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CARROS_BATIDOS_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("CARROS_BATIDOS_ALERTA_RESUMO_COOLDOWN_SEG", "14400"))
CARROS_BATIDOS_ALERTA_COOLDOWN_SEG = int(os.getenv("CARROS_BATIDOS_ALERTA_COOLDOWN_SEG", "86400"))
# Busca web nacional (DDG) — encontra lojas/anúncios de batidos em todo o Brasil
CARROS_BATIDOS_BUSCA_WEB = os.getenv("CARROS_BATIDOS_BUSCA_WEB", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
CARROS_BATIDOS_BUSCA_WEB_MAX_UFS = int(os.getenv("CARROS_BATIDOS_BUSCA_WEB_MAX_UFS", "9"))
CARROS_BATIDOS_BUSCA_WEB_RESULTADOS = int(os.getenv("CARROS_BATIDOS_BUSCA_WEB_RESULTADOS", "8"))
CARROS_BATIDOS_BUSCA_WEB_PAUSA_SEG = float(os.getenv("CARROS_BATIDOS_BUSCA_WEB_PAUSA_SEG", "3"))

FIPE_API_BASE = os.getenv("FIPE_API_BASE", "https://parallelum.com.br/fipe/api/v1").strip()
FIPE_PAUSA_ENTRE_CHAMADAS_SEG = float(os.getenv("FIPE_PAUSA_ENTRE_CHAMADAS_SEG", "0.3"))

# Orquestrador 30 min
ORQUESTRADOR_COOLDOWN_RESUMO_SEG = int(os.getenv("ORQUESTRADOR_COOLDOWN_RESUMO_SEG", "1500"))
ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG = float(os.getenv("ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG", "0.4"))
ORQUESTRADOR_EXCLUIR = {
    x.strip()
    for x in os.getenv(
        "ORQUESTRADOR_EXCLUIR",
        # Rotinas com workflow próprio / secundárias — não repetir no ciclo 30min
        "vigia_datadog,consumo_claude,promocoes_manicures,conversao_manicures,"
        "necessidade_manicures,"
        "relatorio_estrategia_ml,ads_gatilho,resumo_conta_ml,relatorio_manha_ml,"
        "montar_kits_impala,esmaltes_operacao,comparativo_anita_impala,monitor_busca_kit_esmaltes,"
        "leilao,sumare_leiloes,lojas_veiculos,carros_batidos,licitacoes,"
        "alibaba_sourcing,comparar_portos_alibaba,"
        "ml_tendencias_importacao,monitor_filamentos_ml,monitor_masterprint_petg,monitor_masterprint_escritorio,monitor_cnpj_cnae,ponto_ruptura_segundo_cnpj,ponto_ruptura_outra_marca,"
        "sincronizar_estoque,repricing,repricing_impala,operacao_24h,"
        "chat_shopee,chat_magalu,chat_amazon,auto_respostas",
    ).split(",")
    if x.strip()
}

# Vigia Datadog (erros + inatividade 2h)
DATADOG_VIGIA_CATALOGO_FONTES = os.getenv(
    "DATADOG_VIGIA_CATALOGO_FONTES", "catalogo/datadog_vigia_fontes.json"
)
DATADOG_VIGIA_CATALOGO_FILTROS = os.getenv(
    "DATADOG_VIGIA_CATALOGO_FILTROS", "catalogo/datadog_vigia_filtros.json"
)
DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE = float(os.getenv("DATADOG_VIGIA_LIMITE_HORAS_INATIVIDADE", "2"))
DATADOG_VIGIA_LIMITE_HORAS_ERRO = float(os.getenv("DATADOG_VIGIA_LIMITE_HORAS_ERRO", "2"))
DATADOG_VIGIA_ALERTA_COOLDOWN_SEG = int(os.getenv("DATADOG_VIGIA_ALERTA_COOLDOWN_SEG", "3600"))
# Quando 1, o processo termina com exit code 1 se houver inatividade/erros abertos
# (além do alerta Telegram). Default 0: falha só se o agente crashar.
DATADOG_VIGIA_FALHAR_PROCESSO = os.getenv("DATADOG_VIGIA_FALHAR_PROCESSO", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Sync após push na main (não substitui crons dos workflows)
PUSH_MAIN_COOLDOWN_RESUMO_SEG = int(os.getenv("PUSH_MAIN_COOLDOWN_RESUMO_SEG", "300"))

PUSH_DEPLOY_MENSAGEM_COMMIT = os.getenv("PUSH_DEPLOY_MENSAGEM_COMMIT", "chore: deploy automático robo-markplaces")
PUSH_DEPLOY_BRANCH = os.getenv("PUSH_DEPLOY_BRANCH", "").strip()
PUSH_DEPLOY_REMOTE = os.getenv("PUSH_DEPLOY_REMOTE", "origin").strip()
PUSH_DEPLOY_RODAR_TESTES = os.getenv("PUSH_DEPLOY_RODAR_TESTES", "1").strip().lower() not in ("0", "false", "no")
PUSH_DEPLOY_RODAR_RUFF = os.getenv("PUSH_DEPLOY_RODAR_RUFF", "1").strip().lower() not in ("0", "false", "no")
PUSH_DEPLOY_PATHS_EXCLUIR = tuple(
    x.strip() for x in os.getenv("PUSH_DEPLOY_PATHS_EXCLUIR", "arquivos-java-21,.env").split(",") if x.strip()
)

# Gestão de branches (limpeza pós-push + criar nova a partir da main)
GIT_BRANCH_BASE = os.getenv("GIT_BRANCH_BASE", "main").strip() or "main"
GIT_BRANCH_REMOTE = os.getenv("GIT_BRANCH_REMOTE", "origin").strip() or "origin"
GIT_BRANCH_PROTEGIDAS = frozenset(
    x.strip()
    for x in os.getenv("GIT_BRANCH_PROTEGIDAS", "main,master").split(",")
    if x.strip()
)
GIT_BRANCH_PREFIXOS_LIMPEZA = tuple(
    x.strip()
    for x in os.getenv(
        "GIT_BRANCH_PREFIXOS_LIMPEZA",
        "feature/,chore/,cursor/,agent/,fix/,hotfix/",
    ).split(",")
    if x.strip()
)
GIT_BRANCH_LIMPAR_APOS_PUSH = os.getenv("GIT_BRANCH_LIMPAR_APOS_PUSH", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
GIT_BRANCH_LIMPAR_REMOTAS = os.getenv("GIT_BRANCH_LIMPAR_REMOTAS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
GIT_BRANCH_LIMPAR_LOCAIS = os.getenv("GIT_BRANCH_LIMPAR_LOCAIS", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
GIT_BRANCH_NOVA_PREFIXO = os.getenv("GIT_BRANCH_NOVA_PREFIXO", "cursor/").strip()
PUSH_DEPLOY_CRIAR_BRANCH = os.getenv("PUSH_DEPLOY_CRIAR_BRANCH", "").strip()

# Shopee
SHOPEE_PARTNER_ID  = os.getenv("SHOPEE_PARTNER_ID", "").strip()
SHOPEE_PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_SHOP_ID     = os.getenv("SHOPEE_SHOP_ID", "").strip()
SHOPEE_ACCESS_TOKEN  = os.getenv("SHOPEE_ACCESS_TOKEN", "").strip()
SHOPEE_REFRESH_TOKEN = os.getenv("SHOPEE_REFRESH_TOKEN", "").strip()

# Magalu
MAGALU_CLIENT_ID     = os.getenv("MAGALU_CLIENT_ID", "").strip()
MAGALU_CLIENT_SECRET = os.getenv("MAGALU_CLIENT_SECRET", "").strip()
MAGALU_ACCESS_TOKEN  = os.getenv("MAGALU_ACCESS_TOKEN", "").strip()
MAGALU_REFRESH_TOKEN = os.getenv("MAGALU_REFRESH_TOKEN", "").strip()
# ID fixo do canal de venda "Magazine Luiza" na OpenAPI Magalu — é o
# mesmo valor para qualquer seller (não é um identificador de conta).
# Fonte: https://developers.magalu.com/docs/development-guide/sales-channel-id
# Mantido configurável (e não hardcoded) caso o Magalu troque o ID ou
# adicione mais canais (Netshoes/Kabum) no futuro.
MAGALU_CHANNEL_ID = (
    os.getenv("MAGALU_CHANNEL_ID")
    or os.getenv("MAGALU_MERCHANT_ID", "")  # compat: nome antigo da secret
).strip()
# Alias legado — o valor é o channel id, não um identificador de conta do seller.
MAGALU_MERCHANT_ID = MAGALU_CHANNEL_ID
# ID da conta Magalu do seller (por CNPJ). Distinto do channel id.
MAGALU_SELLER_ID = os.getenv("MAGALU_SELLER_ID", "").strip()

# Amazon
AMAZON_LWA_CLIENT_ID     = os.getenv("AMAZON_LWA_CLIENT_ID", "").strip()
AMAZON_LWA_CLIENT_SECRET = os.getenv("AMAZON_LWA_CLIENT_SECRET", "").strip()
AMAZON_REFRESH_TOKEN     = os.getenv("AMAZON_REFRESH_TOKEN", "").strip()
AMAZON_ACCESS_TOKEN      = os.getenv("AMAZON_ACCESS_TOKEN", "").strip()
AMAZON_SELLER_ID         = os.getenv("AMAZON_SELLER_ID", "").strip()
AMAZON_MARKETPLACE_ID    = os.getenv("AMAZON_MARKETPLACE_ID", "A2Q3Y263D00KWC").strip()

# Meta (Facebook + Instagram)
META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN", "").strip()
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "").strip()
META_PAGE_ID       = os.getenv("META_PAGE_ID", "").strip()
META_INSTAGRAM_ID  = os.getenv("META_INSTAGRAM_ID", "").strip()
# Credenciais do App (necessárias para gerar/renovar o token longo via OAuth)
META_APP_ID        = os.getenv("META_APP_ID", "").strip()
META_APP_SECRET    = os.getenv("META_APP_SECRET", "").strip()
META_REDIRECT_URI  = os.getenv("META_REDIRECT_URI", "https://www.google.com").strip()
META_API_VERSION   = os.getenv("META_API_VERSION", "v19.0").strip()
META_CPC_MAXIMO    = float(os.getenv("META_CPC_MAXIMO", "1.50"))
META_CTR_MINIMO    = float(os.getenv("META_CTR_MINIMO", "1.00"))
META_ROAS_MINIMO   = float(os.getenv("META_ROAS_MINIMO", "2.00"))
META_FREQ_MAXIMA   = float(os.getenv("META_FREQ_MAXIMA", "3.00"))
META_GASTO_MINIMO_ALERTA = float(os.getenv("META_GASTO_MINIMO_ALERTA", "50.0"))
META_ROAS_MINIMO_MANICURES = float(os.getenv("META_ROAS_MINIMO_MANICURES", "2.20"))
META_CTR_MINIMO_MANICURES = float(os.getenv("META_CTR_MINIMO_MANICURES", "1.20"))

# Alertas (strip evita 404 por espaço/quebra ao colar secret no GitHub)
TELEGRAM_TOKEN          = (os.getenv("TELEGRAM_TOKEN") or "").strip()
TELEGRAM_CHAT_ID        = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
TELEGRAM_GESTOR_CHAT_ID = (os.getenv("TELEGRAM_GESTOR_CHAT_ID") or "").strip()
TELEGRAM_MANICURES_CHAT_ID = (os.getenv("TELEGRAM_MANICURES_CHAT_ID") or TELEGRAM_CHAT_ID or "").strip()
# Blocos "O que este agente faz" / "Quando roda" nos alertas Telegram.
# Padrão ligado. Para desligar: TELEGRAM_EXPLICACAO_AGENTES=0
TELEGRAM_EXPLICACAO_AGENTES = os.getenv("TELEGRAM_EXPLICACAO_AGENTES", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
ALERTA_COOLDOWN_SEG      = int(os.getenv("ALERTA_COOLDOWN_SEG", "7200"))

# Fiscal (NF-e)
NFE_NATUREZA_OPERACAO = os.getenv("NFE_NATUREZA_OPERACAO", "Venda de mercadoria")
NFE_CFOP_PADRAO       = os.getenv("NFE_CFOP_PADRAO", "5102")
NFE_CST_PADRAO        = os.getenv("NFE_CST_PADRAO", "00")
NFE_CSOSN_PADRAO      = os.getenv("NFE_CSOSN_PADRAO", "102")
NFE_ORIGEM_PADRAO     = os.getenv("NFE_ORIGEM_PADRAO", "0")
NFE_SERIE_PADRAO      = os.getenv("NFE_SERIE_PADRAO", "1")

# WhatsApp
WHATSAPP_API_TYPE = os.getenv("WHATSAPP_API_TYPE", "evolution")  # "evolution" ou "meta"
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
WHATSAPP_INSTANCE = os.getenv("WHATSAPP_INSTANCE", "")
WHATSAPP_NUMERO_DESTINO = os.getenv("WHATSAPP_NUMERO_DESTINO") or "5519999889059"
WHATSAPP_GRUPO_MANICURES_ID = os.getenv("WHATSAPP_GRUPO_MANICURES_ID", "").strip()
WHATSAPP_BUSINESS_TOKEN = os.getenv("WHATSAPP_BUSINESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

# Promoções manicures (ML → WhatsApp grupo + Telegram)
ML_LOJA_URL = os.getenv("ML_LOJA_URL", "").strip()
PROMOCOES_MANICURES_CATALOGO = os.getenv(
    "PROMOCOES_MANICURES_CATALOGO", "catalogo/promocoes_manicures_ml.json"
)
PROMOCOES_MANICURES_RODAPE = os.getenv(
    "PROMOCOES_MANICURES_RODAPE",
    "Promoção por tempo limitado. Sujeita a estoque no Mercado Livre.",
)
# Intervalo mínimo entre envios (qualquer campanha) — padrão 12h = 2 posts/dia
PROMOCOES_MANICURES_INTERVALO_SEG = int(os.getenv("PROMOCOES_MANICURES_INTERVALO_SEG", "43200"))
# Cooldown por campanha no Telegram (evita repetir o mesmo kit em sequência)
PROMOCOES_MANICURES_COOLDOWN_SEG = int(
    os.getenv("PROMOCOES_MANICURES_COOLDOWN_SEG", str(PROMOCOES_MANICURES_INTERVALO_SEG))
)
PROMOCOES_MANICURES_ATIVO = os.getenv("PROMOCOES_MANICURES_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Conversão manicures (WA + IG + FB + chat ML) — Claude Haiku
def _env_bool(nome: str, default: str = "0") -> bool:
    return os.getenv(nome, default).strip().lower() not in ("0", "false", "no", "")


CONVERSAO_MANICURES_ATIVO = _env_bool("CONVERSAO_MANICURES_ATIVO", "1")
CONVERSAO_MANICURES_ALERTA = _env_bool("CONVERSAO_MANICURES_ALERTA", "1")
# Master de escrita pública (WA/TG/FB/IG/reply/chat_ml). 0 = Claude só analisa + Telegram gestor.
CONVERSAO_MANICURES_ESCRITA = _env_bool("CONVERSAO_MANICURES_ESCRITA", "0")
CONVERSAO_MANICURES_COOLDOWN_SEG = int(os.getenv("CONVERSAO_MANICURES_COOLDOWN_SEG", "18000"))
CONVERSAO_MANICURES_PUBLICAR_FB = _env_bool("CONVERSAO_MANICURES_PUBLICAR_FB", "0")
CONVERSAO_MANICURES_PUBLICAR_IG = _env_bool("CONVERSAO_MANICURES_PUBLICAR_IG", "0")
CONVERSAO_MANICURES_REPLY_META = _env_bool("CONVERSAO_MANICURES_REPLY_META", "0")
CONVERSAO_MANICURES_REPLY_WA = _env_bool("CONVERSAO_MANICURES_REPLY_WA", "0")
# Boost orgânico (exigem ESCRITA=1 também)
CONVERSAO_MANICURES_ENVIAR_WA = _env_bool("CONVERSAO_MANICURES_ENVIAR_WA", "0")
CONVERSAO_MANICURES_ENVIAR_TG = _env_bool("CONVERSAO_MANICURES_ENVIAR_TG", "0")
# 0 = chat ML fica só com agentes.ml (evita resposta duplicada com conversão)
CONVERSAO_MANICURES_CHAT_ML = _env_bool("CONVERSAO_MANICURES_CHAT_ML", "0")
# 0 = auto_respostas_visuais não compete com chat_ml no Mercado Livre
AUTO_RESPOSTAS_ML = _env_bool("AUTO_RESPOSTAS_ML", "0")
CONVERSAO_MANICURES_IMAGEM_IG_URL = os.getenv("CONVERSAO_MANICURES_IMAGEM_IG_URL", "").strip()
# Sustentabilidade: cruza gasto Meta Ads × receita real ML
CONVERSAO_MANICURES_SUSTENTABILIDADE = _env_bool("CONVERSAO_MANICURES_SUSTENTABILIDADE", "1")
CONVERSAO_MANICURES_ROAS_MIN_REAL = float(
    os.getenv("CONVERSAO_MANICURES_ROAS_MIN_REAL", str(META_ROAS_MINIMO_MANICURES))
)
CONVERSAO_MANICURES_BLOQUEAR_SE_INSUSTENTAVEL = _env_bool(
    "CONVERSAO_MANICURES_BLOQUEAR_SE_INSUSTENTAVEL", "1"
)
CONVERSAO_MANICURES_SUST_DIAS = int(os.getenv("CONVERSAO_MANICURES_SUST_DIAS", "1"))
CONVERSAO_MANICURES_GASTO_MIN_AVALIAR = float(
    os.getenv("CONVERSAO_MANICURES_GASTO_MIN_AVALIAR", "20")
)

# Necessidade manicures × ML × canais (match sinais → oferta com confirmação)
NECESSIDADE_MANICURES_ATIVO = _env_bool("NECESSIDADE_MANICURES_ATIVO", "1")
NECESSIDADE_MANICURES_ALERTA = _env_bool("NECESSIDADE_MANICURES_ALERTA", "1")
NECESSIDADE_MANICURES_PEDIR_CONFIRMACAO = _env_bool(
    "NECESSIDADE_MANICURES_PEDIR_CONFIRMACAO", "1"
)
NECESSIDADE_MANICURES_ENVIAR_CANAIS = _env_bool("NECESSIDADE_MANICURES_ENVIAR_CANAIS", "1")
NECESSIDADE_MANICURES_COOLDOWN_SEG = int(
    os.getenv("NECESSIDADE_MANICURES_COOLDOWN_SEG", "18000")
)  # 6h

# Regras de negócio
MARGEM_MINIMA  = float(os.getenv("MARGEM_MINIMA",  str(REGRAS.get("margem_minima_pct", 15.0))))
ESTOQUE_CRITICO = int(os.getenv("ESTOQUE_CRITICO", str(REGRAS.get("estoque_critico_unidades", 20))))
CPC_MAXIMO     = float(os.getenv("CPC_MAXIMO",     str(REGRAS.get("cpc_maximo_reais", 1.50))))
ROAS_ESCALA    = float(os.getenv("ROAS_ESCALA",    str(REGRAS.get("roas_escala", 3.0))))
MARKETPLACE_VARIACAO_ALERTA_PCT = float(os.getenv("MARKETPLACE_VARIACAO_ALERTA_PCT", "5.0"))
LUCRO_MINIMO_REPRICING_PCT = float(os.getenv("LUCRO_MINIMO_REPRICING_PCT", "10.0"))
REPRICING_ABAIXO_CONCORRENTE_PCT = float(os.getenv("REPRICING_ABAIXO_CONCORRENTE_PCT", "3.0"))

# Monitor margem das vendas (Telegram)
MONITOR_MARGEM_VENDAS_DIAS = int(os.getenv("MONITOR_MARGEM_VENDAS_DIAS", "2"))
MONITOR_MARGEM_VENDAS_MARGEM_MIN_PCT = float(
    os.getenv("MONITOR_MARGEM_VENDAS_MARGEM_MIN_PCT", str(MARGEM_MINIMA))
)
MONITOR_MARGEM_VENDAS_RESUMO_COOLDOWN_SEG = int(
    os.getenv("MONITOR_MARGEM_VENDAS_RESUMO_COOLDOWN_SEG", "18000")
)
MONITOR_MARGEM_VENDAS_ALERTA_BAIXA = os.getenv(
    "MONITOR_MARGEM_VENDAS_ALERTA_BAIXA", "1"
).strip().lower() not in ("0", "false", "no")
MONITOR_MARGEM_VENDAS_ALERTA_RESUMO = os.getenv(
    "MONITOR_MARGEM_VENDAS_ALERTA_RESUMO", "1"
).strip().lower() not in ("0", "false", "no")

# Repricing + fases
TAXA_CANAL_PADRAO_PCT = float(os.getenv("TAXA_CANAL_PADRAO_PCT", "18.0"))
MARGEM_FASE_1_PCT = float(os.getenv("MARGEM_FASE_1_PCT", "10.0"))
MARGEM_FASE_2_PCT = float(os.getenv("MARGEM_FASE_2_PCT", "18.0"))
MARGEM_FASE_3_PCT = float(os.getenv("MARGEM_FASE_3_PCT", "25.0"))
REPRICING_DIFERENCA_MINIMA = float(os.getenv("REPRICING_DIFERENCA_MINIMA", "0.50"))
PRECIFICACAO_COMPORTAMENTO_ATIVO = os.getenv("PRECIFICACAO_COMPORTAMENTO_ATIVO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
PRECIFICACAO_VISITAS_SEM_VENDA_DESCONTO_PCT = float(
    os.getenv("PRECIFICACAO_VISITAS_SEM_VENDA_DESCONTO_PCT", "3.0")
)
PRECIFICACAO_DEMANDA_FORTE_AUMENTO_PCT = float(os.getenv("PRECIFICACAO_DEMANDA_FORTE_AUMENTO_PCT", "2.0"))
PRECIFICACAO_MIN_VISITAS_7D_ALERTA = int(os.getenv("PRECIFICACAO_MIN_VISITAS_7D_ALERTA", "20"))
PRECIFICACAO_ALERTA_PAINEL_COOLDOWN_SEG = int(os.getenv("PRECIFICACAO_ALERTA_PAINEL_COOLDOWN_SEG", "86400"))
MARKETPLACE_DRY_RUN_REPRICING = os.getenv("MARKETPLACE_DRY_RUN_REPRICING", "true").lower() == "true"
MARKETPLACE_ALERTAR_ATENCAO = os.getenv("MARKETPLACE_ALERTAR_ATENCAO", "false").lower() == "true"
MARKETPLACE_KEEPALIVE_LIMITE_DIAS = int(os.getenv("MARKETPLACE_KEEPALIVE_LIMITE_DIAS", "5"))
MARKETPLACE_SCHEDULE_HOUR = int(os.getenv("MARKETPLACE_SCHEDULE_HOUR", "6"))
MARKETPLACE_SLEEP_SECONDS = int(os.getenv("MARKETPLACE_SLEEP_SECONDS", "30"))

# Meta Ads (gatilhos automáticos)
AVALIACOES_PARA_ADS = int(os.getenv("AVALIACOES_PARA_ADS", "20"))
NOTA_MINIMA_PARA_ADS = float(os.getenv("NOTA_MINIMA_PARA_ADS", "4.8"))
AVALIACOES_PARA_ESCALAR = int(os.getenv("AVALIACOES_PARA_ESCALAR", "50"))
ACOS_MAXIMO = float(os.getenv("ACOS_MAXIMO", "0.20"))
# Itens analisados por ciclo do monitor ML (concorrência + ads). Valores altos = mais chamadas API.
ML_MAX_ITENS_ANALISE = int(os.getenv("ML_MAX_ITENS_ANALISE", "30"))
BUDGET_FASE_INICIO = float(os.getenv("BUDGET_FASE_INICIO", "10.0"))
BUDGET_FASE_CRESCIMENTO = float(os.getenv("BUDGET_FASE_CRESCIMENTO", "30.0"))
BUDGET_FASE_ESCALA = float(os.getenv("BUDGET_FASE_ESCALA", "80.0"))

# Product Ads ML — guardrails
ML_ADS_KILL_SWITCH = os.getenv("ML_ADS_KILL_SWITCH", "false").lower() in {"1", "true", "yes"}
# Kill switch global de emergência — bloqueia TODA escrita real (NF-e, estoque, preço, anúncios, ads)
ROBO_PAUSAR_ESCRITA = os.getenv("ROBO_PAUSAR_ESCRITA", "false").lower() in {"1", "true", "yes"}
ML_ADS_ORCAMENTO_MAXIMO = float(os.getenv("ML_ADS_ORCAMENTO_MAXIMO", "500.0"))
ML_ADS_ACOS_DIAS_LIMITE = int(os.getenv("ML_ADS_ACOS_DIAS_LIMITE", "3"))

# Autenticação da API (api/app.py) — header obrigatório: X-API-Key
# Se ficar vazia, a API roda em modo aberto (compatibilidade com quem
# já estava em produção antes desta variável existir) — um aviso é
# logado no startup. Defina esta variável para exigir autenticação.
ROBO_API_KEY = os.getenv("ROBO_API_KEY", "").strip()

# Datadog Log Management (opcional — HTTP Intake, sem Agent)
# Em GitHub Actions, secret ausente vira env="" (não "unset"). Tratar "" como default
# evita desligar logs/métricas ou mandar para site errado sem perceber.
DD_API_KEY = os.getenv("DD_API_KEY", "").strip()
DD_APPLICATION_KEY = os.getenv("DD_APPLICATION_KEY", "").strip()
DD_SITE = (os.getenv("DD_SITE") or "us5.datadoghq.com").strip() or "us5.datadoghq.com"
DD_LOGS_ENABLED = (os.getenv("DD_LOGS_ENABLED") or "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
# Métricas independentes dos logs: dá para cortar volume de log sem cegar o Datadog.
DD_METRICS_ENABLED = (os.getenv("DD_METRICS_ENABLED") or "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
# Ambiente exibido na tag `env:` no Datadog (production/staging/dev). Antes era fixo em "production".
DD_ENV = (os.getenv("DD_ENV") or "production").strip() or "production"

# Erros ruidosos no Datadog (Leopardo/scrapers, Claude 400, Bling 401/403).
# Padrão OFF — não sobem como ERROR. Religar individualmente com =1.
# Ver core/log_opcional.py
LOG_ERROS_VEICULOS_SCRAPERS = os.getenv("LOG_ERROS_VEICULOS_SCRAPERS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
LOG_ERROS_CLAUDE = os.getenv("LOG_ERROS_CLAUDE", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
LOG_ERROS_BLING = os.getenv("LOG_ERROS_BLING", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Tokens Magalu / Shopee / Amazon (credenciais ausentes, invalid_grant, etc.)
LOG_ERROS_TOKENS = os.getenv("LOG_ERROS_TOKENS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Busca de pedidos FALHOU (monitor margem / vendas_notificador)
LOG_ERROS_PEDIDOS = os.getenv("LOG_ERROS_PEDIDOS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Storage de estado (file = padrão local; dynamodb = AWS Free Tier)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "file").strip().lower() or "file"
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "robo-markplaces-state").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
SSM_PARAMETER_PREFIX = os.getenv("SSM_PARAMETER_PREFIX", "/robo-markplaces").strip() or "/robo-markplaces"


def _init_datadog_logging() -> None:
    from core.datadog_logger import configurar_logging_datadog

    configurar_logging_datadog()


_init_datadog_logging()
