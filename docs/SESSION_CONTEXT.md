# Session context

## Přehled
Session management je v `src/api/main.py` a per-session konverzační paměť žije v `BankingRAGChain` (`src/generation/chain.py`).

## Session pool v API
Backend drží:

- `_sessions: dict[str, tuple[BankingRAGChain, float]]`
- `_session_locks: dict[str, asyncio.Lock]`

Každá session má vlastní chain instanci i vlastní lock.

## TTL a LRU

### TTL
Výchozí TTL je `SESSION_TTL_SECONDS = 3600`.

### LRU eviction
Když počet session dosáhne `MAX_SESSIONS = 50`, backend vyhodí nejstarší session podle posledního přístupu.

### Cleanup
`_cleanup_stale_sessions()` čistí expirované session z backendu i z in-memory chain mapy.

## Per-session chain
`_get_or_create_session()` vytváří nový `BankingRAGChain(conversational=True)`.

### Co si chain drží
V `src/generation/chain.py` má chain mimo jiné:

- `chat_history`
- `pending_clarification`
- `clarification_context`
- `resolved_product`
- `resolved_intent`
- `session_context`

## `session_context` dict
`session_context` se inicializuje s poli:

- `current_domain`
- `current_product`
- `current_intent`
- `last_clarification`
- `resolved_product`
- `resolved_segment`

## `_update_session_context()`
Tahle metoda aktualizuje session context z `QueryProfile` nebo z resolved stavu chainu.

### Co umí
- rozpoznat retail vs corporate domain,
- nastavit current intent podle labels,
- zapsat `resolved_product` a `resolved_intent`.

## `_check_session_inheritance()`
Metoda vrací inherited context pro krátké follow-upy.

### Pravidlo
Pokud je dotaz velmi krátký (<= 4 slova) a existuje historie, může se inheritovat:

- `resolved_product` nebo `current_product`,
- `current_intent`.

### Praktický dopad
Krátké následné dotazy typu „a kolik stojí?“ mohou navázat na předchozí turn.

## Thread safety
`src/api/main.py` používá `asyncio.Lock` per session.

To chrání `chat_history` před race condition, když přijde více paralelních requestů se stejným `session_id`.

## Session debug fields
Po zpracování chain ukládá `self._session_debug`, který API může předat do response.

### Fieldy pro frontend/debug
- `session_context_used`
- `inherited_product`
- `inherited_intent`

## Limitace a edge cases

### Process-local chain state
Samotné chain objekty jsou v procesu. Redis session backend ukládá metadata, ale ne přenosný chain object.

### Follow-up inheritance je heuristická
Short-query inheritance je založená na délce dotazu a existenci historie, ne na plném dialog state machine.

### Clarification state je úzký
Aktuální explicitní pending clarification je hlavně pro `ekonto_pricing`.

### Multi-instance deployment
Bez sticky sessions může konverzační historie mezi instancemi ztratit kontinuitu.
