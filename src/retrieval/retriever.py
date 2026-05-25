"""
Hlavní Retriever – orchestruje celou retrieval pipeline.

Pipeline:
  1. Hybridní vyhledávání (BM25 + Qdrant → RRF)
  2. Reranking (BGE cross-encoder)

Implementuje LangChain BaseRetriever pro snadnou integraci
do libovolného RAG chainu.
"""

from __future__ import annotations

import time
from collections import Counter

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

import config
from src.retrieval.hybrid import hybrid_search
from src.retrieval.pricing_retriever import pricing_search
from src.retrieval.query_classifier import classify_query
from src.retrieval.reranker import rerank
from src.utils.logger import get_logger

logger = get_logger(__name__)

COMPLAINT_FALLBACK_MIN_SOURCES = 2
COMPLAINT_EXPANSION_TERMS = (
    "reklamace platby",
    "reklamace transakce",
    "neoprávněná transakce",
    "chargeback",
    "karetní reklamace",
    "vrácení platby",
    "dispute transaction",
    "stížnost na platbu",
    "reklamace karetní transakce",
)
COMPLAINT_ALIAS_TERMS = (
    "reklamac",
    "chargeback",
    "transakc",
    "platb",
    "karetní reklamac",
    "karetni reklamac",
    "dispute",
    "stížnost",
    "stiznost",
    "neoprávněn",
    "neopravnen",
    "vrácení platby",
    "vraceni platby",
)
CREDIT_CARD_RELEVANCE_TERMS = (
    "kreditni-karty",
    "kreditní karta",
    "kreditni karta",
    "kreditní karty",
    "kreditni karty",
    "kreditka",
    "kreditky",
    "kreditek",
    "splátková karta",
    "splatkova karta",
    "karta na splátky",
    "karta na splatky",
    "mastercard",
    "visa",
    "credit card",
    "rb premium",
    "karta style",
    "karta easy",
    "karta o2",
)
CARD_OVERVIEW_EXPANSION_TERMS = (
    "platební karty",
    "debetní karta",
    "kreditní karta",
    "Mastercard",
    "Visa",
    "virtuální karta",
)
CARD_OVERVIEW_RELEVANCE_TERMS = (
    "platební karta",
    "platebni karta",
    "platební karty",
    "platebni karty",
    "debetní karta",
    "debetni karta",
    "debetní karty",
    "debetni karty",
    "kreditní karta",
    "kreditni karta",
    "kreditní karty",
    "kreditni karty",
    "mastercard",
    "visa",
    "virtuální karta",
    "virtualni karta",
    "karty raiffeisenbank",
)

# --- General overview fallback route definitions ---
# Maps overview label → (expansion_terms, relevance_terms)
OVERVIEW_ROUTES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "account_overview": (
        (
            "běžný účet", "osobní účet", "podnikatelský účet",
            "základní účet", "ekonto", "aktivní účet", "firemní účet",
        ),
        (
            "běžný účet", "bezny ucet", "osobní účet", "osobni ucet",
            "podnikatelský účet", "podnikatelsky ucet", "firemní účet", "firemni ucet",
            "ekonto", "aktivní účet", "aktivni ucet", "účet", "ucet",
        ),
    ),
    "mortgage_overview": (
        (
            "hypotéka", "úvěr na bydlení", "refinancování", "fixace",
            "hypoteční úvěr",
        ),
        (
            "hypotéka", "hypoteka", "hypoteční", "hypotecni",
            "úvěr na bydlení", "uver na bydleni", "refinancování", "refinancovani",
        ),
    ),
    "investment_overview": (
        (
            "investice", "fondy", "podílové fondy", "rizika investování",
            "dluhopis", "DIP", "akcie",
        ),
        (
            "investice", "fondy", "podílové fondy", "podilove fondy",
            "dluhopis", "dip", "akcie", "cenné papíry", "cenne papiry",
        ),
    ),
    "rb_key_overview": (
        (
            "RB klíč", "mobilní aplikace", "ověření", "přihlášení",
            "autorizace", "bezpečnost",
        ),
        (
            "rb klíč", "rb klic", "rb-klic", "mobilní klíč", "mobilni klic",
            "mobilní aplikace", "mobilni aplikace", "autorizace", "přihlášení", "prihlaseni",
        ),
    ),
    "payment_overview": (
        (
            "platba", "převod", "tuzemská platba", "zahraniční platba",
            "platební metody",
        ),
        (
            "platba", "převod", "prevod", "tuzemská", "zahraniční", "zahranicni",
            "platební metody", "platebni metody",
        ),
    ),
    "sepa_swift_overview": (
        (
            "SEPA", "SWIFT", "zahraniční platba", "IBAN", "BIC",
            "EUR platba",
        ),
        (
            "sepa", "swift", "zahraniční", "zahranicni", "iban", "bic",
            "zahraniční platba", "zahranicni platba", "eur platba",
        ),
    ),
}


