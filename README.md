# RAG Banking Chatbot — Raiffeisenbank

> Production-ready Retrieval-Augmented Generation chatbot for Czech banking customer support. Answers questions about Raiffeisenbank products, fees, mortgages, and terms using public PDF documents — entirely locally or via cloud LLM APIs.

---

## Features

- **Hybrid retrieval** — BM25 sparse + Qdrant dense vectors fused with Reciprocal Rank Fusion
- **Cross-encoder reranking** — BGE-Reranker-v2-m3 for precise final ranking
- **Three LLM backends** — Ollama (local), Anthropic Claude, Google Gemini with auto model discovery
- **Web scraper** — sitemap-driven crawler for rb.cz PDFs and FAQ pages with robots.txt compliance
- **FastAPI REST API** — `/chat`, `/health`, `/collections` endpoints with per-session conversation memory
- **Interactive CLI** — conversational chat with source citations and debug mode
- **Czech language** — prompts, cleaning pipeline, and tokenization tuned for Czech banking text

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION PIPELINE                           │
│                                                                     │
│  rb.cz ──► Scraper ──► PDF Downloader ──► Parser ──► Chunker       │
│             (sitemap)   (retry, idempotent) (PyMuPDF)  (recursive)  │
│                                                   │                 │
│                                            ┌──────▼──────┐         │
│                                            │   Indexer   │         │
│                                            │ Qdrant+BM25 │         │
│                                            └──────┬──────┘         │
└───────────────────────────────────────────────────┼─────────────────┘
                                                    │
┌───────────────────────────────────────────────────▼─────────────────┐
│                         QUERY PIPELINE                              │
│                                                                     │
│  Question ──► Query Rewrite ──► Hybrid Search ──► RRF Fusion       │
│               (if follow-up)    BM25 + Qdrant                      │
│                                      │                             │
│                              BGE Reranker (cross-encoder)          │
│                                      │                             │
│                    ┌─────────────────┼──────────────────┐          │
│                    │ Ollama (local)  │ Anthropic Claude │ Gemini   │
│                    └─────────────────┼──────────────────┘          │
│                                      │                             │
│                                 Czech Answer + Sources             │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Technology | Purpose |
|---|---|---|
| **Embeddings** | nomic-embed-text (Ollama) | 768-dim dense vectors |
| **Vector DB** | Qdrant | Dense retrieval with cosine similarity |
| **Sparse retrieval** | BM25 (rank-bm25) | Exact keyword matching |
| **Fusion** | Reciprocal Rank Fusion | Combines dense + sparse rankings |
| **Reranker** | BGE-Reranker-v2-m3 | Cross-encoder final scoring |
| **LLM — local** | Ollama (Mistral, Llama 3.2) | No cloud dependency |
| **LLM — cloud** | Anthropic claude-haiku-4-5 | Fast, with prompt caching |
| **LLM — cloud** | Google Gemini 2.5 Flash | Auto-discovers best available model |
| **PDF parsing** | PyMuPDF + pdfplumber fallback | Czech text extraction and cleaning |
| **Chunking** | RecursiveCharacterTextSplitter | Overlapping context-aware chunks |
| **API** | FastAPI + uvicorn | REST interface with session management |
| **Scraper** | requests + BeautifulSoup4 | Sitemap-driven, robots.txt compliant |

---

## Quick Start

### Prerequisites

```bash
# 1. Ollama — local LLM inference and embeddings
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text   # required for all backends
ollama pull llama3.2           # required only for LLM_BACKEND=ollama

# 2. Qdrant — vector database
docker run -d -p 6333:6333 qdrant/qdrant

# 3. Python dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env — see Configuration section below
```

### Scrape documents

```bash
# Discover and download PDFs from rb.cz (respects robots.txt, ~1-3s delay)
python scripts/scrape_rb.py

# Dry run — only writes sources.txt, no downloads
python scripts/scrape_rb.py --dry-run
```

### Build the index

```bash
# Embed, index into Qdrant, build BM25 index
python scripts/ingest.py

# Re-index existing PDFs without re-downloading
python scripts/ingest.py --skip-download
```

### Chat

```bash
# Interactive CLI
python scripts/chat.py

# With source citations
python scripts/chat.py --show-sources

# REST API
python scripts/serve.py
# → http://127.0.0.1:8000/docs
```

---

## LLM Backends

Switch backends by setting `LLM_BACKEND` in `.env`. Embeddings always run locally via Ollama regardless of backend.

### Ollama (default — fully local)

```bash
LLM_BACKEND=ollama
LLM_MODEL=llama3.2        # or: mistral, llama3.1, phi3, etc.
OLLAMA_BASE_URL=http://localhost:11434
```

