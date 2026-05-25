# Banking RAG Eval Report

## Run metadata
- Dataset: `consolidated: banking_eval_v1 + pricing + ambiguity + source_grounding + formatting`
- API: `http://127.0.0.1:8000/chat`
- Created: 2026-05-24T23:01:49+00:00

## KPI summary
- Pass rate: 47.3% (62/131)
- Pricing accuracy: 1.0
- Hallucination rate: 0.0%
- Unsupported answer rate: n/a
- Avg source grounding score: 0.8191
- Ambiguity correctness: 0.9084
- Retrieval P@3: 0.6624

## Category leaderboard
| category | total | passed | pass_rate |
|---|---:|---:|---:|
| apple_google_pay | 10 | 4 | 40.0% |
| bezpecnost | 10 | 6 | 60.0% |
| faq | 9 | 4 | 44.4% |
| firmy | 9 | 4 | 44.4% |
| hypoteky | 9 | 4 | 44.4% |
| investice | 8 | 3 | 37.5% |
| kreditni_karty | 10 | 3 | 30.0% |
| limity | 8 | 6 | 75.0% |
| osobni_ucty | 18 | 14 | 77.8% |
| podnikatele | 11 | 6 | 54.5% |
| rb_klic | 9 | 3 | 33.3% |
| reklamace | 10 | 1 | 10.0% |
| sepa_swift | 10 | 4 | 40.0% |

## Failure leaderboard
| failure_type | count |
|---|---:|
| format_mismatch | 31 |
| missing_retrieval | 24 |
| ambiguity_miss | 12 |
| missing_source | 1 |
| wrong_product_routing | 1 |

## Failure samples
- `missing_retrieval` **osobni_ucty.005**: Jaké doklady potřebuji k otevření účtu?
- `format_mismatch` **osobni_ucty.007**: Jak zruším běžný účet u Raiffeisenbank?
- `missing_retrieval` **osobni_ucty.008**: Mohu mít k osobnímu účtu více měn?
- `ambiguity_miss` **podnikatele.003**: Jak založím účet pro OSVČ?
- `missing_retrieval` **podnikatele.004**: Jaké poplatky má podnikatelské eKonto Premium?
- `format_mismatch` **podnikatele.006**: Jak změním dispoziční oprávnění u podnikatelského účtu?
- `missing_retrieval` **podnikatele.007**: Jaké dokumenty potřebuje podnikatel k otevření účtu?
- `ambiguity_miss` **podnikatele.008**: Je účet pro podnikatele vhodný pro plátce DPH?
- `format_mismatch` **firmy.002**: Jak založit účet pro firmu?
- `format_mismatch` **firmy.003**: Jak fungují dispoziční práva pro firemní účet?
