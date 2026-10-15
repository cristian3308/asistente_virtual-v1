"""Captura y OCR local de pantalla; todo el procesamiento usa CPU."""
from __future__ import annotations

from pathlib import Path

from config.settings import DATA_DIR


def ver_pantalla_actual(pregunta: str = "") -> str:
    try:
        import mss
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        return f"OCR no instalado: {exc}"
    output = DATA_DIR / "screenshots" / "captura_actual.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with mss.mss() as capture:
            monitor = capture.monitors[1]
            image = capture.grab(monitor)
            Image.frombytes("RGB", image.size, image.rgb).save(output)
        result, _ = RapidOCR()(str(output))
        text = "\n".join(item[1] for item in (result or []))
        if pregunta:
            return f"Captura guardada en {output}. Texto relevante para '{pregunta}':\n{text[:10000]}"
        return f"Captura guardada en {output}. Texto detectado:\n{text[:10000]}"
    except Exception as exc:
        return f"No se pudo capturar/OCR la pantalla: {type(exc).__name__}: {exc}"
