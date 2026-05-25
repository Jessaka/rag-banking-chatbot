from scripts.run_eval import (
    ambiguity_correct,
    answer_formatting_pass,
    classify_failure,
    expected_contains_pass,
    expected_not_contains_pass,
    has_hallucination_failure,
    load_dataset,
    markdown_report,
    normalize_text,
    pricing_accuracy_pass,
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


def test_expected_not_contains_reports_unexpected_terms():
    ok, present = expected_not_contains_pass("Základní platební účet zdarma", ["podnikatelské eKonto", "zdarma"])
    assert ok is False
    assert present == ["zdarma"]


def test_hallucination_heuristic_only_for_pricing_with_sources():
    assert has_hallucination_failure("Nemám informace, kontaktujte podporu.", "pricing", [{"file_name": "cenik.pdf"}]) is True
    assert has_hallucination_failure("Nemám informace.", "pricing", []) is False
    assert has_hallucination_failure("Nemám informace.", "support", [{"file_name": "faq"}]) is False


def test_summarize_counts_accuracy_and_latency():
    summary = summarize([
        {"pass": True, "passed": True, "latency_ms": 1000, "metrics": {"hallucination_fail": False, "source_grounding_score": 0.8}},
        {"pass": False, "passed": False, "latency_ms": 3000, "metrics": {"hallucination_fail": True, "source_grounding_score": 0.2}},
    ])
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["average_latency_ms"] == 2000


def test_pricing_accuracy_accepts_free_text_values():
    item = {"expected_price": {"amount": "0", "currency": "Kč", "period": "měsíčně", "allow_text_values": ["zdarma"]}}
    assert pricing_accuracy_pass("Vedení účtu je zdarma měsíčně.", item) is True


def test_ambiguity_correct_requires_clarification_without_price():
    item = {"should_clarify": True}
    assert ambiguity_correct("Upřesněte prosím, jestli jde o osobní nebo podnikatelský účet.", item) is True
    assert ambiguity_correct("Stojí 500 Kč měsíčně.", item) is False


def test_answer_formatting_layer_blocks_raw_json_and_long_answers():
    assert answer_formatting_pass('{"answer":"x"}', {"format_expectations": {"forbid_raw_json": True}}) is False
    assert answer_formatting_pass("Krátká odpověď. Zdroj: test", {"format_expectations": {"requires_source_cue": True, "max_answer_chars": 50}}) is True
    assert answer_formatting_pass("Cena je 500 Kč", {"format_expectations": {"forbid_price_when_clarifying": True}}) is False


def test_classify_failure_detects_wrong_product_routing():
    item = {"expected_behavior": "direct_answer", "requires_sources": False}
    result = {"status_code": 200, "sources": [], "unexpected_present": ["Základní platební účet"], "missing_expected": []}
    metrics = {"ambiguity_correct": None, "unsupported_correct": None, "retrieval_precision_at_3": None, "pricing_accuracy_pass": None, "hallucination_fail": False, "source_grounding_score": 1.0}
    assert classify_failure(item, result, metrics) == "wrong_product_routing"


def test_markdown_report_contains_leaderboards():
    report = {
        "run_meta": {"dataset_path": "evals/datasets/banking_eval_v1.json", "api_url": "http://localhost:8000/chat", "created_at": "2026-05-24T00:00:00Z"},
        "summary": {"pass_rate": 1.0, "passed": 1, "total": 1, "pricing_accuracy": None, "hallucination_rate": 0.0, "unsupported_answer_rate": None, "avg_source_grounding_score": 1.0, "ambiguity_handling_correctness": None, "retrieval_precision_at_3": None},
        "leaderboards": {"by_category": [{"name": "faq", "total": 1, "passed": 1, "pass_rate": 1.0}], "by_failure_type": []},
        "results": [],
    }
    md = markdown_report(report)
    assert "Category leaderboard" in md
    assert "faq" in md


def test_eval_dataset_has_required_shape():
    items = load_dataset(__import__("pathlib").Path("evals/datasets/banking_eval_v1.json"))
    assert 100 <= len(items) <= 300
    categories = {item["category"] for item in items}
    assert {"osobni_ucty", "podnikatele", "firmy", "kreditni_karty", "hypoteky", "faq", "bezpecnost", "investice", "reklamace", "limity", "rb_klic", "sepa_swift", "apple_google_pay"}.issubset(categories)
    for item in items:
        assert item["question"]
        assert isinstance(item["expected_contains"], list)
        assert item["category"]
        assert item["expected_behavior"] in {"direct_answer", "clarify", "unsupported", "safety_guidance"}
