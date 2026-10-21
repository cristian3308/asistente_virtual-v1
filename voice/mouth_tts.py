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
    # Medición 2026-10-19: con -5 % las JARVIS hablaban a ~2,8 palabras/s (lento); con +8 % quedan
    # en ~3,3, el ritmo de una conversación natural.
    "colombiano": ("es-CO-GonzaloNeural", "+4%", "+0Hz", "Español de Colombia (la de siempre)"),
    "jarvis": ("en-US-AndrewMultilingualNeural", "+8%", "-2Hz",
               "Estilo JARVIS: grave y calmado; habla español con acento inglés"),
    "jarvis_britanico": ("en-GB-RyanNeural", "+12%", "-2Hz",
                         "Británico puro, lo más parecido a 'Brian UK'; ideal si le hablas en inglés"),
    "jarvis_brian": ("en-US-BrianMultilingualNeural", "+12%", "-2Hz", "Otra variante JARVIS multilingüe, algo más cálida"),
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


SILENCIO_MAXIMO_MS = 120   # Edge deja hasta ~1 s mudo al final de cada frase: se recorta a esto


def recortar_silencios(muestras, sample_rate: int, margen_ms: int = SILENCIO_MAXIMO_MS):
    """Quita el silencio sobrante al inicio y al final, para que las frases fluyan sin pausas raras."""
    import numpy as np

    mono = np.abs(muestras.astype(np.float32))
    if mono.ndim == 2:
        mono = mono.max(axis=1)
    if not mono.size or not mono.max():
        return muestras
    voz = np.flatnonzero(mono > 0.02 * mono.max())
    margen = sample_rate * margen_ms // 1000
    return muestras[max(0, voz[0] - margen): voz[-1] + margen]


_interrumpido = threading.Event()


def detener_habla() -> None:
    """Calla al asistente al instante (cuando le dices "Jarvis" mientras habla)."""
    _interrumpido.set()
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.stop()
    except Exception:
        pass


def interrumpido() -> bool:
    return _interrumpido.is_set()


def _reproducir(path: Path) -> None:
    import numpy as np
    import pygame

    propio = not pygame.mixer.get_init()
    if propio:
        pygame.mixer.init()
    try:
        sonido = pygame.mixer.Sound(str(path))
        try:
            muestras = recortar_silencios(pygame.sndarray.array(sonido), pygame.mixer.get_init()[0])
            sonido = pygame.sndarray.make_sound(np.ascontiguousarray(muestras))
            env = envolvente(muestras, pygame.mixer.get_init()[0])
        except Exception:
            env = []
        estado.voz(True)
        try:
            canal = sonido.play()
            estado.boca(env, FRAME_MS, int(time.time() * 1000) + LATENCIA_AUDIO_MS)
            while canal is not None and canal.get_busy():
                if _interrumpido.is_set():
                    canal.stop()
                    break
                pygame.time.wait(20)
        finally:
            estado.voz(False)
    finally:
        if propio:
            pygame.mixer.quit()


def hablar(text: str, voz: str | None = None) -> None:
    _interrumpido.clear()
    path = _sintetizar(text, voz)
    if path is None:
        return
    try:
        _reproducir(path)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)


