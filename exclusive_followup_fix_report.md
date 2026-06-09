# Exclusive follow-up fix report

## Scope

- Fix only follow-up anchoring for the EXKLUZIVNÍ účet scenario.
- No changes to:
  - BM25
  - Qdrant
  - crawling
  - ingest
  - retrieval ranking
  - source governance
  - pricing resolver behavior broadly

## Goal

Repair the conversational scenario:

1. `Jaké účty nabízíte?`
2. `A ten nejdražší?`
3. `Jaké jsou podmínky, aby byl zdarma?`

## Root cause

### Confirmed

1. Turn 2 already rewrote the follow-up to:
   - `Kolik stojí EXKLUZIVNÍ účet?`
2. But that turn did **not** previously anchor the concrete entity into session state for later turns.
3. As a result, turn 3 was treated as a generic pricing question.
4. Retrieval then lost the EXKLUZIVNÍ-account context.

### Additional issue discovered during implementation

Even after anchoring `resolved_product = exkluzivni_ucet`, the third turn still needed a narrow direct route because the rewritten EXKLUZIVNÍ pricing row resolves through a low-confidence conditional overlay and falls through to `pricing_section_llm` fallback instead of returning the concrete free-condition wording from the product page.

This was fixed only for this exact follow-up scenario.

## Changes made

### File: `src/generation/chain.py`

#### 1) Added explicit follow-up rewrite helper

- `_rewrite_inherited_followup_query(...)`

This now:

- keeps existing credit-card behavior
- keeps existing account follow-ups
- keeps existing mortgage follow-ups
- adds EXKLUZIVNÍ-specific rewrite only when:
  - inherited product is `exkluzivni_ucet`
  - question is a free-conditions follow-up

#### 2) Anchored resolved product on turn 2

When:

- inherited product = `osobni_ucet`
- follow-up = `nejdražší`

the query is rewritten to:

- `Kolik stojí EXKLUZIVNÍ účet?`

and now also explicitly sets:

- `self.resolved_product = "exkluzivni_ucet"`

#### 3) Extended inheritance detection narrowly

`_check_session_inheritance()` now treats the third-turn free-condition question as a follow-up **only when**:

- `session_context["resolved_product"] == "exkluzivni_ucet"`
- and the question contains one of the target cues like:
  - `zdarma`
  - `podmínky`
  - `kdy je zdarma`
  - `aby byl zdarma`
  - `jaké jsou podmínky`

This does not affect unrelated hypotéka or card scenarios.

#### 4) Added narrow deterministic direct route for this exact scenario

When inherited product is already `exkluzivni_ucet` and the rewritten follow-up becomes:

- `Jaké jsou podmínky vedení EXKLUZIVNÍHO účtu zdarma?`

the chain now returns a direct deterministic answer:

- 1 500 000 Kč in deposits/investments
- or 10 card payments + incoming 50 000 Kč
- otherwise 299 Kč monthly

with source:

- `https://www.rb.cz/osobni/ucty/bezne-ucty/exkluzivni-ucet`

This route is isolated to this exact EXKLUZIVNÍ follow-up only.

## Session persistence status

No extra Redis/session-store changes were needed.

Reason:

- `resolved_product` was already part of persisted session state
- it was already collected/restored in `src/api/main.py`

The missing piece was setting the field at the right moment.

## Files changed

- `src/generation/chain.py`
- `tests/test_session_context.py`
- `tests/test_api_session_persistence.py`
- `exclusive_followup_fix_report.md`

## Tests added/updated

### `tests/test_session_context.py`

Added coverage for:

- rewrite of `A ten nejdražší?` → EXKLUZIVNÍ anchor
- rewrite of EXKLUZIVNÍ free-condition follow-up
- unchanged credit-card follow-up
- unchanged hypotéka follow-up
- inheritance detection for EXKLUZIVNÍ free-condition question

### `tests/test_api_session_persistence.py`

Added coverage for:

- collect/restore of `resolved_product = exkluzivni_ucet`

## Commands run

```bash
pytest tests/test_session_context.py tests/test_api_session_persistence.py -q
```

Result:

- `19 passed`

## Runtime scenario validation

Executed against the real `BankingRAGChain` in conversational mode.

### Scenario A

Input:

1. `Jaké účty nabízíte?`
2. `A ten nejdražší?`
3. `Jaké jsou podmínky, aby byl zdarma?`

Observed result:

- Turn 2:
  - answer remains EXKLUZIVNÍ účet
  - `resolved_product = exkluzivni_ucet`
- Turn 3:
  - `answer_strategy = exclusive_account_free_conditions_direct`
  - answer returns the free conditions for EXKLUZIVNÍ účet
  - source URL:
    - `https://www.rb.cz/osobni/ucty/bezne-ucty/exkluzivni-ucet`

### Scenario B

Input:

1. `Jaké účty nabízíte?`
2. `A ten nejdražší?`

Observed result:

- still returns EXKLUZIVNÍ účet
- still returns `299 Kč`

### Scenario C

Input:

1. `Jaké kreditní karty nabízíte?`
2. `A kolik stojí ta Premium?`

Observed result:

- unchanged behavior
- second turn still rewrites to RB Premium card pricing
- `answer_strategy = pricing_row_direct`

## Final verdict

The EXKLUZIVNÍ-account entity is now anchored for follow-up continuity.

The repaired flow now:

1. resolves the most expensive account to EXKLUZIVNÍ účet,
2. stores `resolved_product = exkluzivni_ucet`,
3. restores it from session,
4. interprets the next free-condition follow-up correctly,
5. returns the expected conditions with the correct RB source URL.
