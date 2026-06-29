"""
core/config.py
Configuração central — lê spec.yaml e variáveis de ambiente.
"""
import os
import logging
import yaml
from pathlib import Path
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

# IA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

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
ML_SITE_ID       = os.getenv("ML_SITE_ID", "MLB").strip()  # MLB = Brasil

# Monitor de concorrentes (busca pública por palavra-chave, sem precisar de item próprio)
MONITOR_CONCORRENTES_ARQUIVO = os.getenv(
    "MONITOR_CONCORRENTES_ARQUIVO", "catalogo/concorrentes_monitorados.json"
).strip()
MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT = float(
    os.getenv("MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT", "5.0")
)

# Shopee
SHOPEE_PARTNER_ID  = os.getenv("SHOPEE_PARTNER_ID", "").strip()
SHOPEE_PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_SHOP_ID     = os.getenv("SHOPEE_SHOP_ID", "").strip()
SHOPEE_ACCESS_TOKEN  = os.getenv("SHOPEE_ACCESS_TOKEN", "").strip()
SHOPEE_REFRESH_TOKEN = os.getenv("SHOPEE_REFRESH_TOKEN", "").strip()

# Magalu
MAGALU_CLIENT_ID     = os.getenv("MAGALU_CLIENT_ID", "").strip()
MAGALU_CLIENT_SECRET = os.getenv("MAGALU_CLIENT_SECRET", "").strip()
MAGALU_MERCHANT_ID   = os.getenv("MAGALU_MERCHANT_ID", "").strip()
MAGALU_ACCESS_TOKEN  = os.getenv("MAGALU_ACCESS_TOKEN", "").strip()
MAGALU_REFRESH_TOKEN = os.getenv("MAGALU_REFRESH_TOKEN", "").strip()

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

# Alertas
TELEGRAM_TOKEN          = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_GESTOR_CHAT_ID = os.getenv("TELEGRAM_GESTOR_CHAT_ID", "")
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
WHATSAPP_BUSINESS_TOKEN = os.getenv("WHATSAPP_BUSINESS_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

# Regras de negócio
MARGEM_MINIMA  = float(os.getenv("MARGEM_MINIMA",  str(REGRAS.get("margem_minima_pct", 15.0))))
ESTOQUE_CRITICO = int(os.getenv("ESTOQUE_CRITICO", str(REGRAS.get("estoque_critico_unidades", 20))))
CPC_MAXIMO     = float(os.getenv("CPC_MAXIMO",     str(REGRAS.get("cpc_maximo_reais", 1.50))))
ROAS_ESCALA    = float(os.getenv("ROAS_ESCALA",    str(REGRAS.get("roas_escala", 3.0))))
MARKETPLACE_VARIACAO_ALERTA_PCT = float(os.getenv("MARKETPLACE_VARIACAO_ALERTA_PCT", "5.0"))
LUCRO_MINIMO_REPRICING_PCT = float(os.getenv("LUCRO_MINIMO_REPRICING_PCT", "10.0"))
REPRICING_ABAIXO_CONCORRENTE_PCT = float(os.getenv("REPRICING_ABAIXO_CONCORRENTE_PCT", "3.0"))

# Repricing + fases
TAXA_CANAL_PADRAO_PCT = float(os.getenv("TAXA_CANAL_PADRAO_PCT", "18.0"))
MARGEM_FASE_1_PCT = float(os.getenv("MARGEM_FASE_1_PCT", "10.0"))
MARGEM_FASE_2_PCT = float(os.getenv("MARGEM_FASE_2_PCT", "18.0"))
MARGEM_FASE_3_PCT = float(os.getenv("MARGEM_FASE_3_PCT", "25.0"))
REPRICING_DIFERENCA_MINIMA = float(os.getenv("REPRICING_DIFERENCA_MINIMA", "0.50"))
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

# Datadog Log Management (opcional — HTTP Intake, sem Agent)
DD_API_KEY = os.getenv("DD_API_KEY", "").strip()
DD_SITE = os.getenv("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
DD_LOGS_ENABLED = os.getenv("DD_LOGS_ENABLED", "true").lower() in {"1", "true", "yes"}
# Ambiente exibido na tag `env:` no Datadog (production/staging/dev). Antes era fixo em "production".
DD_ENV = os.getenv("DD_ENV", "production").strip() or "production"


def _init_datadog_logging() -> None:
    from core.datadog_logger import configurar_logging_datadog

    configurar_logging_datadog()


_init_datadog_logging()
