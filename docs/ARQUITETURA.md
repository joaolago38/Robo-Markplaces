# Arquitetura — Robo-Markplaces

Esquema da arquitetura atual do robô de operação em marketplaces (chat, estoque, repricing, monitores de mercado, importação e alertas).

## Desenho (visão em camadas)

![Arquitetura Robo-Markplaces](arquitetura-robo-markplaces.png)

*Arquivo: [`docs/arquitetura-robo-markplaces.png`](arquitetura-robo-markplaces.png)*

## 1. Visão geral

```mermaid
flowchart TB
  subgraph triggers [Disparadores]
    GHA["GitHub Actions<br/>crons / workflows"]
    N8N["n8n<br/>webhooks / crons"]
    CLI["CLI local<br/>python -m agentes.*"]
    API_HTTP["API Flask<br/>POST /…"]
  end

  subgraph app [Robo-Markplaces]
    ORQ["Orquestrador 30 min<br/>agentes/orquestrador"]
    AG["Agentes de domínio<br/>agentes/*"]
    CORE["Core<br/>config, HTTP, Claude, guardrails"]
    INT["Integrações<br/>integracoes/*"]
    CAT["Catálogo + estado<br/>catalogo/ · logs/"]
  end

  subgraph externos [Sistemas externos]
    ML["Mercado Livre"]
    SH["Shopee"]
    MG["Magalu"]
    AM["Amazon"]
    BL["Bling ERP"]
    ALI["Alibaba"]
    META["Meta Ads / Inbox"]
    CLAUDE["Anthropic Claude"]
    TG["Telegram gestor"]
    WA["WhatsApp"]
    DD["Datadog"]
    AWS["AWS opcional<br/>Lambda · DynamoDB · SSM"]
  end

  GHA --> ORQ
  GHA --> AG
  N8N --> API_HTTP
  CLI --> AG
  API_HTTP --> AG
  ORQ --> AG
  AG --> CORE
  AG --> INT
  AG --> CAT
  INT --> ML & SH & MG & AM & BL & ALI & META
  CORE --> CLAUDE & TG & WA & DD
  CORE --> AWS
```

## 2. Camadas lógicas

| Camada | Pasta | Responsabilidade |
|--------|--------|------------------|
| Entrada | `api/`, `.github/workflows/`, `n8n/` | HTTP, crons CI, automações externas |
| Orquestração | `agentes/orquestrador/` | Ciclo periódico, registro de agentes, resumo |
| Domínio | `agentes/*` | Casos de uso (chat, monitor, estoque, social…) |
| Integração | `integracoes/*` | Clientes e parsers por sistema externo |
| Plataforma | `core/` | Config, HTTP, IA, métricas, kill switch, I/O atômico |
| Dados locais | `catalogo/`, `logs/` | Produtos, concorrentes, snapshots, histórico |
| Testes | `tests/` | Unitários dos fluxos críticos |

```mermaid
flowchart LR
  A[Entrada<br/>API · Actions · n8n] --> B[Orquestração / Agentes]
  B --> C[Integrações]
  B --> D[Core]
  C --> E[APIs externas]
  D --> E
  B --> F[catalogo / logs]
```

**Regra de dependência:** agentes chamam `integracoes` + `core`; integrações não devem conhecer agentes; `core` não depende de agentes.

## 3. Orquestrador e categorias de agentes

O orquestrador (`agente_orquestrador.py` + `registro_agentes.py`) executa o catálogo a cada ~30 min (workflow `orquestrador_30min.yml`), com pause entre agentes, métricas Datadog e resumo no Telegram.

```mermaid
flowchart TB
  ORQ[Orquestrador]
  ORQ --> INFRA[infra]
  ORQ --> CHAT[chat]
  ORQ --> OP[operacao]
  ORQ --> MON[monitor]
  ORQ --> SOC[social]
  ORQ --> VEN[vendas]

  INFRA --- I1[conectividade · vigia_datadog · consumo_claude · keepalive · algoritmo]
  CHAT --- C1[chat ML/Shopee/Magalu/Amazon · auto_respostas]
  OP --- O1[estoque · repricing · inteligência preços · operação 24h]
  MON --- M1[ML · esmaltes · filamentos · Alibaba · leilões · veículos · licitações · descoberta]
  SOC --- S1[Meta · manicures · promoções · conversão]
  VEN --- V1[WhatsApp · margem vendas]
```

Agentes de escrita destrutiva ou rotinas diárias ficam de fora do ciclo de 30 min (ex.: publicador, relatório financeiro semanal) e rodam em workflows dedicados.

## 4. Fluxo operacional típico (marketplaces)

```mermaid
sequenceDiagram
  participant Cron as GitHub Actions / Orquestrador
  participant Ag as Agente
  participant Core as core
  participant Int as integracoes/*
  participant Mkt as Marketplace / Bling
  participant TG as Telegram

  Cron->>Ag: executar()
  Ag->>Core: guardrails / Claude / config
  Ag->>Int: cliente (ML, Shopee, …)
  Int->>Mkt: HTTP API
  Mkt-->>Int: payload
  Int-->>Ag: dados normalizados
  Ag->>Core: atomic_io → logs/catalogo
  alt alerta relevante
    Ag->>TG: alertar_gestor
  end
  Ag->>Core: métricas Datadog
```

### Chat com IA

1. Agente de canal busca mensagens pendentes  
2. Resolve produto (Bling / catálogo / claim)  
3. Claude gera resposta contextualizada (`core/claude_*`)  
4. Envia resposta no marketplace (respeitando `ROBO_PAUSAR_ESCRITA`)

### Estoque

