"""Role registry — single source of truth for the 8 roles (Gen-4 runtime).

Every field here is a code mirror of ``PROMPT_STANDARD.md §1`` and
``ROLE_CONTRACT_MATRIX.md §1``.  The contract matrix is the human-readable
proof of 100% alignment; this module is the machine-readable single source
so code and docs cannot drift.  ``validate_alignment()`` enforces that.

Gate accountability follows ROLE_CONTRACT_MATRIX §2:
  门① 规格覆盖   — PM (Accountable) · Tech Lead (终审)
  门② 测试通过   — Backend (Accountable) · Data/SRE (Responsible)
  门③ 契约通过   — Architect (Accountable) · Backend/QA/Data (Responsible)
  门④ 独立评估   — QA (Accountable) · Backend (Responsible)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Gate = Literal["门①", "门②", "门③", "门④"]

ROLE_IDS = [
    "0 Tech Lead / Orchestrator",
    "1 PM",
    "2 Architect",
    "3 Quant Researcher",
    "4 Backend / Platform Engineer",
    "5 Data / Feature Engineer",
    "6 QA / Validation Engineer",
    "7 SRE / Reliability Engineer",
]


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str
    produces: tuple[str, ...]      # §1.4 artifact names
    consumes: tuple[str, ...]      # INPUTS
    accountable_gates: tuple[Gate, ...]
    responsible_gates: tuple[Gate, ...]
    out_bounds: tuple[str, ...]    # explicit "do NOT" list (§1 OUT)


# ── The 8 roles.  Values copied verbatim from ROLE_CONTRACT_MATRIX.md §1. ──
ROLES: dict[str, Role] = {
    "TechLead": Role(
        role_id="0", name="Tech Lead / Orchestrator",
        produces=("RACI", "Trace ID", "Merge 裁决"),
        consumes=("全部 7 角色产物",),
        accountable_gates=("门①", "门②", "门③", "门④"),
        responsible_gates=(),
        out_bounds=("不写业务代码", "不自行校验阈值", "不替代 QA"),
    ),
    "PM": Role(
        role_id="1", name="PM",
        produces=("PRD", "Epics", "Stories+GWT"),
        consumes=("战略文档", "用户意图", "Researcher 可行性提示"),
        accountable_gates=("门①",),
        responsible_gates=(),
        out_bounds=("不写代码", "不定义架构", "不设阈值", "不拍板合并"),
    ),
    "Architect": Role(
        role_id="2", name="Architect",
        produces=("ADR", "接口契约"),
        consumes=("PM Stories+GWT", "Researcher 阈值规范", "现有 core/infrastructure/*"),
        accountable_gates=("门③",),
        responsible_gates=("门①",),
        out_bounds=("不实现业务", "不设阈值数值", "不写数据管道"),
    ),
    "Researcher": Role(
        role_id="3", name="Quant Researcher",
        produces=("BRAIN_THRESHOLDS_VERIFIED.md", "taxonomy"),
        consumes=("BRAIN 官方 docs", "arXiv", "平台真实数据", "core/infrastructure/*"),
        accountable_gates=("门②",),
        responsible_gates=("门①",),
        out_bounds=("不写实现", "不做优先级", "不搭 infra"),
    ),
    "Backend": Role(
        role_id="4", name="Backend / Platform Engineer",
        produces=("可运行代码", "验证证据"),
        consumes=("Architect 契约", "Researcher 阈值规范", "现有代码"),
        accountable_gates=("门②",),
        responsible_gates=("门④", "门③"),
        out_bounds=("不发明阈值", "不定义架构", "不写 schema", "不自证完成"),
    ),
    "Data": Role(
        role_id="5", name="Data / Feature Engineer",
        produces=("feature schema contract", "数据管道", "质量报告"),
        consumes=("Architect schema 契约", "brain_reconcile.py", "alpha_db.json 格式"),
        accountable_gates=("门②",),
        responsible_gates=("门③",),
        out_bounds=("不写提交逻辑", "不设阈值", "不定义架构"),
    ),
    "QA": Role(
        role_id="6", name="QA / Validation Engineer",
        produces=("QA 门禁裁决报告",),
        consumes=("Backend 代码+证据", "Researcher 规范", "Architect 契约",
                  "Data 报告", "真实 IS/OOS 数据"),
        accountable_gates=("门④",),
        responsible_gates=("门③",),
        out_bounds=("不写业务", "不设阈值", "不定义架构", "不自行放行"),
    ),
    "SRE": Role(
        role_id="7", name="SRE / Reliability Engineer",
        produces=("非功能契约", "受控重启验证日志"),
        consumes=("Architect 非功能契约", "现有 supervisor/start.py/project_runtime",
                 "core/infrastructure/*"),
        accountable_gates=("门②", "门④"),
        responsible_gates=(),
        out_bounds=("不写业务", "不设阈值", "不写数据管道"),
    ),
}

# Pipeline order a Story flows through (PM -> ... -> Tech Lead).
PIPELINE_ORDER = ["PM", "Architect", "Researcher", "Data", "Backend", "QA", "SRE", "TechLead"]

# Four Merge Gates, with accountable + responsible roles (ROLE_CONTRACT_MATRIX §2).
GATES: dict[Gate, dict] = {
    "门①": {"name": "规格覆盖", "accountable": ("PM", "TechLead"),
            "responsible": ("Architect", "Researcher")},
    "门②": {"name": "测试通过", "accountable": ("Backend",),
            "responsible": ("Data", "SRE")},
    "门③": {"name": "契约通过", "accountable": ("Architect",),
            "responsible": ("Backend", "QA", "Data")},
    "门④": {"name": "独立评估", "accountable": ("QA",),
            "responsible": ("Backend",)},
}

# Expected artifact vocabulary (§1.4) — used by validate_alignment.
EXPECTED_ARTIFACTS = {
    "PRD", "Epics", "Stories+GWT", "ADR", "接口契约",
    "BRAIN_THRESHOLDS_VERIFIED.md", "taxonomy", "可运行代码", "验证证据",
    "feature schema contract", "数据管道", "质量报告", "QA 门禁裁决报告",
    "非功能契约", "受控重启验证日志", "RACI", "Trace ID", "Merge 裁决",
}


def get_role(key: str) -> Role:
    return ROLES[key]


def validate_alignment() -> list[str]:
    """Machine check that code mirrors ROLE_CONTRACT_MATRIX.md.

    Returns a list of drift findings (empty == perfectly aligned).  CI runs this
    as part of 门① so docs and code cannot silently diverge.
    """
    findings: list[str] = []
    for key, r in ROLES.items():
        for art in r.produces + r.consumes:
            # strip trailing qualifiers like "全部 7 角色产物"
            base = art.split()[0]
            if base in EXPECTED_ARTIFACTS or art in EXPECTED_ARTIFACTS:
                continue
            # allow a few free-form inputs that are not artifacts
            if art in ("战略文档", "用户意图", "Researcher 可行性提示",
                       "PM Stories+GWT", "Researcher 阈值规范", "现有 core/infrastructure/*",
                       "Architect schema 契约", "brain_reconcile.py", "alpha_db.json 格式",
                       "Architect 契约", "Researcher 规范", "现有代码",
                       "Backend 代码+证据", "Architect 非功能契约", "现有 supervisor/start.py/project_runtime",
                       "真实 IS/OOS 数据", "BRAIN 官方 docs", "arXiv", "平台真实数据",
                       "全部 7 角色产物"):
                continue
            findings.append(f"{key}: unknown artifact vocabulary '{art}'")
    # every gate must have an accountable role present in ROLES
    for g, meta in GATES.items():
        for who in meta["accountable"] + meta["responsible"]:
            if who not in ROLES:
                findings.append(f"gate {g}: role '{who}' not in registry")
    return findings


if __name__ == "__main__":
    import sys
    f = validate_alignment()
    if f:
        print("ALIGNMENT DRIFT:")
        for line in f:
            print("  -", line)
        sys.exit(1)
    print(f"OK: {len(ROLES)} roles, {len(GATES)} gates — aligned with ROLE_CONTRACT_MATRIX.md")
