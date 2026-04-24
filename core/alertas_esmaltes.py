"""
core/alertas_esmaltes.py
Alertas inteligentes específicos para o negócio de esmaltes Impala.
Integrar chamando verificar_todos() dentro de agentes/operacao_24h.py
"""
from __future__ import annotations

import logging
from datetime import datetime

from core.notificador import alertar_gestor

logger = logging.getLogger("alertas_esmaltes")

# Marcos de avaliações com ação recomendada
MARCOS_AVALIACOES: dict[int, str] = {
    20: "Ligar Product Ads R$10/dia — campanha automática no ML",
    50: "Subir preços para Fase 2 nos kits com nota 4.8+",
    100: "Lançar kit 10 atacado — avaliar estratégia de ancoragem",
    230: "MercadoLíder desbloqueado — aumentar budget ads e lançar kit 15",
    575: "MercadoLíder Gold — considerar Loja Oficial (INPI + Minha Página)",
}

# Datas sazonais com dias de antecedência para alerta
DATAS_SAZONAIS: list[tuple[str, str, int]] = [
    ("05-11", "Dia das Mães", 30),
    ("06-12", "Dia dos Namorados", 21),
    ("10-12", "Natal — antecipação", 45),
    ("02-14", "Dia dos Namorados BR", 21),
]

# Limite de frete como % do custo total — acima disso alerta
FRETE_PCT_CRITICO = 0.35


def verificar_marcos_avaliacoes(total_avaliacoes: int) -> str | None:
    """
    Verifica se atingiu marco de avaliações e dispara alerta com ação recomendada.
    Retorna o marco atingido ou None.
    """
    for marco in sorted(MARCOS_AVALIACOES.keys(), reverse=True):
        if total_avaliacoes >= marco:
            acao = MARCOS_AVALIACOES[marco]
            alertar_gestor(
                f"Marco atingido: {total_avaliacoes} avaliações no ML!\n"
                f"Acao recomendada: {acao}"
            )
            logger.info("Marco avaliações atingido: %d — %s", marco, acao)
            return acao
    return None


def verificar_sazonalidade() -> list[str]:
    """
    Verifica se alguma data sazonal está se aproximando e dispara alerta.
    Retorna lista de eventos próximos.
    """
    hoje_str = datetime.now().strftime("%m-%d")
    hoje = datetime.strptime(hoje_str, "%m-%d")
    alertas_disparados = []

    for data_str, evento, dias_antecedencia in DATAS_SAZONAIS:
        try:
            data_evento = datetime.strptime(data_str, "%m-%d")
            diff = (data_evento - hoje).days

            # Ajuste para ano virada (ex: hoje=dez, evento=jan)
            if diff < -180:
                diff += 365
            elif diff > 180:
                diff -= 365

            if 0 < diff <= dias_antecedencia:
                alertar_gestor(
                    f"Sazonalidade: {evento} em {diff} dias!\n"
                    f"Acoes: aumentar estoque kits mimo e Bailarina, "
                    f"lançar campanha ads sazonal, criar bundle presente com Carmed"
                )
                alertas_disparados.append(f"{evento} em {diff} dias")
                logger.info("Alerta sazonal: %s em %d dias", evento, diff)

        except ValueError:
            logger.warning("Data inválida em DATAS_SAZONAIS: %s", data_str)

    return alertas_disparados


def verificar_frete_critico(kits: list[dict]) -> list[dict]:
    """
    Verifica se algum kit tem frete acima do limite crítico (35% do custo total).
    Retorna lista de kits com frete crítico.
    """
    criticos = []
    for kit in kits:
        custo_total = float(kit.get("custo_total", 0))
        frete = float(kit.get("frete_estimado", 0))
        if custo_total > 0 and frete / custo_total > FRETE_PCT_CRITICO:
            pct = frete / custo_total * 100
            criticos.append(
                {
                    "sku": kit.get("sku"),
                    "nome": kit.get("nome"),
                    "frete": frete,
                    "custo_total": custo_total,
                    "frete_pct": round(pct, 1),
                }
            )

    if criticos:
        detalhes = "\n".join(
            f"- {c['sku']}: frete {c['frete_pct']:.0f}% do custo" for c in criticos
        )
        alertar_gestor(
            f"Frete crítico em {len(criticos)} kit(s) — considere ML Full!\n{detalhes}"
        )

    return criticos


def verificar_todos(total_avaliacoes: int = 0, kits: list[dict] | None = None) -> dict:
    """
    Executa todas as verificações de alerta.
    Chamar dentro de agentes/operacao_24h.py.
    """
    marco = verificar_marcos_avaliacoes(total_avaliacoes)
    sazonais = verificar_sazonalidade()
    frete_critico = verificar_frete_critico(kits or [])

    return {
        "marco_avaliacoes": marco,
        "alertas_sazonais": sazonais,
        "kits_frete_critico": frete_critico,
    }