No API keys required. All inference runs on your hardware.

### Anthropic Claude Haiku

```bash
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

Uses ephemeral **prompt caching** on the system message, reducing cost on follow-up questions with similar retrieved context.

### Google Gemini (with auto model discovery)

```bash
LLM_BACKEND=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash   # triggers auto-discovery at startup
```

At startup, `discover_gemini_model()` calls `client.models.list()` and picks the best available model in priority order:

```
gemini-2.5-flash-preview-05-20 → gemini-2.5-flash → gemini-2.0-flash → gemini-2.0-flash-001 → …
```

Set `GEMINI_MODEL` to a specific name (e.g. `gemini-2.5-flash`) to skip discovery and pin the model.

> **Note:** `google-generativeai` is deprecated. This project uses the official successor `google-genai`.

---

## REST API

```bash
python scripts/serve.py --host 0.0.0.0 --port 8000
# Swagger UI: http://localhost:8000/docs
```

### `POST /chat`

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Jaký je poplatek za vedení běžného účtu?", "session_id": null}'
```

```json
{
  "answer": "Poplatek za vedení běžného účtu eKonto je...",
  "sources": [
    {
      "file_name": "cenik-pi-1.pdf",
      "page": 3,
      "chunk_id": "a1b2c3d4",
      "rerank_score": 0.9821,
      "preview": "Měsíční poplatek za vedení účtu..."
    }
  ],
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "processing_time_ms": 3241.7
}
```

Follow-up questions reuse `session_id` — the chain rewrites the query with conversation context before retrieval.

### `GET /health`

Returns component status for all active backends. `"anthropic"` and `"gemini"` fields are `null` when inactive.

```json
{
  "status": "ok",
  "qdrant":     {"status": "ok", "detail": "'raiffeisenbank_docs': 18700 bodů"},
  "ollama":     {"status": "ok", "detail": "embeddings OK: ['nomic-embed-text:latest']"},
  "bm25_index": {"status": "ok", "detail": "bm25_index.pkl (19.0 MB)"},
  "anthropic":  null,
  "gemini":     {"status": "ok", "detail": "Model 'gemini-2.5-flash' dostupný (2 tokenů/test)"}
}
```

### `GET /collections`

```json
{
  "name": "raiffeisenbank_docs",
  "points_count": 18700,
  "indexed_vectors_count": 17600,
  "status": "green",
  "vector_size": 768,
  "distance_metric": "Cosine"
}
```

---

## CLI Chatbot

```bash
python scripts/chat.py [OPTIONS]

Options:
  --show-sources    Print source citations after every answer
  --debug           Show retrieval scores (hybrid, rerank) and rewritten queries
  --no-history      Disable conversational memory (stateless Q&A)

In-chat commands:
  /reset            Clear conversation history
  /sources          Toggle source display
  /debug            Toggle debug mode
  /quit             Exit
```

**Example session:**

```
Vy: Jaké jsou podmínky pro hypotéku?
Asistent: Raiffeisenbank nabízí hypoteční úvěry od 200 000 Kč...
          [Zdroj 1: hypoteky-podminky.pdf, str. 2]

Vy: A jaká je maximální splatnost?
Asistent: Maximální splatnost hypotečního úvěru je 30 let...
```

---

## Web Scraper

```bash
python scripts/scrape_rb.py [OPTIONS]

Options:
  --max-pages INT     Crawl limit (default: 600)
  --delay FLOAT       Fixed request delay in seconds (default: random 1–3s)
  --dry-run           Write sources.txt only, do not download
  --no-download       Discover URLs only, skip PDF download
  --no-faq            Skip FAQ page text extraction
```

**How it works:**

1. Fetches `robots.txt` and parses allowed paths
2. Loads `sitemap.xml` → 2 300+ Czech-language URLs
3. Scores URLs by banking keywords (sazebník, podmínky, FAQ, hypotéka…)
4. Crawls priority pages, extracts PDF links via `<a href>`, data attributes, and inline JS regex
5. Detects FAQ pages by URL pattern and `<details>` accordion structure; saves as `.txt`
6. Downloads PDFs to `data/raw/`, writes categorised `data/sources.txt`

---

## Project Structure

