# Banking RAG Eval Report

## Run metadata
- Dataset: `targeted: pricing+ambiguity+formatting`
- API: `http://127.0.0.1:8000/chat`
- Created: 2026-05-24T23:57:43Z

## KPI summary
- Pass rate: 95.2% (20/21)
- Pricing accuracy: 1.0
- Hallucination rate: 0.0%
- Unsupported answer rate: n/a
- Avg source grounding score: 0.8238
- Ambiguity correctness: 1.0
- Retrieval P@3: 0.8889

## Category leaderboard
| category | total | passed | pass_rate |
|---|---:|---:|---:|
| apple_google_pay | 1 | 1 | 100.0% |
| bezpecnost | 1 | 1 | 100.0% |
| faq | 1 | 1 | 100.0% |
| firmy | 1 | 1 | 100.0% |
| hypoteky | 1 | 1 | 100.0% |
| kreditni_karty | 2 | 2 | 100.0% |
| osobni_ucty | 9 | 9 | 100.0% |
| podnikatele | 3 | 3 | 100.0% |
| reklamace | 1 | 0 | 0.0% |
| sepa_swift | 1 | 1 | 100.0% |

## Failure leaderboard
| failure_type | count |
|---|---:|
| missing_retrieval | 1 |

## Failure samples
- `missing_retrieval` **formatting.005**: Jak podat reklamaci platby?
