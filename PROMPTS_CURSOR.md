# Prompt para o Cursor — Importar a planilha de NCM no Bling

Cole no Cursor (Agent). Peça: "aplicar e rodar só o dry-run; NÃO aplicar no Bling sem eu confirmar."

---

## Prompt

### Título: Importar Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx (NCM) para o Bling

**Prompt:**
```
Quero importar os NCM da planilha Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx para os
produtos no Bling, usando o script já existente scripts/cadastrar_ncm_bling.py.

1) Commite a planilha em dados/Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx.

2) Se scripts/cadastrar_ncm_bling.py NÃO existir no repo, crie-o conforme o
   PROMPT_CURSOR_CADASTRO_NCM_AUTO (lê a aba "Produtos NCM" com as colunas
   "SKU (código no Bling)", "NCM (sugerido)" e "Validar c/ contador?"; dry-run por
   padrão; idempotente; pula itens marcados "Validar" a menos que --incluir-validar).
   Garanta também: openpyxl em requirements.txt; e as funções de NCM em
   integracoes/bling/bling_client.py (atualizar_ncm_produto, definir_ncm_por_sku).

3) RODE PRIMEIRO O DRY-RUN (não grava nada) e me mostre a saída COMPLETA:
   python scripts/cadastrar_ncm_bling.py --arquivo dados/Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx
   O dry-run vai mostrar, por SKU, "NCM atual -> NCM novo", e no resumo quantos
   foram "não encontrados" (produto inexistente no Bling), "já corretos" e "a atualizar".

4) PARE aqui. NÃO rode com --aplicar até eu analisar o dry-run e confirmar.

Para rodar é preciso ter as variáveis do Bling no ambiente (BLING_CLIENT_ID,
BLING_CLIENT_SECRET, BLING_ACCESS_TOKEN, BLING_REFRESH_TOKEN). Se nenhuma resposta
vier do Bling (tudo "não encontrado" ou erro), me avise — provavelmente o token está
inválido ou os produtos ainda não existem no Bling.
```

**Contexto:**
- Planilha: `dados/Cadastro_NCM_Bling_Impala_Cruzeiro.xlsx` (aba "Produtos NCM", 501 produtos).
- Script: `scripts/cadastrar_ncm_bling.py` (já criado em prompt anterior).
- Pré-requisitos: (a) token do Bling funcionando; (b) produtos já cadastrados no Bling com o SKU batendo com a coluna "SKU (código no Bling)" — por padrão o SKU é o EAN.

**Resultado esperado:**
- O dry-run lista o de-para de NCM e o resumo. Se aparecer muita linha "não encontrado", os produtos ainda não estão no Bling (ver alternativa abaixo).

**Status:** ⬜ a fazer

---

## Importante — qual caminho usar

Esse prompt usa o robô/API e **só atualiza o NCM de produtos que JÁ existem no Bling** (ele acha o produto pelo SKU). Ele NÃO cria produtos. Então:

- Se os produtos já estão no Bling → este prompt resolve (confirme o token e o SKU).
- Se os produtos ainda NÃO estão no Bling, ou o token do robô não está funcionando →
  o caminho mais simples é importar pelo **painel do Bling** (Produtos → Importar),
  que **cria** os produtos já com NCM e **não depende do token do robô**. Nesse caso a
  planilha precisa ser convertida para o layout de importação do Bling (colunas como
  Código, Descrição, NCM, Origem, Unidade). Me peça que eu gero essa versão da planilha
  no formato do Bling.

## Atenção fiscal

Itens marcados "Validar c/ contador? = Sim" na planilha (acetona, água oxigenada,
cremes, bundle com alicate) ficam de fora por padrão. Só inclua-os (--incluir-validar)
depois de validar o NCM com o contador.