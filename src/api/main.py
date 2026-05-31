"""
FastAPI REST API pro Raiffeisenbank RAG chatbot.

Endpointy:
  POST /chat        – hlavní chatbot endpoint s konverzační pamětí
  GET  /health      – stav Qdrant, Ollama a BM25 indexu
  GET  /collections – detailní info o Qdrant kolekci

Session management:
  – Každé sezení (UUID) má vlastní BankingRAGChain instanci s historií
  – asyncio.Lock per session zabraňuje race condition při souběžných requestech
  – Automatické mazání neaktivních sezení po SESSION_TTL_SECONDS
  – Maximálně MAX_SESSIONS simultánních sezení (LRU eviction)

Synchronní operace (chain.ask, Qdrant, Ollama) běží v thread pool executoru
přes asyncio.to_thread(), čímž neblokují event loop FastAPI.
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
from pathlib import Path
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

import requests as http_requests
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

import config
from src.generation.cache import ResponseCache, _cache_key, _is_cacheable, _normalize_for_cache
from src.generation.chain import BankingRAGChain
from src.generation.confidence_semantics import resolve_confidence_semantics
from src.storage.session_store import DistributedSessionStore
from src.storage.response_cache import DistributedResponseCache
from src.utils.logger import get_logger
from src.utils.telemetry import telemetry

logger = get_logger(__name__)


def _startup_log(step: str, event: str, **extra: Any) -> None:
    """Timestamped startup diagnostics; no user data included."""
    parts = [f"startup.{step}.{event}", f"ts={datetime.now(UTC).isoformat(timespec='seconds')}"]
    for key, value in extra.items():
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))


def _startup_check(name: str, fn: Any) -> ComponentStatus:
    """Run one blocking startup check with begin/end diagnostics."""
    t0 = time.perf_counter()
    _startup_log(name, "begin")
    try:
        result = fn()
        _startup_log(name, "end", status=result.status, ms=round((time.perf_counter() - t0) * 1000, 1))
        return result
    except Exception as exc:
        _startup_log(name, "error", ms=round((time.perf_counter() - t0) * 1000, 1), error=type(exc).__name__)
        return ComponentStatus(status="error", detail=str(exc))


async def _startup_check_with_timeout(name: str, fn: Any, timeout_seconds: float) -> ComponentStatus:
    """Bound a blocking startup health check so FastAPI can become ready."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_startup_check, name, fn),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        _startup_log(name, "timeout", timeout_seconds=timeout_seconds)
        return ComponentStatus(
            status="degraded",
            detail=f"Startup health check timeout after {timeout_seconds:.1f}s",
        )


async def _check_redis_startup(timeout_seconds: float) -> ComponentStatus:
    """Bounded Redis ping during startup diagnostics."""
    _startup_log("redis_init", "begin", enabled=config.REDIS_ENABLED)
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis

        if getattr(config, "REDIS_URL", ""):
            client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
        else:
            client = aioredis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD or None,
                db=config.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=config.REDIS_TIMEOUT,
            )
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout_seconds)
        finally:
            await client.aclose()
        _startup_log("redis_init", "end", ms=round((time.perf_counter() - t0) * 1000, 1))
        return ComponentStatus(status="ok", detail="Redis ping OK")
    except TimeoutError:
        _startup_log("redis_init", "timeout", timeout_seconds=timeout_seconds)
        return ComponentStatus(status="degraded", detail=f"Redis ping timeout after {timeout_seconds:.1f}s")
    except Exception as exc:
        _startup_log("redis_init", "error", error=type(exc).__name__)
        return ComponentStatus(status="degraded", detail=f"Redis unavailable: {exc}")

# ---------------------------------------------------------------------------
# Session management – konfigurace
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS: int = 3600   # Sezení expiruje po 1 hodině nečinnosti
MAX_SESSIONS: int = 50            # Limit pro LRU eviction

# Priority 1: Distributed response cache with governed keys, compression, and metrics
_startup_log("cache_init", "begin", cls="DistributedResponseCache")
_distributed_cache: DistributedResponseCache = DistributedResponseCache(
    key_prefix="rag:cache",
)
_startup_log("cache_init", "end", cls="DistributedResponseCache")

# Priority 1: Legacy response cache with in-flight dedup (uses in-memory backend)
_startup_log("legacy_cache_init", "begin", cls="ResponseCache")
_response_cache: ResponseCache = ResponseCache(
    backend=None,  # defaults to InMemoryCacheBackend
    max_entries=config.CACHE_MAX_ENTRIES,
)
_startup_log("legacy_cache_init", "end", cls="ResponseCache")


def _enrich_result_with_semantics(result: dict) -> dict:
    """Add confidence semantics fields to any result dict.

    Safe to call on all results — no-ops if already enriched by chain.py.
    This ensures every API response includes confidence_origin,
    confidence_semantic_label, and degraded_answer even from early returns.
    """
    if "confidence_origin" in result:
        return result
    strategy = result.get("answer_strategy", "generic_llm")
    bucket = result.get("confidence_bucket")
    reason = result.get("confidence_reason", "")
    cs = resolve_confidence_semantics(strategy, bucket=bucket, reason=reason)
    result["confidence_origin"] = cs.origin
    result["confidence_origin_label"] = cs.origin_label
    result["confidence_semantic_label"] = cs.semantic_label
    result["degraded_answer"] = cs.degraded
    return result


# Priority 1: Distributed session store — Redis-backed with graceful fallback to in-memory
_startup_log("session_store_init", "begin", cls="DistributedSessionStore")
_session_store: DistributedSessionStore = DistributedSessionStore(
    default_ttl=config.REDIS_SESSION_TTL,
    key_prefix=config.REDIS_KEY_PREFIX + "session:",
)
_startup_log("session_store_init", "end", cls="DistributedSessionStore")

# Legacy backend reference for cleanup compatibility
_session_backend: Any = _session_store

# Export backends for debug metadata
_api_backends: dict[str, str] = {
    "cache_backend": "DistributedResponseCache",
    "session_backend": "DistributedSessionStore",
    "redis_available": str(config.REDIS_ENABLED or config.USE_REDIS_CACHE or config.USE_REDIS_SESSIONS),
}

# session_id → (chain, last_access_timestamp)
_sessions: dict[str, tuple[BankingRAGChain, float]] = {}

# Per-session asyncio locky zabraňují souběžnému mutování chat_history
# ve stejném sezení při paralelních requestech.
_session_locks: dict[str, asyncio.Lock] = {}


_SESSION_STATE_FIELDS = (
    "resolved_product",
    "resolved_intent",
    "last_canonical_product",
    "unresolved_product",
    "unresolved_product_type",
    "pending_clarification",
    "clarification_candidates",
    "current_domain",
    "current_intent",
    "current_product",
)


def _mask_session_id(session_id: str) -> str:
    return f"{session_id[:8]}…" if session_id else "none"


def _serialize_chat_history(chain: BankingRAGChain) -> list[dict[str, str]]:
    """Serialize LangChain messages for Redis session persistence."""
    out: list[dict[str, str]] = []
    for msg in getattr(chain, "chat_history", []) or []:
        role = "assistant" if isinstance(msg, AIMessage) else "user" if isinstance(msg, HumanMessage) else "message"
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str):
            out.append({"role": role, "content": content})
    return out


def _restore_chat_history(chain: BankingRAGChain, rows: Any) -> None:
    """Restore Redis-serialized chat history into LangChain messages."""
    if not isinstance(rows, list):
        return
    restored = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = row.get("content") or ""
        if not isinstance(content, str) or not content:
            continue
        if row.get("role") == "assistant":
            restored.append(AIMessage(content=content))
        elif row.get("role") == "user":
            restored.append(HumanMessage(content=content))
    if restored:
        chain.chat_history = restored[-(config.CONVERSATION_HISTORY_LIMIT * 2):]


def _collect_chain_session_state(chain: BankingRAGChain) -> dict[str, Any]:
    """Collect serializable conversational state for Redis."""
    session_state: dict[str, Any] = {}
    for field in _SESSION_STATE_FIELDS:
        val = getattr(chain, field, None)
        if val is not None:
            session_state[field] = val
    if hasattr(chain, "session_context") and isinstance(chain.session_context, dict):
        session_state["session_context"] = chain.session_context
    history = _serialize_chat_history(chain)
    if history:
        session_state["chat_history"] = history
    return session_state


