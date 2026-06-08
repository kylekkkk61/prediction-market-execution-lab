from models.ml_filter import (
    FilterThresholds,
    SignalExample,
    chronological_split,
    evaluate_filter,
    fit_baseline_thresholds,
    load_public_model_decision_diagnostics,
    load_signal_examples,
    passes_filter,
    render_ml_filter_report,
    run_walk_forward_demo,
)


def make_example(recorded_at: str, edge: float, spread: float, fill_probability: float, label: int):
    return SignalExample(
        recorded_at=recorded_at,
        side="UP",
        time_bucket="30-60",
        features={
            "signal_edge": edge,
            "signal_spread": spread,
            "signal_fair": 0.55,
            "limit_price": 0.45,
            "fill_probability": fill_probability,
            "elapsed_seconds": 30.0,
        },
        label=label,
    )


def test_chronological_split_preserves_order():
    examples = [make_example(f"2026-06-01T00:0{i}:00Z", 0.1, 0.01, 0.4, 1) for i in range(5)]

    train, test = chronological_split(examples, train_fraction=0.6)

    assert len(train) == 3
    assert len(test) == 2
    assert train[-1].recorded_at < test[0].recorded_at


def test_baseline_filter_passes_high_edge_low_spread_signal():
    thresholds = FilterThresholds(min_edge=0.1, max_spread=0.03, min_fill_probability=0.2)
    good = make_example("2026-06-01T00:00:00Z", 0.2, 0.01, 0.5, 1)
    weak = make_example("2026-06-01T00:01:00Z", 0.01, 0.08, 0.0, 0)

    assert passes_filter(good, thresholds)
    assert not passes_filter(weak, thresholds)


def test_evaluate_filter_returns_nullable_positive_rates():
    examples = [
        make_example("2026-06-01T00:00:00Z", 0.2, 0.01, 0.5, 1),
        make_example("2026-06-01T00:01:00Z", 0.01, 0.08, 0.0, 0),
    ]
    thresholds = FilterThresholds(min_edge=0.1, max_spread=0.03, min_fill_probability=0.2)

    diagnostics = evaluate_filter(examples, thresholds)

    assert diagnostics.row_count == 2
    assert diagnostics.passed_count == 1
    assert diagnostics.positive_rate_all == 0.5
    assert diagnostics.positive_rate_passed == 1.0


def test_load_signal_examples_from_public_sample_csv():
    examples = load_signal_examples("data/sample/executions_sample.csv")

    assert examples
    assert all("signal_edge" in item.features for item in examples)
    assert all("signal_spread" in item.features for item in examples)


def test_walk_forward_demo_and_report_render_on_public_sample():
    examples = load_signal_examples("data/sample/executions_sample.csv")

    train, test = run_walk_forward_demo(examples)
    report = render_ml_filter_report(train, test)

    assert train.row_count > 0
    assert test.row_count > 0
    assert "ML Filter Workflow Report" in report
    assert "does not establish production predictive performance" in report
    assert "chronological train/test split" in report
    assert "Exported private-ledger ML diagnostics" in report
    assert "does not export model paths" in report


def test_public_model_decision_diagnostics_loads_safe_exported_fields():
    diagnostics = load_public_model_decision_diagnostics("data/sample/executions_sample.csv")

    assert diagnostics.row_count > 0
    assert diagnostics.ml_enabled_count >= 0
    assert diagnostics.ml_scored_count >= 0
    assert diagnostics.fill_probability_count >= 0


def test_fit_baseline_thresholds_handles_empty_examples():
    thresholds = fit_baseline_thresholds([])

    assert thresholds.min_edge == 0.0
    assert thresholds.max_spread == 1.0
    assert thresholds.min_fill_probability == 0.0
