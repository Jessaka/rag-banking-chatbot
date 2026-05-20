"""
Dense retrieval pomocí Qdrant vektorové databáze.

Používá cosine similaritu nad aktivním embedding backendem (Ollama/OpenAI).
Vhodné pro sémantické dotazy a parafráze.
"""

from __future__ import annotations

import time
from functools import lru_cache
from collections import Counter

from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> QdrantClient:
    return QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)


@lru_cache(maxsize=1)
def _get_embeddings():
    if config.EMBEDDING_BACKEND == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError("EMBEDDING_BACKEND=openai vyžaduje OPENAI_API_KEY")
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise RuntimeError("Chybí langchain-openai. Spusťte: pip install langchain-openai openai") from exc
        return OpenAIEmbeddings(model=config.OPENAI_EMBED_MODEL, api_key=config.OPENAI_API_KEY)

    if config.EMBEDDING_BACKEND != "ollama":
        raise RuntimeError("EMBEDDING_BACKEND musí být 'ollama' nebo 'openai'")
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(model=config.EMBED_MODEL, base_url=config.OLLAMA_BASE_URL)


def _build_filter(metadata_filters: dict | None):
    if not metadata_filters:
        return None
    conditions = []
    for key, value in metadata_filters.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchAny(any=list(value))))
        else:
            conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value)))
    return qmodels.Filter(must=conditions) if conditions else None


def qdrant_pricing_row_debug(limit: int = 12) -> dict:
    """Return pricing_row coverage diagnostics from Qdrant payloads."""
    client = _get_client()
    rows = []
    offset = None
    row_filter = qmodels.Filter(
        must=[qmodels.FieldCondition(key="chunk_type", match=qmodels.MatchValue(value="pricing_row"))]
    )
    while True:
        points, next_offset = client.scroll(
            collection_name=config.QDRANT_COLLECTION,
            scroll_filter=row_filter,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        rows.extend(points)
        if next_offset is None:
            break
        offset = next_offset
    payloads = [dict(point.payload or {}) for point in rows]
    return {
        "pricing_row_count": len(payloads),
        "pricing_row_non_empty": sum(1 for p in payloads if str(p.get("page_content") or "").strip()),
        "top_product_name": Counter(str(p.get("product_name") or "").strip() or "<empty>" for p in payloads).most_common(limit),
        "top_fee_type": Counter(str(p.get("fee_type") or "").strip() or "<empty>" for p in payloads).most_common(limit),
        "sample_rows": [
            {
                "product_name": p.get("product_name"),
                "fee_type": p.get("fee_type"),
                "fee_value": p.get("fee_value"),
                "source_url": p.get("source_url"),
                "page": p.get("page"),
                "content_preview": str(p.get("page_content") or "")[:220],
            }
            for p in payloads[: min(5, limit)]
        ],
    }


def vector_search(query: str, top_k: int = config.VECTOR_TOP_K, metadata_filters: dict | None = None) -> list[Document]:
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
        query_filter=_build_filter(metadata_filters),
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
