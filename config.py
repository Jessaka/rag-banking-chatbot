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
# Ollama (lokální LLM + embeddings)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL: str = os.getenv("LLM_MODEL", "mistral")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")

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
HYBRID_TOP_K: int = 10     # Počet výsledků po RRF fúzi
RERANK_TOP_K: int = 5      # Finální počet výsledků po rerankingu
RRF_K: int = 60            # Konstanta pro Reciprocal Rank Fusion

# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------
RERANKER_MODEL: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_DEVICE: str = os.getenv("RERANKER_DEVICE", "cpu")  # "cuda" pro GPU

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
