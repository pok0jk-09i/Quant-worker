from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

PROJECT_HEALTH_LABELS = {
    "HEALTHY": "正常",
    "DEGRADED": "降级运行",
    "ERROR": "异常",
}


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


def describe_project_health(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "未知"
    return PROJECT_HEALTH_LABELS.get(text, text)


def extract_metrics(alpha: dict[str, Any]) -> dict[str, Any]:
    metrics = alpha.get("is") or {}
    if not isinstance(metrics, dict):
        metrics = {}
    submit_passed = bool(alpha.get("dateSubmitted"))
    return {
        "fitness": metrics.get("fitness"),
        "sharpe": metrics.get("sharpe"),
        "turnover": metrics.get("turnover"),
        "returns": metrics.get("returns"),
        "status": alpha.get("status"),
        "self_correlation": metrics.get("selfCorrelation"),
        "submit_passed": submit_passed,
    }


def extract_expression(alpha: dict[str, Any]) -> str:
    expr = alpha.get("regular", alpha.get("expression", {}))
    if isinstance(expr, dict):
        return str(expr.get("code", "")).strip()
    return str(expr).strip()


def describe_alpha_timestamp(alpha: dict[str, Any]) -> tuple[str, str]:
    candidates = (
        ("创建时间", alpha.get("dateCreated")),
        ("提交时间", alpha.get("dateSubmitted")),
        ("更新时间", alpha.get("dateModified")),
    )
    for label, value in candidates:
        text = str(value or "").strip()
        if text:
            return label, text
    return "时间", "未知"


def format_alpha_card(alpha: dict[str, Any]) -> str:
    metrics = extract_metrics(alpha)
    settings = alpha.get("settings", {}) if isinstance(alpha.get("settings"), dict) else {}
    expr = extract_expression(alpha)
    timestamp_label, timestamp_value = describe_alpha_timestamp(alpha)
    submit_state = "已确认提交" if metrics["submit_passed"] else "未确认提交"
    return (
        f"{timestamp_label}: {timestamp_value}\n"
        f"因子: {expr}\n"
        f"ID: {alpha.get('id')}\n"
        f"状态: {metrics['status']}\n"
        f"质量: Fitness={metrics['fitness']} | Sharpe={metrics['sharpe']} | Turnover={metrics['turnover']}\n"
        f"提交状态: {submit_state}\n"
        f"设置: region={settings.get('region')} universe={settings.get('universe')} delay={settings.get('delay')} "
        f"decay={settings.get('decay')} neutralization={settings.get('neutralization')} truncation={settings.get('truncation')}\n"
    )


def build_summary_lines(alphas: list[dict[str, Any]], *, threshold: float) -> list[str]:
    submit_passed = 0
    submit_failed = 0
    high_quality = 0
    low_quality = 0

    for alpha in alphas:
        metrics = extract_metrics(alpha)
        fitness = metrics["fitness"]
        if fitness is not None and float(fitness) >= threshold:
            high_quality += 1
        else:
            low_quality += 1
        if metrics["submit_passed"]:
            submit_passed += 1
        else:
            submit_failed += 1

    return [
        f"命中因子: {len(alphas)}",
        f"官方已提交: {submit_passed}",
        f"未见官方提交: {submit_failed}",
        f"Fitness>={threshold}: {high_quality}",
        f"Fitness<{threshold}: {low_quality}",
    ]


def build_offline_summary_lines() -> list[str]:
    return [
        "未找到 BRAIN 凭据",
        "面板会继续保持运行",
        "请配置 WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD",
    ]


def describe_project_runtime_status(state: dict[str, Any]) -> str:
    status = str(state.get("status", "UNKNOWN") or "UNKNOWN")
    progress = str(state.get("last_progress", "") or "").strip()
    if status != "BOOTING":
        return status
    if progress.startswith("stage: "):
        return "运行中"
    return "启动中"


def describe_project_progress(progress: str) -> str:
    text = str(progress or "").strip()
    if not text:
        return "暂无"
    if not text.startswith("stage: "):
        return text

    payload = text[len("stage: ") :]
    stage_name, _, detail = payload.partition("|")
    stage_key = stage_name.strip()
    detail_text = detail.strip()
    labels = {
        "fetch_alphas": "正在抓取 Alpha 列表",
        "bulk_snapshot": "正在建立首轮全量快照",
        "fetch_pnl": "正在抓取 PnL",
        "build_correlation": "正在计算相关性",
        "incremental_scan": "正在执行增量扫描",
    }
    label = labels.get(stage_key, stage_key)

    if "/" in detail_text:
        left, _, right = detail_text.partition("/")
        try:
            current = int(left.strip())
            total = int(right.strip())
        except ValueError:
            return f"{label}: {detail_text}"
        if total > 0:
            return f"{label}: {current}/{total} ({current / total * 100:.2f}%)"
    if detail_text:
        return f"{label}: {detail_text}"
    return label


def build_project_summary_lines(project_state: dict[str, Any] | None) -> list[str]:
    state = project_state if isinstance(project_state, dict) else {}
    lines = [
        f"项目状态: {describe_project_runtime_status(state)}",
        f"项目健康: {describe_project_health(state.get('project_health', ''))}",
        f"运行模式: {state.get('mode', 'unknown')}",
        f"循环次数: {state.get('cycle_count', 0)}",
        f"最近任务: {state.get('last_leaf_job', '') or '暂无'}",
        f"当前进度: {describe_project_progress(str(state.get('last_progress', '') or ''))}",
        f"最近错误: {state.get('last_error', '') or '无'}",
    ]
    submission_summary = state.get("submission_summary", {})
    if isinstance(submission_summary, dict) and submission_summary:
        lines.append(
            "Submit摘要: "
            f"ACTIVE {submission_summary.get('submitted_active', 0)} | "
            f"PENDING {submission_summary.get('submitted_pending', 0)} | "
            f"SKIPPED {submission_summary.get('skipped', 0)} | "
            f"ERROR {submission_summary.get('request_errors', 0)} | "
            f"TOTAL {submission_summary.get('total', 0)}"
        )
    submit_status = str(state.get("submit_status", "") or "").strip()
    submit_failure_kind = str(state.get("submit_failure_kind", "") or "").strip()
    if submit_status:
        lines.append(
            "Submit治理: "
            f"status={submit_status} | failure_kind={submit_failure_kind or 'none'}"
        )
    return lines


def build_adapter_summary_lines(adapter_state: dict[str, Any] | None) -> list[str]:
    state = adapter_state if isinstance(adapter_state, dict) else {}
    lines = [
        f"适配状态: {state.get('adapter_status', 'UNKNOWN')}",
        f"失败类型: {state.get('failure_kind', 'none')}",
        f"最近错误: {state.get('last_error', '') or '无'}",
        f"最近任务: {state.get('last_leaf_job', '') or '暂无'}",
    ]

    authority_map = state.get("authority_map", {})
    if isinstance(authority_map, dict) and authority_map:
        lines.append("权威映射: " + ", ".join(f"{key}={value}" for key, value in authority_map.items()))

    workflow_verdicts = state.get("workflow_verdicts", {})
    if isinstance(workflow_verdicts, dict) and workflow_verdicts:
        for chain_name in ("research_chain", "submit_chain", "production_chain", "truth_closure_chain"):
            verdict = workflow_verdicts.get(chain_name, {})
            if isinstance(verdict, dict) and verdict:
                lines.append(
                    f"{chain_name}: {verdict.get('state', 'unknown')} | "
                    f"{verdict.get('summary', '')} | "
                    f"root_cause={verdict.get('root_cause', '') or 'none'}"
                )
    else:
        missing = state.get("missing_capabilities", [])
        missing_text = ", ".join(str(item) for item in missing) if isinstance(missing, list) and missing else "无"
        lines.append(f"覆盖状态: {state.get('coverage_status', 'unknown')}")
        lines.append(f"缺失链路: {missing_text}")

    next_attention = str(state.get("next_attention", "") or "").strip()
    if next_attention:
        lines.append(f"下一注意点: {next_attention}")

    return lines


def select_qualifying_alphas(
    alphas: list[dict[str, Any]],
    *,
    threshold: float,
    sharpe_threshold: float | None = None,
    status_filter: str = "ANY",
    max_items: int = 100,
    slim: bool = True,
) -> list[dict[str, Any]]:
    """Select alphas meeting the fitness (and optionally sharpe) threshold.

    When `slim=True` (the default), each selected alpha is reduced to the
    fields actually consumed by the panel UI. This keeps panel_state.json
    small even when 100 alphas qualify — ~5KB total instead of ~200KB.
    Fields dropped: full `is.checks` array, full `settings`, `classifications`,
    `competitions`, and other metadata that the UI never displays.
    """
    selected: list[dict[str, Any]] = []
    for alpha in alphas:
        metrics = extract_metrics(alpha)
        fitness = metrics["fitness"]
        sharpe = metrics["sharpe"]
        if fitness is None or float(fitness) < threshold:
            continue
        if sharpe_threshold is not None and (sharpe is None or float(sharpe) < sharpe_threshold):
            continue
        if status_filter != "ANY" and str(metrics["status"]) != status_filter:
            continue
        selected.append(_slim_alpha(alpha) if slim else alpha)
        if len(selected) >= max_items:
            break
    selected.sort(
        key=lambda a: (
            float(extract_metrics(a)["fitness"] or 0.0),
            float(extract_metrics(a)["sharpe"] or 0.0),
        ),
        reverse=True,
    )
    return selected


_SLIM_ALPHA_TOP_KEYS = {"id", "type", "author", "name", "status", "stage", "grade", "tags"}
_SLIM_ALPHA_SETTINGS_KEYS = {
    "instrumentType", "region", "universe", "delay", "decay",
    "neutralization", "truncation", "startDate", "endDate",
}
_SLIM_ALPHA_IS_KEYS = {"sharpe", "fitness", "returns", "turnover", "drawdown", "margin"}


def _slim_alpha(alpha: dict[str, Any]) -> dict[str, Any]:
    """Reduce an alpha dict to the keys actually used by the panel UI."""
    out: dict[str, Any] = {k: alpha[k] for k in _SLIM_ALPHA_TOP_KEYS if k in alpha}
    settings = alpha.get("settings", {})
    if isinstance(settings, dict):
        out["settings"] = {k: settings[k] for k in _SLIM_ALPHA_SETTINGS_KEYS if k in settings}
    is_ = alpha.get("is", {})
    if isinstance(is_, dict):
        out["is"] = {k: is_[k] for k in _SLIM_ALPHA_IS_KEYS if k in is_}
    # Expression — keep this since it identifies the alpha
    regular = alpha.get("regular", {})
    if isinstance(regular, dict) and "code" in regular:
        expr = regular["code"]
        out["regular"] = {"code": expr[:200] if isinstance(expr, str) else expr}
    return out
