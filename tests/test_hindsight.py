"""Memoria Hindsight: ayuda cuando está, y nunca estorba cuando no (sin servidor real)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.brain import AssistantBrain
from memory import hindsight_memoria as hm


class _Respuesta:
    def __init__(self, datos):
        self._datos = datos

    def raise_for_status(self):
        return None

    def json(self):
        return self._datos


class HindsightTests(unittest.TestCase):
    def tearDown(self) -> None:
        hm._listo.clear()
        while not hm._cola.empty():
            hm._cola.get_nowait()

    def test_sin_servidor_no_hace_nada_ni_falla(self) -> None:
        hm._listo.clear()
        with patch("httpx.post", side_effect=AssertionError("no debe llamar a la red")):
            self.assertEqual(hm.recordar("¿cómo se llama mi perro?"), "")
            hm.guardar_turno("hola", "hola")
        self.assertTrue(hm._cola.empty())

    def test_recordar_devuelve_lineas_limpias(self) -> None:
        hm._listo.set()
        datos = {"results": [{"text": "Cristhian's dog is named Rocky | When: Tuesday | Involving: Rocky"},
                             {"text": ""}]}
        with patch("httpx.post", return_value=_Respuesta(datos)) as post:
            self.assertEqual(hm.recordar("perro"), "- Cristhian's dog is named Rocky | When: Tuesday")
        self.assertTrue(post.call_args.args[0].endswith("/memories/recall"))

    def test_recordar_lento_o_caido_no_bloquea(self) -> None:
        hm._listo.set()
        with patch("httpx.post", side_effect=TimeoutError()):
            self.assertEqual(hm.recordar("perro"), "")

    def test_guardar_turno_va_a_la_cola_con_hora_local(self) -> None:
        hm._listo.set()
        with patch.object(hm, "_arrancar_trabajador"):
            hm.guardar_turno("Mi perro se llama Rocky", "Lo recordaré", "telegram")
        item = hm._cola.get_nowait()
        self.assertIn("Mi perro se llama Rocky", item["content"])
        self.assertEqual(item["context"], "conversación por telegram")
        self.assertRegex(item["timestamp"], r"[+-]\d\d:\d\d$")   # con zona horaria: fecha correcta

    def test_el_cerebro_usa_y_alimenta_la_memoria(self) -> None:
        vistos = []

        def stream(prompt, prefer_cloud=False, messages=None, **_k):
            vistos.append(messages)
            chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Se llama Rocky.", tool_calls=None))])
            yield chunk, SimpleNamespace(name="Local", model="l", is_local=True)

        brain = AssistantBrain.__new__(AssistantBrain)
        brain.router = SimpleNamespace(stream=stream, cloud_model="c")
        brain.memory = MagicMock()
        brain.system_prompt = "reglas"
        brain.history = [{"role": "system", "content": "reglas"}]
        with patch.object(hm, "recordar", return_value="- Cristhian's dog is named Rocky"), \
             patch.object(hm, "guardar_turno") as guardar:
            brain.ask("¿qué juguete le gusta a mi perro?")
        self.assertIn("MEMORIA DE LARGO PLAZO", vistos[0][0]["content"])
        guardar.assert_called_once()
        self.assertEqual(guardar.call_args.args[:2], ("¿qué juguete le gusta a mi perro?", "Se llama Rocky."))


if __name__ == "__main__":
    unittest.main()
