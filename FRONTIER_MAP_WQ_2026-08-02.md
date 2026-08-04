# 符合世坤（WorldQuant）顶级方案的前沿图谱

> 深度精读顶级/官方源后综合而成。覆盖：世坤奠基论文、BRAIN 官方算子/模拟文档镜像、实战过检因子、以及 2023–2026 公式化 alpha 挖掘前沿（AlphaGen / AlphaForge / AlphaSAGE / Hubble / QuantaAlpha / CogAlpha / LLM 增强 GP）。
> 用途：作为 P1-A 改造方向的**事实源**与"顶级打法"对齐基准。所有数值均来自源，未拍脑袋。

---

## 一、世坤顶级打法的三大支柱（从奠基论文 + 实战 + 前沿综述收敛）

| 支柱 | 含义 | 证据 |
|---|---|---|
| **① 经济 Grounding** | 因子必须由可解释的经济假设驱动，而非盲替换 | Kakushadze 101 Alphas（世坤研究员，arXiv 1601.00991）全部 101 个因子均有明确经济含义；2026 批判综述点名"无约束生成"是主要失败模式；Hubble/QuantaAlpha/CogAlpha 均以"先有金融逻辑再生成因子"为设计前提 |
| **② 多样性 / 正交性** | 低相关、跨家族、不拥挤 | Kakushadze 实测 101 因子**平均两两相关仅 15.9%**；世坤顾问硬指标 **PnL 相关 < 0.7 才算真 edge（非 remix）**（Darren Li, BRAIN Gold）；AlphaSAGE 把"多样性"直接写进目标函数（GFlowNet 按 reward 比例采样→天然低相关）；QuantaAlpha 初始 10 个"独立互补假设"防拥挤 |
| **③ 评价反馈闭环** | 生成→评估→迭代，且**必须用 BRAIN 真 IS 结果作 ground truth** | ICLR 2026 AlphaBench 铁证：无回测时"判断因子好坏"接近随机→本地瞎猜质量不可靠；Hubble/QuantaAlpha/QuantGPT 均以平台评估反馈驱动下一轮；AlphaSAGE "奖励退火"早用结构信号、晚期才用 terminal IC |

**第四根隐性支柱（世坤平台硬约束）**：因子必须**可实施 + 正交 + 子宇宙稳健**。
- Fitness > 1.0，Sharpe > 1.25
- Turnover ∈ [1%, 70%]（执行/冲击感知）
- 单资产权重 < 10%（分散纪律）
- **子宇宙稳健性**：必须在 size/liquidity/sector 切分上都 travel 得动（Darren Li 原话）

---

## 二、公式化 Alpha 的黄金配方（来自世坤奠基 + 实战过检因子）

### 2.1 实战过检因子（QuantGPT 端到端提交 BRAIN，全部 IS PASS）

| 因子 | 表达式 | Sharpe | Fitness | Returns | 结构特征 |
|---|---|---|---|---|---|
| Debt-Momentum Composite | `-1 * rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)` | 1.77 | 1.26 | 20.18% | 动量反转 + 基本面(债务/EV)，行业中性化 |
| VWAP Decay Reversal | `-1 * rank(ts_decay_linear(close / vwap, 10))` | 1.69 | 1.07 | 18.63% | 价格偏离 VWAP 衰减回归，市场中性化 |
| Returns-Volume Momentum | `-1 * rank(ts_decay_linear(returns * volume / adv20, 5))` | 1.60 | 1.03 | 24.15% | 量价共振衰减动量，市场中性化 |

**三个过检因子的共同结构（这就是"世坤顶级配方"的骨架）**：
1. **组合而非单算子**：2+ 个 `rank(...)` 包裹的子信号相加（`+`）。
2. **每个子信号横截面 `rank` 包裹**是标配（稳健、去量纲）。
3. **衰减加权动量**：`ts_decay_linear` / `ts_av_diff` 捕捉短期反转。
4. **均值反转取向**：整体 `-1 *`（反向）。
5. **多源混合**：动量 + 基本面（debt/EV）/ 流动性（adv20）叠加 → 天然低相关。
6. **中性化必做**：`group_neutralize` / SUBINDUSTRY / 市场中性。

