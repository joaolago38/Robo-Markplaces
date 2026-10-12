"""
integracoes/importacao/siscomex.py
Taxa de Utilização do Siscomex (TUS) — legislação brasileira vigente.

Referência:
  - Lei 9.716/1998, art. 3º
  - Decreto 6.759/2009 (RA), art. 306
  - Portaria ME nº 4.131/2021
  - IN RFB nº 2.024/2021 (valores por adição)

Fórmula (desde 01/06/2021):
  R$ 115,67 por DI/DUIMP
  + valor por adição de mercadoria (tabela decrescente)

DI simples (1 adição) = 115,67 + 38,56 = R$ 154,23
(O valor legado R$ 214,50 = 185+29,50 da Portaria MF 257/2011 NÃO deve mais ser usado.)
"""
from __future__ import annotations

from typing import Any

# Portaria ME 4.131/2021 + IN RFB 2.024/2021
SISCOMEX_DI_BRL = 115.67
# (faixa_ate_adicao_inclusive, valor_por_adicao_nessa_faixa)
# Faixas oficiais: até 2ª; 3ª–5ª; 6ª–10ª; 11ª–20ª; 21ª–50ª; a partir da 51ª
_FAIXAS_ADICAO: tuple[tuple[int, float], ...] = (
    (2, 38.56),
    (5, 30.85),
    (10, 23.14),
    (20, 15.42),
    (50, 7.71),
    (10**9, 3.86),
)

# Legado (pré-jun/2021) — só para auditoria / comparação
SISCOMEX_LEGADO_DI_1_ADICAO_BRL = 214.50


def _valor_adicao(numero_adicao: int) -> float:
    """Valor da n-ésima adição (1-based) segundo a tabela da IN RFB 2.024/2021."""
    if numero_adicao < 1:
        return 0.0
    for ate, valor in _FAIXAS_ADICAO:
        if numero_adicao <= ate:
            return float(valor)
    return 3.86


def calcular_taxa_siscomex(
    *,
    adicoes: int = 1,
    di_brl: float | None = None,
) -> dict[str, Any]:
    """
    Calcula a Taxa de Utilização do Siscomex para uma DI/DUIMP.

    :param adicoes: quantidade de adições de mercadoria (mín. 1 em DI típica)
    :param di_brl: override do valor fixo por DI (default Portaria ME 4.131/2021)
    """
    n = max(0, int(adicoes or 0))
    base = float(di_brl) if di_brl is not None else SISCOMEX_DI_BRL
    detalhe: list[dict[str, Any]] = []
    total_adicoes = 0.0
    for i in range(1, n + 1):
        v = _valor_adicao(i)
        total_adicoes += v
        detalhe.append({"adicao": i, "brl": round(v, 2)})

    total = round(base + total_adicoes, 2) if n > 0 else round(base, 2)
    # Se n==0 (edge), ainda cobra o registro da DI
    if n == 0:
        total = round(base, 2)

    return {
        "ok": True,
        "adicoes": n,
        "di_brl": round(base, 2),
        "adicoes_brl": round(total_adicoes, 2),
        "total_brl": total,
        "detalhe_adicoes": detalhe,
        "formula": "DI + soma(adições por faixa IN RFB 2.024/2021)",
        "referencia": {
            "lei": "Lei 9.716/1998 art. 3º",
            "ra": "Decreto 6.759/2009 art. 306",
            "portaria": "Portaria ME nº 4.131/2021",
            "in_rfb": "IN RFB nº 2.024/2021",
            "vigencia": "desde 01/06/2021",
        },
        "aviso": (
            "Taxa fixa por registro de DI/DUIMP + adições; não proporcional ao FOB. "
            "Entra na base do ICMS de importação. Confirme nº de adições com o despachante."
        ),
        "legado_nao_usar_brl": SISCOMEX_LEGADO_DI_1_ADICAO_BRL,
    }


def taxa_siscomex_brl(*, adicoes: int = 1) -> float:
    """Atalho: só o total em R$."""
    return float(calcular_taxa_siscomex(adicoes=adicoes)["total_brl"])
