# BRAIN 提交阈值 · 交叉验证权威规范（Backend 实现唯一依据）

> 产出：Quant Researcher Agent 依《交叉验证宪法》Article I/II 联网交叉验证（2026-07-31）
>  supersedes 战略文档中 `sub≥0.75·√(sub/uni)·alpha_sharpe` 的旧写法（该公式已判不可信，见底部"已推翻"）
>  所有条目均 ≥2 独立来源；分歧项标「需 Tech Lead 仲裁」，禁止凭推测写死。

## 一、USA D1（Delay-1）提交硬性门槛（可直接写死）

| 检查项 | 阈值 | 来源 |
|---|---|---|
| Sharpe | ≥ 1.25 | zurie(译自官方 tutorial) / zread / LinkedIn(Gold) |
| Fitness | ≥ 1.0 | 同上 |
| Turnover | [1%, 70%] | 同上 |
| Max Weight（CONCENTRATED_WEIGHT） | < 10% | zurie(官方) / zread |
| Self-Correlation | < 0.7（**硬门控**，见仲裁2） | zurie(官方) / deepwiki |
| Returns（IS 附加） | ≥ 6.3%（年化） | zread |
| Sub-universe Sharpe | 见下方公式（D1/D0 不同） | Oo_Amy_oO / zread |

- Delay-0 门槛更高：Sharpe≥2.0、Fitness≥1.3（anweat 文档），本规范默认只覆盖 D1。
- 边界取值建议：`≥`（含边界），与官方 tutorial("1.25 or higher")一致。

## 二、Sub-universe Sharpe 正确公式（采用官方口径，丢弃 0.75 版）

```
# 绝对 Sharpe 下限 floor，非按 alpha_sharpe 缩放
import math
SQRT252 = math.sqrt(252)  # ≈15.87

def sub_universe_sharpe_threshold(sub_size, largest_universe_size, delay=1):
    coeff = 0.15 if delay == 1 else 0.25
    ratio = sub_size / largest_universe_size
    return SQRT252 * max(0.065, ratio * coeff)
```
- 适用：通用（各 region 子宇宙测试同构）；ratio=sub_size/largest_universe_size。
- 来源①：https://blog.csdn.net/Oo_Amy_oO/article/details/147725000
- 来源②：https://zread.ai/Miasyster/QuantGPT/14-wq-brain-simulation-and-submission

## 三、区域硬指标拦截清单（submit_gate 实现指令）

- **所有 region 默认套用上表 USA-D1 通用清单**（CONCENTRATED_WEIGHT、LOW_SUB_UNIVERSE_SHARPE 视为通用 IS 门控，直接拦截）。
- `region == CHINA`：标记"执行更高标准 + 额外测试"，具体额外项**待一手来源补齐**（官方仅确认"更严"，未给阈值）。
- `region == IND / TOP500`：**不要**假设比 USA 更严；**不要**实现 CLUSTER_TEST（无来源）。等 Tech Lead 提供官方提交标准说明页原文再补。

## 四、需 Tech Lead 仲裁的 4 项（严禁凭推测写死）

1. **0.75 系数公式**：仅 1 个"Planned"第三方仓库，与 2 独立来源冲突且结构错误 → 建议**丢弃**，采用第二节公式。
2. **self-corr 1.375 豁免规则**（"新 alpha Sharpe 比相似历史高 10% 可忽略 self-corr"）：仅 1 来源(gentlecactus)，被官方 tutorial 与 deepwiki 反证（官方立场 0.7 为硬限无例外）→ 建议**self-corr<0.7 做硬门控，不实现豁免**。
3. **CLUSTER_TEST 与 IND/TOP500 额外硬检查**：CLUSTER_TEST 无任一检索来源确认；IND/TOP500"比 USA 更严"未被证实（官方仅点名 China）→ 建议**不实现，待一手来源**。
4. **category coverage 是否明文门槛**：有逻辑合理性但无明文来源 → 建议作为**诊断指标展示，不强制拦截**。

## 五、PENDING 11 因子卡住的可能根因（研究侧诊断）

- 最可能是这 11 个因子彼此 / 与现存因子 **self-corr 或 prod-corr ≥ 0.7**（被判为"remix"而非新边缘），无法转 ACTIVE 计权（Gold 复盘 PnL corr<0.7；deepwiki prod/self corr≤0.7）。
- 其次可能是 category coverage 不足或 OS 表现不达标。
- **Backend/诊断层应显式输出每个因子的 `self_corr_max`、`prod_corr_max`、`os_sharpe`** 以定位（来源：deepwiki / LinkedIn Gold）。

## 附：已推翻的旧写法（勿再用）
- ❌ `sub_sharpe >= 0.75 * sqrt(sub_size/uni_size) * alpha_sharpe`（战略文档 §4 Q4 与记忆笔记中的旧引用）
- 推翻理由：单源"Planned"复刻仓库；与 Oo_Amy_oO / zread 冲突；结构错误（相对缩放 vs 绝对 floor），ratio=0.5、alpha_sharpe=1.25 时官方 floor≈1.19 vs 0.75版≈0.66，差近 2 倍。
- 来源：https://dafu-zhu.github.io/alpha-lab/reference/backtest.html（自身标注 Planned，非官方）