def _source_key(doc: Document) -> str:
    return str(doc.metadata.get("source_url") or doc.metadata.get("url") or doc.metadata.get("file_name") or doc.metadata.get("source") or doc.metadata.get("chunk_id") or "")


def _unique_source_count(docs: list[Document]) -> int:
    return len({key for doc in docs if (key := _source_key(doc))})


def _is_complaint_relevant(doc: Document) -> bool:
    md = doc.metadata
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        str(md.get("category") or ""),
        doc.page_content[:2500],
    ]).lower()
    return any(term in hay for term in COMPLAINT_ALIAS_TERMS)


def _expanded_complaint_query(query: str) -> str:
    q = query.lower()
    terms = [term for term in COMPLAINT_EXPANSION_TERMS if term.lower() not in q]
    return " ".join([query, *terms]).strip()


def _is_credit_card_relevant(doc: Document) -> bool:
    md = doc.metadata
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        str(md.get("category") or ""),
        doc.page_content[:3000],
    ]).lower()
    return any(term in hay for term in CREDIT_CARD_RELEVANCE_TERMS)


def _is_card_overview_relevant(doc: Document) -> bool:
    md = doc.metadata
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        str(md.get("category") or ""),
        doc.page_content[:3000],
    ]).lower()
    return any(term in hay for term in CARD_OVERVIEW_RELEVANCE_TERMS)


def _expanded_card_overview_query(query: str) -> str:
    q = query.lower()
    terms = [term for term in CARD_OVERVIEW_EXPANSION_TERMS if term.lower() not in q]
    return " ".join([query, *terms]).strip()


def _overview_route_for_labels(labels: set[str]) -> str | None:
    """Return the first matching overview route label."""
    for route in OVERVIEW_ROUTES:
        if route in labels:
            return route
    return None


def _is_overview_relevant(doc: Document, relevance_terms: tuple[str, ...]) -> bool:
    """Check if a document is relevant for an overview route."""
    md = doc.metadata
    hay = " ".join([
        str(md.get("source_url") or md.get("url") or ""),
        str(md.get("title") or md.get("file_name") or ""),
        str(md.get("category") or ""),
        doc.page_content[:3000],
    ]).lower()
    return any(term in hay for term in relevance_terms)


def _expanded_overview_query(query: str, expansion_terms: tuple[str, ...]) -> str:
    q = query.lower()
    terms = [term for term in expansion_terms if term.lower() not in q]
    return " ".join([query, *terms]).strip()


