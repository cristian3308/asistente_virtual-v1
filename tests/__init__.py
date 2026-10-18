"""Pruebas automatizadas del asistente.

Durante las pruebas, la auditoría, los fallos, las tareas y el perfil van a una carpeta temporal
para no mezclar acciones de prueba con el historial real del usuario.
"""
import atexit
import shutil
import tempfile
from pathlib import Path

from core import auditoria, tareas
from memory import learning_loop, perfil

_TMP = Path(tempfile.mkdtemp(prefix="asistente_tests_"))
auditoria.REGISTRO = _TMP / "acciones.jsonl"
learning_loop.FAILURE_LOG = _TMP / "fallos_herramientas.jsonl"
tareas.DB_PATH = _TMP / "tareas.db"
perfil.DB_PATH = _TMP / "perfil.db"
atexit.register(shutil.rmtree, _TMP, True)
