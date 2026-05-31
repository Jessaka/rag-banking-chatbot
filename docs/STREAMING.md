# Streaming

## Endpoint
SSE stream je vystaven přes:

```http
POST /chat/stream
```

Implementace je v `src/api/main.py`.

## Jak streaming funguje

### 1. Frontend odešle request
`frontend/src/lib/api.ts` volá `fetch()` na `/chat/stream` a čte response body přes `ReadableStream`.

### 2. Backend vytvoří session a zkontroluje cache
Stejně jako `/chat` se nejdřív řeší session a response cache.

### 3. Pokud je cache hit
Backend pošle:

- `start`
- jeden `token` s celým answer textem
- `done`

### 4. Pokud cache miss
Backend spustí `chain.ask_stream()`.

## `ask_stream()` v `src/generation/chain.py`
`ask_stream()` je synchronní generator, který vrací eventy:

- `start`
- `token`
- `done`
- `error`

### `_StreamingInvoker`
Vnitřní wrapper `_StreamingInvoker` obaluje LLM a sbírá tokeny:

- pokud backend má `.stream()`, tokeny jdou průběžně,
- jinak se fallbackne na jeden token s celou odpovědí.

### Deterministické route
Deterministické route (identity, overview, soft guidance, procedural atd.) vrací kompletní answer jako jeden token.

### LLM route
LLM route posílá tokeny postupně podle toho, jak přicházejí z backendu.

## Queue bridge v `src/api/main.py`
Protože `ask_stream()` je sync generator, backend ho překládá do async SSE pomocí `asyncio.Queue` a background threadu:

1. thread běží `for event in chain.ask_stream(...)`,
2. eventy dá na queue,
3. async endpoint je čte a formátuje přes `_sse_format()`.

## SSE event types

### `start`
Obsahuje metadata:

- `session_id`
- `request_id`
- `answer_strategy`
- `sources`
- `clarification_required`
- `unsupported_reason`
- `confidence_semantic_label`
- `confidence_origin`
- `degraded_answer`

### `token`
Nese text tokenu:

```json
{ "text": "..." }
```

### `done`
Nese timing a route metadata:

- `processing_time_ms`
- `retrieval_latency_ms`
- `llm_latency_ms`
- `formatting_latency_ms`

### `error`
Nese `error` a `detail`.

## Post-stream cache store
Po dokončení streamu backend zkusí uložit `chain._last_stream_result` do response cache, pokud je strategie cacheovatelná.

To znamená, že další request může dostat cache hit i pro streamované odpovědi.

## Frontend consumption
`frontend/src/lib/api.ts` parsuje SSE ručně:

- čte `event:` a `data:` řádky,
- po prázdném řádku vyhodí parsed event,
- vrací generátor `{ event, data }`.

## Omezení

### Bez reconnect logiky
Neexistuje server-side reconnect / resume mechanika.

### Jednoduchý parser
Frontend parser očekává standardní SSE formát a jeden JSON payload na event.

### Bez heartbeatů
Endpoint neposílá heartbeat eventy, takže dlouhé generace závisí na stabilním HTTP spojení.