### 2.2 另一个实战复盘（中文 BRAIN 顾问，复合多因子）

- 4 子因子：动量反转 `-ts_mean(returns,33)`、流动性 `adv20`、活跃度 `volume/adv20`、质量 `sales/assets`
- 权重 `(0.12, 0.18, 0.12, 0.58)`（质量给最高权）
- **IS 结果：Sharpe 1.69、Fitness 1.41、Turnover 13.25%、子宇宙 Sharpe 1.17、自相关 0.693**（靠"Sharpe > 10%"条款豁免）
- 印证：复合 + 加权 + 子宇宙稳健 = 过检路径

### 2.3 参数金标准（BRAIN 官方模拟默认值 + 实战修正）

| 参数 | BRAIN 默认 | 顶级实战取值 | 说明 |
|---|---|---|---|
| truncation | 0.08 | **0.01**（达标 alpha 标配） | roger2389 官方搬运"for diversity"；jglazar 实跑 6 个达标 alpha 全用 0.01，Sharpe 1.28–1.62 |
| neutralization | SUBINDUSTRY | SUBINDUSTRY / 市场中性 | group_neutralize 通常**提升 Sharpe、略降 Returns**（CSDN devpress） |
| decay | 0（无） | **4 左右** | 控 turnover 在 [1%,70%]，避免高频 |
| delay | 1 | 1 | 次交易日语义 |
| testPeriod | P2Y | P2Y | 2 年回测 |
| pasteurization | ON | ON | 防未来函数 |

**Fitness 公式（compasty 官方搬运，与之前双源验证一致）**：
```
Fitness = Sharpe × √( |Returns| / max(Turnover, 0.125) )
```
→ 提高 Sharpe/Returns、压低 Turnover → Fitness 升。这就是优化方向。

---

## 三、BRAIN 算子体系（官方文档镜像，trung-vt + CSDN lydeee + compasty）

### 3.1 算子分类（Fast Expression）

| 类别 | 算子（代表性） | 作用 |
|---|---|---|
| **排名类** | `rank`, `group_rank`, `ts_rank` | 横截面/分组/时序排名 |
| **统计类** | `mean`, `std`, `corr`, `covariance`, `skewness`, `kurtosis` | 分布统计 |
| **时间序列** | `delay`, `delta`, `sum`, `ts_mean`, `ts_std_dev`, `ts_rank`, `decay_exp_window`, `ts_av_diff`, `ts_decay_linear`, `ts_corr`, `ts_regression`, `ts_backfill` | 沿时间轴 |
| **条件类** | `if_else`, `greater`, `less`, `eq`, `trade_when` | 条件触发 |
| **中性化** | `group_neutralize`, `regression_neut`, `vector_neut` | 剥离行业/市值/市场暴露 |
| **分组** | `subindustry`, `industry`, `sector`, `bucket` | 分组维度 |
| **算术** | `add`, `subtract`, `multiply`, `divide`, `max`, `min`, `abs`, `log`, `sqrt`, `inverse`, `sign`, `power` | 数值运算 |
| **变换** | `delay`, `decay_exp_window`, `sigmoid`, `left_tail`, `right_tail` | 变换 |

### 3.2 字段类型系统（决定算子-字段兼容）

- `MATRIX`（数值时序，Unit[]，最多，如 close/volume/returns）
- `VECTOR`（截面聚合）
- `GROUP`（分类，Unit[Group]，如 industry/subindustry/sector）
- `SYMBOL`（标识，如 cusip）
- `EVENT`（事件，命名如 `*_event_*` / `newqevent*`）

