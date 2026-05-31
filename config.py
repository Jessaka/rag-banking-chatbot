"""
Centrální konfigurace projektu RAG Banking Chatbot.

Všechny parametry lze přepsat pomocí proměnných prostředí nebo .env souboru.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

# ---------------------------------------------------------------------------
# Cesty
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "indexes"
PRICING_DIR = DATA_DIR / "pricing"
DISCOVERY_DIR: Path = DATA_DIR / "discovery"
CRAWL_DIR: Path = DATA_DIR / "crawl"
CRAWL_MANIFEST_PATH: Path = CRAWL_DIR / "crawl_manifest.json"
DOCUMENTS_DIR: Path = DATA_DIR / "documents"
PRICING_ROWS_PATH: Path = PRICING_DIR / "pricing_rows.jsonl"
PRICING_EXTRACT_MAX_PAGES_PER_PDF: int = int(os.getenv("PRICING_EXTRACT_MAX_PAGES_PER_PDF", "25"))
LOGS_DIR = BASE_DIR / "logs"
ERROR_LOG_PATH: Path = LOGS_DIR / "errors.log"
DEBUG_API_ERRORS: bool = _env_bool("DEBUG_API_ERRORS", "false")

# ---------------------------------------------------------------------------
# Embeddings backend
# ---------------------------------------------------------------------------
# "ollama" = lokální nomic-embed-text (768 dim)
# "openai" = OpenAI text-embedding-3-small (1536 dim)
EMBEDDING_BACKEND: str = os.getenv("EMBEDDING_BACKEND", "ollama").lower()
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL: str = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_EMBED_BATCH_SIZE: int = int(os.getenv("OPENAI_EMBED_BATCH_SIZE", "8"))
OPENAI_EMBED_SLEEP_MS: int = int(os.getenv("OPENAI_EMBED_SLEEP_MS", "250"))
OPENAI_EMBED_TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_EMBED_TIMEOUT_SECONDS", "240"))
OPENAI_EMBED_MAX_RETRIES: int = int(os.getenv("OPENAI_EMBED_MAX_RETRIES", "8"))
OLLAMA_EMBED_BATCH_SIZE: int = int(os.getenv("OLLAMA_EMBED_BATCH_SIZE", "16"))
QDRANT_TIMEOUT_SECONDS: float = float(os.getenv("QDRANT_TIMEOUT_SECONDS", "300"))

# Backward-compatible název Ollama embedding modelu.
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")


def get_embedding_vector_size() -> int:
    """Vrátí dimenzi embeddingů podle aktivního backendu."""
    if EMBEDDING_BACKEND == "openai":
        return 1536
    return 768


def get_active_embed_model() -> str:
    """Vrátí název aktivního embedding modelu pro logy/UI."""
    if EMBEDDING_BACKEND == "openai":
        return OPENAI_EMBED_MODEL
    return EMBED_MODEL


# ---------------------------------------------------------------------------
# Qdrant (vektorová databáze)
# ---------------------------------------------------------------------------
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "raiffeisenbank_docs")
# Dimenze se řídí embedding backendem; env override ponechán pro custom modely.
QDRANT_VECTOR_SIZE: int = int(os.getenv("QDRANT_VECTOR_SIZE", str(get_embedding_vector_size())))

# ---------------------------------------------------------------------------
# LLM backend – "ollama" (lokální) | "anthropic" | "gemini" | "openai"
# ---------------------------------------------------------------------------
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "ollama")

# ---------------------------------------------------------------------------
# Ollama (lokální LLM + embeddings)
# Ollama (lokální LLM + volitelně embeddings); LLM jen pokud LLM_BACKEND == "ollama"
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2")

# ---------------------------------------------------------------------------
# Anthropic API (aktivní pouze pokud LLM_BACKEND == "anthropic")
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# claude-haiku-4-5-20251001 je nejrychlejší a nejlevnější Haiku model
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# ---------------------------------------------------------------------------
# Google Gemini API (aktivní pouze pokud LLM_BACKEND == "gemini")
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
# gemini-2.0-flash: rychlý, zdarma, 1M token kontext (1.5-flash není v google-genai SDK)
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ---------------------------------------------------------------------------
# OpenAI Chat API (aktivní pouze pokud LLM_BACKEND == "openai")
# ---------------------------------------------------------------------------
# Primary and fast model configuration – used by the routing layer to select
# the appropriate model for a given answer strategy.  The historic
# ``OPENAI_CHAT_MODEL``/``OPENAI_CHAT_FALLBACK_MODEL`` pair is retained for
# backward‑compatibility but the new variables are preferred.
PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "gpt-5.5-pro")
FAST_MODEL: str = os.getenv("FAST_MODEL", "gpt-5.4-mini-fast")

# Legacy defaults – kept so existing deployments that only set the old env
# variables continue to work.
OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", PRIMARY_MODEL)
OPENAI_CHAT_FALLBACK_MODEL: str = os.getenv("OPENAI_CHAT_FALLBACK_MODEL", "gpt-4o-mini")

# ---------------------------------------------------------------------------
# LLM timeouty a retry
# ---------------------------------------------------------------------------
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

# ---------------------------------------------------------------------------
# Chunking dokumentů
# ---------------------------------------------------------------------------
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))
# Oddělovače pro RecursiveCharacterTextSplitter (priorita sestupně)
CHUNK_SEPARATORS: list[str] = ["\n\n", "\n", ". ", " ", ""]

# ---------------------------------------------------------------------------
# Retrieval pipeline
# ---------------------------------------------------------------------------
BM25_TOP_K: int = 20       # Počet kandidátů z BM25 (sparse)
VECTOR_TOP_K: int = 20     # Počet kandidátů z Qdrant (dense)
HYBRID_TOP_K: int = 5      # Počet výsledků po RRF fúzi
RERANK_TOP_K: int = 5      # Finální počet výsledků po rerankingu
RRF_K: int = 60            # Konstanta pro Reciprocal Rank Fusion

# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------
RERANKER_MODEL: str = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANKER_DEVICE: str = os.getenv("RERANKER_DEVICE", "cpu")  # "cuda" pro GPU
# Minimální skóre cross-encoderu pro zachování dokumentu ve výsledcích.
# ms-marco-MiniLM-L-6-v2 vrací raw logity (bez sigmoid), typicky -10 až +10.
# Hodnota 0.0 odfiltruje negativní skóre (jednoznačně irelevantní dokumenty).
RERANK_MIN_SCORE: float = float(os.getenv("RERANK_MIN_SCORE", "-10.0"))

# ---------------------------------------------------------------------------
# Persistence lokálních indexů
# ---------------------------------------------------------------------------
BM25_INDEX_PATH: Path = INDEX_DIR / "bm25_index.pkl"
DOCS_STORE_PATH: Path = INDEX_DIR / "documents.pkl"

# ---------------------------------------------------------------------------
# Generování odpovědí
# ---------------------------------------------------------------------------
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))
CONVERSATION_HISTORY_LIMIT: int = 6  # Počet posledních zpráv v historii

# ---------------------------------------------------------------------------
# Response cache (Priority 1) — route-specific TTLs
# ---------------------------------------------------------------------------
CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "500"))

# ---------------------------------------------------------------------------
# Redis / distributed storage (Priority 1)
# ---------------------------------------------------------------------------
# Master switch — set to "1" to enable Redis-backed storage.
# When Redis is unavailable, all storage falls back gracefully to in-memory.
# Individual feature flags for finer control:
USE_REDIS_CACHE: bool = _env_bool("USE_REDIS_CACHE", "true")
USE_REDIS_SESSIONS: bool = _env_bool("USE_REDIS_SESSIONS", "true")
REDIS_ENABLED: bool = _env_bool("REDIS_ENABLED", "false")

# Redis connection — REDIS_URL takes priority; if set, HOST/PORT/PASSWORD/DB ignored.
REDIS_URL: str = os.getenv("REDIS_URL", "")
REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD: str | None = os.getenv("REDIS_PASSWORD", None)
REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
REDIS_TIMEOUT: int = int(os.getenv("REDIS_TIMEOUT", "3"))  # socket connect timeout

# Namespace prefix for all Redis keys
REDIS_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX", "rag:")

# Session store TTL (seconds)
REDIS_SESSION_TTL: int = int(os.getenv("REDIS_SESSION_TTL", "3600"))     # 1h

# Per-strategy cache TTLs (seconds)
REDIS_CACHE_TTL_IDENTITY: int = int(os.getenv("REDIS_CACHE_TTL_IDENTITY", "86400"))       # 24h
REDIS_CACHE_TTL_OVERVIEW: int = int(os.getenv("REDIS_CACHE_TTL_OVERVIEW", "21600"))       # 6h
REDIS_CACHE_TTL_PRICING: int = int(os.getenv("REDIS_CACHE_TTL_PRICING", "900"))           # 15 min

# ---------------------------------------------------------------------------
# Response cache — legacy per-route TTLs (used by cache.py)
# ---------------------------------------------------------------------------
CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "500"))
CACHE_TTL_IDENTITY: int = int(os.getenv("CACHE_TTL_IDENTITY", "86400"))       # 24h
CACHE_TTL_OVERVIEW: int = int(os.getenv("CACHE_TTL_OVERVIEW", "21600"))       # 6h
CACHE_TTL_SOFT_GUIDANCE: int = int(os.getenv("CACHE_TTL_SOFT_GUIDANCE", "3600"))   # 1h
CACHE_TTL_PROCEDURAL: int = int(os.getenv("CACHE_TTL_PROCEDURAL", "3600"))    # 1h
CACHE_TTL_PRICING: int = int(os.getenv("CACHE_TTL_PRICING", "900"))           # 15 min

# ---------------------------------------------------------------------------
# Telemetry (JSONL event log)
# ---------------------------------------------------------------------------
TELEMETRY_ENABLED: bool = _env_bool("TELEMETRY_ENABLED", "false")
TELEMETRY_LOG_PATH: str = os.getenv("TELEMETRY_LOG_PATH", "logs/telemetry.jsonl")
TELEMETRY_QUERY_LOGGING: str = os.getenv("TELEMETRY_QUERY_LOGGING", "hashed").strip().lower()
# TELEMETRY_QUERY_LOGGING: "full" | "hashed" | "none"

# ---------------------------------------------------------------------------
# Security / hardening
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
RATE_LIMIT_ENABLED: bool = _env_bool("RATE_LIMIT_ENABLED", "false")
RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
MAX_REQUEST_BODY_BYTES: int = int(os.getenv("MAX_REQUEST_BODY_BYTES", "10000"))  # 10 KB

# ---------------------------------------------------------------------------
# Zdroje PDF dokumentů Raiffeisenbank
# ---------------------------------------------------------------------------
# Výchozí seznam URL pro stažení (lze přepsat souborem data/sources.txt)
DEFAULT_PDF_URLS: list[str] = [
    # Aktuální URL lze doplnit z rb.cz/dokumenty
    # Příklady struktury – ověřte aktuálnost na rb.cz před spuštěním ingestion
    "https://www.rb.cz/attachments/sazebniky/sazebnik-fyzicke-osoby.pdf",
    "https://www.rb.cz/attachments/sazebniky/sazebnik-produkty-a-sluzby.pdf",
]
