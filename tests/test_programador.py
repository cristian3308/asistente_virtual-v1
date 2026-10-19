"""Pruebas del agente programador sobre un repositorio git temporal (nunca el proyecto real)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import settings
from core import programador, tareas


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _llamada(n, nombre, **argumentos):
    return SimpleNamespace(id=f"c{n}", function=SimpleNamespace(name=nombre, arguments=json.dumps(argumentos)))


def _respuesta(*llamadas):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=list(llamadas)))])


class ProgramadorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="repo_agente_"))
        (self.repo / "tests").mkdir()
        (self.repo / "core").mkdir()
        (self.repo / "app.py").write_text("def saludo():\n    return 'hola'\n", encoding="utf-8")
        (self.repo / "core" / "auditoria.py").write_text("# protegido\n", encoding="utf-8")
        (self.repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.repo / "tests" / "test_app.py").write_text(
            "import os, unittest\nfrom app import saludo\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_saludo(self):\n        self.assertIn(saludo(), ('hola', 'hola Cristhian'))\n"
            "    def test_sin_secretos(self):\n        self.assertNotIn('OPENCODE_API_KEY', os.environ)\n",
            encoding="utf-8")
        _git("init", "-q", "-b", "master", cwd=self.repo)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "vacío", cwd=self.repo)
        _git("add", "-A", cwd=self.repo)
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "inicial", cwd=self.repo)
        for clave, valor in (("user.name", "t"), ("user.email", "t@t")):
            _git("config", clave, valor, cwd=self.repo)
        self.parches = [patch.object(settings, "ROOT_DIR", self.repo),
                        patch.object(programador, "TALLER", self.repo / "data" / "taller")]
        for p in self.parches:
            p.start()
        (self.repo / ".git" / "info" / "exclude").write_text("data/\n", encoding="utf-8")

    def tearDown(self) -> None:
        for p in self.parches:
            p.stop()
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def _ejecutar(self, guion):
        cliente = MagicMock()
        cliente.chat.completions.create.side_effect = guion
        with patch.dict(os.environ, {"OPENCODE_API_KEY": "secreto-de-prueba"}):
            return programador.ejecutar("t1", "saludar por nombre", cliente=cliente, modelo="m"), cliente

    def test_cambia_en_rama_aislada_prueba_y_no_toca_master(self) -> None:
        hecho, cliente = self._ejecutar([
            _respuesta(_llamada(1, "leer_archivo", ruta="app.py")),
            _respuesta(_llamada(2, "reemplazar_texto", ruta="app.py", buscar="'hola'", reemplazar="'hola Cristhian'")),
            _respuesta(_llamada(3, "escribir_archivo", ruta="core/auditoria.py", contenido="# hackeado\n"),
                       _llamada(4, "leer_archivo", ruta="../../fuera.txt")),
            _respuesta(_llamada(5, "ejecutar_pruebas")),
            _respuesta(_llamada(6, "terminar", resumen="Saludo personalizado; pruebas OK.")),
        ])
        self.assertTrue(hecho["pruebas"].startswith("PRUEBAS OK"), hecho["pruebas"])  # incluye: sin secretos
        self.assertEqual(hecho["archivos"], ["app.py"])
        self.assertIn("'hola'", (self.repo / "app.py").read_text(encoding="utf-8"))           # master intacto
        self.assertEqual((self.repo / "core" / "auditoria.py").read_text(encoding="utf-8"), "# protegido\n")
        respuestas_herramientas = [m["content"] for m in cliente.chat.completions.create.call_args.kwargs["messages"]
                                   if m["role"] == "tool"]
        self.assertTrue(any("Archivo protegido" in r for r in respuestas_herramientas))
        self.assertTrue(any("fuera del proyecto" in r for r in respuestas_herramientas))
        self.assertIn("+    return 'hola Cristhian'", programador.diff("t1"))

    def test_aprobar_aplica_y_deshacer_revierte(self) -> None:
        self._ejecutar([
            _respuesta(_llamada(1, "reemplazar_texto", ruta="app.py", buscar="'hola'", reemplazar="'hola Cristhian'")),
            _respuesta(_llamada(2, "terminar", resumen="ok")),
        ])
        merge = programador.aprobar("t1")
        self.assertIn("hola Cristhian", (self.repo / "app.py").read_text(encoding="utf-8"))
        self.assertFalse(programador.carpeta("t1").exists())
        programador.deshacer(merge)
        self.assertIn("'hola'", (self.repo / "app.py").read_text(encoding="utf-8"))

    def test_conflicto_al_aplicar_deja_el_proyecto_como_estaba(self) -> None:
        self._ejecutar([
            _respuesta(_llamada(1, "reemplazar_texto", ruta="app.py", buscar="'hola'", reemplazar="'hola Cristhian'")),
            _respuesta(_llamada(2, "terminar", resumen="ok")),
        ])
        # Mientras esperaba revisión, la misma línea cambió en master.
        (self.repo / "app.py").write_text("def saludo():\n    return 'buenas'\n", encoding="utf-8")
        _git("commit", "-q", "-am", "cambio en master", cwd=self.repo)
        with self.assertRaises(programador.ConflictoAlAplicar) as error:
            programador.aprobar("t1")
        self.assertIn("app.py", str(error.exception))
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())          # no quedó a medio fusionar
        self.assertEqual(_git("status", "--porcelain", "--untracked-files=no", cwd=self.repo), "")
        self.assertIn("'buenas'", (self.repo / "app.py").read_text(encoding="utf-8"))

    def test_rechazar_borra_rama_y_copia(self) -> None:
        self._ejecutar([
            _respuesta(_llamada(1, "escribir_archivo", ruta="nuevo.py", contenido="x = 1\n")),
            _respuesta(_llamada(2, "terminar", resumen="ok")),
        ])
        programador.rechazar("t1")
        self.assertFalse(programador.carpeta("t1").exists())
        self.assertNotIn("agente/t1", _git("branch", cwd=self.repo))
        self.assertFalse((self.repo / "nuevo.py").exists())

    def test_no_aplica_si_tienes_cambios_sin_guardar(self) -> None:
        self._ejecutar([_respuesta(_llamada(1, "escribir_archivo", ruta="nuevo.py", contenido="x = 1\n")),
                        _respuesta(_llamada(2, "terminar", resumen="ok"))])
        (self.repo / "app.py").write_text("# editado a mano\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            programador.aprobar("t1")

    def test_lectura_paginada_y_sin_relecturas_inutiles(self) -> None:
        grande = "\n".join(f"linea_{i} = {'x' * 60}" for i in range(400))
        (self.repo / "grande.py").write_text(grande, encoding="utf-8")
        taller = programador.Taller(self.repo)
        primera = taller.leer_archivo("grande.py")
        self.assertIn("continúa con leer_archivo", primera)
        self.assertLessEqual(len(primera), programador.LIMITE_RESPUESTA)
        siguiente = int(primera.rsplit("desde=", 1)[1].split(")")[0])
        self.assertIn(f"{siguiente:4}| linea_{siguiente - 1}", taller.leer_archivo("grande.py", desde=siguiente))
        self.assertIn("Ya leíste", taller.leer_archivo("grande.py"))

    def test_presupuesto_agotado_guarda_el_avance_y_luego_continua(self) -> None:
        with patch.object(programador, "MAX_LLAMADAS", 2):
            hecho, _ = self._ejecutar([
                _respuesta(_llamada(1, "escribir_archivo", ruta="nuevo.py", contenido="x = 1\n")),
                _respuesta(_llamada(2, "leer_archivo", ruta="app.py")),
            ])
        self.assertTrue(hecho["incompleto"])
        self.assertEqual(hecho["archivos"], ["nuevo.py"])
        self.assertIn("/reactivar", hecho["resumen"])
        hecho2, cliente = self._ejecutar([
            _respuesta(_llamada(3, "ver_cambios")),
            _respuesta(_llamada(4, "escribir_archivo", ruta="otro.py", contenido="y = 2\n")),
            _respuesta(_llamada(5, "terminar", resumen="Terminado sobre el avance previo.")),
        ])
        primeros = cliente.chat.completions.create.call_args_list[0].kwargs["messages"]
        self.assertTrue(any("trabajo previo" in m["content"] for m in primeros if m["role"] == "user"))
        self.assertFalse(hecho2["incompleto"])
        self.assertEqual(sorted(hecho2["archivos"]), ["nuevo.py", "otro.py"])

    def test_avisa_de_cambios_sensibles(self) -> None:
        texto = "+    if not _authorized(update):\n-    x = 1\n+    subprocess.run(cmd, shell=True)\n+    y = 2\n"
        self.assertEqual(len(programador.avisos_de_seguridad(texto)), 2)


class ProgramaEnMotorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tareas_prog_"))
        self.db = patch.object(tareas, "DB_PATH", self.tmp / "tareas.db")
        self.db.start()

    def tearDown(self) -> None:
        self.db.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sin_aprobacion_no_empieza_y_al_terminar_espera_revision(self) -> None:
        id_tarea = tareas.crear("programa", "añade /hora", max_intentos=1, estado="esperando_autorizacion")
        avisos = []
        motor = tareas.MotorTareas(crear_cerebro=MagicMock(), notificar=avisos.append)
        self.assertFalse(motor.procesar_una())
        self.assertTrue(tareas.autorizar_inicio(id_tarea))
        hecho = {"resumen": "Comando /hora añadido", "pruebas": "PRUEBAS OK\n...", "commit": "abc", "archivos": ["x.py"]}
        with patch.object(programador, "ejecutar", return_value=hecho):
            self.assertTrue(motor.procesar_una())
        tarea = tareas.obtener(id_tarea)
        self.assertEqual(tarea["estado"], "esperando_autorizacion")
        self.assertTrue(tareas.datos(tarea)["pruebas_ok"])
        self.assertIn("/revisar", avisos[-1])
        self.assertFalse(tareas.autorizar_inicio(id_tarea))   # ya hay un resultado: ahora toca /aprobar el diff

    def test_cambio_incompleto_queda_para_continuar(self) -> None:
        id_tarea = tareas.crear("programa", "algo grande", max_intentos=1)
        avisos = []
        motor = tareas.MotorTareas(crear_cerebro=MagicMock(), notificar=avisos.append)
        hecho = {"resumen": "INCOMPLETO…", "pruebas": "PRUEBAS OK", "commit": "abc", "archivos": ["a.py"], "incompleto": True}
        with patch.object(programador, "ejecutar", return_value=hecho):
            motor.procesar_una()
        tarea = tareas.obtener(id_tarea)
        self.assertEqual(tarea["estado"], "fallida")
        self.assertTrue(tareas.datos(tarea)["incompleto"])
        self.assertIn("/reactivar", avisos[-1])
        self.assertTrue(tareas.continuar(id_tarea))
        self.assertEqual(tareas.obtener(id_tarea)["estado"], "pendiente")


if __name__ == "__main__":
    unittest.main()
