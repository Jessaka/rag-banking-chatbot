# RAG Banking Chatbot — Raiffeisenbank

Produkčně připravený RAG (Retrieval-Augmented Generation) chatbot pro zákaznickou podporu Raiffeisenbank. Chatbot odpovídá na otázky klientů na základě veřejně dostupných bankovních dokumentů (sazebníky, podmínky produktů, FAQ, hypoteční materiály) s plnou lokální inference — žádné cloudové API.

---

## Architektura

```
                  ┌─────────────────────────────────────────┐
                  │           INGESTION PIPELINE            │
                  │                                         │
  PDF (rb.cz) ──► │ Downloader → Parser → Chunker → Indexer │
                  │                            │            │
                  └────────────────────────────┼────────────┘
                                               │
                              ┌────────────────┴──────────────┐
                              │         STORAGE               │
                              │  Qdrant (dense) + BM25 (pkl)  │
                              └────────────────┬──────────────┘
                                               │
                  ┌────────────────────────────▼────────────┐
                  │           QUERY PIPELINE                 │
                  │                                         │
  Dotaz ────────► │  Hybrid Search (BM25 + Qdrant) → RRF    │
                  │         │                               │
                  │         ▼                               │
                  │  BGE Reranker (cross-encoder)           │
                  │         │                               │
                  │         ▼                               │
                  │  Mistral 7B (Ollama) → Odpověď          │
                  └─────────────────────────────────────────┘
```

### Klíčové komponenty

| Komponenta | Technologie | Účel |
|---|---|---|
| **LLM** | Mistral 7B (Ollama) | Generování odpovědí v češtině |
| **Embeddings** | nomic-embed-text (Ollama) | Dense vektorová reprezentace |
| **Vektorová DB** | Qdrant | Dense retrieval s cosine similaritou |
| **Sparse retrieval** | BM25 (rank-bm25) | Přesné shody klíčových slov |
| **Fúze** | Reciprocal Rank Fusion | Kombinace dense + sparse výsledků |
| **Reranker** | BGE-Reranker-v2-m3 | Cross-encoder rescoring pro přesnost |
| **PDF parser** | PyMuPDF + pdfplumber | Extrakce textu s fallbackem |
| **Chunking** | RecursiveCharacterTextSplitter | Překrývající se kontextové chunky |

### Proč hybridní přístup?

- **BM25** zachytí přesné shody: čísla produktů, zkratky (RPSN, ČNB), specifické termíny
- **Dense retrieval** zachytí sémantické ekvivalenty: „jak otevřít účet" ≈ „zřízení bankovního konta"
- **RRF** kombinuje pořadí bez nutnosti normalizovat různorodá skóre
- **Reranker** jako finální pojistka: cross-encoder má přístup k celému textu páru (dotaz, chunk), čímž překoná bi-encoder přesností

---

## Rychlý start

### Prerekvizity

```bash
# 1. Ollama – lokální LLM inference
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral
ollama pull nomic-embed-text

# 2. Qdrant – vektorová databáze (Docker)
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/data/qdrant_storage:/qdrant/storage \
  qdrant/qdrant

# 3. Python závislosti
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Konfigurace

```bash
cp .env.example .env
# Upravte .env dle potřeby (výchozí hodnoty fungují pro lokální běh)
```

### Scraping (automatické získání dokumentů)

```bash
# Plné spuštění: najde PDF + FAQ na rb.cz a stáhne je
python scripts/scrape_rb.py

# Dry-run: pouze zapíše sources.txt, nestahuje soubory
python scripts/scrape_rb.py --dry-run

# Omezení rozsahu (výchozí: 600 stránek)
python scripts/scrape_rb.py --max-pages 200

# Vlastní delay (výchozí: 1–3 s náhodný rozsah)
python scripts/scrape_rb.py --delay 2.0
```

### Ingestion

```bash
# Varianta A: po scrapingu (sources.txt + data/raw/ jsou připraveny)
python scripts/ingest.py

# Varianta B: vlastní seznam URL
python scripts/ingest.py --urls-file data/sources.txt

# Varianta C: pouze lokální PDF (bez stahování)
python scripts/ingest.py --skip-download
```

### Spuštění chatbotu

```bash
# Základní mód
python scripts/chat.py

# Se zobrazením zdrojů
python scripts/chat.py --show-sources

# Debug mód (retrieval skóre)
python scripts/chat.py --debug

