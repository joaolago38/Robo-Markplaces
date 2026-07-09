"""
tests/test_agente_promocoes_manicures.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agentes.social.agente_promocoes_manicures as agente

_CAMPANHA = {
    "id": "kit-3-mimo-manicure",
    "ativo": True,
    "prioridade": 1,
    "sku": "IMP-MIMO-003",
    "template": "{produto} {preco}",
}
_MONTADO = {
    "ok": True,
    "campanha_id": "kit-3-mimo-manicure",
    "campanha_nome": "Kit 3",
    "sku": "IMP-MIMO-003",
    "texto": "Kit R$ 44,90",
    "texto_telegram": "Kit R$ 44,90",
    "texto_whatsapp": "Kit R$ 44,90",
    "link_ml": "https://produto.mercadolivre.com.br/MLB123",
}


class AgentePromocoesManicuresTests(unittest.TestCase):
    @patch.object(agente, "pode_divulgar_promocoes_manicures", return_value=(False, "promocoes_desativadas"))
    def test_bloqueia_sem_prontidao(self, *_):
        out = agente.executar(enviar=False)
        self.assertFalse(out["ok"])
        self.assertEqual(out["motivo"], "promocoes_desativadas")

    @patch.object(agente, "escrever_json_atomico")
    @patch.object(agente, "montar_mensagem_campanha", return_value=_MONTADO)
    @patch.object(agente, "carregar_campanhas", return_value=[_CAMPANHA])
    @patch.object(agente, "pode_divulgar_promocoes_manicures", return_value=(True, "ok"))
    def test_dry_run_monta_sem_enviar(self, *_mocks):
        out = agente.executar(enviar=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["campanha_id"], "kit-3-mimo-manicure")
        self.assertFalse(out.get("enviado"))

    @patch.object(agente, "PROMOCOES_MANICURES_INTERVALO_SEG", 43200)
    @patch.object(
        agente,
        "_carregar_historico",
        return_value={
            "ultimo_envio_em": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    )
    @patch.object(agente, "carregar_campanhas", return_value=[_CAMPANHA])
    @patch.object(agente, "pode_divulgar_promocoes_manicures", return_value=(True, "ok"))
    def test_respeita_intervalo_minimo(self, *_mocks):
        out = agente.executar(enviar=True)
        self.assertTrue(out.get("adiado"))
        self.assertFalse(out.get("enviado"))

    @patch.object(agente, "escrever_json_atomico")
    @patch.object(agente, "incrementar")
    @patch.object(agente, "enviar_telegram_manicures", return_value=True)
    @patch.object(agente, "enviar_grupo_manicures", return_value=True)
    @patch.object(agente, "whatsapp_grupo_manicures_configurado", return_value=True)
    @patch.object(agente, "_carregar_historico", return_value={})
    @patch.object(agente, "montar_mensagem_campanha", return_value=_MONTADO)
    @patch.object(agente, "carregar_campanhas", return_value=[_CAMPANHA])
    @patch.object(agente, "pode_divulgar_promocoes_manicures", return_value=(True, "ok"))
    def test_envia_wa_e_telegram(self, *_mocks):
        out = agente.executar(enviar=True)
        self.assertTrue(out["ok"])
        self.assertTrue(out["enviado"])
        self.assertTrue(out["whatsapp"])
        self.assertTrue(out["telegram"])


if __name__ == "__main__":
    unittest.main()
