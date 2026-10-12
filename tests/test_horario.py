"""
tests/test_horario.py
"""
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.horario import TZ_BRASIL, agora_brasil, formatar_data_hora_br


class HorarioBrasilTests(unittest.TestCase):
    def test_formatar_data_hora_br(self):
        fixo = datetime(2026, 7, 9, 16, 7, 0, tzinfo=TZ_BRASIL)

        def _now(tz=None):
            return fixo

        with patch("core.horario.datetime") as mock_dt:
            mock_dt.now.side_effect = _now
            self.assertEqual(formatar_data_hora_br(), "09/07 16:07")
            agora_brasil()
            mock_dt.now.assert_called_with(TZ_BRASIL)


if __name__ == "__main__":
    unittest.main()
