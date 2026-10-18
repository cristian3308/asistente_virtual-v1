"""Reconocimiento de voz en español: detección de voz con Silero y Faster-Whisper en CPU (int8)."""
from __future__ import annotations

import queue
import re
import threading
import time
from pathlib import Path

from config import settings
from core import estado

SAMPLE_RATE = 16000
CHUNK = 512                 # 32 ms: el tamaño que espera Silero VAD
VENTANA_VAD = 32 * CHUNK    # ~1 s de contexto para cada decisión
UMBRAL_VOZ = 0.5
MARGEN = int(0.4 * SAMPLE_RATE)  # se conserva antes y después de la voz para no cortar sílabas

# Frases que Whisper inventa con silencio o ruido (aprendidas de subtítulos de internet).
# No incluye "gracias" a secas: es algo que el usuario sí puede decir.
_ALUCINACIONES = {
    "gracias por ver el video", "gracias por ver", "subtitulos realizados por la comunidad de amaraorg",
    "subtitulado por la comunidad de amaraorg", "suscribete al canal",
}

_model = None
_vad = None
_model_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8",
                                  cpu_threads=settings.WHISPER_THREADS)
        return _model


def precargar() -> None:
    """Carga Whisper en segundo plano para que la primera transcripción no espere ~2 s."""
    threading.Thread(target=_whisper, name="stt-precarga", daemon=True).start()


def _detector():
    global _vad
    if _vad is None:
        from faster_whisper.vad import get_vad_model
        _vad = get_vad_model()
    return _vad


def _es_voz(ventana) -> bool:
    """¿Hay voz en los últimos ~100 ms? Silero distingue voz de ventiladores, teclado o música."""
    probabilidades = _detector()(ventana)
    return float(max(probabilidades[-3:])) > UMBRAL_VOZ


def _limpiar_transcripcion(texto: str) -> str:
    import unicodedata
    clave = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    clave = re.sub(r"[^a-z ]", "", clave).strip()
    return "" if clave in _ALUCINACIONES else texto.strip()


def transcribir_audio(audio) -> str:
    """Transcribe audio mono float32 a 16 kHz."""
    import numpy as np

    if audio.size == 0:
        return ""
    pico = float(np.max(np.abs(audio)))
    if 0 < pico < 0.5:
        # Micrófono bajo: normaliza el volumen (con tope para no amplificar solo ruido).
        audio = audio * min(0.9 / pico, 8.0)
    segmentos, _ = _whisper().transcribe(
        audio.astype(np.float32), language="es", beam_size=1, vad_filter=True,
        initial_prompt=settings.WHISPER_VOCABULARIO, condition_on_previous_text=False,
    )
    return _limpiar_transcripcion(" ".join(segmento.text.strip() for segmento in segmentos))


def recortar_voz(audio, primera: int, ultima: int):
    """Deja solo el tramo con voz más un margen: transcribe antes y evita alucinaciones en silencios."""
    return audio[max(0, primera - MARGEN): min(len(audio), ultima + MARGEN)]


def escuchar(silencio_fin: float | None = None, espera_inicio: float | None = None,
             maximo: float | None = None) -> str:
    """Graba hasta que dejas de hablar `silencio_fin` segundos y devuelve el texto.

    Devuelve "" si no empiezas a hablar en `espera_inicio` segundos.
    """
    import numpy as np
    import sounddevice as sd

    silencio_fin = settings.VOZ_SILENCIO_FIN if silencio_fin is None else silencio_fin
    espera_inicio = settings.VOZ_ESPERA_INICIO if espera_inicio is None else espera_inicio
    maximo = settings.VOZ_MAXIMO if maximo is None else maximo

    entrada: queue.Queue = queue.Queue()

    def callback(indata, frames, time_info, status):
        entrada.put(indata[:, 0].copy())

    audio = np.zeros(0, dtype=np.float32)
    primera = ultima = None
    revisado = 0
    estado.publicar("listening")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=CHUNK, callback=callback):
        while True:
            try:
                audio = np.concatenate([audio, entrada.get(timeout=1.0)])
            except queue.Empty:
                break  # el micrófono dejó de entregar audio
            # Decide cada ~96 ms con la última ventana de ~1 s.
            if len(audio) - revisado < 3 * CHUNK or len(audio) < VENTANA_VAD:
                continue
            revisado = len(audio) - len(audio) % CHUNK
            if _es_voz(audio[revisado - VENTANA_VAD: revisado]):
                primera = revisado - 3 * CHUNK if primera is None else primera
                ultima = revisado
            segundos = len(audio) / SAMPLE_RATE
            if primera is None and segundos >= espera_inicio:
                break
            if primera is not None and ((len(audio) - ultima) / SAMPLE_RATE >= silencio_fin
                                        or (len(audio) - primera) / SAMPLE_RATE >= maximo):
                break
    if primera is None:
        estado.publicar("idle")
        return ""
    estado.publicar("thinking", detalle="Transcribiendo…")
    return transcribir_audio(recortar_voz(audio, primera, ultima))


def transcribir_archivo(path: str | Path) -> str:
    """Transcribe un archivo de audio existente (p. ej. notas de voz de Telegram)."""
    segmentos, _ = _whisper().transcribe(
        str(path), language="es", beam_size=1, vad_filter=True,
        initial_prompt=settings.WHISPER_VOCABULARIO, condition_on_previous_text=False,
    )
    return _limpiar_transcripcion(" ".join(segmento.text.strip() for segmento in segmentos))
