# ARCHITEKTURA RB Banking RAG chatbotu

## Účel
Tento projekt je RAG chatbot pro bankovní dotazy nad Raiffeisenbank dokumenty. V jádru kombinuje:

- FastAPI backend pro API a orchestrace (`src/api/main.py`),
- SvelteKit frontend pro chat UI (`frontend/src/lib/api.ts`, `frontend/src/routes/+page.svelte`),
- hybridní retrieval nad BM25 + Qdrant (`src/retrieval/*`),
- generování odpovědí přes LLM backendy (`src/generation/chain.py`),
- per-session konverzační paměť a response cache (`src/api/main.py`, `src/generation/cache.py`).

## High-level pohled

```text
Browser / SvelteKit frontend
        |
        | POST /chat nebo /chat/stream
        v
FastAPI (`src/api/main.py`)
  |  - session pool + TTL/LRU
  |  - cache lookup
  |  - telemetry + security middleware
        |
        v
BankingRAGChain (`src/generation/chain.py`)
  |  1) pre-routing (identity, guided, procedural, unsupported, clarification, comparison)
  |  2) query rewrite (pokud je historie)
  |  3) retrieval (`src/retrieval/retriever.py`)
  |  4) overview / catalog / soft guidance
  |  5) LLM fallback
        |
        v
Retrieval layer (`src/retrieval/*`)
  |  BM25 index (`data/indexes/bm25_index.pkl`)
  |  Qdrant collection (`config.QDRANT_COLLECTION`)
  |  RRF fusion + reranking
        |
        v
LLM backend (ollama / anthropic / gemini / openai)
        |
        v
JSON response / SSE stream
```

## Stack

### Backend
- Python 3.12+
- FastAPI (`src/api/main.py`)
- Uvicorn (`scripts/serve.py`, `Dockerfile`)
- Pydantic modely pro request/response schema

### Retrieval
- BM25 index na disku (`config.BM25_INDEX_PATH`, `config.DOCS_STORE_PATH`)
- Qdrant vektorová DB (`config.QDRANT_HOST`, `config.QDRANT_PORT`, `config.QDRANT_COLLECTION`)
- Cross-encoder reranker (`src/retrieval/reranker.py`)

### Frontend
- SvelteKit (`frontend/`)
- API klient v `frontend/src/lib/api.ts`

## Klíčové adresáře

### `src/api/`
REST API, session management, middleware, health checks, SSE endpoint.

### `src/generation/`
RAG chain, route strategie, cache, prompts, confidence semantics, comparison engine.

### `src/retrieval/`
Hybrid retrieval, query classification, authority/freshness/trust scoring, reranking.

### `src/storage/`
Pluggable backend pro cache a session state: in-memory a Redis implementace.

### `frontend/`
SvelteKit UI a klient pro `/chat` a `/chat/stream`.

### `scripts/`
Serve, ingestion, eval, smoke testy, audit nástroje.

### `evals/`
Datasety, gating thresholds a historické eval runy.

## Datový tok

### 1. Dotaz uživatele
Frontend volá `POST /chat` nebo `POST /chat/stream` přes `frontend/src/lib/api.ts`.

### 2. Session a cache
Backend v `src/api/main.py`:

- najde nebo vytvoří session,
- zkusí response cache (`src/generation/cache.py`),
- pokud je cache hit, vrátí hotový výsledek bez nového retrieval/LLM běhu.

### 3. Routing a retrieval
`BankingRAGChain.ask()` v `src/generation/chain.py` nejdřív zpracuje deterministic routing:

- identity,
- guided flows,
- procedural flows,
- unsupported topics,
- clarification,
- comparison.

Pokud dotaz projde do retrieval fáze, použije `BankingRetriever` (`src/retrieval/retriever.py`), který kombinuje:

- BM25 sparse search,
- Qdrant dense search,
- RRF fusion,
- reranking cross-encoderem.

### 4. Generování
Když existuje vhodný overview/catalog/soft-guidance route, chain vrátí deterministickou odpověď bez LLM. Jinak sestaví kontext a zavolá LLM backend.

### 5. Odpověď
API vrátí JSON nebo SSE eventy. Odpověď nese debug metadata: sources, route, confidence, latency a volitelně retrieval debug.

## Deployment možnosti

### Docker
`Dockerfile` startuje backend přes:

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Obraz kopíruje `config.py`, `src/`, `scripts/` a indexová data z `data/indexes` a `data/pricing`.

### Standalone
Pro lokální spuštění je připraven `scripts/serve.py`:

```bash
python3 scripts/serve.py --host 127.0.0.1 --port 8000 --reload
```

## Omezení a produkční poznámky

### Závislosti na datech
Kvalita odpovědí závisí na tom, zda jsou přítomné BM25 indexy a Qdrant kolekce. Health check to ověřuje v `/health`.

### In-memory session state
Výchozí session management je procesní. Při horizontálním škálování je potřeba sticky sessions nebo externí session store.

### Debug / observability
Detailní interní metadata jsou dostupná přes `retrieval_debug`, ale jejich expozice závisí na `config.DEBUG_API_ERRORS`.
