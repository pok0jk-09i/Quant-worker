# Quant worker 研究方向决策（2026-08-01，深度联网双源验证）

> 目的：在动手改研究管线之前，先用深度联网 + 双源交叉验证，确定「最专业、最正确」的方向。
> 结论先行：**方向不是「把 IND truncation 调到 0.01」这么简单；根因是生成配方缺少横截面 rank/中性化包裹，truncation 默认 0.08 + 偶发 `neutralization: NONE` 是浓度爆到 0.5 的真凶。正确方向 = 生成配方硬化（rank+中性化+低 truncation+decay）+ 保留已验证的闸 + 研究家族治理。质量优先于数量。**

---

## 一、双源验证的关键事实（每个结论 ≥ 2 独立来源）

### 1. CONCENTRATED_WEIGHT（权重测试）= 单一股票最大权重 ≤ 账簿 10%，全局硬红线
- 来源 A（WorldQuant BRAIN 学习记录，compasty.netlify.app）：「权重测试衡量单只股票的资本集中度，限制为总账簿规模的 **10%**」。
- 来源 B（delitao.com 指标汇总）：「Maximum single stock weight less than **10%**」。
- ✅ 我们 `submit_gate.concentrated_weight_max = 0.10` **正确**，无需改。

### 2. 权重测试失败的两类根因及解法
- 来源（compasty 教程）：
  - (a) **集中度过高** → 用 `rank` / `ts_rank` / `zscore` / `ts_zscore` 移除异常值，**或**降低 `truncation`。
  - (b) **覆盖率过低**（多/空仓 < 10 只，或总数 < 20 只）→ 用 `ts_backfill` / `is_nan` / `last_diff_value` 回填。
- ✅ 我们 IND `value=0.5` 属 (a) 极端集中度，是**生成缺陷**（信号未横截面均匀化），不是区域天花板。

### 3. truncation 的权威用法（推翻「只调 truncation」的朴素假设）
- 来源 A（CSDN m0_73177400）：TOP3000 通常用 **~0.01**；更小域（TOP200）反而可稍大。
- 来源 B（roger2389 WorldQuant 入门）：「**Truncation value = 0.01 for diversity**」。
- 来源 C（alexisdpc 实跑高 Sharpe 案例）：`truncation=0.08` 能过权重测试，**前提是表达式已 `rank()` + `SUBINDUSTRY` 中性化 + `decay 4~15`**。
- 🔑 **关键洞察**：truncation 是「次级杠杆」，真正让单股权重 < 10% 的是**表达式外层的横截面 rank/zscore 包裹**。裸比值（如 `operating_income/equity`）即使 truncation=0.08 仍会集中到 50%。**rank + 低 truncation 组合才是正解。**

### 4. Sub-Universe Sharpe 阈值公式 —— 我们已实现版本被独立源确认正确
- 我们 `thresholds.sub_universe_sharpe_threshold`：`√252 × max(0.065, ratio × coeff)`，coeff 0.15(delay1)/0.25(delay0)。
- 独立来源（zread QuantGPT `wq_brain_simulation_and_submission`）：「Sub-Universe Sharpe ≥ `√252 × max(0.065, 0.5×0.15)`」——**结构完全一致**（ratio=0.5 为 50/50 划分，coeff=0.15 为 delay1）。
- ⚠️ 另一社区公式 `0.75 × √(sub/uni) × alpha_sharpe`（dafu-zhu）**非主流、与官方 tutorial 不符**，我们此前已正确否决。
- ✅ Sub-Universe 闸**无需改**，保留。

### 5. 提交的硬门槛（决定能否进池）
- 多源一致（gentlecactus / zurie PV Alphas / zread / roger2389 / delitao）：Sharpe > 1.25、Fitness > 1.0、Turnover ∈ [1%,70%]、Max Weight ≤ 10%、Self-Correlation < 0.7（或 Sharpe > 1.375 即超 10% 可豁免）、Sub-Universe 阈值。
- 标准**因区域和 delay 而异**；CHN 更高。IND 是真实支持区域（worldquantbrain.com 顾问页列 India 为 17 区域之一），公开仅详述 USA D1，区域细节需登录查看。

### 6. Alpha 状态生命周期（纠正一个关键误解）
- 官方 tutorial（compasty）：成功模拟 → **UNSUBMITTED**；成功提交并接纳 → **ACTIVE**；数据集退役/OS 持续差 → **DECOMMISSIONED**。
- deepwiki 本地状态机（INIT→SIMULATED→SYNC→CHECKED→SUBMITTED）是**我们本地 DB 的状态**，不等于平台 ACTIVE。
- 🔑 **含义**：BRAIN 上 1100 条 100% UNSUBMITTED、ACTIVE=0 = 这些 alpha 要么未被成功接纳进活池，要么提交 API 失败（IND 403）。**拿到 API 201（本地 SUBMITTED）≠ 平台 ACTIVE**——平台还会按活池质量线复审。这与「质量优先于数量」完全吻合。

