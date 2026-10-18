"""Motor de tareas persistente: recordatorios y trabajos del agente en segundo plano.

Las tareas viven en `data/tareas.db`, así sobreviven a cerrar el programa o reiniciar el
PC. Un hilo las ejecuta de una en una cuando les toca. Cada cambio de estado se guarda
(punto de recuperación): una tarea que quedó "ejecutando" al cerrarse se reanuda al
volver a abrir. Hay reintentos con espera creciente, límite de intentos y la parada de
emergencia pausa el motor.

Estados: pendiente · ejecutando · pausada · esperando_autorizacion · completada · fallida · cancelada.
Tipos: recordatorio · agente (trabajo con herramientas) · programa (cambio de código con revisión).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta

from config.settings import DATA_DIR
from core import auditoria

DB_PATH = DATA_DIR / "tareas.db"
ACTIVAS = ("pendiente", "ejecutando", "pausada", "esperando_autorizacion")
_lock = threading.Lock()


def _ahora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _conectar() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS tareas (
            id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL,                 -- recordatorio | agente
            objetivo TEXT NOT NULL,
            estado TEXT NOT NULL,
            creada TEXT NOT NULL,
            actualizada TEXT NOT NULL,
            programada_para TEXT,
            intentos INTEGER NOT NULL DEFAULT 0,
            max_intentos INTEGER NOT NULL DEFAULT 3,
            resultado TEXT,
            error TEXT,
            acciones TEXT NOT NULL DEFAULT '[]',
            proximo_paso TEXT,
            origen TEXT NOT NULL DEFAULT 'consola'
        )"""
    )
    if "datos" not in {c[1] for c in db.execute("PRAGMA table_info(tareas)")}:
        db.execute("ALTER TABLE tareas ADD COLUMN datos TEXT NOT NULL DEFAULT '{}'")  # migración
    return db


def crear(tipo: str, objetivo: str, cuando: datetime | None = None, origen: str = "consola",
          max_intentos: int = 3, estado: str = "pendiente") -> str:
    if tipo not in ("recordatorio", "agente", "programa"):
        raise ValueError(f"Tipo de tarea desconocido: {tipo}")
    id_tarea = uuid.uuid4().hex[:8]
    ahora = _ahora().isoformat()
    with _lock, _conectar() as db:
        db.execute(
            "INSERT INTO tareas(id, tipo, objetivo, estado, creada, actualizada, programada_para, max_intentos, "
            "acciones, proximo_paso, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
            (id_tarea, tipo, objetivo.strip(), estado, ahora, ahora, cuando.isoformat() if cuando else None,
             max_intentos, {"recordatorio": "avisar", "agente": "ejecutar el objetivo"}.get(
                 tipo, "empezar cuando lo apruebes: /aprobar " + id_tarea if estado != "pendiente" else "programar"),
             origen),
        )
    auditoria.registrar("tarea", f"crear {tipo}", objetivo, id_tarea)
    return id_tarea


def datos(tarea: dict) -> dict:
    try:
        return json.loads(tarea.get("datos") or "{}")
    except ValueError:
        return {}


def obtener(id_tarea: str) -> dict | None:
    with _conectar() as db:
        fila = db.execute("SELECT * FROM tareas WHERE id=?", (id_tarea,)).fetchone()
    return dict(fila) if fila else None


def listar(incluir_terminadas: bool = False, limite: int = 30) -> list[dict]:
    consulta = "SELECT * FROM tareas"
    if not incluir_terminadas:
        consulta += f" WHERE estado IN ({','.join('?' * len(ACTIVAS))})"
    consulta += " ORDER BY COALESCE(programada_para, creada) LIMIT ?"
    with _conectar() as db:
        filas = db.execute(consulta, (*ACTIVAS, limite) if not incluir_terminadas else (limite,)).fetchall()
    return [dict(f) for f in filas]


