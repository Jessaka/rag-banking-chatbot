# Security

## Aktuální opatření

### CORS
`src/api/main.py` používá `CORSMiddleware` s origins z `CORS_ALLOWED_ORIGINS`.

### Rate limiting
Volitelný per-IP sliding window rate limit je zapnutelný přes `RATE_LIMIT_ENABLED`.

Platí jen pro:

- `/chat`
- `/chat/stream`

### Security headers
Backend přidává:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'; ...`

### Request body limit
Middleware odmítne request nad `MAX_REQUEST_BODY_BYTES` (default 10 KB), pokud je nastaven `Content-Length`.

### Input validation
`ChatRequest.question` má `max_length=2000`.

## Kde to je implementované
Všechno výše je v `src/api/main.py`.

## Známá rizika

### Bez API auth
Backend nemá API key auth ani user auth vrstvu.

### Docs jsou otevřené
FastAPI docs jsou zapnuté (`/docs`, `/redoc`).

### Žádný CSP report-to
CSP je statická hlavička bez report endpointu.

### Body limit spoléhá na Content-Length
Chunked nebo streamované requesty bez správného headeru se touto kontrolou nemusí zachytit včas.

### Session state je citlivý na škálování
Bez sticky sessions nebo externího session store může multi-instance nasazení rozbít konverzační kontinuity.

## Produkční doporučení

### 1. Omezit CORS
V produkci povolit jen konkrétní frontend originy.

### 2. Vypnout docs
Pokud není potřeba veřejné API prohlížení, vypnout `/docs` a `/redoc`.

### 3. Přidat auth vrstvu
Pro veřejný provoz doplnit API auth nebo gateway-level auth.

### 4. Monitoring a alerting
Sledovat:

- 429 rate limit odpovědi,
- 5xx chyby,
- latenci `/chat` a `/chat/stream`,
- Qdrant/BM25 health.

### 5. Zapnout telemetry
`TELEMETRY_ENABLED=true` pomůže s auditovatelným provozem, ale query logging mode by měl být zvolen podle privacy policy.
