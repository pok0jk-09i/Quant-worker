from __future__ import annotations

from typing import Iterable


def collect_new_hit_ids(current_hits: Iterable[dict], seen_ids: set[str]) -> set[str]:
    new_ids: set[str] = set()
    for hit in current_hits:
        hit_id = str(hit.get("id", "")).strip()
        if not hit_id or hit_id in seen_ids:
            continue
        new_ids.add(hit_id)
    return new_ids


def build_factor_popup(hits: list[dict], *, threshold: float, max_preview: int = 3) -> tuple[str, str]:
    preview = hits[:max_preview]
    lines = [
        f"本次发现 {len(hits)} 个 Fitness >= {threshold} 的候选因子。",
        "",
    ]
    for hit in preview:
        expr = hit.get("regular", {})
        if isinstance(expr, dict):
            expr = expr.get("code", "")
        metrics = hit.get("is", {})
        if not isinstance(metrics, dict):
            metrics = {}
        lines.append(
            f"ID: {hit.get('id')} | 因子: {expr} | Fitness={metrics.get('fitness')} | Sharpe={metrics.get('sharpe')}"
        )
    if len(hits) > max_preview:
        lines.append("")
        lines.append(f"还有 {len(hits) - max_preview} 个因子未展示。")
    return "Quant worker 因子提醒", "\n".join(lines)


def build_error_popup(error_text: str) -> tuple[str, str]:
    return "Quant worker 异常提醒", f"监控程序发生异常：\n{error_text}"


def build_offline_popup() -> tuple[str, str]:
    return "Quant worker 离线运行", "未找到 BRAIN 凭据，面板将继续静默运行。请配置 WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD。"


def should_popup_for_error(current_error: str, last_error: str | None) -> bool:
    return current_error != (last_error or "")
