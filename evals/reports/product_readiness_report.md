# Product Readiness Report

Generated: 2026-05-24T23:01:49+00:00

## Executive summary
- Total eval queries: **131**
- Overall pass rate: **47.3%** (62/131)
- Pricing suite pass rate: **60.0%**
- Ambiguity suite pass rate: **50.0%**
- Hallucination rate: **0.0%**
- Average source grounding score: **0.8191**

## Pass rate by dataset
| dataset | total | passed | pass_rate | failures |
|---|---:|---:|---:|---:|
| banking_eval_v1.json | 104 | 45 | 43.3% | 59 |
| pricing_eval_v1.json | 10 | 6 | 60.0% | 4 |
| ambiguity_eval_v1.json | 6 | 3 | 50.0% | 3 |
| source_grounding_eval_v1.json | 6 | 4 | 66.7% | 2 |
| formatting_eval_v1.json | 5 | 4 | 80.0% | 1 |

## Pass rate by category
| category | total | passed | pass_rate |
|---|---:|---:|---:|
| reklamace | 10 | 1 | 10.0% |
| kreditni_karty | 10 | 3 | 30.0% |
| rb_klic | 9 | 3 | 33.3% |
| investice | 8 | 3 | 37.5% |
| apple_google_pay | 10 | 4 | 40.0% |
| sepa_swift | 10 | 4 | 40.0% |
| faq | 9 | 4 | 44.4% |
| firmy | 9 | 4 | 44.4% |
| hypoteky | 9 | 4 | 44.4% |
| podnikatele | 11 | 6 | 54.5% |
| bezpecnost | 10 | 6 | 60.0% |
| limity | 8 | 6 | 75.0% |
| osobni_ucty | 18 | 14 | 77.8% |

## TOP 10 critical failures
| failure | dataset | category | id | question | strategy |
|---|---|---|---|---|---|
| ambiguity_miss | banking_eval_v1.json | podnikatele | podnikatele.003 | Jak založím účet pro OSVČ? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | podnikatele | podnikatele.008 | Je účet pro podnikatele vhodný pro plátce DPH? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | kreditni_karty | kreditni_karty.004 | Jak splácet kreditní kartu? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | hypoteky | hypoteky.007 | Co je americká hypotéka? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | bezpecnost | bezpecnost.008 | Může po mně bankéř chtít PIN ke kartě? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | investice | investice.003 | Jaká rizika mají investiční fondy? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | investice | investice.006 | Mohu investici kdykoliv prodat? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | limity | limity.003 | Jak změním limit pro internetové platby? | pricing_section_llm |
| ambiguity_miss | banking_eval_v1.json | limity | limity.005 | Kde nastavím limity v mobilním bankovnictví? | pricing_section_llm |
| wrong_product_routing | pricing_eval_v1.json | kreditni_karty | pricing.008 | Kolik stojí vedení kreditní karty? | pricing_row_direct |

## TOP 10 high-risk failures
| failure | dataset | category | id | question | strategy |
|---|---|---|---|---|---|
| missing_retrieval | banking_eval_v1.json | osobni_ucty | osobni_ucty.005 | Jaké doklady potřebuji k otevření účtu? | fallback_no_answer |
| format_mismatch | banking_eval_v1.json | osobni_ucty | osobni_ucty.007 | Jak zruším běžný účet u Raiffeisenbank? | pricing_section_llm |
| missing_retrieval | banking_eval_v1.json | osobni_ucty | osobni_ucty.008 | Mohu mít k osobnímu účtu více měn? | fallback_no_answer |
| missing_retrieval | banking_eval_v1.json | podnikatele | podnikatele.004 | Jaké poplatky má podnikatelské eKonto Premium? | pricing_row_direct |
| format_mismatch | banking_eval_v1.json | podnikatele | podnikatele.006 | Jak změním dispoziční oprávnění u podnikatelského účtu? | pricing_section_llm |
| missing_retrieval | banking_eval_v1.json | podnikatele | podnikatele.007 | Jaké dokumenty potřebuje podnikatel k otevření účtu? | fallback_no_answer |
| format_mismatch | banking_eval_v1.json | firmy | firmy.002 | Jak založit účet pro firmu? | pricing_section_llm |
| format_mismatch | banking_eval_v1.json | firmy | firmy.003 | Jak fungují dispoziční práva pro firemní účet? | pricing_section_llm |
| missing_retrieval | banking_eval_v1.json | firmy | firmy.006 | Má Raiffeisenbank služby pro právnické osoby? | fallback_no_answer |
| format_mismatch | banking_eval_v1.json | firmy | firmy.007 | Jak fungují firemní platební karty? | pricing_section_llm |

## TOP 10 low-confidence queries
| bucket | passed | dataset | category | id | question | grounding |
|---|---:|---|---|---|---|---:|
| low | False | banking_eval_v1.json | osobni_ucty | osobni_ucty.005 | Jaké doklady potřebuji k otevření účtu? | 0.0 |
| low | False | banking_eval_v1.json | reklamace | reklamace.008 | Mohu podat reklamaci elektronicky? | 0.0 |
| low | False | banking_eval_v1.json | rb_klic | rb_klic.004 | Jak přenesu RB klíč do nového telefonu? | 0.0 |
| low | False | banking_eval_v1.json | osobni_ucty | osobni_ucty.008 | Mohu mít k osobnímu účtu více měn? | 0.0 |
| low | False | banking_eval_v1.json | reklamace | reklamace.007 | Jak zjistím stav reklamace? | 0.0 |
| low | False | banking_eval_v1.json | rb_klic | rb_klic.003 | Co dělat, když RB klíč nefunguje? | 0.0 |
| low | False | banking_eval_v1.json | kreditni_karty | kreditni_karty.003 | Jak funguje bezúročné období u kreditní karty? | 0.0 |
| low | False | banking_eval_v1.json | apple_google_pay | apple_google_pay.003 | Funguje Apple Pay s kreditní kartou? | 0.0 |
| low | False | banking_eval_v1.json | faq | faq.004 | Jak změním adresu trvalého bydliště? | 0.0 |
| low | False | banking_eval_v1.json | podnikatele | podnikatele.007 | Jaké dokumenty potřebuje podnikatel k otevření účtu? | 0.0 |

## TOP business risk categories
| category | failures |
|---|---:|
| reklamace | 9 |
| kreditni_karty | 7 |
| rb_klic | 6 |
| sepa_swift | 6 |
| apple_google_pay | 6 |
| podnikatele | 5 |
| firmy | 5 |
| hypoteky | 5 |
| faq | 5 |
| investice | 5 |

## Weakest system layer
- **format_mismatch** is the largest failure bucket with 31 failures.
- Observed major layers: format_mismatch=31, missing_retrieval=24, ambiguity_miss=12, missing_source=1, wrong_product_routing=1

## What is no longer the bottleneck
- Dataset `formatting_eval_v1.json` passed >=75%.

## Recommended next 3 priorities
1. Fix non-pricing retrieval coverage for FAQ/reklamace/RB klíč/Apple Pay queries that fall into `missing_retrieval`.
2. Tighten intent routing so card/SEPA/hypotéka pricing does not use generic account-fee pricing rows.
3. Improve ambiguity policy: subjective/generic account/card questions should ask clarifying questions instead of attempting direct answers.

## Report paths
- Consolidated JSON: `evals/runs/consolidated_latest.json`
- Consolidated Markdown: `evals/runs/consolidated_latest.md`
- Baseline JSON: `evals/snapshots/baseline/latest.json`
- Baseline Markdown: `evals/snapshots/baseline/latest.md`
