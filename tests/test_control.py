"""Control del PC y protocolos (sin pulsar teclas reales ni tocar ventanas)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import entender, protocolos, self_coder
from core.brain import AssistantBrain
from tools import control_pc, registry


class ControlTests(unittest.TestCase):
    def test_volumen_a_un_nivel_exacto(self) -> None:
        teclas = []
        with patch.object(control_pc, "_tecla", side_effect=lambda vk, veces=1: teclas.append((vk, veces))):
            self.assertEqual(control_pc.volumen(nivel=30), "Volumen al 30 %.")
            control_pc.volumen("subir")
            control_pc.volumen("silencio")
        self.assertEqual(teclas, [(control_pc.VK["bajar"], 50), (control_pc.VK["subir"], 15),
                                  (control_pc.VK["subir"], 5), (control_pc.VK["silencio"], 1)])

    def test_multimedia(self) -> None:
        teclas = []
        with patch.object(control_pc, "_tecla", side_effect=lambda vk, veces=1: teclas.append(vk)):
            self.assertEqual(control_pc.multimedia("siguiente"), "Siguiente canción.")
            self.assertIn("Dime", control_pc.multimedia("bailar"))
        self.assertEqual(teclas, [control_pc.VK["siguiente"]])

    def test_ventana_que_no_existe(self) -> None:
        with patch.object(control_pc, "buscar_ventana", return_value=None):
            self.assertIn("No encuentro", control_pc.organizar_ventana("izquierda", "programa-inventado"))

    def test_presionar_botones_solo_desde_la_consola(self) -> None:
        with patch.object(control_pc, "buscar_ventana", return_value=(1, "Bloc de notas", "notepad.exe")):
            token = self_coder.confirmation_context(False)
            try:
                self.assertIn("solo se autoriza desde la consola", control_pc.presionar_boton("Guardar"))
            finally:
                self_coder.reset_confirmation_context(token)

    def test_reflejos_sin_modelo(self) -> None:
        brain = AssistantBrain.__new__(AssistantBrain)
        casos = {
            "Jarvis, sube el volumen.": ("volumen", {"accion": "subir"}),
            "pon el volumen al 30": ("volumen", {"nivel": 30}),
            "siguiente canción": ("multimedia", {"accion": "siguiente"}),
            "bloquea el PC": ("bloquear_pc", {}),
            "activa protocolo estudio": ("ejecutar_protocolo", {"nombre": "estudio"}),
            "modo descanso": ("ejecutar_protocolo", {"nombre": "descanso"}),
            "activa el wifi": None,                        # no es un protocolo
            "¿qué es la pausa activa?": None,
        }
        for frase, esperado in casos.items():
            with self.subTest(frase=frase):
                self.assertEqual(brain._orden_directa(entender.para_comparar(frase)), esperado)


class ProtocolosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="protocolos_"))
        self.parche = patch.object(protocolos, "ARCHIVO", self.tmp / "protocolos.json")
        self.parche.start()

    def tearDown(self) -> None:
        self.parche.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_solo_herramientas_inofensivas(self) -> None:
        self.assertIsNone(protocolos.validar([{"herramienta": "volumen", "argumentos": {"nivel": 20}}, {"decir": "Listo."}]))
        for peligrosa in ("cerrar_proceso", "presionar_boton", "ejecutar_powershell_seguro", "bloquear_pc"):
            self.assertIn("no está permitida", protocolos.validar([{"herramienta": peligrosa, "argumentos": {}}]))

    def test_ejecuta_los_pasos_en_orden_y_dice_la_frase(self) -> None:
        llamadas = []
        with patch.object(registry, "call_tool", side_effect=lambda n, a: llamadas.append((n, json.loads(a))) or "ok"):
            respuesta = protocolos.ejecutar("Estudio")
        self.assertEqual([n for n, _ in llamadas], ["volumen", "programar_recordatorio"])
        self.assertEqual(llamadas[1][1]["minutos"], 50)
        self.assertTrue(respuesta.startswith("Protocolo estudio activado"))
        self.assertIn("No conozco el protocolo", protocolos.ejecutar("fiesta"))

    def _plan(self, pasos):
        texto = json.dumps({"descripcion": "Gaming", "pasos": pasos})
        respuesta = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])
        router = MagicMock()
        router.return_value.complete.return_value = (respuesta, "Cloud")
        return patch("core.router.ModelRouter", router)

    def test_crear_guarda_solo_si_lo_apruebas(self) -> None:
        pasos = [{"herramienta": "volumen", "argumentos": {"nivel": 70}}, {"decir": "Que gane el mejor, señor."}]
        with self._plan(pasos), patch.object(self_coder.Confirm, "ask", return_value=False):
            self.assertEqual(protocolos.crear("gaming", "sube el volumen para jugar"), "No lo guardé.")
        self.assertIsNone(protocolos.buscar("gaming"))
        with self._plan(pasos), patch.object(self_coder.Confirm, "ask", return_value=True):
            self.assertIn("guardado", protocolos.crear("gaming", "sube el volumen para jugar"))
        self.assertEqual(protocolos.buscar("gaming")[1]["pasos"], pasos)

    def test_crear_rechaza_planes_peligrosos(self) -> None:
        with self._plan([{"herramienta": "cerrar_proceso", "argumentos": {"pid": 4}}]), \
             patch.object(self_coder.Confirm, "ask", side_effect=AssertionError("no debe preguntar")):
            self.assertIn("no es seguro", protocolos.crear("malo", "cierra cosas"))


if __name__ == "__main__":
    unittest.main()
