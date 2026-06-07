# RAG Banking Chatbot — Technická architektura

Konverzační AI asistent pro zákaznickou podporu Raiffeisenbank (ČR).
Odpovídá na dotazy o produktech, poplatcích a službách banky výhradně z ověřených interních zdrojů.

---

## 1. Architektura systému

```
┌──────────────────────────────────────────────────────────────────────┐
│  UŽIVATEL (prohlížeč)                                                │
│  SvelteKit frontend  ←→  POST /chat  ←→  GET /health                │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ SSE streaming / JSON
┌─────────────────────────────▼────────────────────────────────────────┐
│  FastAPI  (src/api/main.py)                                          │
│  • Session management (UUID per konverzaci, LRU eviction)            │
│  • asyncio.to_thread() — sync chain neblokuje event loop             │
│  • Rate limiting, CORS, request size guard                           │
│  • Streaming: SSE (start → token → done)                             │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────────┐
│  BankingRAGChain  (src/generation/chain.py  ~3 800 řádků)            │
│                                                                      │
│  Pre-retrieval routing (deterministické, bez LLM):                   │
│  1. identity_direct     — "Kdo jsi?" → pevná odpověď                │
│  2. procedural_flow     — "Jak změním PIN?" → pevný postup           │
│  3. soft_guidance_direct— "Jaké účty máte?" → pevná FAQ odpověď      │
│  4. unsupported         — "Bitcoin?" → odmítnutí mimo scope          │
│                                                                      │
│  Retrieval → Rerank → LLM cesta:                                     │
│  5. BankingRetriever    — hybrid BM25 + Qdrant + RRF + rerank        │
│  6. LLM (OpenAI/Ollama) — generuje odpověď z context chunků         │
│  7. Response cache      — Redis (per-strategy TTL)                   │
└──────────┬──────────────────────────────────────┬────────────────────┘
           │                                      │
┌──────────▼──────────┐              ┌────────────▼───────────────────┐
│  BankingRetriever   │              │  Redis                         │
│  retriever.py       │              │  • Response cache (TTL 15min-  │
│                     │              │    24h per strategy)           │
│  1. classify_query  │              │  • Session store (konv. hist.) │
│     → labels, URLs  │              └────────────────────────────────┘
│  2. expand_query    │
│     → BM25 varianta │
│  3. hybrid_search   │
│     BM25 (rank-bm25)│──→ RRF fusion (k=60) ←──── Qdrant dense
│     Qdrant (768/    │                              (nomic-embed-text
│     1536 dim)       │                               nebo OpenAI)
│  4. rerank          │
│     NVIDIA NIM nebo │
│     BGE CrossEncoder│
└─────────────────────┘
```

---

## 2. Data pipeline

### Zdroje dat

```
rb.cz/osobni/          ←─ Playwright Docker crawl (JS-rendered pages)
rb.cz/podpora/         ←─ requests + BeautifulSoup (statické stránky)
rb.cz/attachments/     ←─ PDF stažení (sazebníky, podmínky)
data/pricing/          ←─ Strukturovaná cenová data (pricing_rows.jsonl)
```

### Průběh ingestion

```
scripts/crawl_playwright_full.py   -- Playwright v Docker kontejneru
  mcr.microsoft.com/playwright/python:v1.44.0-jammy
  → rb_pwfull_*.txt  (raw HTML obsah, batch po URL skupinách)

scripts/crawl_rb.py / crawl_rb_requests.py
  → data/crawl/structured/*.json   (strukturovaný obsah stránek)

src/ingestion/downloader.py        -- stahování PDF souborů
src/ingestion/parser.py            -- PyMuPDF (primární) + pdfplumber (záloha)
  → list[Document] se stránkovými metadaty

src/ingestion/enterprise.py        -- enterprise loader
  _is_bad_table_row()              -- filtruje PDF garbage + nav boilerplate
  detect_chunk_quality()           -- "ok" | "bad_pdf_extraction" | "navigation_boilerplate"

src/ingestion/chunker.py           -- RecursiveCharacterTextSplitter
  chunk_size=1000 znaky, overlap=200
  _make_chunk_id()                 -- SHA-256 deterministické ID

src/ingestion/indexer.py           -- uložení do Qdrant + BM25
  filter_new_chunks()              -- přeskočí duplikáty (chunk_id) + bad quality
  Embedding: nomic-embed-text (768 dim) nebo text-embedding-3-small (1536 dim)
  BM25: rank-bm25, serializovaný pickle (~80 MB)
  Qdrant: ~99 000 chunků v kolekci raiffeisenbank_docs
```

