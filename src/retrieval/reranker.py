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

import time
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
    min_score: float = config.RERANK_MIN_SCORE,
) -> list[Document]:
    """
    Přeřadí dokumenty podle cross-encoder relevance pro daný dotaz.

    Args:
        query:     Uživatelský dotaz.
        documents: Kandidáti z hybridního vyhledávání.
        top_k:     Počet finálních výsledků.
        min_score: Minimální sigmoid skóre pro zachování dokumentu.
                   BGE reranker: relevantní ≈ 0.5–1.0, irelevantní ≈ 0.0.
                   Výchozí hodnota (RERANK_MIN_SCORE=0.01) odfiltruje dokumenty
                   jejichž rerank_score se zaokrouhlí na 0.0000 — ty jsou pro
                   daný dotaz prakticky irelevantní.

    Returns:
        Dokumenty s rerank_score ≥ min_score, seřazené sestupně (max top_k).
        Pokud žádný dokument neprojde prahem, vrátí nejlepší dokument bez ohledu
        na skóre (záruka neprázdného výsledku pro chain.py).
    """
    if not documents:
        return []

    model = _load_reranker()

    pairs = [(query, doc.page_content) for doc in documents]

    t0 = time.perf_counter()
    scores: list[float] = model.predict(pairs).tolist()
    rerank_ms = (time.perf_counter() - t0) * 1000

    ranked = sorted(
        zip(documents, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    results = []
    for doc, score in ranked[:top_k]:
        if score < min_score:
            break
        enriched = Document(
            page_content=doc.page_content,
            metadata={**doc.metadata, "rerank_score": round(score, 4)},
        )
        results.append(enriched)

    if not results and ranked:
        best_doc, best_score = ranked[0]
        logger.warning(
            f"Všechny rerank skóre pod prahem {min_score:.4f} "
            f"(nejlepší: {best_score:.4f}). Vracím nejlepší kandidát."
        )
        results.append(Document(
            page_content=best_doc.page_content,
            metadata={**best_doc.metadata, "rerank_score": round(best_score, 4)},
        ))

    logger.info(
        f"⏱ BGE reranking: {rerank_ms:.0f}ms "
        f"({len(documents)} párů → {len(results)} výsledků, "
        f"top score: {ranked[0][1]:.4f})"
        if ranked else "⏱ BGE reranking: 0 výsledků"
    )
    return results
