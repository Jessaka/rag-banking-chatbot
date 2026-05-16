"""
Systémové a uživatelské prompty pro RAG chain.

Prompty jsou optimalizovány pro:
  - Česky psané bankovní dokumenty
  - Konzervativní odpovědi (vychází výhradně z kontextu)
  - Transparentnost zdrojů (citace dokumentu a stránky)
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

SYSTEM_PROMPT = """Jsi pomocný AI asistent zákaznické podpory Raiffeisenbank.
Odpovídáš výhradně na základě poskytnutého kontextu z interní dokumentace banky.

Pravidla:
1. Odpovídej vždy česky.
2. Pokud odpověď není v kontextu, řekni: "Tuto informaci jsem v dostupných dokumentech nenalezl. Prosím kontaktujte zákaznickou linku Raiffeisenbank na 800 900 900."
3. Nikdy nedomýšlej ani neodhaduj finanční informace (úroky, poplatky, lhůty).
4. U každé informace uveď zdroj ve formátu: [název souboru, str. X].
5. Buď stručný a konkrétní – klient potřebuje jasnou odpověď.
6. Pokud se dotaz týká osobní situace klienta (konkrétní účet, transakce), nasměruj ho do internetového bankovnictví nebo na pobočku.

Kontext z dokumentů:
{context}
"""

HUMAN_TEMPLATE = "{question}"

# Prompt pro konverzační RAG (s historií)
CONVERSATIONAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", HUMAN_TEMPLATE),
    ]
)

# Jednoduchý prompt bez historie (pro jednoduché dotazy)
SIMPLE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_TEMPLATE),
    ]
)

# Prompt pro přeformulování dotazu s ohledem na historii konverzace
QUERY_REWRITE_PROMPT = ChatPromptTemplate.from_messages(
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

    parts = []
    for i, doc in enumerate(documents, start=1):
        file_name = doc.metadata.get("file_name", "neznámý dokument")
        page = doc.metadata.get("page", "?")
        score = doc.metadata.get("rerank_score", "")
        score_str = f" [skóre: {score:.3f}]" if score else ""

        parts.append(
            f"--- Zdroj {i}: {file_name}, str. {page}{score_str} ---\n"
            f"{doc.page_content}\n"
        )

    return "\n".join(parts)
