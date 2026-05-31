# Retrieval pipeline

## Přehled
Retrieval je v `src/retrieval/` a v produkčním toku ho řídí `BankingRetriever` (`src/retrieval/retriever.py`).

Pipeline:

1. query classification,
2. deterministický pricing path (když je relevantní),
3. hybrid search = BM25 + Qdrant,
4. RRF fusion,
5. metadata-aware boosting,
6. reranking cross-encoderem,
7. route-specifické fallbacky.

## Hybridní retrieval: BM25 + Qdrant + RRF

### BM25
Sparse search běží přes `bm25_search()`.

### Dense search
Vektorové vyhledávání běží přes `vector_search()` nad Qdrant kolekcí.

### RRF fúze
`src/retrieval/hybrid.py` používá Reciprocal Rank Fusion:

```text
RRF(d) = Σ 1 / (k + rank(d))
```

`k` je konfigurace `config.RRF_K` (default 60).

### Ochrana proti dominance jednoho zdroje
Výsledky jsou deduplikované a z jednoho source souboru se ponechají maximálně 2 chunky (`MAX_CHUNKS_PER_SOURCE = 2`).

## Query classification
`classify_query()` v `src/retrieval/query_classifier.py` vrací `QueryProfile`:

- `labels` – sady routing labels,
- `preferred_url_contains`, `penalized_url_contains`,
- `preferred_categories`, `preferred_chunk_types`, `preferred_document_types`,
- `bm25_weight`, `vector_weight`, `rerank_min_score`.

### Co classifier umí
- pricing vs non-pricing,
- retail vs corporate banking,
- personal retail account vs business account,
- cards / credit card / card overview,
- account / mortgage / investment / RB key / SEPA-SWIFT overviews,
- procedural flows,
- soft guidance candidates,
- complaints / support / FAQ.

### Query expansion
`expand_query()` přidává české banking synonymy a product terms pro lepší recall v BM25 i dense search.

## Source priority scoring
`source_priority(doc, profile)` vrací:

- additive score,
- human-readable reasons.

Používá signály jako:

- `chunk_type`, `document_type`, `category`,
- URL / title / filename,
- content terms,
- freshness penalty/boost,
- authority boost,
- FAQ / complaints / RB key / wallets / card overview / account overview.

### Praktický efekt
Např. retail pricing query preferuje retail sources a penalizuje corporate/FOP dokumenty.

## Autorita dokumentů
`_classify_document_authority()` rozřazuje dokumenty do tierů:

- `product_page`
- `faq_support_page`
- `current_pricing`
- `current_pdf`
- `generic_page`
- `historical_pdf`
- `migration_notice`
- `archived_legal`
- `unknown`

`score_document_authority()` převádí tier na boost v rozsahu přibližně `[-0.30, +0.30]`.

## Freshness governance
`freshness_priority()` a `compute_source_freshness()` řeší stáří zdroje.

### Buckety
- `current`
- `recent`
- `stale`
- `archived`

### Co se děje s archived dokumenty
Pokud dotaz není explicitně o archivech, archived pricing zdroje dostávají penalizaci nebo jsou ve vyšší vrstvě odstraněny.

## Trust scoring
`compute_source_trust()` kombinuje:

- authority weight (50 %),
- recency weight (25 %),
- stability weight (25 %).

Výstup obsahuje:

- `trust_score`,
- `authority_weight`,
- `recency_weight`,
- `stability_weight`,
- `authority_tier`.

## Bankovní retriever
`BankingRetriever._get_relevant_documents()`:

1. klasifikuje query,
2. pokud jde o pricing, zkusí `pricing_search()` a může vrátit deterministic pricing docs bez dalšího rerankingu,
3. jinak spustí `hybrid_search()`,
4. rerankuje kandidáty přes `rerank()`,
5. aplikuje route-specifické fallbacky (complaints, overview, pricing).

## OCR a crawl limity

### OCR / PDF extrakce
`detect_chunk_quality()` penalizuje podezřelé chunky:

- `bad_pdf_extraction`,
- `bad_table_row`.

To je důležité u skenů nebo rozbitých tabulek.

### Freshness crawlu
Freshness závisí na tom, co bylo skutečně naindexováno. Když crawl nebo ingest zaostane za webem RB, retrieval může vracet staré nebo neúplné zdroje.

### Hlavní limit
Systém neumí sám ověřit externí web v reálném čase; pracuje s tím, co je v indexu a na disku.