def _restore_chain_session_state(chain: BankingRAGChain, state: dict[str, Any]) -> None:
    """Restore Redis session state into a fresh BankingRAGChain."""
    for field in _SESSION_STATE_FIELDS:
        if field in state:
            setattr(chain, field, state.get(field))
    if isinstance(state.get("session_context"), dict):
        chain.session_context.update(state["session_context"])
    _restore_chat_history(chain, state.get("chat_history"))


# ---------------------------------------------------------------------------
# Pydantic modely – request / response
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Bankovní dotaz v češtině.",
        examples=["Jaký je poplatek za vedení běžného účtu?"],
    )
    session_id: str | None = Field(
        None,
        description="UUID sezení pro konverzační paměť. Pokud chybí, vygeneruje se nové.",
    )


class SourceDocument(BaseModel):
    file_name: str = Field(description="Název zdrojového souboru (PDF nebo FAQ text).")
    page: int | None = Field(None, description="Číslo stránky v PDF.")
    chunk_id: str | None = Field(None, description="Unikátní hex ID chunku v indexu.")
    rerank_score: float | None = Field(None, description="Relevance skóre cross-encoder rerankeru.")
    preview: str = Field(description="Prvních 300 znaků textu chunku.")

    # Priority 2: Source UX metadata
    human_title: str | None = Field(None, description="Human-readable source title for UI display.")
    display_url: str | None = Field(None, description="Shortened display URL.")
    source_year: int | None = Field(None, description="Extracted document year.")
    current_or_archived: str | None = Field(None, description="Badge label: Aktuální | Archivní | FAQ | Ceník …")
    source_category: str | None = Field(None, description="Classification: product_page | faq_support | pricing | legal | archived | unknown.")
    source_label: str | None = Field(None, description="Short UX label: Produktová stránka | FAQ / Návod | Ceník …")
    # Priority 3: Retrieval observability
    why_this_source: str | None = Field(None, description="Human-readable explanation of why this source was selected.")
    # Priority 5: Source UX refinement
    source_context_label: str | None = Field(None, description="Contextual label (e.g. 'Položka: Poplatek za vedení').")
    source_relevance_reason: str | None = Field(None, description="Why this source is relevant to the query.")

    # Priority 2b: Source trust scoring
    trust_score: float | None = Field(None, description="Overall trust score 0-1 combining authority, recency, stability.")
    authority_weight: float | None = Field(None, description="Document authority component (0-1).")
    recency_weight: float | None = Field(None, description="Document recency component (0-1).")
    stability_weight: float | None = Field(None, description="Document stability component (0-1).")
    authority_tier: str | None = Field(None, description="Authority tier classification (product_page, faq_support_page, current_pricing, etc.).")

    # Priority 1b: Source freshness governance
    source_freshness_bucket: str | None = Field(None, description="Freshness classification: current | recent | stale | archived.")
    freshness_priority_score: float | None = Field(None, description="Freshness priority score 0-1 for ranking.")
    stale_source_suppressed: bool | None = Field(None, description="Whether source was suppressed due to staleness.")
    effective_date: str | None = Field(None, description="Extracted effective date of the document.")
    valid_from: str | None = Field(None, description="Valid-from date if available.")
    valid_to: str | None = Field(None, description="Valid-to date if available.")
    freshness_reason: str | None = Field(None, description="Human-readable freshness explanation.")

    # Priority 4: Retrieval explainability
    retrieval_reason: str | None = Field(None, description="Why the source was retrieved.")
    authority_reason: str | None = Field(None, description="Why the authority level was assigned.")


class ChatResponse(BaseModel):
    answer: str = Field(description="Vygenerovaná odpověď v češtině.")
    sources: list[SourceDocument] = Field(description="Zdrojové chunky použité pro odpověď.")
    session_id: str = Field(description="UUID sezení – použijte ho v příštím požadavku.")
    processing_time_ms: float = Field(description="Celková latence (retrieval + LLM) v ms.")
    request_id: str | None = Field(None, description="Correlation ID requestu pro logy/eval debugging.")
    answer_strategy: str | None = Field(None, description="Strategie odpovědi/debug informace.")
    error: str | None = Field(None, description="Chybová zpráva pouze v debug/error odpovědích.")
    traceback: str | None = Field(None, description="Traceback pouze pokud DEBUG_API_ERRORS=true.")
    retrieval_debug: Any | None = Field(None, description="Debug retrievalu pouze pro eval/debug odpovědi.")
    confidence_bucket: str | None = Field(None, description="UX confidence bucket: high | medium | low.")
    confidence_reason: str | None = Field(None, description="Stručné vysvětlení confidence pro UX/eval.")
    clarification_required: bool | None = Field(None, description="Zda je vhodné vyžádat upřesnění.")
    unsupported_reason: str | None = Field(None, description="Důvod bezpečného unsupported fallbacku.")

    # Priority 1: Backend metadata
    cache_backend: str | None = Field(None, description="Active cache backend (in_memory | redis).")
    session_backend: str | None = Field(None, description="Active session backend (in_memory | redis).")
    redis_available: bool | None = Field(None, description="Whether Redis is connected and available.")

    # Priority 5: Latency observability
    cache_check_ms: float | None = Field(None, description="Cache lookup latency in ms.")
    retrieval_latency_ms: float | None = Field(None, description="Retrieval (hybrid search) latency in ms.")
    llm_latency_ms: float | None = Field(None, description="LLM generation latency in ms.")
    formatting_latency_ms: float | None = Field(None, description="Response formatting latency in ms.")

    # Priority 2: Confidence semantics
    confidence_origin: str | None = Field(None, description="Origin of confidence assessment (pricing_row, procedural, overview_fallback, etc.).")
    confidence_origin_label: str | None = Field(None, description="Human-readable confidence origin label.")
    confidence_semantic_label: str | None = Field(None, description="Frontend semantic label: Ověřeno ve zdrojích RB | Doporučená odpověď | Vyžaduje ověření.")
    degraded_answer: bool | None = Field(None, description="Whether the answer is a fallback/degraded response.")


class ComponentStatus(BaseModel):
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    active_provider: str | None = Field(None, description="Active LLM provider (e.g., openai, ollama).")
    active_model: str | None = Field(None, description="Primary model in use.")
    fallback_model: str | None = Field(None, description="Fallback model if primary fails.")
    status: Literal["ok", "degraded", "error"] = Field(
        description="Celkový stav: ok | degraded (část komponent nefunguje) | error."
    )
    qdrant: ComponentStatus
    ollama: ComponentStatus = Field(
        description="Stav Ollama – kontroluje jen modely potřebné pro aktivní LLM/embedding backend."
    )
    bm25_index: ComponentStatus
    anthropic: ComponentStatus | None = Field(
        None,
        description="Stav Anthropic API – přítomno pouze pokud LLM_BACKEND='anthropic'.",
    )
    gemini: ComponentStatus | None = Field(
        None,
        description="Stav Google Gemini API – přítomno pouze pokud LLM_BACKEND='gemini'.",
    )
    openai: ComponentStatus | None = Field(
        None,
        description="Stav OpenAI API – přítomno pouze pokud LLM_BACKEND='openai'.",
    )


class CollectionInfo(BaseModel):
    name: str = Field(description="Název Qdrant kolekce.")
    points_count: int = Field(description="Celkový počet bodů (chunků) v kolekci.")
    indexed_vectors_count: int = Field(description="Počet plně indexovaných vektorů.")
    status: str = Field(description="Stav kolekce: green | yellow | grey.")
    vector_size: int = Field(description="Dimenze embeddingů podle backendu: Ollama 768, OpenAI text-embedding-3-small 1536.")
    distance_metric: str = Field(description="Metrika vzdálenosti: Cosine | Dot | Euclid.")


# ---------------------------------------------------------------------------
# Session management – implementace
# ---------------------------------------------------------------------------

def _cleanup_stale_sessions() -> None:
    """Odstraní sezení neaktivní déle než SESSION_TTL_SECONDS.

    Uses the distributed session store for TTL tracking.
    Chain objects (non-serializable) are kept in `_sessions` dict.
    """
    # Session store handles TTL for metadata tracking
    removed = _session_store.stats.get("emergency_fallback_count", 0)

    # Also clean up in-memory chain objects for expired sessions
    cutoff = time.monotonic() - SESSION_TTL_SECONDS
    stale = [sid for sid, (_, ts) in _sessions.items() if ts < cutoff]
    for sid in stale:
        _sessions.pop(sid, None)
        _session_locks.pop(sid, None)
    if stale:
        logger.info(f"Session cleanup: {len(stale)} chain(s) expired (TTL={SESSION_TTL_SECONDS}s)")


