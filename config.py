"""
Centrální konfigurace projektu RAG Banking Chatbot.

Všechny parametry lze přepsat pomocí proměnných prostředí nebo .env souboru.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Cesty
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "indexes"

# ---------------------------------------------------------------------------
# Qdrant (vektorová databáze)
# ---------------------------------------------------------------------------
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "raiffeisenbank_docs")
# Dimenze embeddings modelu nomic-embed-text
QDRANT_VECTOR_SIZE: int = 768

# ---------------------------------------------------------------------------
# LLM backend – "ollama" (lokální) nebo "anthropic" (cloud API)
# ---------------------------------------------------------------------------
LLM_BACKEND: str = os.getenv("LLM_BACKEND", "ollama")  # "ollama" | "anthropic"

# ---------------------------------------------------------------------------
# Ollama (lokální LLM + embeddings)
# Embeddings vždy přes Ollama; LLM jen pokud LLM_BACKEND == "ollama"
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")

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
