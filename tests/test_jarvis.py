"""Toques de JARVIS: personalidad, frase de espera, sonidos y saludo al volver."""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from config import settings
from core import presencia, tareas
from voice import efectos, mouth_tts


class PersonalidadTests(unittest.TestCase):
    def test_se_presenta_como_jarvis_y_usa_el_trato(self) -> None:
        from core.brain import AssistantBrain
        with patch.object(AssistantBrain, "_precargar_memoria"):
            prompt = AssistantBrain().system_prompt
        self.assertIn("Eres Jarvis", prompt)
        self.assertIn(settings.TRATO, prompt)
        self.assertIn("sin emojis", prompt)


class EfectosTests(unittest.TestCase):
    def test_tonos_suaves_sin_saturar(self) -> None:
        import numpy as np
        onda = efectos._onda(efectos.TONOS["escucha"], 22050)
        self.assertAlmostEqual(len(onda) / 22050, 0.16, places=2)
        self.assertLessEqual(float(np.abs(onda).max()), efectos.VOLUMEN + 1e-6)
        self.assertLess(abs(float(onda[0])), 0.01)      # sin "clic" al empezar

    def test_un_sonido_nunca_rompe_nada(self) -> None:
        with patch("pygame.mixer.get_init", side_effect=RuntimeError("sin tarjeta de sonido")):
            efectos.sonido("escucha")

    def test_frase_de_espera_solo_si_ya_esta_grabada(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="voz_cache_"))
        try:
            with patch.object(efectos, "CACHE", tmp), patch.object(mouth_tts, "voz_actual", return_value="jarvis"):
                self.assertIsNone(efectos.frase_de_espera())
                ruta = efectos._ruta("Enseguida.", "jarvis")
                ruta.parent.mkdir(parents=True)
                ruta.write_bytes(b"mp3")
                self.assertEqual(efectos.frase_de_espera(), ruta)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FraseDeEsperaTests(unittest.TestCase):
    def _hablar(self, demora: float) -> list[str]:
        sonadas = []
        with patch.object(mouth_tts, "_reproducir", side_effect=lambda p: sonadas.append(str(p))), \
             patch.object(mouth_tts.shutil, "rmtree"), patch.object(mouth_tts.SentenceSpeaker, "ESPERA_ANTES_DE_RELLENO", 0.2):
            hablante = mouth_tts.SentenceSpeaker(sintetizar=lambda t: (time.sleep(demora), Path(t))[1],
                                                 frase_de_espera=lambda: Path("Enseguida.mp3"))
            hablante.feed("Hecho, Cristhian. ")
            hablante.close()
        return sonadas

    def test_si_tarda_dice_enseguida_y_luego_responde(self) -> None:
        self.assertEqual(self._hablar(demora=0.6), ["Enseguida.mp3", "Hecho, Cristhian."])

    def test_si_responde_rapido_no_rellena(self) -> None:
        self.assertEqual(self._hablar(demora=0.0), ["Hecho, Cristhian."])


class PresenciaTests(unittest.TestCase):
    def test_saluda_una_vez_al_volver_tras_un_rato(self) -> None:
        mediciones = iter([30, 25 * 60, 26 * 60, 3, 2])
        saludos = []
        vigia = presencia.Presencia(saludos.append, minutos=20, medir=lambda: next(mediciones))
        resultados = [vigia.revisar() for _ in range(5)]
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertIsNotNone(resultados[3])
        self.assertIn("Bienvenido de vuelta", saludos[0])

    def test_no_saluda_si_no_te_fuiste(self) -> None:
        saludos = []
        vigia = presencia.Presencia(saludos.append, minutos=20, medir=lambda: 5)
        for _ in range(3):
            vigia.revisar()
        self.assertEqual(saludos, [])

    def test_resumen_con_lo_que_paso_mientras_no_estabas(self) -> None:
        antes = datetime.now() - timedelta(hours=1)
        id_hecha = tareas.crear("agente", "investigar precios de la RTX 4060 en Colombia", max_intentos=1)
        tareas._actualizar(id_hecha, "listo", estado="completada")
        cuando = (datetime.now() + timedelta(hours=1)).replace(microsecond=0)
        id_rec = tareas.crear("recordatorio", "llamar a mi mamá", cuando=cuando)
        try:
            texto = presencia.resumen_de_regreso(antes)
            self.assertIn("Bienvenido de vuelta", texto)
            self.assertEqual([presencia._saludo_por_hora(h) for h in (9, 15, 22)],
                             ["Buenos días", "Buenas tardes", "Buenas noches"])
            self.assertIn("terminé 1 tarea: investigar precios", texto)
            self.assertIn(f"a las {cuando:%H:%M}: llamar a mi mamá", texto)
        finally:
            tareas.cancelar(id_rec)


if __name__ == "__main__":
    unittest.main()
