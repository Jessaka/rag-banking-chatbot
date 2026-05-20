from scripts.run_eval import (
    expected_contains_pass,
    has_hallucination_failure,
    load_dataset,
    normalize_text,
    summarize,
)


def test_normalize_text_handles_case_and_diacritics():
    assert normalize_text("Běžný ÚČET") == "bezny ucet"


def test_expected_contains_match_is_case_and_diacritic_insensitive():
    ok, missing = expected_contains_pass("Vedení běžného účtu stojí 250 Kč.", ["bezneho uctu", "Kč"])
    assert ok is True
    assert missing == []


def test_expected_contains_reports_missing_terms():
    ok, missing = expected_contains_pass("Odpověď o kartě", ["hypotéka"])
    assert ok is False
    assert missing == ["hypotéka"]


def test_hallucination_heuristic_only_for_pricing_with_sources():
    assert has_hallucination_failure("Nemám informace, kontaktujte podporu.", "pricing", [{"file_name": "cenik.pdf"}]) is True
    assert has_hallucination_failure("Nemám informace.", "pricing", []) is False
    assert has_hallucination_failure("Nemám informace.", "support", [{"file_name": "faq"}]) is False


def test_summarize_counts_accuracy_and_latency():
    summary = summarize([
        {"pass": True, "latency_ms": 1000},
        {"pass": False, "latency_ms": 3000},
    ])
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["average_latency_ms"] == 2000


def test_eval_dataset_has_required_shape():
    items = load_dataset(__import__("pathlib").Path("evals/pricing_eval.json"))
    assert len(items) >= 10
    for item in items:
        assert item["question"]
        assert isinstance(item["expected_contains"], list)
        assert item["category"]
