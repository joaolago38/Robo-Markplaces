# Robo-Markplaces

API e agentes para operação de vendas em marketplaces, com automações de:
- resposta de chat com IA,
- repricing com proteção de margem,
- publicação social,
- relatório diário e alertas.

Esquema de arquitetura (camadas, orquestrador, integrações, fluxos e desenho): [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

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

### Autenticação

A variável `ROBO_API_KEY` exige o header `X-API-Key` em todas as chamadas à API, exceto `GET /health`. Sem ela definida, a API roda em modo aberto (comportamento anterior — um aviso é logado no startup). Em produção, configure `ROBO_API_KEY` como secret/variável de ambiente e atualize os nós HTTP Request do n8n para enviar `X-API-Key: <valor>` em todas as requisições à API.

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
- `POST /ml/listing/otimizar`
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

### Otimização de título ML (somente sugestão)

Use `POST /ml/listing/otimizar` para receber sugestões de título via Claude, comparando seu anúncio com concorrentes do mesmo catálogo no Mercado Livre.

Payload opcional:

```json
{
  "item_id": "MLB123456",
  "limite_itens": 10
}
```

- Com `item_id`: analisa só esse anúncio.
- Sem `item_id`: analisa até `limite_itens` produtos ML ativos em `catalogo/produtos.json` e envia resumo ao gestor via Telegram.

**Este agente é SOMENTE SUGESTÃO** — não altera título, descrição nem qualquer dado no Mercado Livre. A revisão e publicação são sempre manuais.

Agente: `agentes/ml/agente_otimizador_listing.py`  
Workflow semanal: `.github/workflows/otimizar_listing.yml` (terça-feira 08:00 BRT)

```bash
python -m agentes.ml.agente_otimizador_listing
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

## CI (GitHub Actions)

- **Qualidade em todo push/PR para `main`:** `.github/workflows/ci.yml` — roda `ruff check` e `pytest -q` automaticamente. Não usa Secrets nem executa rotinas de produção.
- **Orquestrador de produção:** `.github/workflows/agente_principal.yml` — continua disparado apenas por `schedule` e `workflow_dispatch` (relatório, chat, vendas WhatsApp, keepalive/algoritmo). Não roda em push/PR para evitar efeitos colaterais reais a cada commit.
- **Keepalive do próprio repositório:** `.github/workflows/manter_repositorio_ativo.yml` — o GitHub desativa automaticamente (e silenciosamente) todos os workflows agendados de um repositório depois de **60 dias sem nenhum push**. Esse workflow roda 2x por mês e faz um commit trivial (atualiza `logs/keepalive_status.json`) só pra contar como atividade e nunca deixar o repositório chegar nesse limite — sem ele, se ninguém der push manual por 2 meses, a renovação automática de token e todos os outros crons (`renovar_tokens.yml`, `conectividade_marketplaces.yml`, etc.) param de rodar sem nenhum aviso.

## Observabilidade com Datadog

O projeto pode enviar logs automaticamente para o **Datadog Log Management** via HTTP Intake API (sem Agent nem servidor). Basta configurar:

| Variável | Descrição |
|----------|-----------|
| `DD_API_KEY` | Chave de API — Datadog → Organization Settings → API Keys |
| `DD_SITE` | Região do site (padrão: `datadoghq.com`) |
| `DD_LOGS_ENABLED` | `true`/`false` — desligue com `false` para parar o envio sem alterar código |

**Opcional:** sem `DD_API_KEY`, o sistema funciona exatamente como antes — só não envia logs ao Datadog.

**Custo:** o Datadog cobra Log Management por volume ingerido (GB). O handler envia apenas nível **INFO ou superior** (nunca DEBUG). Se o custo for uma preocupação, use `DD_LOGS_ENABLED=false`.

**Filtros úteis no Datadog:** `service:robo-markplaces`, `marketplace:bling`, `marketplace:mercadolivre`, `level:info`, `level:warning`, `level:error`.

Módulo: `core/datadog_logger.py` — ativado automaticamente ao importar `core.config`.

## Agentes ML — cron GitHub Actions

Rotinas diárias do Mercado Livre (somente leitura ou com confirmação Telegram antes de escrita):

| Horário (BRT) | Workflow | Agente | Função |
|---------------|----------|--------|--------|
| 09:00 | `.github/workflows/monitor_ml.yml` | `agentes/ml/agente_monitor_ml.py` | Diagnóstico conta + Product Ads + concorrência |
| 10:00 | `.github/workflows/ads_gatilho_ml.yml` | `agentes/ml/agente_ads_gatilho.py` | Ligar/pausar/escalar ads (confirmação gestor) |
| 08:30 | `.github/workflows/panorama.yml` | `agentes/panorama/agente_panorama.py` | Visão geral ML + Magalu + Bling + síntese Claude |
| Seg 08:00 | `.github/workflows/relatorio_financeiro.yml` | `agentes/relatorio_financeiro.py` | Impacto financeiro estimado (repricing + ads) |
| Ter 08:00 | `.github/workflows/otimizar_listing.yml` | `agentes/ml/agente_otimizador_listing.py` | Sugestões de título ML via IA (somente leitura) |
| A cada 2h | `.github/workflows/sincronizar_estoque.yml` | `agentes/sincronizar_estoque_marketplaces.py` | Estoque Bling → ML/Magalu/Shopee |
| A cada 2h | `.github/workflows/operacao_24h_seguranca.yml` | `agentes/operacao_24h.py` | Repricing + faturamento (camada redundante ao n8n) |

Execução local:

```bash
python -m agentes.ml.agente_monitor_ml
python -m agentes.ml.agente_ads_gatilho
python -m agentes.ml.agente_otimizador_listing
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

## Deploy AWS (Free Tier) — opcional

Esta migração é **opcional e incremental**. Com `STORAGE_BACKEND=file` (padrão) ou sem
deploy na AWS, o projeto continua funcionando exatamente como hoje — arquivos JSON
locais, GitHub Actions nos crons, API via `python api/app.py`.

A branch `feature/aws-free-tier-migration` adiciona suporte a:

| Componente | Local (padrão) | AWS (opcional) |
|------------|----------------|----------------|
| Estado JSON | `core/atomic_io.py` → disco | `DynamoDBStateBackend` |
| API Flask | `python api/app.py` :5000 | Lambda + Function URL |
| Segredos (tokens) | GitHub Secrets (`github_secrets.py`) | SSM (`ssm_secrets.py`) |

### Antes do primeiro deploy

1. **Crie um AWS Budget de US$ 1** no console AWS (Billing → Budgets). Contas novas
   usam créditos por 6 meses; se algo fora do Always Free for criado sem querer, você
   é avisado no mesmo dia.
2. Instale [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam.html)
   e configure credenciais (`aws configure`).

### Deploy com SAM

```bash
cd infra
sam build
sam deploy --guided --stack-name robo-markplaces-aws-teste
```

No `--guided`, aceite criar a role IAM e confirme a região. Anote a saída
`ApiFunctionUrl` — é a URL para o n8n (com header `X-API-Key`).

Para destruir tudo depois dos testes:

```bash
sam delete --stack-name robo-markplaces-aws-teste
```

### Trocar storage para DynamoDB

1. Faça o deploy SAM (cria a tabela `robo-markplaces-estado-teste`).
2. Migre os JSONs locais (idempotente):

```bash
export STORAGE_BACKEND=dynamodb
export DYNAMODB_TABLE_NAME=robo-markplaces-estado-teste
export AWS_REGION=us-east-1
python scripts/migrar_estado_para_dynamodb.py
# opcional: --dry-run para apenas listar
```

3. Na Lambda (ou localmente para testar), defina `STORAGE_BACKEND=dynamodb` e
   `DYNAMODB_TABLE_NAME` com o nome da tabela criada.

### Variáveis novas

| Variável | Default | Descrição |
|----------|---------|-----------|
| `STORAGE_BACKEND` | `file` | `file` ou `dynamodb` |
| `DYNAMODB_TABLE_NAME` | `robo-markplaces-state` | Tabela quando backend=dynamodb |
| `AWS_REGION` | `us-east-1` | Região AWS |
| `SSM_PARAMETER_PREFIX` | `/robo-markplaces` | Prefixo dos parâmetros SSM |

### O que NÃO migra nesta fase

- Workflows GitHub Actions (`.github/workflows/*.yml`) — continuam como estão.
- `core/github_secrets.py` — continua para os crons no Actions.
- EC2, RDS, NAT Gateway — não incluídos no template SAM.

## Monitor de leilões de veículos (24h)

Agente opcional que varre **leiloeiros principais** e portais **DETRAN de todos os 27 estados** buscando veículos **recuperados de furto com média monta**.

Modelos já configurados e ativos (por prioridade): **Fiorino Furgão**, **Gol**, **Civic**, **City**, **Fit**.

- Catálogo: `catalogo/leiloes_veiculos_monitorados.json` — campo `perfil: recuperado_furto_media_monta` e `prioridade` (1 = mais importante)
- Agente: `python -m agentes.leilao.agente_leilao_veiculo`
- Workflow: `.github/workflows/leilao_veiculo.yml` (cron **2×/dia** BRT 08h/17h; fila `monitor-secundario`)
- Alertas Telegram gestor: **resumo da varredura** (1×/hora, padrão) + alerta **detalhado** quando houver achado **novo**
- Variáveis: `LEILAO_ALERTA_RESUMO` (1), `LEILAO_ALERTA_RESUMO_COOLDOWN_SEG` (3600)
- Histórico: `logs/leilao_veiculos_history.json` (restaurado via cache entre execuções no GitHub Actions)
- Preflight: `python scripts/preflight_monitor_telegram.py` (valida token antes de rodar)

A busca usa DuckDuckGo (`site:dominio` por leiloeiro/DETRAN) — sem API paga. Cliente compartilhado: `core/ddg_lite.py` (GET em `lite.duckduckgo.com` por padrão, rate limit global, retry, circuit breaker). Se aparecer **DDG HTTP 403** ou erros de conexão no Datadog, é rate limit temporário; o agente faz retry e pausa automática. Variáveis opcionais: `DDG_BACKEND` (`lite` padrão, `html`, `auto`), `DDG_DISABLED` (1), `DDG_MIN_INTERVAL_SEG` (2.5), `DDG_RETRY_MAX` (3), `DDG_CIRCUIT_BREAKER_SEG` (300), `DDG_FALHAS_403_PARA_BREAKER` (5), `DDG_ALIBABA_SKIP_SE_DIRETO` (1). Ajuste `LEILAO_PAUSA_ENTRE_FONTES_SEG` ou `ORQUESTRADOR_EXCLUIR=leilao` se quiser aliviar carga.

## Orquestrador 30 minutos (todos os agentes)

Agente que **a cada 30 minutos** executa todos os monitores do robô em sequência, envia **resumo consolidado** ao Telegram gestor e **métricas** ao Datadog (`robo.orquestrador.*`).

- Módulo: `python -m agentes.orquestrador.agente_orquestrador`
- Workflow: `.github/workflows/orquestrador_30min.yml` (cron `*/30 * * * *` UTC)
- Catálogo de agentes: `agentes/orquestrador/registro_agentes.py` (21 agentes)
- Excluir agentes lentos: env `ORQUESTRADOR_EXCLUIR=leilao,alibaba` (vírgula; já aplicado nos workflows do orquestrador e push main)
- Preflight: `python scripts/preflight_producao.py` (Telegram + renovação ML)
- Cooldown do resumo: `ORQUESTRADOR_COOLDOWN_RESUMO_SEG` (padrão 1500s)
- Telegram: `core/telegram_gate.py` valida token (`getMe`) e abre circuit breaker em 404 — `TELEGRAM_CIRCUIT_BREAKER_SEG` (padrão 3600s) evita spam de ERROR no Datadog com token revogado

**Segurança:** repricing, estoque, NF-e e operação 24h rodam em **dry-run** dentro do orquestrador; escrita real continua nos workflows dedicados (`operacao_24h_seguranca`, etc.).

**Não incluídos** (rotinas diárias/semanais ou destrutivas): `publicador`, `relatorio`, `relatorio_financeiro`, `otimizador_listing`.

## Sync push main (manual)

Agente que roda **sob demanda** (`workflow_dispatch`) executando os agentes do push main. **Não** dispara mais após CI (evitava filar o grupo de tokens ~50 min e atrasar análises). **Não remove** os crons dos workflows abaixo — eles continuam nos horários cadastrados.

- Módulo: `python -m agentes.orquestrador.agente_sync_push_main`
- Workflow: `.github/workflows/push_main_rotinas.yml` (somente **Run workflow** manual; fila própria `robo-markplaces-push-main-sync`)
- Métricas Datadog: `robo.push_main.*`
- Extras além do orquestrador 30min: relatório GitHub, relatório financeiro, otimizador listing (`renovar_tokens` fica no cron dedicado)

### Horários cadastrados (crons UTC — mantidos)

| Workflow | Cron (UTC) | Frequência aprox. (BRT) |
|----------|------------|-------------------------|
| `orquestrador_30min.yml` | `*/30 * * * *` | A cada 30 min |
| `renovar_tokens.yml` | `*/30 * * * *` | A cada 30 min |
| `agente_principal.yml` | `*/30 9-21`, `*/30 22` | Chat/vendas ~08h–21h30 |
| `agente_principal.yml` | `0 3,9,15,21` | Keepalive 00/06/12/18h |
| `agente_principal.yml` | `0 9` | Relatório 08h |
| `operacao_24h_seguranca.yml` | `0 */2 * * *` | A cada 2h |
| `sincronizar_estoque.yml` | `0 */2 * * *` | A cada 2h |
| `leilao_veiculo.yml` | `0 11,20 * * *` | 2×/dia (acompanhar) |
| `alibaba_importacao.yml` | `0 */2 * * *` | A cada 2h |
| `conectividade_marketplaces.yml` | `0 * * * *` | A cada hora |
| `panorama.yml` | `30 9 * * *` | 08:30 diário |
| `monitor_ml.yml` | `0 10 * * *` | 09:00 diário |
| `monitor_concorrentes_ml.yml` | `0 9 * * *` | 08:00 diário |
| `ads_gatilho_ml.yml` | `0 11 * * *` | 10:00 diário |
| `relatorio_financeiro.yml` | `0 9 * * 1` | Segunda 08h |
| `otimizar_listing.yml` | `0 9 * * 2` | Terça 08h |
| `descoberta_produtos.yml` | `0 11 * * 3` | Quarta 08h |
| `push_main_rotinas.yml` | manual | Sync completo sob demanda |

## Descoberta de produtos por marketplace

Agente que analisa cada marketplace ativo (`spec/spec.yaml`) e identifica **público-alvo** + **oportunidades de produto** com base em busca real (ML) e inferência via Claude.

- Catálogo: `catalogo/descoberta_nichos.json` — nichos, termos de busca e `marketplaces` alvo
- Agente: `python -m agentes.descoberta.agente_descoberta_produtos`
- Workflow: `.github/workflows/descoberta_produtos.yml` (quarta-feira 08h BRT)
- Orquestrador 30min: incluído como `descoberta_produtos` (somente leitura)
- Histórico: `logs/descoberta_produtos_history.json`
- **Snapshot da última rodada:** `logs/descoberta_produtos_ultima_rodada.json` (painel completo para decisão)
- Alertas Telegram gestor:
  - **Painel de decisão** (1×/dia) — marketplace + público + margem estimada + Alibaba
  - **Nova análise** de marketplace
  - **Novos fornecedores Alibaba** para importação

**Cruzamento Alibaba:** para cada oportunidade identificada no marketplace, o agente busca fornecedores no Alibaba.com (preço USD, MOQ, distribuidor, URL) e estima margem de importação vs preço médio do mercado.

**Por marketplace hoje:**

| Marketplace | Coleta | Análise |
|-------------|--------|---------|
| Mercado Livre | Busca pública por termo (preços, vendas, títulos) | Claude + fallback estatístico |
| Shopee / Magalu / Amazon | Saúde da conta + hints do catálogo | Claude infere público típico da plataforma |

Para ativar Shopee/Magalu/Amazon na descoberta: marque `ativo: true` em `spec/spec.yaml` e inclua o id em `marketplaces` do nicho.

```json
{
  "id": "kits-esmalte-manicure-ml",
  "ativo": true,
  "nome": "Kits esmalte manicure",
  "marketplaces": ["mercadolivre"],
  "termo_busca": "kit esmalte impala manicure profissional",
  "termo_alibaba_en": "nail polish kit wholesale professional",
  "publico_alvo_hint": "manicures profissionais",
  "preco_alvo_min": 35,
  "preco_alvo_max": 80,
  "alibaba_preco_max_usd": 8,
  "alibaba_moq_max": 500
}
```

Variáveis: `DESCOBERTA_NICHOS_CATALOGO`, `DESCOBERTA_BUSCAR_ALIBABA` (1), `DESCOBERTA_ALIBABA_PRECO_MAX_USD` (15), `DESCOBERTA_ALIBABA_MOQ_MAX` (1000), `DESCOBERTA_CAMBIO_USD_BRL` (5.5), `DESCOBERTA_ALERTA_PAINEL_COOLDOWN_SEG` (86400), `ANTHROPIC_API_KEY` (recomendado).

## Monitor Alibaba — oportunidades de importação (2h)

Agente que varre [Alibaba.com](https://www.alibaba.com/) buscando fornecedores para produtos que você configurar (preço máximo USD, MOQ máximo).

- Catálogo: `catalogo/alibaba_produtos_importacao.json`
- Agente: `python -m agentes.importacao.agente_alibaba_importacao`
- Workflow: `.github/workflows/alibaba_importacao.yml` (cron **a cada 2 horas**)
- Alertas Telegram gestor: **resumo da varredura** (1×/2h, padrão) + alerta **detalhado** quando houver anúncio **novo**
- Variáveis: `ALIBABA_ALERTA_RESUMO` (1), `ALIBABA_ALERTA_RESUMO_COOLDOWN_SEG` (7200)
- Histórico: `logs/alibaba_importacao_history.json` (restaurado via cache entre execuções no GitHub Actions)
- Preflight: `python scripts/preflight_monitor_telegram.py`

Exemplo de produto no catálogo (produto inicial configurado: **filamento impressora 3D**):

```json
{
  "id": "filamento-impressora-3d-pla",
  "ativo": true,
  "nome": "Filamento impressora 3D",
  "termo_busca": "3D printer filament PLA 1.75mm 1kg wholesale",
  "termo_busca_pt": "filamento impressora 3D PLA 1,75mm 1kg atacado",
  "preco_max_usd": 4.5,
  "moq_max": 200
}
```

O Alibaba é muito JavaScript — a busca combina página pública de search + fallback `site:alibaba.com`. Resultados podem variar; use termos em inglês em `termo_busca` para melhor cobertura.

## Qualidade recomendada

- Lint: `ruff check .`
- Formatação: `ruff format .`