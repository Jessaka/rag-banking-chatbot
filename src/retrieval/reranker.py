"""
Reranking pomocí NVIDIA NIM API (primární) nebo CrossEncoder CPU (fallback).

Primární: NVIDIA NIM llama-nemotron-rerank-vl-1b-v2
  - Cloud inference, žádný lokální GPU potřeba
  - ~200-400ms na batch 10 kandidátů

Fallback: BAAI/bge-reranker-v2-m3 CrossEncoder (CPU)
  - Aktivuje se pokud NVIDIA_API_KEY není nastaven nebo API selže
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache

from langchain_core.documents import Document

import config
from src.retrieval.query_classifier import QueryProfile, classify_query
from src.utils.logger import get_logger

logger = get_logger(__name__)

_NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
_NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking"
_NVIDIA_MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2"

_RERANK_CANDIDATES_CAP = 10


# ---------------------------------------------------------------------------
# NVIDIA NIM reranker
# ---------------------------------------------------------------------------

def _nvidia_rerank_scores(query: str, doc_contents: tuple[str, ...]) -> list[float] | None:
    """Zavolá NVIDIA NIM reranking API. Vrátí None pokud API selže."""
    if not _NVIDIA_API_KEY:
        return None
    payload = json.dumps({
        "model": _NVIDIA_MODEL,
        "query": {"text": query},
        "passages": [{"text": t} for t in doc_contents],
    }).encode()
    req = urllib.request.Request(
        _NVIDIA_RERANK_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {_NVIDIA_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        # Odpověď: {"rankings": [{"index": 0, "logit": 3.14}, ...]}
        rankings = data.get("rankings", [])
        scores_by_idx = {r["index"]: r["logit"] for r in rankings}
        return [scores_by_idx.get(i, -99.0) for i in range(len(doc_contents))]
    except Exception as exc:
        logger.warning(f"NVIDIA NIM reranker selhal: {exc!s:.120} — přepínám na CrossEncoder")
        return None


# ---------------------------------------------------------------------------
# CrossEncoder CPU fallback
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_reranker():
    """Načte CrossEncoder model (singleton, fallback)."""
    logger.info("Importuji sentence_transformers.CrossEncoder")
    t_import = time.perf_counter()
    from sentence_transformers import CrossEncoder
    logger.info(f"import_timing.sentence_transformers.CrossEncoder ms={(time.perf_counter() - t_import) * 1000:.1f}")
    logger.info(f"Načítám reranker: {config.RERANKER_MODEL}")
    t_model = time.perf_counter()
    model = CrossEncoder(config.RERANKER_MODEL, device=config.RERANKER_DEVICE, max_length=256)
    logger.info(f"Reranker připraven model_load_ms={(time.perf_counter() - t_model) * 1000:.1f}")
    return model


@lru_cache(maxsize=512)
def _cached_crossencoder_predict(query: str, doc_contents: tuple[str, ...]) -> tuple[float, ...]:
    model = _load_reranker()
    pairs = [(query, content) for content in doc_contents]
    return tuple(model.predict(pairs, batch_size=32).tolist())


# ---------------------------------------------------------------------------
# Unified rerank
# ---------------------------------------------------------------------------

def rerank(
    query: str,
    documents: list[Document],
    top_k: int = config.RERANK_TOP_K,
    min_score: float = config.RERANK_MIN_SCORE,
    query_profile: QueryProfile | None = None,
) -> list[Document]:
    """
    Přeřadí dokumenty podle relevance (NVIDIA NIM, fallback CrossEncoder).

    Args:
        query:     Uživatelský dotaz.
        documents: Kandidáti z hybridního vyhledávání.
        top_k:     Počet finálních výsledků.
        min_score: Minimální skóre pro zachování dokumentu.

    Returns:
        Dokumenty seřazené sestupně (max top_k), splňující min_score.
    """
    if not documents:
        return []
    query_profile = query_profile or classify_query(query)
    min_score = max(min_score, query_profile.rerank_min_score)

    candidates = documents[:_RERANK_CANDIDATES_CAP]
    doc_contents = tuple(doc.page_content for doc in candidates)

    t0 = time.perf_counter()
    backend = "nvidia_nim"
    scores = _nvidia_rerank_scores(query, doc_contents)
    if scores is None:
        backend = "crossencoder_cpu"
        scores = list(_cached_crossencoder_predict(query, doc_contents))
    rerank_ms = (time.perf_counter() - t0) * 1000

    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)

    results = []
    for doc, score in ranked[:top_k]:
        if score < min_score:
            break
        results.append(Document(
            page_content=doc.page_content,
            metadata={**doc.metadata, "rerank_score": round(score, 4), "rerank_backend": backend},
        ))

    if not results and ranked:
        logger.warning(
            f"Všechny rerank skóre pod prahem {min_score:.4f} "
            f"(nejlepší: {ranked[0][1]:.4f}). Nevracím žádný dokument."
        )

    logger.info(
        f"⏱ Reranking [{backend}]: {rerank_ms:.0f}ms "
        f"({len(candidates)} párů → {len(results)} výsledků, "
        f"threshold: {min_score:.4f}, top score: {ranked[0][1]:.4f})"
        if ranked else f"⏱ Reranking [{backend}]: 0 výsledků"
    )
    return results
