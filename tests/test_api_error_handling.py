from pathlib import Path

import config
from src.api.main import _internal_error_response, _serialize_sources, _write_error_log


def test_serialize_sources_supports_dict_sources():
    sources = _serialize_sources([
        {
            "title": "Ceník Raiffeisenbank",
            "page": 4,
            "url": "https://example.test/cenik.pdf",
        }
    ])
    assert sources[0].file_name == "Ceník Raiffeisenbank"
    assert sources[0].page == 4
    assert sources[0].preview == ""


def test_internal_error_response_hides_traceback_when_debug_disabled(monkeypatch):
    monkeypatch.setattr(config, "DEBUG_API_ERRORS", False)
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        response = _internal_error_response(
            request_id="req-1",
            session_id="session-1",
            question="test question",
            exc=exc,
            elapsed_ms=12.3,
            partial_result={"sources": [{"title": "source"}], "retrieval_debug": [{"x": 1}]},
        )
    assert response.status_code == 500
    assert response.body
    assert b"internal_error" in response.body
    assert b"Traceback" not in response.body


def test_error_log_writes_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "errors.log"
    monkeypatch.setattr(config, "ERROR_LOG_PATH", path)
    _write_error_log({"request_id": "req-2", "query": "q"})
    assert path.exists()
    assert "req-2" in path.read_text(encoding="utf-8")
