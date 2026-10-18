"""Acciones de memoria vectorial y lectura/indexación local."""
from __future__ import annotations

import hashlib
from pathlib import Path

from memory.vector_rag import VectorMemory
from config import settings

_vector: VectorMemory | None = None


def get_vector_memory() -> VectorMemory:
    global _vector
    if _vector is None:
        _vector = VectorMemory()
    return _vector


def guardar_recuerdo_importante(dato: str, categoria: str) -> str:
    # También al perfil: así el dato llega en cada respuesta, no solo si se busca.
    from memory import perfil
    perfil.guardar("nota", dato, (categoria or "nota").strip().lower(), fuente="guardado por el asistente", confianza=0.8)
    return get_vector_memory().remember(dato, categoria)


def buscar_en_memoria_profunda(consulta: str) -> str:
    vector = get_vector_memory()
    # Las versiones anteriores guardaban fallos de herramientas como recuerdos.
    personal = [item for item in vector.search(consulta, "personal", 8)
                if item["metadata"].get("categoria") != "autoevolucion"][:5]
    documents = vector.search(consulta, "documents")
    lines = [f"- [Recuerdo · {item['metadata'].get('categoria', 'general')}] {item['text']}" for item in personal]
    lines.extend(
        f"- [Proyecto · {item['metadata'].get('path', 'archivo')}] {item['text']}" for item in documents
    )
    return "\n".join(lines) or "No encontré recuerdos o fragmentos relevantes."


def indexar_proyecto_local(ruta_carpeta: str) -> str:
    root = Path(ruta_carpeta).expanduser().resolve()
    if not settings.path_is_allowed(root):
        return "Indexación bloqueada: la carpeta está fuera de las rutas locales permitidas."
    if not root.is_dir():
        return f"La ruta no es una carpeta: {root}"
    vector = get_vector_memory()
    extensions = {".py", ".md", ".txt", ".json", ".pdf"}
    ignored = {".venv", "venv", ".git", "__pycache__", "node_modules", "chroma_db"}
    indexed = errors = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions or ignored.intersection(path.parts):
            continue
        try:
            if path.suffix.lower() == ".pdf":
                from pypdf import PdfReader
                text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
            chunks = [text[i:i + 800] for i in range(0, len(text), 800) if text[i:i + 800].strip()]
            for n, chunk in enumerate(chunks):
                doc_id = hashlib.sha256(f"{path}:{n}".encode("utf-8")).hexdigest()
                vector.add_document(doc_id, chunk, {"path": str(path), "chunk": n, "extension": path.suffix.lower()})
                indexed += 1
        except Exception:
            errors += 1
    return f"Indexación terminada: {indexed} fragmentos; {errors} archivos con error. Carpeta: {root}"