`Bling (saldo real) → catalogo/produtos.json → atualizar_estoque` em ML / Magalu / Shopee.

### Importação (ML × Alibaba)

`sinais ML → busca Alibaba (com meta coleta/anti-bot) → margem landed → veredito → Telegram`.

## 5. Integrações (mapa)

```mermaid
mindmap
  root((integracoes))
    Marketplaces
      ml
      shopee
      magalu
      amazon
      marketplaces
    ERP / Fiscal
      bling
      lojahub
    Importação
      alibaba
      importacao
      cambio
      filamentos
    Inteligência de mercado
      esmaltes
      descoberta
      comparativo
      vendas
    Outros
      leilao
      veiculos
      licitacao
      meta
      social
      datadog
```

## 6. Plataforma (`core`) — serviços transversais

| Módulo | Função |
|--------|--------|
| `config.py` | Env vars e flags |
| `http_client.py` / `http_errors.py` | HTTP unificado + métricas |
| `claude_client.py` / `claude_orcamento.py` / `claude_toggle.py` | IA + orçamento + pause |
| `guardrails.py` | Kill switch de escrita |
| `notificador.py` / `telegram_*` | Alertas gestor |
| `datadog_metrics.py` / `datadog_logger.py` | Observabilidade |
| `token_manager.py` / `github_secrets.py` / `ssm_secrets.py` | Segredos e refresh |
| `atomic_io.py` / `state_backend.py` | Persistência segura (arquivo / DynamoDB) |
| `prontidao.py` | Checagem de credenciais |

```mermaid
flowchart LR
  AG[Agente] --> GR{ROBO_PAUSAR_ESCRITA?}
  GR -->|sim| SKIP[Somente leitura / dry-run]
  GR -->|não| WRITE[Escrita marketplace / Bling]
  AG --> CLAUDE{CLAUDE_ATIVO + orçamento}
  CLAUDE -->|ok| AI[Resposta / análise]
  CLAUDE -->|bloqueado| FB[Fallback / skip]
  AG --> DD[Datadog logs + metrics]
  AG --> TG[Telegram]
```

## 7. Persistência e estado

```mermaid
flowchart TB
  subgraph local [Local / Actions runner]
    CAT["catalogo/*.json<br/>produtos, concorrentes, Alibaba"]
    LOG["logs/*.json<br/>snapshots, history, toggle Claude"]
  end

  subgraph aws_opt [AWS opcional]
    DDB[(DynamoDB<br/>locks / state)]
    SSM[SSM Parameter Store<br/>secrets]
    LAMBDA[API Lambda + SAM]
  end

  AG[Agentes] --> CAT
  AG --> LOG
  AG -.-> DDB
  CORE[core] -.-> SSM
  API[api/app.py] -.-> LAMBDA
```

## 8. Observabilidade e operação

```mermaid
flowchart LR
  AG[Agentes / HTTP] --> LOGS[DatadogLogHandler]
  AG --> MET[datadog_metrics]
  LOGS --> DD[Datadog]
  MET --> DD
  VIGIA[agente_vigia_datadog] --> DD
  VIGIA --> TG[Telegram crítico]
  ORQ[Orquestrador] --> MET
  ORQ --> TG
```

- Métricas com tags de baixa cardinalidade (`agente:`, `ok:`, `origem:`)  
- Vigia detecta erros e inatividade  
- Cooldown em alertas Telegram para evitar spam

## 9. Deploy e CI

```mermaid
flowchart TB
  DEV[Push / PR] --> CI[GitHub Actions<br/>testes + workflows]
  CI --> MAIN[main]
  MAIN --> CRONS[Crons por domínio]
  MAIN --> ORQ30[orquestrador_30min]
  MAIN --> SYNC[push_main / push_deploy]
  OPT[SAM opcional] --> AWS[Lambda API]
```

| Mecanismo | Uso |
|-----------|-----|
| Workflows em `.github/workflows/` | Agentes agendados (ML, esmaltes, Alibaba, estoque, tokens…) |
| `orquestrador_30min.yml` | Varredura ampla + resumo |
| Flask `api/app.py` | Entrada HTTP / n8n |
| `api/lambda_handler.py` | Deploy AWS opcional |

## 10. Domínios de negócio (resumo)

| Domínio | Exemplos de agentes | Integrações principais |
|---------|---------------------|-------------------------|
| Chat & atendimento | `agente_ml`, Shopee, Magalu, Amazon, auto_respostas | ML/Shopee/Magalu/Amazon, Bling, Claude |
| Preço & estoque | repricing, sync estoque, inteligência preços | Bling + canais |
| Esmaltes / manicures | Anita, kits, Impala, acetona, Meta, ecossistema | ML, Meta, planilhas |
| Filamentos 3D | monitor filamentos + cruzamento Alibaba | ML, Alibaba, câmbio |
| Importação | Alibaba, ML×Alibaba, cálculo aéreo | Alibaba, ML, câmbio |
| Veículos / leilões | Sumaré, FIPE, carros batidos | scrapers / sites |
| Infra | vigia Datadog, consumo Claude, conectividade | Datadog, Anthropic |

## 11. Como estender

1. Lógica de API externa → `integracoes/<dominio>/`  
2. Caso de uso agendável → `agentes/<dominio>/agente_*.py` com `executar()`  
3. Registrar em `registro_agentes.py` (se for no ciclo de 30 min) e/ou criar workflow em `.github/workflows/`  
4. Flags em `core/config.py` + `.env.exemplo`  
5. Testes em `tests/`  
6. Alertas via `core.notificador.alertar_gestor`

---

*Documento vivo: atualizar quando novas camadas, canais ou fluxos críticos forem adicionados.*
