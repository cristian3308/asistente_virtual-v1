"""Memoria vectorial persistente con embeddings multilingües en CPU."""
from __future__ import annotations

from config.settings import CHROMA_PATH, DATA_DIR


def _embedding_function():
    """Usa un modelo multilingüe adecuado para consultas en español."""
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    return SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        device="cpu",
    )


# Chroma guarda la función de embeddings de cada colección y rechaza otra
# distinta, así que el modelo multilingüe usa colecciones propias.
_COLLECTIONS = {
    "personal": ("memoria_personal_ml", "memoria_personal"),
    "documents": ("documentos_codigo_ml", "documentos_codigo"),
}


class VectorMemory:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        import chromadb

        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        embedding_function = _embedding_function()
        for attribute, (name, legacy_name) in _COLLECTIONS.items():
            collection = self.client.get_or_create_collection(name, embedding_function=embedding_function)
            self._migrate_legacy(legacy_name, collection)
            setattr(self, attribute, collection)

    def _migrate_legacy(self, legacy_name: str, target) -> None:
        """Copia una sola vez los textos de la colección antigua, recalculando sus embeddings."""
        if target.count() > 0:
            return
        try:
            legacy = self.client.get_collection(legacy_name)
        except Exception:
            return
        total = legacy.count()
        for offset in range(0, total, 200):
            batch = legacy.get(limit=200, offset=offset, include=["documents", "metadatas"])
            rows = [
                (item_id, document, metadata or {"origen": "migrado"})
                for item_id, document, metadata in zip(batch["ids"], batch["documents"], batch["metadatas"])
                if document
            ]
            if rows:
                ids, documents, metadatas = (list(column) for column in zip(*rows))
                target.upsert(ids=ids, documents=documents, metadatas=metadatas)

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
