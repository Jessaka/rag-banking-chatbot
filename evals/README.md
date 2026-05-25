# Banking RAG evaluation framework

This framework evaluates the running FastAPI backend through `POST /chat` only.
It does not crawl, reindex, or modify Qdrant.

## Run evaluation

```bash
venv/bin/python scripts/run_eval.py \
  --dataset evals/datasets/banking_eval_v1.json \
  --api-url http://127.0.0.1:8000/chat \
  --save-report \
  --update-leaderboard
```

Reports are written to `evals/runs/*.json` and `evals/runs/*.md`.

## Specialized suites

- `evals/datasets/pricing_eval_v1.json` — pricing correctness, stale pricing, product routing.
- `evals/datasets/ambiguity_eval_v1.json` — clarification vs direct-answer behavior.
- `evals/datasets/source_grounding_eval_v1.json` — source quality and grounding.
- `evals/datasets/formatting_eval_v1.json` — answer formatting, source cue, no raw JSON.

## Regression gates

Validate an existing report against automated gates:

```bash
venv/bin/python scripts/eval_gate.py \
  evals/runs/banking_eval_latest.json \
  --thresholds evals/gates/regression_thresholds.json \
  --output evals/runs/gate_result.json
```

Priority gates protect:

1. pricing correctness,
2. hallucination prevention,
3. ambiguity handling,
4. source quality.

## Compare snapshots

```bash
venv/bin/python scripts/compare_eval_reports.py \
  evals/snapshots/baseline/report.json \
  evals/runs/candidate.json \
  --output evals/runs/comparison.json
```

## Dataset fields

Each item is dataset-driven and can define:

- `category`, `subcategory`, `tags`
- `expected_behavior`: `direct_answer`, `clarify`, `unsupported`, `safety_guidance`
- `expected_contains` / `expected_not_contains`
- `expected_price`
- `expected_products` / `expected_sources`
- `requires_sources`
- `should_clarify`
- `should_refuse_unsupported`
- `min_grounding_score`

## Metrics

- retrieval precision@3, approximated from `retrieval_debug` when present and sources otherwise
- pricing accuracy
- hallucination rate
- unsupported answer rate
- source grounding score
- ambiguity handling correctness
- answer formatting pass/fail

## CI

`.github/workflows/eval-ci.yml` runs dataset/script validation and unit eval gates on PRs.
Live API eval is available through manual `workflow_dispatch` with `run_live_eval=true`
and `EVAL_API_URL` configured as a repository variable. This keeps default CI
hermetic and avoids requiring Qdrant/LLM credentials for every PR.

## Failure taxonomy

- `missing_retrieval`
- `wrong_product_routing`
- `stale_pricing`
- `hallucination`
- `missing_source`
- `ambiguity_miss`
- `unsupported_answer`
- `api_error`
- `format_mismatch`
