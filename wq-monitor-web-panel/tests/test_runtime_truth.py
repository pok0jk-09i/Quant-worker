from pathlib import Path

from quant_worker_monitor_panel.runtime_truth import (
    classify_state_source,
    load_submit_results_payload,
    submit_results_are_fresh_for_runtime,
)


def test_classify_state_source_distinguishes_authority_and_display_only():
    assert classify_state_source("project_runtime_state") == "authority"
    assert classify_state_source("batch_submit_results") == "authority"
    assert classify_state_source("adapter_state") == "derived"
    assert classify_state_source("panel_state") == "display_only"


def test_load_submit_results_payload_returns_empty_list_for_missing_file(tmp_path: Path):
    payload = load_submit_results_payload(tmp_path / "missing.json")
    assert payload == []


def test_submit_results_are_not_fresh_when_older_than_runtime_bootstrap():
    assert not submit_results_are_fresh_for_runtime(
        submit_results_updated_at="2026-06-29T04:36:05+00:00",
        runtime_updated_at="2026-06-29T05:58:00+00:00",
    )


def test_submit_results_are_fresh_when_not_older_than_runtime_bootstrap():
    assert submit_results_are_fresh_for_runtime(
        submit_results_updated_at="2026-06-29T06:36:05+00:00",
        runtime_updated_at="2026-06-29T05:58:00+00:00",
    )
