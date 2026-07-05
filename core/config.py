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
ML_SITE_ID       = (os.getenv("ML_SITE_ID", "MLB").strip() or "MLB")  # MLB = Brasil

# Monitor de concorrentes (busca pública por palavra-chave, sem precisar de item próprio)
MONITOR_CONCORRENTES_ARQUIVO = os.getenv(
    "MONITOR_CONCORRENTES_ARQUIVO", "catalogo/concorrentes_monitorados.json"
).strip()
MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT = float(
    os.getenv("MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT", "5.0")
)

LEILAO_VEICULOS_CATALOGO = os.getenv(
    "LEILAO_VEICULOS_CATALOGO", "catalogo/leiloes_veiculos_monitorados.json"
)
LEILAO_PAUSA_ENTRE_FONTES_SEG = float(os.getenv("LEILAO_PAUSA_ENTRE_FONTES_SEG", "2.5"))
LEILAO_DDG_RETRY_MAX = int(os.getenv("LEILAO_DDG_RETRY_MAX", os.getenv("DDG_RETRY_MAX", "3")))
LEILAO_DDG_RETRY_BASE_SEG = float(os.getenv("LEILAO_DDG_RETRY_BASE_SEG", os.getenv("DDG_RETRY_BASE_SEG", "5")))
LEILAO_ALERTA_RESUMO = os.getenv("LEILAO_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
LEILAO_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("LEILAO_ALERTA_RESUMO_COOLDOWN_SEG", "3600"))

# DuckDuckGo Lite (compartilhado leilão + Alibaba)
DDG_MIN_INTERVAL_SEG = float(os.getenv("DDG_MIN_INTERVAL_SEG", "2.5"))
DDG_RETRY_MAX = int(os.getenv("DDG_RETRY_MAX", "3"))
DDG_RETRY_BASE_SEG = float(os.getenv("DDG_RETRY_BASE_SEG", "5"))
DDG_CIRCUIT_BREAKER_SEG = float(os.getenv("DDG_CIRCUIT_BREAKER_SEG", "300"))
DDG_FALHAS_403_PARA_BREAKER = int(os.getenv("DDG_FALHAS_403_PARA_BREAKER", "5"))
# lite = GET lite.duckduckgo.com | html = POST html.duckduckgo.com | auto = lite depois html
DDG_BACKEND = os.getenv("DDG_BACKEND", "lite").strip().lower()
DDG_DISABLED = os.getenv("DDG_DISABLED", "").strip().lower() in ("1", "true", "yes")
# Alibaba: pula DDG quando busca direta já retornou itens (menos carga no DDG)
DDG_ALIBABA_SKIP_SE_DIRETO = os.getenv("DDG_ALIBABA_SKIP_SE_DIRETO", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Telegram — circuit breaker após token inválido (evita centenas de ERROR no Datadog)
TELEGRAM_CIRCUIT_BREAKER_SEG = int(os.getenv("TELEGRAM_CIRCUIT_BREAKER_SEG", "3600"))

ALIBABA_IMPORTACAO_CATALOGO = os.getenv(
    "ALIBABA_IMPORTACAO_CATALOGO", "catalogo/alibaba_produtos_importacao.json"
)
ALIBABA_PAUSA_ENTRE_BUSCAS_SEG = float(os.getenv("ALIBABA_PAUSA_ENTRE_BUSCAS_SEG", "1.0"))
ALIBABA_ALERTA_RESUMO = os.getenv("ALIBABA_ALERTA_RESUMO", "1").strip().lower() not in ("0", "false", "no")
ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG = int(os.getenv("ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG", "7200"))

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
LICITACOES_BUSCAR_PORTAIS_ESTADUAIS = os.getenv("LICITACOES_BUSCAR_PORTAIS_ESTADUAIS", "0").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Orquestrador 30 min
ORQUESTRADOR_COOLDOWN_RESUMO_SEG = int(os.getenv("ORQUESTRADOR_COOLDOWN_RESUMO_SEG", "1500"))
ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG = float(os.getenv("ORQUESTRADOR_PAUSA_ENTRE_AGENTES_SEG", "1.5"))
ORQUESTRADOR_EXCLUIR = {
    x.strip() for x in os.getenv("ORQUESTRADOR_EXCLUIR", "").split(",") if x.strip()
}

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
DD_API_KEY = os.getenv("DD_API_KEY", "").strip()
DD_SITE = os.getenv("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
DD_LOGS_ENABLED = os.getenv("DD_LOGS_ENABLED", "true").lower() in {"1", "true", "yes"}
# Ambiente exibido na tag `env:` no Datadog (production/staging/dev). Antes era fixo em "production".
DD_ENV = os.getenv("DD_ENV", "production").strip() or "production"

# Storage de estado (file = padrão local; dynamodb = AWS Free Tier)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "file").strip().lower() or "file"
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "robo-markplaces-state").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
SSM_PARAMETER_PREFIX = os.getenv("SSM_PARAMETER_PREFIX", "/robo-markplaces").strip() or "/robo-markplaces"


def _init_datadog_logging() -> None:
    from core.datadog_logger import configurar_logging_datadog

    configurar_logging_datadog()


_init_datadog_logging()
