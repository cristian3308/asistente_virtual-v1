"""Medición básica de latencia del endpoint local Ollama."""
from __future__ import annotations

import subprocess
import time

from config import settings


def medir_ollama(router, prompt: str = "Responde únicamente: OK") -> dict:
    if not settings.ollama_activo():
        return {"error": "Ollama no está escuchando en el puerto 11434."}
    started = time.perf_counter()
    first = None
    text = []
    chunks = 0
    reported_tokens = None
    try:
        model = settings.LOCAL_TURBO_MODELS.get(getattr(router, "local_model_key", ""), settings.LOCAL_MODEL_ALIASES.get(getattr(router, "local_model_key", ""), settings.MODEL_LOCAL))
        benchmark_prompt = prompt + ("\n/no_think" if model.startswith("qwen3") else "")
        stream = router.local.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": benchmark_prompt}],
            stream=True,
            max_tokens=120,
            stream_options={"include_usage": True},
            extra_body=settings.OLLAMA_EXTRA_BODY,
        )
        for chunk in stream:
            chunks += 1
            usage = getattr(chunk, "usage", None)
            if usage and getattr(usage, "completion_tokens", None) is not None:
                reported_tokens = usage.completion_tokens
            for choice in getattr(chunk, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", None) or getattr(delta, "reasoning_content", None)
                if content:
                    first = first or time.perf_counter()
                    text.append(content)
        elapsed = max(time.perf_counter() - started, 1e-6)
        has_real_ttft = first is not None
        first_elapsed = (first - started) if has_real_ttft else elapsed
        token_count = reported_tokens or max(1, len("".join(text)) // 4)
        generation_elapsed = max(elapsed - first_elapsed, 0.001)
        return {
            "ttft_ms": round(first_elapsed * 1000, 1) if has_real_ttft else None,
            "ttft_real": has_real_ttft,
            "tok_s_total": round(token_count / elapsed, 2),
            "tok_s_generacion": round(token_count / generation_elapsed, 2) if has_real_ttft else None,
            "tokens": token_count,
            "chunks": chunks,
            "ollama_ps": _ollama_ps(),
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as exc:
        return {"error": f"Benchmark falló: {type(exc).__name__}: {exc}", "ollama_ps": _ollama_ps()}


def _ollama_ps() -> str:
    try:
        result = subprocess.run(["ollama", "ps"], shell=False, capture_output=True, text=True, timeout=10)
        return (result.stdout or result.stderr).strip() or "ollama ps sin salida"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"ollama ps no disponible: {exc}"
