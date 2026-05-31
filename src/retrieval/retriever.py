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
from src.retrieval.pricing_resolver import _cached_resolve_pricing_query as resolve_pricing_query
from src.retrieval.query_classifier import classify_query, is_archived_doc
from src.retrieval.reranker import rerank
from src.retrieval.url_product_filter import is_product_url
from src.retrieval.source_governance import (
    MAX_RECOVERY_DOCS,
    MIN_REQUIRED_DOCS,
    apply_governance_pipeline,
    apply_source_diversity,
    attach_governance_summary,
    merge_recovery_docs,
)
from src.utils.logger import get_logger
from src.utils.telemetry import telemetry

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

RECOVERY_BASE_TERMS = (
    "aktuální informace",
    "aktuální zdroj",
    "oficiální stránka",
    "FAQ",
    "podpora",
)

RECOVERY_LABEL_TERMS: dict[str, tuple[str, ...]] = {
    "pricing": ("aktuální ceník", "poplatky", "sazebník", "platné ceny"),
    "accounts": ("běžný účet", "osobní účet", "eKonto", "Aktivní účet"),
    "cards": ("platební karta", "kreditní karta", "debetní karta"),
    "payments": ("platba", "převod", "SEPA", "SWIFT"),
    "mortgages": ("hypotéka", "úvěr na bydlení"),
    "investments": ("investice", "fondy", "cenné papíry"),
    "support": ("návod", "jak postupovat", "podpora"),
}

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


def _recovery_query(query: str, labels: set[str]) -> str:
    """Build a broader recovery query without changing embeddings or index."""
    q = query.lower()
    terms: list[str] = []
    for term in RECOVERY_BASE_TERMS:
        if term.lower() not in q:
            terms.append(term)
    for label, label_terms in RECOVERY_LABEL_TERMS.items():
        if label in labels:
            for term in label_terms:
                if term.lower() not in q:
                    terms.append(term)
    return " ".join([query, *terms[:8]]).strip()


def _family_key(doc: Document) -> str:
    return str(
        doc.metadata.get("document_family")
        or doc.metadata.get("canonical_product")
        or doc.metadata.get("product_name")
        or doc.metadata.get("source_url")
        or doc.metadata.get("url")
        or doc.metadata.get("file_name")
        or ""
    ).strip().lower()


def _is_current_preferred_recovery_doc(doc: Document) -> bool:
    tier = str(doc.metadata.get("canonical_source_type") or doc.metadata.get("authority_tier") or "").lower()
    if tier in {"historical_pdf", "migration_notice", "archived_legal"}:
        return False
    return not is_archived_doc(doc)


