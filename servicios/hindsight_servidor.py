"""Servidor de memoria Hindsight (github.com/vectorize-io/hindsight), 100 % local.

Hindsight necesita Python 3.11+ y el asistente usa 3.10, así que corre aparte con su
propio entorno (.venv-hindsight) y el asistente le habla por HTTP en 127.0.0.1.
Usa Ollama como modelo (nada sale del PC) y su base de datos PostgreSQL integrada.
Se cierra solo si el asistente que lo abrió deja de existir.

Uso (lo lanza el asistente): .venv-hindsight\\Scripts\\python.exe servicios/hindsight_servidor.py
    --puerto 8890 --modelo qwen2.5-coder:3b --padre <pid>
"""
import argparse
import os
import sys
import time


def _vive(pid: int) -> bool:
    """¿Sigue abierto el asistente? (Ojo: en Windows os.kill(pid, 0) MATA el proceso; no se usa.)"""
    if pid <= 0:
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    proceso = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not proceso:
        return False
    try:
        codigo = wintypes.DWORD()
        kernel32.GetExitCodeProcess(proceso, ctypes.byref(codigo))
        return codigo.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(proceso)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puerto", type=int, default=8890)
    parser.add_argument("--modelo", default="qwen2.5-coder:3b")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--padre", type=int, default=0)
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from hindsight import HindsightServer

    servidor = HindsightServer(llm_provider="ollama", llm_model=args.modelo, llm_base_url=args.ollama,
                               host="127.0.0.1", port=args.puerto, log_level="warning")
    servidor.start(timeout=900)   # la primera vez descarga modelos y prepara la base de datos
    print(f"HINDSIGHT_LISTO {servidor.url}", flush=True)
    try:
        while _vive(args.padre):
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        servidor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
