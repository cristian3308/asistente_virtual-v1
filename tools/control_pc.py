"""Controlar el PC con la voz: volumen, música, ventanas, bloquear y presionar botones.

Usa funciones propias de Windows (teclas multimedia, MoveWindow, LockWorkStation) y UI
Automation para leer y presionar botones de cualquier programa. Presionar un botón siempre
pide confirmación en la consola; desde Telegram o el celular se rechaza.
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes

VK = {"subir": 0xAF, "bajar": 0xAE, "silencio": 0xAD, "pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1,
      "detener": 0xB2}
_PROPIAS = {"windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "py.exe", "conhost.exe",
            "electron.exe", "claude.exe", "nvidia overlay.exe", "textinputhost.exe"}
_CLICABLES = {"ButtonControl", "MenuItemControl", "HyperlinkControl", "CheckBoxControl", "TabItemControl",
              "ListItemControl", "RadioButtonControl", "SplitButtonControl"}


def _user32():
    return ctypes.windll.user32


def _tecla(vk: int, veces: int = 1) -> None:
    for _ in range(max(1, veces)):
        _user32().keybd_event(vk, 0, 0, 0)
        _user32().keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
        time.sleep(0.01)


def volumen(accion: str = "", nivel: int | None = None) -> str:
    """'subir' / 'bajar' (10 %), 'silencio' (activa o quita) o un nivel de 0 a 100."""
    accion = (accion or "").lower().strip()
    if nivel is None and re.fullmatch(r"\d{1,3}", accion):
        nivel, accion = int(accion), ""
    if nivel is not None:
        nivel = max(0, min(100, int(nivel)))
        _tecla(VK["bajar"], 50)              # cada pulsación son 2 %: primero a 0
        if nivel:
            _tecla(VK["subir"], round(nivel / 2))
        return f"Volumen al {nivel} %."
    if accion in {"silencio", "silenciar", "mute", "quitar silencio"}:
        _tecla(VK["silencio"])
        return "Silencio activado o desactivado."
    if accion in {"subir", "sube", "más", "mas"}:
        _tecla(VK["subir"], 5)
        return "Volumen arriba."
    if accion in {"bajar", "baja", "menos"}:
        _tecla(VK["bajar"], 5)
        return "Volumen abajo."
    return "Dime: subir, bajar, silencio o un nivel de 0 a 100."


def multimedia(accion: str = "pausa") -> str:
    """Controla la música o el video que esté sonando (Spotify, YouTube, cualquier reproductor)."""
    clave = {"pausa": "pausa", "pausar": "pausa", "reproducir": "pausa", "play": "pausa", "continuar": "pausa",
             "siguiente": "siguiente", "adelante": "siguiente", "anterior": "anterior", "atrás": "anterior",
             "atras": "anterior", "detener": "detener", "parar": "detener"}.get((accion or "").lower().strip())
    if not clave:
        return "Dime: pausa, siguiente, anterior o detener."
    _tecla(VK[clave])
    return {"pausa": "Hecho: pausa/reproducir.", "siguiente": "Siguiente canción.", "anterior": "Canción anterior.",
            "detener": "Detenido."}[clave]


def bloquear_pc() -> str:
    _user32().LockWorkStation()
    return "PC bloqueado."


# --- ventanas ----------------------------------------------------------------

def _ventanas() -> list[tuple[int, str, str]]:
    """(hwnd, título, programa) de las ventanas visibles con título."""
    import psutil
    resultado = []
    user32 = _user32()
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visitar(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            largo = user32.GetWindowTextLengthW(hwnd)
            if largo:
                buffer = ctypes.create_unicode_buffer(largo + 1)
                user32.GetWindowTextW(hwnd, buffer, largo + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    programa = psutil.Process(pid.value).name()
                except Exception:
                    programa = ""
                resultado.append((hwnd, buffer.value, programa))
        return True

    user32.EnumWindows(CALLBACK(visitar), 0)
    return resultado


def buscar_ventana(app: str = "") -> tuple[int, str, str] | None:
    """La ventana de `app` (por título o programa); sin app, la última que usaste que no sea la consola."""
    ventanas = _ventanas()
    app = (app or "").lower().strip()
    if app:
        for hwnd, titulo, programa in ventanas:
            if app in titulo.lower() or app in programa.lower().removesuffix(".exe"):
                return hwnd, titulo, programa
        return None
    from tools import system_tools
    for titulo, programa in reversed(getattr(system_tools, "_ventanas_recientes", [])):
        for v in ventanas:
            if v[1] == titulo:
                return v
    return next((v for v in ventanas if v[2].lower() not in _PROPIAS), None)


def organizar_ventana(posicion: str, app: str = "") -> str:
    """izquierda, derecha, maximizar, minimizar o restaurar la ventana de una app."""
    ventana = buscar_ventana(app)
    if ventana is None:
        return f"No encuentro una ventana abierta de {app or 'ningún programa'}."
    hwnd, titulo, _programa = ventana
    user32 = _user32()
    posicion = (posicion or "").lower().strip()
    if posicion in {"maximizar", "maximiza", "grande", "pantalla completa"}:
        user32.ShowWindow(hwnd, 3)
    elif posicion in {"minimizar", "minimiza", "esconder", "ocultar"}:
        user32.ShowWindow(hwnd, 6)
    elif posicion in {"restaurar", "normal"}:
        user32.ShowWindow(hwnd, 9)
    elif posicion in {"izquierda", "derecha"}:
        area = wintypes.RECT()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)   # SPI_GETWORKAREA: sin la barra de tareas
        ancho = (area.right - area.left) // 2
        user32.ShowWindow(hwnd, 9)
        x = area.left if posicion == "izquierda" else area.left + ancho
        user32.MoveWindow(hwnd, x, area.top, ancho, area.bottom - area.top, True)
    else:
        return "Dime: izquierda, derecha, maximizar, minimizar o restaurar."
    return f"Hecho: «{titulo[:50]}» → {posicion}."


# --- botones (UI Automation) -------------------------------------------------

def _controles(ventana, maximo: int = 60, profundidad: int = 12, segundos: float = 3.0) -> list:
    import uiautomation as auto
    encontrados = []
    limite = time.monotonic() + segundos
    for control, _nivel in auto.WalkControl(ventana, maxDepth=profundidad):
        if time.monotonic() > limite or len(encontrados) >= maximo:
            break
        if control.ControlTypeName in _CLICABLES and control.Name and control.IsEnabled:
            encontrados.append(control)
    return encontrados


def ver_botones(app: str = "") -> str:
    """Botones y opciones que se pueden presionar en la ventana de una app."""
    ventana = buscar_ventana(app)
    if ventana is None:
        return f"No encuentro una ventana abierta de {app or 'ningún programa'}."
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            control = auto.ControlFromHandle(ventana[0])
            nombres = list(dict.fromkeys(c.Name.strip() for c in _controles(control) if c.Name.strip()))
    except Exception as exc:
        return f"No pude leer los botones: {exc}"
    if not nombres:
        return f"No encontré botones con nombre en «{ventana[1][:50]}»."
    return f"Botones en «{ventana[1][:50]}»: " + ", ".join(nombres[:40]) + "."


def presionar_boton(nombre: str, app: str = "") -> str:
    """Presiona un botón por su nombre, con confirmación en la consola."""
    from core import auditoria
    from core.self_coder import confirmar, confirmation_allowed

    nombre = (nombre or "").strip()
    if not nombre:
        return "¿Qué botón presiono?"
    ventana = buscar_ventana(app)
    if ventana is None:
        return f"No encuentro una ventana abierta de {app or 'ningún programa'}."
    if not confirmation_allowed():
        return "Presionar botones solo se autoriza desde la consola del PC."
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            controles = _controles(auto.ControlFromHandle(ventana[0]), maximo=300)
            objetivo = next((c for c in controles if c.Name.strip().lower() == nombre.lower()), None) or \
                next((c for c in controles if nombre.lower() in c.Name.lower()), None)
            if objetivo is None:
                return f"No encontré «{nombre}» en «{ventana[1][:50]}». Pregúntame qué botones hay."
            if not confirmar(f"¿Presionar «{objetivo.Name}» en «{ventana[1][:60]}»?"):
                return "No lo presioné."
            patron = objetivo.GetInvokePattern() if hasattr(objetivo, "GetInvokePattern") else None
            if patron is not None:
                patron.Invoke()
            else:
                objetivo.Click(simulateMove=False)
    except Exception as exc:
        return f"No pude presionarlo: {exc}"
    auditoria.registrar("control", "presionar botón", f"{objetivo.Name} en {ventana[1][:60]}")
    return f"Hecho: presioné «{objetivo.Name}»."
