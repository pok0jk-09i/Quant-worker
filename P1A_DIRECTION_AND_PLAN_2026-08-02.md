# P1-A 改造方向与具体计划（顶级源研读后决策）

日期：2026-08-02
**本文件取代 `P1A_PLAN_2026-08-02.md`**（旧计划只含 A/B/C 参数层改造；本轮新增 D/E 两根前沿支柱）。
依赖证据：`P1A_VALIDATION_2026-08-02.md`（参数双源验证）+ 本轮顶级源检索（见 §1）。

---

## 1. 顶级源研读结论（只列前沿 / 顶级，禁止拍脑袋）

| 层级 | 来源 | 类型 | 关键结论 |
|---|---|---|---|
| 奠基 | Kakushadze《101 Formulaic Alphas》arXiv:1601.00991 (2016) | 经典论文 | 101 个真实 alpha 平均两两相关仅 **15.9%**；收益与波动率强相关、与 turnover 无关；主张把大量弱 alpha 组合成"mega-alpha"内部对冲。 |
| 前沿-RL | **AlphaGen** "Generating Synergistic Formulaic Alpha Collections via RL" **KDD 2023** | 顶会论文 | 单个 alpha 天然是**弱预测器**，真正力量来自**组合**；用 PPO + 非法动作掩码生成表达式，奖励 = 该 alpha 对现有池的**边际 IC 贡献**；基线含 GP(gplearn)、DSO。 |
| 前沿-组合 | **AlphaForge** arXiv:2406.18394 (2024) | 论文 | 两阶段：生成-预测 NN 产出因子 + 组合模型按因子**时序表现动态调权**，克服固定权重的市场不适应。 |
| 前沿-多样性 | **AlphaSAGE** arXiv:2509.25055 (2025) | 论文 | GFlowNet 多样性探索 + RGCN 结构感知；密集多维权衡奖励（预测力+可解释+显著性）；OOS 信息系数 +18%、多样性熵 +0.42 nats。 |
| 前沿-基准 | **AlphaBench** ICLR 2026 (OpenReview d97Q8r7ZKZ) | 顶会基准 | **关键诚实发现**：LLM 能可靠生成*合法*因子，但"判断因子好坏（评估任务）"接近**随机猜测**。证明无回测则无法判质量。 |
| 前沿-综述 | LLM-based alpha mining 综述 FITEE 2025 (2026 卷) | 综述 | FAMA(CSS+CoE)、QuantAgent(writer-judge)、AlphaAgent(原创性+假设-因子对齐+复杂度控制) 三大范式。 |
| 前沿-批判 | 港科大《Automated Alpha Factor Discovery…A Critical Survey》2026-05 | 批判综述 | 明确指出：**进展不靠"无约束生成"，而靠可靠评价 + 经济 grounding + 多样性控制 + 可复现基建 + 人机协作**；LLM 引入幻觉/泄漏/非法代码风险。 |
| BRAIN 实战 | alexisdpc/WorldQuant-alpha-trading (GitHub, 实跑公式) | 官方镜像/实跑 | Fitness = Sharpe·√(\|Returns\|/max(Turnover,0.125))；**truncation=0.01 是达标 alpha 标配**；SUBINDUSTRY 中性化基线；具体模板：`rank(ts_mean(close,30)-close)`、`trade_when(volume>adv20,-ts_delta(close,5),-1)`、`ts_rank(cashflow_op/cap,60);group_rank(alpha,subindustry)`。 |
| BRAIN 实战 | compasty WorldQuant Brain 教程 (搬运官方) | 官方镜像 | 提 Sharpe：降 decay / 更流动 Universe / 增波动 / 另类数据；降 turnover：`trade_when`；鲁棒性：`rank test`/`binary test`/`sub-super universe test`；中性化选择。 |
| 集成 | 东方证券 KD-Ensemble / DFQ-XGB (2024) | 券商研报 | **低相关因子组合 1+1>2**；知识蒸馏集成树+NN；多模型等权合成 IC 提升。 |

---

## 2. 方向决策（5 条证据驱动）

**当前生成器 = 纯盲字段替换（R3-B）+ 超时护栏（R3-C）**，对照前沿，它恰好命中 2026 批判综述点名的四大失败模式：

1. **无经济 grounding**：盲替换不产生"均值回复/动量/质量"等可解释经济假设，正是 AlphaAgent/QuantAgent 强调要杜绝的。
2. **无多样性控制**：80 个候选几乎都是同一弱父的近邻替换，高度相关——违背 AlphaGen"边际 IC 贡献"、AlphaSAGE"多样性熵"原则。
3. **无评价反馈**：生成→BRAIN 提交是开环，没有 AlphaGen 的 IC 奖励 / AlphaForge 的时序选择闭环。
4. **参数空间残缺**（已确诊）：`TRUNCATION_OPTIONS` 无 0.01 → 结构上过不了 IND 浓度闸。
5. **本地无法判质量**（AlphaBench 铁证）：任何系统无回测都接近随机判质量——所以"本地评分"不可靠，**唯一可靠 ground truth 是 BRAIN 自身 IS 结果**。

