from __future__ import annotations

import asyncio
from collections.abc import Generator
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

import src.api.main as api_main


class _FakeSessionStore:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict, int | None]] = []

    async def save(self, session_id: str, data: dict, ttl_seconds: int | None = None, **_: object) -> bool:
        self.saved.append((session_id, data, ttl_seconds))
        return True


class _FakeResponseCache:
    def get(self, _key: str) -> None:
        return None

    def add_debug_metadata(self, result: dict, **_: object) -> None:
        return None

    def try_claim_inflight(self, _key: str) -> bool:
        return True

    def signal_inflight_done(self, _key: str) -> None:
        return None

    def wait_inflight(self, _key: str) -> None:
        return None

    def set(self, _key: str, _value: dict) -> None:
        return None


class _FakeDistributedCache:
    async def get(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def set(self, *_args: object, **_kwargs: object) -> None:
        return None

    def get_ttl(self, _namespace: str) -> int:
        return 60


class _FakeChain:
    def __init__(self, question: str, answer: str, strategy: str, current_product: str) -> None:
        self.question = question
        self.answer = answer
        self.strategy = strategy
        self.current_product = current_product
        self.conversational = True
        self.chat_history: list = []
        self.session_context = {
            "current_domain": "retail",
            "current_product": None,
            "current_intent": None,
            "resolved_product": None,
        }
        self._session_debug = {}
        self._last_stream_result: dict | None = None
        self.resolved_product = None
        self.resolved_intent = None
        self.last_canonical_product = None
        self.unresolved_product = None
        self.unresolved_product_type = None
        self.pending_clarification = None
        self.clarification_candidates = None
        self.current_domain = None
        self.current_intent = None

    def _result(self) -> dict:
        return {
            "answer": self.answer,
            "sources": [],
            "answer_strategy": self.strategy,
            "answer_confidence": "high",
            "confidence_bucket": "high",
            "confidence_reason": "test",
            "timing_ms": {"retrieval": 1, "llm": 0, "formatting_latency_ms": 0},
        }

    def _mutate_state(self, question: str) -> dict:
        self.chat_history.append(HumanMessage(content=question))
        self.chat_history.append(AIMessage(content=self.answer))
        self.session_context["current_product"] = self.current_product
        if self.strategy == "account_overview_direct":
            self.session_context["current_intent"] = "account_overview"
        elif self.strategy == "credit_card_catalog_direct":
            self.session_context["current_intent"] = "credit_card_catalog"
        result = self._result()
        self._last_stream_result = result
        return result

    def ask(self, question: str) -> dict:
        return self._mutate_state(question)

    def ask_stream(self, question: str) -> Generator[dict, None, None]:
        result = self._mutate_state(question)
        yield {
            "type": "start",
            "answer_strategy": self.strategy,
            "sources": [],
            "cache_hit": False,
        }
        yield {"type": "token", "text": self.answer}
        yield {
            "type": "done",
            "processing_time_ms": 1,
            "answer_strategy": self.strategy,
            "sources": [],
            "confidence_bucket": result.get("confidence_bucket"),
        }


def _parse_sse_text(raw: str) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for chunk in raw.strip().split("\n\n"):
        lines = [line for line in chunk.splitlines() if line]
        if len(lines) < 2:
            continue
        event = lines[0].removeprefix("event: ")
        payload = api_main.json.loads(lines[1].removeprefix("data: "))
        events.setdefault(event, []).append(payload)
    return events


def test_collect_restore_chain_session_state_mirrors_chat_history_and_current_product() -> None:
    chain = SimpleNamespace(
        resolved_product=None,
        resolved_intent=None,
        last_canonical_product=None,
        unresolved_product=None,
        unresolved_product_type=None,
        pending_clarification=None,
        clarification_candidates=None,
        current_domain=None,
        current_intent=None,
        current_product=None,
        chat_history=[HumanMessage(content="Jaké účty nabízíte?"), AIMessage(content="Máme ...")],
        session_context={
            "current_domain": "retail",
            "current_product": "osobni_ucet",
            "current_intent": "account_overview",
            "resolved_product": None,
        },
    )

    state = api_main._collect_chain_session_state(chain)

    assert state["current_product"] == "osobni_ucet"
    assert state["chat_history"][0]["content"] == "Jaké účty nabízíte?"

    restored = SimpleNamespace(
        resolved_product=None,
        resolved_intent=None,
        last_canonical_product=None,
        unresolved_product=None,
        unresolved_product_type=None,
        pending_clarification=None,
        clarification_candidates=None,
        current_domain=None,
        current_intent=None,
        current_product=None,
        chat_history=[],
        session_context={
            "current_domain": None,
            "current_product": None,
            "current_intent": None,
            "resolved_product": None,
        },
    )

    api_main._restore_chain_session_state(restored, state)

    assert len(restored.chat_history) == 2
    assert restored.session_context["current_product"] == "osobni_ucet"


def test_chat_and_stream_persist_followup_state(monkeypatch) -> None:
    client = TestClient(api_main.app)
    fake_store = _FakeSessionStore()
    fake_cache = _FakeResponseCache()
    fake_distributed_cache = _FakeDistributedCache()

    monkeypatch.setattr(api_main, "_warmup_complete", True)
    monkeypatch.setattr(api_main, "_session_store", fake_store)
    monkeypatch.setattr(api_main, "_response_cache", fake_cache)
    monkeypatch.setattr(api_main, "_distributed_cache", fake_distributed_cache)
    monkeypatch.setattr(api_main, "_is_cacheable", lambda _result: False)
    monkeypatch.setattr(api_main.telemetry, "emit", lambda *_args, **_kwargs: None)

    scenarios = [
        ("/chat", "Jaké účty nabízíte?", "account_overview_direct", "osobni_ucet"),
        ("/chat", "Jaké kreditní karty nabízíte?", "credit_card_catalog_direct", "kreditni_karta"),
        ("/chat/stream", "Jaké účty nabízíte?", "account_overview_direct", "osobni_ucet"),
        ("/chat/stream", "Jaké kreditní karty nabízíte?", "credit_card_catalog_direct", "kreditni_karta"),
    ]

    for idx, (route, question, strategy, current_product) in enumerate(scenarios, start=1):
        fake_chain = _FakeChain(question, "test answer", strategy, current_product)

        async def _fake_get_or_create_session(_session_id: str | None) -> tuple[str, _FakeChain, asyncio.Lock]:
            return f"session-{idx}", fake_chain, asyncio.Lock()

        monkeypatch.setattr(api_main, "_get_or_create_session", _fake_get_or_create_session)

        if route == "/chat":
            response = client.post(route, json={"question": question})
            assert response.status_code == 200
            assert response.json()["answer_strategy"] == strategy
        else:
            with client.stream("POST", route, json={"question": question}) as response:
                assert response.status_code == 200
                events = _parse_sse_text(response.read().decode("utf-8"))
                assert events["start"][0]["answer_strategy"] == strategy
                assert events["done"][0]["answer_strategy"] == strategy

        saved_session_id, saved_state, _ttl = fake_store.saved[-1]
        assert saved_session_id == f"session-{idx}"
        assert len(saved_state["chat_history"]) == 2
        assert saved_state["current_product"] == current_product
        assert saved_state["session_context"]["current_product"] == current_product
