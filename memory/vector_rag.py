"""Colecciones vectoriales persistentes; Chroma usa el proveedor CPU por defecto."""
from __future__ import annotations

from config.settings import CHROMA_PATH, DATA_DIR


class VectorMemory:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        import chromadb

        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.personal = self.client.get_or_create_collection("memoria_personal")
        self.documents = self.client.get_or_create_collection("documentos_codigo")

    def remember(self, dato: str, categoria: str) -> str:
        dato = dato.strip()
        if not dato:
            return "No se guardó un recuerdo vacío."
        import uuid

        self.personal.add(
            ids=[str(uuid.uuid4())], documents=[dato], metadatas=[{"categoria": categoria.strip() or "general"}]
        )
        return "Recuerdo guardado."

    def search(self, query: str, collection: str = "personal", limit: int = 5) -> list[dict]:
        target = self.personal if collection == "personal" else self.documents
        if target.count() == 0:
            return []
        result = target.query(query_texts=[query], n_results=min(limit, target.count()))
        entries = []
        for i, text in enumerate((result.get("documents") or [[]])[0]):
            entries.append({
                "text": text,
                "metadata": ((result.get("metadatas") or [[]])[0] or [{}])[i],
                "distance": ((result.get("distances") or [[]])[0] or [None])[i],
            })
        return entries

    def add_document(self, doc_id: str, text: str, metadata: dict) -> None:
        self.documents.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])
