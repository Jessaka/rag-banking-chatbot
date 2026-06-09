# Follow-up reference fix report

## Scope

- Implemented only the generic reference follow-up layer in:
  - `src/generation/chain.py`
  - session/context-related tests
- No changes to:
  - BM25
  - Qdrant
  - crawling
  - ingest
  - pricing resolver
  - retrieval ranking
  - source governance
  - frontend

## Goal

Improve context inheritance for referential follow-up questions such as:

- `Je k nim pojištění?`
- `A co pojištění?`
- `A jaké mají limity?`
- `A jaké jsou podmínky?`
- `A jaké jsou poplatky?`

while preserving existing special cases like:

- `A ten nejdražší?`
- `Jaké jsou podmínky, aby byl zdarma?`
- `A kolik stojí ta Premium?`
- `Kolik stojí Aktivní?`

## Root cause

The previous implementation concentrated four concerns into `_check_session_inheritance()`:

1. follow-up detection,
2. new-topic blocking,
3. product inheritance,
4. query rewrite.

This caused referential questions like `Je k nim pojištění?` to be blocked by `explicit_new_topic_markers` because they contain words like `pojištění`, even though the phrasing clearly refers to the previous product.

## Changes made

### File changed: `src/generation/chain.py`

### 1) Added `_is_reference_followup(q_norm: str) -> bool`

This helper detects generic referential patterns, including:

- `k nim`
- `k tomu`
- `k němu` / `k ni` / `k ní`
- `a co`
- `a jaké` / `a jaký`
- `a kolik`
- `a mají` / `a má`
- `je k nim`
- `je k tomu`
- `mají k tomu`
- `mají k nim`

### 2) Added `_resolve_reference_followup_query(...)`

This helper creates a safer retrieval query based on inherited product context.

Implemented product-family rewrites for:

- `osobni_ucet`
- `kreditni_karta`
- `hypoteky`
- `investice`
- `sporeni`
- `pujcky`
- `rb_premium_karta`

Examples:

- `Je k nim pojištění?` + `osobni_ucet`
  → `Jaké pojištění nebo doplňkové služby jsou k osobním účtům?`
- `A jaké mají limity?` + `kreditni_karta`
  → `Jaké limity mají kreditní karty?`
- `A jaké jsou podmínky?` + `hypoteky`
  → `Jaké jsou podmínky hypotéky?`
- `A jaké jsou poplatky?` + `investice`
  → `Jaké jsou poplatky u investic?`

### 3) Kept existing special scenarios intact

The existing product-specific rewrites remain first-class and keep priority:

- `A ten nejdražší?`
- `Kolik stojí Aktivní?`
- `A kolik stojí ta Premium?`
- `Jaké jsou podmínky, aby byl zdarma?`

The generic reference layer runs as a fallback after those existing narrow rewrites.

### 4) Updated `_check_session_inheritance()` priority

Reference follow-up now has higher priority than `explicit_new_topic_markers`, but only when:

- a product anchor already exists in session (`resolved_product` or `current_product`)
- and the query matches referential follow-up form

This preserves:

- `Jaké pojištění nabízíte?` → new topic

while enabling:

- `Je k nim pojištění?` → inherited follow-up

### 5) Anchored soft-guidance catalog turns into session

Some category turns such as:

- `Jaké hypotéky nabízíte?`
- `Jaké investice nabízíte?`

were answered by pre-retrieval soft-guidance and previously did not leave enough conversational state for the next turn.

The fix now stores session anchors for catalog soft-guidance families and appends them to chat history, enabling follow-up inheritance in later turns.

## Changed files

- `src/generation/chain.py`
- `tests/test_session_context.py`

## Tests updated

### `tests/test_session_context.py`

Added / expanded coverage for:

- reference follow-up detection
- inheritance for account referential insurance question
- negative explicit-insurance new-topic query
- rewrite coverage for:
  - accounts → insurance
  - accounts → conditions
  - cards → insurance
  - cards → limits
  - hypotéky → conditions
  - investice → poplatky
- preservation of existing special rewrites

## Commands run

```bash
pytest tests/test_session_context.py tests/test_api_session_persistence.py -q
```

## Test result

- `28 passed`

## Runtime smoke result (A–G)

Executed against real `BankingRAGChain` in conversational mode.

### A) Accounts → insurance follow-up

- `Jaké účty nabízíte?`
- `Je k nim pojištění?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké pojištění nebo doplňkové služby jsou k osobním účtům?`

### B) Accounts → pronoun insurance

- `Jaké účty nabízíte?`
- `A co pojištění?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké pojištění nebo doplňkové služby jsou k osobním účtům?`

### C) Credit cards → insurance follow-up

- `Jaké kreditní karty nabízíte?`
- `Je k nim pojištění?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké pojištění nebo doplňkové služby jsou ke kreditním kartám?`

### D) Credit cards → limits follow-up

- `Jaké kreditní karty nabízíte?`
- `A jaké mají limity?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké limity mají kreditní karty?`

### E) Hypotéky → podmínky follow-up

- `Jaké hypotéky nabízíte?`
- `A jaké jsou podmínky?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké jsou podmínky hypotéky?`

### F) Investice → poplatky follow-up

- `Jaké investice nabízíte?`
- `A jaké jsou poplatky?`

Observed:

- follow-up inherited product context
- rewritten query:
  - `Jaké jsou poplatky u investic?`

### G) Negative test — explicit new topic

- `Jaké účty nabízíte?`
- `Jaké pojištění nabízíte?`

Observed:

- treated as a new topic
- no referential rewrite applied

## Important note

This fix guarantees the **inheritance/reference layer** and safer `retrieval_query` generation.

It does **not** guarantee that every downstream retrieval + LLM answer is now perfect for all products, because:

- some rewritten queries still depend on existing retrieval coverage,
- some routes still fall back later in the pipeline,
- but the contextual inheritance problem itself is fixed.

## Final verdict

The new generic reference layer now:

1. recognizes referential follow-up phrasing,
2. prefers session anchor inheritance over blunt topic blocking,
3. rewrites follow-up questions into safer retrieval queries,
4. preserves existing product-specific scenarios,
5. correctly keeps `Jaké pojištění nabízíte?` as a new topic.