def _overview_fallback(
    query: str,
    query_profile: QueryProfile,
    final_docs: list[Document],
    candidates: list[Document],
    hybrid_top_k: int,
    rerank_top_k: int,
    metadata_filters: dict | None,
    bm25_weight: float,
    vector_weight: float,
) -> list[Document]:
    """Generic overview fallback: expand query, re-retrieve, filter by relevance."""
    overview_route = _overview_route_for_labels(query_profile.labels)
    if not overview_route:
        return final_docs

    expansion_terms, relevance_terms = OVERVIEW_ROUTES[overview_route]
    overview_source_count = _unique_source_count([doc for doc in final_docs if _is_overview_relevant(doc, relevance_terms)])

    if not final_docs or overview_source_count == 0:
        expanded_query = _expanded_overview_query(query, expansion_terms)
        logger.warning(
            f"{overview_route} fallback retrieval: "
            f"source_count={overview_source_count}, expanded_query='{expanded_query[:180]}'"
        )
        fallback_profile = classify_query(expanded_query)
        fallback_candidates = hybrid_search(
            query=expanded_query,
            top_k=max(hybrid_top_k, 8),
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
            metadata_filters=metadata_filters,
            query_profile=fallback_profile,
        )
        relevant_fallback_docs = [doc for doc in fallback_candidates if _is_overview_relevant(doc, relevance_terms)]
        if relevant_fallback_docs:
            final_docs = [
                Document(
                    page_content=doc.page_content,
                    metadata={
                        **doc.metadata,
                        "retrieval_route": overview_route,
                        "overview_route_used": True,
                        "overview_type": overview_route,
                        "supported_domain_detected": True,
                        "unsupported_guard_bypassed": True,
                        "fallback_overview_retrieval_used": True,
                        "expanded_query": expanded_query,
                        "fallback_source_count": _unique_source_count(relevant_fallback_docs),
                    },
                )
                for doc in relevant_fallback_docs[:rerank_top_k]
            ]
            logger.info(
                f"{overview_route} fallback succeeded: "
                f"{len(final_docs)} docs, {_unique_source_count(final_docs)} sources"
            )
        else:
            logger.warning(
                f"{overview_route} fallback nenašel relevantní source; "
                f"vracím {len(final_docs)} původních dokumentů"
            )
    else:
        final_docs = [
            Document(
                page_content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "retrieval_route": overview_route,
                    "overview_route_used": True,
                    "overview_type": overview_route,
                    "supported_domain_detected": True,
                    "unsupported_guard_bypassed": True,
                    "fallback_overview_retrieval_used": False,
                    "fallback_source_count": overview_source_count,
                },
            )
            for doc in final_docs
        ]

    return final_docs


