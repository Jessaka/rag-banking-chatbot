"""
RAG chain pro generování odpovědí na bankovní dotazy.

Podporuje tři LLM backendy (config.LLM_BACKEND):
  - "ollama"     → lokální Mistral/Llama přes Ollama (bez cloudu)
  - "anthropic"  → claude-haiku-4-5 přes Anthropic SDK s prompt cachingem
  - "gemini"     → gemini-1.5-flash přes Google Gemini SDK (google-genai)

Pipeline: retriever → format_context → LLM → odpověď
Konverzační mód: query rewriting + paměť posledních N zpráv
"""

from __future__ import annotations

import time

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
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


# ---------------------------------------------------------------------------
# Anthropic LLM wrapper
# ---------------------------------------------------------------------------

class AnthropicLLM:
    """
    Wrapper kolem Anthropic Python SDK kompatibilní s rozhraním OllamaLLM.

    Přijímá seznam LangChain BaseMessage objektů (výstup z prompt.format_messages()),
    konvertuje je do Anthropic messages.create() formátu a vrací text odpovědi.

    Prompt caching:
      Systémová zpráva (instrukce + retrieved kontext) je označena
      cache_control="ephemeral". Při opakovaných dotazech se stejným kontextem
      (follow-up otázky, stejné dokumenty) API vrátí výsledek z cache za ~0.1×
      vstupních tokenů místo plné ceny.
      Minimální cacheable prefix pro Haiku 4.5 je ~4 096 tokenů; u kratšího
      kontextu se caching tiše přeskočí bez chyby.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
    ) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        logger.info(f"AnthropicLLM inicializována (model: {model})")

    def invoke(self, messages: list[BaseMessage]) -> str:
        """
        Volá Anthropic messages.create() a vrátí text první odpovědi.

        Args:
            messages: LangChain BaseMessage list z prompt.format_messages().
                      SystemMessage → system param s cache_control
                      HumanMessage → role "user"
                      AIMessage    → role "assistant"
        """
        system_text = ""
        anthropic_messages: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                anthropic_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                anthropic_messages.append({"role": "assistant", "content": msg.content})

        # Ephemeral cache na systémové zprávě.
        # Snižuje cenu za konverzace s opakujícím se kontextem.
        system_param = (
            [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
            if system_text
            else None
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system_param,
            messages=anthropic_messages,
        )

        usage = response.usage
        logger.debug(
            f"Anthropic usage – input: {usage.input_tokens}, "
            f"output: {usage.output_tokens}, "
            f"cache_read: {getattr(usage, 'cache_read_input_tokens', 0)}, "
            f"cache_write: {getattr(usage, 'cache_creation_input_tokens', 0)}"
        )

        return response.content[0].text


# ---------------------------------------------------------------------------
# Google Gemini – auto-discovery + LLM wrapper
# ---------------------------------------------------------------------------

# Prioritizovaný seznam modelů pro automatický výběr.
# client.models.list() vrací jména ve formátu "models/gemini-*";
# pro API volání se používá jméno BEZ prefixu "models/".
_GEMINI_MODEL_PRIORITY: list[str] = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
]

# Vzory modelů k přeskočení (embedding, TTS, vision-only, deprecated)
_GEMINI_SKIP_PATTERNS = ("embed", "tts", "vision", "aqa", "imagen", "deprecated")


def discover_gemini_model(api_key: str) -> str:
    """
    Dotáže se Gemini API na seznam dostupných modelů a vrátí nejlepší
    dostupný model podporující generateContent.

    Algoritmus:
      1. Zavolá client.models.list() a extrahuje jména bez prefixu "models/"
      2. Projde _GEMINI_MODEL_PRIORITY → vrátí první, který je dostupný
      3. Pokud žádný z priority listu není dostupný, vrátí první flash model
         s generateContent nebo count_tokens capability
      4. Pokud ani to selže, vrátí výchozí "gemini-2.0-flash"

    Args:
        api_key: Platný Gemini API klíč.

    Returns:
        Název modelu pro použití v generate_content() (bez prefixu "models/").
    """
    from google import genai

    try:
        client = genai.Client(api_key=api_key)

        # Načteme dostupné modely a normalizujeme jména (strip "models/" prefix)
        available: list[str] = []
        for m in client.models.list():
            raw_name: str = m.name or ""
            short_name = raw_name.removeprefix("models/")

            # Přeskočíme modely bez jména nebo s nevhodným vzorem
            if not short_name:
                continue
            if any(pat in short_name.lower() for pat in _GEMINI_SKIP_PATTERNS):
                continue

            available.append(short_name)

        logger.debug(f"Dostupné Gemini modely: {available}")

        # Krok 1: zkontrolujeme priority list
        for preferred in _GEMINI_MODEL_PRIORITY:
            if preferred in available:
                logger.info(f"Auto-discovery: zvolen model '{preferred}'")
                return preferred

        # Krok 2: první flash model v dostupných
        flash_models = [m for m in available if "flash" in m.lower()]
        if flash_models:
            chosen = flash_models[0]
            logger.info(f"Auto-discovery: zvolen první flash model '{chosen}'")
            return chosen

        # Krok 3: bezpečný fallback
        logger.warning("Auto-discovery nenašla vhodný model, používám fallback 'gemini-2.0-flash'")

    except Exception as exc:
        logger.warning(f"Auto-discovery selhala: {exc} – používám výchozí model z konfigurace")

    return "gemini-2.0-flash"


class GeminiLLM:
    """
    Wrapper kolem Google Gemini SDK (google-genai) kompatibilní s rozhraním OllamaLLM.

    Při inicializaci volitelně zavolá discover_gemini_model() pro automatický
    výběr nejlepšího dostupného modelu – viz config.GEMINI_MODEL.

    Konverze LangChain BaseMessage → Gemini Contents:
      SystemMessage → GenerateContentConfig.system_instruction
      HumanMessage  → role "user"
      AIMessage     → role "model"  (Gemini používá "model", ne "assistant")

    Poznámka: google-generativeai je deprecated; tento wrapper používá
    officiální nástupce google-genai (from google import genai).
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
    ) -> None:
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._max_tokens = max_tokens
        self._temperature = temperature

        # Pokud je model nastaven na výchozí hodnotu, ověříme dostupnost
        # přes API; jinak respektujeme explicitní nastavení uživatele.
        if model == "gemini-2.0-flash":
            self._model = discover_gemini_model(api_key)
        else:
            self._model = model

        logger.info(f"GeminiLLM inicializována (model: {self._model})")

    def invoke(self, messages: list[BaseMessage]) -> str:
        """
        Volá Gemini generate_content a vrátí text odpovědi.

        Args:
            messages: LangChain BaseMessage list z prompt.format_messages().
                      SystemMessage → system_instruction v config
                      HumanMessage  → role "user"
                      AIMessage     → role "model"
        """
        from google.genai import types

        system_text = ""
        contents: list[dict] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = msg.content
            elif isinstance(msg, HumanMessage):
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif isinstance(msg, AIMessage):
                # Gemini používá "model" jako roli asistenta, ne "assistant"
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        generation_config = types.GenerateContentConfig(
            system_instruction=system_text or None,
            max_output_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=generation_config,
        )

        return response.text


