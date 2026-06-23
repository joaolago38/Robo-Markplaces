Corrija o campo "JSON Body" de 3 nodes HTTP nos workflows do n8n, que estão dando o erro "The value in the JSON Body field is not valid JSON" ao executar.

CONTEXTO DO BUG:
Esses 3 nodes misturam texto JSON literal com chamadas de função JavaScript (`Number(...)`, comparação `=== 'true'`) dentro de um campo que usa o prefixo `=` (modo "campo inteiro é uma expressão"), sem usar `{{ }}` ao redor da parte dinâmica. Isso faz o n8n tentar validar a string resultante como JSON estrito e falhar, porque `Number(...)` e `===` não são sintaxe JSON válida.

A correção é trocar para o padrão seguro do n8n: manter o texto como JSON literal e envolver SÓ a parte dinâmica (o valor calculado) em `{{ }}`, em vez de usar `=` sozinho no início pra tratar o campo inteiro como JavaScript puro.

TAREFA:

1. Em `n8n/workflows/robo_markplaces_rotinas.json`, localize o node `HTTP Keepalive` (id `http-keepalive`). O campo `jsonBody` está assim:
   ```
   "jsonBody": "={\"limite_dias_sem_acesso\": Number($vars.ROBO_KEEPALIVE_DIAS || 5)}"
   ```
   Troque para:
   ```
   "jsonBody": "={\"limite_dias_sem_acesso\": {{ Number($vars.ROBO_KEEPALIVE_DIAS || 5) }} }"
   ```

2. No mesmo arquivo, localize o node `HTTP Algoritmo`. O campo `jsonBody` está assim:
   ```
   "jsonBody": "={\"alertar_quando_atencao\": ($vars.ROBO_ALERTAR_ATENCAO || 'false') === 'true'}"
   ```
   Troque para:
   ```
   "jsonBody": "={\"alertar_quando_atencao\": {{ ($vars.ROBO_ALERTAR_ATENCAO || 'false') === 'true' }} }"
   ```

3. Em `n8n/workflows/robo_markplaces_meta_metricas.json`, localize o node `HTTP Meta Metricas`. O campo `jsonBody` está assim:
   ```
   "jsonBody": "={\"alertar_quando_atencao\": ($vars.ROBO_ALERTAR_ATENCAO || 'false') === 'true', \"periodo_dias\": 1}"
   ```
   Troque para:
   ```
   "jsonBody": "={\"alertar_quando_atencao\": {{ ($vars.ROBO_ALERTAR_ATENCAO || 'false') === 'true' }}, \"periodo_dias\": 1}"
   ```

4. Procure em TODOS os arquivos `n8n/workflows/*.json` por qualquer outro campo `jsonBody` (ou `body`, dependendo do node) que misture chaves JSON literais com chamadas de função JavaScript (`Number(`, `===`, `||` dentro de uma expressão de valor, etc.) sem `{{ }}` ao redor — aplique a mesma correção (envolver só a parte dinâmica em `{{ }}`) em qualquer ocorrência que encontrar, mesmo que eu não tenha listado aqui. Os campos `jsonBody` que já são JSON literal puro (ex.: `={"dry_run_repricing": true, "dry_run_nfe": true}`) ou que usam `={{$json.body}}` (passthrough completo) já estão corretos e NÃO devem ser alterados.

5. Depois de corrigir, valide que cada `jsonBody` alterado é, depois de mentalmente substituir o `{{ }}` pelo valor que ele produziria, um JSON válido (chaves bem fechadas, vírgulas corretas) — para não introduzir um novo erro de sintaxe.

6. Não há testes automatizados em Python pra arquivos `.json` do n8n — não precisa criar testes, mas liste ao final, para cada arquivo alterado, o valor final do campo `jsonBody` corrigido, para eu poder confirmar visualmente.