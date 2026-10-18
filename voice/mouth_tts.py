"""Síntesis de voz Edge TTS y reproducción local con pygame, con la boca del avatar sincronizada."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import queue
import threading
import time
from pathlib import Path

from config import settings
from core import estado

FRAME_MS = 16          # ~60 muestras de volumen por segundo: una por fotograma del avatar
LATENCIA_AUDIO_MS = 60  # el búfer de la tarjeta de sonido retrasa un poco lo que se oye


def limpiar_texto(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_~|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Voces de Edge TTS (gratis, sin API key). Las "jarvis" imitan el estilo británico,
# grave y calmado del asistente de Iron Man; no es la voz real de Paul Bettany.
VOCES: dict[str, tuple[str, str, str, str]] = {
    # nombre: (voz de Edge, velocidad, tono, descripción)
    "colombiano": ("es-CO-GonzaloNeural", "+0%", "+0Hz", "Español de Colombia (la de siempre)"),
    "jarvis": ("en-US-AndrewMultilingualNeural", "-5%", "-6Hz",
               "Estilo JARVIS: grave y calmado; habla español con acento inglés"),
    "jarvis_britanico": ("en-GB-RyanNeural", "-5%", "-4Hz",
                         "Británico puro, lo más parecido a 'Brian UK'; ideal si le hablas en inglés"),
    "jarvis_brian": ("en-US-BrianMultilingualNeural", "-5%", "-6Hz", "Otra variante JARVIS multilingüe, algo más cálida"),
    "britanico": ("en-GB-ThomasNeural", "+0%", "+0Hz", "Británico, tono natural"),
    "espanol": ("es-ES-AlvaroNeural", "+0%", "+0Hz", "Español de España"),
    "mexicano": ("es-MX-JorgeNeural", "+0%", "+0Hz", "Español de México"),
    "argentino": ("es-AR-TomasNeural", "+0%", "+0Hz", "Español de Argentina"),
}
VOZ_POR_DEFECTO = "colombiano"
_PREFERENCIAS = settings.DATA_DIR / "preferencias.json"


def voz_actual() -> str:
    try:
        nombre = json.loads(_PREFERENCIAS.read_text(encoding="utf-8")).get("voz", VOZ_POR_DEFECTO)
    except (OSError, ValueError):
        return VOZ_POR_DEFECTO
    return nombre if nombre in VOCES or nombre.endswith("Neural") else VOZ_POR_DEFECTO


def elegir_voz(nombre: str) -> str:
    """Guarda la voz elegida. Acepta un nombre del catálogo o cualquier voz de Edge (p. ej. es-PE-AlexNeural)."""
    nombre = nombre.strip()
    clave = nombre.lower()
    if clave not in VOCES and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", nombre):
        return f"No conozco la voz '{nombre}'. Usa /voces para ver las disponibles."
    elegida = clave if clave in VOCES else nombre
    try:
        datos = json.loads(_PREFERENCIAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    datos["voz"] = elegida
    _PREFERENCIAS.parent.mkdir(parents=True, exist_ok=True)
    _PREFERENCIAS.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Voz cambiada a '{elegida}'."


def listar_voces() -> str:
    actual = voz_actual()
    lineas = [f"{'▶' if nombre == actual else ' '} {nombre:17} {desc}" for nombre, (_, _, _, desc) in VOCES.items()]
    if actual not in VOCES:
        lineas.insert(0, f"▶ {actual} (voz de Edge personalizada)")
    return "\n".join(lineas)


def _parametros_voz(nombre: str | None = None) -> tuple[str, str, str]:
    nombre = nombre or voz_actual()
    if nombre in VOCES:
        return VOCES[nombre][:3]
    return nombre, "+0%", "+0Hz"


async def _speak_async(text: str, output: Path, voz: str | None = None) -> None:
    import edge_tts
    nombre, velocidad, tono = _parametros_voz(voz)
    await edge_tts.Communicate(text, voice=nombre, rate=velocidad, pitch=tono).save(str(output))


def _sintetizar(text: str, voz: str | None = None) -> Path | None:
    """Genera el mp3 de una frase en una carpeta temporal propia; el llamador la borra."""
    clean = limpiar_texto(text)
    if not clean:
        return None
    folder = Path(tempfile.mkdtemp(prefix="asistente_tts_"))
    path = folder / "frase.mp3"
    asyncio.run(_speak_async(clean, path, voz))
    return path


def envolvente(samples, sample_rate: int, frame_ms: int = FRAME_MS) -> list[float]:
    """Volumen 0–1 por fotograma: cada sílaba es un pico, cada pausa un valle."""
    import numpy as np

    mono = samples.astype(np.float32)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    paso = max(1, sample_rate * frame_ms // 1000)
    usable = len(mono) // paso * paso
    if not usable:
        return []
    rms = np.sqrt(np.mean(np.square(mono[:usable].reshape(-1, paso)), axis=1))
    techo = np.percentile(rms, 95) or 1.0
    nivel = np.clip(rms / techo, 0.0, 1.0)
    # Abre rápido y cierra un poco más lento, como una boca real.
    suave, anterior = [], 0.0
    for valor in nivel:
        anterior = valor if valor > anterior else anterior * 0.55 + valor * 0.45
        suave.append(anterior if anterior > 0.08 else 0.0)
    return suave


def _reproducir(path: Path) -> None:
    import pygame

    propio = not pygame.mixer.get_init()
    if propio:
        pygame.mixer.init()
    try:
        sonido = pygame.mixer.Sound(str(path))
        try:
            env = envolvente(pygame.sndarray.array(sonido), pygame.mixer.get_init()[0])
        except Exception:
            env = []
        estado.voz(True)
        try:
            canal = sonido.play()
            estado.boca(env, FRAME_MS, int(time.time() * 1000) + LATENCIA_AUDIO_MS)
            while canal is not None and canal.get_busy():
                pygame.time.wait(20)
        finally:
            estado.voz(False)
    finally:
        if propio:
            pygame.mixer.quit()


def hablar(text: str, voz: str | None = None) -> None:
    path = _sintetizar(text, voz)
    if path is None:
        return
    try:
        _reproducir(path)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


class SentenceSpeaker:
    """Habla frase a frase mientras el modelo sigue generando.

    Un hilo sintetiza y otro reproduce: la siguiente frase ya está lista cuando
    termina la actual, así no hay silencios de ~1 s entre frases.
    """

    def __init__(self) -> None:
        self._sentences: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[Path | None] = queue.Queue(maxsize=3)
        self._buffer = ""
        self._synth = threading.Thread(target=self._synth_worker, name="tts-sintesis", daemon=True)
        self._player = threading.Thread(target=self._play_worker, name="tts-reproduccion", daemon=True)
        self._synth.start()
        self._player.start()

    def _synth_worker(self) -> None:
        while True:
            sentence = self._sentences.get()
            if sentence is None:
                self._audio.put(None)
                return
            try:
                path = _sintetizar(sentence)
            except Exception:
                path = None
            if path is not None:
                self._audio.put(path)

    def _play_worker(self) -> None:
        import pygame

        while True:
            path = self._audio.get()
            if path is None:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
                return
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                _reproducir(path)
            except Exception:
                pass
            finally:
                shutil.rmtree(path.parent, ignore_errors=True)

    def feed(self, text: str) -> None:
        self._buffer += text
        parts = re.split(r"(?<=[.!?])\s+|\n+", self._buffer)
        self._buffer = parts.pop() if parts else ""
        for part in parts:
            if limpiar_texto(part):
                self._sentences.put(part)

    def finish(self) -> None:
        if limpiar_texto(self._buffer):
            self._sentences.put(self._buffer)
        self._buffer = ""

    def close(self) -> None:
        self.finish()
        self._sentences.put(None)
        # No se vuelve a abrir el micrófono hasta que haya terminado de hablar.
        self._player.join()


def nota_de_voz(text: str, max_chars: int = 900) -> Path | None:
    """Genera una nota de voz OGG/Opus (el formato que Telegram muestra como nota de voz).

    El llamador debe borrar la carpeta del archivo devuelto (`path.parent`).
    """
    import av

    mp3 = _sintetizar(text[:max_chars])
    if mp3 is None:
        return None
    ogg = mp3.with_suffix(".ogg")
    with av.open(str(mp3)) as origen, av.open(str(ogg), "w", format="ogg") as destino:
        salida = destino.add_stream("libopus", rate=48000)
        salida.layout = "mono"
        remuestreo = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for frame in origen.decode(audio=0):
            for parte in remuestreo.resample(frame):
                for paquete in salida.encode(parte):
                    destino.mux(paquete)
        for paquete in salida.encode(None):
            destino.mux(paquete)
    return ogg
