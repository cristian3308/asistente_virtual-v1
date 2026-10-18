"""Pruebas del oído: detección de voz, corte por silencio y transcripción (micrófono simulado)."""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from voice import ear_stt

SR = ear_stt.SAMPLE_RATE
VOZ = wavfile.read(Path(__file__).parent / "fixtures" / "voz_prueba.wav")[1].astype(np.float32) / 32767


def ruido(segundos: float, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.012, int(SR * segundos)).astype(np.float32)


class MicrofonoFalso:
    """Sustituye a sounddevice.InputStream entregando una señal fija en bloques."""

    def __init__(self, senal: np.ndarray):
        self.senal = senal
        self.entregado = 0
        self._parar = threading.Event()

    def __call__(self, *, callback, blocksize, **_kwargs):
        self.callback, self.blocksize = callback, blocksize
        return self

    def __enter__(self):
        def alimentar():
            while not self._parar.is_set() and self.entregado + self.blocksize <= len(self.senal):
                bloque = self.senal[self.entregado:self.entregado + self.blocksize].reshape(-1, 1)
                self.entregado += self.blocksize
                self.callback(bloque, self.blocksize, None, None)
                self._parar.wait(0.0005)
        self._hilo = threading.Thread(target=alimentar, daemon=True)
        self._hilo.start()
        return self

    def __exit__(self, *_exc):
        self._parar.set()
        self._hilo.join()


class OidoTests(unittest.TestCase):
    def _escuchar(self, senal, **kwargs):
        microfono = MicrofonoFalso(senal)
        with patch("sounddevice.InputStream", microfono):
            texto = ear_stt.escuchar(**kwargs)
        return texto, microfono.entregado / SR

    def test_termina_tras_el_silencio_sin_esperar_al_maximo(self) -> None:
        voz_con_ruido = VOZ + np.random.default_rng(1).normal(0, 0.012, len(VOZ)).astype(np.float32)
        senal = np.concatenate([ruido(1.0), voz_con_ruido, ruido(20.0, 2)])
        texto, escuchado = self._escuchar(senal, silencio_fin=4.0)
        fin_voz = 1.0 + len(VOZ) / SR
        self.assertLess(escuchado, fin_voz + 5.0)       # ~4 s de silencio, no los 20 s de ruido
        self.assertGreater(escuchado, fin_voz + 3.0)
        self.assertIn("spotify", texto.lower())

    def test_silencio_fin_configurable(self) -> None:
        senal = np.concatenate([ruido(1.0), VOZ, ruido(20.0, 3)])
        _texto, escuchado = self._escuchar(senal, silencio_fin=1.0)
        self.assertLess(escuchado, 1.0 + len(VOZ) / SR + 2.0)

    def test_sin_voz_deja_de_esperar(self) -> None:
        texto, escuchado = self._escuchar(ruido(20.0), espera_inicio=3.0)
        self.assertEqual(texto, "")
        self.assertLess(escuchado, 4.5)

    def test_detector_separa_voz_de_ruido(self) -> None:
        ventana = ear_stt.VENTANA_VAD
        self.assertFalse(ear_stt._es_voz(ruido(2.0)[:ventana]))
        self.assertTrue(ear_stt._es_voz(VOZ[SR: SR + ventana]))

    def test_recorte_conserva_margen_y_quita_silencios(self) -> None:
        audio = np.zeros(SR * 10, dtype=np.float32)
        recorte = ear_stt.recortar_voz(audio, 3 * SR, 5 * SR)
        self.assertEqual(len(recorte), 2 * SR + 2 * ear_stt.MARGEN)

    def test_descarta_frases_inventadas_por_whisper(self) -> None:
        self.assertEqual(ear_stt._limpiar_transcripcion("Gracias por ver el video."), "")
        self.assertEqual(ear_stt._limpiar_transcripcion("Gracias"), "Gracias")


if __name__ == "__main__":
    unittest.main()
