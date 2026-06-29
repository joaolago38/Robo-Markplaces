# PROMPT MESTRE — alertas recorrentes de saúde CRÍTICO + falha de pedidos (Magalu/Amazon)

Cole isto no Cursor, dentro do repositório `Robo-Markplaces`.
Use quando o Telegram estiver repetindo mensagens como:
- `Saúde magalu: CRITICO (score 0)` (Gestor)
- `Saúde amazon: CRITICO (score 0)` + queda brusca (Gestor)
- `⚠️ Não consegui buscar pedidos novos no Magalu` (Crítico)

**Não aplique correções de código antes de diagnosticar.** A primeira
rodada é só leitura + comandos de diagnóstico. Só passe para correção
depois de classificar a causa-raiz em uma das categorias abaixo.

Crie a branch `fix/alertas-recorrentes-magalu-amazon` antes de qualquer
alteração de código.

---

## CONTEXTO — o que cada alerta significa no código

| Alerta Telegram | Origem no código | O que score 0 / falha costuma significar |
|-----------------|------------------|------------------------------------------|
| `Saúde {mp}: CRITICO (score 0)` | `agentes/algoritmo_marketplaces.py` → `core/marketplace_algorithm.py` | `configurado: false` em `obter_saude_conta()` **ou** penalidades graves (pendências, dias sem acesso, claims) |
| `Não consegui buscar pedidos novos no Magalu` | `agentes/vendas_notificador.py` → `_checar_busca_falhou()` | `listar_pedidos_detalhado()` retornou `ok=False` (token/API falhou — **não** é “sem vendas”) |
| Conectividade (se aparecer) | `agentes/conectividade_marketplaces.py` | `probe_conexao()` falhou — OAuth pode ter “renovado” mas API recusa |

**Score 0 quase sempre = `configurado: false`**, não necessariamente
conta suspensa. Verifique credenciais e se a chamada de saúde falhou.

---

## FASE 0 — Diagnóstico obrigatório (sem mudar código)

Rode **nessa ordem** e cole o output no resumo final:

```bash
# 1. Conectividade real (todos os MPs)
py scripts/verificar_marketplaces.py

# 2. Probe + métricas de conectividade ML/Magalu
py -c "from agentes.conectividade_marketplaces import executar; import pprint; pprint.pprint(executar())"

# 3. Saúde/algoritmo (o que gera o alerta do Gestor)
py -c "from agentes.algoritmo_marketplaces import executar; import pprint; pprint.pprint(executar())"

# 4. Simular busca de pedidos (o que gera o alerta Crítico)
py -c "
from integracoes.magalu.magalu_client import listar_pedidos_detalhado
p, ok = listar_pedidos_detalhado(dias=1)
print('ok=', ok, 'pedidos=', len(p))
"

# 5. Tokens (só renovação OAuth — não prova API)
py scripts/renovar_tokens.py

# 6. Histórico de score (últimos pontos Magalu/Amazon)
py -c "
import json
from pathlib import Path
h = json.loads(Path('logs/marketplace_algorithm_history.json').read_text(encoding='utf-8'))
for mp in ('magalu', 'amazon'):
    pts = h.get(mp, [])[-5:]
    print(mp, '->', [(p.get('ts'), p.get('score'), p.get('metrics', {}).get('configurado')) for p in pts])
"
```

**Classifique a causa** (pode ser mais de uma):

| Código | Causa provável | Evidência |
|--------|----------------|-----------|
| **A** | Credencial ausente/errada no ambiente que roda o cron | `verificar_marketplaces`: `configurado: false` ou probe 401 |
| **B** | Token expirado / refresh inválido | `renovar_tokens` falha; probe 401; `token.falha` no Datadog |
| **C** | API fora / rede / SSL | probe `status_http: 0` ou 5xx; `http.exception` no Datadog |
| **D** | `dias_sem_acesso` alto → score cai mesmo com token ok | `metrics.dias_sem_acesso >= 3`; keepalive/conectividade não registra acesso |
| **E** | Falso CRÍTICO: saúde falhou mas caiu em `configurado: false` | `obter_saude_conta` falhou internamente; score 0 sem probe 401 |
| **F** | Spam: mesmo problema alertando a cada cron | Mesmo erro em `vendas_whatsapp` + `algoritmo` no mesmo horário |
| **G** | Crons do GitHub desligados (60 dias sem push) | Actions sem runs recentes; `manter_repositorio_ativo.yml` falhou |

