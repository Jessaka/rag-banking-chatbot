# RB AI Asistent – Frontend

Frontend pro Raiffeisenbank RAG chatbot – moderní AI asistent pro bankovní dotazy.

Postaveno na **SvelteKit 2**, **TypeScript**, **TailwindCSS** a **shadcn-svelte**.

## Požadavky

- Node.js ≥ 20
- npm ≥ 10

## Instalace

```bash
cd frontend/
npm install
```

## Konfigurace

Zkopírujte `.env.example` na `.env` a nastavte URL backend API:

```bash
cp .env.example .env
```

Výchozí hodnota: `http://localhost:8000`

## Vývoj

```bash
npm run dev
```

Server běží na `http://localhost:5173`.

## Build

```bash
npm run build
npm run preview   # lokální náhled produkčního buildu
```

## Kontrola typů

```bash
npm run check
```

## Struktura

```
src/
├── app.html              # HTML šablona
├── app.css               # Globální styly (Tailwind)
├── app.d.ts              # Typové deklarace
├── lib/
│   ├── api.ts            # API klient (/chat, /health)
│   ├── stores.ts         # Svelte stores (theme, conversations, messages)
│   ├── types.ts          # TypeScript rozhraní
│   ├── utils.ts          # Helper funkce (cn, generateId, formatters)
│   └── components/
│       ├── ui/           # Shadcn-inspired UI komponenty
│       │   ├── button.svelte
│       │   ├── card.svelte
│       │   ├── badge.svelte
│       │   ├── separator.svelte
│       │   └── scroll-area.svelte
│       ├── Header.svelte
│       ├── Sidebar.svelte
│       ├── Chat.svelte
│       ├── ChatMessage.svelte
│       ├── ChatInput.svelte
│       ├── Markdown.svelte
│       ├── SourcesCard.svelte
│       ├── DebugPanel.svelte
│       └── ThemeToggle.svelte
└── routes/
    ├── +layout.svelte    # Hlavní layout (sidebar + header + main)
    ├── +layout.ts        # SSR disabled
    └── +page.svelte      # Chat stránka
```

## API Endpoint

Frontend komunikuje s backendem na `POST /chat`:

```json
// Request
{ "question": "Jaký je poplatek za vedení účtu?", "session_id": "uuid" }

// Response
{
  "answer": "...",
  "sources": [{ "file_name": "...", "page": 1, "chunk_id": "...", "rerank_score": 0.95, "preview": "..." }],
  "session_id": "uuid",
  "processing_time_ms": 1234,
  "answer_strategy": "pricing_row_direct",
  "answer_confidence": "high",
  "retrieval_debug": null
}
```
