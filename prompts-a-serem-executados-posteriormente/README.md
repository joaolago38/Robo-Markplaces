# Prompts a serem executados posteriormente

Cole o conteúdo de cada arquivo `.md` inteiro no Cursor, dentro do repositório `Robo-Markplaces`.

## Como usar

1. Abra o prompt desejado.
2. Cole no chat do Cursor (modo Agent).
3. Siga a ordem das fases — cada prompt pede validação (`ruff` + testes) antes de seguir.
4. Marque como concluído nesta tabela quando terminar (opcional: mova para `prompts-executados/`).

## Índice

| Arquivo | Quando usar | Branch sugerida | Status |
|---------|-------------|-----------------|--------|
| [alertas-recorrentes-magalu-amazon.md](./alertas-recorrentes-magalu-amazon.md) | Telegram repetindo score 0 + “não consegui buscar pedidos Magalu/Amazon” | `fix/alertas-recorrentes-magalu-amazon` | Pendente |
| [confiabilidade-shopee-amazon-detalhado.md](./confiabilidade-shopee-amazon-detalhado.md) | Estender padrão `*_detalhado` / `dados.degradado` para Shopee e Amazon | `feature/confiabilidade-shopee-amazon` | Pendente |
| [conectividade-shopee-amazon.md](./conectividade-shopee-amazon.md) | Incluir Shopee e Amazon no agente `conectividade_marketplaces` | `feature/conectividade-shopee-amazon` | Pendente |
| [cooldown-alertas-telegram.md](./cooldown-alertas-telegram.md) | Mesmo alerta crítico/gestor disparando a cada cron (spam) | `fix/cooldown-alertas-telegram` | Pendente |
| [unittest-discover-encoding-windows.md](./unittest-discover-encoding-windows.md) | `unittest discover` falha no Windows (5 errors em scripts com emoji) | `fix/unittest-discover-windows` | Pendente |

## Já executados (referência)

O prompt mestre de **7 fases** (Datadog + confiabilidade ML/Magalu + keepalive do repo) foi aplicado na branch `feature/datadog-completo-ml-magalu`. Não está duplicado aqui para evitar reexecução acidental.

O arquivo legado `PROMPTS_CURSOR.md` na raiz contém apenas a **Fase 1** antiga do Datadog (substituída pelo pacote completo de 7 fases).
