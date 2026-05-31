# RB Banking RAG Chatbot — Anchored Summary

## Projekt
Banking RAG chatbot pro Raiffeisenbank — produkční retrieval-augmented generation s hybridním vyhledáváním, rerankingem, strukturovaným pricingem a source governance.

## Stack
- Python 3.14, LangChain, Qdrant (vektorová DB), BM25 (hybrid)
- FastAPI, Pydantic, pytest, typeguard
- OpenAI API (chat completions, embeddings)
- Redis (cache/rate-limiting)

---

## Canonical Pricing Resolver (právě dokončeno)

### Co bylo implementováno

| Workstream | Status | Soubory |
|---|---|---|
| **P1 — Canonical Pricing Resolver** | ✅ | `src/retrieval/pricing_resolver.py`, `src/retrieval/retriever.py` |
| **P2 — Pricing Source Priority** | ✅ | `src/retrieval/pricing_resolver.py` |
| **P3 — Structured Pricing Extraction** | ✅ | `src/retrieval/pricing_resolver.py` |
| **P4 — Pricing Confidence Layer** | ✅ | `src/retrieval/pricing_resolver.py`, `src/generation/chain.py` |
| **P5 — False Unsupported Prevention** | ✅ | `src/generation/chain.py` |
| **P6 — Pricing Eval Dataset** | ✅ | `evals/datasets/pricing_resolution_eval_v2.json` |
| **P7 — Regression Metrics** | ✅ | `scripts/run_eval.py` |
| **P8 — Debug Metadata** | ✅ | `src/generation/chain.py`, `frontend/src/lib/components/DebugPanel.svelte` |
| **P9 — Tests** | ✅ | `tests/test_pricing_resolver.py` |

### Resolver architecture
- Deterministic-first resolver over existing structured pricing JSONL rows.
- No crawl, ingest, reindex, Qdrant schema change or embedding change.
- Pricing fast-path in `retriever.py` now calls `resolve_pricing_query()`.
- Governance/recovery still runs before final answer selection.

### Pricing metadata
- `pricing_confidence`, `pricing_source_type`, `pricing_row_found`, `pricing_row_exact_match`, `pricing_canonical_used`.
- Normalization handles `zdarma`, `0 Kč`, `bez poplatku`, `měsíčně zdarma`, `vedení zdarma`, `fee waived`, `first year free`.

### Testy
- `python3 -m pytest tests/ -q` → 242 passed
- `npm run check` → 0 errors / 0 warnings
- `pricing_resolution_eval_v2.json` → valid JSON

---

## Retrieval Recovery & Resilience Layer (dokončeno v předchozí fázi)

### Co bylo implementováno

| Workstream | Status | Soubory |
|---|---|---|
| **P1 — Governance Recovery Pass** | ✅ | `src/retrieval/retriever.py`, `src/retrieval/source_governance.py` |
| **P2 — Empty Retrieval Resilience** | ✅ | `src/generation/chain.py` |
| **P3 — Source Diversity Policy** | ✅ | `src/retrieval/source_governance.py` |
| **P4 — Retrieval Stability Evals** | ✅ | `evals/datasets/retrieval_resilience_eval_v1.json`, `scripts/run_eval.py` |
| **P5 — Observability** | ✅ | `src/retrieval/retriever.py`, `src/generation/chain.py`, `frontend/src/lib/components/DebugPanel.svelte` |
| **P6 — Load/Stress Testing** | ✅ | `scripts/load_test.py` |
| **P7 — Resilience Documentation** | ✅ | `docs/RETRIEVAL_RESILIENCE.md` |

### Recovery flow
- Trigger: governance suppression ratio > 50 % nebo final docs < `MIN_REQUIRED_DOCS`.
- Recovery: read-only hybrid search s širší query expanzí, větším candidate poolem, BM25-heavy weighting a current-only preference.
- Recovery docs jsou append-only sekundární context, nikdy neobejdou governance.