```
rag-banking-chatbot/
│
├── config.py                    # Central configuration (all env-overridable)
├── requirements.txt
├── .env.example                 # Template — copy to .env
│
├── scripts/
│   ├── scrape_rb.py             # Sitemap-driven web scraper for rb.cz
│   ├── ingest.py                # Ingestion pipeline CLI
│   ├── chat.py                  # Interactive terminal chatbot
│   └── serve.py                 # FastAPI server launcher (uvicorn)
│
├── src/
│   ├── ingestion/
│   │   ├── downloader.py        # HTTP downloader with retry + idempotency
│   │   ├── parser.py            # PDF text extraction (PyMuPDF + pdfplumber)
│   │   ├── chunker.py           # RecursiveCharacterTextSplitter + chunk IDs
│   │   └── indexer.py           # Qdrant upsert + BM25 pickle index
│   │
│   ├── retrieval/
│   │   ├── bm25_retriever.py    # Sparse BM25 search
│   │   ├── vector_retriever.py  # Dense Qdrant search (query_points API)
│   │   ├── hybrid.py            # RRF fusion (weighted, k=60)
│   │   ├── reranker.py          # BGE cross-encoder reranking
│   │   └── retriever.py         # LangChain BaseRetriever orchestration
│   │
│   ├── generation/
│   │   ├── prompts.py           # Czech system prompts + context formatting
│   │   └── chain.py             # BankingRAGChain + OllamaLLM / AnthropicLLM /
│   │                            #   GeminiLLM + discover_gemini_model()
│   │
│   ├── api/
│   │   └── main.py              # FastAPI app — /chat, /health, /collections
│   │
│   └── utils/
│       └── logger.py            # Rich-formatted logger
│
└── data/
    ├── raw/                     # Downloaded PDFs + extracted FAQ .txt files
    ├── indexes/                 # BM25 index + document store (pickle)
    └── sources.txt              # Auto-generated PDF URL list (scraper output)
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | `ollama` | LLM provider: `ollama` \| `anthropic` \| `gemini` |
| `LLM_MODEL` | `llama3.2` | Ollama model name (ollama backend only) |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model (always via Ollama) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (anthropic backend) |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model ID |
| `GEMINI_API_KEY` | — | Google AI Studio API key (gemini backend) |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model; default triggers auto-discovery |
| `QDRANT_HOST` | `localhost` | Qdrant server host |
| `QDRANT_PORT` | `6333` | Qdrant REST API port |
| `QDRANT_COLLECTION` | `raiffeisenbank_docs` | Qdrant collection name |
| `CHUNK_SIZE` | `1000` | Max chunk size in characters |
| `CHUNK_OVERLAP` | `200` | Overlap between adjacent chunks |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | HuggingFace cross-encoder model |
| `RERANKER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `LLM_TEMPERATURE` | `0.1` | Generation temperature (low = factual) |
| `LLM_MAX_TOKENS` | `1024` | Max output tokens per response |

---

## Design Decisions

**Why hybrid retrieval?**
BM25 excels at exact matches — product codes, Czech abbreviations (RPSN, ČNB), specific fee amounts. Dense retrieval captures semantic equivalents — "jak otevřít účet" ≈ "zřízení bankovního konta". RRF combines rank orders without score normalization, making it robust to score distribution differences.

**Why a cross-encoder reranker?**
Bi-encoders encode query and document independently; cross-encoders see both together and produce significantly more accurate relevance scores. The cost is linear with candidate count, so reranking runs after pre-filtering to top-10 candidates only.

**Why `query_points` instead of `search`?**
`qdrant-client ≥ 1.14` removed the `search()` method. `query_points()` is the universal replacement — it accepts a dense vector directly and returns results under `.points`.

**Why prompt caching on Anthropic?**
The system prompt contains static banking assistant instructions followed by dynamic retrieved context. Marking it `cache_control: ephemeral` caches the entire block. On follow-up questions retrieving the same documents, the cached tokens cost ~0.1× the standard input price.

**Why `google-genai` instead of `google-generativeai`?**
`google-generativeai` reached end-of-life and no longer receives updates. `google-genai` is the official successor with support for Gemini 2.x models.

---

## Extending the Project

**Add a new LLM backend**

1. Implement a class with `invoke(messages: list[BaseMessage]) -> str`
2. Add a branch to `_build_llm()` in `src/generation/chain.py`
3. Add a `_check_<backend>()` function and `<backend>: ComponentStatus | None` field in `src/api/main.py`

**Use GPU for reranking**

```bash
# .env
RERANKER_DEVICE=cuda
```

**Add a Streamlit UI**

```bash
pip install streamlit
# Point at http://localhost:8000/chat via API calls
```

**Swap the embedding model**

Update `EMBED_MODEL` and `QDRANT_VECTOR_SIZE` in config, then re-run `scripts/ingest.py` to rebuild the index.

---

## License

MIT — free for commercial and non-commercial use.

---

*Portfolio project demonstrating production-quality RAG with hybrid retrieval, multi-backend LLM support, and a web scraping pipeline. Not an official Raiffeisenbank a.s. product.*
