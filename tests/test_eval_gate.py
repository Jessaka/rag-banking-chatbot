from scripts.eval_gate import evaluate_gates


def test_eval_gate_passes_clean_report():
    report = {
        "summary": {
            "pass_rate": 0.9,
            "pricing_accuracy": 0.95,
            "hallucination_rate": 0.0,
            "unsupported_answer_rate": 0.0,
            "avg_source_grounding_score": 0.8,
            "ambiguity_handling_correctness": 1.0,
            "retrieval_precision_at_3": 0.7,
        },
        "failures": {"wrong_product_routing": 0, "stale_pricing": 0, "api_error": 0},
        "leaderboards": {"by_category": [{"name": "osobni_ucty", "pass_rate": 0.9}]},
    }
    thresholds = {
        "minimums": {"pass_rate": 0.8},
        "maximums": {"hallucination_rate": 0.05},
        "category_minimum_pass_rate": {"osobni_ucty": 0.8},
        "failure_count_maximums": {"wrong_product_routing": 0},
    }
    assert evaluate_gates(report, thresholds)["passed"] is True


def test_eval_gate_fails_priority_metrics():
    report = {
        "summary": {"pass_rate": 0.7, "hallucination_rate": 0.2},
        "failures": {"wrong_product_routing": 1},
        "leaderboards": {"by_category": []},
    }
    thresholds = {
        "minimums": {"pass_rate": 0.8},
        "maximums": {"hallucination_rate": 0.05},
        "failure_count_maximums": {"wrong_product_routing": 0},
    }
    result = evaluate_gates(report, thresholds)
    assert result["passed"] is False
    assert {gate["type"] for gate in result["failed_gates"]} == {"minimum", "maximum", "failure_count"}