# ---------------------------------------------------------------------------
# Factory – výběr backendu dle konfigurace
# ---------------------------------------------------------------------------

def _build_llm() -> OllamaLLM | AnthropicLLM:
    """
    Vytvoří LLM instanci dle config.LLM_BACKEND.

    Returns:
        OllamaLLM  – pokud LLM_BACKEND == "ollama"
        AnthropicLLM – pokud LLM_BACKEND == "anthropic"

    Raises:
        ValueError: Při neznámém backendu nebo chybějícím ANTHROPIC_API_KEY.
    """
    backend = config.LLM_BACKEND.lower()

    if backend == "ollama":
        return OllamaLLM(
            model=config.LLM_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            temperature=config.LLM_TEMPERATURE,
            num_predict=config.LLM_MAX_TOKENS,
        )

    if backend == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise ValueError(
                "LLM_BACKEND='anthropic' vyžaduje nastavený ANTHROPIC_API_KEY v .env"
            )
        return AnthropicLLM(
            model=config.ANTHROPIC_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        )

    if backend == "gemini":
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "LLM_BACKEND='gemini' vyžaduje nastavený GEMINI_API_KEY v .env"
            )
        return GeminiLLM(
            model=config.GEMINI_MODEL,
            api_key=config.GEMINI_API_KEY,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
        )

    raise ValueError(
        f"Neznámý LLM_BACKEND='{config.LLM_BACKEND}'. "
        f"Povolené hodnoty: 'ollama', 'anthropic', 'gemini'."
    )


# ---------------------------------------------------------------------------
# BankingRAGChain
# ---------------------------------------------------------------------------

