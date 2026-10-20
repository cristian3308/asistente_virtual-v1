"""Entiende lo que dices aunque Whisper ponga comas, puntos o lo llames por su nombre."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import entender, self_coder
from core.brain import AssistantBrain
from memory import perfil
from tools import registry
from voice import ear_stt


class NormalizarTests(unittest.TestCase):
    def test_quita_el_llamado_y_la_puntuacion_sobrante(self) -> None:
        casos = {
            "Jarvis, abre Chrome.": "Abre Chrome",
            "Oye Jarvis abre chrome": "Abre chrome",
            "Ok Jarvis. Pon música.": "Pon música",
            "Oye, ¿cómo se llama mi mamá?": "¿cómo se llama mi mamá?",
            "¿Qué hora es?": "¿Qué hora es?",
            "Jarvis es un buen nombre": "Jarvis es un buen nombre",   # ahí no lo está llamando
            "Jarvis.": "Jarvis.",                                     # solo el nombre: no queda vacío
        }
        for frase, esperado in casos.items():
            with self.subTest(frase=frase):
                self.assertEqual(entender.normalizar(frase), esperado)
        self.assertEqual(entender.para_comparar("Abre, Chrome."), "Abre Chrome")


class OrdenesConPuntuacionTests(unittest.TestCase):
    def _cerebro(self):
        brain = AssistantBrain.__new__(AssistantBrain)
        brain.router = SimpleNamespace(stream=MagicMock(side_effect=AssertionError("no debe llamar al modelo")))
        brain.memory = MagicMock()
        brain.system_prompt = "reglas"
        brain.history = [{"role": "system", "content": "reglas"}]
        return brain

    def test_abre_aunque_lo_llames_y_haya_comas(self) -> None:
        llamadas = []
        with patch.dict(registry.FUNCTIONS, {"abrir_aplicacion": lambda a: llamadas.append(a) or "Abrí Chrome."}):
            for frase in ("Jarvis, abre Chrome.", "Oye Jarvis abre chrome", "Abre, Chrome."):
                _, motor = self._cerebro().ask(frase)
                self.assertEqual(motor, "Directo · abrir_aplicacion", frase)
        self.assertEqual([a["nombre_aplicacion"].lower() for a in llamadas], ["chrome"] * 3)

    def test_preguntas_de_memoria_con_llamado(self) -> None:
        perfil.aprender_de("Me llamo Cristhian")
        self.assertEqual(self._cerebro().ask("Hola Jarvis, ¿cómo me llamo?"), ("¡Hola! Te llamas Cristhian.", "Memoria"))
        self.assertEqual(self._cerebro().ask("Jarvis, ¿cómo me llamo?")[1], "Memoria")


class RecordatoriosRealesTests(unittest.TestCase):
    def test_recuerdame_y_alarma_usan_el_recordatorio_real(self) -> None:
        for frase in ("Recuérdame a las 10 revisar las habilidades", "Pon una alarma a las seis", "despiértame a las 6"):
            nombres = [t["function"]["name"] for t in registry.obtener_herramientas_relevantes(frase, True)]
            self.assertIn("programar_recordatorio", nombres, frase)

    def test_no_forja_alarmas_falsas_ni_gasta_en_la_nube(self) -> None:
        with patch("core.router.ModelRouter", side_effect=AssertionError("no debe llamar a ningún modelo")):
            resultado = self_coder.forjar_con_pruebas("una alarma que suene a las 10 con un mensaje", "alarma")
        self.assertIn("programar_recordatorio", resultado)


class OidoTests(unittest.TestCase):
    def test_vocabulario_incluye_los_nombres_de_tu_memoria(self) -> None:
        perfil.aprender_de("Mi mamá se llama jacquelin")
        palabras = ear_stt.vocabulario().split()
        self.assertIn("Jarvis", palabras)
        self.assertIn("Jacquelin", palabras)
        opciones = ear_stt._opciones()
        self.assertEqual(opciones["beam_size"], 5)
        self.assertNotIn(",", opciones["hotwords"])   # como lista con comas Whisper imitaba las comas


if __name__ == "__main__":
    unittest.main()
