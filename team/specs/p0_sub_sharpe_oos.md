# P0 规格：sub_sharpe 绝对下限公式 + OOS 过拟合评估器

> STDD 纪律文档：SDD 层（PM GWT + Architect 契约）先于实现。阈值 oracle = `team/BRAIN_THRESHOLDS_VERIFIED.md` + 本次 OOS 联网交叉验证。
> 来源：sub_sharpe 公式 Oo_Amy_oO / zread（双源）；OOS decay 阈值 backtrex / mathandmarkets / CFM 论文（三源一致：decay>50% 为临界警告）。

---

## Story 1 — sub-universe Sharpe 绝对下限公式（修 IND 0.0 漏洞）

**作为** 提交闸门
**我希望** 用 BRAIN 验证后的绝对 floor 公式替换 IND 区域的 `sub_universe_sharpe_min = 0.0`
**以便** IND 因子在 sub-universe Sharpe 不足时被本地拦截，不再烧配额撞 403

### GWT 验收场景
```gherkin
Feature: sub-universe Sharpe 闸门（IND 区域）

  Scenario: D1 alpha 在 ratio=0.5 时的下限
    Given region=IND, delay=D1, sub_size=500, largest_universe_size=1000
    When  计算 sub-universe Sharpe 绝对下限
    Then  结果应 ≈ 1.19（SQRT252 × max(0.065, 0.5×0.15) = 15.87×0.075）
    And   结果不低于 0.065 的绝对 floor

  Scenario: D0 系数更高
    Given region=IND, delay=D0, sub_size=500, largest_universe_size=1000
    When  计算下限
    Then  结果应 ≈ 1.98（SQRT252 × max(0.065, 0.5×0.25) = 15.87×0.125）

  Scenario: 小 sub-universe 触发绝对 floor
    Given region=IND, delay=D1, sub_size=10, largest_universe_size=1000  # ratio=0.01
    When  计算下限
    Then  系数项 0.01×0.15=0.0015 < 0.065
    And   取 max → 结果 = 15.87×0.065 ≈ 1.032（绝对 floor 生效）

  Scenario: ratio 被钳制到 (0,1]
    Given sub_size=2000, largest_universe_size=1000  # ratio>1
    When  计算下限
    Then  ratio 取 min(1, 2.0)=1.0，结果 = 15.87×0.15 ≈ 2.38（不超上限）
```

### Architect 接口契约（纯函数，便于 PBT）
```python
# core/infrastructure/thresholds.py
import math
SQRT252 = math.sqrt(252)  # ≈15.8745

def sub_universe_sharpe_threshold(
    *,
    sub_size: int,
    largest_universe_size: int,
    delay: int = 1,
) -> float:
    """返回 sub-universe Sharpe 的绝对下限 floor。

    floor = SQRT252 * max(0.065, ratio * coeff)
    coeff = 0.15 if delay == 1 else 0.25
    ratio = clamp(sub_size / largest_universe_size, 0 < ratio <= 1)

    不变式（PBT 验证）：
      - floor >= SQRT252 * 0.065  （绝对 floor）
      - delay=0 的 floor >= delay=1 的 floor（同 ratio 下）
      - floor 关于 ratio 单调非减
      - floor 有限且为正
    """
```

### 集成契约（submit_gate 改造）
- `gate_submission` 新增可选参数 `sub_size`, `largest_universe_size`（IND/TOP500 区域必填；缺省时沿用原逻辑但不设 0.0 软通过——改为"缺参即警告并软拦"）。
- IND/TOP500 的 `sub_universe_sharpe_min` 改为**动态计算**：`floor = sub_universe_sharpe_threshold(sub_size=..., largest_universe_size=..., delay=...)`；比较 `is_metrics['sub_universe_sharpe'] >= floor`。
- 删除 `REGION_METRIC_FLOORS` 中 IND 的 `sub_universe_sharpe_min: 0.0`（漏洞根因）。

---

## Story 2 — OOS / holdout 过拟合评估器

**作为** 诊断与提交前闸门
**我希望** 显式计算每个因子的 IS→OOS Sharpe 衰减并拦截过拟合
**以便** 避免把样本内幻觉当成可用因子提交

### GWT 验收场景
```gherkin
Feature: OOS 过拟合评估

  Scenario: 衰减超 50% 判过拟合
    Given is_sharpe=2.0, oos_sharpe=0.8  # decay = (2.0-0.8)/2.0 = 0.6
    When  评估 OOS
    Then  passed=False, reason 含 "OOS decay 0.60 > 0.50"

  Scenario: OOS 为负直接作废
    Given is_sharpe=1.5, oos_sharpe=-0.2
    When  评估 OOS
    Then  passed=False, reason 含 "OOS Sharpe < 0"

  Scenario: 健康衰减通过
    Given is_sharpe=2.0, oos_sharpe=1.3  # decay = 0.35
    When  评估 OOS
    Then  passed=True

  Scenario: 缺 OOS 数据不硬拦（诊断）
    Given is_sharpe=1.6, oos_sharpe=None
    When  评估 OOS
    Then  passed=True, reason 含 "no OOS data: diagnostic only"
```

### Architect 接口契约
```python
# core/infrastructure/oos_evaluator.py
from dataclasses import dataclass

@dataclass
class OosResult:
    passed: bool
    decay_ratio: float | None      # (is - oos) / is，None 表示无 OOS
    is_sharpe: float | None
    oos_sharpe: float | None
    reasons: list[str]

def evaluate_oos(
    *,
    is_sharpe: float | None,
    oos_sharpe: float | None,
    max_decay_ratio: float = 0.50,   # 阈值来源：backtrex/mathandmarkets/CFM 三源一致
) -> OosResult:
    """评估 IS→OOS 衰减。

    规则（阈值已双源+验证）：
      - oos_sharpe is None        -> passed=True, 诊断，不硬拦（缺数据）
      - oos_sharpe < 0            -> passed=False（作废）
      - decay_ratio = (is-oos)/is
          decay_ratio > 0.50      -> passed=False（过拟合高危）
          否则                     -> passed=True
    max_decay_ratio 可配置；默认 0.50 来自交叉验证，非凭记忆。
    """
```

### 集成契约
- `gate_submission` 新增可选 `is_sharpe`, `oos_sharpe`；若提供且 `evaluate_oos(...).passed == False`，追加 `oos_fail` 原因并 `submit_allowed=False`。
- 诊断输出：`GateResult` 增加 `oos` 字段（OosResult），供日志/面板展示每个因子的 `decay_ratio`（呼应 BRAIN_THRESHOLDS_VERIFIED §5 诊断要求）。

---

## 反假功能自检（STDD §6）
- [x] 阈值全部双源验证（sub_sharpe Oo_Amy_oO/zread；OOS decay backtrex/mathandmarkets/CFM）。
- [x] 无 skeleton/mock/TODO；先写失败测试再实现。
- [x] 不变式用 hypothesis PBT 穿透；mutation score ≥70%。
- [x] QA 独立评估，非写代码者自证。
- [x] 四门 Merge Gate 全过才合入。
