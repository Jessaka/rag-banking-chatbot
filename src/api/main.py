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
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import requests as http_requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
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


class ComponentStatus(BaseModel):
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"] = Field(
        description="Celkový stav: ok | degraded (část komponent nefunguje) | error."
    )
    qdrant: ComponentStatus
    ollama: ComponentStatus
    bm25_index: ComponentStatus


class CollectionInfo(BaseModel):
    name: str = Field(description="Název Qdrant kolekce.")
    points_count: int = Field(description="Celkový počet bodů (chunků) v kolekci.")
    indexed_vectors_count: int = Field(description="Počet plně indexovaných vektorů.")
    status: str = Field(description="Stav kolekce: green | yellow | grey.")
    vector_size: int = Field(description="Dimenze embeddingů (nomic-embed-text = 768).")
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
    """Zkontroluje, zda Ollama běží a má načteny potřebné modely."""
    try:
        resp = http_requests.get(
            f"{config.OLLAMA_BASE_URL}/api/tags",
            timeout=5,
        )
        resp.raise_for_status()
        available = [m["name"] for m in resp.json().get("models", [])]

        # Modely v Ollama mají formát "mistral:latest"; porovnáváme prefix
        def _model_present(name: str) -> bool:
            return any(tag == name or tag.startswith(f"{name}:") for tag in available)

        missing = [
            m for m in (config.LLM_MODEL, config.EMBED_MODEL)
            if not _model_present(m)
        ]
        if missing:
            return ComponentStatus(
                status="degraded",
                detail=(
                    f"Chybí modely: {missing}. "
                    f"Dostupné: {available}. "
                    f"Spusťte: ollama pull {' '.join(missing)}"
                ),
            )
        return ComponentStatus(
            status="ok",
            detail=f"Modely OK: {available}",
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

    # Paralelní health checks při startu
    qdrant, ollama = await asyncio.gather(
        asyncio.to_thread(_check_qdrant),
        asyncio.to_thread(_check_ollama),
    )
    bm25 = _check_bm25()

    for name, comp in [("Qdrant", qdrant), ("Ollama", ollama), ("BM25", bm25)]:
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
        except Exception as exc:
            logger.error(f"[{session_id[:8]}] Chain error: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Chyba při generování odpovědi: {exc}",
            )

    elapsed_ms = (time.perf_counter() - t_start) * 1000

    sources = [
        SourceDocument(
            file_name=doc.metadata.get("file_name", "neznámý"),
            page=doc.metadata.get("page"),
            chunk_id=doc.metadata.get("chunk_id"),
            rerank_score=round(doc.metadata["rerank_score"], 4)
            if "rerank_score" in doc.metadata
            else None,
            preview=doc.page_content[:300],
        )
        for doc in result.get("sources", [])
    ]

    return ChatResponse(
        answer=result["answer"],
        sources=sources,
        session_id=session_id,
        processing_time_ms=round(elapsed_ms, 1),
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Stav komponent",
    description=(
        "Vrátí 200 vždy – i při `degraded` / `error` stavu. "
        "Sledujte pole `status` a sub-komponenty pro alerting."
    ),
)
async def health() -> HealthResponse:
    # Qdrant a Ollama paralelně (obě síťové I/O operace)
    qdrant, ollama = await asyncio.gather(
        asyncio.to_thread(_check_qdrant),
        asyncio.to_thread(_check_ollama),
    )
    bm25 = _check_bm25()

    statuses = {qdrant.status, ollama.status, bm25.status}
    if "error" in statuses:
        overall: Literal["ok", "degraded", "error"] = "error"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        qdrant=qdrant,
        ollama=ollama,
        bm25_index=bm25,
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