class SentenceSpeaker:
    """Habla frase a frase mientras el modelo sigue generando.

    Las frases se sintetizan en paralelo (Edge tarda 2–7 s por frase y en paralelo
    tarda lo mismo que una sola) y se reproducen en orden: mientras suena una, las
    siguientes ya se están generando. El primer trozo se corta en la primera coma
    para empezar a hablar cuanto antes.
    """

    SINTESIS_EN_PARALELO = 3
    PRIMER_TROZO_MINIMO = 25   # caracteres antes de poder cortar en una coma

    ESPERA_ANTES_DE_RELLENO = 0.8   # si la primera frase tarda más, dice "Enseguida." para no quedarse callado

    def __init__(self, sintetizar=None, frase_de_espera=None) -> None:
        from concurrent.futures import ThreadPoolExecutor
        import pygame  # noqa: F401  la primera importación tarda ~1 s: mejor ahora que antes de la primera frase

        _interrumpido.clear()   # una respuesta nueva vuelve a hablar aunque antes lo hayas callado
        self._frase_de_espera = frase_de_espera   # función que devuelve la ruta de un audio ya grabado, o None
        self._sintetizar = sintetizar or _sintetizar
        self._pool = ThreadPoolExecutor(self.SINTESIS_EN_PARALELO, thread_name_prefix="tts-sintesis")
        self._audio: queue.Queue = queue.Queue()   # futuros en el orden en que se dicen
        self._buffer = ""
        self._dichas = 0
        self._player = threading.Thread(target=self._play_worker, name="tts-reproduccion", daemon=True)
        self._player.start()

    def _encolar(self, frase: str) -> None:
        if limpiar_texto(frase) and not _interrumpido.is_set():
            self._dichas += 1
            futuro = self._pool.submit(self._sintetizar, frase)
            futuro.frase = limpiar_texto(frase)   # para el subtítulo del avatar
            self._audio.put(futuro)

    def _play_worker(self) -> None:
        import pygame

        try:
            # Abrir la tarjeta de sonido tarda ~1 s: se hace ya, mientras se sintetiza la primera frase.
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            pass
        self._rellenar_si_tarda()
        while True:
            futuro = self._audio.get()
            if futuro is None:
                estado.subtitulo("")
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
                return
            try:
                path = futuro.result()
            except Exception:
                continue
            if path is None:
                continue
            if _interrumpido.is_set():   # lo callaste: lo que quedaba se descarta
                shutil.rmtree(path.parent, ignore_errors=True)
                continue
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                estado.subtitulo(getattr(futuro, "frase", ""))
                self._reproducir(path)
            except Exception:
                pass
            finally:
                shutil.rmtree(path.parent, ignore_errors=True)

    def _rellenar_si_tarda(self) -> None:
        """Si la primera frase no está lista a tiempo, suena una frase de espera ya grabada."""
        if self._frase_de_espera is None or _interrumpido.is_set():
            return
        limite = time.monotonic() + self.ESPERA_ANTES_DE_RELLENO
        try:
            primero = self._audio.get(timeout=self.ESPERA_ANTES_DE_RELLENO)
        except queue.Empty:
            primero = ...
        # Se devuelve a la cabeza de la cola para que el bucle normal lo reproduzca.
        if primero is not ...:
            with self._audio.mutex:
                self._audio.queue.appendleft(primero)
                self._audio.unfinished_tasks += 1
                self._audio.not_empty.notify()
            if primero is None or (primero.done() or self._esperar(primero, limite - time.monotonic())):
                return
        ruta = self._frase_de_espera()
        if ruta is not None:
            try:
                self._reproducir(ruta)   # archivo de la caché: no se borra
            except Exception:
                pass

    @staticmethod
    def _esperar(futuro, segundos: float) -> bool:
        try:
            futuro.result(timeout=max(0.0, segundos))
            return True
        except Exception:
            return futuro.done()

    @staticmethod
    def _reproducir(path: Path) -> None:
        _reproducir(path)

    def feed(self, text: str) -> None:
        self._buffer += text
        if not self._dichas:
            # Primera frase larga: se dice hasta la primera coma y el resto sigue después.
            corte = re.search(r"[,;:]\s", self._buffer[self.PRIMER_TROZO_MINIMO:])
            if corte and not re.search(r"[.!?]\s", self._buffer):
                fin = self.PRIMER_TROZO_MINIMO + corte.end()
                self._encolar(self._buffer[:fin])
                self._buffer = self._buffer[fin:]
        parts = re.split(r"(?<=[.!?])\s+|\n+", self._buffer)
        self._buffer = parts.pop() if parts else ""
        for part in parts:
            self._encolar(part)

    def finish(self) -> None:
        self._encolar(self._buffer)
        self._buffer = ""

    def close(self) -> None:
        self.finish()
        self._audio.put(None)
        # No se vuelve a abrir el micrófono hasta que haya terminado de hablar.
        self._player.join()
        self._pool.shutdown(wait=False)


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