class BankingRetriever(BaseRetriever):
    """
    RAG retriever pro Raiffeisenbank dokumenty.

    Kombinuje:
      - BM25 sparse retrieval (přesné shody klíčových slov)
      - Qdrant dense retrieval (sémantické vyhledávání)
      - RRF fúze (Reciprocal Rank Fusion)
      - BGE cross-encoder reranking
    """

    hybrid_top_k: int = Field(default=config.HYBRID_TOP_K)
    rerank_top_k: int = Field(default=config.RERANK_TOP_K)
    bm25_weight: float = Field(default=0.4)
    vector_weight: float = Field(default=0.6)
    metadata_filters: dict | None = Field(default=None)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """
        Vrátí relevantní dokumenty pro dotaz.

        Args:
            query: Uživatelský dotaz.

        Returns:
            Reranked seznam Document objektů.
        """
        t_total = time.perf_counter()
        logger.info(f"▶ Retrieval: '{query[:60]}'")
        query_profile = classify_query(query)
        logger.info(
            f"Query classification: labels={sorted(query_profile.labels)}, "
            f"preferred_urls={query_profile.preferred_url_contains}, "
            f"penalized_urls={query_profile.penalized_url_contains}, "
            f"weights=bm25:{query_profile.bm25_weight}/vector:{query_profile.vector_weight}"
        )

        pricing_docs: list[Document] = []
        if "pricing" in query_profile.labels:
            t_pricing = time.perf_counter()
            pricing_docs = pricing_search(query, top_k=self.rerank_top_k)
            pricing_ms = (time.perf_counter() - t_pricing) * 1000
            if pricing_docs:
                logger.info(
                    f"⏱ PricingRetriever deterministic: {pricing_ms:.0f}ms → {len(pricing_docs)} výsledků; "
                    "hybrid/reranker přeskočen"
                )
                return pricing_docs

        # Krok 1: Hybridní pre-filtr (BM25 + Qdrant + RRF)
        t_hybrid = time.perf_counter()
        candidates = hybrid_search(
            query=query,
            top_k=self.hybrid_top_k,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
            metadata_filters=self.metadata_filters,
            query_profile=query_profile,
        )
        hybrid_ms = (time.perf_counter() - t_hybrid) * 1000

        if not candidates:
            logger.warning("Hybrid search nevrátil žádné výsledky")
            return []

        logger.info(f"⏱ Hybrid search (BM25+Qdrant+RRF): {hybrid_ms:.0f}ms → {len(candidates)} kandidátů")
        candidate_types = Counter(doc.metadata.get("chunk_type", "unknown") for doc in candidates)
        pricing_rows = [doc for doc in candidates if doc.metadata.get("chunk_type") == "pricing_row"]
        logger.info(
            "Retrieval candidate debug: "
            f"top_chunk_types={candidate_types.most_common(8)}, "
            f"pricing_row_count={len(pricing_rows)}, "
            f"pricing_row_hybrid_scores={[doc.metadata.get('hybrid_score') for doc in pricing_rows[:8]]}"
        )

        # Krok 2: Reranking cross-encoderem
        t_rerank = time.perf_counter()
        final_docs = rerank(
            query=query,
            documents=candidates,
            top_k=self.rerank_top_k,
            query_profile=query_profile,
        )
        rerank_ms = (time.perf_counter() - t_rerank) * 1000

        if not final_docs and "pricing" in query_profile.labels:
            fallback_docs = pricing_rows or [
                doc for doc in candidates
                if doc.metadata.get("chunk_type") in {"pricing", "table", "pdf_table"} or doc.metadata.get("document_type") == "pricing"
            ]
            if fallback_docs:
                final_docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={**doc.metadata, "rerank_score": doc.metadata.get("hybrid_score", 0.0), "fallback_reason": "pricing_rerank_empty"},
                    )
                    for doc in fallback_docs[: self.rerank_top_k]
                ]
                logger.warning(
                    f"Pricing fallback: reranker nevrátil výsledky, vracím {len(final_docs)} "
                    f"kandidátů typu {[doc.metadata.get('chunk_type') for doc in final_docs]}"
                )

        is_complaints_route = "complaints" in query_profile.labels or any(
            doc.metadata.get("retrieval_route") == "reklamace" for doc in candidates[:5]
        )
        retrieved_source_count = _unique_source_count(final_docs)
        if is_complaints_route and retrieved_source_count < COMPLAINT_FALLBACK_MIN_SOURCES:
            expanded_query = _expanded_complaint_query(query)
            logger.warning(
                "Complaints fallback retrieval: "
                f"source_count={retrieved_source_count}, expanded_query='{expanded_query[:180]}'"
            )
            t_fallback = time.perf_counter()
            fallback_profile = classify_query(expanded_query)
            fallback_candidates = hybrid_search(
                query=expanded_query,
                top_k=self.hybrid_top_k,
                bm25_weight=self.bm25_weight,
                vector_weight=self.vector_weight,
                metadata_filters=self.metadata_filters,
                query_profile=fallback_profile,
            )
            fallback_docs = rerank(
                query=expanded_query,
                documents=fallback_candidates,
                top_k=self.rerank_top_k,
                query_profile=fallback_profile,
            )
            relevant_fallback_docs = [doc for doc in fallback_docs if _is_complaint_relevant(doc)]
            fallback_source_count = _unique_source_count(relevant_fallback_docs)
            fallback_ms = (time.perf_counter() - t_fallback) * 1000

            if relevant_fallback_docs:
                final_docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={
                            **doc.metadata,
                            "retrieval_route": "reklamace",
                            "fallback_used": True,
                            "fallback_retrieval_used": True,
                            "expanded_query": expanded_query,
                            "fallback_source_count": fallback_source_count,
                            "fallback_reason": "complaints_low_source_count",
                        },
                    )
                    for doc in relevant_fallback_docs
                ]
                logger.info(
                    "Complaints fallback succeeded: "
                    f"{len(final_docs)} docs, {fallback_source_count} sources, {fallback_ms:.0f}ms"
                )
            elif not any(_is_complaint_relevant(doc) for doc in final_docs):
                final_docs = []
                logger.warning(
                    "Complaints fallback nenašel relevantní source; vracím prázdný výsledek "
                    "pro bezpečný unsupported response bez halucinací"
                )

        if "credit_card_catalog" in query_profile.labels:
            credit_source_count = _unique_source_count([doc for doc in final_docs if _is_credit_card_relevant(doc)])
            if not final_docs or credit_source_count == 0:
                fallback_docs = [doc for doc in candidates if _is_credit_card_relevant(doc)]
                if fallback_docs:
                    final_docs = [
                        Document(
                            page_content=doc.page_content,
                            metadata={
                                **doc.metadata,
                                "retrieval_route": "credit_card_catalog",
                                "fallback_used": True,
                                "fallback_retrieval_used": True,
                                "catalog_intent_detected": True,
                                "boosted_product_group": "kreditni_karta",
                                "matched_credit_card_sources": _unique_source_count(fallback_docs),
                                "fallback_reason": "credit_card_catalog_rerank_empty_or_non_credit",
                            },
                        )
                        for doc in fallback_docs[: self.rerank_top_k]
                    ]
                    logger.info(
                        "Credit-card catalog fallback succeeded: "
                        f"{len(final_docs)} docs, {_unique_source_count(final_docs)} sources"
                    )
            else:
                final_docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={
                            **doc.metadata,
                            "catalog_intent_detected": True,
                            "boosted_product_group": "kreditni_karta",
                            "matched_credit_card_sources": credit_source_count,
                        },
                    )
                    for doc in final_docs
                ]

        if "card_overview" in query_profile.labels:
            overview_source_count = _unique_source_count([doc for doc in final_docs if _is_card_overview_relevant(doc)])
            if not final_docs or overview_source_count == 0:
                expanded_query = _expanded_card_overview_query(query)
                fallback_profile = classify_query(expanded_query)
                fallback_candidates = hybrid_search(
                    query=expanded_query,
                    top_k=max(self.hybrid_top_k, 8),
                    bm25_weight=self.bm25_weight,
                    vector_weight=self.vector_weight,
                    metadata_filters=self.metadata_filters,
                    query_profile=fallback_profile,
                )
                relevant_fallback_docs = [doc for doc in fallback_candidates if _is_card_overview_relevant(doc)]
                if relevant_fallback_docs:
                    final_docs = [
                        Document(
                            page_content=doc.page_content,
                            metadata={
                                **doc.metadata,
                                "retrieval_route": "card_overview",
                                "overview_route_used": True,
                                "overview_type": "card_overview",
                                "supported_domain_detected": True,
                                "unsupported_guard_bypassed": True,
                                "fallback_card_retrieval_used": True,
                                "expanded_query": expanded_query,
                                "fallback_source_count": _unique_source_count(relevant_fallback_docs),
                            },
                        )
                        for doc in relevant_fallback_docs[: self.rerank_top_k]
                    ]
                    logger.info(
                        "Card overview fallback succeeded: "
                        f"{len(final_docs)} docs, {_unique_source_count(final_docs)} sources"
                    )
            else:
                final_docs = [
                    Document(
                        page_content=doc.page_content,
                        metadata={
                            **doc.metadata,
                            "retrieval_route": "card_overview",
                            "overview_route_used": True,
                            "overview_type": "card_overview",
                            "supported_domain_detected": True,
                            "unsupported_guard_bypassed": True,
                            "fallback_card_retrieval_used": False,
                            "fallback_source_count": overview_source_count,
                        },
                    )
                    for doc in final_docs
                ]

        # Generic overview fallback for all other supported product overview routes.
        overview_route = _overview_route_for_labels(query_profile.labels)
        if overview_route:
            final_docs = _overview_fallback(
                query=query,
                query_profile=query_profile,
                final_docs=final_docs,
                candidates=candidates,
                hybrid_top_k=self.hybrid_top_k,
                rerank_top_k=self.rerank_top_k,
                metadata_filters=self.metadata_filters,
                bm25_weight=self.bm25_weight,
                vector_weight=self.vector_weight,
            )

        total_retrieval_ms = (time.perf_counter() - t_total) * 1000
        logger.info(
            f"⏱ Retrieval celkem: {total_retrieval_ms:.0f}ms "
            f"(hybrid={hybrid_ms:.0f}ms, rerank={rerank_ms:.0f}ms) "
            f"→ {len(final_docs)} výsledků"
        )
        return final_docs

    def get_relevant_documents_with_scores(
        self, query: str
    ) -> list[tuple[Document, float]]:
        """Vrátí dokumenty spolu s rerank skórem (pro debug/logging)."""
        docs = self.invoke(query)
        return [
            (doc, doc.metadata.get("rerank_score", 0.0))
            for doc in docs
        ]
