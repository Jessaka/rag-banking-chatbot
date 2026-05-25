# Deployment readiness

This milestone packages the existing FastAPI backend and SvelteKit frontend without changing retrieval, pricing, ingest, embeddings, or Qdrant collections.

## Services

- `backend`: FastAPI app on port `8000`.
- `frontend`: SvelteKit Node server on port `3000`.
- `qdrant`: vector database on port `6333`.

## Quick start

```bash
cp .env.production.example .env
# Fill OPENAI_API_KEY and production URLs.
docker compose up --build
```

Frontend: <http://localhost:3000>  
Backend health: <http://localhost:8000/health>

## Production notes

1. Use a real reverse proxy/TLS layer in front of frontend and backend.
2. Set `VITE_API_URL` to the public backend origin at build time.
3. Keep `DEBUG_API_ERRORS=false` so retrieval internals are not exposed to users.
4. Backend sessions are in-memory. For multi-instance deployment, use sticky sessions or add an external session store before scaling horizontally.
5. Do not run ingest/crawl/reindex in the serving stack. Qdrant data must be provisioned separately.
6. Restrict backend CORS for production domains before public exposure.

## Smoke checks

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"kdo jste","session_id":"smoke"}'
```

Expected `/chat` behavior for the identity smoke test:

- `answer_strategy=identity_direct`
- no source documents
- `confidence_bucket=high`

## Frontend telemetry hook

The frontend emits browser `CustomEvent` events named `rb-chat-telemetry` for latency, confidence, unsupported, clarification, copy, retry, source expand, and escalation actions. A production analytics adapter can subscribe to those events without changing chat UI components.
