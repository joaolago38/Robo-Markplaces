# Como publicar os kits no Mercado Livre e ativar o robô

## Passo a passo

### 1. Publique cada kit manualmente no ML

Acesse: https://www.mercadolivre.com.br/anuncios/criar

Para cada kit use o título sugerido no campo `titulo_anuncio`
do arquivo `catalogo/produtos.json`.

### 2. Após publicar, copie o ID de cada anúncio

O ID aparece na URL do anúncio:
```
https://produto.mercadolivre.com.br/MLB-XXXXXXXXX-nome-do-produto
                                         ^^^^^^^^^^^
                                         Este é o item_id
```

Formato: `MLB` + números (ex: `MLB3456789012`)

### 3. Atualize o catalogo/produtos.json

Para cada kit, substitua `MLB_PREENCHER` pelo ID real:

```json
"canais": {
  "mercadolivre": {
    "ativo": true,
    "item_id": "MLB3456789012",   ← substitua aqui
    ...
  }
}
```

### 4. Ative o canal no catálogo

Quando o anúncio estiver publicado e com avaliações:
```json
"mercadolivre": {
  "ativo": true,   ← já está true
  "estoque": 50    ← atualize o estoque real
}
```

### 5. Faça git push

```bash
git add catalogo/produtos.json
git commit -m "feat: item_ids reais do ML configurados"
git push
```

O robô começa a monitorar e responder perguntas automaticamente.

## Kits para publicar (em ordem de prioridade)

| SKU | Título sugerido | Preço fase 1 |
|-----|----------------|-------------|
| IMP-ATAC-010 | Kit 10 Esmaltes Impala Atacado Manicure | R$ 69,90 |
| IMP-COLC-015 | Kit 15 Esmaltes Impala Cores da Moda    | R$ 79,90 |
| IMP-SORT-006 | Kit 6 Esmaltes Impala Sortidos          | R$ 49,90 |
| IMP-MIMO-003 | Kit 3 Esmaltes Impala Mimo + Carmed     | R$ 44,90 |
| IMP-GRAN-030 | Kit 30 Esmaltes Impala Atacado          | R$ 145,00 |

Comece pelos kits de atacado (10 e 15 unidades) — são os que
as manicures mais buscam e têm ticket maior.
