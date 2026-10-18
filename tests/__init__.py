"""Pruebas automatizadas del asistente.

Durante las pruebas, los registros de auditoría y de fallos van a una carpeta temporal
para no mezclar acciones de prueba con el historial real del usuario.
"""
import atexit
import shutil
import tempfile
from pathlib import Path

from core import auditoria
from memory import learning_loop

_TMP = Path(tempfile.mkdtemp(prefix="asistente_tests_"))
auditoria.REGISTRO = _TMP / "acciones.jsonl"
learning_loop.FAILURE_LOG = _TMP / "fallos_herramientas.jsonl"
atexit.register(shutil.rmtree, _TMP, True)
