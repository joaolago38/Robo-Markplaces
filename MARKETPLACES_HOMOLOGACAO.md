# Homologação de Marketplaces

Checklist objetivo para colocar Mercado Livre, Shopee, Magalu e Amazon em produção.

## 1) Pré-requisitos

- Criar `.env` a partir de `.env.exemplo`.
- Instalar dependências:
  - `pip install -r requirements.txt`
  - `pip install -r requirements-dev.txt`
- Subir a API local:
  - `flask --app api.app run --host 0.0.0.0 --port 5000`

## 2) Credenciais mínimas por canal

- Mercado Livre:
  - `ML_ACCESS_TOKEN`, `ML_SELLER_ID`
- Shopee:
  - `SHOPEE_PARTNER_ID`, `SHOPEE_PARTNER_KEY`, `SHOPEE_SHOP_ID`, `SHOPEE_ACCESS_TOKEN`
- Magalu:
  - `MAGALU_ACCESS_TOKEN`, `MAGALU_MERCHANT_ID`
- Amazon:
  - `AMAZON_ACCESS_TOKEN`

Observação: para produção, preferir fluxo com refresh token em todos os canais que suportam.

## 3) Diagnóstico rápido automatizado

Execute:

```bash
py scripts/verificar_marketplaces.py
```

Esse comando:

- valida se as credenciais mínimas existem no `.env`;
- faz uma chamada de leitura leve por marketplace;
- gera `logs/diagnostico_marketplaces.json`.

Critério de aprovação:

- `configurados` = quantidade esperada de canais ativos;
- `conectados` = `configurados`;
- `ok` = `true`.

## 4) Testes funcionais por endpoint

- Keepalive:
  - `POST /marketplaces/keepalive`
- Saúde/algoritmo:
  - `POST /marketplaces/algoritmo/ajustar`
- Respostas automáticas:
  - `POST /marketplaces/chat/visual/rodar`
- Repricing:
  - `POST /marketplaces/produtos/monitorar`

Critério de aprovação:

- status HTTP 200;
- payload com campos esperados;
- logs sem erro de autenticação/permissão.

## 5) Operação contínua

Agendar no n8n:

- keepalive 1x ao dia;
- algoritmo de saúde em janela de monitoramento;
- chat visual e repricing conforme rotina comercial.

## 6) Troubleshooting rápido

- `401/403`: token inválido ou escopo insuficiente.
- `400` com token válido: endpoint/permissão não liberado para a conta.
- retorno vazio com conta ativa: ausência de pendências no canal (normal).
