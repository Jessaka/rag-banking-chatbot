# RAG Banking Chatbot — Raiffeisenbank

> Production-quality Retrieval-Augmented Generation chatbot for Czech banking customer support. Answers questions about Raiffeisenbank products, fees, cards, and terms using public PDFs and web data — with deterministic pricing lookup, hybrid retrieval, and Redis-backed session caching.

---

## Features

- **Deterministic pricing** — structured `pricing_rows.jsonl` lookup for cards/accounts, no LLM required (~2s cold, ~0.6s warm)
- **Hybrid retrieval** — BM25 sparse (96K docs) + Qdrant dense vectors fused with Reciprocal Rank Fusion
- **NVIDIA NIM reranker** — `llama-nemotron-rerank-vl-1b-v2` via API, BGE CPU fallback
- **SSE streaming** — `/chat/stream` for real-time token streaming with sub-3s first-token for deterministic routes
- **Redis cache** — per-session conversation memory + cross-session response cache (pricing TTL 900s)
- **SvelteKit frontend** — chat UI on port 5173 with dark mode, source cards, confidence badges
- **FastAPI REST API** — `/chat`, `/chat/stream`, `/health`, `/health/deep` with OpenAPI docs

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      INGESTION PIPELINE                         │
│                                                                 │
│  rb.cz ──► Scraper ──► PDF Downloader ──► Parser ──► Chunker   │
│             (sitemap)   (retry, idempotent) (PyMuPDF) (recursive)│
│                                                 │               │
│                                          ┌──────▼──────┐       │
│                                          │   Indexer   │       │
│                                          │ Qdrant+BM25 │       │
│                                          └──────┬──────┘       │
└─────────────────────────────────────────────────┼───────────────┘
                                                  │
┌─────────────────────────────────────────────────▼───────────────┐
│                       QUERY PIPELINE                            │
│                                                                 │
│  Question ──► Classifier ──► Pricing Resolver ──► FAST PATH    │
│                  │              (JSONL rows)    (pricing_row_    │
│                  │                              direct, no LLM) │
│                  └──► Hybrid Search ──► RRF Fusion              │
│                         BM25 + Qdrant                           │
│                              │                                  │
│                    NVIDIA NIM Reranker                          │
│                    (llama-nemotron, API)                        │
│                              │                                  │
│                    OpenAI GPT-5.5-pro                           │
│                    (gpt-4o-mini fast path)                      │
│                              │                                  │
│          Redis Cache  ◄──── Czech Answer + Sources             │
│          (session + response)                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Technology | Notes |
|---|---|---|
| **LLM primary** | OpenAI `gpt-5.5-pro` | timeout 20s, 1 retry |
| **LLM fast** | OpenAI `gpt-4o-mini` | query rewrite, classification |
| **Embeddings** | OpenAI `text-embedding-3-small` | 1536-dim, timeout 15s |
| **Vector DB** | Qdrant | 607 points, cosine similarity |
| **Sparse retrieval** | BM25 (rank-bm25) | 96 341 documents, 78 MB index |
| **Fusion** | Reciprocal Rank Fusion | weighted BM25:0.3–0.65 / vector:0.35–0.7 |
| **Reranker** | NVIDIA NIM `llama-nemotron-rerank-vl-1b-v2` | API; BGE CPU fallback |
| **Pricing lookup** | `pricing_rows.jsonl` (2 554 rows) | deterministic, canonical product matching |
| **Cache** | Redis 7 (Docker) | sessions + response cache, port 6379 |
| **API** | FastAPI + uvicorn | port 8000, SSE streaming |
| **Frontend** | SvelteKit | port 5173, dark mode, SSE |
| **PDF parsing** | PyMuPDF + pdfplumber | Czech text + table extraction |

---

## Quick Start

### Prerequisites

```bash
# 1. Docker — Redis cache
docker run -d --name redis-temp -p 6379:6379 redis:7-alpine

# 2. Python dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Node.js dependencies (frontend)
cd frontend && npm install && cd ..
```

### Configuration

```bash
cp .env.example .env
# Required: OPENAI_API_KEY, PRIMARY_MODEL, OPENAI_EMBED_MODEL
# Optional: NVIDIA_API_KEY (NIM reranker)
```

Key `.env` values:

```bash
LLM_BACKEND=openai
PRIMARY_MODEL=gpt-5.5-pro
OPENAI_API_KEY=sk-...
OPENAI_EMBED_MODEL=text-embedding-3-small

LLM_TIMEOUT=20
LLM_MAX_RETRIES=1
OPENAI_EMBED_TIMEOUT_SECONDS=15

NVIDIA_API_KEY=nvapi-...   # optional — enables NIM reranker
```

