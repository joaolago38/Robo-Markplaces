Estenda agentes/ml/agente_otimizador_listing.py para também sugerir
DESCRIÇÃO completa do anúncio (hoje ele só sugere título). Mantenha o
mesmo contrato de segurança já usado no resto do robô: é só leitura +
sugestão via IA — NUNCA escreve a descrição no ML automaticamente.
Aplique literalmente os trechos abaixo.

═══════════════════════════════════════════════════════════════
PASSO 1 — integracoes/ml/ml_client.py
Adicionar função para buscar a descrição atual do anúncio
(a ML só expõe descrição em endpoint separado, não vem em /items/{id}).
═══════════════════════════════════════════════════════════════

Adicionar depois de `buscar_metricas_item`:

```python
def buscar_descricao_item(item_id: str) -> str:
    """
    Busca a descrição (plain_text) de um anúncio do ML.
    Retorna string vazia se não houver descrição ou em caso de erro.
    Nunca lança exceção.
    """
    if not _enabled() or not (item_id or "").strip():
        return ""
    try:
        item_id = item_id.strip()
        r = _request_ml("GET", f"{BASE}/items/{item_id}/description", timeout=20)
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        data = r.json() or {}
        return str(data.get("plain_text", "") or "")
    except Exception as exc:
        logger.error("ML buscar_descricao_item erro item_id=%s: %s", item_id, exc)
        return ""
```

═══════════════════════════════════════════════════════════════
PASSO 2 — agentes/ml/agente_otimizador_listing.py
Adicionar prompt/system específico de descrição + função de sugestão.
═══════════════════════════════════════════════════════════════

2a. Trocar o docstring do topo do arquivo:

```python
"""
agentes/ml/agente_otimizador_listing.py
Sugestões de título para anúncios do Mercado Livre via Claude.
Somente leitura + recomendação — NÃO altera título nem descrição no ML.
"""
```

por:

```python
"""
agentes/ml/agente_otimizador_listing.py
Sugestões de título e descrição para anúncios do Mercado Livre via Claude.
Somente leitura + recomendação — NÃO altera título nem descrição no ML.
"""
```

2b. Adicionar, depois de `_PROMPT_SUGESTOES`, os prompts de descrição:

```python
SYSTEM_DESCRICAO = (
    "Você escreve descrições de anúncio para o Mercado Livre com base em dados reais "
    "fornecidos (próprio anúncio, descrição atual se houver, e concorrentes). "
    "Nunca invente especificações, certificações, prazos de garantia ou características "
    "do produto que não estejam no contexto fornecido — se faltar informação, escreva a "
    "descrição sem inventar esse dado, em vez de supor. Use linguagem direta, sem emojis, "
    "organizada em parágrafos curtos e, se fizer sentido, uma lista de bullet points com "
    "as principais características. Limite total: até 2000 caracteres."
)

_PROMPT_DESCRICAO = (
    "Com base nos dados acima (anúncio próprio, descrição atual se houver, e concorrentes), "
    "escreva uma sugestão de descrição completa para este anúncio. Se já existir uma "
    "descrição atual, aponte em 1 frase o que está sendo melhorado antes do texto novo."
)
```

2c. Atualizar `_montar_contexto` para receber a descrição atual e incluir
no contexto enviado à IA. Trocar a assinatura e o corpo:

```python
def _montar_contexto(metricas: dict, concorrentes: list[dict]) -> str:
    linhas = [
        "=== ANÚNCIO PRÓPRIO ===",
        f"Título atual: {metricas.get('titulo', '')}",
        f"Preço: R$ {float(metricas.get('preco', 0) or 0):.2f}",
        f"Estoque: {metricas.get('estoque', 0)}",
        f"Visitas 7 dias: {metricas.get('visitas_7d', 0)}",
        f"Visitas 30 dias: {metricas.get('visitas_30d', 0)}",
        f"Status: {metricas.get('status', '')}",
        "",
        "=== CONCORRENTES (mesmo catálogo) ===",
    ]
```

por:

```python
def _montar_contexto(metricas: dict, concorrentes: list[dict], descricao_atual: str = "") -> str:
    linhas = [
        "=== ANÚNCIO PRÓPRIO ===",
        f"Título atual: {metricas.get('titulo', '')}",
        f"Preço: R$ {float(metricas.get('preco', 0) or 0):.2f}",
        f"Estoque: {metricas.get('estoque', 0)}",
        f"Visitas 7 dias: {metricas.get('visitas_7d', 0)}",
        f"Visitas 30 dias: {metricas.get('visitas_30d', 0)}",
        f"Status: {metricas.get('status', '')}",
        f"Descrição atual: {descricao_atual.strip() or '(sem descrição cadastrada)'}",
        "",
        "=== CONCORRENTES (mesmo catálogo) ===",
    ]
```

(manter o resto da função igual — o loop de concorrentes não muda)

2d. Atualizar `analisar_item` para também buscar a descrição atual e
pedir a sugestão de descrição à IA, junto com a de título. Trocar:

```python
    try:
        metricas = ml_client.buscar_metricas_item(item_id) or {}
        if not metricas:
            return {"ok": False, "erro": f"item não encontrado ou indisponível: {item_id}"}

        concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        contexto = _montar_contexto(metricas, concorrentes)
        sugestoes = perguntar(
            _PROMPT_SUGESTOES,
            max_tokens=600,
            contexto=contexto,
            system=SYSTEM_OTIMIZADOR,
        )

        resultado: dict[str, Any] = {
            "ok": True,
            "item_id": item_id,
            "titulo_atual": metricas.get("titulo", ""),
            "visitas_7d": metricas.get("visitas_7d", 0),
            "visitas_30d": metricas.get("visitas_30d", 0),
            "sugestoes_texto": sugestoes,
            "concorrentes_analisados": len(concorrentes),
        }
        if _ia_falhou(sugestoes):
            resultado["ia_falhou"] = True
        return resultado
    except Exception as exc:
        logger.error("analisar_item erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "erro": str(exc)}
```

por:

```python
    try:
        metricas = ml_client.buscar_metricas_item(item_id) or {}
        if not metricas:
            return {"ok": False, "erro": f"item não encontrado ou indisponível: {item_id}"}

        descricao_atual = ml_client.buscar_descricao_item(item_id)
        concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        contexto = _montar_contexto(metricas, concorrentes, descricao_atual)

        sugestoes_titulo = perguntar(
            _PROMPT_SUGESTOES,
            max_tokens=600,
            contexto=contexto,
            system=SYSTEM_OTIMIZADOR,
        )
        sugestao_descricao = perguntar(
            _PROMPT_DESCRICAO,
            max_tokens=900,
            contexto=contexto,
            system=SYSTEM_DESCRICAO,
        )

        resultado: dict[str, Any] = {
            "ok": True,
            "item_id": item_id,
            "titulo_atual": metricas.get("titulo", ""),
            "descricao_atual": descricao_atual,
            "visitas_7d": metricas.get("visitas_7d", 0),
            "visitas_30d": metricas.get("visitas_30d", 0),
            "sugestoes_texto": sugestoes_titulo,
            "sugestao_descricao": sugestao_descricao,
            "concorrentes_analisados": len(concorrentes),
        }
        if _ia_falhou(sugestoes_titulo):
            resultado["ia_falhou"] = True
        if _ia_falhou(sugestao_descricao):
            resultado["ia_falhou_descricao"] = True
        return resultado
    except Exception as exc:
        logger.error("analisar_item erro item_id=%s: %s", item_id, exc)
        return {"ok": False, "erro": str(exc)}
```

2e. Atualizar `_montar_resumo_telegram` para incluir um trecho curto da
sugestão de descrição (sem mandar o texto completo de todos os itens no
mesmo alerta — só um preview, pra não estourar o limite de mensagem do
Telegram). Trocar:

```python
        sugestao = _primeira_sugestao(str(r.get("sugestoes_texto") or ""))
        if not sugestao:
            continue
        incluidos += 1
        linhas.append(f"• {r.get('item_id')} — {r.get('titulo_atual', '')[:50]}")
        linhas.append(f"  Visitas 7d: {r.get('visitas_7d', 0)}")
        linhas.append(f"  Sugestão: {sugestao}")
        linhas.append("")
```

por:

```python
        sugestao = _primeira_sugestao(str(r.get("sugestoes_texto") or ""))
        if not sugestao:
            continue
        incluidos += 1
        descricao_preview = str(r.get("sugestao_descricao") or "").strip().replace("\n", " ")[:120]
        linhas.append(f"• {r.get('item_id')} — {r.get('titulo_atual', '')[:50]}")
        linhas.append(f"  Visitas 7d: {r.get('visitas_7d', 0)}")
        linhas.append(f"  Sugestão título: {sugestao}")
        if descricao_preview:
            linhas.append(f"  Sugestão descrição (preview): {descricao_preview}...")
        linhas.append("")
```

═══════════════════════════════════════════════════════════════
PASSO 3 — api/app.py
Conferir o endpoint que já expõe analisar_item/analisar_catalogo (usado
pelo otimizador de listing) e garantir que o JSON de resposta devolve os
novos campos (descricao_atual, sugestao_descricao, ia_falhou_descricao)
sem filtrar/remover chaves do dict. Normalmente isso já funciona sozinho
se o endpoint apenas faz jsonify(resultado) — só confirme que não há
serialização manual campo a campo que precise ser atualizada.
═══════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════
PASSO 4 — Testes
═══════════════════════════════════════════════════════════════

- tests/test_ml_client.py: adicionar teste para `buscar_descricao_item`
  cobrindo: sucesso (retorna plain_text), 404 (retorna string vazia) e
  exceção de rede (retorna string vazia, não lança).
- tests/test_agente_otimizador_listing.py (criar se não existir):
  - `analisar_item` retorna `descricao_atual` e `sugestao_descricao`
    no dict de resultado.
  - quando `ml_client.buscar_descricao_item` retorna `""` (sem
    descrição), o contexto montado contém "(sem descrição cadastrada)"
    e a função não lança exceção.
  - `_montar_resumo_telegram` inclui a linha de preview de descrição só
    quando `sugestao_descricao` não está vazia.

Rode `pytest -q` no final e cole o resultado.

═══════════════════════════════════════════════════════════════
NÃO FAZER (fora de escopo deste prompt)
═══════════════════════════════════════════════════════════════
- Não criar nenhuma função que escreva a descrição de volta no ML
  (PUT /items/{id}/description). Isso fica para uma etapa futura
  separada, com dry_run/confirmar e guardrail, igual ao padrão usado em
  pausar_anuncio/atualizar_preco_item — não implementar "de brinde" aqui.
- Não replicar para Shopee/Magalu/Amazon neste prompt — escopo é só ML.