Pare e me mostre a classificação antes de implementar qualquer fix.

---

## FASE 1 — Correções operacionais (sem código, se A ou B)

Se **A** ou **B**, tente nesta ordem (documente o que funcionou):

1. GitHub → Settings → Secrets: conferir `MAGALU_*`, `AMAZON_*`, `ML_*`
2. Rodar workflow `renovar_tokens.yml` manualmente (workflow_dispatch)
3. Se Magalu rotacionou refresh: confirmar `MAGALU_TOKEN_STORE` no servidor
   e que `dados/magalu_token.json` está persistido entre restarts
4. Settings → Actions → Workflow permissions: **Read and write**
   (necessário para `manter_repositorio_ativo.yml` e sync de secrets)
5. Re-rodar Fase 0 — só seguir para Fase 2 se alertas persistirem **com**
   credenciais válidas e probe `ok: true`

---

## FASE 2 — Correções de código (escolha conforme a causa)

**Só implemente o bloco que bater com a classificação da Fase 0.**
Não misture todos de uma vez.

### 2A — Causa E: score 0 quando API falha (não quando “não configurado”)

- Garantir que falha de API distingue `configurado: true` + `api_ok: false`
- `core/marketplace_algorithm.py`: não retornar score 0 só por falha
  transitória; penalizar menos ou status `atencao` com mensagem explícita
- Testes em `tests/test_algoritmo_marketplaces.py`

### 2B — Causa F: spam de Telegram (mesmo erro a cada 30 min)

- `core/notificador.py`: cooldown por chave de alerta (ex.: 2–4 h)
  usando arquivo `logs/alertas_cooldown.json`
- `_checar_busca_falhou` e `algoritmo_marketplaces`: respeitar cooldown
- `alertar_critico` / `alertar_gestor`: parâmetro opcional `chave=` e
  `cooldown_segundos=`
- Testes: mesmo alerta 2x seguidas → só 1 Telegram

### 2C — Causa D: dias_sem_acesso sem keepalive real

- Confirmar `conectividade_marketplaces.yml` rodando e `registrar_acesso`
  em sucesso
- Se Amazon também score 0: estender `conectividade_marketplaces` com
  `probe_amazon` (mesmo padrão ML/Magalu)

### 2D — Causa B: auto-recuperação de token quando busca falha

- Em `get_token_magalu` / clients: se 401, tentar renovação **uma vez**
  antes de retornar `ok=False`
- Métrica `token.recuperacao_automatica` no Datadog
- Cuidado: refresh_token de uso único — não loop infinito
- Testes com mock de 401 → renovação → 200

### 2E — Ordem dos crons no `agente_principal.yml`

Reordenar jobs: renovar token → conectividade → vendas → algoritmo
(ou disparar conectividade como step prévio de vendas).

---

## FASE 3 — Validar

```bash
ruff check .
py -m pytest tests -q --no-cov
py scripts/verificar_marketplaces.py
py -c "from agentes.vendas_notificador import executar; print(executar())"
py -c "from agentes.algoritmo_marketplaces import executar; print(executar())"
```

Critérios de sucesso:
- `verificar_marketplaces`: Magalu `conectado: true` (se configurado)
- `listar_pedidos_detalhado(dias=1)` → `ok=True` (ou falha clara com 401 no probe)
- Próxima execução agendada **não** repete o mesmo Telegram em < 2 h (se Fase 2B aplicada)
- 679+ testes passando, ruff limpo

---

## O que NÃO fazer

- Não assumir “sem vendas” quando `ok=False`
- Não desligar `_checar_busca_falhou` para “parar o spam” sem cooldown
- Não force push de secrets para o repositório
- Não mude regras de preço/repricing neste prompt

---

## Resumo final (obrigatório)

1. Classificação da causa (A–G)
2. Output resumido dos 6 comandos da Fase 0
3. O que foi alterado (arquivo + motivo)
4. Se o problema era operacional (secrets/cron) ou código
5. Próximo passo no Datadog (`robo.conectividade.*`, `robo.token.*`, `robo.dados.degradado`)
