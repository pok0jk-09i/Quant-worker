# Story SEEDPOOL — Real parent-pool builder (P1-A A1–A27)

> SDD layer (PM GWT + Architect 接口契约) 先于实现。阈值 oracle = `team/BRAIN_THRESHOLDS_VERIFIED.md` + 父池真实化科研报告（A1–A27）。
> 门① 校验：本规格存在 + `build_real_parent_pool` 接口契约 + `tests/test_seed_pool.py` 引用本 story。

---

## 背景与根因

`scripts/candidate_generator.py::select_high_performing_alphas` 只认 `status==ACTIVE` 的因子，而本地 `alpha_db.json` 的 10 个 ACTIVE 是**幽灵数据**（BRAIN 平台 1100 条中不存在）。真正跑过 BRAIN 的 **13,191 条 UNSUBMITTED** 原料从未进入父池 → 结构性天花板。本 Story 用 `build_real_parent_pool` 替换该选择逻辑。

---

## Story — 真实父池构建

**作为** 父池构建器
**我希望** 从「经济模板 + 真实 BRAIN 评估原料 + Kakushadze 101 子集」三层构建父池
**以便** 生成器拿到真实、多样、合规的父池，而不是对幽灵因子做 mutation

### GWT 验收场景

```gherkin
Feature: Real parent-pool (SEEDPOOL)

  Scenario: Tier1 只用真实 BRAIN 原料，拒绝幽灵 ACTIVE
    Given alpha_db.json 含 10 个幽灵 ACTIVE + 13191 条 UNSUBMITTED
    When  调用 build_real_parent_pool(db)
    Then  返回的 pool 中不得含任何幽灵 ACTIVE（BRAIN 平台不存在者）
    And   Tier1 仅含 UNSUBMITTED 且 fitness >= 1.0 的真实原料

  Scenario: OOS 纪律（A19）— 只信 BRAIN 真评估，不信本地 sim
    Given 某候选仅有本地仿真指标、无 BRAIN OOS/IS 真评估
    When  评估其是否可作种子
    Then  不被纳入 Tier1（OOS-by-construction）

  Scenario: 风格均衡（A22）— 5 家族配额，反转不占多数
    Given 经济模板含 momentum/reversal/value_quality/liquidity/volatility_news 五族
    When  构建池并施加每族配额
    Then  任一风格家族占比 <= 配额上限（默认 0.30）

  Scenario: News/Sentiment 解禁（A21）— 仅排除稀疏子字段
    Given 分析师/新闻字段 anl4_*/pv13_*/_guidance 中仅部分稀疏
    When  构建 Tier0/Tier1
    Then  非稀疏的分析师/新闻字段被放行，仅稀疏子字段被 R3-C 精细拦截

  Scenario: 真实 Self-Correlation 闸门（A20）
    Given 候选与已提交池某因子结构相关 > 0.7
    When  评估 self-corr
    Then  判不通过（除非 Sharpe 豁免，平台真实实例 Self-Corr 0.693 靠 10% 豁免过检）

  Scenario: 显著性闸门（A7 DSR）
    Given 某因子 sharpe=1.55 但样本不足/偏度异常
    When  计算 Deflated Sharpe Ratio
    Then  DSR < 0.95 时不视为真 alpha（仅降级，不谎报）

  Scenario: 谱分散（A10/A16）— 结构性相关代理 + 每簇上限
    Given 池中存在多个结构高度相似的候选
    When  施加谱分散过滤
    Then  每相关簇保留 <= per_cluster_cap，池覆盖更分散
```

### Architect 接口契约（纯函数，便于 PBT）

```python
# core/infrastructure/seed_pool.py
from dataclasses import dataclass
from typing import Iterable

@dataclass
class PoolRecord:
    expression: str
    settings: dict                 # region/universe/decay/neutralization/truncation/instrumentType/delay
    source: str                    # tier0_economic | tier1_real | tier2_kakushadze
    family: str                    # momentum|reversal|value_quality|liquidity|volatility_news
    hypothesis: str
    fitness: float | None = None
    sharpe: float | None = None
    turnover: float | None = None
    oos_present: bool = False

def build_real_parent_pool(
    db: dict,
    *,
    fitness_min: float = 1.0,
    per_family_quota: float = 0.30,
    include_tier2: bool = True,
    timeout_guard=None,
) -> dict:
    """返回 {'tier0':[PoolRecord], 'tier1':[PoolRecord], 'tier2':[PoolRecord],
             'pool':[PoolRecord], 'meta':{...}}。"""
```

### 集成契约
- `candidate_generator.main()` 在父池构建阶段调用 `build_real_parent_pool` 作为父池来源之一（与现有 D/F/G 管线并行，不破坏）。
- 输出 `PoolRecord` 字段与 `candidate_generator` 消费结构兼容（见 `team/contracts/contracts.json`）。

---

## 反假功能自检（STDD §6）
- [x] 阈值全部交叉验证（BRAIN_THRESHOLDS_VERIFIED + 父池真实化报告 A1–A27）。
- [x] 无 skeleton/mock/TODO；test-first。
- [x] 不变式用 hypothesis PBT（配置有效性、配额上限）。
- [x] 门④ 变异 score ≥ 70%，由 QA 独立评估，非写代码者自证。
- [x] 四门 Merge Gate 全过才合入。
