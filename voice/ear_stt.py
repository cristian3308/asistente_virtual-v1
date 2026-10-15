"""Reconocimiento de voz en español usando CPU e int8."""
from __future__ import annotations

import tempfile
import time
import threading
from pathlib import Path

_model = None


def escuchar(max_seconds: int = 5, silence_seconds: float = 0.8) -> str:
    import numpy as np
    import sounddevice as sd
    from scipy.io import wavfile

    sample_rate = 16000
    blocks = []
    silence_samples = 0
    stop_samples = int(silence_seconds * sample_rate)
    started = False
    sample_count = 0
    done = threading.Event()

    def callback(indata, frames, time_info, status):
        nonlocal silence_samples, started, sample_count
        block = indata.copy()
        blocks.append(block)
        sample_count += frames
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0
        if rms > 0.012:
            started = True
            silence_samples = 0
        elif started:
            silence_samples += frames
        if sample_count >= max_seconds * sample_rate or (started and silence_samples >= stop_samples):
            done.set()
            raise sd.CallbackStop

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=callback, blocksize=1024) as stream:
        deadline = time.monotonic() + max_seconds + 0.5
        while stream.active and not done.is_set() and time.monotonic() < deadline:
            sd.sleep(50)
    audio = np.concatenate(blocks, axis=0).reshape(-1) if blocks else np.array([], dtype=np.float32)
    if audio.size == 0:
        return ""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory(prefix="asistente_stt_") as temp_dir:
        wav_path = Path(temp_dir) / "entrada.wav"
        wavfile.write(wav_path, sample_rate, (np.clip(audio, -1, 1) * 32767).astype(np.int16))
        segments, _ = _model.transcribe(str(wav_path), language="es", beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()


def transcribir_archivo(path: str | Path) -> str:
    """Transcribe un archivo de audio existente usando Faster-Whisper en CPU."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(str(path), language="es", beam_size=1, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
