"""
Hybridní retrieval: fúze BM25 (sparse) + Qdrant (dense) pomocí RRF.

Reciprocal Rank Fusion (RRF) kombinuje pořadové seznamy bez nutnosti
normalizovat různorodá skóre. Každý dokument dostane skóre:

    RRF(d) = Σ_r  1 / (k + rank_r(d))

kde k=60 je empiricky ověřená konstanta (Cormack et al., 2009).

Výhoda hybridního přístupu:
  - BM25 zachytí přesné shody (čísla, zkratky, produkty)
  - Dense retrieval zachytí sémantické ekvivalenty a parafráze
"""

from __future__ import annotations

from collections import defaultdict

from langchain_core.documents import Document

import config
from src.retrieval.bm25_retriever import bm25_search
from src.retrieval.vector_retriever import vector_search
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maximální počet chunků ze stejného zdrojového souboru v RRF výsledcích.
# Brání tomu, aby jeden dokument s mnoha podobnými chunky (např. 516×
# BlueChipBond s cosine ≈ 0.72) zaplnil celý výsledkový seznam.
MAX_CHUNKS_PER_SOURCE: int = 2


def _rrf_score(rank: int, k: int = config.RRF_K) -> float:
    """Vypočítá RRF skóre pro danou pozici v pořadovém seznamu."""
    return 1.0 / (k + rank)


def hybrid_search(
    query: str,
    top_k: int = config.HYBRID_TOP_K,
    bm25_weight: float = 0.4,
    vector_weight: float = 0.6,
) -> list[Document]:
    """
    Hybridní vyhledávání s RRF fúzí.

    Args:
        query:         Uživatelský dotaz.
        top_k:         Počet výsledků po fúzi.
        bm25_weight:   Váha BM25 ranku v RRF (0–1).
        vector_weight: Váha dense ranku v RRF (0–1).

    Returns:
        Seřazený seznam Document objektů s metadatem `hybrid_score`.
    """
    # Paralelní dotazy na oba retrievery
    bm25_results = bm25_search(query, top_k=config.BM25_TOP_K)
    vector_results = vector_search(query, top_k=config.VECTOR_TOP_K)

    # Mapa chunk_id → (Document, rrf_score)
    scores: dict[str, tuple[Document, float]] = {}

    def _get_doc_key(doc: Document) -> str:
        return doc.metadata.get("chunk_id") or doc.page_content[:100]

    # Přidáme BM25 příspěvky
    for rank, doc in enumerate(bm25_results, start=1):
        key = _get_doc_key(doc)
        contribution = bm25_weight * _rrf_score(rank)
        if key in scores:
            _, existing = scores[key]
            scores[key] = (doc, existing + contribution)
        else:
            scores[key] = (doc, contribution)

    # Přidáme dense příspěvky
    for rank, doc in enumerate(vector_results, start=1):
        key = _get_doc_key(doc)
        contribution = vector_weight * _rrf_score(rank)
        if key in scores:
            existing_doc, existing_score = scores[key]
            scores[key] = (existing_doc, existing_score + contribution)
        else:
            scores[key] = (doc, contribution)

    # Seřadíme podle RRF skóre
    ranked = sorted(scores.values(), key=lambda x: x[1], reverse=True)

    # Deduplication: max MAX_CHUNKS_PER_SOURCE chunků z jednoho zdrojového souboru.
    # Bez tohoto může jeden soubor s mnoha podobnými chunky (napr. 516 chunků
    # BlueChipBond) obsadit všechna místa ve výsledcích přesto, že relevantní
    # dokumenty z jiných souborů mají celkově vyšší pokrytí dotazu.
    source_counts: dict[str, int] = defaultdict(int)
    results = []
    for doc, score in ranked:
        source = doc.metadata.get("file_name", "")
        if source_counts[source] >= MAX_CHUNKS_PER_SOURCE:
            continue
        source_counts[source] += 1
        enriched = Document(
            page_content=doc.page_content,
            metadata={**doc.metadata, "hybrid_score": round(score, 6)},
        )
        results.append(enriched)
        if len(results) >= top_k:
            break

    logger.debug(
        f"Hybrid RRF: '{query[:40]}…' → {len(results)} výsledků "
        f"(top RRF: {ranked[0][1]:.4f}, unikátních zdrojů: {len(source_counts)})"
        if ranked else
        f"Hybrid RRF: '{query[:40]}…' → 0 výsledků"
    )
    return results
