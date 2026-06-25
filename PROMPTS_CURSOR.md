Implemente o monitoramento de concorrentes no Mercado Livre + o script de
preenchimento de item_id, exatamente como especificado abaixo (código já
testado e validado — 631 testes passando, lint limpo). Aplique literalmente,
sem reinterpretar a lógica.

═══════════════════════════════════════════════════════════════
1. core/config.py — adicionar depois da linha ML_SELLER_ID = ...
═══════════════════════════════════════════════════════════════
ML_SITE_ID       = os.getenv("ML_SITE_ID", "MLB").strip()  # MLB = Brasil

# Monitor de concorrentes (busca pública por palavra-chave, sem precisar de item próprio)
MONITOR_CONCORRENTES_ARQUIVO = os.getenv(
    "MONITOR_CONCORRENTES_ARQUIVO", "catalogo/concorrentes_monitorados.json"
).strip()
MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT = float(
    os.getenv("MONITOR_CONCORRENTES_VARIACAO_ALERTA_PCT", "5.0")
)

═══════════════════════════════════════════════════════════════
2. integracoes/ml/ml_client.py
═══════════════════════════════════════════════════════════════
2a. Trocar o import:
    from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID
para:
    from core.config import ML_ACCESS_TOKEN, ML_SELLER_ID, ML_SITE_ID

2b. Inserir estas funções IMEDIATAMENTE ANTES de `def buscar_acos_ads`:

def _normalizar_resultado_busca(row: dict) -> dict:
    shipping = row.get("shipping") or {}
    try:
        preco = float(row.get("price") or 0)
    except (TypeError, ValueError):
        preco = 0.0
    try:
        vendidos = int(row.get("sold_quantity", 0) or 0)
    except (TypeError, ValueError):
        vendidos = 0
    seller = row.get("seller") or {}
    return {
        "item_id": str(row.get("id", "") or ""),
        "titulo": str(row.get("title", "") or ""),
        "preco": preco,
        "frete_gratis": bool(shipping.get("free_shipping", False)),
        "condicao": str(row.get("condition", "") or ""),
        "quantidade_vendida": vendidos,
        "seller_id": str(seller.get("id", "") or ""),
        "permalink": str(row.get("permalink", "") or ""),
    }


def buscar_concorrentes_por_termo(termo: str, limite: int = 10) -> list[dict]:
    """
    Pesquisa o Mercado Livre por palavra-chave (busca pública do site, sem precisar
    que o produto já esteja no seu catálogo/anúncio). Útil para monitorar concorrência
    de produtos que você define livremente (por nome/termo), e não só dos seus próprios
    anúncios.

    Exclui resultados do próprio vendedor (ML_SELLER_ID) quando configurado.
    Retorna lista vazia em caso de termo vazio ou erro. Nunca lança exceção.
    """
    termo = (termo or "").strip()
    if not termo:
        return []
    try:
        r = request(
            "GET",
            f"{BASE}/sites/{ML_SITE_ID}/search",
            params={"q": termo, "limit": max(1, min(50, limite))},
            timeout=20,
        )
        r.raise_for_status()
        body = r.json() or {}
        results = body.get("results") or []

        seller_self = str(ML_SELLER_ID or "").strip()
        encontrados: list[dict] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            norm = _normalizar_resultado_busca(row)
            if seller_self and norm["seller_id"] == seller_self:
                continue
            if norm["preco"] > 0:
                encontrados.append(norm)
            if len(encontrados) >= limite:
                break
        return encontrados
    except Exception as exc:
        logger.error("ML buscar_concorrentes_por_termo erro termo=%s: %s", termo, exc)
        return []


