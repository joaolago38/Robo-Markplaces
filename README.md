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
- `POST /marketplaces/algoritmo/ajustar`
- `POST /marketplaces/produtos/monitorar`
- `POST /operacao/24h`
- `POST /faturamento/nfe`
- `POST /meta/campanhas/validar`
- `POST /meta/trafego/manicures`
- `POST /meta/trafego/manicures/resumo-madrugada`
- `POST /marketplaces/chat/visual/rodar`

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

### Saúde da conta + ajuste de algoritmo

Use `POST /marketplaces/algoritmo/ajustar` para monitorar Mercado Livre, Shopee, Magalu e Amazon.

Payload opcional:

```json
{
  "alertar_quando_atencao": false
}
```

Esse fluxo:
- mede saúde por marketplace (pendências, claims quando disponível e dias sem acesso),
- gera score e status (`saudavel`, `atencao`, `critico`),
- sugere ajustes automáticos para o momento (responder fila, revisar preço/título, estabilizar operação),
- mantém histórico em `logs/marketplace_algorithm_history.json` para detectar queda brusca de desempenho.

Variações:
- O motor também detecta variações relevantes de 5% (configurável em `MARKETPLACE_VARIACAO_ALERTA_PCT`) em score, pendências e taxa de reclamação.
- Quando detecta variação relevante, gera ajuste fino de vendas (ex.: micro ajuste de preço 1-2%, reforço de atendimento e revisão de oferta).

### Validação de campanhas Meta (Instagram/Facebook)

Use `POST /meta/campanhas/validar` para avaliar campanhas da Meta Ads API.

Payload opcional:

```json
{
  "alertar_quando_atencao": false,
  "periodo_dias": 1
}
```

Regras de validação:
- CPC acima do limite configurado.
- CTR abaixo do mínimo.
- ROAS abaixo do alvo com gasto relevante.
- Frequência alta (fadiga de criativo).

Retorna status por campanha (`saudavel`, `atencao`, `critico`) e recomendações.

### Eficiência de tráfego para manicures (Impala, Anita e kits)

Use `POST /meta/trafego/manicures` para medir eficiência de tráfego pago no Instagram/Facebook com foco nas marcas e kits de manicure.

Payload opcional:

```json
{
  "periodo_dias": 1,
  "alertar_todo_relatorio": true
}
```

Retorna:
- score de eficiência por campanha,
- resumo por grupo (`impala`, `anita`, `kits`, `outras`),
- campanhas críticas e recomendações de otimização.

### Emissão de NF-e automática (Bling)

Use `POST /faturamento/nfe` quando o pedido estiver pago/confirmado.

Payload:

```json
{
  "dry_run": true,
  "pedido": {
    "pedido_id": "PED-123",
    "cliente": {
      "nome": "Cliente Exemplo",
      "documento": "12345678901",
      "email": "cliente@exemplo.com"
    },
    "itens": [
      {
        "sku": "ESM-001",
        "quantidade": 2,
        "valor_unitario": 9.9
      }
    ]
  }
}
```

Regras:
- NCM é resolvido por prioridade: item -> produto no Bling -> `catalogo/produtos.json`.
- Se algum item ficar sem NCM válido, a emissão é bloqueada e alerta crítico é disparado.
- Em `dry_run=true`, retorna o payload fiscal para conferência antes da emissão real.
- O item já sai com campos fiscais base (`cfop`, `cst`, `csosn`, `origem`) configuráveis no `.env`.

### Repricing de produtos por marketplace

Use `POST /marketplaces/produtos/monitorar` para monitorar e ajustar preços visando lucro mínimo.

Payload opcional:

```json
{
  "dry_run": true,
  "lucro_minimo_pct": 10.0,
  "produtos": []
}
```

Regras:
- Garante margem mínima por item/canal (default 10%).
- Considera preço concorrente quando informado.
- Nunca propõe preço abaixo do necessário para manter o lucro mínimo.
- Em `dry_run=false`, tenta aplicar preço nos canais integrados.

### Operação contínua 24h

Use `POST /operacao/24h` para:
- monitorar marketplaces continuamente,
- calcular média de venda/lucro/preço geral dos produtos,
- gerar NF no Bling para pedidos aprovados vindos do Lojahub (recomendado agendar para o dia seguinte, ex.: 06:15).

Payload opcional:

```json
{
  "dry_run_repricing": true,
  "dry_run_nfe": false
}
```

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

## Diagnóstico de conexão de marketplaces

- Execute: `py scripts/verificar_marketplaces.py`
- Saída detalhada: `logs/diagnostico_marketplaces.json`
- Guia completo de homologação: `MARKETPLACES_HOMOLOGACAO.md`

## Agente de varredura diária (7x por semana)

- Agente: `agentes/agente_varredura_marketplaces.py`
- Scheduler diário: `scripts/scheduler_varredura_marketplaces.py`
- Execução:
  - `py scripts/scheduler_varredura_marketplaces.py`
- Padrão:
  - roda todos os dias às `06:00` (hora local),
  - faz varredura de pendências em ML/Shopee/Magalu/Amazon,
  - executa keepalive + algoritmo + repricing,
  - roda chat visual quando existir pendência.
- Variáveis opcionais no `.env`:
  - `MARKETPLACE_SCHEDULE_HOUR=6`
  - `MARKETPLACE_SCHEDULE_MINUTE=0`
  - `MARKETPLACE_RUN_ON_START=true`
  - `MARKETPLACE_SLEEP_SECONDS=30`
  - `MARKETPLACE_DRY_RUN_REPRICING=true`
  - `MARKETPLACE_ALERTAR_ATENCAO=false`
  - `MARKETPLACE_KEEPALIVE_LIMITE_DIAS=5`

## n8n pronto para uso

O pacote de automação está em `n8n/` com workflows prontos para importação:
- `n8n/workflows/robo_markplaces_rotinas.json`
- `n8n/workflows/robo_markplaces_chat_webhook.json`

Guia de configuração: `n8n/README.md`.

## Qualidade recomendada

- Lint: `ruff check .`
- Formatação: `ruff format .`