### 决策：从「盲替换」升级为「经济模板驱动 + 多样性感知 + BRAIN 结果反馈」范式

**为什么不是直接搬 AlphaGen 全量？** AlphaGen 需要 Qlib + CSI300 历史数据 + RL 训练，且用 Qlib 回测做 IC 奖励——我们的约束是 **BRAIN 算子语言 + BRAIN 是唯一评估器 + 无本地数据/回测器**，全量 RL 不现实。因此采纳其**三根支柱的原则**，做轻量 BRAIN-native 落地：

| 前沿支柱 | 本系统落地 | 改动 |
|---|---|---|
| 经济 grounding（AlphaAgent/Kakushadze） | **D 经济模板库**：以有经济含义的骨架生成，而非纯替换 | 新增 |
| 多样性控制（AlphaGen/AlphaSAGE） | **D 跨 field-family/operator-family 实例化 + 局部多样性草图** | 新增 |
| 评价反馈（AlphaGen IC / AlphaForge 时序） | **E BRAIN 结果反馈偏置**：用 `candidate_submit_results.json` 的历史 IS sharpe 反哺采样 | 新增 |
| 参数合规（alexisdpc/compasty） | **A 参数硬化 + B rank 包裹 + C 字段偏好** | 已规划（保留） |

> **"mega-alpha" 组合的转化**：Kakushadze 的"组合大量弱 alpha"在 BRAIN 单因子提交模型下，语义转化为"**系统性、有依据、低相关地批量产出候选，让 BRAIN 真守门人筛**"，而非追求"一个超级 alpha"。

---

## 3. 具体改动（SDD 接口契约）

### A. 参数硬化（低风险，确定性强）— 保留原计划
- A1 `TRUNCATION_OPTIONS` → `[0.01, 0.02, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12]`（0.01 置首）。
- A2 `extract_settings` 默认 `truncation 0.08→0.01`、`decay 0→4`。
- A3 `generate_variants` 的 `base_truncation 0.08→0.01`、`base_decay 0→4`。

### B. 表达式 rank 安全包裹（中风险，test-first）— 保留原计划
- 最外层非横截面算子（`{rank,zscore,scale,group_rank,group_zscore,sign}`）则包 `rank(...)`；已是则跳过；`trade_when/if_else` 整体包裹；包裹后 `validate_expression` 复核。

### C. 字段偏好（低风险，与 R3-C 联动）— 保留原计划
- `_substitute_fields` 优先同 type 且非 `anl4_*`/分析师前缀字段；降权超时/慎用字段。

### D. 经济模板库 + 多样性生成（核心新增）
- **新增 `core/infrastructure/alpha_templates.py`**：
  - 一组 `TEMPLATES`，每条 = `(name, economic_category, builder(field, window)->expr, required_type, default_window_range)`。
  - 来源是顶级源里的**实跑/经典**骨架（非发明）：
    1. 均值回复 `rank(ts_mean(f,30) - f)`（alexisdpc）
    2. 短期反转 `rank(-ts_delta(f,5))`（alexisdpc 量价事件）
    3. 质量-现金流 `group_rank(ts_rank(f/cap,60), subindustry)`（alexisdpc）
    4. 量价事件 `trade_when(volume>adv20, rank(-ts_delta(f,5)), -1)`（alexisdpc）
    5. 低波动 `rank(-ts_std_dev(f,20))`
    6. 动量 `rank(ts_delta(f,60))`（Kakushadze 动量）
    7. 估值 `rank(-f)`（估值类字段，便宜做多）
    8. 横截面 `zscore(f)`
  - `instantiate(tpl, field, window)` → 返回 (expr, signature)；`signature` = `(economic_category, field_family, operator_family, window)` 用于多样性草图。
- **生成器改造**（`candidate_generator.py`）：在原有"父替换"之外，**新增模板驱动通道**——对每个经济类别，从 `load_field_types()` 里挑**不同 field-family**（价格量/基本面/估值/质量）的合格字段、各取 2-3 个窗口实例化，保证跨家族多样性。
- **局部多样性草图**：维护 `seen_signatures` 集合，对重复 signature 降采样，避免 80 候选塌缩成近邻。

