# 顶级源交叉验证报告 — 2026-08-01

> 目的：对 R1（激活 √252 Sub-Universe 公式）、R3（生成器类型感知）、R5（统一阈值来源）依赖的**每一个决策点**，只用顶级/官方镜像源做交叉验证，禁止拍脑袋。
> 方法：官方 BRAIN 文档有登录墙，改取**直接搬运官方文档的镜像源**（明确标注原文链接）+ 引用官方数值的开源实现（QuantGPT/wq_brain_client.py）。论坛帖仅作线索，最终以官方镜像或官方数值落地实现为准。

## 一、使用的源（按权威度分级）

| 源 | 类型 | 权威性 | 说明 |
|---|---|---|---|
| `platform.worldquantbrain.com/learn/data-and-operators/operators` | 官方 | ★★★★★ | 登录墙；由 GitHub `trung-vt/Fast-Expression-Documentation` 逐字搬运 |
| `platform.worldquantbrain.com/learn/documentation` | 官方 | ★★★★★ | 登录墙；由 CSDN `zurie` 翻译镜像 |
| `platform.worldquantbrain.com/simulate/tutorial` | 官方 | ★★★★★ | 登录墙；由 CSDN `Oo_Amy` / `zurie` 引用 |
| `hr-23/Worldquant-Brain-Alpha` "How to choose Simulation Settings" | 官方教程搬运 | ★★★★★ | 逐段对应官方 Settings 说明 |
| `zread.ai/Miasyster/QuantGPT` (wq_brain_client.py 镜像) | 开源实现，内置官方 IS 阈值 | ★★★★☆ | 直接 mirror 强制执行的 BRAIN 提交阈值 |
| `alexisdpc/WorldQuant-alpha-trading` | 实跑 alpha + 设置 | ★★★★☆ | 给出可复现的 USA/TOP3000 真实设置 |
| `dafu-zhu/alpha-lab` | 算子参考（68 算子对齐 BRAIN） | ★★★★☆ | 算子分类与签名 |
| `compasty` / `lydeee` | 算子分类科普 | ★★★☆☆ | 仅用于交叉确认算子类别 |

## 二、决策点交叉验证

### ✅ D1：√252 Sub-Universe 公式 —— 确认正确（双源逐字符印证）
- **zread.ai (QuantGPT)**：`Sub-Universe Sharpe ≥ √252 × max(0.065, 0.5×0.15)`；并明确"阈值 = √252 × max(0.065, (subuniverse_size/largest_universe_size) × coeff)，delay1 coeff=0.15，delay0 coeff=0.25"。
- **CSDN Oo_Amy**：`Delay1: sqrt(252)*max(0.065,(subuniverse_size/largest_universe_size)*0.15)` / `Delay0: sqrt(252)*max(0.065,(subuniverse_size/largest_universe_size)*0.25)` —— **逐字符等同我们的 `thresholds.py`**。
- **dafu-zhu**：提到备选公式 `0.75 × sqrt(sub_size/alpha_universe_size) × alpha_sharpe`，但明确标注"非固定常数"、"不同方法"。**已正确否决该变体**。
- **结论**：我们的 `sub_universe_sharpe_threshold(delay=1 → 0.15, delay=0 → 0.25, floor=0.065)` 选型**正确**。R1 激活它的方向无误。

### ✅ D2：官方硬指标阈值（ACTIVE 守门） —— 统一到官方值
- **zread.ai**：`Sharpe ≥ 1.25`、`Fitness ≥ 1.0`、`Returns ≥ 6.3%`、`Turnover ∈ [1%,70%]`、`Max Weight ≤ 10%`、`Sub-Universe Sharpe ≥ √252×max(0.065,0.5×0.15)`。
- **dafu-zhu**：`Sharpe > 1.25`、`Fitness > 1`、`Turnover 1% cutoff`。
- **alexisdpc**：`Fitness passing requirement > 1.0`。
- **结论**：平台硬线是 **Sharpe 1.25 / Fitness 1.0 / MaxWeight 10%**。当前 `candidate_submitter.py` 硬编码 `1.5/1.5/0.30`、`submit_batch.py` 用 `0.20`——**三套不一致**。R5 应统一到官方 1.25/1.0/0.10（更严格的质量地板可作为可选配置，但必须显式来源化，杜绝散落硬编码）。

