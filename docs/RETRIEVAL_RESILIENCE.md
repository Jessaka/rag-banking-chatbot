# Retrieval Recovery & Resilience

This layer prevents retrieval collapse after source governance suppression while preserving the existing hallucination, stale-pricing, wrong-product-routing and identity guardrails.

## Collapse scenarios

Retrieval collapse is detected when either condition is true:

1. Source governance suppresses more than 50% of top retrieved documents.
2. Final governed results fall below `MIN_REQUIRED_DOCS`.

Typical causes:

- stale pricing rows ranked highly before governance,
- archived FAQ/support pages competing with current pages,
- migration notices ranking above product/support pages,
- multiple chunks from one PDF crowding out other current sources.

## Recovery flow

1. Normal hybrid retrieval and rerank run as before.
2. Source governance applies suppression, lineage and canonical priority.
3. If collapse is detected, the retriever runs a controlled recovery pass:
   - broader query expansion (`aktuální`, `oficiální stránka`, `FAQ`, label-specific terms),
   - larger read-only hybrid candidate pool,
   - BM25-heavy weighting for exact current-product terms,
   - current-only preference after recovery governance,
   - restricted source-family preference from already observed current families.
4. Recovery docs are appended as secondary context only.
5. Source diversity caps are applied after merge.

No crawl, ingest, reindex, Qdrant mutation or embedding change is performed.

## Governance interaction

Recovery does not bypass source governance:

- recovery candidates are governed again before being appended,
- migration/archive/historical tiers cannot become primary via recovery,
- recovery metadata is attached to docs for debug/eval visibility,
- if recovery cannot find safe current sources, retrieval can safely return no docs and the chain uses explicit resilience UX.

Key metadata:

- `governance_removed_count`
- `governance_suppressed_count`
- `suppression_ratio`
- `recovery_pass_used`
- `recovery_reason`
- `recovery_query`
- `recovery_result_count`
- `recovery_pass_latency_ms`
- `retrieval_collapse_detected`
- `resilience_strategy`
- `final_source_count`

## Diversity policy

Post-governance diversity prevents one source from monopolizing the answer context.

Defaults:

- `max_chunks_per_document = 2`
- `max_chunks_per_family = 3`
- `MIN_REQUIRED_DOCS = 3`

The policy preserves recall: if enforcing caps would drop below `MIN_REQUIRED_DOCS`, it keeps additional docs and marks `diversity_override_used`.

Preferred source mix:

- current product page,
- current pricing document/row,
- FAQ/support page,
- current legal/current PDF only when needed.

Avoided pattern:

- 5 chunks from the same PDF or source family.

## Fallback semantics

Empty/weak retrieval is not collapsed into one generic message. The chain distinguishes:

1. `supported_but_missing_data` — supported RB topic, but no safe current source.
2. `unsupported_domain` — outside supported RB scope.
3. `governance_suppressed` — only unsafe/stale sources were available.
4. `retrieval_timeout` — retrieval timed out.
5. `low_confidence_retrieval` — sources are weak/ambiguous.

Each category has its own confidence semantics and escalation strategy through `confidence_factors`.

## Observability

Backend telemetry/debug fields include:

- `governance_removed_count`
- `recovery_pass_latency_ms`
- `diversity_score`
- `retrieval_collapse_detected`
- `resilience_strategy`
- `final_source_count`

Frontend `?debug` panel displays:

- recovery pass used/not used,
- suppressed count,
- diversity score,
- collapse detection,
- resilience strategy.

## Production risks

- Recovery can increase latency because it performs a second read-only hybrid retrieval and rerank.
- Debug visibility depends on `DEBUG_API_ERRORS`; production may hide `retrieval_debug` from clients.
- Source-family metadata can be sparse; fallback keys use source URL/file name/product name.
- Diversity caps must stay conservative for pricing queries to avoid removing necessary structured rows.

## Scaling risks

- High recovery frequency increases BM25/vector read load.
- 100+ concurrent recovery-triggering queries can amplify reranker CPU latency.
- Cache hit ratio strongly affects perceived latency for repeated pricing and identity queries.
- Streaming completion rate should be monitored separately from non-streaming p95/p99 latency.

## Validation

Recommended checks:

```bash
python3 -m pytest tests/
python3 scripts/run_eval.py --dataset evals/datasets/retrieval_resilience_eval_v1.json
python3 scripts/load_test.py --users 100
```