### Strukturovaná cenová data

```
src/ingestion/pricing_extractor.py
  → data/pricing/pricing_rows.jsonl  (359 řádků)
  → indexovány jako pricing_row chunk type s metadaty:
    product_name, fee_type, fee_value, currency, period
```

---

## 3. Query pipeline — krok za krokem

Příklad: uživatel napíše *"Jaký je poplatek za vedení AKTIVNÍHO účtu?"*

```
1. POST /chat  { question: "...", session_id: "uuid" }
   └─ FastAPI ověří session, vytvoří/načte BankingRAGChain instanci

2. normalize_query()                         [query_classifier.py]
   "jaký je poplatek za vedení aktivního účtu"  (lowercase + fix překlepů)

3. classify_query()                          [query_classifier.py]
   labels = {"pricing", "retail_banking", "personal_retail_account"}
   preferred_url_contains = ("/osobni/ucty/", "/sazebnik")
   bm25_weight = 0.4, vector_weight = 0.6

4. Pre-retrieval check                       [chain.py]
   → není identity / procedural / soft_guidance → jde do retrieval

5. expand_query()                            [query_classifier.py]
   query → "poplatek vedení AKTIVNÍ účet sazebník"  (BM25-optimalizovaná)

6. hybrid_search()                           [hybrid.py]
   ├─ bm25_search(query_expanded, top_k=20)  [bm25_retriever.py]
   │   _strip_diacritics() → přidá verzi bez háčků do query
   │   → 20 kandidátů (rank-bm25 TF-IDF scoring)
   └─ vector_search(query, top_k=20)         [vector_retriever.py]
       nomic-embed-text embed → Qdrant cosine similarity
       → 20 kandidátů
   
   RRF fusion: score = Σ 1/(60 + rank)
   → top 5 dokumentů po fúzi

7. rerank()                                  [reranker.py]
   NVIDIA NIM llama-nemotron-rerank-vl-1b-v2  (primární, ~300ms)
   nebo BAAI/bge-reranker-v2-m3 CrossEncoder  (CPU fallback)
   → top 5 finálních chunků s rerank_score

8. source_governance, url_product_filter     [source_governance.py]
   → filtruje off-topic dokumenty, penalizuje archivní zdroje

9. LLM generování                            [chain.py + prompts.py]
   System prompt: "Odpovídej výhradně z kontextu, vždy česky..."
   Context: 5 chunků + chat_history (posledních 6 zpráv)
   Model: gpt-5.5-pro (fallback: gpt-4o-mini) nebo Ollama lokálně
   Streaming: SSE token po tokenu

10. Response cache (Redis)
    key = hash(question + labels)
    TTL: pricing=15min, identity=24h, soft_guidance=1h
    
11. POST /chat odpověď:
    { answer, sources, answer_strategy, confidence_bucket,
      processing_time_ms, retrieval_latency_ms, llm_latency_ms }
```

---

## 4. Klíčové soubory

| Soubor | Co dělá |
|--------|---------|
| `src/api/main.py` | FastAPI server, session management, SSE streaming, health check |
| `src/generation/chain.py` (~3 800 ř.) | Centrální orchestrátor: routing, retrieval, LLM, caching. Obsahuje všechny deterministické odpovědi (SOFT_GUIDANCE_ANSWERS, PROCEDURAL_FLOW_ANSWERS) |
| `src/generation/prompts.py` | System prompt + LangChain ChatPromptTemplate s historií |
| `src/generation/pricing_response_formatter.py` | Formátování strukturovaných cenových odpovědí |
| `src/generation/comparison_engine.py` | Detekce a zpracování srovnávacích dotazů (CHYTRÝ vs. AKTIVNÍ) |
| `src/retrieval/query_classifier.py` (~1 900 ř.) | `classify_query()` → labels + URL preference; `normalize_query()` → fix překlepů; `expand_query()` → BM25 obohacení |
| `src/retrieval/retriever.py` | `BankingRetriever` (LangChain BaseRetriever): orchestrace hybrid search → rerank → filtrování |
| `src/retrieval/hybrid.py` | RRF fúze BM25 + Qdrant výsledků |
| `src/retrieval/bm25_retriever.py` | `bm25_search()` s query expansion (strip diakritiky), `_tokenize()` |
| `src/retrieval/vector_retriever.py` | Qdrant cosine similarity search |
| `src/retrieval/reranker.py` | NVIDIA NIM (primární) + BGE CrossEncoder (CPU fallback) |
| `src/retrieval/source_governance.py` | Filtrování a penalizace zdrojů |
| `src/ingestion/enterprise.py` | Enterprise loader: web crawl → strukturované chunky, detekce nav boilerplate |
| `src/ingestion/indexer.py` | `filter_new_chunks()` (dedup + quality), Qdrant upsert, BM25 rebuild |
| `src/ingestion/chunker.py` | RecursiveCharacterTextSplitter, deterministické chunk_id |
| `src/ingestion/pricing_extractor.py` | Extrakce strukturovaných poplatků z PDF/HTML |
| `src/storage/redis_impl.py` | Redis-backed session store + response cache |
| `config.py` | Všechny parametry (chunk size, top_k hodnoty, TTL, embedding backend) |
| `frontend/src/lib/components/Chat.svelte` | Hlavní chat UI, SSE streaming, konverzační stav |
| `frontend/src/lib/components/Sidebar.svelte` | Collapsible history sidebar |
| `frontend/src/lib/stores.ts` | Svelte stores: messages, conversations, sidebarCollapsed |

