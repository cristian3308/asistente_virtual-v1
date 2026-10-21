"""Siempre atento a "Jarvis": activación por voz, interrupción y tecla rápida.

Cómo funciona (todo en CPU y en el PC):
1. El detector de voz (Silero) escucha de forma continua; gasta muy poco.
2. Cuando dices algo corto, Whisper "base" mira si empieza con "Jarvis" (o "Oye Jarvis").
   Medido 2026-10-21 con 48 frases y ruido: detecta 22/24 y 0 falsas alarmas en 1,3 s.
   (openWakeWord "hey_jarvis" está entrenado en inglés: con "Oye Jarvis" no separaba.)
3. "Jarvis" solo → bip y te escucha. "Jarvis, abre Spotify" de corrido → lo hace directo.
4. Si estaba hablando, se calla al oír "Jarvis" (interrupción).
5. Ctrl+Alt+J hace lo mismo que decir "Jarvis", desde cualquier programa.
"""
from __future__ import annotations

import queue
import re
import threading
import time

from config import settings

SAMPLE_RATE = 16000
CHUNK = 512
VENTANA_VAD = 32 * CHUNK
SILENCIO_FIN_FRASE = 0.7        # s: una pausa así cierra la frase a revisar
MAXIMO_FRASE = 8.0              # s: "Jarvis, ..." con la orden incluida
REVISAR_PRIMEROS = 3.0          # s: el nombre está al principio
PRIMER_TRAMO = 1.3              # s: segunda revisión, donde solo cabe "Jarvis"
_NOMBRE = re.compile(r"\b(?:jarvis|yarvis|harvis|jarbis|charvis|jarvi|j[aá]rvis|yarbis|jervis|garvis|ejarvis)\b",
                     re.IGNORECASE)

_rapido = None
_rapido_lock = threading.Lock()


def _whisper_rapido():
    global _rapido
    with _rapido_lock:
        if _rapido is None:
            from faster_whisper import WhisperModel
            _rapido = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=settings.WHISPER_THREADS)
        return _rapido


def menciona_jarvis(texto: str, primeras_palabras: int = 4) -> bool:
    """¿Lo llamaron? El nombre debe estar entre las primeras palabras ("Oye, Jarvis…", "A Jarvis…")."""
    palabras = re.findall(r"[\wáéíóúñ]+", texto or "", re.IGNORECASE)[:primeras_palabras]
    return bool(_NOMBRE.search(" ".join(palabras)))


def orden_tras_el_nombre(texto: str) -> str:
    """'Oye Jarvis, abre Spotify.' → 'abre Spotify'; '' si solo dijo el nombre."""
    coincide = _NOMBRE.search(texto or "")
    if not coincide:
        return (texto or "").strip()
    return texto[coincide.end():].strip(" ,.;:!¡¿?").strip()


def contiene_nombre(audio) -> bool:
    """Revisa con Whisper base los primeros segundos de una frase."""
    import numpy as np

    def oir(segundos: float) -> str:
        recorte = audio[: int(SAMPLE_RATE * segundos)].astype(np.float32)
        segmentos, _ = _whisper_rapido().transcribe(
            recorte, language="es", beam_size=1, vad_filter=False, hotwords="Jarvis",
            condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text for s in segmentos)

    if menciona_jarvis(oir(REVISAR_PRIMEROS)):
        return True
    # Si la frase sigue de corrido, Whisper a veces se "come" la primera palabra ("Jarvis, ¿cómo…" →
    # "¿Cómo…"). En el primer segundo y pico solo cabe el nombre: se revisa aparte.
    return len(audio) > SAMPLE_RATE * PRIMER_TRAMO and menciona_jarvis(oir(PRIMER_TRAMO))


