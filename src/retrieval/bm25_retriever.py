"""
Sparse retrieval pomocí BM25 (Best Match 25).

BM25 je TF-IDF varianta optimalizovaná pro kratší dokumenty.
Dobře funguje pro přesné shody klíčových slov (čísla produktů,
konkrétní výrazy jako „ČSOB", „úrok", „RPSN", apod.).

Index je načten z disku (vytvořen během ingestion).
"""

from __future__ import annotations

import pickle
import time
from functools import lru_cache

from langchain_core.documents import Document

import config
from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _load_bm25_index():
    """Načte BM25 index z disku (singleton, cachovaný)."""
    if not config.BM25_INDEX_PATH.exists():
        raise FileNotFoundError(
            f"BM25 index nenalezen: {config.BM25_INDEX_PATH}\n"
            "Spusťte nejprve: python scripts/ingest.py"
        )
    with open(config.BM25_INDEX_PATH, "rb") as f:
        return pickle.load(f)


@lru_cache(maxsize=1)
def _load_documents() -> list[Document]:
    """Načte uložené dokumenty (singleton, cachovaný)."""
    if not config.DOCS_STORE_PATH.exists():
        raise FileNotFoundError(
            f"Dokumenty nenalezeny: {config.DOCS_STORE_PATH}\n"
            "Spusťte nejprve: python scripts/ingest.py"
        )
    with open(config.DOCS_STORE_PATH, "rb") as f:
        return pickle.load(f)


def _tokenize(text: str) -> list[str]:
    """
    Tokenizuje text pro BM25 vyhledávání.

    Rozdíl oproti prostému .split():
      - Odstraňuje interpunkci ze začátku/konce tokenů
        ("hypotéku?" → "hypotéku", "účtu," → "účtu")
      - Zachovává česká diakritická znaménka (á, č, ě, í, ...)
      - Přeskočí prázdné tokeny vzniklé po odebrání interpunkce

    BUG bez tohoto: query "hypotéku?" neodpovídá indexovanému "hypotéku"
    → BM25 vrací zcela irelevantní dokumenty s nulovým overlappem.
    """
    import re
    tokens = []
    for raw in text.lower().split():
        # Odstraníme interpunkci z okrajů, ponecháme písmena + číslice + diakritiku
        clean = re.sub(r'^[^\wÀ-ɏ]+|[^\wÀ-ɏ]+$', '', raw)
        if clean:
            tokens.append(clean)
    return tokens


def bm25_search(query: str, top_k: int = config.BM25_TOP_K) -> list[Document]:
    """
    Vyhledá top_k nejrelevantnějších chunků pomocí BM25.

    Args:
        query: Uživatelský dotaz v přirozeném jazyce.
        top_k: Počet výsledků.

    Returns:
        Seřazený seznam Document objektů (nejlepší první).
    """
    bm25 = _load_bm25_index()
    documents = _load_documents()

    tokenized_query = _tokenize(query)

    t0 = time.perf_counter()
    scores = bm25.get_scores(tokenized_query)
    ranked_indices = sorted(
        range(len(scores)), key=lambda i: scores[i], reverse=True
    )[:top_k]
    bm25_ms = (time.perf_counter() - t0) * 1000

    results = []
    for idx in ranked_indices:
        doc = documents[idx]
        enriched = Document(
            page_content=doc.page_content,
            metadata={**doc.metadata, "bm25_score": float(scores[idx])},
        )
        results.append(enriched)

    logger.info(
        f"⏱ BM25 retrieval: {bm25_ms:.0f}ms "
        f"({len(documents)} dokumentů, top score: {scores[ranked_indices[0]]:.3f})"
    )
    return results