### Build the index

```bash
# Structured crawl + PDF download
python3 scripts/crawl_rb.py --max-pages 200 --depth 2
python3 scripts/download_documents.py --category pricing
python3 scripts/download_documents.py --category mortgages

# Ingest into Qdrant + BM25
python3 scripts/ingest.py --enterprise --full
```

### Start everything

```bash
./start.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173
# API docs: http://localhost:8000/docs
```

`start.sh` starts Redis (if not running), uvicorn backend, and SvelteKit dev server.

---

## Performance

| Query type | Cold (no cache) | Warm (Redis hit) |
|---|---|---|
| Pricing (`pricing_row_direct`) | ~2s | ~0.6s |
| Deterministic (catalog, FAQ) | ~0.2s | ~0.06s |
| LLM (hybrid + GPT) | ~3–18s | ~0.6s |
| Stream first token (deterministic) | ~2s | ~0.6s |

BM25 warm-up runs at startup — first non-pricing query after cold start: ~3s (vs. 15s without warm-up).

---

## Capabilities

### What it answers well

- **Credit card pricing** — EASY (free), STYLE (50 Kč/mo), RB PREMIUM (199 Kč/mo), Visa Gold (199 Kč/mo), O2 RB (89 Kč/mo) — deterministic lookup
- **Account fees** — eKonto SMART (99 Kč/mo, conditional free), basic payment account
- **Card catalog** — types of payment cards (debit + credit)
- **Procedural** — how to block a card, online banking setup
- **Mortgage conditions** — from PDF documents (general terms, not live rates)
- **Conversational follow-up** — session context carries product/intent between turns

### Known gaps

- **Live mortgage rates** — individual, not publicly disclosed; answered with honest "data not available"
- **Consumer loans** — data coverage gap in current index
- **Real-time balances/account data** — not connected to banking systems

---

## REST API