---

## 5. Problémy které jsme řešili

### P1: JS-rendered stránky vracely jen navigační menu
**Problém:** `requests` crawler zachytil pouze statické HTML — stránky jako `/podpora/platebni-karty/pin-ke-karte` obsahovaly po parsování jen navigační menu (Účty a karty / Půjčky / Spoření...) namísto obsahu.

**Detekce:** 692 chunků z bezne-ucty a pin-ke-karte měly v Qdrant identický obsah — navigační boilerplate.

**Řešení:**
- Playwright Docker crawl: `mcr.microsoft.com/playwright/python:v1.44.0-jammy` renderuje JS před scrapováním
- `detect_chunk_quality()` v `query_classifier.py`: detekuje nav boilerplate signaturou (≥3 z {"účty a karty", "půjčky", "spoření a investice"...} + délka < 500 znaků)
- `filter_new_chunks()` v `indexer.py`: při ingestion přeskočí `navigation_boilerplate` a `bad_pdf_extraction`
- 125 existujících nav chunků smazáno z Qdrant

### P2: PIN dotazy vracely špatné odpovědi
**Problém:** "jak nastavím PIN ke kartě" → retrieval vrátil navigační chunky místo support stránky.

**Příčina:** `preferred_urls=('/karty',)` pro label `cards` přesměrovával na produktové stránky, nikoli support. Support stránky `/podpora/` nikdy nedosáhly top 10.

**Řešení:** `pin_flow` v `PROCEDURAL_FLOW_PATTERNS` — deterministická odpověď před retrieval, obsahuje přesný postup (mobilní app → Karty → PIN karty).

### P3: "podmínky pro účet" → 0 výsledků
**Problém:** BM25 token "podmínky" matchoval smluvní podmínky PDF, nikoli stránku o otevření účtu. Vector retrieval bez BM25 overlap nevytlačil správné dokumenty do top 5.

**Řešení:** `ucet_zalozeni_online` soft_guidance pattern zachytí celou skupinu dotazů (podmínky/dokumenty/co potřebuji/jak si otevřu) a vrátí deterministickou odpověď s podmínkami (18+, OP/pas) a 5-krokovým postupem.

### P4: Dotazy bez diakritiky nezasáhly správné dokumenty
**Problém:** "jake mam moznosti sporeni" → BM25 hledal token `"sporeni"`, ale index obsahuje `"spoření"` → 0 BM25 score.

**Řešení — dvě vrstvy:**
1. `normalize_query()` v `query_classifier.py`: mappe časté ASCII varianty na správné české formy (`"pujcit"` → `"půjčit"`, `"ucet"` → `"účet"`)
2. `_strip_diacritics()` + query expansion v `bm25_search()`: query se rozšíří o variantu bez diakritiky → BM25 matchuje oba tvary

### P5: "jak reklamuji platbu" → 0 výsledků
**Problém:** `COMPLAINT_TERMS` v `query_classifier.py` obsahoval jen substantivum `"reklamac"`, ne slovesné formy.

**Řešení:** Přidány tvary `"reklamovat"`, `"reklamuj"`, `"reklamoval"` → label `complaints` → `expand_query()` obohacuje query o synonyama.