### Diversity policy
- `max_chunks_per_document = 2`
- `max_chunks_per_family = 3`
- `source_diversity_score` / `diversity_score` na finálních doc metadatech.
- Diversity se nevynutí tak agresivně, aby sama způsobila collapse pod `MIN_REQUIRED_DOCS`.

### Resilience semantics
- Empty/weak retrieval rozlišuje: `supported_but_missing_data`, `unsupported_domain`, `governance_suppressed`, `retrieval_timeout`, `low_confidence_retrieval`.
- Žádná nová indexace, crawl, ingest, reindex, Qdrant mutation ani embedding změna.

### Observability
- Debug/telemetry fields: `governance_removed_count`, `recovery_pass_latency_ms`, `diversity_score`, `retrieval_collapse_detected`, `resilience_strategy`, `final_source_count`.
- Frontend `?debug` panel zobrazuje recovery pass, suppressed count, diversity score, collapse detection a strategy.

### Testy
- `python3 -m pytest tests/` → 235 passed
- `python3 -m pytest tests/test_source_governance.py -v` → 28 passed
- `npm run check` ve frontend → 0 errors, 0 warnings
- `py_compile` změněných Python souborů → OK

---

## Source Governance Hardening Layer (dokončeno v předchozí fázi)

### Co bylo implementováno

| Workstream | Status | Soubory |
|---|---|---|
| **P1 — Hard Source Suppression** | ✅ | `src/retrieval/source_governance.py` |
| **P2 — Canonical Source Priority** | ✅ | `src/retrieval/source_governance.py` |
| **P3 — Document Lineage** | ✅ | `src/retrieval/source_governance.py` |
| **P4 — Source Policy Evals** | ✅ | `tests/test_source_governance.py` (24 testů) |
| **P5 — Source Policy Explainability** | ✅ | `src/generation/chain.py` (debug fields) |
| **P6 — Governance Documentation** | ⬜ | (module docstring exists) |
| **P7 — Hardening Regression Tests** | ✅ | `tests/test_source_governance.py` |

### P1 — Hard Source Suppression
- Rule 1: Archivovaný zdroj nikdy nepřebije current source stejného typu
- Rule 2: Historická cena blokována pokud existuje current pricing
- Rule 3: Migration notice není nikdy primárním zdrojem
- Rule 4: Archived legal document není nikdy primárním zdrojem
- Rule 5: Deprecated FAQ není primárním zdrojem

### P2 — Canonical Source Priority
- Hierarchie: product_page → current_pricing → faq_support_page → current_pdf → generic_page → recent_page → historical_pdf → migration_notice → archived_legal → unknown
- Re-rank podle priority (stable sort, zachovává retrieval order v rámci stejné priority)
- Flag `canonical_override_used` pro debug

### P3 — Document Lineage
- Grouping podle `document_family`
- Preference vyššího `document_generation`
- Detekce `superseded_by` pro potlačení nahrazených dokumentů

### P5 — Explainability
- Nová pole v `_retrieval_debug()`: `suppression_applied`, `suppression_reason`, `canonical_priority`, `canonical_source_type`, `canonical_override_used`, `lineage_superseded`

### Hook do pipeline
- `apply_governance_pipeline()` volán v `BankingRetriever._get_relevant_documents()` před returnem (krok 4)
- Aplikován i na pricing path s fallbackem pokud by governance vyprázdnila výsledky
- Logování: governance čas + počet suppresí

## Testy
- 24 nových testů v `tests/test_source_governance.py`
- 231 celkem testů → vše PASS

## Rizika
- `_classify_document_authority()` může klasifikovat dokumenty jinak než governance očekává → testy pokrývají reálné klasifikační výstupy
- Fallback při vyprázdnění výsledků gouvernancí: vrací původní set s warningem
- Modifikuje metadata dokumentů in-place (stejný pattern jako zbytek pipeline)
