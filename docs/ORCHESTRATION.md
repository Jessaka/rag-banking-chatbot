# Orchestrace requestu

## Co se děje při `ask()`
Hlavní logika je v `src/generation/chain.py` v metodě `BankingRAGChain.ask()`.

### 1. Inicializace a session debug
Metoda si změří čas, resetuje `self._session_debug` a začne zpracovávat aktuální dotaz jako samostatný turn.

### 2. Pre-retrieval routing na surovém dotazu
Ještě před query rewritingem se vyhodnotí bezpečnostní a deterministické cesty:

- pending clarification pro eKonto pricing,
- identity route,
- guided flows,
- procedural flows,
- unsupported topics,
- explicit clarification policies,
- comparison route.

To je důležité, aby historii konverzace nepřepsala identitu asistenta ani urgentní flow.

## Pořadí rozhodování

### 1) Pending clarification
Pokud je v `clarification_context` uložený rozcestník pro `ekonto_pricing`, krátký follow-up typu „osobní“ / „podnikatelské“ rozřeší pending stav.

### 2) Identity
Detekce přes `IDENTITY_PATTERNS` vrací `identity_direct` a odpověď `IDENTITY_RESPONSE` bez retrieval.

### 3) Guided flows
Regexy v `GUIDED_FLOW_PATTERNS` vrací například:

- blokaci / ztrátu karty,
- reklamaci transakce,
- SEPA/SWIFT,
- RB klíč,
- hypotéku.

Výsledek je `guided_flow_direct`.

### 4) Procedural flows
`PROCEDURAL_FLOW_PATTERNS` pokrývají deterministic how-to odpovědi:

- aktivace karty,
- změna limitu,
- karta v mobilu,
- použití v zahraničí,
- Visa/Mastercard overview.

Výsledek je `procedural_flow_direct`.

### 5) Unsupported
Některé topics mimo znalostní hranici (např. crypto) jdou rovnou na `unsupported_direct`.

### 6) Clarification
Ambiguous otázky jako obecné pricing dotazy na eKonto vrátí `clarification_direct` a nastaví `pending_clarification`.

### 7) Comparison
Comparison route je detekovaná přes `comparison_engine`. Pokud se podaří najít entity a sestavit odpověď, vrací `RouteStrategy.COMPARISON_DIRECT`.

## Query rewriting
Pokud dotaz neodešel přes pre-retrieval route, chain může přepsat dotaz pomocí `QUERY_REWRITE_PROMPT`, ale pouze když existuje historie v `self.chat_history`.

## Retrieval fáze
Když se žádná deterministic cesta nespustí, chain volá:

```python
self._retriever.invoke(retrieval_query)
```

Retriever je `BankingRetriever` (`src/retrieval/retriever.py`).

### Vstupní rozhodnutí retrievalu
`classify_query()` vrací `QueryProfile` s labels a preferencemi. Podle nich se upraví:

- BM25 vs vector váhy,
- preferované URL / kategorie / chunk typy,
- minimální rerank threshold.

## Post-retrieval routing

### Overview routes
Po retrievalu chain zkusí deterministické overview odpovědi:

- `card_overview_direct`
- `account_overview_direct`
- `mortgage_overview_direct`
- `investment_overview_direct`
- `rb_key_overview_direct`
- `payment_overview_direct`
- `sepa_swift_overview_direct`
- `product_overview_direct`

### Credit card catalog
Pokud query classifier identifikuje `credit_card_catalog`, chain může vrátit `credit_card_catalog_direct` bez LLM.

### Soft guidance
Pokud retrieval nepřinesl dost relevantních dokumentů, ale dotaz odpovídá bezpečnému FAQ/procedural patternu, chain vrátí `soft_guidance_direct`.

### Fallback no answer
Když nejsou zdroje a žádná safe cesta nepasuje, vrátí se `fallback_no_answer`.

## LLM fallback
Když žádná deterministic cesta neuspěje:

1. sestaví se `context = format_context(source_docs)`,
2. vybere se `CONVERSATIONAL_PROMPT` nebo `SIMPLE_PROMPT`,
3. zavolá se `_invoke_llm()`.

`_invoke_llm()` navíc umí:

- normalizovat odpověď,
- přepsat dead-end pricing fallback zpět na strukturovanou pricing odpověď,
- vrátit `answer_strategy` a `answer_confidence`.

## Post-LLM degradace
Po LLM odpovědi se kontrolují dead-end marker strings (`nenalezl jsem`, `kontaktujte podporu`, …).

Pokud je odpověď slabá:

- chain zkusí overview fallback,
- jinak sníží confidence na `low`,
- a dead-end text doplní bezpečným CTA místo halucinace.

## RouteStrategy v `src/generation/constants.py`
`RouteStrategy` je enum se string hodnotami používanými napříč chainem, cache a confidence semantics. Důležité skupiny:

- identity,
- guided / procedural,
- unsupported / clarification,
- overview routes,
- soft guidance,
- pricing,
- generic LLM,
- degradation,
- comparison.

## Jak přidat nový route

### Povinné kroky
1. Přidej novou hodnotu do `RouteStrategy` v `src/generation/constants.py`.
2. Pokud má být cacheovatelná, doplň TTL mapu v `src/generation/cache.py`.
3. Přidej routing logiku do `BankingRAGChain.ask()` nebo do retrievalu.
4. Doplň debug metadata, aby se nová cesta ukázala ve `retrieval_debug`.
5. Přidej eval test případ do `evals/datasets/`.

### Co hlídat
- String hodnota strategie musí zůstat konzistentní.
- Pokud route mění UX confidence, musí sedět i confidence semantics.
- Pokud route závisí na session, nesmí se cacheovat.