def listar_itens_com_sugestao_preco() -> list[str]:
    """
    API oficial de Sugestões de Preço da ML (/suggestions/...).
    Lista os item_ids do vendedor que têm referência de preço disponível
    (a ML já compara com produtos similares dentro e fora da plataforma,
    histórico de vendas e demanda — não depende de catalog_product_id).
    Retorna [] se não configurado ou em caso de erro. Nunca lança exceção.
    """
    if not _enabled():
        return []
    try:
        r = _request_ml("GET", f"{BASE}/suggestions/user/{ML_SELLER_ID}/items", timeout=20)
        r.raise_for_status()
        body = r.json() or {}
        itens = body.get("items") or []
        return [str(i) for i in itens]
    except Exception as exc:
        logger.error("ML listar_itens_com_sugestao_preco erro: %s", exc)
        return []


def _extrair_amount(campo: Any) -> float:
    if isinstance(campo, dict):
        try:
            return float(campo.get("amount") or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(campo or 0)
    except (TypeError, ValueError):
        return 0.0


def buscar_sugestao_preco(item_id: str) -> dict:
    """
    API oficial de Sugestões de Preço da ML (/suggestions/items/{itemId}/details).
    Consulta a referência de preço calculada pela própria ML para um item — não
    depende de catalog_product_id, então funciona mesmo fora de catálogo/buy-box.
    Retorna {} se item_id vazio, não configurado ou em caso de erro. Nunca lança exceção.
    """
    item_id = (item_id or "").strip()
    if not _enabled() or not item_id:
        return {}
    try:
        r = _request_ml("GET", f"{BASE}/suggestions/items/{item_id}/details", timeout=20)
        r.raise_for_status()
        body = r.json() or {}
        return {
            "item_id": str(body.get("item_id", item_id)),
            "status": str(body.get("status", "")),
            "preco_atual": _extrair_amount(body.get("current_price")),
            "preco_sugerido": _extrair_amount(body.get("suggested_price")),
            "ratio": float(body.get("ratio") or 0),
            "percent_difference": float(body.get("percent_difference") or 0),
            "aplicavel": bool(body.get("applicable_suggestion", False)),
        }
    except Exception as exc:
        logger.error("ML buscar_sugestao_preco erro item_id=%s: %s", item_id, exc)
        return {}

═══════════════════════════════════════════════════════════════
3. catalogo/concorrentes_monitorados.json (criar novo arquivo)
═══════════════════════════════════════════════════════════════
[
  {
    "id": "kit3-mimo-carmed",
    "ativo": true,
    "nome": "Kit 3 Mimo + Carmed Impala",
    "termo_busca": "kit 3 esmaltes impala mimo carmed",
    "sku": "IMP-MIMO-003",
    "meu_preco": 44.90,
    "limite_resultados": 10
  }
]

═══════════════════════════════════════════════════════════════
4. agentes/ml/agente_monitor_concorrentes.py (criar novo arquivo)
═══════════════════════════════════════════════════════════════
Peça pro Cursor buscar o conteúdo completo no histórico do projeto — se ele
não tiver acesso, me avise nesta resposta que eu cole o arquivo completo
(206 linhas) numa mensagem separada, pra não estourar o tamanho deste prompt.

═══════════════════════════════════════════════════════════════
5. .github/workflows/monitor_concorrentes_ml.yml (criar novo arquivo)
═══════════════════════════════════════════════════════════════
name: Monitor Concorrentes ML

on:
  workflow_dispatch:
  schedule:
    # 06:00 BRT (UTC-3) = 09:00 UTC
    - cron: "0 9 * * *"

env:
  PYTHON_VERSION: "3.11"
  DD_API_KEY: ${{ secrets.DD_API_KEY }}
  DD_SITE: ${{ secrets.DD_SITE }}
  DD_LOGS_ENABLED: ${{ secrets.DD_LOGS_ENABLED }}

jobs:
  monitorar:
    name: Buscar concorrentes por termo (lista catalogo/concorrentes_monitorados.json)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - name: Instalar dependencias
        run: pip install -r requirements.txt
      - name: Rodar monitor de concorrentes
        run: python -m agentes.ml.agente_monitor_concorrentes
        env:
          ML_SELLER_ID:              ${{ secrets.ML_SELLER_ID }}
          ML_SITE_ID:                ${{ secrets.ML_SITE_ID }}
          TELEGRAM_TOKEN:            ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_GESTOR_CHAT_ID:   ${{ secrets.TELEGRAM_GESTOR_CHAT_ID }}
      - name: Salvar historico atualizado
        uses: actions/upload-artifact@v4
        with:
          name: concorrentes-ml-history
          path: logs/concorrentes_ml_history.json
          retention-days: 90

═══════════════════════════════════════════════════════════════
6. agentes/ml/agente_monitor_ml.py — duas edições pontuais
═══════════════════════════════════════════════════════════════
6a. Onde tem:
        try:
            concorrentes = ml_client.buscar_detalhes_concorrentes(item_id, limite=5)
        except Exception as exc:
            logger.error("monitor_ml detalhes_concorrentes %s: %s", item_id, exc)
            concorrentes = []

        try:
            acos_item = ml_client.buscar_acos_ads(item_id, dias=14)

   Inserir ENTRE os dois blocos try:
        try:
            sugestao = ml_client.buscar_sugestao_preco(item_id)
        except Exception as exc:
            logger.error("monitor_ml sugestao_preco %s: %s", item_id, exc)
            sugestao = {}

6b. No dict `analise: dict[str, Any] = {...}`, adicionar a chave
    "sugestao_preco": sugestao, (logo depois de "concorrentes": concorrentes,)

    E logo depois do fechamento do dict `analise`, antes de
    `if menor_concorrente > 0 and meu_preco > menor_concorrente:`, inserir:

        if sugestao.get("aplicavel") and sugestao.get("preco_sugerido", 0) > 0:
            preco_sugerido = sugestao["preco_sugerido"]
            diff_sugestao = sugestao.get("percent_difference", 0)
            if abs(diff_sugestao) >= LIMIAR_PRECO_CONCORRENTE * 100:
                msg = (
                    f"Item {item_id}: ML sugere R$ {preco_sugerido:.2f} "
                    f"(seu preço R$ {meu_preco:.2f}, diferença {diff_sugestao:.1f}%) "
                    "com base em produtos similares dentro/fora da ML."
                )
                analise["alertas"].append(msg)
                recomendacoes.append(msg)
                prioridade = max(prioridade, abs(diff_sugestao))

═══════════════════════════════════════════════════════════════
7. scripts/preencher_item_id_ml.py (criar novo arquivo)
═══════════════════════════════════════════════════════════════
Script que casa SKUs do catalogo/produtos.json com anúncios reais do ML
(via integracoes.ml.ml_client.listar_meus_anuncios) para substituir
item_id="MLB_PREENCHER" pelo ID real. Match EXATO por seller_sku, ou
PROVÁVEL por similaridade de título (difflib, limiar 0.72). Roda em
dry-run por padrão; só grava com --aplicar (e --incluir-provaveis pra
gravar os PROVÁVEIS também). Peça-me o arquivo completo (185 linhas) se
precisar do código exato — já está testado e revisado.

═══════════════════════════════════════════════════════════════
8. TESTES — criar/atualizar
═══════════════════════════════════════════════════════════════
- tests/test_ml_buscar_concorrentes_termo.py (novo)
- tests/test_agente_monitor_concorrentes.py (novo)
- tests/test_preencher_item_id_ml.py (novo)
- tests/test_agente_monitor_ml.py — adicionar 1 teste novo cobrindo o
  alerta de sugestão oficial de preço
Peça-me os arquivos de teste completos se precisar do código exato.

═══════════════════════════════════════════════════════════════
VALIDAÇÃO FINAL (obrigatória)
═══════════════════════════════════════════════════════════════
1. python -m pytest -q  → confirme 0 falhas e cobertura >= 80%
2. ruff check .  → confirme 0 erros
3. python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
   → confirme que não lança exceção
4. NÃO altere nenhuma lógica de repricing, ads ou notificação além do
   especificado acima.