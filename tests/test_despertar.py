"""'Jarvis': reconocer el llamado, sacar la orden, cortar la frase y callarse al interrumpir."""
from __future__ import annotations

import queue
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from voice import despertar, ear_stt, mouth_tts

SR = 16000
VOZ = wavfile.read(Path(__file__).parent / "fixtures" / "voz_prueba.wav")[1].astype(np.float32) / 32767


class LlamadoTests(unittest.TestCase):
    def test_reconoce_el_nombre_al_principio(self) -> None:
        for texto in ("Jarvis.", "Oye Jarvis, abre Spotify.", "Que Jarvis.", "A Jarvis.", "Ejarvis.", "Hey, Yarvis, ¿qué hora es?"):
            with self.subTest(texto=texto):
                self.assertTrue(despertar.menciona_jarvis(texto))
        for texto in ("Mi primo Javier vive en Bogotá", "Voy a regar el jardín", "Hay que revisar el servidor",
                      "Ayer vi una película muy larga donde al final aparecía Jarvis"):
            with self.subTest(texto=texto):
                self.assertFalse(despertar.menciona_jarvis(texto))

    def test_saca_la_orden_que_viene_despues(self) -> None:
        self.assertEqual(despertar.orden_tras_el_nombre("Oye Jarvis, abre Spotify."), "abre Spotify")
        self.assertEqual(despertar.orden_tras_el_nombre("Jarvis."), "")
        self.assertEqual(despertar.orden_tras_el_nombre("Hey Jarvis, ¿qué hora es?"), "qué hora es")


class FraseDelMicrofonoTests(unittest.TestCase):
    def test_corta_la_frase_al_hacer_una_pausa(self) -> None:
        silencio = np.zeros(SR, dtype=np.float32)
        audio = np.concatenate([silencio, VOZ, silencio, silencio])
        entrada: queue.Queue = queue.Queue()
        for i in range(0, len(audio), despertar.CHUNK):
            entrada.put(audio[i:i + despertar.CHUNK])
        d = despertar.Despertador(lambda orden: None)
        frase = d._esperar_frase(entrada, ear_stt, np)
        self.assertIsNotNone(frase)
        self.assertLess(abs(len(frase) / SR - len(VOZ) / SR), 1.5)   # la voz y poco más

    def test_en_pausa_suelta_el_microfono(self) -> None:
        entrada: queue.Queue = queue.Queue()
        entrada.put(np.zeros(despertar.CHUNK, dtype=np.float32))
        d = despertar.Despertador(lambda orden: None)
        d.pausar(True)
        self.assertIsNone(d._esperar_frase(entrada, ear_stt, np))


class InterrumpirTests(unittest.TestCase):
    def test_al_llamarlo_se_calla_y_descarta_lo_que_faltaba(self) -> None:
        sonadas = []

        def reproducir(path):
            sonadas.append(str(path))
            for _ in range(50):   # "suena" hasta que lo callan
                if mouth_tts.interrumpido():
                    return
                time.sleep(0.01)

        with patch.object(mouth_tts, "_reproducir", side_effect=reproducir), patch.object(mouth_tts.shutil, "rmtree"):
            hablante = mouth_tts.SentenceSpeaker(sintetizar=lambda t: Path(t))
            hablante.feed("Uno. Dos. Tres. Cuatro. ")
            threading.Timer(0.15, mouth_tts.detener_habla).start()
            hablante.close()
        self.assertEqual(sonadas, ["Uno."])
        self.assertTrue(mouth_tts.interrumpido())
        mouth_tts.SentenceSpeaker(sintetizar=lambda t: None).close()   # una respuesta nueva vuelve a hablar
        self.assertFalse(mouth_tts.interrumpido())


if __name__ == "__main__":
    unittest.main()