**兼容规则（我们 R3-B/expression_types.py 已实现并验证）**：
- 时序 `ts_*` 只接受 MATRIX/VECTOR；GROUP 禁入（→`Unit[Group:1]` 错误）
- SYMBOL/EVENT 禁入 `ts_backfill`/算术（→"event inputs"错误）
- `group_*(x, group)`：x 须数值、group 须 GROUP

### 3.3 调用约定（官方）

```
参数顺序：数据字段 → Group(可选) → Lookback(可选) → kwargs(key=value)
变量赋值：a = sales/assets; ts_delta(a, 252)   （不可重赋值）
```

---

## 四、2023–2026 前沿制胜范式（学术 SOTA，对齐世坤支柱）

### 4.1 演进时间线

| 方法 | 年份/会议 | 核心机制 | CSI300 IC / Sharpe |
|---|---|---|---|
| AlphaGen (PPO) | KDD 2023 | RL 组合生成因子表达式 | 0.058 / 0.76 |
| AlphaForge (GAN) | 2025 | 对抗生成 + 自适应组合 | 0.041 / — |
| AlphaQCM | 2025 | RL 变体 | 0.043 / — |
| **AlphaSAGE (GFlowNet)** | **ICLR 2026** | **结构感知 GFlowNet + 复合奖励 + 自适应组合** | **0.079 / 1.71** |
| Hubble (LLM) | 2026-03 | DSL + AST sandbox + 正负 RAG + family-aware | range/vol/trend 家族主导 |
| QuantaAlpha (LLM+进化) | 2026-02 | 多智能体模拟研究员流程 | RankIC + 低冗余 + 容量三重门 |
| CogAlpha (LLM) | ACL 2026 Oral | 公式→代码升级 + 7层21智能体 | 年化超额 16.39% / IR 1.90 |
| 东吴 LLM增强GP | 2026-06 | LLM 提供金融逻辑+子表达式基因，GA 高强度搜索 | \|RankIC\| 6.98% / ICIR 0.79 |

### 4.2 AlphaSAGE（当前 SOTA）关键设计——可直接借鉴

1. **结构感知编码**（RGCN 替换序列编码器）= **单项最大增益**。"丢结构"是 RL 路线最大短板 → 印证"结构/经济含义"比"字符序列"重要。
2. **多样性必须在目标函数里**（GFlowNet 采样概率 ∝ reward → 从一开始就是低相关），而非事后去重。
3. **复合奖励**：结构对齐（相似结构⇒相似行为）+ 新颖度（降冗余）+ 熵正则（鲁棒探索）。
4. **奖励退火**：早期用密集的结构/新颖信号解冷启动，晚期过渡到 terminal IC（真预测力）。
5. **自适应组合（部署关键）**：动态线性回归重加权，每个再平衡期筛掉过时/冗余信号 → 单信号变 mega-alpha。**这正是"组合"这步的顶级实现**。

### 4.3 Hubble（最贴合 BRAIN-native 落地的框架）

- **安全生成**：约束到 DSL（可解释算子树）+ 三层 AST sandbox 校验 → 零运行时崩溃（我们 R3-A/R3-B 即此类）
- **正负 RAG**：正 RAG 探索欠覆盖主题；负 RAG 显式抑制拥挤模板 → 直接对应我们的"家族多样性门控"
- **Family-aware 选择**：打分含**拥挤度/相似度/家族集中度**，而非裸统计 → 直接对应 P1-A 的多样性感知
- **研究就绪输出**：每个因子存档 RankIC / Pearson IC / 分桶收益 / 多空价差 / turnover / coverage / 复杂度诊断
- **反馈闭环**：top 公式 + 结构化家族诊断回灌下一轮

### 4.4 QuantaAlpha / 东吴：初始种群与进化

- **初始 10 个独立互补假设** → 避免局部最优 + 因子拥挤（ diversity by construction）
- LLM 增强 GP：LLM 出金融逻辑 + 子表达式基因，GA 做高强度搜索；分岛进化 + 周期 LLM 注入 + 低相关筛选（81.6% 因子对相关 <0.70）

---

## 五、可落地到我们 BRAIN-native 系统的精确改造（连接 P1-A）