def _restricted_recovery_docs(
    recovery_docs: list[Document],
    current_docs: list[Document],
    original_candidates: list[Document],
) -> list[Document]:
    """Prefer recovery docs from known source families and current sources."""
    allowed_families = {
        key
        for doc in [*current_docs, *original_candidates[:12]]
        if (key := _family_key(doc)) and not is_archived_doc(doc)
    }
    current_first = [doc for doc in recovery_docs if _is_current_preferred_recovery_doc(doc)]
    pool = current_first or recovery_docs
    restricted = [doc for doc in pool if not allowed_families or _family_key(doc) in allowed_families]
    return restricted or pool


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
    last_governance_meta: dict = Field(default_factory=dict, exclude=True)

    def _apply_governance_with_recovery(
        self,
        query: str,
        docs: list[Document],
        original_candidates: list[Document],
        query_profile,
    ) -> tuple[list[Document], dict, float, float]:
        """Apply governance, then run controlled recovery if collapse is detected."""
        t_gov = time.perf_counter()
        governed_docs, gov_meta = apply_governance_pipeline(docs, query_profile)
        gov_ms = (time.perf_counter() - t_gov) * 1000
        final_docs = governed_docs
        recovery_ms = 0.0

        if gov_meta.get("recovery_pass_needed"):
            recovery_query = _recovery_query(query, query_profile.labels)
            t_recovery = time.perf_counter()
            recovery_profile = classify_query(recovery_query)
            logger.warning(
                "Retrieval recovery pass triggered: "
                f"reason={gov_meta.get('recovery_reason')}, "
                f"suppression_ratio={gov_meta.get('suppression_ratio')}, "
                f"final_docs={len(final_docs)}, recovery_query='{recovery_query[:180]}'"
            )
            recovery_candidates = hybrid_search(
                query=recovery_query,
                top_k=max(self.hybrid_top_k * 2, 12),
                bm25_weight=max(self.bm25_weight, 0.55),
                vector_weight=min(self.vector_weight, 0.45),
                metadata_filters=self.metadata_filters,
                query_profile=recovery_profile,
            )
            recovery_ranked = rerank(
                query=recovery_query,
                documents=recovery_candidates,
                top_k=max(self.rerank_top_k, MIN_REQUIRED_DOCS + MAX_RECOVERY_DOCS),
                query_profile=recovery_profile,
            )
            recovery_governed, _recovery_gov_meta = apply_governance_pipeline(recovery_ranked, recovery_profile)
            recovery_pool = _restricted_recovery_docs(recovery_governed, final_docs, original_candidates)
            merged_docs, added_count = merge_recovery_docs(
                final_docs,
                recovery_pool,
                recovery_reason=str(gov_meta.get("recovery_reason") or "retrieval_collapse"),
                recovery_query=recovery_query,
            )
            diversified_docs, diversity_meta = apply_source_diversity(merged_docs)
            final_docs = diversified_docs or merged_docs
            recovery_ms = (time.perf_counter() - t_recovery) * 1000
            gov_meta.update(diversity_meta)
            gov_meta.update({
                "recovery_pass_used": True,
                "recovery_reason": gov_meta.get("recovery_reason") or "retrieval_collapse",
                "recovery_query": recovery_query,
                "recovery_result_count": added_count,
                "recovery_pass_latency_ms": round(recovery_ms, 1),
                "retrieval_collapse_detected": added_count == 0 and len(final_docs) < MIN_REQUIRED_DOCS,
                "resilience_strategy": "governance_recovery" if added_count else "collapse_detected_no_recovery",
                "final_source_count": len(final_docs),
                "output_count": len(final_docs),
            })
            attach_governance_summary(final_docs, gov_meta)
            logger.info(
                "Retrieval recovery pass completed: "
                f"added={added_count}, candidates={len(recovery_candidates)}, "
                f"ranked={len(recovery_ranked)}, final={len(final_docs)}, latency={recovery_ms:.0f}ms"
            )

        if not final_docs and docs:
            # Preserve governance semantics: do not reintroduce suppressed/stale docs.
            gov_meta["retrieval_collapse_detected"] = True
            gov_meta["resilience_strategy"] = "governance_suppressed"
            logger.warning("Source governance suppressed all docs and recovery did not restore safe sources")

        attach_governance_summary(final_docs, gov_meta)
        self.last_governance_meta = gov_meta
        return final_docs, gov_meta, gov_ms, recovery_ms

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
            pricing_docs = resolve_pricing_query(query, top_k=self.rerank_top_k)
            pricing_ms = (time.perf_counter() - t_pricing) * 1000
            if pricing_docs:
                pricing_docs, gov_meta, gov_ms, recovery_ms = self._apply_governance_with_recovery(
                    query=query,
                    docs=pricing_docs,
                    original_candidates=pricing_docs,
                    query_profile=query_profile,
                )
                logger.info(
                    f"⏱ PricingRetriever deterministic: {pricing_ms:.0f}ms → {len(pricing_docs)} výsledků; "
                    f"governance={gov_ms:.0f}ms, recovery={recovery_ms:.0f}ms; "
                    f"governance_suppressed={gov_meta.get('suppressed_count', 0)}; "
                    f"recovery_pass_used={gov_meta.get('recovery_pass_used', False)}; "
                    "hybrid/reranker přeskočen"
                )
                telemetry.emit(
                    "retrieval_completed",
                    question=query,
                    route="pricing",
                    source_count=len(pricing_docs),
                    suppressed_count=gov_meta.get("suppressed_count", 0),
                    suppression_ratio=gov_meta.get("suppression_ratio", 0.0),
                    recovery_triggered=gov_meta.get("recovery_pass_used", False),
                    recovery_added_count=gov_meta.get("recovery_result_count", 0),
                    diversity_score=gov_meta.get("diversity_score", 0.0),
                    retrieval_collapse_detected=gov_meta.get("retrieval_collapse_detected", False),
                    resilience_strategy=gov_meta.get("resilience_strategy"),
                )
                return pricing_docs

        # Krok 1: Hybridní pre-filtr (BM25 + Qdrant + RRF)
        # Widen the RRF pool for category queries without pricing so that
        # product_page docs aren't crowded out by high-scoring pricing PDFs.
        CATEGORY_LABELS_WIDE = {"mortgages", "cards", "accounts", "payments", "investments"}
        hybrid_top_k = self.hybrid_top_k
        if CATEGORY_LABELS_WIDE & query_profile.labels and "pricing" not in query_profile.labels:
            hybrid_top_k = max(hybrid_top_k, 20)
        t_hybrid = time.perf_counter()
        candidates = hybrid_search(
            query=query,
            top_k=hybrid_top_k,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
            metadata_filters=self.metadata_filters,
            query_profile=query_profile,
        )
        hybrid_ms = (time.perf_counter() - t_hybrid) * 1000
        # URL product filter disabled — was incorrectly dropping valid product pages
        # (e.g. kreditni-karta-easy, kreditni-karta-rb-premium) whose URLs contain
        # segments that matched NON_PRODUCT_SEGMENTS. BM25+vector already surface them.
        # if "catalog_intent" in query_profile.labels and "product_overview" in query_profile.labels:
        #     before_cnt = len(candidates)
        #     filtered_candidates = [
        #         doc for doc in candidates
        #         if is_product_url(
        #             str(doc.metadata.get("source_url") or doc.metadata.get("url") or "")
        #         )
        #     ]
        #     after_cnt = len(filtered_candidates)
        #     logger.info(
        #         f"URL product filter – catalog_intent & product_overview: before={before_cnt}, after={after_cnt}"
        #     )
        #     candidates = filtered_candidates

        if not candidates:
            logger.warning("Hybrid search nevrátil žádné výsledky")
            self.last_governance_meta = {
                "retrieval_collapse_detected": True,
                "resilience_strategy": "supported_but_missing_data",
                "final_source_count": 0,
            }
            return []

        logger.info(f"⏱ Hybrid search (BM25+Qdrant+RRF): {hybrid_ms:.0f}ms → {len(candidates)} kandidátů")
        candidate_types = Counter(doc.metadata.get("chunk_type", "unknown") for doc in candidates)
        pricing_rows = [doc for doc in candidates if doc.metadata.get("chunk_type") == "pricing_row"]
        logger.info(
            "Hybrid candidate types: "
            + "/".join(f"{t}:{c}" for t, c in candidate_types.most_common(8))
            + f" | pricing_row_found={len(pricing_rows)}"
        )

        # When query is category-specific but NOT pricing, exclude pricing docs
        # from candidates so the reranker doesn't crowd them out.
        CATEGORY_LABELS = {"mortgages", "cards", "accounts", "payments", "investments"}
        if CATEGORY_LABELS & query_profile.labels and "pricing" not in query_profile.labels:
            non_pricing = [
                doc for doc in candidates
                if doc.metadata.get("document_type") != "pricing"
                and doc.metadata.get("chunk_type") not in {"pricing", "pricing_row", "table", "pdf_table"}
            ]
            if non_pricing:
                logger.info(
                    f"Category filter: excluded {len(candidates) - len(non_pricing)} pricing candidates "
                    f"(labels={query_profile.labels & CATEGORY_LABELS})"
                )
                candidates = non_pricing

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

        # Step 4: Source governance + recovery + source diversity
        final_docs, gov_meta, gov_ms, recovery_ms = self._apply_governance_with_recovery(
            query=query,
            docs=final_docs,
            original_candidates=candidates,
            query_profile=query_profile,
        )

        total_retrieval_ms = (time.perf_counter() - t_total) * 1000
        telemetry.emit(
            "ranking_completed",
            question=query,
            route=sorted(query_profile.labels),
            candidate_count=len(candidates),
            rerank_count=len(final_docs),
        )
        telemetry.emit(
            "retrieval_completed",
            question=query,
            route=sorted(query_profile.labels),
            source_count=len(final_docs),
            suppressed_count=gov_meta.get("suppressed_count", 0),
            governance_removed_count=gov_meta.get("governance_removed_count", 0),
            suppression_ratio=gov_meta.get("suppression_ratio", 0.0),
            recovery_triggered=gov_meta.get("recovery_pass_used", False),
            recovery_added_count=gov_meta.get("recovery_result_count", 0),
            recovery_pass_latency_ms=gov_meta.get("recovery_pass_latency_ms", 0.0),
            diversity_score=gov_meta.get("diversity_score", 0.0),
            retrieval_collapse_detected=gov_meta.get("retrieval_collapse_detected", False),
            resilience_strategy=gov_meta.get("resilience_strategy"),
            final_source_count=len(final_docs),
        )
        if gov_meta.get("retrieval_collapse_detected"):
            telemetry.emit(
                "degradation_triggered",
                question=query,
                route=sorted(query_profile.labels),
                strategy=gov_meta.get("resilience_strategy"),
                source_count=len(final_docs),
                suppressed_count=gov_meta.get("suppressed_count", 0),
            )
        logger.info(
            f"⏱ Retrieval celkem: {total_retrieval_ms:.0f}ms "
            f"(hybrid={hybrid_ms:.0f}ms, rerank={rerank_ms:.0f}ms, "
            f"governance={gov_ms:.0f}ms, recovery={recovery_ms:.0f}ms) "
            f"→ {len(final_docs)} výsledků "
            f"(governance_suppressed={gov_meta.get('suppressed_count', 0)}, "
            f"recovery_pass_used={gov_meta.get('recovery_pass_used', False)}, "
            f"diversity_score={gov_meta.get('diversity_score', 0.0)})"
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
