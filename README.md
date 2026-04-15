# Robo-Markplaces

API e agentes para operação de vendas em marketplaces, com automações de:
- resposta de chat com IA,
- repricing com proteção de margem,
- publicação social,
- relatório diário e alertas.

## Requisitos

- Python 3.11+ (recomendado)
- Conta/configuração para serviços externos (Anthropic, Bling, Telegram, etc.)

## Setup local

1. Criar/ativar virtualenv:
   - Windows PowerShell:
     - `python -m venv .venv`
     - `.\.venv\Scripts\Activate.ps1`
2. Instalar dependências:
   - Runtime: `pip install -r requirements.txt`
   - Desenvolvimento: `pip install -r requirements-dev.txt`
3. Configurar ambiente:
   - Copie `.env.exemplo` para `.env`
   - Preencha os tokens/chaves necessários

## Rodar API

- `flask --app api.app run --host 0.0.0.0 --port 5000`
- ou `python api/app.py`

## Endpoints principais

- `GET /health`
- `POST /chat`
- `POST /repricing`
- `POST /post`
- `GET /estoque/criticos`
- `POST /relatorio`
- `POST /campanha/avaliar`
- `POST /marketplaces/keepalive`

## Conexão com marketplaces

Os agentes agora estão ligados a clientes dedicados em `integracoes/`:
- `integracoes/ml/ml_client.py`
- `integracoes/shopee/shopee_client.py`
- `integracoes/magalu/magalu_client.py`
- `integracoes/amazon/amazon_client.py`

Fluxo padrão:
1. buscar perguntas/mensagens pendentes,
2. gerar resposta com IA contextualizada no produto (Bling),
3. enviar resposta para o canal.

Observação: Shopee, Magalu e Amazon podem variar endpoints/permissões por conta e app. O cliente já está preparado com autenticação e fallback seguro (não quebra o robô quando credencial/permite faltar), mas pode exigir ajuste fino de rota em produção.

### Keepalive (Shopee e Magalu)

Para reduzir risco de inatividade de conta, use `POST /marketplaces/keepalive` em um cron diário (n8n, por exemplo, 1x ao dia).

Payload opcional:

```json
{
  "limite_dias_sem_acesso": 5
}
```

Esse fluxo:
- executa uma chamada leve em Shopee e Magalu,
- registra último acesso com sucesso em `logs/marketplace_keepalive.json`,
- alerta gestor quando falha acesso ou quando ultrapassa limite configurado.

## Exemplos de payload

### Repricing

```json
{
  "sku": "ESM-001",
  "preco_atual": 9.9,
  "custo": 6.0,
  "preco_concorrente": 8.5
}
```

### Campanha

```json
{
  "nome": "Esmalte Carmim - SP",
  "cpc": 1.2,
  "ctr": 2.5,
  "roas": 3.8
}
```

## Testes

- `python -m unittest discover -s tests -p "test_*.py"`

## Qualidade recomendada

- Lint: `ruff check .`
- Formatação: `ruff format .`