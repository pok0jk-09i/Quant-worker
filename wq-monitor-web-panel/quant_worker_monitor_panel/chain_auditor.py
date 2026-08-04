from __future__ import annotations

from typing import Any


def _build_verdict(state: str, summary: str, impact: str, root_cause: str) -> dict[str, str]:
    return {
        "state": state,
        "summary": summary,
        "impact": impact,
        "root_cause": root_cause,
    }


def _audit_research_chain(project_state: dict[str, Any], alpha_db_present: bool) -> dict[str, str]:
    last_leaf_job = str(project_state.get("last_leaf_job", "") or "")
    last_progress = str(project_state.get("last_progress", "") or "")
    # Temporal-style durable execution: if durable writeback (alpha_db) exists,
    # research is considered complete regardless of the current cycle phase.
    if alpha_db_present:
        return _build_verdict(
            "complete",
            "研究快照链具备 durable writeback",
            "研究记忆可以进入增量闭环",
            "",
        )
    if last_leaf_job == "evolve_skill_preview":
        if last_progress.startswith("stage: "):
            return _build_verdict(
                "partial",
                "研究快照工作流运行中",
                "研究扫描在推进，但研究记忆尚未形成 durable 闭环",
                "preview 模式未写入 alpha_db",
            )
        return _build_verdict(
            "pseudo",
            "研究链有活动迹象但闭环状态不明",
            "可能存在运行但未闭环的研究行为",
            "缺少 durable writeback 证据",
        )
    return _build_verdict(
        "unknown",
        "研究链当前未被观测为活动状态",
        "无法确认研究快照链状态",
        "当前叶子任务不是 evolve_skill_preview",
    )


def _audit_submit_chain(project_state: dict[str, Any], submit_results: list[dict[str, Any]]) -> dict[str, str]:
    submit_enabled = bool(project_state.get("submit_enabled", False))
    mode = str(project_state.get("mode", "") or "")
    summary = project_state.get("submission_summary", {})
    submit_results_fresh = bool(project_state.get("_submit_results_fresh", False))
    if submit_enabled or mode == "research+submit":
        if isinstance(summary, dict) and summary:
            return _build_verdict("complete", "固定模板提交治理链可用", "submit 真相可被 runtime 汇总和展示", "")
        if submit_results:
            if not submit_results_fresh:
                return _build_verdict(
                    "partial",
                    "发现 submit 结果文件，但其早于当前 runtime 会话",
                    "当前这轮运行还没有给出新的 submit 真相，面板不应把历史结果当成本轮证据",
                    "只有历史 submit 结果，当前 runtime 尚未写出新的 submission_summary / batch_submit_results",
                )
            return _build_verdict(
                "partial",
                "固定模板提交链已运行但 runtime 治理摘要未闭合",
                "submit 结果存在，但治理汇总未完全进入 runtime 真相",
                "submission_summary 缺失",
            )
        return _build_verdict("partial", "提交链已配置但尚无提交结果证据", "暂时无法确认 submit 治理闭环", "缺少 submit 结果样本")
    return _build_verdict("disabled", "提交链未启用", "当前不会执行固定模板提交治理链", "runtime 未处于 research+submit 模式")


def _audit_production_chain(project_state: dict[str, Any], submit_results: list[dict[str, Any]]) -> dict[str, str]:
    # Check if candidate generation and submission scripts exist
    import os
    scripts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "wq-alpha-research", "scripts",
    )
    # Actually check the Quant worker-Research scripts directory
    scripts_dir = r"E:\Quant worker-CLEAN\wq-alpha-research\scripts"
    candidate_gen_exists = os.path.exists(os.path.join(scripts_dir, "candidate_generator.py"))
    candidate_sub_exists = os.path.exists(os.path.join(scripts_dir, "candidate_submitter.py"))

    if not candidate_gen_exists or not candidate_sub_exists:
        return _build_verdict(
            "missing", "新因子生产链未接入",
            "当前运行不会持续产出新的候选因子并送入 submit 消费",
            "缺少 candidate_generator.py 和/或 candidate_submitter.py",
        )

    # Check if these scripts are in the job plan
    last_leaf = str(project_state.get("last_leaf_job", "") or "")
    if last_leaf == "candidate_generate":
        return _build_verdict(
            "active", "候选生成正在进行",
            "生产链正在运行中",
            "",
        )
    if last_leaf == "candidate_submit":
        return _build_verdict(
            "active", "候选提交正在进行",
            "生产链正在运行中",
            "",
        )
    return _build_verdict(
        "ready", "生产链已接入，等待调度",
        "脚本就绪，等待下一周期运行",
        "",
    )


def _audit_truth_closure_chain(
    research_chain: dict[str, str],
    submit_chain: dict[str, str],
) -> dict[str, str]:
    if research_chain["state"] == "complete" and submit_chain["state"] == "complete":
        return _build_verdict("complete", "研究与提交真相闭环均已完成", "外围可以稳定陈述研究与提交结果", "")
    if submit_chain["state"] == "complete":
        return _build_verdict(
            "partial",
            "submit 真相闭合，但研究真相闭合不完整",
            "可稳定解释提交链，但不能把研究链误判为完整自进化闭环",
            "研究链缺少 durable writeback",
        )
    # submit_chain is not complete. This may be a configuration boundary
    # (disabled/missing) rather than a runtime failure. Report as partial
    # with the upstream reason, never as broken.
    reason = "工作流证据尚在积累"
    if submit_chain["state"] in ("disabled", "missing"):
        reason = submit_chain.get("root_cause", "功能未启用或组件缺失")
    return _build_verdict("partial", "真相闭环尚未完成", "工作流证据尚在积累，等待 submit_chain 进入 complete 后再判断", reason)


def audit_workflows(
    *,
    project_state: dict[str, Any],
    submit_results: list[dict[str, Any]],
    submit_results_fresh: bool = False,
    alpha_db_present: bool,
) -> dict[str, dict[str, str]]:
    project_state_with_truth = dict(project_state)
    project_state_with_truth["_submit_results_fresh"] = submit_results_fresh
    research_chain = _audit_research_chain(project_state_with_truth, alpha_db_present)
    submit_chain = _audit_submit_chain(project_state_with_truth, submit_results)
    production_chain = _audit_production_chain(project_state_with_truth, submit_results)
    truth_closure_chain = _audit_truth_closure_chain(research_chain, submit_chain)
    return {
        "research_chain": research_chain,
        "submit_chain": submit_chain,
        "production_chain": production_chain,
        "truth_closure_chain": truth_closure_chain,
    }
