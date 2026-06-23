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
- `POST /marketplaces/estoque/sincronizar`
- `POST /marketplaces/algoritmo/ajustar`
- `POST /marketplaces/produtos/monitorar`
- `POST /operacao/24h`
- `POST /faturamento/nfe`
- `POST /meta/campanhas/validar`
- `POST /ml/ads/diagnostico`
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

### Renovação automática do token Bling (GitHub Actions)

O Bling rotaciona o `BLING_REFRESH_TOKEN` a cada renovação (uso único). Em workflows do GitHub Actions (`GITHUB_ACTIONS=true`), qualquer rotação feita por `core/token_manager.py` — inclusive após HTTP 401 em `bling_client.py` — sincroniza automaticamente `BLING_ACCESS_TOKEN` e `BLING_REFRESH_TOKEN` nos Secrets via `gh` CLI (`core/github_secrets.py`). Isso vale para todos os jobs que usam o Bling (`renovar_tokens.yml`, `panorama.yml`, `testar_integracao.yml`, etc.), não só o cron dedicado de renovação.

Fora do Actions, o cofre local (`_salvar_store_bling`) continua ativo. Scripts como `scripts/debug_bling_refresh.py` (refresh HTTP direto) mantêm sync próprio quando rodam no Actions.

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

### Sincronização de estoque (Bling → marketplaces)

Use `POST /marketplaces/estoque/sincronizar` para alinhar o estoque dos canais ativos (`catalogo/produtos.json`) com o saldo real do Bling — evita overselling entre ML, Magalu e Shopee.

Payload opcional:

```json
{
  "dry_run": true
}
```

Esse fluxo:
- lê `catalogo/produtos.json` (mapeamento SKU → `item_id` por canal),
- consulta estoque real via `bling_client.buscar_produto(sku)` (pula SKU sem saldo conhecido),
- compara com o `estoque` salvo em cada canal ativo e aplica `atualizar_estoque_item` quando `dry_run=false`,
- atualiza o JSON do catálogo após sincronização bem-sucedida (escrita atômica),
- alerta gestor quando há ajustes e alerta crítico quando estoque chega a zero (pausa anúncio no ML quando possível).

Agente: `agentes/sincronizar_estoque_marketplaces.py`  
Workflow: `.github/workflows/sincronizar_estoque.yml` (a cada 2h, `dry_run=false`)

```bash
python -m agentes.sincronizar_estoque_marketplaces
# Local com simulação: ESTOQUE_SYNC_DRY_RUN=true python -m agentes.sincronizar_estoque_marketplaces
```

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
- Antes de emitir (`dry_run=false`), consulta o Bling por NF-e existente com o mesmo `numeroPedidoLoja` — evita duplicidade quando panorama e operação 24h processam o mesmo pedido.

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

**Cron de segurança (GitHub Actions):** `.github/workflows/operacao_24h_seguranca.yml` roda a cada 2h com `dry_run_repricing=false` e `dry_run_nfe=false`. Não substitui o n8n — é camada redundante para repricing/faturamento não ficarem parados se o orquestrador externo falhar. A checagem de NF-e duplicada (via `buscar_nfe_por_pedido`) torna seguro o n8n e este cron rodarem em paralelo.

### Kill switch de emergência (`ROBO_PAUSAR_ESCRITA`)

Variável global que **tem prioridade sobre qualquer `dry_run=False`** individual. Quando `ROBO_PAUSAR_ESCRITA=true` (no `.env` ou nos Secrets do GitHub Actions), **nenhuma escrita real** é executada nos canais:

- NF-e no Bling (`criar_nfe` / `emitir_nfe_pedido`)
- Repricing de preços (`agente_repricing_marketplaces`)
- Estoque em ML, Magalu e Shopee (`atualizar_estoque_item`)
- Pausa/encerramento de anúncios no ML
- Product Ads do ML (além do `ML_ADS_KILL_SWITCH` específico)
- Sincronização de estoque (`sincronizar_estoque_marketplaces`)
- Operação 24h quando `dry_run_repricing=false` ou `dry_run_nfe=false`

Operações de **leitura** (monitoramento, panorama, relatórios, diagnóstico) continuam normais.

Para reativar escritas: `ROBO_PAUSAR_ESCRITA=false` ou remova a variável.

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

## CI (GitHub Actions)

- **Qualidade em todo push/PR para `main`:** `.github/workflows/ci.yml` — roda `ruff check` e `pytest -q` automaticamente. Não usa Secrets nem executa rotinas de produção.
- **Orquestrador de produção:** `.github/workflows/agente_principal.yml` — continua disparado apenas por `schedule` e `workflow_dispatch` (relatório, chat, vendas WhatsApp, keepalive/algoritmo). Não roda em push/PR para evitar efeitos colaterais reais a cada commit.

## Agentes ML — cron GitHub Actions

Rotinas diárias do Mercado Livre (somente leitura ou com confirmação Telegram antes de escrita):

| Horário (BRT) | Workflow | Agente | Função |
|---------------|----------|--------|--------|
| 09:00 | `.github/workflows/monitor_ml.yml` | `agentes/ml/agente_monitor_ml.py` | Diagnóstico conta + Product Ads + concorrência |
| 10:00 | `.github/workflows/ads_gatilho_ml.yml` | `agentes/ml/agente_ads_gatilho.py` | Ligar/pausar/escalar ads (confirmação gestor) |
| 08:30 | `.github/workflows/panorama.yml` | `agentes/panorama/agente_panorama.py` | Visão geral ML + Magalu + Bling + síntese Claude |
| Seg 08:00 | `.github/workflows/relatorio_financeiro.yml` | `agentes/relatorio_financeiro.py` | Impacto financeiro estimado (repricing + ads) |
| A cada 2h | `.github/workflows/sincronizar_estoque.yml` | `agentes/sincronizar_estoque_marketplaces.py` | Estoque Bling → ML/Magalu/Shopee |
| A cada 2h | `.github/workflows/operacao_24h_seguranca.yml` | `agentes/operacao_24h.py` | Repricing + faturamento (camada redundante ao n8n) |

Execução local:

```bash
python -m agentes.ml.agente_monitor_ml
python -m agentes.ml.agente_ads_gatilho
python -m agentes.panorama.agente_panorama
```

O gatilho de ads usa ACOS agregado das campanhas com gasto (não reputação do vendedor). Pausa afeta apenas campanhas com ACOS acima do limite (`ACOS_MAXIMO`).

### Variáveis ML (monitoramento e ads)

| Variável | Default | Descrição |
|----------|---------|-----------|
| `ML_MAX_ITENS_ANALISE` | `30` | Máximo de anúncios analisados por ciclo (concorrência + monitor). Valores altos aumentam tempo e chamadas à API do ML. |
| `ACOS_MAXIMO` | `0.20` | Teto de ACOS (20%) para alertas e pausa seletiva de campanhas |

## Relatório financeiro semanal

- Agente: `agentes/relatorio_financeiro.py`
- Workflow: `.github/workflows/relatorio_financeiro.yml` (segunda-feira 08:00 BRT)
- Estima impacto do repricing (margem protegida no piso) e gasto diário em campanhas com ACOS alto
- Somente leitura — não altera preços nem campanhas

```bash
python -m agentes.relatorio_financeiro
```

## n8n pronto para uso

O pacote de automação está em `n8n/` com workflows prontos para importação:
- `n8n/workflows/robo_markplaces_rotinas.json`
- `n8n/workflows/robo_markplaces_chat_webhook.json`

Guia de configuração: `n8n/README.md`.

## Qualidade recomendada

- Lint: `ruff check .`
- Formatação: `ruff format .`