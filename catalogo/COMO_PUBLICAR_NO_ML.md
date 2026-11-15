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

Quando o anúncio estiver publicado:
```json
"mercadolivre": {
  "ativo": true,
  "estoque": 10    ← validação; sobe para 30 depois
}
```

Dimensões do anúncio: a caixa, não o frasco. Frente S20: **16 × 11 × 10 cm**. Peso do SKU (MIMO 0,280 kg, PERL 0,380 kg, Ju Paes 0,450 kg). Product Ads desligado até 20 avaliações, nota 4,8 e ACOS até 20%.

### 5. Faça git push

```bash
git add catalogo/produtos.json
git commit -m "feat: item_ids reais do ML configurados"
git push
```

O robô começa a monitorar e responder perguntas automaticamente.

## Kits para publicar (em ordem de prioridade)

Fonte: `catalogo/estrategia_entrada_ml.json`. Taxa ML 18%. Piso operacional 15%.

Compre **24 caixas S20** (CaixasNet, código `S20-16x11x10`, ~R$ 0,98/un): 12 MIMO + 12 PERL.

### Onda 0 — mesmo dia em que fotos e títulos estiverem prontos

| SKU | Título | Preço fase 1 | Caixa | Peso |
|-----|--------|--------------|-------|------|
| IMP-MIMO-003 | Kit 3 Esmaltes Impala Mimo + Carmed Manicure | R$ 44,90 | S20 16×11×10 cm | 0,280 kg |
| IMP-PERL-004 | Kit 4 Esmaltes Impala Perolado Tendência Tons da Moda Manicure | R$ 39,90 | S20 16×11×10 cm | 0,380 kg |

Estoque no anúncio: 10, depois 30. MIMO não iguala líder barato. PERL só baixa depois, com rival de kit 4 perolado ao vivo, gap de pelo menos 3% e preço ainda acima de R$ 39,15.

### Onda 1 — só depois do 1º pedido que fechar margem

| SKU | Título | Preço fase 1 | Caixa | Peso |
|-----|--------|--------------|-------|------|
| IMP-JUPAES-006 | Kit 6 Ju Paes — Virando o Jogo | R$ 64,90 | S20 16×11×10 cm | 0,450 kg |

### Fora desta entrada

Bailarina (IMP-BAIL-005), sortidos 6, POV 8, kits 10/12/15/30, bundle do alicate e Cruzeiro ficam sem MLB agora. Margem abaixo do piso ou caixa S03 (31×20×11,5 cm) que só entra com preço acima do piso. Detalhe em `catalogo/estrategia_entrada_ml.json`.
