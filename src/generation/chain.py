"""
RAG chain pro generování odpovědí na bankovní dotazy.

Architektura:
  retriever → format_context → LLM (Ollama/Mistral) → odpověď

Podporuje:
  - Jednoduchý dotaz (bez historie)
  - Konverzační mód s pamětí posledních N zpráv
  - Přeformulování dotazu s kontextem konverzace (query rewriting)
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_ollama import OllamaLLM

import config
from src.generation.prompts import (
    CONVERSATIONAL_PROMPT,
    QUERY_REWRITE_PROMPT,
    SIMPLE_PROMPT,
    format_context,
)
from src.retrieval.retriever import BankingRetriever
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BankingRAGChain:
    """
    Hlavní RAG chain pro Raiffeisenbank chatbot.

    Použití:
        chain = BankingRAGChain()
        answer = chain.ask("Jaký je poplatek za vedení účtu?")

        # Konverzační mód
        chain = BankingRAGChain(conversational=True)
        answer1 = chain.ask("Co je eKonto?")
        answer2 = chain.ask("Jaké jsou jeho poplatky?")  # navazuje na předchozí
    """

    def __init__(self, conversational: bool = True) -> None:
        self.conversational = conversational
        self.chat_history: list[BaseMessage] = []

        self._llm = OllamaLLM(
            model=config.LLM_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            num_predict=config.LLM_MAX_TOKENS,
        )
        self._retriever = BankingRetriever()

        logger.info(
            f"BankingRAGChain inicializována "
            f"(model: {config.LLM_MODEL}, konverzační: {conversational})"
        )

    def _rewrite_query(self, question: str) -> str:
        """
        Přeformuluje dotaz s ohledem na historii konverzace.
        Používá se pouze pokud existuje neprázdná historie.
        """
        if not self.chat_history:
            return question

        prompt = QUERY_REWRITE_PROMPT
        messages = prompt.format_messages(
            chat_history=self.chat_history,
            question=question,
        )
        rewritten = self._llm.invoke(messages)
        logger.debug(f"Query rewrite: '{question}' → '{rewritten.strip()}'")
        return rewritten.strip()

    def ask(self, question: str) -> dict:
        """
        Položí otázku a vrátí odpověď s metadaty.

        Args:
            question: Uživatelský dotaz v češtině.

        Returns:
            Dict s klíči:
              - answer (str): Vygenerovaná odpověď
              - sources (list[Document]): Použité zdroje
              - rewritten_query (str): Přeformulovaný dotaz (pokud se liší)
        """
        # 1. Query rewriting pro follow-up otázky
        retrieval_query = (
            self._rewrite_query(question)
            if self.conversational
            else question
        )

        # 2. Retrieval
        source_docs: list[Document] = self._retriever.invoke(retrieval_query)

        if not source_docs:
            answer = (
                "Omlouvám se, ale k vašemu dotazu jsem nenalezl relevantní "
                "informace v dostupné dokumentaci. Prosím kontaktujte "
                "zákaznickou linku Raiffeisenbank na čísle 800 900 900."
            )
            return {
                "answer": answer,
                "sources": [],
                "rewritten_query": retrieval_query,
            }

        # 3. Formátování kontextu
        context = format_context(source_docs)

        # 4. Generování odpovědi
        if self.conversational and self.chat_history:
            prompt = CONVERSATIONAL_PROMPT
            messages = prompt.format_messages(
                context=context,
                chat_history=self.chat_history,
                question=question,
            )
        else:
            prompt = SIMPLE_PROMPT
            messages = prompt.format_messages(
                context=context,
                question=question,
            )

        answer: str = self._llm.invoke(messages)

        # 5. Aktualizace konverzační historie
        if self.conversational:
            self.chat_history.append(HumanMessage(content=question))
            self.chat_history.append(AIMessage(content=answer))
            # Ořezání na posledních N zpráv
            limit = config.CONVERSATION_HISTORY_LIMIT
            if len(self.chat_history) > limit * 2:
                self.chat_history = self.chat_history[-(limit * 2):]

        logger.info(
            f"Odpověď vygenerována ({len(answer)} znaků, "
            f"{len(source_docs)} zdrojů)"
        )
        return {
            "answer": answer,
            "sources": source_docs,
            "rewritten_query": retrieval_query,
        }

    def reset_history(self) -> None:
        """Vymaže konverzační historii (nové sezení)."""
        self.chat_history = []
        logger.info("Konverzační historie vymazána")
