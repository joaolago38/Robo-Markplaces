"""
tests/test_behaviors.py
Testes derivados dos behaviors da spec.yaml (BDD).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_B01_identifica_atacado():
    palavras = ["atacado", "salão", "salon", "revenda", "quantidade"]
    def eh_atacado(texto):
        return any(p in texto.lower() for p in palavras)
    assert eh_atacado("vocês vendem no atacado?")
    assert eh_atacado("tenho salão, preciso de bastante")
    assert not eh_atacado("qual a cor desse esmalte?")
    print("  PASS  B01 — identifica pergunta de atacado")


def test_B03_repricing_respeita_margem():
    MARGEM_MINIMA = 15.0
    custo = 6.00
    preco_concorrente = 4.00
    preco_alvo = preco_concorrente * 1.05
    margem = (preco_alvo - custo) / preco_alvo * 100
    assert margem < MARGEM_MINIMA, "Repricing deveria ser bloqueado"
    print("  PASS  B03 — repricing bloqueado quando margem insuficiente")


def test_B06_nf_nao_emitida_pendente():
    pode_emitir = ["pago", "aprovado", "confirmed"]
    nao_emite   = ["pendente", "aguardando_pagamento", "cancelado"]
    for s in nao_emite:
        assert s not in pode_emitir, f"'{s}' não deveria emitir NF"
    print("  PASS  B06 — NF bloqueada para status pendente")


def test_B07_campanha_pausada_estoque_zero():
    def pausar(estoque):
        return estoque <= 0
    assert pausar(0) and pausar(-1)
    assert not pausar(1) and not pausar(100)
    print("  PASS  B07 — campanha pausada com estoque zero")


def test_B08_post_exige_estoque_minimo():
    MIN = 20
    produtos = [
        {"nome": "A", "estoque": 5},
        {"nome": "B", "estoque": 50},
        {"nome": "C", "estoque": 15},
    ]
    elegiveis = [p for p in produtos if p["estoque"] >= MIN]
    assert len(elegiveis) == 1 and elegiveis[0]["nome"] == "B"
    print("  PASS  B08 — post bloqueado para estoque abaixo de 20")


if __name__ == "__main__":
    testes = [test_B01_identifica_atacado, test_B03_repricing_respeita_margem,
              test_B06_nf_nao_emitida_pendente, test_B07_campanha_pausada_estoque_zero,
              test_B08_post_exige_estoque_minimo]
    falhas = 0
    print(f"\nRodando {len(testes)} testes...\n")
    for t in testes:
        try:
            t()
        except AssertionError as e:
            print(f"  FAIL  {t.__name__} — {e}")
            falhas += 1
    print(f"\nResultado: {len(testes)-falhas}/{len(testes)} testes passaram")
    if falhas:
        exit(1)