def _actualizar(id_tarea: str, accion: str | None = None, **campos) -> None:
    with _lock, _conectar() as db:
        fila = db.execute("SELECT acciones FROM tareas WHERE id=?", (id_tarea,)).fetchone()
        if fila is None:
            return
        campos["actualizada"] = _ahora().isoformat()
        if accion:
            acciones = json.loads(fila["acciones"] or "[]")
            acciones.append({"fecha": campos["actualizada"], "accion": accion})
            campos["acciones"] = json.dumps(acciones[-50:], ensure_ascii=False)
        columnas = ", ".join(f"{k}=?" for k in campos)
        db.execute(f"UPDATE tareas SET {columnas} WHERE id=?", (*campos.values(), id_tarea))


def _cambiar(id_tarea: str, desde: tuple[str, ...], hacia: str, accion: str) -> bool:
    tarea = obtener(id_tarea)
    if not tarea or tarea["estado"] not in desde:
        return False
    _actualizar(id_tarea, accion, estado=hacia)
    auditoria.registrar("tarea", accion, id_tarea)
    return True


def cancelar(id_tarea: str) -> bool:
    return _cambiar(id_tarea, ACTIVAS, "cancelada", "cancelada por el usuario")


def pausar(id_tarea: str) -> bool:
    return _cambiar(id_tarea, ("pendiente",), "pausada", "pausada por el usuario")


def continuar(id_tarea: str) -> bool:
    return _cambiar(id_tarea, ("pausada", "fallida"), "pendiente", "reanudada por el usuario")


def autorizar_inicio(id_tarea: str) -> bool:
    """Un cambio de código pedido sin confirmación (p. ej. desde Telegram) empieza solo al aprobarlo."""
    tarea = obtener(id_tarea)
    if not tarea or tarea["tipo"] != "programa" or tarea["estado"] != "esperando_autorizacion" or datos(tarea):
        return False
    _actualizar(id_tarea, "inicio aprobado por el usuario", estado="pendiente", proximo_paso="programar")
    auditoria.registrar("tarea", "inicio aprobado", id_tarea)
    return True


def recuperar_tras_reinicio() -> int:
    """Las tareas que quedaron a medias al cerrarse el programa vuelven a la cola."""
    with _lock, _conectar() as db:
        ids = [f["id"] for f in db.execute("SELECT id FROM tareas WHERE estado='ejecutando'").fetchall()]
    for id_tarea in ids:
        _actualizar(id_tarea, "reanudada tras reinicio (punto de recuperación)", estado="pendiente")
    return len(ids)


def _siguiente() -> dict | None:
    ahora = _ahora().isoformat()
    with _conectar() as db:
        fila = db.execute(
            "SELECT * FROM tareas WHERE estado='pendiente' AND (programada_para IS NULL OR programada_para<=?) "
            "ORDER BY COALESCE(programada_para, creada) LIMIT 1", (ahora,)).fetchone()
    return dict(fila) if fila else None


def describir(tarea: dict) -> str:
    cuando = f" · {tarea['programada_para'][11:16]}" if tarea.get("programada_para") else ""
    return f"[{tarea['id']}] {tarea['tipo']} · {tarea['estado']}{cuando} · {tarea['objetivo'][:70]}"


