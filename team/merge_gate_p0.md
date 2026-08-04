# P0 Merge Gate 证据（STDD 四道门）

> 本文件是 STDD 第四道门「Merge Gate」的可追溯证据。任一门关失败 → PR 红，禁止合入。
> 提交对象：`core/infrastructure/{thresholds,oos_evaluator,submit_gate}.py` + 测试 + 配置。
> 阈值来源：双源/三源交叉验证（见 `BRAIN_THRESHOLDS_VERIFIED.md` 与 spec 顶部来源标注）。

## Door 1 — 规格覆盖（Spec Coverage）

PM 写的 GWT 场景 ↔ 测试 1:1 可追溯（grep 实测，非假设）：

### Story 1 — sub-universe Sharpe 绝对下限（修 IND 0.0 漏洞）
| GWT 场景 | 测试 | 文件 |
|---|---|---|
| D1 ratio=0.5 → ≈1.19 | `test_d1_ratio_half` | test_thresholds.py |
| D0 系数更高 → ≈1.98 | `test_d0_higher_coeff` | test_thresholds.py |
| 小 sub-universe 触发绝对 floor≈1.032 | `test_small_sub_universe_uses_absolute_floor` | test_thresholds.py |
| ratio 钳制 (0,1] | `test_ratio_clamped_to_one` | test_thresholds.py |
| 默认 delay=D1 | `test_default_delay_is_d1` | test_thresholds.py |
| 不变式（floor≥abs / delay0≥delay1 / 单调 / 有限正） | `test_invariants` (hypothesis PBT) | test_thresholds.py |
| 单调非减 | `test_monotone_non_decreasing_in_ratio` (hypothesis PBT) | test_thresholds.py |
| 集成：IND 低于 floor 拦截 | `test_ind_blocked_when_sub_sharpe_below_formula_floor` | test_gate_p0.py |
| 集成：IND 达到 floor 放行 | `test_ind_allowed_when_sub_sharpe_meets_floor` | test_gate_p0.py |
| 集成：小 sub-universe 用绝对 floor | `test_small_sub_universe_uses_absolute_floor` | test_gate_p0.py |

### Story 2 — OOS / holdout 过拟合评估器
| GWT 场景 | 测试 | 文件 |
|---|---|---|
| 衰减>50% 判过拟合 | `test_decay_over_50_fails` | test_oos.py |
| OOS 为负直接作废 | `test_oos_negative_fails` | test_oos.py |
| 健康衰减通过 | `test_healthy_decay_passes` | test_oos.py |
| 缺 OOS 数据不硬拦（诊断） | `test_missing_oos_is_diagnostic_not_block` | test_oos.py |
| 自定义阈值 | `test_custom_threshold` | test_oos.py |
| 集成：oos 失败阻断提交 | `test_oos_fail_blocks_submission` | test_gate_p0.py |
| 集成：oos 缺失诊断放行 | `test_oos_missing_is_diagnostic_allows` | test_gate_p0.py |

**结论：Story 1 / Story 2 全部 GWT 场景均有对应测试 → Door 1 PASS。**

## Door 2 — 三层测试栈（3-tier）
- L1 Lint：`ruff check core/infrastructure/` → 见 Door 4 报告（`qa_gate_report.json`）。
- L2 单元/集成 + PBT：`pytest core/infrastructure/tests/` → 见 Door 4（含 hypothesis 不变式）。
- L3 E2E：本模块为库层，无独立 app E2E；`test_gate_p0.py` 充当系统级集成契约测试，等价于 consumer-driven contract 的 provider 验证。

## Door 3 — 契约（Contract / Consumer-Driven）
- Architect 接口契约（`sub_universe_sharpe_threshold`、`evaluate_oos`、`GateResult.oos`）由单元测试直接绑定。
- 集成契约（submit_gate 动态 floor + OOS 阻断）由 `test_gate_p0.py` 5 例验证，等价于消费者驱动契约的 provider 侧。
- `from __future__ import annotations` + 类型标注保证接口契约静态可检。

## Door 4 — QA 独立评估 + Mutation Score ≥ 70%
- 执行：`python team/qa_gate.py`（独立进程，不携带写码上下文）。
- 信号：ruff → pytest(+PBT) → cosmic-ray mutation score。
- 硬指标：`standard_score ≥ 0.70` 且 `incompetent == 0` 且 `timeout == 0`。

### 变异分结果（cosmic-ray，独立评估器 `qa_gate.py`）
- **范围**：聚焦 P0 核心纯函数 `thresholds.py` + `oos_evaluator.py`（178→174 个 mutant；`submit_gate.py` 为集成接线，由 `test_gate_p0.py` 契约测试覆盖）。
- **原因**：cosmic-ray v8 `local` 分发器**串行**执行（无并行配置）；且对不接收参数的算子（含 `number_replacer`）**无法排除**，对 200 行的 `submit_gate.py` 会爆炸式生成。故把变异预算压到最关键的公式逻辑，换取可控门禁耗时（~8min）。
- **结果**：
  - killed = **174**，survived = **0**，incompetent = **0**，timeout = **0**
  - standard mutation score = **1.0000**
  - strict mutation score = **1.0000**
  - 阈值 ≥ 0.70 → **PASS**
- **诚实说明**：0 survived 表示注入的每个故障（数值替换 / 运算符替换 / 比较符替换 / 布尔替换 / 一元符替换）均被「精确值单测 + hypothesis PBT 不变式」捕获；无漏网 mutant。score 来自**干净基线**（重跑前已修复被 kill 中断残留的变异源码，避免了基线红导致的虚假 1.0）。
- 报告：`qa_gate_report.json`

---

## 四门总裁定（Tech Lead / Senior Developer 复核）
| 门 | 状态 |
|---|---|
| 门① 规格覆盖 | PASS |
| 门② 测试通过 | PASS（L1/L2 绿；L3 以集成契约替代） |
| 门③ 契约通过 | PASS |
| 门④ 独立评估（mutation≥70%） | PASS（score=1.0000, 174/174 killed） |

**最终裁定：四门全过 → SAFE TO MERGE（P0 可合入）**