def _evict_oldest_session() -> None:
    """LRU eviction: smaže sezení s nejstarším přístupem."""
    if not _sessions:
        return
    oldest = min(_sessions, key=lambda k: _sessions[k][1])
    _sessions.pop(oldest, None)
    _session_locks.pop(oldest, None)
    asyncio.create_task(_session_store.delete(oldest))
    logger.warning(f"LRU eviction sezení {oldest[:8]}… (limit {MAX_SESSIONS})")


async def _get_or_create_session(
    session_id: str | None,
) -> tuple[str, BankingRAGChain, asyncio.Lock]:
    """
    Vrátí existující nebo vytvoří nové sezení.

    Volána v async kontextu; samotný dict přístup je bezpečný
    (GIL + single event-loop thread pro dict operace).

    Returns:
        (session_id, chain, per-session lock)
    """
    _cleanup_stale_sessions()

    # Nové sezení nebo neznámé session_id
    if not session_id or session_id not in _sessions:
        if not session_id:
            session_id = str(uuid.uuid4())

        if len(_sessions) >= MAX_SESSIONS:
            _evict_oldest_session()

        chain = BankingRAGChain(conversational=True)

        # Restore persisted Redis state after backend restart.
        # Hard timeout prevents startup/request hangs if Redis stalls.
        if session_id:
            try:
                logger.debug(f"Session load start sid={_mask_session_id(session_id)}")
                persisted = await asyncio.wait_for(_session_store.load(session_id), timeout=3.0)
                logger.debug(
                    f"Session load done sid={_mask_session_id(session_id)} found={bool(persisted)}"
                )
                if persisted:
                    _restore_chain_session_state(chain, persisted)
                    logger.info(
                        f"Session restored from Redis sid={_mask_session_id(session_id)} "
                        f"fields={sorted(k for k in persisted.keys() if not k.startswith('_'))}"
                    )
            except asyncio.TimeoutError:
                logger.warning(f"Session load timeout sid={_mask_session_id(session_id)}")
            except Exception as exc:
                logger.warning(f"Session load failed sid={_mask_session_id(session_id)} error={exc}")

        _sessions[session_id] = (chain, time.monotonic())
        _session_locks[session_id] = asyncio.Lock()

        # Register/touch in distributed session store (bounded; no fire-and-forget leak)
        try:
            logger.debug(f"Session save start sid={_mask_session_id(session_id)} reason=create")
            await asyncio.wait_for(
                _session_store.save(
                    session_id,
                    _collect_chain_session_state(chain) or {"created_at": time.time()},
                    ttl_seconds=SESSION_TTL_SECONDS,
                ),
                timeout=3.0,
            )
            logger.debug(f"Session save done sid={_mask_session_id(session_id)} reason=create")
        except asyncio.TimeoutError:
            logger.warning(f"Session save timeout sid={_mask_session_id(session_id)} reason=create")
        except Exception as exc:
            logger.warning(f"Session save failed sid={_mask_session_id(session_id)} reason=create error={exc}")
        logger.info(f"Nové sezení: {session_id[:8]}… (aktivních: {len(_sessions)})")
    else:
        # Obnov timestamp přístupu
        chain, _ = _sessions[session_id]
        _sessions[session_id] = (chain, time.monotonic())

        # Touch TTL with bounded save of current state.
        try:
            logger.debug(f"Session save start sid={_mask_session_id(session_id)} reason=touch")
            await asyncio.wait_for(
                _session_store.save(
                    session_id,
                    _collect_chain_session_state(chain) or {"created_at": time.time()},
                    ttl_seconds=SESSION_TTL_SECONDS,
                ),
                timeout=3.0,
            )
            logger.debug(f"Session save done sid={_mask_session_id(session_id)} reason=touch")
        except asyncio.TimeoutError:
            logger.warning(f"Session touch timeout sid={_mask_session_id(session_id)}")
        except Exception as exc:
            logger.warning(f"Session touch failed sid={_mask_session_id(session_id)} error={exc}")

    return session_id, _sessions[session_id][0], _session_locks[session_id]


def _serialize_sources(raw_sources: list[Any]) -> list[SourceDocument]:
    sources: list[SourceDocument] = []
    for doc in raw_sources:
        if isinstance(doc, dict):
            metadata = doc.get("metadata", doc)
            page_content = doc.get("page_content", "")
        else:
            metadata = getattr(doc, "metadata", {}) or {}
            page_content = getattr(doc, "page_content", "")

        file_name = metadata.get("file_name") or metadata.get("source_file") or metadata.get("title") or "neznámý"
        rerank_score = metadata.get("rerank_score")
        sources.append(
            SourceDocument(
                file_name=file_name,
                page=metadata.get("page"),
                chunk_id=metadata.get("chunk_id"),
                rerank_score=round(rerank_score, 4) if rerank_score is not None else None,
                preview=page_content[:500],
                # Priority 2: Source UX metadata
                human_title=metadata.get("human_title"),
                display_url=metadata.get("display_url"),
                source_year=metadata.get("source_year"),
                current_or_archived=metadata.get("current_or_archived"),
                source_category=metadata.get("source_category"),
                source_label=metadata.get("source_label"),
                # Priority 3: Retrieval observability
                why_this_source=metadata.get("why_this_source"),
                # Priority 5: Source UX refinement
                source_context_label=metadata.get("source_context_label"),
                source_relevance_reason=metadata.get("source_relevance_reason"),
                # Priority 2b: Source trust scoring
                trust_score=metadata.get("trust_score"),
                authority_weight=metadata.get("authority_weight"),
                recency_weight=metadata.get("recency_weight"),
                stability_weight=metadata.get("stability_weight"),
                authority_tier=metadata.get("authority_tier"),
                # Priority 1b: Source freshness governance
                source_freshness_bucket=metadata.get("source_freshness_bucket"),
                freshness_priority_score=metadata.get("freshness_priority_score"),
                stale_source_suppressed=metadata.get("stale_source_suppressed"),
                effective_date=metadata.get("effective_date"),
                valid_from=metadata.get("valid_from"),
                valid_to=metadata.get("valid_to"),
                freshness_reason=metadata.get("freshness_reason"),
                # Priority 4: Retrieval explainability
                retrieval_reason=metadata.get("retrieval_reason"),
                authority_reason=metadata.get("authority_reason"),
            )
        )
    return sources


def _source_debug(raw_sources: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in raw_sources[:5]:
        if isinstance(doc, dict):
            metadata = doc.get("metadata", doc)
            page_content = doc.get("page_content", "")
        else:
            metadata = getattr(doc, "metadata", {}) or {}
            page_content = getattr(doc, "page_content", "")
        out.append({
            "metadata": metadata,
            "preview": page_content[:500],
        })
    return out


def _write_error_log(payload: dict[str, Any]) -> None:
    try:
        config.ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with config.ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as log_exc:
        logger.error(f"Nelze zapsat error log: {log_exc}")


def _internal_error_response(
    *,
    request_id: str,
    session_id: str,
    question: str,
    exc: Exception,
    elapsed_ms: float,
    partial_result: dict[str, Any] | None = None,
) -> JSONResponse:
    tb = traceback.format_exc()
    partial_result = partial_result or {}
    raw_sources = partial_result.get("sources", []) or []
    retrieval_debug = partial_result.get("retrieval_debug", []) or []
    answer_strategy = partial_result.get("answer_strategy") or "internal_error"
    payload_for_log = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "request_id": request_id,
        "session_id": session_id,
        "query": question,
        "error": str(exc),
        "traceback": tb,
        "answer_strategy": answer_strategy,
        "retrieval_debug": retrieval_debug,
        "sources": _source_debug(raw_sources),
        "pricing_retriever_result": partial_result.get("pricing_retriever_result"),
        "hybrid_candidates": partial_result.get("hybrid_candidates"),
    }
    _write_error_log(payload_for_log)

    content = {
        "answer": "Došlo k interní chybě při zpracování dotazu.",
        "error": str(exc),
        "traceback": tb if config.DEBUG_API_ERRORS else None,
        "answer_strategy": "internal_error",
        "retrieval_debug": retrieval_debug if config.DEBUG_API_ERRORS else None,
        "sources": [s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in _serialize_sources(raw_sources)] if config.DEBUG_API_ERRORS else [],
        "request_id": request_id,
        "session_id": session_id,
        "processing_time_ms": round(elapsed_ms, 1),
        "pricing_retriever_result": partial_result.get("pricing_retriever_result") if config.DEBUG_API_ERRORS else None,
        "hybrid_candidates": partial_result.get("hybrid_candidates") if config.DEBUG_API_ERRORS else None,
    }
    return JSONResponse(status_code=500, content=content)


