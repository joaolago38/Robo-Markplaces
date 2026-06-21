# Prompt — Painel unificado com Claude: ML + Magalu + Bling (visão total, NF-e, alertas, concorrência) + cobertura 90%

Crie no projeto Robo-Markplaces um **orquestrador de visão geral** que dá ao
Claude um panorama completo de Mercado Livre, Magazine Luiza (Magalu) e Bling,
emite nota fiscal, dispara alertas e — no caso do Mercado Livre — analisa contas
concorrentes para recomendar decisões objetivas. Entregue também testes com
**cobertura mínima de 90%** nos arquivos novos.

REGRA DE OURO (segurança): a coleta e a análise são automáticas, mas qualquer
AÇÃO DE ESCRITA que tenha efeito real — emitir NF-e de verdade, mudar preço,
pausar/escalar campanha, alterar estoque — só pode rodar com flag explícita
(`dry_run=False` e/ou confirmação do gestor). O padrão é SEMPRE o modo seguro
(coleta + recomendação + alerta), nunca agir sozinho.

---

## ARQUIVO 1 — `agentes/panorama/agente_panorama.py`

Função principal: `gerar_panorama(enviar_alerta: bool = True, emitir_nfe: bool = False, limite_itens: int = 15) -> dict`

Reutilize SOMENTE funções já existentes no projeto (não reescreva integrações):

**Mercado Livre** (`integracoes.ml.ml_client` e `integracoes.ml.ml_product_ads`):
- `_enabled()`, `obter_saude_conta()`, `listar_perguntas_nao_respondidas()`,
  `buscar_reputacao_vendedor()`, `listar_meus_anuncios()`,
  `buscar_metricas_item(item_id)`, `buscar_menor_preco_concorrente(item_id)`,
  `buscar_acos_ads(item_id)`, `obter_advertiser()`, `listar_campanhas(...)`,
  `campanhas_acos_acima_limite(...)`.
- Reaproveite o agente já existente `agentes.ml.agente_monitor_ml.analisar()`
  se ele já consolidar conta+ads+concorrência — chame-o em vez de duplicar.

**Magalu** (`integracoes.magalu.magalu_client`):
- `_enabled()`, `obter_saude_conta()`, `listar_perguntas_nao_respondidas()`,
  `listar_pedidos(dias=7)`.

**Bling** (`integracoes.bling.bling_client`):
- `listar_produtos()`, `estoques_criticos()`.

**NF-e** (`agentes.faturamento.agente_faturamento.emitir_nfe_pedido`):
- Para cada pedido pago (de ML e Magalu via `listar_pedidos`), monte o pedido no
  formato esperado e chame `emitir_nfe_pedido(pedido, dry_run=not emitir_nfe)`.
- Com `emitir_nfe=False` (padrão): dry-run — só valida o que está pronto e o que
  falta (NCM, destinatário etc.), sem emitir nada.
- Com `emitir_nfe=True`: emite de verdade, mas só os pedidos cujo dry-run passou.

**Alertas** (`core.notificador.alertar_gestor` / `alertar_critico`).

**Síntese com Claude** (`core.claude_client.perguntar`):
- Monte um texto com TODOS os dados coletados (conta, ads, concorrência,
  estoque crítico, pedidos a faturar, pendências fiscais) e peça ao Claude um
  resumo executivo curto + decisões priorizadas. Use o parâmetro `contexto`.
- O prompt ao Claude deve pedir resposta OBJETIVA em tópicos: "Situação",
  "Riscos", "Ações recomendadas (priorizadas)". Limite de tokens moderado.
- Se a `ANTHROPIC_API_KEY` não estiver setada ou Claude falhar, faça fallback:
  gere o resumo por regras (sem IA), nunca quebre.

**Análise de concorrentes no ML** (decisões concisas):
- Para até `limite_itens` anúncios meus: compare meu preço com
  `buscar_menor_preco_concorrente(item_id)`. Classifique cada item em uma decisão
  objetiva: "MANTER", "BAIXAR PREÇO (estou X% acima)", "REVISAR ANÚNCIO
  (visitas altas, sem giro)", "SEM DADOS DE CATÁLOGO".
