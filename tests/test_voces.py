"""Pruebas del selector de voces, las notas de voz de Telegram y el turno compartido."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from voice import mouth_tts

FIXTURE = Path(__file__).parent / "fixtures" / "voz_prueba.wav"


class VocesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="voces_"))
        self.prefs = patch.object(mouth_tts, "_PREFERENCIAS", self.tmp / "preferencias.json")
        self.prefs.start()

    def tearDown(self) -> None:
        self.prefs.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_elegir_y_recordar_voz(self) -> None:
        self.assertEqual(mouth_tts.voz_actual(), "colombiano")
        self.assertIn("jarvis", mouth_tts.elegir_voz("JARVIS"))
        self.assertEqual(mouth_tts.voz_actual(), "jarvis")
        self.assertIn("▶ jarvis", mouth_tts.listar_voces())

    def test_acepta_cualquier_voz_de_edge_y_rechaza_inventadas(self) -> None:
        self.assertIn("es-PE-AlexNeural", mouth_tts.elegir_voz("es-PE-AlexNeural"))
        self.assertIn("No conozco", mouth_tts.elegir_voz("voz-de-ironman"))
        self.assertEqual(mouth_tts.voz_actual(), "es-PE-AlexNeural")

    def test_sintesis_usa_voz_velocidad_y_tono_de_la_elegida(self) -> None:
        mouth_tts.elegir_voz("jarvis")
        comunicador = MagicMock()
        comunicador.return_value.save = MagicMock(side_effect=lambda *_: asyncio.sleep(0))
        with patch("edge_tts.Communicate", comunicador):
            asyncio.run(mouth_tts._speak_async("hola", self.tmp / "x.mp3"))
            asyncio.run(mouth_tts._speak_async("hola", self.tmp / "y.mp3", "mexicano"))
        voz, velocidad, tono = mouth_tts.VOCES["jarvis"][:3]
        self.assertEqual(comunicador.call_args_list[0].kwargs, {"voice": voz, "rate": velocidad, "pitch": tono})
        self.assertEqual(comunicador.call_args_list[1].kwargs["voice"], "es-MX-JorgeNeural")


class NotaDeVozTests(unittest.TestCase):
    def test_convierte_a_ogg_opus_para_telegram(self) -> None:
        import av
        carpeta = Path(tempfile.mkdtemp(prefix="nota_"))
        audio = carpeta / "frase.wav"
        shutil.copy(FIXTURE, audio)
        try:
            with patch.object(mouth_tts, "_sintetizar", return_value=audio):
                ogg = mouth_tts.nota_de_voz("hola")
            with av.open(str(ogg)) as contenedor:
                self.assertEqual(contenedor.streams.audio[0].codec_context.name, "opus")
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)


class TurnoCompartidoTests(unittest.TestCase):
    def test_consola_y_telegram_no_se_mezclan(self) -> None:
        from core.brain import AssistantBrain
        brain = AssistantBrain.__new__(AssistantBrain)
        dentro, maximo = [0], [0]

        def turno_lento(prompt, on_token=None):
            dentro[0] += 1
            maximo[0] = max(maximo[0], dentro[0])
            time.sleep(0.1)
            dentro[0] -= 1
            return prompt, "x"

        with patch.object(AssistantBrain, "_ask", side_effect=turno_lento):
            hilos = [threading.Thread(target=brain.ask, args=(f"m{i}",)) for i in range(4)]
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join()
        self.assertEqual(maximo[0], 1)


if __name__ == "__main__":
    unittest.main()