把"世坤顶级打法"翻译为 5 个可实施改动（已在 P1A_DIRECTION_AND_PLAN 细化）：

| 改动 | 对应顶级原则 | 具体做法 |
|---|---|---|
| **D 经济模板库** | ① 经济 Grounding + ② 多样性 | 8 个源自实战过检结构的骨架（均值回复/短期反转/质量-现金流/量价事件/低波动/动量/估值/横截面），以经济含义实例化而非纯替换 |
| **E BRAIN 结果反馈偏置** | ③ 评价反馈闭环 | 用 `candidate_submit_results.json` 的历史 IS sharpe 反哺采样（轻量实现 AlphaGen 的 IC reward，且用 BRAIN 真结果作 ground truth，规避"本地瞎判质量"陷阱） |
| **F 组合/自适应加权** | AlphaSAGE 自适应组合 + 实战复合 | 生成"多子信号 rank 相加"的复合因子（非单算子），必要时做低相关加权组合 |
| **G 家族多样性门控** | ② 多样性 + Hubble family-aware | 跟踪已生成因子的算子家族/字段族，惩罚拥挤模板，奖励欠覆盖家族 |
| **A/B/C 参数硬化** | 2.3 参数金标准 | truncation 0.01 置首、decay 4、rank 安全包裹、字段偏好（基本面优先，降权 anl4_* 分析师字段） |

---

## 六、必须直说的边界（诚实，不夸大）

1. **预测力根因在父池质量**：本地 10 个 `status=ACTIVE` 是幽灵数据（BRAIN 1100 条里不存在），生成器基于弱逻辑变异，天花板低。D/E/F/G 提升"结构性合规 + 多样性 + 有依据采样"，不保证瞬间冲到 Sharpe 1.5。
2. **AlphaBench 铁证**：无回测判质量接近随机 → 评价反馈必须用 BRAIN IS 真结果，E 改动的设计正基于此。
3. **完整 RL/LLM 训练与 BRAIN 约束冲突**：BRAIN 算子语言 + BRAIN 是唯一评估器 + 无本地数据 → 不能照搬 AlphaGen 全套，采纳其**原则**做轻量 BRAIN-native 落地（D/E/F/G + 已有 R3 护栏）。
4. **若实施后仍 0 提交**：根因转向"父池真实化 / 经济逻辑增强"专项，需另立（非 P1-A 单轮能解）。

---

## 七、源清单（顶级/官方，全部可追溯）

- Kakushadze Z. *101 Formulaic Alphas*. arXiv:1601.00991（世坤研究员，Wilmott 2016）— 奠基
- trung-vt/Fast-Expression-Documentation（GitHub，搬运 platform.worldquantbrain.com/learn/data-and-operators/operators）— 算子官方镜像
- compasty.netlify.app WorldQuant BRAIN tutorial（搬运官方 Fitness 公式/算子）— 模拟文档镜像
- CSDN lydeee / devpress（BRAIN Alpha 教程、中性化专章）— 实战镜像
- Darren Li (LinkedIn, BRAIN Challenge Gold) — 世坤顾问硬指标与正交哲学
- QuantGPT (ComeStart, GitHub) — 3 个 BRAIN 实提交 IS-PASS 因子表达式与业绩
- Yu et al. *AlphaGen* KDD 2023；Shi et al. *AlphaForge* 2025；Zhu & Zhu *AlphaQCM* 2025
- huy4ng/AlphaSAGE, arXiv:2509.25055（ICLR 2026）— SOTA
- Shi et al. *Hubble* arXiv:2604.09601（2026-03/04）— DSL+AST+正负RAG+family-aware
- QuantaAlpha arXiv:2602.07085（2026-02）— LLM+进化多智能体
- CogAlpha arXiv:2511.18850（ACL 2026 Oral）— 公式→代码+7层智能体
- 东吴证券《AI因子挖掘双路径》(2026-06) — LLM 增强遗传编程实证
