"""Ventana flotante del avatar (proceso aparte): `python -m interfaces.avatar_window <url>`.

Transparente: solo se ve el robot y los clics en el hueco pasan a la ventana de detrás.
"""
from __future__ import annotations

import sys

ANCHO, ALTO, MARGEN = 230, 240, 16


def _color_clave_oscuro(window) -> None:
    """pywebview usa rojo puro como color transparente; los bordes suavizados del robot se
    mezclan con él y dejan un halo rojizo. Un casi negro deja el borde imperceptible."""
    try:
        from System import Action
        from System.Drawing import Color

        form = window.native

        def cambiar() -> None:
            clave = Color.FromArgb(255, 1, 2, 3)
            form.BackColor = clave
            form.TransparencyKey = clave

        form.Invoke(Action(cambiar))
    except Exception:
        pass  # Sin el ajuste solo se nota un borde rojizo fino; la ventana sigue funcionando.


def main() -> None:
    import webview

    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
    x = y = None
    try:
        pantalla = webview.screens[0]
        # Esquina inferior derecha, por encima de la barra de tareas.
        x, y = pantalla.width - ANCHO - MARGEN, pantalla.height - ALTO - MARGEN - 48
    except (IndexError, AttributeError):
        pass
    window = webview.create_window(
        "Asistente", url, width=ANCHO, height=ALTO, x=x, y=y,
        on_top=True, frameless=True, easy_drag=True, resizable=False, transparent=True,
    )
    window.events.shown += lambda: _color_clave_oscuro(window)
    webview.start()


if __name__ == "__main__":
    main()
