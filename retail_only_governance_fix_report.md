# Retail-only governance fix report

## Scope

Implemented only in the final source-governance layer.

No changes to:

- crawling
- ingest
- BM25
- Qdrant
- reranking

## Goal

Prevent business/corporate/private-banking sources from being used in answer generation for the retail-only chatbot.

Blocked URL patterns:

- `/podnikatele/`
- `/firmy/`
- `/private-banking/`

## Implemented change

### File changed

- `src/retrieval/source_governance.py`

### What was added

Added a hard suppression rule to `apply_source_suppression(...)`:

- detect source URLs containing:
  - `/podnikatele/`
  - `/firmy/`
  - `/private-banking/`
- suppress them before answer-generation sources are finalized

### Rule name

- `retail_only_source_filter`

### Suppression reason

- `Business/corporate/private-banking source suppressed — retail-only chatbot policy.`

## Test files changed

- `tests/test_source_governance.py`

Added regression coverage for:

- `/podnikatele/`
- `/firmy/`
- `/private-banking/`
- retail URL survival
- full governance pipeline suppression behavior

## Commands run

### Unit tests

```bash
pytest tests/test_source_governance.py -q
```

Result:

- `33 passed`

### Runtime retail smoke

Checked queries:

- `Jaké dokumenty potřebuji k úvěru?`
- `Jaké účty nabízíte?`
- `Jaké kreditní karty nabízíte?`
- `Jaké hypotéky nabízíte?`
- `Jaké investice nabízíte?`

Verified returned source URLs contain **none** of:

- `/podnikatele/`
- `/firmy/`
- `/private-banking/`

## Smoke results summary

### `Jaké dokumenty potřebuji k úvěru?`

- `answer_strategy = supported_but_missing_data_fallback`
- returned sources: `[]`
- blocked business/private sources in final output: **none**

### `Jaké účty nabízíte?`

- `answer_strategy = account_overview_direct`
- returned retail source:
  - `https://www.rb.cz/osobni/ucty/bezne-ucty`
- blocked business/private sources in final output: **none**

### `Jaké kreditní karty nabízíte?`

- `answer_strategy = credit_card_catalog_direct`
- returned sources included non-blocked URLs only
- blocked business/private sources in final output: **none**

### `Jaké hypotéky nabízíte?`

- `answer_strategy = soft_guidance_direct`
- returned sources: `[]`
- blocked business/private sources in final output: **none**

### `Jaké investice nabízíte?`

- `answer_strategy = soft_guidance_direct`
- returned sources: `[]`
- blocked business/private sources in final output: **none**

## Important note

This fix enforces **negative source governance** only.

It guarantees that blocked business/private-banking URLs do not survive final governance.

It does **not** guarantee that every retail query now has the ideal retail source, because:

- some queries may fall back when business content is removed,
- some existing retail answer paths still rely on weak/indirect sources,
- but the blocked source families no longer reach final answer sources.

## Changed files

- `src/retrieval/source_governance.py`
- `tests/test_source_governance.py`
- `retail_only_governance_fix_report.md`

## Final verdict

The retail-only source-governance filter is active and working.

Business/corporate/private-banking URLs are now suppressed at the final governance layer before answer generation.
