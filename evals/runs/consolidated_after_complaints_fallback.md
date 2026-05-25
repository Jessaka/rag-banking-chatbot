# Consolidated eval after complaints fallback

- Total: 131
- Passed: 85
- Failed: 46
- Pass rate: 64.89%
- Delta vs 47.33% baseline: 17.56 pp

## Dataset summaries
- banking_eval_v1.json: 59/104 (56.73%)
- pricing_eval_v1.json: 10/10 (100.00%)
- ambiguity_eval_v1.json: 6/6 (100.00%)
- source_grounding_eval_v1.json: 5/6 (83.33%)
- formatting_eval_v1.json: 5/5 (100.00%)

## Failure counts
- missing_retrieval: 25
- format_mismatch: 14
- ambiguity_miss: 5
- missing_source: 2
- api_error: 0
- hallucination: 0
- stale_pricing: 0
- unsupported_answer: 0
- wrong_product_routing: 0

## Category leaderboard
- apple_google_pay: 8/10 (80.00%)
- bezpecnost: 7/10 (70.00%)
- faq: 5/9 (55.56%)
- firmy: 4/9 (44.44%)
- hypoteky: 6/9 (66.67%)
- investice: 4/8 (50.00%)
- kreditni_karty: 8/10 (80.00%)
- limity: 7/8 (87.50%)
- osobni_ucty: 15/18 (83.33%)
- podnikatele: 6/11 (54.55%)
- rb_klic: 2/9 (22.22%)
- reklamace: 5/10 (50.00%)
- sepa_swift: 8/10 (80.00%)