# ---------------------------------------------------------------------------
# Health check – pomocné funkce (synchronní, volají se přes to_thread)
# ---------------------------------------------------------------------------

def _check_qdrant() -> ComponentStatus:
    """Zkontroluje dostupnost Qdrant a existenci kolekce."""
    _startup_log("vector_store_init", "begin", component="qdrant")
    from qdrant_client import QdrantClient

    try:
        client = QdrantClient(
            host=config.QDRANT_HOST,
            port=config.QDRANT_PORT,
            timeout=5,
        )
        names = {c.name for c in client.get_collections().collections}
        if config.QDRANT_COLLECTION not in names:
            return ComponentStatus(
                status="degraded",
                detail=(
                    f"Kolekce '{config.QDRANT_COLLECTION}' neexistuje. "
                    "Spusťte: python scripts/ingest.py"
                ),
            )
        info = client.get_collection(config.QDRANT_COLLECTION)
        _startup_log("vector_store_init", "end", component="qdrant")
        return ComponentStatus(
            status="ok",
            detail=(
                f"'{config.QDRANT_COLLECTION}': "
                f"{info.points_count or 0} bodů, "
                f"stav: {info.status}"
            ),
        )
    except Exception as exc:
        _startup_log("vector_store_init", "error", component="qdrant", error=type(exc).__name__)
        return ComponentStatus(status="error", detail=str(exc))


def _check_ollama() -> ComponentStatus:
    """
    Zkontroluje Ollama modely potřebné pro aktivní konfiguraci:
      - embedding model pouze pokud EMBEDDING_BACKEND == 'ollama'
      - LLM model pouze pokud LLM_BACKEND == 'ollama'
    """
    try:
        resp = http_requests.get(
            f"{config.OLLAMA_BASE_URL}/api/tags",
            timeout=5,
        )
        resp.raise_for_status()
        available = [m["name"] for m in resp.json().get("models", [])]

        def _model_present(name: str) -> bool:
            return any(tag == name or tag.startswith(f"{name}:") for tag in available)

        required = []
        if config.EMBEDDING_BACKEND == "ollama":
            required.append(config.EMBED_MODEL)
        if config.LLM_BACKEND == "ollama":
            required.append(config.LLM_MODEL)

        if not required:
            return ComponentStatus(status="ok", detail="Ollama není potřeba pro aktivní LLM/embedding backend")

        missing = [m for m in required if not _model_present(m)]
        if missing:
            return ComponentStatus(
                status="degraded",
                detail=(
                    f"Chybí modely: {missing}. "
                    f"Spusťte: ollama pull {' '.join(missing)}"
                ),
            )

        scope_parts = []
        if config.LLM_BACKEND == "ollama":
            scope_parts.append("LLM")
        if config.EMBEDDING_BACKEND == "ollama":
            scope_parts.append("embeddings")
        scope = " + ".join(scope_parts)
        return ComponentStatus(
            status="ok",
            detail=f"{scope} OK: {available}",
        )
    except Exception as exc:
        return ComponentStatus(status="error", detail=str(exc))


def _check_anthropic() -> ComponentStatus:
    """
    Ověří Anthropic API – jen pokud LLM_BACKEND == 'anthropic'.

    Pošle minimální test request (count_tokens) aby ověřil klíč
    bez zbytečných nákladů na generování.
    """
    if not config.ANTHROPIC_API_KEY:
        return ComponentStatus(
            status="error",
            detail="ANTHROPIC_API_KEY není nastavený v .env",
        )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        # count_tokens je levný způsob ověření API klíče
        result = client.messages.count_tokens(
            model=config.ANTHROPIC_MODEL,
            messages=[{"role": "user", "content": "test"}],
        )
        return ComponentStatus(
            status="ok",
            detail=f"Model {config.ANTHROPIC_MODEL} dostupný ({result.input_tokens} tokenů/test)",
        )
    except Exception as exc:
        return ComponentStatus(status="error", detail=str(exc))


def _check_bm25() -> ComponentStatus:
    """Zkontroluje existenci BM25 pickle souborů na disku."""
    missing = [
        p.name
        for p in (config.BM25_INDEX_PATH, config.DOCS_STORE_PATH)
        if not p.exists()
    ]
    if missing:
        return ComponentStatus(
            status="error",
            detail=(
                f"Chybí soubory: {missing}. "
                "Spusťte: python scripts/ingest.py"
            ),
        )
    size_mb = config.BM25_INDEX_PATH.stat().st_size / (1024 * 1024)
    return ComponentStatus(
        status="ok",
        detail=f"{config.BM25_INDEX_PATH.name} ({size_mb:.1f} MB)",
    )


def _check_gemini() -> ComponentStatus:
    """
    Ověří Google Gemini API – jen pokud LLM_BACKEND == 'gemini'.

    Postup:
      1. Zavolá discover_gemini_model() → zjistí nejlepší dostupný model
      2. Ověří ho přes count_tokens (levné, bez generování tokenů)
    """
    if not config.GEMINI_API_KEY:
        return ComponentStatus(
            status="error",
            detail="GEMINI_API_KEY není nastavený v .env",
        )
    try:
        from google import genai
        from src.generation.chain import discover_gemini_model

        client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Auto-discovery: najdeme nejlepší dostupný model
        model_name = (
            discover_gemini_model(config.GEMINI_API_KEY)
            if config.GEMINI_MODEL == "gemini-2.0-flash"
            else config.GEMINI_MODEL
        )

        result = client.models.count_tokens(
            model=model_name,
            contents="test",
        )
        return ComponentStatus(
            status="ok",
            detail=f"Model '{model_name}' dostupný ({result.total_tokens} tokenů/test)",
        )
    except Exception as exc:
        return ComponentStatus(status="error", detail=str(exc))


def _check_openai() -> ComponentStatus:
    """
    Ověří OpenAI API – jen pokud LLM_BACKEND == 'openai'.

    Použije models.list() k ověření API klíče (levné, bez generování).
    """
    if not config.OPENAI_API_KEY:
        return ComponentStatus(
            status="error",
            detail="OPENAI_API_KEY není nastavený v .env",
        )
    try:
        _startup_log("openai_init", "begin", model=config.OPENAI_CHAT_MODEL)
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=10)
        # models.list() je levný způsob ověření API klíče
        models = client.models.list()
        _startup_log("openai_init", "end", model=config.OPENAI_CHAT_MODEL)
        available = {m.id for m in models}
        primary_ok = config.OPENAI_CHAT_MODEL in available
        fallback_ok = config.OPENAI_CHAT_FALLBACK_MODEL in available
        if primary_ok:
            detail = (
                f"Model '{config.OPENAI_CHAT_MODEL}' dostupný"
                + (f", fallback '{config.OPENAI_CHAT_FALLBACK_MODEL}' {'dostupný' if fallback_ok else 'NENALEZEN'}"
                   if config.OPENAI_CHAT_FALLBACK_MODEL != config.OPENAI_CHAT_MODEL
                   else "")
            )
            return ComponentStatus(status="ok", detail=detail)
        return ComponentStatus(
            status="degraded",
            detail=f"Primární model '{config.OPENAI_CHAT_MODEL}' nedostupný. Fallback: '{config.OPENAI_CHAT_FALLBACK_MODEL}' {'OK' if fallback_ok else 'NENALEZEN'}",
        )
    except Exception as exc:
        _startup_log("openai_init", "error", error=type(exc).__name__)
        return ComponentStatus(status="error", detail=str(exc))


def _get_collection_info() -> CollectionInfo:
    """Načte detailní info o Qdrant kolekci (synchronní, pro to_thread)."""
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=config.QDRANT_HOST,
        port=config.QDRANT_PORT,
        timeout=10,
    )
    info = client.get_collection(config.QDRANT_COLLECTION)

    # config.params.vectors může být VectorParams (single) nebo dict (named)
    vectors_cfg = info.config.params.vectors
    if hasattr(vectors_cfg, "size"):
        # Jednoduchá kolekce (náš případ)
        vector_size = vectors_cfg.size
        distance = vectors_cfg.distance.value
    else:
        # Pojmenované vektory – bereme první
        first = next(iter(vectors_cfg.values()))
        vector_size = first.size
        distance = first.distance.value

    return CollectionInfo(
        name=config.QDRANT_COLLECTION,
        points_count=info.points_count or 0,
        indexed_vectors_count=info.indexed_vectors_count or 0,
        status=info.status.value if hasattr(info.status, "value") else str(info.status),
        vector_size=vector_size,
        distance_metric=distance,
    )


