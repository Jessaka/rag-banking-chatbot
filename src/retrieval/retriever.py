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