### ✅ D3：算子/数据类型兼容性（R3 根因） —— 官方分类确认
- **官方结构（GitHub trung-vt 镜像）**：参数顺序 = 数据字段 → 分组(可选) → 回看天数(可选) → 关键字参数。
- **算子类别（dafu-zhu / compasty 对齐官方）**：
  - **Time-Series (ts_*)**：`ts_mean/ts_sum/ts_std/ts_min/ts_max/ts_delta/ts_delay/ts_zscore/ts_scale/ts_corr/ts_covariance/ts_regression/ts_backfill` 等 —— 作用于**单只股票自身历史**（Unit[]）。
  - **Cross-Sectional**：`rank/zscore/quantile/winsorize/scale/normalize` —— **同一时点跨股票**（Unit[]，但语义是截面）。
  - **Group**：`group_rank/group_zscore/group_scale/group_mean/group_neutralize/group_backfill` + `densify` —— 输入/输出带 **Unit[Group]**。
  - **Arithmetic**：`add/subtract/divide/multiply/log/power/abs/signed_power/sqrt/inverse` —— 标量/向量逐元素。
  - **Vector**：`vec_avg/vec_sum`。
- **错误语义确认**：
  - `expected Unit[], found Unit[Group:1]` = 把 **Group 类型字段/算子输出**喂进了 **Time-Series 算子（ts_*）** → 非法。
  - `ts_backfill/divide does not support event inputs` = 把 **Event 类型数据字段**（财报/分红/新闻/公告类）喂进了**不支持事件输入的算子** → 非法。
- **Event 用法范式（alexisdpc 实跑）**：事件字段只作为 `trade_when(event, alpha, -1)` 的**触发条件**，alpha 本体是普通时序表达式；事件字段**不直接进算术/ts_* 算子**。
- **结论**：R3 的类型感知规则有官方依据：① Event 字段 → 仅 `trade_when` 触发 / 事件算子，禁入 `ts_backfill/divide/ts_*`；② Group 字段/输出 → 仅 `group_*/rank/zscore/quantile/winsorize/densify`，禁入 `ts_*`；③ Time-Series 字段 → 可入 `ts_*/算术`。

### ✅ D4：Universe 规模（R1 的 largest_universe_size 来源）
- **hr-23（官方 Settings 搬运）**：`US: TOP3000 = top 3000 most liquid stocks`；zread.ai 列出可选 `TOP3000/TOP1000/TOP500/TOP200`。
- **结论**：名义规模表 `TOP3000→3000, TOP1000→1000, TOP500→500, TOP200→200`；`sub_size` 优先取 BRAIN 回传的 coverage，否则取 `largest/2`（50/50 子宇宙划分，与 zread.ai 描述的子宇宙测试一致）。

### ✅ D5：Self-Correlation 是 SUBMITTED→ACTIVE 的真正守门人
- **zread.ai**：`提交触发 SC 检查，判定 Alpha 是否与平台已有 Alpha 充分不同（SC<0.7），这是成功模拟与被接受(ACTIVE)之间的守门人`。
- **结论**：1100 条全 `UNSUBMITTED`、0 `ACTIVE` 的根因之一是**平台 SC 拒相似因子**——印证"质量+独特性优先于数量"。R3 必须加**相关性剪枝**（家族内/跨家族 PnL 相关 < 0.7）才能提高 ACTIVE 转化率。

## 三、对修复任务的影响

| 任务 | 决策 | 依据 |
|---|---|---|
| **R1** 激活 √252 | 推进 | D1 双源确认公式正确；D4 提供规模表 |
| **R3** 生成器类型感知 | 推进（最高杠杆） | D3 官方算子分类 + 错误语义 + Event 范式 |
| **R5** 统一阈值 | 推进 | D2 官方硬线 1.25/1.0/0.10；消除三套硬编码 |
| **R4** 落盘 is_metrics | 推进 | 无外部依赖，纯观测增强 |
| 否决 `0.75×√(sub/uni)×α` 变体 | 维持否决 | D1 dafu-zhu 标注非主流 |

## 四、反模式（禁止）
- ❌ 把 Group 字段直接喂 `ts_*`（产生 `Unit[Group:1]` 错误）。
- ❌ 把 Event 字段喂 `ts_backfill/divide/ts_*`（产生 event input 错误）。
- ❌ 在生成器里散落 `1.5/0.20/0.30` 等未来源化阈值。
- ❌ 用社区 `0.75×√(sub/uni)×α` 替代已验证的 √252 公式。