# Bez konverzační paměti (každý dotaz samostatný)
python scripts/chat.py --no-history
```

---

## Struktura projektu

```
rag-banking-chatbot/
├── config.py                    # Centrální konfigurace
├── requirements.txt
├── .env.example
├── data/sources.txt             # Auto-generováno scraperem
│
├── scripts/
│   ├── scrape_rb.py             # Web scraper (sitemap → PDF + FAQ discovery)
│   ├── ingest.py                # CLI: ingestion pipeline
│   └── chat.py                  # CLI: interaktivní chatbot
│
├── src/
│   ├── ingestion/
│   │   ├── downloader.py        # Stahování PDF z URL
│   │   ├── parser.py            # Extrakce textu (PyMuPDF + pdfplumber)
│   │   ├── chunker.py           # RecursiveCharacterTextSplitter
│   │   └── indexer.py           # Indexace do Qdrant + BM25
│   │
│   ├── retrieval/
│   │   ├── bm25_retriever.py    # Sparse BM25 vyhledávání
│   │   ├── vector_retriever.py  # Dense Qdrant vyhledávání
│   │   ├── hybrid.py            # RRF fúze
│   │   ├── reranker.py          # BGE cross-encoder reranking
│   │   └── retriever.py         # Orchestrace (LangChain BaseRetriever)
│   │
│   ├── generation/
│   │   ├── prompts.py           # České systémové prompty + format_context
│   │   └── chain.py             # BankingRAGChain (query rewriting, paměť)
│   │
│   └── utils/
│       └── logger.py            # Rich logging
│
└── data/
    ├── raw/                     # Stažené PDF soubory
    ├── processed/               # (rezerva pro mezivýstupy)
    ├── indexes/                 # BM25 index + document store (pickle)
    └── sources.txt              # (volitelný) seznam URL, jeden na řádek
```

---

## Konfigurace (config.py / .env)

| Proměnná | Výchozí | Popis |
|---|---|---|
| `QDRANT_HOST` | `localhost` | Host Qdrant instance |
| `QDRANT_PORT` | `6333` | Port Qdrant REST API |
| `QDRANT_COLLECTION` | `raiffeisenbank_docs` | Název kolekce |
| `LLM_MODEL` | `mistral` | Ollama model pro generování |
| `EMBED_MODEL` | `nomic-embed-text` | Ollama embed model |
| `CHUNK_SIZE` | `1000` | Max. délka chunku (znaky) |
| `CHUNK_OVERLAP` | `200` | Překryv sousedních chunků |
| `RERANKER_DEVICE` | `cpu` | `cpu` nebo `cuda` |
| `LLM_TEMPERATURE` | `0.1` | Kreativita LLM (nízká = faktická) |

---

## data/sources.txt – formát

```
# Komentáře začínají #
# Jeden URL na řádek

https://www.rb.cz/attachments/sazebniky/sazebnik-fyzicke-osoby.pdf
https://www.rb.cz/attachments/produkty/podminky-ekonto.pdf
```

---

## Rozšíření a ladění

### Přidání GPU akcelerace
```bash
# .env
RERANKER_DEVICE=cuda

# Pro GPU verzi PyTorch (CUDA 12.1):
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### Výměna LLM
```bash
# .env
LLM_MODEL=llama3.1
ollama pull llama3.1
```

### Ladění retrieval parametrů
V `config.py`:
```python
BM25_TOP_K = 20       # Více kandidátů → pomalejší reranking, lepší pokrytí
VECTOR_TOP_K = 20
HYBRID_TOP_K = 10     # Počet výsledků do rerankeru
RERANK_TOP_K = 5      # Finální kontext pro LLM
```

---

## Technické poznámky

**Proč nomic-embed-text?** Model s 768 dimenzemi optimalizovaný pro anglický a vícejazyčný text, provozovatelný lokálně přes Ollama. Pro ryze český deployment lze zvážit `multilingual-e5-large`.

**Proč BGE-Reranker-v2-m3?** Vícejazyčný cross-encoder s vynikajícím výkonem na BEIR benchmarku. Verze `v2-m3` je optimalizována pro RAG use case a podporuje češtinu.

**Proč RRF místo váženého průměru skóre?** BM25 skóre a cosine similarity mají různé škály a distribuce. RRF kombinuje pouze pořadí, čímž je robustní vůči outlierům.

**Chunking s překryvem:** `chunk_overlap=200` zajistí, že věty na hranici chunků neztratí kontext. U tabulek a sazebníků může být výhodné zvýšit na 300.

---

## Licence

MIT License — volně použitelné pro komerční i nekomerční účely.

---

*Projekt je určen jako portfolio ukázka moderního RAG systému. Není oficiálním produktem Raiffeisenbank a.s.*
