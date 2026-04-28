"""ChromaDB vector store for semantic API discovery."""

import json
import os

import chromadb

from backend.shared.config import settings

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_embedding_fn():
    if settings.EMBEDDING_PROVIDER == "gemini":
        from backend.shared.optional_gemini_embeddings import GeminiEmbeddingFunction
        return GeminiEmbeddingFunction(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_EMBEDDING_MODEL,
        )
    return None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        # Persistent storage — survives server restarts
        persist_dir = settings.CHROMA_PERSIST_DIR
        os.makedirs(persist_dir, exist_ok=True)
        _client = chromadb.PersistentClient(path=persist_dir)
    return _client


def get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = get_client()
        embedding_fn = _get_embedding_fn()
        collection_name = f"api_endpoints_{settings.EMBEDDING_PROVIDER}"
        kwargs = {"name": collection_name, "metadata": {"hnsw:space": "cosine"}}
        if embedding_fn is not None:
            kwargs["embedding_function"] = embedding_fn
        _collection = client.get_or_create_collection(**kwargs)
    return _collection


async def init_vector_store():
    """Index all OpenAPI specs on startup."""
    from backend.discovery.api_indexer import index_all_specs

    collection = get_collection()
    if collection.count() > 0:
        print(f"[VectorStore] Already indexed {collection.count()} endpoints. Skipping.")
        return

    specs_dir = settings.SPECS_DIR
    if not os.path.exists(specs_dir):
        print(f"[VectorStore] Specs directory not found: {specs_dir}")
        return

    count = await index_all_specs(specs_dir, collection)
    print(f"[VectorStore] Indexed {count} API endpoints from {specs_dir}")


def similarity_search(query: str, k: int = 5) -> list[dict]:
    """Search for semantically similar API endpoints."""
    collection = get_collection()

    results = collection.query(
        query_texts=[query],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    endpoints = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 1.0
            endpoints.append({
                "document": doc,
                "metadata": meta,
                "confidence": round(1 - distance, 3),  # Convert distance to confidence
            })

    return endpoints
