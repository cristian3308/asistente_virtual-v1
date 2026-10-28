"""Pruebas del estado observable y del servidor local del avatar."""
from __future__ import annotations

import io
import json
import unittest
import urllib.request
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import estado


def _reset() -> None:
    estado._temporal = None
    estado._habla_hasta = 0.0
    estado._voz_activa = 0
    estado.publicar("idle", motor="local")


class EstadoTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset()

    def test_estado_breve_vuelve_al_anterior(self) -> None:
        estado.publicar("thinking")
        estado.publicar("happy", duracion=60, detalle="¡Listo!")
        self.assertEqual(estado.actual()["estado"], "happy")
        estado._temporal = (estado._temporal[0], 0.0, "")
        self.assertEqual(estado.actual()["estado"], "thinking")

    def test_la_voz_mantiene_la_boca_moviendose_aunque_el_turno_termine(self) -> None:
        estado.voz(True)
        estado.publicar("idle")
        self.assertEqual(estado.actual()["estado"], "speaking")
        estado.voz(False)
        estado._habla_hasta = 0.0
        self.assertEqual(estado.actual()["estado"], "idle")

    def test_se_duerme_tras_inactividad(self) -> None:
        estado._estado["cambio"] -= estado.DORMIR_TRAS + 1
        self.assertEqual(estado.actual()["estado"], "sleeping")

    def test_estado_desconocido_se_ignora(self) -> None:
        estado.publicar("bailando")
        self.assertEqual(estado.actual()["estado"], "idle")


class BocaSincronizadaTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset()

    def test_envolvente_marca_silabas_y_silencios(self) -> None:
        import numpy as np
        from voice.mouth_tts import envolvente
        sr = 16000
        tono = np.sin(np.linspace(0, 2 * np.pi * 220 * 0.2, int(sr * 0.2))) * 20000
        silencio = np.zeros(int(sr * 0.2))
        env = envolvente(np.concatenate([tono, silencio, tono]), sr, frame_ms=20)
        self.assertGreater(max(env[:8]), 0.8)                    # primera sílaba: boca abierta
        self.assertEqual(env[16], 0.0)                           # pausa: boca cerrada
        self.assertGreater(max(env[21:29]), 0.8)                 # segunda sílaba

    def test_volumen_solo_se_envia_mientras_suena(self) -> None:
        estado.boca([0.1, 0.9], 16, 123)
        self.assertNotIn("boca", estado.actual())
        estado.voz(True)
        try:
            self.assertEqual(estado.actual()["boca"]["env"], [0.1, 0.9])
        finally:
            estado.voz(False)

    def test_sintetiza_la_siguiente_frase_mientras_suena_la_actual(self) -> None:
        import threading
        import time
        from pathlib import Path
        from voice import mouth_tts
        eventos, sonando = [], threading.Event()

        def sintetizar(texto):
            time.sleep(0.1)  # la síntesis real tarda ~1 s por frase
            eventos.append(("sintetiza", texto, sonando.is_set()))
            return Path(texto)

        def reproducir(path):
            sonando.set()
            eventos.append(("suena", str(path)))
            time.sleep(0.2)
            sonando.clear()

        with patch.object(mouth_tts, "_sintetizar", side_effect=sintetizar), \
                patch.object(mouth_tts, "_reproducir", side_effect=reproducir), \
                patch.object(mouth_tts.shutil, "rmtree"):
            hablante = mouth_tts.SentenceSpeaker()
            hablante.feed("Hola Cristhian. ¿Cómo estás? Todo bien.")
            hablante.close()
        self.assertEqual([e[1] for e in eventos if e[0] == "suena"], ["Hola Cristhian.", "¿Cómo estás?", "Todo bien."])
        # Las frases siguientes ya están sintetizadas antes de que termine de sonar la primera.
        ultima_sintesis = max(i for i, e in enumerate(eventos) if e[0] == "sintetiza")
        segunda_suena = [i for i, e in enumerate(eventos) if e[0] == "suena"][1]
        self.assertLess(ultima_sintesis, segunda_suena)


class CerebroPublicaEstadosTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset()

    def test_secuencia_pensar_hablar_reposo(self) -> None:
        from core.brain import AssistantBrain

        def stream(prompt, prefer_cloud=False, **_kwargs):
            chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hola", tool_calls=None))])
            yield chunk, SimpleNamespace(name="Local", model="l", is_local=True)

        brain = AssistantBrain.__new__(AssistantBrain)
        brain.router = SimpleNamespace(stream=stream, cloud_model="c")
        brain.memory = MagicMock()
        brain.history = [{"role": "system", "content": "reglas"}]
        vistos = []
        original = estado.publicar
        with patch.object(estado, "publicar", side_effect=lambda e, *a, **k: (vistos.append(e), original(e, *a, **k))), \
                redirect_stdout(io.StringIO()):
            brain.ask("cuéntame algo interesante")
        self.assertEqual(vistos[0], "thinking")
        self.assertIn("speaking", vistos)
        self.assertEqual(vistos[-1], "idle")


class ServidorAvatarTests(unittest.TestCase):
    def test_estado_por_http_solo_en_localhost(self) -> None:
        from interfaces import avatar
        url = avatar._iniciar_servidor()
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        _reset()
        estado.publicar("listening")
        with urllib.request.urlopen(url + "estado", timeout=5) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        self.assertEqual(datos["estado"], "listening")
        self.assertEqual(datos["motor"], "local")


if __name__ == "__main__":
    unittest.main()