### `POST /chat`

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Kolik stojí kreditní karta STYLE?", "session_id": null}'
```

```json
{
  "answer": "Kreditní karty:\n* hlavní karta STYLE: 50 Kč měsíčně",
  "sources": [{"file_name": "pricing_cenik-pi-1_...", "page": null}],
  "session_id": "550e8400-...",
  "answer_strategy": "pricing_row_direct",
  "processing_time_ms": 623.4
}
```

### `POST /chat/stream`

Server-Sent Events — yields `start`, `token`, `answer`, `done` events. Used by the SvelteKit frontend.

```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Co je eKonto SMART?"}'
```

### `GET /health`

```json
{
  "status": "ok",
  "bm25_index": {"status": "ok", "detail": "bm25_index.pkl (78.7 MB)"},
  "qdrant":     {"status": "ok", "detail": "Skipped in fast health; use /health/deep"},
  "redis":      {"status": "ok", "detail": "Redis ping OK (localhost:6379)"},
  "openai":     null
}
```

Use `/health/deep` for full Qdrant + OpenAI + Redis checks.

---

## Project Structure

```
rag-banking-chatbot/
│
├── start.sh                     # One-command start (Redis + backend + frontend)
├── config.py                    # Central configuration (all env-overridable)
├── requirements.txt
├── .env.example                 # Template — copy to .env
│
├── scripts/
│   ├── crawl_rb.py              # Playwright structured crawler: HTML → JSON/MD
│   ├── download_documents.py    # PDF downloader (pricing / mortgages / cards)
│   ├── ingest.py                # Ingestion pipeline CLI
│   ├── debug_dataset.py         # Dataset/chunk diagnostics
│   ├── scrape_rb.py             # Sitemap-driven web scraper
│   ├── chat.py                  # Interactive terminal chatbot
│   └── serve.py                 # FastAPI server launcher (uvicorn wrapper)
│
├── src/
│   ├── ingestion/
│   │   ├── enterprise.py        # Structured/PDF semantic loaders + chunking
│   │   ├── downloader.py        # HTTP downloader with retry + idempotency
│   │   ├── parser.py            # PDF text extraction (PyMuPDF + pdfplumber)
│   │   ├── chunker.py           # RecursiveCharacterTextSplitter + chunk IDs
│   │   ├── indexer.py           # Qdrant upsert + BM25 pickle index
│   │   ├── pricing_extractor.py # Structured pricing row extraction
│   │   └── quality_filters.py   # Chunk quality validation
│   │
│   ├── retrieval/
│   │   ├── pricing_retriever.py # Deterministic pricing lookup (JSONL)
│   │   ├── pricing_resolver.py  # Canonical product matching + scoring
│   │   ├── hybrid.py            # RRF fusion (BM25 + Qdrant, weighted)
│   │   ├── reranker.py          # NVIDIA NIM + BGE CPU fallback
│   │   ├── retriever.py         # BankingRetriever orchestration
│   │   ├── query_classifier.py  # Intent + product label detection
│   │   └── source_governance.py # Source quality + diversity filters
│   │
│   ├── generation/
│   │   ├── chain.py             # BankingRAGChain — ask() + ask_stream()
│   │   ├── llm.py               # OpenAI LLM wrapper (timeout, retry)
│   │   ├── prompts.py           # Czech system prompts + context formatting
│   │   └── confidence_semantics.py # Answer confidence scoring
│   │
│   ├── api/
│   │   └── main.py              # FastAPI app — /chat, /chat/stream, /health
│   │
│   └── storage/
│       ├── redis_impl.py        # Redis cache + session backends
│       └── response_cache.py    # Distributed response cache (Redis + in-memory)
│
├── frontend/                    # SvelteKit chat UI
│   └── src/lib/
│       ├── api.ts               # sendChatMessage() + streamChatMessage()
│       └── components/          # Chat, ChatMessage, SourcesCard, DebugPanel...
│
└── data/
    ├── pricing/
    │   └── pricing_rows.jsonl   # 2 554 structured pricing rows
    ├── documents/               # PDF documents + metadata.jsonl
    ├── crawl/structured/        # Structured JSON/MD from crawler
    ├── indexes/                 # BM25 index + document store (pickle)
    └── raw/                     # Downloaded PDFs + FAQ .txt files
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | `openai` | LLM provider (`openai` only in current deployment) |
| `PRIMARY_MODEL` | `gpt-5.5-pro` | Primary OpenAI chat model |
| `OPENAI_CHAT_FALLBACK_MODEL` | `gpt-4o-mini` | Fallback / fast path model |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `EMBEDDING_BACKEND` | `openai` | Embedding provider |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | OpenAI embedding model (1536 dim) |
| `OPENAI_EMBED_TIMEOUT_SECONDS` | `15` | Embedding request timeout |
| `LLM_TIMEOUT` | `20` | LLM call timeout in seconds |
| `LLM_MAX_RETRIES` | `1` | Max LLM retry attempts |
| `NVIDIA_API_KEY` | — | NVIDIA NIM API key (enables cloud reranker) |
| `QDRANT_HOST` | `localhost` | Qdrant server host |
| `QDRANT_PORT` | `6333` | Qdrant REST API port |
| `QDRANT_COLLECTION` | `raiffeisenbank_docs` | Qdrant collection name |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | BGE fallback reranker model |
| `RERANKER_DEVICE` | `cpu` | `cpu` or `cuda` for BGE reranker |
| `CHUNK_SIZE` | `1000` | Max chunk size in characters |
| `CHUNK_OVERLAP` | `200` | Overlap between adjacent chunks |
| `LLM_TEMPERATURE` | `0.1` | Generation temperature (low = factual) |
| `LLM_MAX_TOKENS` | `1024` | Max output tokens per response |

---

## Design Decisions

**Deterministic pricing over LLM synthesis**
Card and account fees are looked up directly from `pricing_rows.jsonl` using canonical product matching (`detect_query_product`). This eliminates hallucination risk for the most common query type and cuts latency from ~15s to ~2s.

**Why hybrid retrieval?**
BM25 excels at exact matches — product codes, Czech abbreviations (RPSN, ČNB), specific fee amounts. Dense retrieval captures semantic equivalents — "jak otevřít účet" ≈ "zřízení bankovního konta". RRF combines rank orders without score normalization.

**Why NVIDIA NIM reranker?**
`llama-nemotron-rerank-vl-1b-v2` runs on NVIDIA cloud inference and outperforms the BGE CPU cross-encoder for Czech banking text. BGE remains as a local fallback when `NVIDIA_API_KEY` is absent.

**Why suppress Qdrant recovery for structured pricing?**
When the pricing resolver returns structured rows, governance recovery would inject Qdrant docs from unrelated card lists, corrupting the answer. Recovery is disabled when all candidate docs are `structured_pricing=True`.

**BM25 warm-up**
The 78 MB BM25 index takes ~12s to load on first access. A `hypotéka podmínky` warm-up query runs at startup to load it into RAM, reducing first-user latency from 15s to 3s.

---

## License

MIT — free for commercial and non-commercial use.

---

*Portfolio project demonstrating production-quality RAG with hybrid retrieval, deterministic pricing lookup, NVIDIA NIM reranking, Redis caching, and a SvelteKit streaming frontend. Not an official Raiffeisenbank a.s. product.*
