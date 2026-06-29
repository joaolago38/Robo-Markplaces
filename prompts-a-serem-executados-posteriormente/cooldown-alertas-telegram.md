# PROMPT — cooldown de alertas Telegram (evitar spam a cada cron)

Cole no Cursor dentro de `Robo-Markplaces`.
Use quando o **mesmo** alerta crítico/gestor repetir a cada 30–60 min
sem mudança de causa (ex.: token Magalu inválido por horas).

Crie a branch `fix/cooldown-alertas-telegram` antes de começar.

---

## CONTEXTO

`alertar_critico()` e `alertar_gestor()` enviam sempre que chamados.
Crons (`vendas_whatsapp`, `algoritmo`, `conectividade`) podem disparar
a mesma mensagem dezenas de vezes até alguém corrigir o token.

---

## ESCOPO

### `core/notificador.py`

1. Arquivo de estado `logs/alertas_cooldown.json` (ou similar)
2. Função interna `_deve_suprimir(chave: str, cooldown_segundos: int) -> bool`
3. Parâmetros opcionais em `alertar_critico` e `alertar_gestor`:
   - `chave: str | None = None` (default: hash da mensagem)
   - `cooldown_segundos: int = 7200` (2 h — configurável via env `ALERTA_COOLDOWN_SEG`)

### Chamadores prioritários

- `agentes/vendas_notificador.py` → `_checar_busca_falhou`
  - chave: `falha_pedidos:{marketplace}`
- `agentes/algoritmo_marketplaces.py`
  - chave: `f"saude:{nome}:{status}"`
- `agentes/conectividade_marketplaces.py`
  - chave: `f"conectividade:{marketplace}"`

### Testes

`tests/test_notificador_cooldown.py`:
- primeira chamada envia
- segunda dentro do cooldown não envia
- após cooldown (mock de tempo) envia de novo

---

## GARANTIA

- Cooldown é por **chave**, não global — alertas diferentes não se bloqueiam
- Falha ao ler/gravar cooldown → envia alerta (fail-open para não perder incidente)
- Não altera texto das mensagens existentes

---

## VALIDAR

```bash
ruff check .
py -m pytest tests -q --no-cov
```