# ---------------------------------------------------------------------------
# Lifespan – startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Kontroluje stav všech komponent při startu serveru.
    Neblokuje start při degraded stavu – server startuje vždy,
    ale chybějící komponenty nahlásí /health.
    """
    _startup_log("app", "begin", pid=os.getpid())
    logger.info("Raiffeisenbank RAG API startuje…")
    logger.info(f"  LLM backend: [bold]{config.LLM_BACKEND}[/bold]")
    startup_timeout = float(os.getenv("STARTUP_HEALTH_CHECK_TIMEOUT", "8"))

    # Paralelní health checks with hard timeout diagnostics.
    _startup_log("health_checks", "begin", timeout_seconds=startup_timeout)
    checks = [
        _check_redis_startup(min(startup_timeout, 3.0)),
        _startup_check_with_timeout("qdrant", _check_qdrant, startup_timeout),
        _startup_check_with_timeout("ollama", _check_ollama, startup_timeout),
    ]
    llm_check = None
    if config.LLM_BACKEND == "anthropic":
        checks.append(_startup_check_with_timeout("anthropic", _check_anthropic, startup_timeout))
        llm_check = "anthropic"
    elif config.LLM_BACKEND == "gemini":
        checks.append(_startup_check_with_timeout("gemini", _check_gemini, startup_timeout))
        llm_check = "gemini"
    elif config.LLM_BACKEND == "openai":
        checks.append(_startup_check_with_timeout("openai", _check_openai, startup_timeout))
        llm_check = "openai"

    results = await asyncio.gather(*checks)
    _startup_log("health_checks", "end", count=len(results))
    redis_status, qdrant, ollama = results[0], results[1], results[2]
    llm_status: ComponentStatus | None = results[3] if llm_check else None
    anthropic_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "anthropic" else None
    gemini_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "gemini" else None
    openai_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "openai" else None
    bm25 = _startup_check("bm25", _check_bm25)

    checks_to_log = [("Redis", redis_status), ("Qdrant", qdrant), ("Ollama", ollama), ("BM25", bm25)]
    if anthropic_status:
        checks_to_log.append(("Anthropic", anthropic_status))
    if gemini_status:
        checks_to_log.append(("Gemini", gemini_status))
    if openai_status:
        checks_to_log.append(("OpenAI", openai_status))

    for name, comp in checks_to_log:
        icon = "✓" if comp.status == "ok" else "⚠" if comp.status == "degraded" else "✗"
        logger.info(f"  {icon} {name}: {comp.status} – {comp.detail}")

    logger.info("API server připraven na http://localhost:8000")
    logger.info("Dokumentace: http://localhost:8000/docs")
    _startup_log("app", "completed")

    # Warm-up: projde celou pipeline (BM25 + embedding + reranker) aby se
    # vše načetlo do paměti před prvním uživatelským dotazem.
    async def _warmup() -> None:
        try:
            t_wu = time.perf_counter()
            chain = BankingRAGChain(conversational=False)
            await asyncio.to_thread(chain.ask, "eKonto")
            logger.info(f"Warm-up complete, ready ({(time.perf_counter() - t_wu) * 1000:.0f}ms)")
        except Exception as exc:
            logger.warning(f"Warm-up selhal (server pokračuje): {exc!s:.100}")

    asyncio.ensure_future(_warmup())

    yield  # Server běží

    # Shutdown
    logger.info(f"Ukončuji server, uvolňuji {len(_sessions)} sezení…")
    _sessions.clear()
    _session_locks.clear()
    _session_store.close()
    _distributed_cache.close()


# ---------------------------------------------------------------------------
# FastAPI aplikace
# ---------------------------------------------------------------------------

_startup_log("router_registration", "begin")
app = FastAPI(
    title="Raiffeisenbank RAG API",
    description=(
        "REST API pro RAG chatbot Raiffeisenbank.\n\n"
        "Pipeline: BM25 + Qdrant (hybridní) → BGE Reranker → LLM\n"
        "Backend: ollama | anthropic | gemini | openai"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

_startup_log("router_registration", "app_created")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
_startup_log("router_registration", "middleware_registered")

# Security headers middleware
@app.middleware("http")
async def _add_security_headers(request: Request, call_next: Any) -> Any:
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'"
    return response

# Simple per-IP rate limiting middleware
_rate_limit_buckets: dict[str, list[float]] = {}

@app.middleware("http")
async def _rate_limiter(request: Request, call_next: Any) -> Any:
    """Rate limit requests per IP using a sliding window counter."""
    if not config.RATE_LIMIT_ENABLED:
        return await call_next(request)

    # Only rate-limit chat endpoints
    if request.url.path not in ("/chat", "/chat/stream"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = 60.0  # 1 minute

    bucket = _rate_limit_buckets.setdefault(client_ip, [])
    # Prune old entries outside the window
    while bucket and bucket[0] < now - window:
        bucket.pop(0)

    if len(bucket) >= config.RATE_LIMIT_PER_MINUTE:
        logger.warning(f"Rate limit exceeded for {client_ip}: {len(bucket)}/{config.RATE_LIMIT_PER_MINUTE}")
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "detail": "Too many requests. Try again later."},
        )

    bucket.append(now)
    return await call_next(request)

# Request body size limit middleware
@app.middleware("http")
async def _request_body_size_limit(request: Request, call_next: Any) -> Any:
    """Reject requests with body larger than MAX_REQUEST_BODY_BYTES."""
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "payload_too_large", "detail": f"Request body exceeds {config.MAX_REQUEST_BODY_BYTES} bytes."},
                    )
            except (ValueError, TypeError):
                pass
    return await call_next(request)


# ---------------------------------------------------------------------------
# Endpointy
# ---------------------------------------------------------------------------

@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chatbot endpoint",
    description=(
        "Odpoví na bankovní dotaz. Při opakovaném volání se stejným `session_id` "
        "udržuje konverzační paměť (follow-up otázky fungují v kontextu)."
    ),
)
async def chat(request: ChatRequest) -> ChatResponse:
    t_start = time.perf_counter()
    request_id = str(uuid.uuid4())
    partial_result: dict[str, Any] | None = None

    # Získání / vytvoření sezení
    try:
        session_id, chain, lock = await _get_or_create_session(request.session_id)
    except Exception as exc:
        telemetry.emit("error", request_id=request_id, error_type="session_init_failed", detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Nelze inicializovat RAG chain: {exc}",
        )

    telemetry.emit(
        "request_started",
        request_id=request_id,
        session_id=session_id,
        question=request.question,
    )

    # Priority 1: Cache check – first check distributed cache (governed key),
    # then fall back to legacy cache (in-flight dedup)
    t_cache = time.perf_counter()
    cache_key = _cache_key(request.question)
    cached_result: dict | None = None

    # Check distributed cache with governed key (product-aware, namespace-aware)
    # We try identity/pricing/overview namespaces — first hit wins
    for ns in ("identity", "overview", "pricing"):
        # Try without session_id (cross-session cache is fine for deterministic routes)
        logger.debug(f"Cache get start request_id={request_id} sid={_mask_session_id(session_id)} ns={ns}")
        try:
            dc_result = await asyncio.wait_for(
                _distributed_cache.get(
                    ns, request.question,
                    canonical_product=getattr(chain, "resolved_product", None),
                    pricing_version=getattr(config, "PRICING_DATA_VERSION", None),
                ),
                timeout=3.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Cache get timeout request_id={request_id} sid={_mask_session_id(session_id)} ns={ns}")
            dc_result = None
        logger.debug(f"Cache get done request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} hit={dc_result is not None}")
        if dc_result is not None:
            try:
                cached_result = json.loads(dc_result)
                cached_result["_distributed_cache_hit"] = True
                cached_result["_distributed_namespace"] = ns
                cached_result["cache_check_ms"] = (time.perf_counter() - t_cache) * 1000
                logger.info(f"[{request_id}] [{session_id[:8]}] Distributed cache HIT ns={ns}")
                break
            except (json.JSONDecodeError, TypeError):
                cached_result = None

    # Fallback to legacy cache if distributed miss
    if cached_result is None:
        cached_result = _response_cache.get(cache_key)

    cache_check_ms = (time.perf_counter() - t_cache) * 1000

    _backend_meta = {
        "cache_backend": "DistributedResponseCache",
        "session_backend": "DistributedSessionStore",
        "redis_available": config.REDIS_ENABLED or config.USE_REDIS_CACHE or config.USE_REDIS_SESSIONS,
    }

    if cached_result is not None:
        _response_cache.add_debug_metadata(cached_result, cache_hit=True, key=cache_key)
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.info(f"[{request_id}] [{session_id[:8]}] Cache HIT key={cache_key[:12]}…")
        telemetry.emit("cache_hit", request_id=request_id, session_id=session_id,
                       latency_ms=cache_check_ms, confidence_bucket=cached_result.get("confidence_bucket"))
        cached_result = _enrich_result_with_semantics(cached_result)
        return ChatResponse(
            answer=cached_result["answer"],
            sources=_serialize_sources(cached_result.get("sources", [])),
            session_id=session_id,
            processing_time_ms=round(elapsed_ms, 1),
            request_id=request_id,
            answer_strategy=cached_result.get("answer_strategy"),
            retrieval_debug=cached_result.get("retrieval_debug") if config.DEBUG_API_ERRORS else None,
            confidence_bucket=cached_result.get("confidence_bucket"),
            confidence_reason=cached_result.get("confidence_reason"),
            clarification_required=cached_result.get("clarification_required"),
            unsupported_reason=cached_result.get("unsupported_reason"),
            **_backend_meta,
            confidence_origin=cached_result.get("confidence_origin"),
            confidence_origin_label=cached_result.get("confidence_origin_label"),
            confidence_semantic_label=cached_result.get("confidence_semantic_label"),
            degraded_answer=cached_result.get("degraded_answer"),
        )

    # In-flight deduplication
    telemetry.emit("cache_miss", request_id=request_id, session_id=session_id, latency_ms=cache_check_ms)
    if not _response_cache.try_claim_inflight(cache_key):
        t_wait = time.perf_counter()
        logger.info(f"[{request_id}] [{session_id[:8]}] Cache DEDUP waiting for key={cache_key[:12]}…")
        _response_cache.wait_inflight(cache_key)
        cached_result = _response_cache.get(cache_key)
        if cached_result is not None:
            _response_cache.add_debug_metadata(cached_result, cache_hit=True, key=cache_key)
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            logger.info(f"[{request_id}] [{session_id[:8]}] Cache DEDUP HIT key={cache_key[:12]}…")
            cached_result = _enrich_result_with_semantics(cached_result)
            return ChatResponse(
                answer=cached_result["answer"],
                sources=_serialize_sources(cached_result.get("sources", [])),
                session_id=session_id,
                processing_time_ms=round(elapsed_ms, 1),
                request_id=request_id,
                answer_strategy=cached_result.get("answer_strategy"),
                retrieval_debug=cached_result.get("retrieval_debug") if config.DEBUG_API_ERRORS else None,
                confidence_bucket=cached_result.get("confidence_bucket"),
                confidence_reason=cached_result.get("confidence_reason"),
                clarification_required=cached_result.get("clarification_required"),
                unsupported_reason=cached_result.get("unsupported_reason"),
                **_backend_meta,
                confidence_origin=cached_result.get("confidence_origin"),
                confidence_origin_label=cached_result.get("confidence_origin_label"),
                confidence_semantic_label=cached_result.get("confidence_semantic_label"),
                degraded_answer=cached_result.get("degraded_answer"),
            )
        # Fallback: if wait timed out or no result, compute normally
        logger.warning(f"[{request_id}] [{session_id[:8]}] Cache DEDUP wait failed for key={cache_key[:12]}… — computing")

    # Serializace requestů pro jedno sezení – chrání chat_history před race condition
    async with lock:
        try:
            result: dict = await asyncio.to_thread(chain.ask, request.question)
            partial_result = result
        except Exception as exc:
            _response_cache.signal_inflight_done(cache_key)
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            logger.error(f"[{request_id}] [{session_id[:8]}] Chain error: {exc}", exc_info=True)
            telemetry.emit("error", request_id=request_id, session_id=session_id,
                           error_type="chain_error", detail=str(exc)[:200], latency_ms=elapsed_ms)
            return _internal_error_response(
                request_id=request_id,
                session_id=session_id,
                question=request.question,
                exc=exc,
                elapsed_ms=elapsed_ms,
                partial_result=partial_result,
            )

    elapsed_ms = (time.perf_counter() - t_start) * 1000

    # Priority 4: Session context debug fields (populated by chain.ask)
    session_debug = getattr(chain, "_session_debug", None) or {}
    if session_debug.get("session_context_used"):
        result["session_context_used"] = True
        if session_debug.get("inherited_product"):
            result["inherited_product"] = session_debug["inherited_product"]
        if session_debug.get("inherited_intent"):
            result["inherited_intent"] = session_debug["inherited_intent"]

    # Priority 1: Cache store in both legacy and distributed caches
    if _is_cacheable(result):
        _response_cache.set(cache_key, result)

        # Also store in distributed cache with governed key
        strategy = result.get("answer_strategy", "")
        if strategy in ("identity_direct",):
            ns = "identity"
        elif strategy in ("pricing_row_direct",):
            ns = "pricing"
        elif "_overview_" in strategy or strategy.endswith("_overview_direct"):
            ns = "overview"
        else:
            ns = "overview"  # fallback

        canonical_product = result.get("resolved_product") or getattr(chain, "resolved_product", None)
        response_json = json.dumps({
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "answer_strategy": result.get("answer_strategy"),
            "confidence_bucket": result.get("confidence_bucket"),
            "confidence_reason": result.get("confidence_reason"),
            "clarification_required": result.get("clarification_required"),
            "unsupported_reason": result.get("unsupported_reason"),
            "confidence_origin": result.get("confidence_origin"),
            "confidence_origin_label": result.get("confidence_origin_label"),
            "confidence_semantic_label": result.get("confidence_semantic_label"),
            "degraded_answer": result.get("degraded_answer"),
            "processing_time_ms": result.get("processing_time_ms"),
            "cache_age_seconds": 0,
            "_cached_at": datetime.now(UTC).isoformat(),
            "_cache_ttl_seconds": _distributed_cache.get_ttl(ns),
            "_original_strategy": strategy,
        }, ensure_ascii=False, default=str)

        try:
            logger.debug(f"Cache set start request_id={request_id} sid={_mask_session_id(session_id)} ns={ns}")
            await asyncio.wait_for(
                _distributed_cache.set(
                    ns, request.question, response_json,
                    canonical_product=canonical_product,
                    pricing_version=getattr(config, "PRICING_DATA_VERSION", None),
                ),
                timeout=3.0,
            )
            logger.debug(f"Cache set done request_id={request_id} sid={_mask_session_id(session_id)} ns={ns}")
        except asyncio.TimeoutError:
            logger.warning(f"Cache set timeout request_id={request_id} sid={_mask_session_id(session_id)} ns={ns}")
        except Exception as exc:
            logger.warning(f"Cache set failed request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} error={exc}")

    _response_cache.signal_inflight_done(cache_key)

    # --- Session state persistence after /chat ---
    try:
        session_state = _collect_chain_session_state(chain)
        if session_state:
            logger.debug(f"Session save start sid={_mask_session_id(session_id)} reason=post_chat")
            await asyncio.wait_for(
                _session_store.save(
                    session_id, session_state,
                    ttl_seconds=SESSION_TTL_SECONDS,
                ),
                timeout=3.0,
            )
            logger.debug(f"Session save done sid={_mask_session_id(session_id)} reason=post_chat")
    except asyncio.TimeoutError:
        logger.warning(f"[{request_id}] Session state save timeout sid={_mask_session_id(session_id)}")
    except Exception as exc:
        logger.warning(f"[{request_id}] Session state save failed sid={_mask_session_id(session_id)} error={exc}")

    try:
        sources = _serialize_sources(result.get("sources", []))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.error(f"[{request_id}] [{session_id[:8]}] Source serialization error: {exc}", exc_info=True)
        return _internal_error_response(
            request_id=request_id,
            session_id=session_id,
            question=request.question,
            exc=exc,
            elapsed_ms=elapsed_ms,
            partial_result=result,
        )

    # Priority 5: Extract timing breakdown from chain result
    timing_ms = result.get("timing_ms", {}) or {}
    retrieval_lat = timing_ms.get("retrieval") or timing_ms.get("retrieval_latency_ms")
    llm_lat = timing_ms.get("llm") or timing_ms.get("llm_latency_ms")
    fmt_lat = timing_ms.get("formatting_latency_ms")

    # Priority 1: Backend metadata
    cache_backend_name = _api_backends.get("cache_backend", "unknown")
    session_backend_name = _api_backends.get("session_backend", "unknown")
    redis_avail = config.USE_REDIS_CACHE or config.USE_REDIS_SESSIONS

    # Enrich result with confidence semantics for ALL response paths
    result = _enrich_result_with_semantics(result)

    telemetry.emit(
        "response_completed",
        request_id=request_id,
        session_id=session_id,
        route=result.get("answer_strategy"),
        strategy=result.get("answer_strategy"),
        latency_ms=round(elapsed_ms, 1),
        confidence_bucket=result.get("confidence_bucket"),
        source_count=len(sources) if sources else 0,
        cache_hit=False,
        degraded=result.get("degraded_answer") or False,
    )

    return ChatResponse(
        answer=result["answer"],
        sources=sources,
        session_id=session_id,
        processing_time_ms=round(elapsed_ms, 1),
        request_id=request_id,
        answer_strategy=result.get("answer_strategy"),
        retrieval_debug=result.get("retrieval_debug") if config.DEBUG_API_ERRORS else None,
        confidence_bucket=result.get("confidence_bucket"),
        confidence_reason=result.get("confidence_reason"),
        clarification_required=result.get("clarification_required"),
        unsupported_reason=result.get("unsupported_reason"),
        cache_check_ms=cache_check_ms,
        retrieval_latency_ms=round(retrieval_lat, 1) if retrieval_lat is not None else None,
        llm_latency_ms=round(llm_lat, 1) if llm_lat is not None else None,
        formatting_latency_ms=round(fmt_lat, 1) if fmt_lat is not None else None,
        cache_backend=cache_backend_name,
        session_backend=session_backend_name,
        redis_available=redis_avail,
        # P2: Confidence semantics
        confidence_origin=result.get("confidence_origin"),
        confidence_origin_label=result.get("confidence_origin_label"),
        confidence_semantic_label=result.get("confidence_semantic_label"),
        degraded_answer=result.get("degraded_answer"),
    )


# ---------------------------------------------------------------------------
# Priority 2: SSE streaming endpoint
# ---------------------------------------------------------------------------

def _sse_format(event: str, data: Any) -> str:
    """Format an SSE message."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post(
    "/chat/stream",
    summary="Chatbot streaming endpoint (SSE)",
    description=(
        "Server-Sent Events streaming endpoint. "
        "Deterministic routes return instantly; LLM routes stream tokens.\n\n"
        "Events:\n"
        "  - `start`  — metadata (strategy, confidence, sources, session_id)\n"
        "  - `token`  — increment text token (field: `text`)\n"
        "  - `done`   — final metadata (timing, cache info, errors)\n"
        "  - `error`  — error event (field: `error`, `detail`)"
    ),
)
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    request_id = str(uuid.uuid4())

    async def event_stream() -> Any:
        import asyncio
        import threading

        # Session
        try:
            session_id, chain, lock = await _get_or_create_session(request.session_id)
        except Exception as exc:
            yield _sse_format("error", {"error": "session_init_failed", "detail": str(exc)})
            return

        # Cache check (fast path — identical to /chat)
        t_start = time.perf_counter()
        cache_key = _cache_key(request.question)
        cached = _response_cache.get(cache_key)
        if cached is not None:
            _response_cache.add_debug_metadata(cached, cache_hit=True, key=cache_key)
            cached = _enrich_result_with_semantics(cached)
            sources = _serialize_sources(cached.get("sources", []))
            telemetry.emit("cache_hit", request_id=request_id, session_id=session_id,
                           route=request.question[:80])
            yield _sse_format("start", {
                "session_id": session_id,
                "request_id": request_id,
                "answer_strategy": cached.get("answer_strategy"),
                "answer_confidence": cached.get("answer_confidence"),
                "sources": [s.model_dump() for s in sources],
                "cache_hit": True,
                "confidence_semantic_label": cached.get("confidence_semantic_label"),
                "confidence_origin": cached.get("confidence_origin"),
                "degraded_answer": cached.get("degraded_answer"),
            })
            yield _sse_format("token", {"text": cached["answer"]})
            yield _sse_format("done", {
                "processing_time_ms": round((time.perf_counter() - t_start) * 1000, 1),
            })
            return

        telemetry.emit(
            "stream_started",
            request_id=request_id,
            session_id=session_id,
            question=request.question,
        )

        # True token streaming via ask_stream() bridge
        # ask_stream() is a sync generator; we bridge it to async via Queue.
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def _producer():
            """Run ask_stream() in a thread and enqueue events."""
            try:
                for event in chain.ask_stream(request.question):
                    queue.put_nowait(event)
            except Exception as exc:
                logger.exception(f"[{request_id}] ask_stream error")
                queue.put_nowait({"type": "error", "error": "chain_error", "detail": str(exc)})
            finally:
                queue.put_nowait(None)  # sentinel — stream complete

        async with lock:
            thread = threading.Thread(target=_producer, daemon=True)
            thread.start()

            while True:
                event = await queue.get()
                if event is None:
                    break

                if event["type"] == "start":
                    sources_raw = event.get("sources", [])
                    sources = _serialize_sources(sources_raw)
                    yield _sse_format("start", {
                        "session_id": session_id,
                        "request_id": request_id,
                        "answer_strategy": event.get("answer_strategy"),
                        "answer_confidence": event.get("answer_confidence"),
                        "sources": [s.model_dump() for s in sources],
                        "clarification_required": event.get("clarification_required"),
                        "unsupported_reason": event.get("unsupported_reason"),
                        "cache_hit": event.get("cache_hit", False),
                        "confidence_semantic_label": event.get("confidence_semantic_label"),
                        "confidence_origin": event.get("confidence_origin"),
                        "degraded_answer": event.get("degraded_answer"),
                    })

                elif event["type"] == "token":
                    yield _sse_format("token", {"text": event["text"]})

                elif event["type"] == "done":
                    # Cache the result if possible (reconstruct result from events)
                    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
                    yield _sse_format("done", {
                        "processing_time_ms": elapsed_ms,
                        "retrieval_latency_ms": event.get("retrieval_latency_ms"),
                        "llm_latency_ms": event.get("llm_latency_ms"),
                        "formatting_latency_ms": event.get("formatting_latency_ms"),
                        "answer_strategy": event.get("answer_strategy"),
                        "confidence_bucket": event.get("confidence_bucket"),
                        "confidence_semantic_label": event.get("confidence_semantic_label"),
                    })

                elif event["type"] == "error":
                    logger.error(f"[{request_id}] ask_stream error: {event.get('detail')}")
                    telemetry.emit("error", request_id=request_id, session_id=session_id,
                                   error_type=event.get("error", "stream_error"),
                                   detail=str(event.get("detail", ""))[:200])
                    yield _sse_format("error", {
                        "error": event.get("error", "stream_error"),
                        "detail": event.get("detail", ""),
                    })

            # --- Post-stream telemetry and caching ---
            telemetry.emit(
                "stream_completed",
                request_id=request_id,
                session_id=session_id,
                latency_ms=round((time.perf_counter() - t_start) * 1000, 1),
            )

            # ask_stream() stores the final result dict in chain._last_stream_result
            stream_result = getattr(chain, "_last_stream_result", None)
            if stream_result and _is_cacheable(stream_result):
                _response_cache.set(cache_key, stream_result)

                # Also store in distributed cache
                strategy = stream_result.get("answer_strategy", "")
                if strategy in ("identity_direct",):
                    ns = "identity"
                elif strategy in ("pricing_row_direct",):
                    ns = "pricing"
                elif "_overview_" in strategy or strategy.endswith("_overview_direct"):
                    ns = "overview"
                else:
                    ns = "overview"

                canonical_product = stream_result.get("resolved_product") or getattr(chain, "resolved_product", None)
                response_json = json.dumps({
                    "answer": stream_result.get("answer", ""),
                    "sources": stream_result.get("sources", []),
                    "answer_strategy": strategy,
                    "confidence_bucket": stream_result.get("confidence_bucket"),
                    "confidence_reason": stream_result.get("confidence_reason"),
                    "clarification_required": stream_result.get("clarification_required"),
                    "unsupported_reason": stream_result.get("unsupported_reason"),
                    "confidence_origin": stream_result.get("confidence_origin"),
                    "confidence_origin_label": stream_result.get("confidence_origin_label"),
                    "confidence_semantic_label": stream_result.get("confidence_semantic_label"),
                    "degraded_answer": stream_result.get("degraded_answer"),
                    "_cached_at": datetime.now(UTC).isoformat(),
                    "_cache_ttl_seconds": _distributed_cache.get_ttl(ns),
                    "_original_strategy": strategy,
                }, ensure_ascii=False, default=str)

                try:
                    logger.debug(f"Cache set start request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} route=stream")
                    await asyncio.wait_for(
                        _distributed_cache.set(
                            ns, request.question, response_json,
                            canonical_product=canonical_product,
                            pricing_version=getattr(config, "PRICING_DATA_VERSION", None),
                        ),
                        timeout=3.0,
                    )
                    logger.debug(f"Cache set done request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} route=stream")
                except asyncio.TimeoutError:
                    logger.warning(f"Cache set timeout request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} route=stream")
                except Exception as exc:
                    logger.warning(f"Cache set failed request_id={request_id} sid={_mask_session_id(session_id)} ns={ns} route=stream error={exc}")

            # --- Session state persistence after stream ---
            try:
                session_state = _collect_chain_session_state(chain)
                if session_state:
                    logger.debug(f"Session save start sid={_mask_session_id(session_id)} reason=post_stream")
                    await asyncio.wait_for(
                        _session_store.save(
                            session_id, session_state,
                            ttl_seconds=SESSION_TTL_SECONDS,
                        ),
                        timeout=3.0,
                    )
                    logger.debug(f"Session save done sid={_mask_session_id(session_id)} reason=post_stream")
            except asyncio.TimeoutError:
                logger.warning(f"[{request_id}] Session state persistence timeout sid={_mask_session_id(session_id)}")
            except Exception as exc:
                logger.warning(f"[{request_id}] Session state persistence error sid={_mask_session_id(session_id)} error={exc}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Rychlý stav API",
    description=(
        "Rychlý frontend-facing health check bez síťových/deep kontrol. "
        "Pro Qdrant/OpenAI/Redis detaily použijte /health/deep."
    ),
)
async def health() -> HealthResponse:
    bm25 = _check_bm25()
    overall: Literal["ok", "degraded", "error"] = "ok" if bm25.status == "ok" else bm25.status
    return HealthResponse(
        status=overall,
        qdrant=ComponentStatus(status="ok", detail="Skipped in fast health; use /health/deep for Qdrant check"),
        ollama=ComponentStatus(status="ok", detail="Skipped in fast health; use /health/deep for model check"),
        bm25_index=bm25,
        anthropic=None,
        gemini=None,
        openai=None,
        active_provider=config.LLM_BACKEND,
        active_model=config.PRIMARY_MODEL,
        fallback_model=config.OPENAI_CHAT_FALLBACK_MODEL,
    )


