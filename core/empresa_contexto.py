"""
core/empresa_contexto.py
Facade estável (Design Pattern: Facade).

Mantém a API pública usada por agentes/testes e delega a core.empresa/*
(SOLID: SRP nos módulos; OCP via Strategy no roteador/dono).

Ordem: flags primeiro (para patches e core.empresa.flags), depois imports.
"""
from __future__ import annotations

import core.config as _cfg
from core.config import (
    ML_SELLER_ID,
    ML_SITE_ID,
    ROOT,
    TELEGRAM_GESTOR_CHAT_ID,
)

# --- Flags no Facade ANTES dos imports internos (testes @patch + flags.flag) ---
EMPRESAS_CNAE_CNPJ_CATALOGO = getattr(
    _cfg, "EMPRESAS_CNAE_CNPJ_CATALOGO", "catalogo/empresas_cnae_cnpj.json"
)
EMPRESA_ATIVA_ID = getattr(_cfg, "EMPRESA_ATIVA_ID", "") or ""
EMPRESA_ATIVA_CNPJ = getattr(_cfg, "EMPRESA_ATIVA_CNPJ", "") or ""
ESMALTES_CNPJ = getattr(_cfg, "ESMALTES_CNPJ", "52668583000127") or "52668583000127"
DEMAIS_PRODUTOS_CNPJ = (
    getattr(_cfg, "DEMAIS_PRODUTOS_CNPJ", "23811261000197") or "23811261000197"
)
CNPJ_DONO_PRODUTOS = (
    getattr(_cfg, "CNPJ_DONO_PRODUTOS", ESMALTES_CNPJ) or ESMALTES_CNPJ
)
CNPJ_DONO_PRODUTOS_ALVO = (
    getattr(_cfg, "CNPJ_DONO_PRODUTOS_ALVO", DEMAIS_PRODUTOS_CNPJ) or DEMAIS_PRODUTOS_CNPJ
)
CNPJ_DONO_PRODUTOS_USAR_ALVO = bool(getattr(_cfg, "CNPJ_DONO_PRODUTOS_USAR_ALVO", False))
MARKETPLACE_FOCO_PRINCIPAL = (
    getattr(_cfg, "MARKETPLACE_FOCO_PRINCIPAL", "mercadolivre") or "mercadolivre"
)

from core.empresa.apresentacao import (  # noqa: E402
    contexto_analise,
    linha_empresa_telegram,
    mapa_dois_cnpjs,
    marketplace_foco,
    prioriza_mercadolivre,
)
from core.empresa.catalogo import (  # noqa: E402
    carregar_catalogo,
    empresa_por_cnpj,
    empresa_por_id,
    empresa_por_ramo,
    empresas_por_cnae,
    enriquecer_empresa,
    limpar_cache_empresas,
    listar_empresas,
)
from core.empresa.cnpj_utils import digitos as _digitos  # noqa: E402
from core.empresa.cnpj_utils import formatar_cnpj  # noqa: E402
from core.empresa.cnpj_utils import norm_cnae as _norm_cnae  # noqa: E402
from core.empresa.dono_produtos import (  # noqa: E402
    cnpj_dono_produtos_efetivo,
    empresa_dono_produtos,
    situacao_dono_produtos,
)
from core.empresa.marketplace import MARKETPLACES_CONHECIDOS  # noqa: E402
from core.empresa.marketplace import norm_marketplace as _norm_marketplace  # noqa: E402
from core.empresa.overrides import aplicar_overrides_env as _aplicar_overrides_env  # noqa: E402
from core.empresa.roteador import empresa_ativa, empresa_para_proposito  # noqa: E402

# Alias legado usado nos testes
_enriquecer_empresa = enriquecer_empresa

__all__ = [
    "EMPRESAS_CNAE_CNPJ_CATALOGO",
    "EMPRESA_ATIVA_ID",
    "EMPRESA_ATIVA_CNPJ",
    "ESMALTES_CNPJ",
    "DEMAIS_PRODUTOS_CNPJ",
    "CNPJ_DONO_PRODUTOS",
    "CNPJ_DONO_PRODUTOS_ALVO",
    "CNPJ_DONO_PRODUTOS_USAR_ALVO",
    "MARKETPLACE_FOCO_PRINCIPAL",
    "ML_SELLER_ID",
    "ML_SITE_ID",
    "ROOT",
    "TELEGRAM_GESTOR_CHAT_ID",
    "MARKETPLACES_CONHECIDOS",
    "formatar_cnpj",
    "_digitos",
    "_norm_cnae",
    "_norm_marketplace",
    "carregar_catalogo",
    "limpar_cache_empresas",
    "listar_empresas",
    "enriquecer_empresa",
    "_enriquecer_empresa",
    "empresa_por_id",
    "empresa_por_cnpj",
    "empresas_por_cnae",
    "empresa_por_ramo",
    "empresa_ativa",
    "_aplicar_overrides_env",
    "empresa_para_proposito",
    "mapa_dois_cnpjs",
    "cnpj_dono_produtos_efetivo",
    "situacao_dono_produtos",
    "empresa_dono_produtos",
    "marketplace_foco",
    "prioriza_mercadolivre",
    "contexto_analise",
    "linha_empresa_telegram",
]
