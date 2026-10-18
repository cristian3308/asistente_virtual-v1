"""Pruebas del motor de tareas persistente y los recordatorios."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import auditoria, tareas


class CerebroFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.preguntas = []
        self.confirmaciones_permitidas = []

    def ask(self, prompt):
        from core.self_coder import confirmation_allowed
        self.preguntas.append(prompt)
        self.confirmaciones_permitidas.append(confirmation_allowed())
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta, "Local · prueba"


class TareasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tareas_"))
        self.db = patch.object(tareas, "DB_PATH", self.tmp / "tareas.db")
        self.db.start()
        self.avisos = []
        auditoria.reanudar()

    def tearDown(self) -> None:
        auditoria.reanudar()
        self.db.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _motor(self, respuestas=()):
        cerebro = CerebroFalso(respuestas)
        return tareas.MotorTareas(crear_cerebro=lambda: cerebro, notificar=self.avisos.append), cerebro

    def test_recordatorio_solo_avisa_cuando_toca(self) -> None:
        futuro = tareas.crear("recordatorio", "sacar la ropa", cuando=datetime.now() + timedelta(hours=1))
        ya = tareas.crear("recordatorio", "tomar agua", cuando=datetime.now() - timedelta(seconds=1))
        motor, _ = self._motor()
        self.assertTrue(motor.procesar_una())
        self.assertFalse(motor.procesar_una())
        self.assertEqual(self.avisos, ["⏰ Recordatorio: tomar agua"])
        self.assertEqual(tareas.obtener(ya)["estado"], "completada")
        self.assertEqual(tareas.obtener(futuro)["estado"], "pendiente")

    def test_agente_resuelve_y_avisa_sin_poder_aprobar_acciones(self) -> None:
        id_tarea = tareas.crear("agente", "investiga el precio del dólar")
        motor, cerebro = self._motor(["El dólar está a 4.000 COP."])
        motor.procesar_una()
        tarea = tareas.obtener(id_tarea)
        self.assertEqual(tarea["estado"], "completada")
        self.assertIn("4.000 COP", tarea["resultado"])
        self.assertIn("✅", self.avisos[0])
        self.assertEqual(cerebro.confirmaciones_permitidas, [False])

    def test_reintenta_con_espera_y_luego_falla(self) -> None:
        id_tarea = tareas.crear("agente", "algo difícil", max_intentos=2)
        motor, _ = self._motor([RuntimeError("sin red"), RuntimeError("sin red")])
        motor.procesar_una()
        tarea = tareas.obtener(id_tarea)
        self.assertEqual((tarea["estado"], tarea["intentos"]), ("pendiente", 1))
        self.assertGreater(tarea["programada_para"], datetime.now().isoformat())
        self.assertFalse(motor.procesar_una())  # todavía no toca el reintento
        with patch.object(tareas, "_ahora", return_value=datetime.now() + timedelta(minutes=5)):
            motor.procesar_una()
        tarea = tareas.obtener(id_tarea)
        self.assertEqual(tarea["estado"], "fallida")
        self.assertIn("❌", self.avisos[-1])

    def test_se_reanuda_tras_reinicio(self) -> None:
        id_tarea = tareas.crear("agente", "tarea larga")
        tareas._actualizar(id_tarea, "inicio", estado="ejecutando")   # el PC se apagó aquí
        motor, _ = self._motor(["Hecho tras reiniciar."])
        with patch("threading.Thread"):
            self.assertEqual(motor.iniciar(), 1)
        self.assertEqual(tareas.obtener(id_tarea)["estado"], "pendiente")
        motor.procesar_una()
        tarea = tareas.obtener(id_tarea)
        self.assertEqual(tarea["estado"], "completada")
        self.assertIn("reanudada tras reinicio", tarea["acciones"])

    def test_cancelar_pausar_y_reactivar(self) -> None:
        id_tarea = tareas.crear("agente", "x")
        self.assertTrue(tareas.pausar(id_tarea))
        motor, _ = self._motor(["no debería ejecutarse"])
        self.assertFalse(motor.procesar_una())
        self.assertTrue(tareas.continuar(id_tarea))
        self.assertTrue(tareas.cancelar(id_tarea))
        self.assertFalse(tareas.cancelar(id_tarea))
        self.assertEqual(tareas.listar(), [])

    def test_parada_de_emergencia_pausa_el_motor(self) -> None:
        tareas.crear("recordatorio", "x", cuando=datetime.now() - timedelta(seconds=1))
        motor, _ = self._motor()
        motor._intervalo = 0.01
        auditoria.detener("prueba")
        with patch.object(motor, "procesar_una") as procesar:
            motor._parar.wait = MagicMock(side_effect=[False, False, True])
            motor._bucle()
        procesar.assert_not_called()

    def test_recordatorio_por_hora_y_por_minutos(self) -> None:
        from tools.clipboard_tasks import programar_recordatorio
        texto = programar_recordatorio("llamar a mamá", hora="23:59")
        self.assertIn("23:59", texto)
        texto = programar_recordatorio("estirar", minutos=10)
        self.assertEqual(len(tareas.listar()), 2)
        self.assertIn("Hora no válida", programar_recordatorio("x", hora="25:99"))


if __name__ == "__main__":
    unittest.main()
