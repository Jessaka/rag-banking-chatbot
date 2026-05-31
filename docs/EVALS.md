# Evaluace a regression gating

## Přehled
Eval infrastruktura je v `evals/` a používá dva hlavní běžce:

- `scripts/run_eval.py` — hlavní dataset-driven eval proti běžícímu backendu,
- `scripts/run_golden_suite.py` — golden regression suite pro route / confidence / behavior.

Oba běžce volají backend přes `POST /chat`; neimportují retrieval kód a nereindexují data.

## Dataset formát
Datasety jsou JSON listy v `evals/datasets/`.

### Typické pole
Podle typu datasetu se používají pole jako:

- `question`
- `category`
- `subcategory`
- `expected_behavior`
- `expected_strategy`
- `expected_confidence`
- `expected_contains`
- `expected_not_contains`
- `expected_sources`
- `expected_price`
- `requires_sources`
- `should_clarify`
- `unsupported_topic`
- `turns`
- `format_expectations`

## Runner `scripts/run_eval.py`
Hlavní runner:

- načte dataset,
- pošle dotazy na `/chat`,
- spočítá metriky,
- uloží report do `evals/runs/`.

### Metriky
`run_eval.py` umí počítat zejména:

- pass rate,
- pricing accuracy,
- hallucination rate,
- unsupported answer rate,
- avg source grounding score,
- ambiguity handling correctness,
- retrieval P@3,
- average latency.

## Golden suite `scripts/run_golden_suite.py`
Golden suite kontroluje:

- expected route / strategy,
- expected confidence,
- expected behavior,
- obsah odpovědi,
- forbid patterns,
- latency.

## Dostupné datasety a co testují

### `banking_eval_v1.json`
Hlavní směs dotazů napříč pricing, overview, cards, complaints, support, RB key, SEPA/SWIFT, investicemi a hypotékami.

### `golden_queries_v1.json`
Smoketest na routing, confidence a behavior.

### `retrieval_qa_eval_v1.json`
Kontrola správného route, source typu, authority tier a expected strategy.

### `source_grounding_eval_v1.json`
Zda odpověď obsahuje správné zdroje a má dostatečné grounding score.

### `pricing_eval_v1.json`
Pricing extraction, pricing accuracy a ambiguity boundary.

### `ambiguity_eval_v1.json`
Clarification behavior pro nejednoznačné otázky.

### `procedural_eval_v1.json`
Deterministické how-to flow pro karty.

### `faq_soft_guidance_eval_v1.json`
Safe FAQ soft guidance bez přehnané reliance na LLM.

### `overview_eval_v1.json`
Overview route coverage pro account / mortgage / investment / RB key / payment / SEPA-SWIFT.

### `card_overview_eval_v1.json`
Specifická validace card overview route.

### `identity_eval_v1.json`
Asistent identity a boundary vysvětlení.

### `conversational_eval_v1.json`
Multi-turn inheritance a krátké follow-upy.

### `conversational_noise_eval_v1.json`
Robustnost na noisy/short query variace.

### `session_context_eval_v1.json`
Session context inheritance scénáře.

### `graceful_degradation_eval_v1.json`
Fallback z pricing na overview nebo jiné bezpečné degradace.

### `dead_end_ux_eval_v1.json`
Zda odpovědi nekončí bez akce a nevrací slepé dead-end texty.

### `confidence_eval_v1.json`
High / clarification / unsupported confidence chování.

### `confidence_semantics_eval_v1.json`
Semantic labels a `degraded_answer` flag.

### `source_ux_eval_v1.json`
UX metadata kolem zdrojů a route labelů.

### `retrieval_authority_eval_v1.json`
Authority tier selection a metadata checks.

### `comparison_eval_v1.json`
Comparison route a expected strategy.

### `escalation_eval_v1.json`
Escalation / support flow pro blokaci karty, reklamace a SEPA/SWIFT.

### `formatting_eval_v1.json`
Formátování odpovědí a prohibice na raw JSON nebo přímý price leak.

### `latency_smoke_eval_v1.json`
Latency smoke testy a základní route sanity.

## Regression gates
`evals/gates/regression_thresholds.json` definuje minimální a maximální limity.

### Hlavní thresholdy
- pass rate: 0.75
- pricing accuracy: 0.80
- avg source grounding score: 0.55
- ambiguity handling correctness: 0.85
- retrieval P@3: 0.45
- hallucination rate max: 0.05
- unsupported answer rate max: 0.10

### Důležité failure gates
File také hlídá maxima pro:

- wrong product routing,
- stale pricing,
- hallucination,
- ambiguity miss,
- missing source,
- missing retrieval,
- unsupported answer,
- api error.

## Jak přidat nový eval dataset

### Postup
1. Vytvoř nový `evals/datasets/<name>.json` jako list objektů.
2. Použij pole očekávaná runnerem, který dataset bude číst.
3. Pokud má dataset gate, doplň thresholdy do `evals/gates/regression_thresholds.json`.
4. Přidej nový dataset do CI nebo release checku, protože runners nemají automatický registry.

### Doporučení
- držet dataset malé a deterministické,
- explicitně uvádět expected behavior,
- přidat source expectations, pokud na nich záleží,
- u multi-turn scénářů používat `turns` a stabilní `session_id`.

## Známé eval mezery

### Závislost na běžícím backendu
Evaly testují backend přes HTTP, ne interní funkce přímo.

### Debug metadata nejsou vždy dostupná
Některé metriky používají `retrieval_debug`; pokud backend debug metadata nevrací, jde jen o částečné vyhodnocení.

### Žádné ingest/crawl ověření
Evaly neověřují, že je Qdrant skutečně správně zreindexovaný.

### Žádné browser UI testy
UI a SSE chování nejsou v těchto runners automaticky pokryté.