class Despertador:
    """Hilo que escucha "Jarvis" y llama a `al_llamar(orden)` (orden "" = solo dijo el nombre)."""

    def __init__(self, al_llamar, ocupado=lambda: False) -> None:
        self.al_llamar = al_llamar
        self.ocupado = ocupado          # True mientras se atiende una orden (no se escucha a la vez)
        self._parar = threading.Event()
        self._pausa = threading.Event()
        self._hilo: threading.Thread | None = None
        self._hotkey: threading.Thread | None = None

    # --- ciclo de vida ---
    def iniciar(self) -> str:
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:
            return f"Activación por voz no disponible: {exc}"
        self._parar.clear()
        if self._hilo is None or not self._hilo.is_alive():
            self._hilo = threading.Thread(target=self._bucle, name="despertar", daemon=True)
            self._hilo.start()
        if self._hotkey is None or not self._hotkey.is_alive():
            self._hotkey = threading.Thread(target=self._tecla_rapida, name="tecla-jarvis", daemon=True)
            self._hotkey.start()
        threading.Thread(target=_whisper_rapido, name="despertar-precarga", daemon=True).start()
        return 'Di "Jarvis" (o pulsa Ctrl+Alt+J) para hablarme. /jarvis off para que deje de escuchar.'

    def detener(self) -> None:
        self._parar.set()

    def activo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive() and not self._parar.is_set()

    def pausar(self, pausado: bool) -> None:
        """Mientras se graba una orden con escuchar(), el despertador suelta el micrófono."""
        (self._pausa.set if pausado else self._pausa.clear)()

    # --- escucha continua ---
    def _bucle(self) -> None:
        import numpy as np
        import sounddevice as sd
        from voice import ear_stt

        while not self._parar.is_set():
            if self._pausa.is_set() or self.ocupado() and not self._hablando():
                time.sleep(0.2)
                continue
            entrada: queue.Queue = queue.Queue()
            try:
                with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=CHUNK,
                                    callback=lambda datos, *_: entrada.put(datos[:, 0].copy())):
                    frase = self._esperar_frase(entrada, ear_stt, np)
            except Exception:
                time.sleep(2)     # micrófono ocupado o desconectado: reintenta
                continue
            if frase is None or self._parar.is_set():
                continue
            try:
                if not contiene_nombre(frase):
                    continue
            except Exception:
                continue
            from voice import mouth_tts
            mouth_tts.detener_habla()            # si estaba hablando, se calla
            orden = ""
            if len(frase) > SAMPLE_RATE * 1.6:   # dijo algo más que el nombre: se transcribe completo
                try:
                    orden = orden_tras_el_nombre(ear_stt.transcribir_audio(frase))
                except Exception:
                    orden = ""
            threading.Thread(target=self.al_llamar, args=(orden,), name="jarvis-orden", daemon=True).start()

    def _hablando(self) -> bool:
        from core import estado
        return estado.actual().get("estado") == "speaking"

    def _esperar_frase(self, entrada, ear_stt, np):
        """Junta audio hasta una frase con voz seguida de una pausa corta; None si se pausa o detiene."""
        audio = np.zeros(0, dtype=np.float32)
        primera = ultima = None
        revisado = 0
        while not self._parar.is_set() and not self._pausa.is_set():
            if self.ocupado() and not self._hablando():
                return None
            try:
                audio = np.concatenate([audio, entrada.get(timeout=1.0)])
            except queue.Empty:
                return None
            if len(audio) - revisado < 3 * CHUNK or len(audio) < VENTANA_VAD:
                continue
            revisado = len(audio) - len(audio) % CHUNK
            if ear_stt._es_voz(audio[revisado - VENTANA_VAD: revisado]):
                primera = revisado - 3 * CHUNK if primera is None else primera
                ultima = revisado
            elif primera is None and len(audio) > SAMPLE_RATE * 4:
                audio = audio[-VENTANA_VAD:]     # silencio largo: no acumular memoria
                revisado = len(audio)
            if primera is not None and ((len(audio) - ultima) / SAMPLE_RATE >= SILENCIO_FIN_FRASE
                                        or (len(audio) - primera) / SAMPLE_RATE >= MAXIMO_FRASE):
                return ear_stt.recortar_voz(audio, primera, ultima)
        return None

    # --- tecla rápida Ctrl+Alt+J (RegisterHotKey de Windows, sin librerías) ---
    def _tecla_rapida(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY = 0x1, 0x2, 0x4000, 0x0312
            if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord("J")):
                return   # otra app ya usa esa combinación
            mensaje = wintypes.MSG()
            while not self._parar.is_set() and user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) != 0:
                if mensaje.message == WM_HOTKEY:
                    from voice import mouth_tts
                    mouth_tts.detener_habla()
                    threading.Thread(target=self.al_llamar, args=("",), name="jarvis-tecla", daemon=True).start()
            user32.UnregisterHotKey(None, 1)
        except Exception:
            return
