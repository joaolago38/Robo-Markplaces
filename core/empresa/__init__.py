"""
core/empresa — configuração por CNPJ/CNAE (SRP + Strategy + Facade).

Módulos:
  cnpj_utils      — formatação / dígitos
  marketplace     — normalização de nomes de marketplace
  catalogo        — carregar e enriquecer empresas
  overrides       — env ML/Telegram/CNPJ por empresa
  dono_produtos   — Strategy de migração do dono dos catálogos
  roteador        — Strategy propósito → empresa
  apresentacao    — Telegram + contexto Claude

API pública estável em core.empresa_contexto (Facade).
"""
