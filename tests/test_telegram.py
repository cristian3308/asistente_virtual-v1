"""Arranque de Telegram: reintenta si no hay red y no se rinde al primer corte."""
from __future__ import annotations

import io
import logging
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from telegram.error import InvalidToken, TimedOut

from config import settings
from interfaces import telegram_bot


class ArranqueTelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parches = [patch.object(settings, "TELEGRAM_BOT_TOKEN", "123:abc"),
                        patch.object(settings, "TELEGRAM_ALLOWED_USER_ID", "42"),
                        patch.object(telegram_bot.time, "sleep")]
        for p in self.parches:
            p.start()

    def tearDown(self) -> None:
        for p in self.parches:
            p.stop()

    def test_reintenta_tras_un_corte_de_red(self) -> None:
        with patch.object(telegram_bot, "_ejecutar_bot", side_effect=[TimedOut(), TimedOut(), None]) as bot, \
             redirect_stdout(io.StringIO()):
            telegram_bot.run_telegram(brain=None)
        self.assertEqual(bot.call_count, 3)

    def test_token_invalido_no_reintenta(self) -> None:
        with patch.object(telegram_bot, "_ejecutar_bot", side_effect=InvalidToken()) as bot, \
             redirect_stdout(io.StringIO()):
            telegram_bot.run_telegram(brain=None)
        self.assertEqual(bot.call_count, 1)

    def test_corte_de_red_sin_traceback_enorme(self) -> None:
        telegram_bot._sin_trazas_de_red()
        registro = logging.getLogger("telegram.ext").makeRecord(
            "telegram.ext", logging.ERROR, "networkloop.py", 1, "Timed out", (), (TimedOut, TimedOut(), None))
        registro.module = "networkloop"
        logging.getLogger("telegram.ext").filter(registro)
        self.assertIsNone(registro.exc_info)


if __name__ == "__main__":
    unittest.main()
