# PROMPT — corrigir `unittest discover` no Windows (5 errors de encoding)

Cole no Cursor dentro de `Robo-Markplaces`.

**Sintoma:** `py -m unittest discover` roda 679 testes mas termina com
`FAILED (errors=5)` enquanto `pytest` passa 100%.

**Causa conhecida:** testes que executam scripts com `print()` de emoji
no stdout (ex.: `test_diagnostico_bling`, `test_preencher_item_id_ml`)
quebram no console Windows (cp1252).

Crie a branch `fix/unittest-discover-windows` antes de começar.

---

## PASSOS

1. Identificar os 5 testes com `unittest discover -v` e confirmar
   `UnicodeEncodeError` no traceback.

2. Corrigir **sem mudar comportamento dos scripts**:
   - Opção A: nos testes, redirecionar `sys.stdout` para `io.StringIO`
     com encoding utf-8 durante `subprocess` / `runpy`
   - Opção B: `PYTHONIOENCODING=utf-8` só no ambiente do teste
   - Opção C: substituir emojis nos scripts de diagnóstico por ASCII
     (último recurso — preferir A/B)

3. Documentar no README ou comentário do teste por que o redirect existe.

---

## VALIDAR

```bash
ruff check .
py -m unittest discover -s tests -p "test_*.py"
py -m pytest tests -q --no-cov
```

Ambos com exit code 0 e 679 testes sem falha.
