"""
Reranking pomocí BGE-Reranker-v2-m3 (cross-encoder).

Cross-encoder vyhodnotí každý pár (dotaz, chunk) společně,
čímž dosáhne podstatně přesnější relevance než bi-encoder.
Cena: lineární s počtem kandidátů → proto reranking probíhá
až po hybridním pre-filtru, ne nad celou kolekcí.

Model: BAAI/bge-reranker-v2-m3
  - Vícejazyčný, včetně češtiny
  - Optimalizován pro RAG reranking
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_reranker() -> CrossEncoder:
    """Načte cross-encoder model (singleton)."""
    logger.info(f"Načítám reranker: {config.RERANKER_MODEL}")
    model = CrossEncoder(
        config.RERANKER_MODEL,
        device=config.RERANKER_DEVICE,
        max_length=512,
    )
    logger.info("Reranker připraven")
    return model


def rerank(
    query: str,
    documents: list[Document],
    top_k: int = config.RERANK_TOP_K,
) -> list[Document]:
    """
    Přeřadí dokumenty podle cross-encoder relevance pro daný dotaz.

    Args:
        query:     Uživatelský dotaz.
        documents: Kandidáti z hybridního vyhledávání.
        top_k:     Počet finálních výsledků.

    Returns:
        Top-k Document objektů s metadatem `rerank_score` (sestupně).
    """
    if not documents:
        return []

    model = _load_reranker()

    pairs = [(query, doc.page_content) for doc in documents]
    scores: list[float] = model.predict(pairs).tolist()

    ranked = sorted(
        zip(documents, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    results = []
    for doc, score in ranked[:top_k]:
        enriched = Document(
            page_content=doc.page_content,
            metadata={**doc.metadata, "rerank_score": round(score, 4)},
        )
        results.append(enriched)

    logger.debug(
        f"Rerank: {len(documents)} → {len(results)} "
        f"(top score: {ranked[0][1]:.4f})" if ranked else "Rerank: 0 výsledků"
    )
    return results