@app.get(
    "/health/deep",
    response_model=HealthResponse,
    summary="Detailní stav komponent",
    description=(
        "Detailní health check včetně Qdrant/Ollama/OpenAI/Gemini/Anthropic. "
        "Může trvat několik sekund; frontend má používat rychlý /health."
    ),
)
async def health_deep() -> HealthResponse:
    # Qdrant a Ollama paralelně; Anthropic check jen při příslušném backendu
    gather_tasks = [
        asyncio.to_thread(_check_qdrant),
        asyncio.to_thread(_check_ollama),
    ]
    llm_check = None
    if config.LLM_BACKEND == "anthropic":
        gather_tasks.append(asyncio.to_thread(_check_anthropic))
        llm_check = "anthropic"
    elif config.LLM_BACKEND == "gemini":
        gather_tasks.append(asyncio.to_thread(_check_gemini))
        llm_check = "gemini"
    elif config.LLM_BACKEND == "openai":
        gather_tasks.append(asyncio.to_thread(_check_openai))
        llm_check = "openai"

    results = await asyncio.gather(*gather_tasks)
    qdrant, ollama = results[0], results[1]
    llm_status: ComponentStatus | None = results[2] if llm_check else None
    anthropic_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "anthropic" else None
    gemini_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "gemini" else None
    openai_status: ComponentStatus | None = llm_status if config.LLM_BACKEND == "openai" else None
    bm25 = _check_bm25()

    all_statuses = {qdrant.status, ollama.status, bm25.status}
    for extra in (anthropic_status, gemini_status, openai_status):
        if extra:
            all_statuses.add(extra.status)

    if "error" in all_statuses:
        overall: Literal["ok", "degraded", "error"] = "error"
    elif "degraded" in all_statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        qdrant=qdrant,
        ollama=ollama,
        bm25_index=bm25,
        anthropic=anthropic_status,
        gemini=gemini_status,
        openai=openai_status,
    )

