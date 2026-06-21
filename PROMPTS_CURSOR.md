# Prompt — Criar teste de diagnóstico Mercado Livre + NF-e (Robo-Markplaces)

Crie um novo arquivo **`scripts/testar_ml_e_nfe.py`** no projeto Robo-Markplaces,
seguindo o MESMO estilo do `scripts/testar_integracao.py` já existente (mesmos
helpers `log()`, `checar()`, prefixos `[OK]/[ERRO]/[INFO]`, bloco de resultado
final com contagem e `sys.exit(0 if falhou == 0 else 1)`, e o ajuste de
`sys.path` para a raiz do projeto).

O objetivo do script é diagnosticar a operação diária em 4 blocos. Use SOMENTE
as funções que já existem no projeto (não invente nomes nem assinaturas):

## TESTE 1 — Mercado Livre: perguntas dos clientes
- Importe `from integracoes.ml import ml_client`.
- Se `ml_client._enabled()` for False, marque como IGNORADO (não como falha):
  registre um aviso de que o ML não está configurado e siga em frente.
- Se configurado, chame `ml_client.listar_perguntas_nao_respondidas()` e:
  - confirme que retornou uma lista (use `checar`),
  - imprima as 3 primeiras perguntas (campos `text` e `item_id`),
  - chame `ml_client.obter_saude_conta()` e imprima `pendencias`, `claims_rate`
    e `dias_sem_acesso`.

## TESTE 2 — Mercado Livre: situação dos Product Ads
- Importe `from integracoes.ml import ml_product_ads`.
- Se ML não estiver configurado, marque IGNORADO.
- Chame `ml_product_ads.obter_advertiser()`. Se vier `ok=False`:
  - é um AVISO, não falha de código; se `codigo == "sem_permissao"`, oriente a
    ativar em "Mercado Livre > Mi perfil > Publicidad". Marque IGNORADO.
- Se `ok=True`: confirme que há `advertiser_id` (use `checar`), depois chame
  `ml_product_ads.listar_campanhas(advertiser_id, dias=14)` e imprima:
  - total de campanhas, quantas estão `active`,
  - até 5 campanhas com `nome`, `status`, `acos`, `cost`.
  - chame `ml_product_ads.campanhas_acos_acima_limite(campanhas)` e avise se
    houver campanhas com ACOS acima do limite.

## TESTE 3 — Pedidos pagos prontos para faturar (há NF-e a gerar?)
- Se ML não configurado, marque IGNORADO.
- Chame `ml_client.listar_pedidos(dias=7)`, confirme que é lista (use `checar`),
  e imprima até 5 pedidos com `order_id`, `total` e os `sku` dos itens.
- Guarde a lista de pedidos para reutilizar no TESTE 4.

## TESTE 4 — NF-e automática: o que falta para emitir
- Importe `from agentes.faturamento.agente_faturamento import emitir_nfe_pedido`
  e `from core import config as cfg`.
- IMPORTANTE: NUNCA emita nota de verdade. Chame `emitir_nfe_pedido(pedido,
  dry_run=True)` — dry-run apenas monta e valida o payload, não envia ao Bling.
- Monte o `pedido` assim:
  - Se houver pedidos reais do TESTE 3, use o primeiro, convertendo seus itens
    para o formato `{"sku","quantidade","valor_unitario"}` e cliente
    `{"nome":"Consumidor Final","documento":""}`.
  - Se não houver pedidos (ou itens sem SKU), use um pedido SIMULADO:
    `{"pedido_id":"SIMULADO-1","cliente":{...},"itens":[{"sku":"ESM-001",
    "quantidade":1,"valor_unitario":9.9}]}`.
- Se `resultado["ok"]` for True: marque OK ("payload montado, emissão pronta").
- Se for False: NÃO é falha de código — é o diagnóstico. Marque IGNORADO,
  imprima o `erro` e cada item de `resultado["erros"]` como pendência.
- Ao final, imprima um checklist fiscal lendo os defaults de `cfg`
  (`NFE_NATUREZA_OPERACAO`, `NFE_CFOP_PADRAO`, `NFE_CST_PADRAO`,
  `NFE_CSOSN_PADRAO`, `NFE_ORIGEM_PADRAO`, `NFE_SERIE_PADRAO`) e liste os
  requisitos para emissão 100% automática:
  1. Todo produto com NCM válido (8 dígitos) no Bling/catálogo fiscal.
  2. Dados do destinatário (nome/documento/endereço) vindos do pedido.
  3. Escopo "NFe" autorizado no app do Bling (OAuth).
  4. Certificado digital A1 configurado na conta Bling.
  5. Série/numeração fiscal habilitada no Bling.

## Regras gerais
- O script NUNCA deve lançar exceção não tratada: envolva cada bloco em
  try/except e, em erro inesperado, use `checar(False, "", f"Exceção...")`.
- Distinga três estados: OK (passou), ERRO (falha de código → conta como falha),
  e IGNORADO (integração não configurada / sem permissão → não conta como falha).
  No resumo final, mostre quantas foram ignoradas separadamente das que falharam.
- `sys.exit(0)` quando não houver ERRO (ignorados não reprovam o teste).
- É um script de diagnóstico seguro para rodar no GitHub Actions: como tudo é
  leitura e a NF-e é só dry-run, não há efeitos colaterais.
- Ao terminar, confirme que o arquivo compila (`python -m py_compile
  scripts/testar_ml_e_nfe.py`) e me diga o comando para rodar.

## Opcional
Se possível, crie também o workflow `.github/workflows/testar_ml_e_nfe.yml` nos
mesmos moldes do `testar_integracao.yml` existente, acionável por
`workflow_dispatch`, instalando as dependências e rodando
`python scripts/testar_ml_e_nfe.py`.