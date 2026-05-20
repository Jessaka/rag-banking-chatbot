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
import json
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

import requests as http_requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
from src.generation.chain import BankingRAGChain
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Session management – konfigurace
# ---------------------------------------------------------------------------

SESSION_TTL_SECONDS: int = 3600   # Sezení expiruje po 1 hodině nečinnosti
MAX_SESSIONS: int = 50            # Limit pro LRU eviction

# session_id → (chain, last_access_timestamp)
_sessions: dict[str, tuple[BankingRAGChain, float]] = {}

# Per-session asyncio locky zabraňují souběžnému mutování chat_history
# ve stejném sezení při paralelních requestech.
_session_locks: dict[str, asyncio.Lock] = {}


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


class ComponentStatus(BaseModel):
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
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
    """Odstraní sezení neaktivní déle než SESSION_TTL_SECONDS."""
    cutoff = time.monotonic() - SESSION_TTL_SECONDS
    stale = [sid for sid, (_, ts) in _sessions.items() if ts < cutoff]
    for sid in stale:
        _sessions.pop(sid, None)
        _session_locks.pop(sid, None)
    if stale:
        logger.info(f"Expirovalo {len(stale)} sezení (TTL={SESSION_TTL_SECONDS}s)")


def _evict_oldest_session() -> None:
    """LRU eviction: smaže sezení s nejstarším přístupem."""
    if not _sessions:
        return
    oldest = min(_sessions, key=lambda k: _sessions[k][1])
    _sessions.pop(oldest, None)
    _session_locks.pop(oldest, None)
    logger.warning(f"LRU eviction sezení {oldest[:8]}… (limit {MAX_SESSIONS})")


def _get_or_create_session(
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
        _sessions[session_id] = (chain, time.monotonic())
        _session_locks[session_id] = asyncio.Lock()
        logger.info(f"Nové sezení: {session_id[:8]}… (aktivních: {len(_sessions)})")
    else:
        # Obnov timestamp přístupu
        chain, _ = _sessions[session_id]
        _sessions[session_id] = (chain, time.monotonic())

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
        return ComponentStatus(
            status="ok",
            detail=(
                f"'{config.QDRANT_COLLECTION}': "
                f"{info.points_count or 0} bodů, "
                f"stav: {info.status}"
            ),
        )
    except Exception as exc:
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
    logger.info("Raiffeisenbank RAG API startuje…")
    logger.info(f"  LLM backend: [bold]{config.LLM_BACKEND}[/bold]")

    # Paralelní health checks
    checks = [
        asyncio.to_thread(_check_qdrant),
        asyncio.to_thread(_check_ollama),
    ]
    if config.LLM_BACKEND == "anthropic":
        checks.append(asyncio.to_thread(_check_anthropic))
    elif config.LLM_BACKEND == "gemini":
        checks.append(asyncio.to_thread(_check_gemini))

    results = await asyncio.gather(*checks)
    qdrant, ollama = results[0], results[1]
    anthropic_status = results[2] if config.LLM_BACKEND == "anthropic" else None
    gemini_status = results[2] if config.LLM_BACKEND == "gemini" else None
    bm25 = _check_bm25()

    checks_to_log = [("Qdrant", qdrant), ("Ollama", ollama), ("BM25", bm25)]
    if anthropic_status:
        checks_to_log.append(("Anthropic", anthropic_status))
    if gemini_status:
        checks_to_log.append(("Gemini", gemini_status))

    for name, comp in checks_to_log:
        icon = "✓" if comp.status == "ok" else "⚠" if comp.status == "degraded" else "✗"
        logger.info(f"  {icon} {name}: {comp.status} – {comp.detail}")

    logger.info("API server připraven na http://localhost:8000")
    logger.info("Dokumentace: http://localhost:8000/docs")

    yield  # Server běží

    # Shutdown
    logger.info(f"Ukončuji server, uvolňuji {len(_sessions)} sezení…")
    _sessions.clear()
    _session_locks.clear()


# ---------------------------------------------------------------------------
# FastAPI aplikace
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Raiffeisenbank RAG API",
    description=(
        "REST API pro RAG chatbot Raiffeisenbank.\n\n"
        "Pipeline: BM25 + Qdrant (hybridní) → BGE Reranker → Mistral 7B (Ollama)"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Pro produkci omezit na konkrétní originy
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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
        session_id, chain, lock = _get_or_create_session(request.session_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Nelze inicializovat RAG chain: {exc}",
        )

    # Serializace requestů pro jedno sezení – chrání chat_history před race condition
    async with lock:
        try:
            result: dict = await asyncio.to_thread(chain.ask, request.question)
            partial_result = result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            logger.error(f"[{request_id}] [{session_id[:8]}] Chain error: {exc}", exc_info=True)
            return _internal_error_response(
                request_id=request_id,
                session_id=session_id,
                question=request.question,
                exc=exc,
                elapsed_ms=elapsed_ms,
                partial_result=partial_result,
            )

    elapsed_ms = (time.perf_counter() - t_start) * 1000

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

    return ChatResponse(
        answer=result["answer"],
        sources=sources,
        session_id=session_id,
        processing_time_ms=round(elapsed_ms, 1),
        request_id=request_id,
        answer_strategy=result.get("answer_strategy"),
        retrieval_debug=result.get("retrieval_debug") if config.DEBUG_API_ERRORS else None,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Stav komponent",
    description=(
        "Vrátí 200 vždy – i při `degraded` / `error` stavu. "
        "Sledujte pole `status` a sub-komponenty pro alerting. "
        "Pole `anthropic` je přítomno pouze pokud LLM_BACKEND='anthropic'."
    ),
)
async def health() -> HealthResponse:
    # Qdrant a Ollama paralelně; Anthropic check jen při příslušném backendu
    gather_tasks = [
        asyncio.to_thread(_check_qdrant),
        asyncio.to_thread(_check_ollama),
    ]
    if config.LLM_BACKEND == "anthropic":
        gather_tasks.append(asyncio.to_thread(_check_anthropic))
    elif config.LLM_BACKEND == "gemini":
        gather_tasks.append(asyncio.to_thread(_check_gemini))

    results = await asyncio.gather(*gather_tasks)
    qdrant, ollama = results[0], results[1]
    anthropic_status: ComponentStatus | None = results[2] if config.LLM_BACKEND == "anthropic" else None
    gemini_status: ComponentStatus | None = results[2] if config.LLM_BACKEND == "gemini" else None
    bm25 = _check_bm25()

    all_statuses = {qdrant.status, ollama.status, bm25.status}
    for extra in (anthropic_status, gemini_status):
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
    )


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