class MotorTareas:
    """Hilo que ejecuta las tareas pendientes de una en una."""

    def __init__(self, crear_cerebro, notificar, intervalo: float = 2.0) -> None:
        self._crear_cerebro = crear_cerebro   # fábrica: el agente de fondo no comparte historial con la consola
        self._notificar = notificar
        self._intervalo = intervalo
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._cerebro = None

    def iniciar(self) -> int:
        recuperadas = recuperar_tras_reinicio()
        self._hilo = threading.Thread(target=self._bucle, name="motor-tareas", daemon=True)
        self._hilo.start()
        return recuperadas

    def detener(self) -> None:
        self._parar.set()

    def _bucle(self) -> None:
        while not self._parar.wait(self._intervalo):
            if auditoria.detenido():
                continue  # la parada de emergencia pausa todo el motor
            try:
                self.procesar_una()
            except Exception:
                continue

    def procesar_una(self) -> bool:
        """Ejecuta la siguiente tarea que toque. Devuelve True si procesó alguna."""
        tarea = _siguiente()
        if tarea is None:
            return False
        _actualizar(tarea["id"], "inicio de ejecución", estado="ejecutando", intentos=tarea["intentos"] + 1)
        token = auditoria.origen(f"tarea:{tarea['id']}")
        try:
            if tarea["tipo"] == "recordatorio":
                self._notificar(f"⏰ Recordatorio: {tarea['objetivo']}")
                _actualizar(tarea["id"], "aviso enviado", estado="completada", resultado="avisado", proximo_paso=None)
                return True
            if tarea["tipo"] == "programa":
                self._ejecutar_programa(tarea)
                return True
            resultado = self._ejecutar_agente(tarea)
            _actualizar(tarea["id"], "objetivo terminado", estado="completada", resultado=resultado, proximo_paso=None)
            self._notificar(f"✅ Tarea {tarea['id']} terminada: {tarea['objetivo'][:80]}\n\n{resultado[:1500]}")
        except Exception as exc:
            intentos = tarea["intentos"] + 1
            error = f"{type(exc).__name__}: {exc}"
            if intentos >= tarea["max_intentos"]:
                _actualizar(tarea["id"], f"falló definitivamente: {error}", estado="fallida", error=error,
                            proximo_paso="revisar el error y reanudar manualmente")
                self._notificar(f"❌ Tarea {tarea['id']} falló tras {intentos} intentos: {error[:300]}")
            else:
                reintento = _ahora() + timedelta(minutes=intentos)  # espera creciente
                _actualizar(tarea["id"], f"intento {intentos} falló: {error}", estado="pendiente", error=error,
                            programada_para=reintento.isoformat(), proximo_paso=f"reintentar a las {reintento:%H:%M}")
        finally:
            auditoria.restaurar_origen(token)
        return True

    def _ejecutar_programa(self, tarea: dict) -> None:
        from core import programador
        hecho = programador.ejecutar(tarea["id"], tarea["objetivo"],
                                     registrar_paso=lambda paso: _actualizar(tarea["id"], paso))
        pruebas_ok = hecho["pruebas"].startswith("PRUEBAS OK")
        if not hecho["commit"]:
            _actualizar(tarea["id"], "el agente no cambió ningún archivo", estado="completada",
                        resultado=hecho["resumen"], proximo_paso=None)
            self._notificar(f"ℹ️ Cambio {tarea['id']}: el agente no modificó nada.\n{hecho['resumen'][:800]}")
            return
        _actualizar(tarea["id"], "cambio listo para revisar", estado="esperando_autorizacion",
                    resultado=f"{hecho['resumen']}\n\n{hecho['pruebas'][:1500]}",
                    datos=json.dumps({"commit": hecho["commit"], "archivos": hecho["archivos"], "pruebas_ok": pruebas_ok}),
                    proximo_paso=f"revisar: /revisar {tarea['id']} · aplicar: /aprobar {tarea['id']} · descartar: /rechazar {tarea['id']}")
        self._notificar(
            f"🛠️ Cambio {tarea['id']} listo para revisar ({'pruebas OK' if pruebas_ok else '⚠ las pruebas FALLAN'}).\n"
            f"Archivos: {', '.join(hecho['archivos'][:8])}\n\n{hecho['resumen'][:800]}\n\n"
            f"Revísalo en la consola con /revisar {tarea['id']}.")

    def _ejecutar_agente(self, tarea: dict) -> str:
        from core.self_coder import confirmation_context, reset_confirmation_context
        if self._cerebro is None:
            self._cerebro = self._crear_cerebro()
        # En segundo plano nadie puede confirmar: las acciones sensibles se rechazan solas.
        token = confirmation_context(False)
        try:
            respuesta, motor = self._cerebro.ask(
                f"Tarea en segundo plano (id {tarea['id']}). Resuélvela con tus herramientas y responde con el "
                f"resultado verificado y lo que quede pendiente. Objetivo: {tarea['objetivo']}")
        finally:
            reset_confirmation_context(token)
        if respuesta.startswith(("Error al consultar", "⛔")):
            raise RuntimeError(respuesta)
        return f"{respuesta}\n\n(motor: {motor})"

