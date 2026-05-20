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
OPENAI_EMBED_BATCH_SIZE: int = int(os.getenv("OPENAI_EMBED_BATCH_SIZE", "16"))
OPENAI_EMBED_SLEEP_MS: int = int(os.getenv("OPENAI_EMBED_SLEEP_MS", "250"))

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
# Výchozí model: gpt-4.1-mini, fallback: gpt-4o-mini
# API klíč je sdílený s embedding backendem (OPENAI_API_KEY).
# ---------------------------------------------------------------------------
OPENAI_CHAT_MODEL: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
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
RERANK_MIN_SCORE: float = float(os.getenv("RERANK_MIN_SCORE", "0.0"))

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
# Zdroje PDF dokumentů Raiffeisenbank
# ---------------------------------------------------------------------------
# Výchozí seznam URL pro stažení (lze přepsat souborem data/sources.txt)
DEFAULT_PDF_URLS: list[str] = [
    # Aktuální URL lze doplnit z rb.cz/dokumenty
    # Příklady struktury – ověřte aktuálnost na rb.cz před spuštěním ingestion
    "https://www.rb.cz/attachments/sazebniky/sazebnik-fyzicke-osoby.pdf",
    "https://www.rb.cz/attachments/sazebniky/sazebnik-produkty-a-sluzby.pdf",
]