# ---------------------------------------------------------------------------
# Memory usage report – helper and endpoint
# ---------------------------------------------------------------------------

def _memory_report() -> dict:
    """Collect memory usage estimates for major components.

    Returns a dict with MB values and a simple largest-consumer hint.
    """
    # BM25 index size
    bm25_mb = (
        config.BM25_INDEX_PATH.stat().st_size / (1024 * 1024)
        if config.BM25_INDEX_PATH.exists()
        else 0
    )

    # Pricing rows file size and line count
    pricing_mb = (
        config.PRICING_ROWS_PATH.stat().st_size / (1024 * 1024)
        if config.PRICING_ROWS_PATH.exists()
        else 0
    )
    pricing_lines = None
    if config.PRICING_ROWS_PATH.exists():
        try:
            with config.PRICING_ROWS_PATH.open("r", encoding="utf-8") as f:
                for i, _ in enumerate(f, 1):
                    pass
                pricing_lines = i
        except Exception:
            pricing_lines = None

    # In‑memory session cache – rough 1 MiB per active session
    session_count = len(_sessions)
    session_cache_mb = session_count * 1.0

    # In‑memory response cache – use emergency entry count as proxy (≈0.5 MiB each)
    rc_stats = _response_cache.stats
    resp_entries = rc_stats.get("emergency_current_entries", 0)
    response_cache_mb = resp_entries * 0.5

    # Qdrant retriever memory – points * vector_dim * 4 bytes (float32)
    retriever_mb = None
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            host=config.QDRANT_HOST,
            port=config.QDRANT_PORT,
            timeout=5,
        )
        coll = client.get_collection(config.QDRANT_COLLECTION)
        points = coll.points_count or 0
        # Vector size extraction – works for simple and named configs
        vectors_cfg = coll.config.params.vectors
        if hasattr(vectors_cfg, "size"):
            vector_size = vectors_cfg.size
        else:
            first = next(iter(vectors_cfg.values()))
            vector_size = first.size
        retriever_mb = points * vector_size * 4 / (1024 * 1024)
    except Exception:
        retriever_mb = None

    # Helper to compute size of a HuggingFace model directory (if present)
    def _model_dir_size(model_name: str) -> float | None:
        base = Path(os.path.expanduser("~/.cache/huggingface/hub"))
        if not base.is_dir():
            return None
        # Model directories are named with a hash; we look for a folder containing the model name
        for p in base.iterdir():
            if p.is_dir() and model_name.replace("/", "-") in p.name:
                total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                return total / (1024 * 1024)
        return None

    reranker_mb = _model_dir_size(config.RERANKER_MODEL)
    embeddings_mb = _model_dir_size(config.get_active_embed_model())

    # Aggregate totals (ignore None values)
    components = {
        "bm25": bm25_mb,
        "pricing": pricing_mb,
        "session_cache": session_cache_mb,
        "response_cache": response_cache_mb,
        "retriever": retriever_mb,
        "reranker": reranker_mb,
        "embeddings": embeddings_mb,
    }
    total_mb = sum(v for v in components.values() if v is not None)
    largest_consumer = max(components.items(), key=lambda kv: kv[1] if kv[1] is not None else -1)[0]

    report = {
        "bm25_mb": round(bm25_mb, 1),
        "pricing_mb": round(pricing_mb, 1),
        "pricing_rows": pricing_lines,
        "session_cache_mb": round(session_cache_mb, 1),
        "response_cache_mb": round(response_cache_mb, 1),
        "retriever_mb": round(retriever_mb, 1) if retriever_mb is not None else None,
        "reranker_mb": round(reranker_mb, 1) if reranker_mb is not None else None,
        "embeddings_mb": round(embeddings_mb, 1) if embeddings_mb is not None else None,
        "total_mb": round(total_mb, 1),
        "largest_consumer": largest_consumer,
    }
    return report


@app.get(
    "/health/memory",
    response_model=dict,
    summary="Memory usage report",
    description="Provides an approximate memory footprint of major components.",
)
async def health_memory() -> dict:
    return _memory_report()


@app.get(
    "/collections",
    response_model=CollectionInfo,
    summary="Info o Qdrant kolekci",
    description="Vrátí počet dokumentů, stav indexu a konfiguraci vektorové kolekce.",
)
async def collections() -> CollectionInfo:
    try:
        return await asyncio.to_thread(_get_collection_info)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Qdrant nedostupný nebo kolekce neexistuje: {exc}",
        )
