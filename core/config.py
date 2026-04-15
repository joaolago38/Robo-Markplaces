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
AMAZON_ACCESS_TOKEN      = os.getenv("AMAZON_ACCESS_TOKEN", "")
AMAZON_SELLER_ID         = os.getenv("AMAZON_SELLER_ID", "")
AMAZON_MARKETPLACE_ID    = os.getenv("AMAZON_MARKETPLACE_ID", "A2Q3Y263D00KWC")

# Meta (Facebook + Instagram)
META_ACCESS_TOKEN  = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
META_PAGE_ID       = os.getenv("META_PAGE_ID", "")
META_INSTAGRAM_ID  = os.getenv("META_INSTAGRAM_ID", "")
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

# Fiscal (NF-e)
NFE_NATUREZA_OPERACAO = os.getenv("NFE_NATUREZA_OPERACAO", "Venda de mercadoria")
NFE_CFOP_PADRAO       = os.getenv("NFE_CFOP_PADRAO", "5102")
NFE_CST_PADRAO        = os.getenv("NFE_CST_PADRAO", "00")
NFE_CSOSN_PADRAO      = os.getenv("NFE_CSOSN_PADRAO", "102")
NFE_ORIGEM_PADRAO     = os.getenv("NFE_ORIGEM_PADRAO", "0")
NFE_SERIE_PADRAO      = os.getenv("NFE_SERIE_PADRAO", "1")

# Regras de negócio
MARGEM_MINIMA  = float(os.getenv("MARGEM_MINIMA",  str(REGRAS.get("margem_minima_pct", 15.0))))
ESTOQUE_CRITICO = int(os.getenv("ESTOQUE_CRITICO", str(REGRAS.get("estoque_critico_unidades", 20))))
CPC_MAXIMO     = float(os.getenv("CPC_MAXIMO",     str(REGRAS.get("cpc_maximo_reais", 1.50))))
ROAS_ESCALA    = float(os.getenv("ROAS_ESCALA",    str(REGRAS.get("roas_escala", 3.0))))
MARKETPLACE_VARIACAO_ALERTA_PCT = float(os.getenv("MARKETPLACE_VARIACAO_ALERTA_PCT", "5.0"))
LUCRO_MINIMO_REPRICING_PCT = float(os.getenv("LUCRO_MINIMO_REPRICING_PCT", "10.0"))
REPRICING_ABAIXO_CONCORRENTE_PCT = float(os.getenv("REPRICING_ABAIXO_CONCORRENTE_PCT", "3.0"))
