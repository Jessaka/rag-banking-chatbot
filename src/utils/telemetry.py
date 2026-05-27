"""
Lightweight JSONL telemetry logger for production observability.

Features:
  - Non-blocking fire-and-forget via background thread + queue.
  - Structured JSONL events with timestamp, request_id, session_id_hash, route, etc.
  - Configurable via TELEMETRY_ENABLED, TELEMETRY_LOG_PATH, TELEMETRY_QUERY_LOGGING.
  - Query stored as hash by default (or "full" / "none" via env).

Usage:
    from src.utils.telemetry import telemetry

    telemetry.emit("request_started", request_id="abc", route="pricing")
    telemetry.emit("llm_completed", request_id="abc", latency_ms=1234.5)
    telemetry.shutdown()
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import config

logger = getLogger(__name__)

_TELEMETRY_EVENTS: list[str] = [
    "request_started",
    "cache_hit",
    "cache_miss",
    "retrieval_started",
    "retrieval_completed",
    "ranking_completed",
    "llm_started",
    "llm_completed",
    "stream_started",
    "stream_completed",
    "stream_cancelled",
    "clarification_triggered",
    "unsupported_triggered",
    "degradation_triggered",
    "response_completed",
    "error",
]


def _hash_id(value: str) -> str:
    """Produce a stable, opaque hash of a session/request ID."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class TelemetryLogger:
    """Non-blocking JSONL telemetry logger.

    Internally runs a daemon thread that drains a queue and writes
    JSON-formatted events to the configured log file.
    """

    def __init__(self, log_path: str | None = None, enabled: bool | None = None) -> None:
        self._enabled = enabled if enabled is not None else config.TELEMETRY_ENABLED
        self._log_path = Path(log_path or config.TELEMETRY_LOG_PATH)
        self._queue: Queue[dict[str, Any] | None] = Queue()
        self._query_logging_mode: str = config.TELEMETRY_QUERY_LOGGING
        self._thread: threading.Thread | None = None
        self._started = False

        if not self._enabled:
            return

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._started = True
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="telemetry-writer")
        self._thread.start()

    def _writer_loop(self) -> None:
        """Background loop: drain queue and append JSON lines to the log file."""
        while True:
            try:
                event = self._queue.get(timeout=1.0)
            except Empty:
                continue
            if event is None:  # Sentinel — shutdown
                break
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning(f"Telemetry write error: {exc}")

    def emit(self, event_type: str, **kwargs: Any) -> None:
        """Emit a telemetry event.

        Args:
            event_type: One of _TELEMETRY_EVENTS.
            **kwargs: Event-specific fields. Common fields include:
                request_id, session_id, route, strategy, latency_ms,
                confidence_bucket, source_count, cache_hit, error_type.
        """
        if not self._enabled or not self._started:
            return

        if event_type not in _TELEMETRY_EVENTS:
            logger.debug(f"Unknown telemetry event type: {event_type}")

        event: dict[str, Any] = {
            "event": event_type,
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        }

        # Copy allowed kwargs, applying privacy transforms
        for key, value in kwargs.items():
            if value is None:
                continue

            # Session ID: always hash
            if key == "session_id":
                event["session_id_hash"] = _hash_id(str(value))
                continue

            # Question: respect TELEMETRY_QUERY_LOGGING
            if key == "question":
                if self._query_logging_mode == "none":
                    continue
                elif self._query_logging_mode == "hashed":
                    event["question_hash"] = _hash_id(str(value))
                else:  # "full"
                    event["question"] = str(value)[:500]
                continue

            # All other fields pass through as-is
            event[key] = value

        self._queue.put_nowait(event)

    def shutdown(self, timeout: float = 3.0) -> None:
        """Flush remaining events and stop the writer thread."""
        if not self._enabled or not self._started:
            return
        self._queue.put_nowait(None)  # Sentinel
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def __del__(self) -> None:
        self.shutdown(timeout=1.0)


# Singleton — importable across modules
telemetry = TelemetryLogger()