- Ordene por prioridade (maior diferença de preço / maior gasto de ads primeiro)
  e inclua no panorama os 5 itens mais urgentes.

**Retorno** (dict estruturado):
```
{
  "ok": True,
  "mercado_livre": {...},        # saúde, ads, concorrência, decisões
  "magalu": {...},               # saúde, perguntas, pedidos
  "bling": {...},                # total produtos, estoque crítico
  "nfe": {"a_faturar": N, "prontos": N, "pendencias": [...], "emitidos": N},
  "alertas": [...],
  "resumo_claude": "texto",
  "decisoes": ["...", "..."],
  "enviado": True/False
}
```

**Comportamento sem credenciais:** cada marketplace ausente entra como
"não configurado" (não quebra, não conta como erro). Se NENHUM estiver
configurado, retorne `{ok: False, motivo: "nenhuma integração configurada"}` e
mande um alerta.

**Execução direta:** permita `python -m agentes.panorama.agente_panorama`,
chamando `gerar_panorama(enviar_alerta=False, emitir_nfe=False)` e imprimindo o
resultado.

Boas práticas obrigatórias: try/except por bloco, nunca propagar exceção;
respeitar rate limit (limitar nº de itens, pequenos sleeps se necessário);
nenhuma ação de escrita no modo padrão.

---

## ARQUIVO 2 — `tests/test_agente_panorama.py` (cobertura ≥ 90%)

Use `unittest` + `unittest.mock.patch`, no MESMO estilo de
`tests/test_agente_monitor_ml.py` (patchando as funções de integração no módulo
do agente, sem nenhuma chamada de rede real). Cubra TODOS os caminhos:

1. Nenhuma integração configurada → `ok=False`, alerta enviado.
2. Só ML configurado: com perguntas pendentes, com campanha de ACOS alto, e com
   item cujo preço está acima do concorrente → decisão "BAIXAR PREÇO".
3. Só Magalu configurado: perguntas + pedidos.
4. Bling: estoque crítico presente e ausente.
5. NF-e dry-run: pedido pronto (payload ok) e pedido bloqueado (sem NCM) → entra
   em `pendencias`. Teste também `emitir_nfe=True` com `emitir_nfe_pedido`
   mockado retornando ok.
6. Síntese Claude: caminho com `perguntar` mockado retornando texto, e caminho de
   fallback (perguntar lança/`⚠️`) garantindo que o resumo por regras é usado.
7. `enviar_alerta=True` chama `alertar_gestor`; `False` não chama.
8. Garanta que NENHUM teste faz I/O de rede (todos os clients mockados).

Inclua no rodapé `if __name__ == "__main__": unittest.main()`.

---

## ARQUIVO 3 — Configuração de cobertura

- Adicione `pytest-cov` ao `requirements-dev.txt` (já tem `pytest` e `ruff`).
- Rode localmente e garanta ≥ 90% nos arquivos novos:
  ```
  pip install -r requirements-dev.txt
  pytest tests/test_agente_panorama.py \
    --cov=agentes.panorama.agente_panorama --cov-report=term-missing
  ```
- Ajuste os testes até a cobertura do `agente_panorama.py` ficar ≥ 90%
  (idealmente cobrir também as linhas de fallback e de erro).

---

## ARQUIVO 4 (opcional) — Workflow

Crie `.github/workflows/panorama.yml` (workflow_dispatch + schedule diário,
ex. 08:30 BRT) que instala dependências e roda
`python -m agentes.panorama.agente_panorama`. Sem efeitos de escrita (modo
padrão seguro).

---

## Critérios de aceite (confirme ao final)
1. `python -m py_compile agentes/panorama/agente_panorama.py` sem erros.
2. `pytest tests/test_agente_panorama.py` todos verdes.
3. Cobertura do `agente_panorama.py` ≥ 90% (mostre o número do `--cov-report`).
4. Nenhuma chamada de rede real nos testes; nenhuma ação de escrita no modo padrão.
5. Reuso das funções existentes (sem duplicar integrações).

> Lembrete: roda no GitHub Actions a partir do que está commitado. Depois de
> gerar e passar os testes, faça commit e push na branch `main`.