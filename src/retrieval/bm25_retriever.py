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
import unicodedata
from functools import lru_cache
from collections import Counter

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


def _strip_diacritics(text: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )


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


def _matches_filters(doc: Document, metadata_filters: dict | None) -> bool:
    if not metadata_filters:
        return True
    for key, expected in metadata_filters.items():
        actual = doc.metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def bm25_pricing_row_debug(limit: int = 12) -> dict:
    """Return pricing_row coverage diagnostics from the BM25 document store."""
    documents = _load_documents()
    rows = [doc for doc in documents if doc.metadata.get("chunk_type") == "pricing_row"]
    non_empty = [doc for doc in rows if doc.page_content and doc.page_content.strip()]
    return {
        "bm25_documents": len(documents),
        "pricing_row_count": len(rows),
        "pricing_row_non_empty": len(non_empty),
        "top_product_name": Counter(str(doc.metadata.get("product_name") or "").strip() or "<empty>" for doc in rows).most_common(limit),
        "top_fee_type": Counter(str(doc.metadata.get("fee_type") or "").strip() or "<empty>" for doc in rows).most_common(limit),
        "sample_rows": [
            {
                "product_name": doc.metadata.get("product_name"),
                "fee_type": doc.metadata.get("fee_type"),
                "fee_value": doc.metadata.get("fee_value"),
                "source_url": doc.metadata.get("source_url"),
                "page": doc.metadata.get("page"),
                "content_preview": doc.page_content[:220],
            }
            for doc in non_empty[: min(5, limit)]
        ],
    }


def bm25_search(
    query: str,
    top_k: int = config.BM25_TOP_K,
    metadata_filters: dict | None = None,
    max_query_tokens: int | None = None,
) -> list[Document]:
    """
    Vyhledá top_k nejrelevantnějších chunků pomocí BM25.

    Args:
        query:            Uživatelský dotaz v přirozeném jazyce.
        top_k:            Počet výsledků.
        max_query_tokens: Pokud zadáno, omezí BM25 tokeny na N s nejvyšším IDF.
                          Pricing: 4, non-pricing: 3. Snižuje O(n_tokens × n_docs).

    Returns:
        Seřazený seznam Document objektů (nejlepší první).
    """
    bm25 = _load_bm25_index()
    documents = _load_documents()

    # Přidej verzi bez diakritiky — pokryje dotazy psané bez háčků/čárek.
    # Duplikátní tokeny nevadí (BM25 je váhuje stejně).
    stripped = _strip_diacritics(query)
    query_expanded = query if stripped == query else f"{query} {stripped}"

    tokenized_query = _tokenize(query_expanded)
    if max_query_tokens and len(tokenized_query) > max_query_tokens:
        tokenized_query = sorted(
            tokenized_query,
            key=lambda t: bm25.idf.get(t, 0.0),
            reverse=True,
        )[:max_query_tokens]

    t0 = time.perf_counter()
    scores = bm25.get_scores(tokenized_query)
    ranked_indices = []
    for idx in sorted(range(len(scores)), key=lambda i: scores[i], reverse=True):
        if _matches_filters(documents[idx], metadata_filters):
            ranked_indices.append(idx)
        if len(ranked_indices) >= top_k:
            break
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
