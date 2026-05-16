"""
Hlavní Retriever – orchestruje celou retrieval pipeline.

Pipeline:
  1. Hybridní vyhledávání (BM25 + Qdrant → RRF)
  2. Reranking (BGE cross-encoder)

Implementuje LangChain BaseRetriever pro snadnou integraci
do libovolného RAG chainu.
"""

from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

import config
from src.retrieval.hybrid import hybrid_search
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
        logger.debug(f"Retrieval pro dotaz: '{query[:60]}…'")

        # Krok 1: Hybridní pre-filtr
        candidates = hybrid_search(
            query=query,
            top_k=self.hybrid_top_k,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
        )

        if not candidates:
            logger.warning("Hybrid search nevrátil žádné výsledky")
            return []

        # Krok 2: Reranking cross-encoderem
        final_docs = rerank(
            query=query,
            documents=candidates,
            top_k=self.rerank_top_k,
        )

        logger.info(
            f"Retrieval: {len(candidates)} kandidátů → "
            f"{len(final_docs)} po rerankingu"
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
