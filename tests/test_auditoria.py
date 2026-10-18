"""Pruebas del registro de auditoría y la parada de emergencia."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import settings
from core import auditoria
from core.brain import AssistantBrain
from tools import registry


def _chunk(texto: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=texto, tool_calls=None))])


def _cerebro(router) -> AssistantBrain:
    brain = AssistantBrain.__new__(AssistantBrain)
    brain.router = router
    brain.memory = MagicMock()
    brain.system_prompt = "reglas"
    brain.history = [{"role": "system", "content": "reglas"}]
    return brain


class AuditoriaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="auditoria_"))
        self.registro = patch.object(auditoria, "REGISTRO", self.tmp / "acciones.jsonl")
        self.registro.start()
        auditoria.reanudar()

    def tearDown(self) -> None:
        auditoria.reanudar()
        self.registro.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cada_herramienta_queda_registrada(self) -> None:
        with patch.dict(registry.FUNCTIONS, {"demo": lambda a: f"hecho {a['x']}"}):
            registry.call_tool("demo", '{"x": 1}')
        accion = auditoria.recientes()[-1]
        self.assertEqual((accion["tipo"], accion["nombre"], accion["ok"]), ("herramienta", "demo", True))
        self.assertIn("hecho 1", accion["resultado"])
        self.assertEqual(accion["origen"], "consola")

    def test_oculta_secretos(self) -> None:
        with patch.object(settings, "API_KEY", "clave-super-secreta-123"):
            auditoria.registrar("herramienta", "x", {"token": "abc", "texto": "usa clave-super-secreta-123",
                                                      "bot": "1234567890:AAHabcdefghijklmnopqrstuvwxyz0123456"})
        linea = (self.tmp / "acciones.jsonl").read_text(encoding="utf-8")
        for secreto in ("clave-super-secreta-123", "AAHabcdefghijklmnopqrstuvwxyz0123456", '"abc"'):
            self.assertNotIn(secreto, linea)

    def test_origen_telegram(self) -> None:
        token = auditoria.origen("telegram")
        try:
            auditoria.registrar("herramienta", "x")
        finally:
            auditoria.restaurar_origen(token)
        self.assertEqual(auditoria.recientes()[-1]["origen"], "telegram")

    def test_parada_bloquea_herramientas(self) -> None:
        ejecutada = MagicMock(return_value="ok")
        auditoria.detener("prueba")
        with patch.dict(registry.FUNCTIONS, {"demo": ejecutada}):
            resultado = registry.call_tool("demo", "{}")
        ejecutada.assert_not_called()
        self.assertIn("parada de emergencia", resultado)
        self.assertFalse(auditoria.recientes()[-1]["ok"])

    def test_parada_no_llama_al_modelo(self) -> None:
        auditoria.detener()
        brain = _cerebro(SimpleNamespace(stream=MagicMock(side_effect=AssertionError("no debe llamar al modelo"))))
        respuesta, motor = brain.ask("hola")
        self.assertEqual(motor, "Detenido")
        self.assertIn("/reanudar", respuesta)

    def test_parar_corta_una_respuesta_a_medias(self) -> None:
        recibidos = []

        def stream(prompt, prefer_cloud=False, **_kwargs):
            for parte in ("Uno. ", "Dos. ", "Tres. ", "Cuatro."):
                yield _chunk(parte), SimpleNamespace(name="Local", model="l", is_local=True)

        def on_token(texto):
            recibidos.append(texto)
            if len(recibidos) == 2:
                auditoria.detener("prueba")

        brain = _cerebro(SimpleNamespace(stream=stream, cloud_model="c"))
        with redirect_stdout(io.StringIO()):
            respuesta, _motor = brain.ask("cuenta", on_token=on_token)
        self.assertEqual(recibidos, ["Uno. ", "Dos. "])
        self.assertTrue(respuesta.startswith("⛔"))

    def test_confirmaciones_quedan_registradas(self) -> None:
        from core import self_coder
        with patch.object(self_coder.Confirm, "ask", return_value=False):
            self_coder.confirmar("¿Autorizas algo?")
        accion = auditoria.recientes()[-1]
        self.assertEqual((accion["tipo"], accion["resultado"], accion["ok"]), ("confirmacion", "rechazada", False))


if __name__ == "__main__":
    unittest.main()