### 7. 研究判断 > 回测次数（元方向，来自可信复盘）
- 来源（CSDN 2402_87488142「一个月研究复盘」）：决定效率的是**研究判断而非回测次数**。「无效努力信号」= Sharpe 卡 0.7–0.9、PnL 后段衰减、Sub-Universe 反复挂、权重集中度过高、相似度爆表。若同一研究家族连续相似失败 → **果断停，路线接近天花板**，而非硬磨。
- 我们的症状（IND 集中度 0.5）属**技术性失败**（可修），不是结构性天花板 → 应修管线，而非弃 IND。

---

## 二、对我们当前代码的核对（立在本项目事实上）

| 项 | 当前真实值（grep 证据） | 问题 |
|---|---|---|
| `candidate_generator.py` 默认 truncation | `base_truncation = settings.get("truncation", 0.08)` | 默认 0.08 偏高 |
| `submit_batch.py` 提交表达式 truncation | 全部 `0.08` | 未随区域调整 |
| neutralization | `SUBINDUSTRY` / `INDUSTRY` / **`NONE`**（candidate_submit_results 中确有 NONE） | `NONE` + 裸比值 + 0.08 → 浓度爆 |
| 表达式包裹 | 多数有 `rank/group_rank/ts_rank`，但变体扫掠可能生成未包裹副本 | 缺强制保证 |
| decay | 0 / 2 / 12 混合 | 0 在部分场景加剧换手与集中 |

**结论**：根因 = 生成端未强制「横截面 rank 包裹 + 区域感知中性化 + 低 truncation + 适度 decay」。闸（submit_gate）只挡已生成的坏 alpha，不生产好 alpha。

---

## 三、决定的方向（三层）

### 方向层 1 — 生成配方硬化（最高杠杆，真正解决 403 与 0→ACTIVE）
- **强制横截面包裹**：每个 emit 的表达式，若最外层非 `rank/ts_rank/zscore/ts_zscore`，自动外包一层 `rank(...)`（或 `ts_zscore`）。
- **中性化绝不 NONE**：区域感知，`SUBINDUSTRY`（默认）/ `INDUSTRY`；IND 等小域强制 `SUBINDUSTRY`。
- **truncation 区域感知**：TOP3000 → `0.01`；更小域（TOP500/TOP200）→ `0.01–0.02`；扫掠选项改为 `[0.01, 0.02]`，不再保留 0.08 为默认。
- **decay 默认 ≥ 3**（平滑、降换手、间接降集中）。
- **生成期浓度探针**：模拟后若 `is.checks` 含 `CONCENTRATED_WEIGHT` 且值 > 0.1 → 该候选判失败、不进提交队列（闸已是兜底，此为前移止损）。

### 方向层 2 — 保留并校验已验证的闸（不回退）
- `submit_gate`：`concentrated_weight_max=0.10` + `sub_universe_sharpe_threshold(√252×max(0.065, ratio×coeff))` 双闸**正确且双源验证**，保留为安全网。
- `oos_evaluator`：IS→OOS decay > 50% = 过拟合，保留并强化（walk-forward）。

### 方向层 3 — 研究家族治理（元层，避免无效努力）
- 给候选打「研究家族」标签（价量事件 / 慢频基本面 / 期权IV / 分析师预期 / 新闻情绪 / 风险风格）。
- 同家族连续 3 次相似结构性失败 → 自动降权/暂停该家族，转下一个，而非 brute-force。
- 多层相关性剪枝（0.98 / 0.95 / 0.95）避开 self-correlation 0.7 墙（参考 WQAlphas）。
- 反过拟合：4 项统计检验 + walk-forward + 真实模拟（参考 QuantGPT）。

---

## 四、下一步实施计划（P1，按 STDD 四门 Merge Gate）

**P1-A（核心，建议立刻做）**：生成配方硬化
- 改 `candidate_generator.py`：默认 truncation→区域感知 0.01；变体扫掠 truncation 选项 `[0.01,0.02]`；新增 `ensure_rank_wrapped(expr)` 强制横截面包裹；neutralization 禁止 NONE（区域感知）。
- 改 `evolve_skill.py`：继承同套配方；`_write_generation_guidance` 下发浓度安全约束。
- 改 `submit_batch.py`：表达式统一加 rank 包裹、truncation 区域感知。
- 测试：新增 `test_generator_recipe.py`（Red→Green）覆盖「未包裹表达式被自动 rank」「NONE 中性化被拒」「IND truncation=0.01」。
- 四门：规格覆盖 → lint→unit→（集成模拟 stub）→ 契约（表达式解析合法）→ QA 独立评估 + 变异分≥70%。

**P1-B（支撑）**：生成期浓度探针前移（复用 submit_gate 逻辑到生成侧）。

**P1-C（治理）**：研究家族分类 + 相关性剪枝（可下一轮）。

---

## 五、反模式（绝不做）
- ❌ 只把 truncation 调到 0.01 但表达式不 rank —— 峰值信号仍集中。
- ❌ brute-force 更多 alpha 指望「神奇窗口」—— 复盘明确此为无效努力。
- ❌ 因 IND 浓度失败就弃 IND —— 这是技术缺陷，非天花板。
- ❌ 动已验证正确的 sub_universe 公式或 0.10 浓度红线。

---

## 六、待用户拍板
是否按 STDD 启动 **P1-A（生成配方硬化）**？这是把 IND 真正推到 0→ACTIVE 的关键一步，也是把整体从「1100 条 0 ACTIVE」扭转为「质量优先」的转折点。
