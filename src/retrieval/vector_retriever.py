"""
Dense retrieval pomocí Qdrant vektorové databáze.

Používá cosine similaritu nad embeddingy z nomic-embed-text.
Vhodné pro sémantické dotazy a parafráze.
"""

from __future__ import annotations

import time
from functools import lru_cache

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> QdrantClient:
    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)


@lru_cache(maxsize=1)
def _get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBED_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def vector_search(query: str, top_k: int = config.VECTOR_TOP_K) -> list[Document]:
    """
    Sémantické vyhledávání v Qdrant.

    Args:
        query: Uživatelský dotaz.
        top_k: Počet výsledků.

    Returns:
        Seřazený seznam Document objektů (nejlepší první).
    """
    client = _get_client()
    embeddings = _get_embeddings()

    t_embed = time.perf_counter()
    query_vector = embeddings.embed_query(query)
    embed_ms = (time.perf_counter() - t_embed) * 1000

    t_qdrant = time.perf_counter()
    # qdrant-client ≥ 1.14: client.search() nahrazeno client.query_points()
    response = client.query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    qdrant_ms = (time.perf_counter() - t_qdrant) * 1000
    hits = response.points

    results = []
    for hit in hits:
        payload = dict(hit.payload or {})
        page_content = payload.pop("page_content", "")
        doc = Document(
            page_content=page_content,
            metadata={**payload, "vector_score": float(hit.score)},
        )
        results.append(doc)

    logger.info(
        f"⏱ Vector retrieval: embed={embed_ms:.0f}ms, "
        f"qdrant={qdrant_ms:.0f}ms, celkem={embed_ms+qdrant_ms:.0f}ms "
        f"(top score: {hits[0].score:.4f})" if hits else
        f"⏱ Vector retrieval: embed={embed_ms:.0f}ms, qdrant={qdrant_ms:.0f}ms, 0 výsledků"
    )
    return results
