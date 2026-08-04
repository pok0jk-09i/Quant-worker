from quant_worker_monitor_panel.chain_auditor import audit_workflows


def test_audit_workflows_marks_production_chain_as_missing_when_only_preview_and_fixed_submit_exist():
    result = audit_workflows(
        project_state={
            "mode": "research+submit",
            "submit_enabled": True,
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 4803/10000",
        },
        submit_results=[{"submission": {"submitted": False, "reason": "metrics_threshold"}}],
        alpha_db_present=False,
    )
    assert result["production_chain"]["state"] == "missing"


def test_audit_workflows_marks_research_chain_as_partial_without_durable_writeback():
    result = audit_workflows(
        project_state={
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 10/100",
        },
        submit_results=[],
        alpha_db_present=False,
    )
    assert result["research_chain"]["state"] == "partial"


def test_audit_workflows_does_not_treat_stale_submit_results_as_current_submit_evidence():
    result = audit_workflows(
        project_state={
            "mode": "research+submit",
            "submit_enabled": True,
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 4803/10000",
            "updated_at": "2026-06-29T05:58:00+00:00",
        },
        submit_results=[{"submission": {"submitted": False, "reason": "metrics_threshold"}}],
        submit_results_fresh=False,
        alpha_db_present=False,
    )
    assert result["submit_chain"]["state"] == "partial"
    assert "历史" in result["submit_chain"]["root_cause"]
