"""
Systémové a uživatelské prompty pro RAG chain.

Prompty jsou optimalizovány pro:
  - Česky psané bankovní dokumenty
  - Konzervativní odpovědi (vychází výhradně z kontextu)
  - Transparentnost zdrojů (citace dokumentu a stránky)
"""

from functools import lru_cache
import logging
import time

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Jsi pomocný AI asistent zákaznické podpory Raiffeisenbank.
Odpovídáš výhradně na základě poskytnutého kontextu z interní dokumentace banky.

Pravidla:
1. Odpovídej vždy česky.
2. Pokud odpověď není v kontextu, řekni: "Tuto informaci jsem v dostupných dokumentech nenalezl. Prosím kontaktujte zákaznickou linku Raiffeisenbank na 800 900 900."
3. Nikdy nedomýšlej ani neodhaduj finanční informace (úroky, poplatky, lhůty).
4. U cen, sazeb a poplatků vždy uveď zdroj ve formátu: [název zdroje, URL].
5. Buď stručný a konkrétní – klient potřebuje jasnou odpověď.
6. Pokud se dotaz týká osobní situace klienta (konkrétní účet, transakce), nasměruj ho do internetového bankovnictví nebo na pobočku.
7. Odpověď strukturuj přirozeně: krátké shrnutí, potom bullet points. Pokud existuje více pricing variant, odděl je do samostatných odrážek.
8. Nezmiňuj interní metadata, chunk_id, hash, technické názvy souborů ani skóre retrievalu.

Kontext z dokumentů:
{context}
"""

HUMAN_TEMPLATE = "{question}"

def _prompt_classes():
    t_import = time.perf_counter()
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    logger.info(f"import_timing.langchain_core.prompts ms={(time.perf_counter() - t_import) * 1000:.1f}")
    return ChatPromptTemplate, MessagesPlaceholder


@lru_cache(maxsize=1)
def get_conversational_prompt():
    """Lazy prompt builder; avoids importing prompt stack during API module import."""
    ChatPromptTemplate, MessagesPlaceholder = _prompt_classes()
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", HUMAN_TEMPLATE),
        ]
    )


@lru_cache(maxsize=1)
def get_simple_prompt():
    """Lazy prompt builder for non-conversational RAG."""
    ChatPromptTemplate, _MessagesPlaceholder = _prompt_classes()
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ]
    )


@lru_cache(maxsize=1)
def get_query_rewrite_prompt():
    """Lazy prompt builder for query rewriting."""
    ChatPromptTemplate, MessagesPlaceholder = _prompt_classes()
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Přeformuluj následující otázku uživatele tak, aby byla samostatná "
                "a obsahovala veškerý kontext z předchozí konverzace. "
                "Vrať pouze přeformulovanou otázku, bez vysvětlení.",
            ),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ]
    )


def format_context(documents) -> str:
    """
    Formátuje seznam Document objektů do přehledného kontextového bloku.

    Každý chunk je označen zdrojem pro snadné citování v odpovědi.
    """
    if not documents:
        return "Žádný relevantní kontext nenalezen."

    has_pricing_row = any(doc.metadata.get("chunk_type") == "pricing_row" for doc in documents)
    if has_pricing_row:
        documents = [
            doc for doc in documents
            if doc.metadata.get("chunk_type") not in {"table", "pdf_table"}
        ]

    parts = []
    for i, doc in enumerate(documents, start=1):
        title = doc.metadata.get("title") or doc.metadata.get("section_title") or "Raiffeisenbank zdroj"
        source_url = doc.metadata.get("source_url") or doc.metadata.get("url") or ""
        page = doc.metadata.get("page")
        page_str = f", str. {page}" if page else ""

        parts.append(
            f"--- Zdroj {i}: {title}{page_str} ---\n"
            f"URL: {source_url}\n"
            f"{doc.page_content}\n"
        )

    return "\n".join(parts)
