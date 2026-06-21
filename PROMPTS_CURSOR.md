# Prompt — Alertar quando o Bling entrar em estado "travado" (refresh não se auto-cura)

No projeto Robo-Markplaces, o script `scripts/renovar_tokens.py` renova os tokens
dos marketplaces e grava os refresh_tokens rotacionados de volta nos GitHub
Secrets (via `_sync_secrets_github`). ML e Magalu se auto-curam porque a renovação
deles funciona. O Bling, porém, pode entrar num estado TRAVADO: quando o
`BLING_REFRESH_TOKEN` já está inválido/expirado, a renovação falha com HTTP 400
ANTES de gravar um token novo — então o ciclo nunca se recupera sozinho e exige um
bootstrap manual com `pegar_token_bling.py`.

Hoje esse estado só aparece no log do GitHub Actions (e o job termina com exit 1),
o que é fácil de passar despercebido. Quero um ALERTA ATIVO quando isso acontecer.

## Alterações em `scripts/renovar_tokens.py`

1. Importe o notificador já existente:
   ```python
   from core.notificador import alertar_critico  # ou alertar_gestor
   ```
   (Use try/except no import para o script não quebrar caso o módulo falhe.)

2. No bloco do Bling, quando a renovação falhar (`res_bling.get("ok")` é False)
   OU quando o import/execução levantar exceção, dispare UM alerta claro e
   acionável, por exemplo:
   ```
   🚨 BLING TRAVADO — renovação automática falhou (refresh inválido/expirado).
   O ciclo não se auto-cura: é preciso bootstrap manual.
   Ação: rode `python pegar_token_bling.py SEU_CODE` e atualize os Secrets
   BLING_ACCESS_TOKEN e BLING_REFRESH_TOKEN no GitHub.
   Detalhe: <motivo retornado>
   ```
   - Inclua no texto o `motivo`/erro retornado, mas NUNCA imprima o token em si.
   - Envie via `alertar_critico(...)`.

3. Evite spam: dispare o alerta do Bling apenas UMA vez por execução (não dentro
   de loop). Se já existir um mecanismo de deduplicação de alertas no projeto,
   reutilize-o; senão, basta garantir um único envio por run.

4. Diferencie os dois sub-casos no texto do alerta, se detectável:
   - "refresh inválido/expirado" (HTTP 400 invalid_grant) → precisa bootstrap.
   - "BLING_CLIENT_SECRET ausente/errado" → precisa corrigir o Secret.
   Use a informação que `renovar_token_bling_detalhado()` já retorna (motivo/dica).

5. Não altere o comportamento de sucesso: quando o Bling renovar normalmente e o
   `_sync_secrets_github` gravar os tokens, NÃO envie alerta.

6. Mantenha o `exit code` atual (1 quando algo essencial falha), mas garanta que o
   alerta seja enviado ANTES do `return`/`sys.exit`.

## Opcional (recomendado)
- Faça o mesmo padrão de alerta para os OUTROS provedores quando entrarem em
  estado equivalente de "não renovou e não se auto-cura" (ex.: ML/Magalu falhando
  na renovação), reutilizando uma função auxiliar única
  `_alertar_token_travado(provedor: str, motivo: str)` para não duplicar texto.
- Se `alertar_critico` não estiver configurado (sem Telegram), o próprio
  notificador já imprime no stdout — apenas garanta que isso registre um
  `logger.warning` de "alerta não entregue" (alinhado com a correção de pontos
  cegos da camada de alertas).

## Testes
- Em `tests/`, adicione/atualize testes (estilo `unittest` + `patch`) que:
  - mockam `renovar_token_bling_detalhado()` retornando `{ok: False, motivo: ...}`
    e verificam que `alertar_critico` foi chamado UMA vez com texto contendo
    "BLING" e a orientação de bootstrap.
  - mockam o caminho de SUCESSO e verificam que `alertar_critico` NÃO é chamado.
  - garantem que nenhum token aparece no texto do alerta.
  - nenhum teste deve fazer chamada de rede real (mocke `_sync_secrets_github` e
    o notificador).

## Critérios de aceite
1. `python -m pytest -q` — tudo verde, sem regressão.
2. Ao simular Bling travado, um alerta crítico é enviado com instrução de
   bootstrap; no sucesso, nenhum alerta.
3. Nenhum token é exposto em log/alerta.

> Lembrete: roda no GitHub Actions a partir do que está commitado — depois de
> aplicar e passar os testes, faça commit + push na branch `main`.