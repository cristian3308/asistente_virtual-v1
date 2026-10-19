"""Pruebas del bot de Telegram."""
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from interfaces.telegram_bot import _authorized, _formatear_hora_local


class TelegramBotTests(unittest.TestCase):
    def test_formatear_hora_local_devuelve_texto_en_español(self) -> None:
        fijo = datetime(2026, 10, 18, 15, 42)
        self.assertEqual(_formatear_hora_local(fijo), "domingo 18/10/2026 15:42")

    def test_formatear_hora_local_domingo_primera_hora(self) -> None:
        fijo = datetime(2024, 1, 7, 0, 1)
        self.assertEqual(_formatear_hora_local(fijo), "domingo 07/01/2024 00:01")

    def test_authorized_rechaza_usuario_no_configurado(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=12345, username="otro"))
        with patch("interfaces.telegram_bot.settings.TELEGRAM_ALLOWED_USER_ID", ""):
            self.assertFalse(_authorized(update))

    def test_authorized_acepta_usuario_correcto(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=12345, username="cristhian"))
        with patch("interfaces.telegram_bot.settings.TELEGRAM_ALLOWED_USER_ID", "12345"):
            self.assertTrue(_authorized(update))

    def test_authorized_rechaza_id_diferente(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=99999, username="intruso"))
        with patch("interfaces.telegram_bot.settings.TELEGRAM_ALLOWED_USER_ID", "12345"):
            self.assertFalse(_authorized(update))


if __name__ == "__main__":
    unittest.main()
