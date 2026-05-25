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

from collections import Counter, defaultdict

from langchain_core.documents import Document

import config
from src.retrieval.bm25_retriever import bm25_search
from src.retrieval.query_classifier import QueryProfile, classify_query, expand_query, freshness_priority, is_archived_doc, is_corporate_doc, is_personal_retail_doc, is_retail_doc, source_priority
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
    metadata_filters: dict | None = None,
    query_profile: QueryProfile | None = None,
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
    query_profile = query_profile or classify_query(query)
    expanded_query = expand_query(query, query_profile)
    retrieval_route = (
        "pricing" if "pricing" in query_profile.labels else
        "reklamace" if "complaints" in query_profile.labels else
        "card_overview" if "card_overview" in query_profile.labels else
        "account_overview" if "account_overview" in query_profile.labels else
        "mortgage_overview" if "mortgage_overview" in query_profile.labels else
        "investment_overview" if "investment_overview" in query_profile.labels else
        "rb_key_overview" if "rb_key_overview" in query_profile.labels else
        "payment_overview" if "payment_overview" in query_profile.labels else
        "sepa_swift_overview" if "sepa_swift_overview" in query_profile.labels else
        "product_overview" if "product_overview" in query_profile.labels else
        "credit_card_catalog" if "credit_card_catalog" in query_profile.labels else
        "faq" if "faq" in query_profile.labels else
        "hybrid"
    )
    bm25_weight = query_profile.bm25_weight if bm25_weight == 0.4 else bm25_weight
    vector_weight = query_profile.vector_weight if vector_weight == 0.6 else vector_weight

    # Paralelní dotazy na oba retrievery
    bm25_results = bm25_search(expanded_query, top_k=config.BM25_TOP_K, metadata_filters=metadata_filters)
    try:
        vector_results = vector_search(expanded_query, top_k=config.VECTOR_TOP_K, metadata_filters=metadata_filters)
    except Exception as exc:
        vector_results = []
        logger.warning(f"Vector retrieval selhal, pokračuji BM25-only fallbackem: {exc}")

    pricing_row_bm25: list[Document] = []
    pricing_row_vector: list[Document] = []
    if "pricing" in query_profile.labels:
        row_filter = {**(metadata_filters or {}), "chunk_type": "pricing_row"}
        pricing_row_bm25 = bm25_search(expanded_query, top_k=min(config.BM25_TOP_K, 30), metadata_filters=row_filter)
        try:
            pricing_row_vector = vector_search(expanded_query, top_k=min(config.VECTOR_TOP_K, 30), metadata_filters=row_filter)
        except Exception as exc:
            logger.warning(f"Pricing_row vector fallback selhal, pokračuji s BM25 rows: {exc}")
        bm25_results = pricing_row_bm25 + bm25_results
        vector_results = pricing_row_vector + vector_results
        logger.info(
            f"Pricing_row recall: bm25={len(pricing_row_bm25)}, qdrant={len(pricing_row_vector)}, "
            f"expanded_query='{expanded_query[:140]}'"
        )

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

    # Metadata-aware boosting/penalizace nad RRF skóre.
    boosted: list[tuple[Document, float]] = []
    for doc, base_score in (item for item in scores.values()):
        metadata_boost, reasons = source_priority(doc, query_profile)
        freshness_score, archived_penalty, _freshness_reasons = freshness_priority(doc, query_profile)
        final_score = base_score + metadata_boost
        boosted.append((
            Document(
                page_content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "rewritten_query": expanded_query,
                    "retrieval_route": retrieval_route,
                    "overview_route_used": "product_overview" in query_profile.labels or "card_overview" in query_profile.labels,
                    "overview_type": (
                        "account_overview" if "account_overview" in query_profile.labels else
                        "mortgage_overview" if "mortgage_overview" in query_profile.labels else
                        "investment_overview" if "investment_overview" in query_profile.labels else
                        "rb_key_overview" if "rb_key_overview" in query_profile.labels else
                        "payment_overview" if "payment_overview" in query_profile.labels else
                        "sepa_swift_overview" if "sepa_swift_overview" in query_profile.labels else
                        "card_overview" if "card_overview" in query_profile.labels else
                        "product_overview" if "product_overview" in query_profile.labels else
                        None
                    ),
                    "supported_domain_detected": "supported_domain" in query_profile.labels,
                    "unsupported_guard_bypassed": "supported_domain" in query_profile.labels,
                    "catalog_intent_detected": "catalog_intent" in query_profile.labels,
                    "boosted_product_group": "kreditni_karta" if "credit_card" in query_profile.labels else None,
                    "expanded_credit_card_terms": [
                        term for term in ("kreditka", "kreditní karta", "splátková karta", "Mastercard kreditní karta", "Visa kreditní karta")
                        if "credit_card" in query_profile.labels and term.lower() in expanded_query.lower()
                    ],
                    "metadata_boost_reason": reasons[:8],
                    "faq_priority_used": any("faq_priority_used" in reason for reason in reasons),
                    "hybrid_base_score": round(base_score, 6),
                    "metadata_boost": round(metadata_boost, 6),
                    "freshness_score": round(freshness_score, 6),
                    "archived_penalty": round(archived_penalty, 6),
                    "retrieval_reasons": reasons,
                    "query_labels": sorted(query_profile.labels),
                },
            ),
            final_score,
        ))

    # Seřadíme podle boosted skóre
    ranked = sorted(boosted, key=lambda x: x[1], reverse=True)

    pricing_row_candidates = [(doc, score) for doc, score in ranked if doc.metadata.get("chunk_type") == "pricing_row"]
    logger.info(
        "Hybrid candidate types: "
        + ", ".join(
            f"{chunk_type}:{count}"
            for chunk_type, count in Counter(doc.metadata.get("chunk_type", "unknown") for doc, _ in ranked).most_common(8)
        )
        + f" | pricing_row_found={len(pricing_row_candidates)}"
        + (
            " | pricing_row_scores=" + ", ".join(f"{score:.4f}" for _doc, score in pricing_row_candidates[:5])
            if pricing_row_candidates else ""
        )
    )

    if "retail_banking" in query_profile.labels and "corporate_banking" not in query_profile.labels:
        personal_mode = "personal_retail_account" in query_profile.labels
        def _allowed_retail_doc(doc: Document) -> bool:
            return is_personal_retail_doc(doc) if personal_mode else (is_retail_doc(doc) and not is_corporate_doc(doc))

        has_retail = any(_allowed_retail_doc(doc) for doc, _score in ranked)
        if has_retail:
            before = len(ranked)
            if "cards" not in query_profile.labels and "mortgages" not in query_profile.labels:
                ranked = [(doc, score) for doc, score in ranked if _allowed_retail_doc(doc)]
                logger.info(f"Retail hard filter: ponechány pouze {'personal retail' if personal_mode else 'retail/account'} kandidáti {before} → {len(ranked)}")
            else:
                ranked = [(doc, score) for doc, score in ranked if not is_corporate_doc(doc)]
                logger.info(f"Retail hard filter: corporate kandidáti odfiltrováni {before} → {len(ranked)}")

    if "pricing" in query_profile.labels and "archived_requested" not in query_profile.labels:
        active_ranked = [(doc, score) for doc, score in ranked if not is_archived_doc(doc)]
        if active_ranked:
            before = len(ranked)
            ranked = active_ranked
            logger.info(f"Freshness hard filter: archived/discontinued pricing vyřazeno {before} → {len(ranked)}")

    # Deduplication: max MAX_CHUNKS_PER_SOURCE chunků z jednoho zdrojového souboru.
    # Bez tohoto může jeden soubor s mnoha podobnými chunky (napr. 516 chunků
    # BlueChipBond) obsadit všechna místa ve výsledcích přesto, že relevantní
    # dokumenty z jiných souborů mají celkově vyšší pokrytí dotazu.
    source_counts: dict[str, int] = defaultdict(int)
    results = []
    for doc, score in ranked:
        source = doc.metadata.get("source_url") or doc.metadata.get("url") or doc.metadata.get("file_name", "")
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