### E. BRAIN 结果反馈偏置（核心新增）
- **新增 `core/infrastructure/result_feedback.py`**：
  - `load_result_signal(results_path)`：解析 `candidate_submit_results.json`，对每条 COMPLETE 提取 `(field_family, operator_family, truncation, decay, neutralization)` + `is_metrics.sharpe/fitness/turnover`。
  - `bucket_sharpe(field_family, operator_family, ...)`：仅对样本数 `N≥k`（默认 3）的桶算均值 sharpe，避免小样本噪声。
  - `sampling_bias(field, expr)`：返回 `[0,1]` 偏置分——高 sharpe 桶↑、长期 0 提交/负 sharpe 桶↓。
- **生成器集成**：字段选择、模板选择、参数选择时，用 `sampling_bias` 做加权采样。这是轻量实现 AlphaGen 的 "IC reward" + AlphaForge 的 "时序选择"——**用 BRAIN 自身 IS 结果作 ground truth**，规避 AlphaBench 证明的"本地瞎判质量"陷阱。

---

## 4. 测试策略（三层验证栈）

- **Unit**：
  - A：`TRUNCATION_OPTIONS` 含 0.01；`extract_settings` 默认 0.01/4；`generate_variants` base 默认 0.01/4。
  - B：4 种形态（ts_corr/log/trade_when/已 rank）包裹正确且不破坏类型。
  - C：替代字段降权分析师。
  - D：每个模板 `instantiate` 产出 `is_type_safe` 表达式 + 经济类别标签 + 窗口变化；模板通道产出跨 field-family 多样性（断言 ≥4 个不同 field_family）。
  - E：`load_result_signal` 从 mock JSON 正确算桶均值；死桶（sharpe<0）bias 低、活桶高；`sampling_bias` 返回归一化值。
- **PBT（hypothesis）**：随机 field + 随机模板 → 表达式 `is_type_safe` 且 signature 合法。
- **Mutation**：对 `_safe_rank_wrap` / `instantiate` / `bucket_sharpe` 核心函数做 mutmut，目标 **mutation score ≥ 70%**。

## 5. 验收标准（GIVEN-WHEN-THEN）
- GIVEN 父无 truncation/decay → WHEN `extract_settings` → THEN truncation=0.01、decay=4、neutralization=SUBINDUSTRY。
- GIVEN `ts_corr(x,y,20)` → WHEN `_safe_rank_wrap` → THEN `rank(ts_corr(x,y,20))` 且 validate 通过。
- GIVEN 8 个模板各取 3 字段 × 2 窗口 → WHEN 生成 → THEN 候选覆盖 ≥4 个 field_family，无重复 signature 占比 ≥ 80%。
- GIVEN mock 结果含"家族 X sharpe=2.0(N=5)、家族 Y sharpe=-1.0(N=5)" → WHEN `sampling_bias` → THEN bias(X) > bias(Y) 且均 ∈[0,1]。
- GIVEN 生成 100 变体 → WHEN 检查 settings → THEN truncation 含 0.01、decay≥4 占比 ≥50%。

## 6. 实施步骤顺序（test-first）
1. 写 `test_candidate_generator_p1a.py`（A/B/C 骨架）+ `test_alpha_templates.py`（D）+ `test_result_feedback.py`（E）。
2. 实施 A1-A3 → 跑单测。
3. 实施 B → unit + PBT。
4. 实施 C → 测试。
5. 新增 `alpha_templates.py` + 生成器模板通道 → D 测试。
6. 新增 `result_feedback.py` + 生成器集成 → E 测试。
7. mutmut 核心函数 ≥70%。
8. 全量 pytest 零回归（当前 **89 passed** 基线）。
9. **重启监督树**（时序陷阱：project_runtime 启动即 import 生成器）观察真实产出。

## 7. 诚实边界（必须直说）
- **不承诺预测力跳涨**：AlphaBench ICLR2026 证明——无回测则判因子质量接近随机。我们无本地回测器，**唯一可靠信号是 BRAIN 真实 IS 结果**（已用 E 反馈吸收）。D/E 提升的是"结构性合规 + 多样性 + 有依据采样"，不是"瞬间冲到 sharpe 1.5"。
- **父池幽灵数据仍是天花板**：本地 10 个 `status=ACTIVE` 在 BRAIN 1100 条里不存在。模板化能拉高合规率与多样性，但弱父逻辑天花板仍在。若实施后仍 0 提交 → 根因转向"父池真实化/经济逻辑增强"专项（另立）。
- **E 的噪声护栏**：桶 `N<3` 不采纳，防止早期小样本误导采样。
- **回滚**：A/B/C/D/E 集中且可逆（generator + 2 新模块），git diff 可退；改动须重启监督树才生效，回滚同理。

## 8. 观察指标（实施后盯 `candidate_submit_results.json`）
- `metrics_threshold` 拦截率是否下降（合规率↑）；
- 是否有因子首次 sharpe/fitness ≥ 1.5/1.5 进入提交；
- 候选 field_family 多样性是否提升（D 生效）；
- TIMEOUT 率是否进一步下降（C 减少分析师字段）。