class BankingRAGChain:
    """
    Hlavní RAG chain pro Raiffeisenbank chatbot.

    Backend se volí automaticky dle config.LLM_BACKEND:
      - "ollama"    → lokální LLM (Mistral/Llama), žádné cloudové volání
      - "anthropic" → claude-haiku-4-5 s prompt cachingem, rychlý a levný

    Použití:
        chain = BankingRAGChain()
        result = chain.ask("Jaký je poplatek za vedení účtu?")
        print(result["answer"])

        # Konverzační mód (výchozí)
        chain = BankingRAGChain(conversational=True)
        chain.ask("Co je eKonto?")
        chain.ask("Jaké jsou jeho poplatky?")  # navazuje na kontext
    """

    def __init__(self, conversational: bool = True) -> None:
        self.conversational = conversational
        self.chat_history: list[BaseMessage] = []

        self._llm = _build_llm()
        self._retriever = BankingRetriever()

        if config.LLM_BACKEND == "anthropic":
            backend_info = f"anthropic/{config.ANTHROPIC_MODEL}"
        elif config.LLM_BACKEND == "gemini":
            backend_info = f"gemini/{config.GEMINI_MODEL}"
        else:
            backend_info = f"ollama/{config.LLM_MODEL}"
        logger.info(
            f"BankingRAGChain inicializována "
            f"(backend: {backend_info}, konverzační: {conversational})"
        )

    def _rewrite_query(self, question: str) -> str:
        """
        Přeformuluje dotaz s ohledem na historii konverzace.
        Používá se pouze pokud existuje neprázdná historie.
        """
        if not self.chat_history:
            return question

        messages = QUERY_REWRITE_PROMPT.format_messages(
            chat_history=self.chat_history,
            question=question,
        )
        rewritten = self._llm.invoke(messages)
        # OllamaLLM vrátí str, AnthropicLLM také vrátí str
        rewritten_text = rewritten if isinstance(rewritten, str) else str(rewritten)
        logger.debug(f"Query rewrite: '{question}' → '{rewritten_text.strip()}'")
        return rewritten_text.strip()

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
        t_ask = time.perf_counter()

        # 1. Query rewriting pro follow-up otázky
        t_rewrite = time.perf_counter()
        retrieval_query = (
            self._rewrite_query(question)
            if self.conversational
            else question
        )
        rewrite_ms = (time.perf_counter() - t_rewrite) * 1000
        if self.chat_history:  # rewriting probíhá jen pokud existuje historie
            logger.info(f"⏱ Query rewriting: {rewrite_ms:.0f}ms")

        # 2. Retrieval
        t_retrieval = time.perf_counter()
        source_docs: list[Document] = self._retriever.invoke(retrieval_query)
        retrieval_ms = (time.perf_counter() - t_retrieval) * 1000

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
            messages = CONVERSATIONAL_PROMPT.format_messages(
                context=context,
                chat_history=self.chat_history,
                question=question,
            )
        else:
            messages = SIMPLE_PROMPT.format_messages(
                context=context,
                question=question,
            )

        backend = config.LLM_BACKEND
        model_name = (
            config.ANTHROPIC_MODEL if backend == "anthropic"
            else config.GEMINI_MODEL if backend == "gemini"
            else config.LLM_MODEL
        )
        t_llm = time.perf_counter()
        answer = self._llm.invoke(messages)
        llm_ms = (time.perf_counter() - t_llm) * 1000
        answer_text = answer if isinstance(answer, str) else str(answer)

        total_ms = (time.perf_counter() - t_ask) * 1000

        # 5. Aktualizace konverzační historie
        if self.conversational:
            self.chat_history.append(HumanMessage(content=question))
            self.chat_history.append(AIMessage(content=answer_text))
            limit = config.CONVERSATION_HISTORY_LIMIT
            if len(self.chat_history) > limit * 2:
                self.chat_history = self.chat_history[-(limit * 2):]

        logger.info(
            f"⏱ LLM generation ({backend}/{model_name}): {llm_ms:.0f}ms "
            f"({len(answer_text)} znaků)"
        )
        logger.info(
            f"⏱ TOTAL ask(): {total_ms:.0f}ms "
            f"[retrieval={retrieval_ms:.0f}ms, llm={llm_ms:.0f}ms]"
        )
        return {
            "answer": answer_text,
            "sources": source_docs,
            "rewritten_query": retrieval_query,
        }

    def reset_history(self) -> None:
        """Vymaže konverzační historii (nové sezení)."""
        self.chat_history = []
        logger.info("Konverzační historie vymazána")
