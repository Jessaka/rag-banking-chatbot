# Telemetrie

## Co to je
Telemetrie je JSONL logger v `src/utils/telemetry.py`. Slouží pro produkční observability bez blokování request path.

## Architektura

### Non-blocking zápis
`TelemetryLogger` používá:

- background daemon thread,
- `queue.Queue`,
- append do JSONL souboru.

`telemetry.emit()` jen vloží event do queue; request thread nečeká na disk.

### Výchozí storage
Soubor je podle konfigurace typicky:

```text
logs/telemetry.jsonl
```

## Event types
Podporovaných je 16 eventů:

1. `request_started`
2. `cache_hit`
3. `cache_miss`
4. `retrieval_started`
5. `retrieval_completed`
6. `ranking_completed`
7. `llm_started`
8. `llm_completed`
9. `stream_started`
10. `stream_completed`
11. `stream_cancelled`
12. `clarification_triggered`
13. `unsupported_triggered`
14. `degradation_triggered`
15. `response_completed`
16. `error`

## Privacy

### Hashované session IDs
`session_id` se vždy ukládá jako `session_id_hash`.

### Query logging režimy
`TELEMETRY_QUERY_LOGGING` podporuje:

- `hashed` (default),
- `full`,
- `none`.

### Co je důležité
Při `hashed` režimu se ukládá `question_hash`, ne raw otázka.

## Konfigurace přes env

- `TELEMETRY_ENABLED`
- `TELEMETRY_LOG_PATH`
- `TELEMETRY_QUERY_LOGGING`

## Hooky v `src/api/main.py`
Backend telemetry emituje hlavně na těchto místech:

- request start,
- cache hit / miss,
- session init error,
- chain error,
- response completed,
- stream started / completed,
- stream error.

## Jak analyzovat data

### Základní princip
Každý řádek je samostatný JSON objekt.

### Příklad dotazů

```bash
jq -r '.event' logs/telemetry.jsonl | sort | uniq -c
jq 'select(.event=="error")' logs/telemetry.jsonl
jq 'select(.event=="response_completed") | {route, latency_ms, confidence_bucket}' logs/telemetry.jsonl
```

### Na co se dívat
- podíl cache hitů,
- latence podle route,
- počet degradací,
- error typy,
- session-level chování v čase.

## Omezení

### Není to tracing systém
Telemetrie není full distributed tracing; je to lehký event log.

### Bez zápisu do DB
Data se neukládají do databáze, pouze do JSONL souboru.
