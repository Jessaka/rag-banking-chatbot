# Response cache

## Přehled
Cache je v `src/generation/cache.py` a je orchestrace vrstva nad storage backendem.

## Cache key
Cache key je odvozený **pouze z normalizované otázky**:

- diakritika pryč,
- lowercase,
- bez interpunkce,
- whitespace collapsed.

### Co se do klíče nedává
Nezahrnuje se:

- intent,
- product,
- session context.

To je záměr: cache musí být session-safe a nesmí kontaminovat odpovědi mezi uživateli.

## TTL podle route
`_ROUTE_TTL` mapuje strategie na TTL:

- `identity_direct` → 24h
- overview routes → 6h
- `soft_guidance_direct` → 1h
- `guided_flow_direct` → 1h
- `procedural_flow_direct` → 1h
- `pricing_row_direct` → 15 min
- `comparison_direct` → 6h

## Cacheable vs non-cacheable

### Cacheable
Route strategie jako identity, overview, guided/procedural, soft guidance, pricing row, comparison.

### Non-cacheable
- `unsupported_direct`
- `fallback_no_answer`
- `clarification_direct`
- session-dependent/LLM-like strategie (`generic_llm`, `clarification_direct`)

## `ResponseCache`
Class `ResponseCache` dělá:

- `get()`
- `set()`
- `add_debug_metadata()`
- in-flight dedup,
- stats,
- clear.

### Metadata
Při cache hitu přidává:

- `cache_hit`
- `cache_key`
- `cache_age_seconds`
- `cache_backend`
- `cached_at`
- `original_strategy`
- `original_confidence`

## In-flight dedup
Pokud stejný cache key přichází paralelně vícekrát, první request ho „claimne“ a ostatní čekají na `threading.Event`.

To snižuje duplicitní výpočty při burst traffic.

## Backendy

### Default: InMemory
`src/storage/memory.py`:

- thread-safe,
- LRU-like eviction,
- TTL expirace.

### Optional: Redis
`src/storage/redis_impl.py`:

- `RedisCacheBackend`,
- `RedisSessionBackend`,
- graceful fallback na in-memory při výpadku.

Backend se volí v `src/api/main.py` přes `USE_REDIS_CACHE`.

## Post-stream caching
SSE endpoint po dokončení streamu ukládá `chain._last_stream_result` do cache, pokud je výsledek cacheovatelný.

## Session safety
Proč je klíč jen podle otázky:

### Důvod
Odpovědi deterministic route jsou definované primárně textem otázky. Přidání session metadata by vedlo k rozdílným cache hitům pro stejný dotaz a zbytečně by rozbilo sdílenou cache.

### Co hlídat
Session-dependent route se nesmí cacheovat, jinak by cache mohla vracet odpověď založenou na cizím kontextu.