### P6: Soft_guidance dotazy blokovány stale serverem
**Problém:** Nové `SOFT_GUIDANCE_FAQ_PATTERNS` byly přidány, ale server měl v paměti starý kód — redis flush nepomohl.

**Důvod:** Uvicorn načte Python moduly při startu do paměti; `flush` maže pouze cache odpovědí, ne kód.

**Řešení:** Vždy `pkill -f uvicorn && restart` po změně chain.py / query_classifier.py.

---

## 6. Technologie a důvody výběru

| Technologie | Verze | Proč |
|-------------|-------|------|
| **FastAPI** | ≥0.115 | Async, SSE streaming, Pydantic validace, OpenAPI docs zdarma |
| **SvelteKit** | latest | Rychlý dev, menší bundle než React, reactive stores, TypeScript |
| **Qdrant** | latest | Self-hosted vector DB, payload filtering, cosine similarity, Docker |
| **rank-bm25** | ≥0.2.2 | Lightweight BM25, přesné keyword shody (produkty, čísla, zkratky) |
| **RRF (Reciprocal Rank Fusion)** | k=60 | Kombinuje sparse+dense bez normalizace skóre; empiricky ověřeno (Cormack 2009) |
| **NVIDIA NIM reranker** | llama-nemotron-rerank-vl-1b-v2 | Cloud inference bez GPU, ~300ms, výrazně lepší precision než BM25 alone |
| **BGE CrossEncoder** | bge-reranker-v2-m3 | CPU fallback bez API key, multilingual |
| **nomic-embed-text** | Ollama | 768 dim, lokální inference, zdarma; alternativa: OpenAI text-embedding-3-small (1536 dim) |
| **OpenAI GPT** | gpt-5.5-pro / gpt-4o-mini | Primární LLM; fallback na levnější model při chybě |
| **Redis** | 7-alpine | Response cache (TTL per strategy), session persistence, O(1) GET |
| **PyMuPDF (fitz)** | ≥1.24 | Rychlý PDF parser; pdfplumber jako záloha pro tabulky |
| **Playwright** | 1.44.0 | Jediný způsob jak získat JS-rendered obsah z rb.cz |
| **LangChain** | ≥0.3 | RAG orchestrace, chat history, BaseRetriever abstrakce |
| **Tailwind CSS** | v3 | Utility-first, dark mode, rychlý prototyping |

### Embedding backend switch
```
EMBEDDING_BACKEND=ollama   → nomic-embed-text  (768 dim, lokálně, zdarma)
EMBEDDING_BACKEND=openai   → text-embedding-3-small (1536 dim, lepší kvalita)
```
Přepínání vyžaduje re-indexaci (dimenze vektoru se musí shodovat s Qdrant kolekcí).

### LLM backend
```
Primární:  OpenAI gpt-5.5-pro   (nejlepší kvalita, cloud)
Fallback:  gpt-4o-mini          (automatický retry při přetížení)
Alternativa: Ollama lokálně     (soukromí, bez API klíče, pomalejší)
Anthropic/Gemini: volitelné, konfigurované přes .env
```

---

## 7. Infrastruktura (Docker Compose)

```yaml
services:
  redis:   redis:7-alpine  → port 6379  (cache + sessions, AOF persistence)
  qdrant:  qdrant/qdrant   → port 6333  (vector store, volume mount)
  backend: ./Dockerfile    → port 8000  (FastAPI + uvicorn)
  frontend: ./frontend     → port 3000  (SvelteKit Node adapter)
```

### Klíčové env proměnné
```
OPENAI_API_KEY        — LLM + embeddings (OpenAI backend)
NVIDIA_API_KEY        — NVIDIA NIM reranker (volitelné, fallback na CPU)
EMBEDDING_BACKEND     — "ollama" | "openai"
REDIS_ENABLED         — "true" pro distribuovaný cache
QDRANT_HOST           — hostname Qdrant instance
```

---

## 8. Metriky projektu

| Metrika | Hodnota |
|---------|---------|
| Chunků v Qdrant | ~99 000 |
| BM25 index | ~99 000 dokumentů, ~80 MB |
| Git commits | 143+ |
| Hlavní Python soubory | ~35 |
| Největší soubor | `chain.py` (~3 800 řádků) |
| Embedding dim | 768 (Ollama) / 1536 (OpenAI) |
| Průměrná latence | ~800ms (cache miss) / <50ms (cache hit) |
| Pre-retrieval pokrytí | ~40 soft_guidance + ~15 procedural flow patterns |
