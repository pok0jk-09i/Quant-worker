---
name: wq-alpha-research
description: "Use for WorldQuant BRAIN alpha research: designing WQ Alpha expressions, selecting fields/operators, diagnosing simulation and IS check failures, tuning Sharpe/Fitness/Turnover, submitting alphas, and building low-correlation alpha portfolios. Also use for 中文 requests about WorldQuant、BRAIN、WQ Alpha、因子表达式、回测、提交、换手、Fitness、Sharpe."
---

# WQ Alpha 研究 Skill

> 结构化 playbook：字段 → 表达式 → 回测 → 检查 → 提交 → 组合。融合 WorldQuant BRAIN 文档知识与 USA TOP3000 实证经验。

---

## 1. 快速决策树

```
开始
  ├── 拉取所有 alpha 列表 ──→ 只看 ACTIVE；算 **日收益** 相关，>0.7 则修改或放弃
  ├── 设计新因子
  │    ├── 字段已验证？ ──否──→ 查第 2 节（本地字段文件搜索 / 模拟 rank(field)）
  │    └── 是
  │         ├── 基本面 ──→ group_rank + ts_rank, SUBINDUSTRY, decay=0
  │         ├── 分析师 ──→ group_rank + ts_rank, INDUSTRY/SUBINDUSTRY, decay=0–4
  │         ├── 技术 ────→ 高 decay(10–30) 或混合基本面降低换手
  │         └── 情绪 ────→ nanHandling=ON, 小窗口谨慎
  └── 提交后 ──→ 验证 status == ACTIVE，否则检查 SELF_CORRELATION
```

---

## 2. 字段速查（本地数据集）

本 SKILL 已内置 USA TOP3000 delay=1 的完整字段列表（共 4367 个），无需每次从网页/ API 拉取：

- `references/wq_usa_top3000_delay1_data_fields.json`：完整字段元数据数组
- `references/wq_usa_top3000_delay1_data_fields.csv`：CSV 版，方便 Excel/ pandas 查看
- `references/wq_usa_top3000_delay1_data_fields_summary.json`：分类统计与示例字段

字段分布：

| 类别 | 数量 | 说明 |
|------|------|------|
| fundamental | 1652 | 财务报表、附注科目 |
| analyst | 1324 | 分析师预期、一致预期 |
| news | 996 | 新闻、财报事件 |
| pv | 195 | 价量、ADV、VWAP 等 |
| option | 138 | 期权隐含波动、Put/Call 等 |
| model | 40 | 模型因子 |
| socialmedia | 22 | 社交媒体情绪 |
| univ1 | 6 | Universe 相关 |

### 2.1 本地搜索字段

```python
import json
from pathlib import Path

# 假设在 skill 目录下运行；如在其他位置，改为实际路径
skill_dir = Path(".")
field_dir = skill_dir / "references"
data = json.loads((field_dir / "wq_usa_top3000_delay1_data_fields.json").read_text(encoding="utf-8"))

keyword = "operating_income"
matches = [
    f for f in data
    if keyword.lower() in f["id"].lower()
    or (f.get("description") and keyword.lower() in f["description"].lower())
]

for f in matches[:10]:
    print(f"{f['id']} | {f.get('category',{}).get('name')} | {f.get('dataset',{}).get('name')} | coverage={f.get('coverage')} | alphaCount={f.get('alphaCount')}")
```

### 2.2 按类别筛选

```python
category = "pv"  # 或 fundamental / analyst / news / option / model / socialmedia
fields = [f for f in data if f.get("category", {}).get("id") == category]
print(f"{category}: {len(fields)} fields")
for f in sorted(fields, key=lambda x: x.get("alphaCount", 0), reverse=True)[:10]:
    print(f"  {f['id']} | alphaCount={f.get('alphaCount')} | coverage={f.get('coverage')}")
```

### 2.3 字段验证

拿到候选字段后，**先用简单表达式模拟验证**字段是否真的可用：

```python
payload = {
    "type": "REGULAR",
    "settings": {
        "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
        "delay": 1, "decay": 0, "neutralization": "MARKET",
        "truncation": 0.08, "pasteurization": "ON", "unitHandling": "VERIFY",
        "nanHandling": "ON", "language": "FASTEXPR", "visualization": False,
    },
    "regular": "rank(my_candidate_field)",
}
resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
# 201 表示字段可用；非 201 通常表示字段不存在或参数不匹配
```

### 2.4 何时需要重新拉取

本地字段集已覆盖 USA TOP3000 delay=1。以下情况才需要重新从 BRAIN 拉取：

- 换 Region（如 CHN、EUR）
- 换 Universe（如 TOP500、TOP1000）
- 换 Delay（如 0）
- BRAIN 平台字段列表明显更新（可对比 `dateCreated` 与本地）

---

## 3. 运算符速查表

| 类型 | 算子 | 作用 |
|------|------|------|
| 截面 | `rank(x)`, `zscore(x)`, `normalize(x)`, `scale(x)`, `winsorize(x, std=4)` | 每天对所有股票标准化 |
| 时序 | `ts_mean`, `ts_std_dev`, `ts_delta`, `ts_rank`, `ts_corr`, `ts_decay_linear`, `ts_backfill`, `ts_zscore` | 单只股票历史窗口计算 |
| 分组 | `group_rank(x, group)`, `group_neutralize(x, group)`, `group_zscore(x, group)`, `group_backfill(x, group, N)` | 组内中性化 |
| 条件 | `if_else(cond, a, b)`, `trade_when(x, cond, delay)` | 条件暴露 |
| 向量 | `vec_avg(a, b, c)`, `vec_sum(a, b, c)` | 多字段逐元素平均/求和 |

**黄金组合**：`group_rank(ts_rank(signal, N), subindustry)`

---

## 4. 因子模板库

### 4.1 高胜率模板

```fastexpr
-- 模板 A：ROE 趋势（通过率最高）
group_rank(ts_rank(operating_income / equity, 126), subindustry)

-- 模板 B：EPS 收益率修正
group_rank(ts_rank(est_eps / close, 126), industry)

-- 模板 C：FCF 收益率
group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)

-- 模板 D：多因子混合（高 Fitness）
0.5 * group_rank(ts_rank(operating_income / equity, 126), subindustry)
+ 0.5 * group_rank(ts_rank(est_eps / close, 126), industry)

-- 模板 E：低相关技术+基本面混合
0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))

-- 模板 F：资产周转 × 利润率
rank(ts_rank(operating_income / sales * sales / assets, 126))
```

### 4.2 推荐默认设置

| 因子类型 | Decay | Neutralization | Truncation | nanHandling | 预期 TO |
|----------|-------|----------------|------------|-------------|---------|
| 基本面质量 | 0 | SUBINDUSTRY | 0.08 | ON | 2–8% |
| 分析师预期 | 0–4 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 9–16% |
| 技术反转 | 10–30 | INDUSTRY | 0.08 | OFF | 15–35% |
| 混合因子 | 4–20 | INDUSTRY/SUBINDUSTRY | 0.08 | ON | 10–20% |
| 情绪 | 4–10 | INDUSTRY | 0.05–0.08 | ON | 8–30% |

---

## 5. 指标与检查

### 5.1 核心指标

| 指标 | 公式/含义 | 目标 |
|------|-----------|------|
| Sharpe | 日 IR × √252 | ≥ 1.5（最低 1.3） |
| Fitness | Sharpe × √(|Returns| / max(TO, 0.125)) | ≥ 1.7（最低 1.5） |
| Returns | 年化收益 / $10M | ≥ 7% |
| Turnover | 日交易额 / Book Size | 1%–20% |
| Drawdown | 峰值到谷值最大回撤 | < 15% |
| Margin | PnL / 总交易额 | 越高越好 |

### 5.2 IS 检查清单

| 检查项 | 阈值 | 失败原因 | 修复方法 |
|--------|------|----------|----------|
| LOW_SHARPE | ≥ 1.25 | 信号弱 | 换字段/窗口/加 group_rank |
| LOW_FITNESS | ≥ 1.0 | 换手过高 | 增大 decay、混合稳定信号 |
| LOW_TURNOVER | ≥ 1% | 信号太稳定 | 缩短窗口、换更活跃字段 |
| HIGH_TURNOVER | ≤ 70% | 换手爆炸 | 增大 decay、trade_when、混合 |
| CONCENTRATED_WEIGHT | 单股 < 10% 且分散 | 权重集中 | 用 rank()、降低 truncation、ts_backfill |
| LOW_SUB_UNIVERSE_SHARPE | TOP1000 也有效 | 小票依赖 | 用基本面、SUBINDUSTRY、避免市值倾斜 |
| SELF_CORRELATION | **日收益** 相关系数 < 0.7 | 与已有因子太像 | 换信号簇、加过滤、换 Universe；不要只调参数 |
| MATCHES_COMPETITION | 信息性 | — | 无影响 |

### 5.3 失败统计（625 个实测）

| 失败原因 | 占比 | 结论 |
|----------|------|------|
| LOW_SHARPE | 90.7% | 信号质量是最大瓶颈 |
| LOW_FITNESS | 66.2% | 通常是 HIGH_TURNOVER 的软性版本 |
| LOW_SUB_UNIVERSE_SHARPE | 51.0% | 避免小票/流动性倾斜 |

**按数据类型通过率**：基本面 40% > 混合 12.7% > 纯技术 5.3% > 其他 0%

---

## 6. 问题诊断与修复

| 症状 | 可能原因 | 修复 |
|------|----------|------|
| Fitness < 1.0 | 换手 > 30% | 增大 decay、混合基本面、ts_decay_linear |
| Sharpe < 1.25 | 信号弱 | 拉长窗口、group_rank、换字段 |
| TO > 50% | 信号变化太快 | decay 10–30、trade_when、混合 |
| DD > 15% | 波动大/杠杆高 | 增大 decay、降 truncation、混合低波信号 |
| CONCENTRATED_WEIGHT FAIL | 稀疏/极值 | rank()、truncation 0.05、ts_backfill |
| Sub-Universe FAIL | 小票依赖 | 避免 `rank(-assets)`，用 group_rank、加流动性过滤 |
| simulation_error | 字段不存在/算子参数错误 | 先 rank(field) 验证字段，检查算子参数个数 |
| trade_when 零交易 | 条件过严 | 放宽条件或用 if_else |

---

## 7. BRAIN API 自动化

### 7.1 认证（请填写账号）

**使用前必须准备凭据**。推荐使用环境变量；也可以在本地放置未跟踪的 `credential.txt`（已被 `.gitignore` 忽略），内容为 JSON 数组：

```json
["your_username", "your_password"]
```

⚠️ **提醒**：不要把真实账号密码写入仓库。优先使用 `WQ_BRAIN_USERNAME` / `WQ_BRAIN_PASSWORD` 环境变量。

```python
import json
import requests
from requests.auth import HTTPBasicAuth

API_BASE = "https://api.worldquantbrain.com"

# 1. 读取 credential.txt
import os

username = os.getenv("WQ_BRAIN_USERNAME")
password = os.getenv("WQ_BRAIN_PASSWORD")
if not (username and password):
    with open("credential.txt") as f:
        username, password = json.load(f)

# 2. 创建会话并认证
session = requests.Session()
session.auth = HTTPBasicAuth(username, password)
session.headers.update({
    "Content-Type": "application/json",
    "Accept": "application/json",
})

resp = session.post(f"{API_BASE}/authentication")
assert resp.status_code == 201, f"认证失败: {resp.status_code} {resp.text}"
print("认证成功")
```

### 7.2 获取已提交 Alpha 并计算相关性

**目的**：在新因子提交前，避免与已有因子 PnL 高度相关（相关系数 ≥ 0.7）。

```python
import numpy as np

def fetch_pnl(session, alpha_id):
    """获取 Alpha 累计 PnL 序列；schema.properties 可能是 list 或 dict。"""
    r = session.get(f"{API_BASE}/alphas/{alpha_id}/recordsets/pnl")
    if r.status_code != 200 or not r.text.strip():
        return []
    data = r.json()
    props = data.get("schema", {}).get("properties", [])
    if isinstance(props, list):
        date_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() == "date"), 0)
        pnl_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() in ("pnl", "cum_pnl", "returns", "ret")), 1)
    else:
        date_idx = next((v["index"] for k, v in props.items() if k.lower() == "date"), 0)
        pnl_idx = next((v["index"] for k, v in props.items() if k.lower() in ("pnl", "cum_pnl", "returns", "ret")), 1)
    records = sorted(data.get("records", []), key=lambda r: r[date_idx])
    out = []
    for row in records:
        rec = row[0] if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list) else row
        try:
            out.append(float(rec[pnl_idx]))
        except Exception:
            continue
    return out

def daily_returns(cum_pnl):
    """累计 PnL 转日收益；相关性应基于日收益，而非累计曲线。"""
    return [cum_pnl[i+1] - cum_pnl[i] for i in range(len(cum_pnl) - 1)]

def get_active_alphas(session, user_id="self", limit=100):
    """获取所有 alpha（含 ACTIVE / UNSUBMITTED），分页。"""
    all_alphas = []
    offset = 0
    while True:
        data = session.get(f"{API_BASE}/users/{user_id}/alphas", params={"limit": limit, "offset": offset}).json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        all_alphas.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return all_alphas

# 计算新因子与所有 ACTIVE alpha 的日收益相关性
new_pnl = fetch_pnl(session, new_alpha_id)
new_ret = daily_returns(new_pnl)
existing = get_active_alphas(session)
active = [a for a in existing if a.get("status") == "ACTIVE"]

high_corr = []
for alpha in active:
    old_id = alpha.get("id")
    try:
        old_pnl = fetch_pnl(session, old_id)
        old_ret = daily_returns(old_pnl)
        if len(new_ret) == len(old_ret) and len(new_ret) > 20:
            corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
            print(f"与 {old_id} 日收益相关性: {corr:.3f}")
            if abs(corr) >= 0.7:
                high_corr.append((old_id, corr))
    except Exception:
        continue

if high_corr:
    print(f"⚠️ 发现 {len(high_corr)} 个高相关因子，建议修改或放弃")
```

**判断规则（基于日收益，不是累计 PnL）**：

| 相关系数 | 动作 |
|----------|------|
| abs(corr) < 0.5 | ✅ 可提交 |
| 0.5 ≤ abs(corr) < 0.7 | ⚠️ 谨慎，需提升 Sharpe 或修改信号 |
| abs(corr) ≥ 0.7 | ❌ 放弃或重构（除非新因子 Sharpe ≥ 旧因子 × 1.1） |

> ⚠️ **不要用累计 PnL 算相关**。累计曲线自带强趋势，会把不同信号的相关性严重夸大。

### 7.3 回测

```python
payload = {
    "type": "REGULAR",
    "settings": {
        "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
        "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY",
        "truncation": 0.08, "pasteurization": "ON", "unitHandling": "VERIFY",
        "nanHandling": "ON", "language": "FASTEXPR", "visualization": False,
    },
    "regular": "group_rank(ts_rank(operating_income/equity, 126), subindustry)",
}
resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
sim_id = resp.headers["Location"].rstrip("/").split("/")[-1]

while True:
    data = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}").json()
    if data.get("status") == "COMPLETE":
        alpha_id = data["alpha"]
        break
    time.sleep(8)

alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
```

### 7.4 提交与监控

```python
# 提交
sub = session.post(f"https://api.worldquantbrain.com/alphas/{alpha_id}/submit")
print(sub.status_code)  # 201 成功

# 监控 SELF_CORRELATION
for _ in range(30):
    alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
    sc = next((c for c in alpha.get("is", {}).get("checks", []) if c["name"] == "SELF_CORRELATION"), {})
    if sc.get("result") in ("PASS", "FAIL"):
        break
    time.sleep(60)
```

### 7.5 自动提交模板

```python
import numpy as np

def simulate_and_submit(expression, settings, existing_pnls=None):
    """
    existing_pnls: {alpha_id: [cum_pnl_values]}，已上线因子的累计 PnL 序列。
    返回: {"alpha_id": ..., "decision": "submitted|skip|high_corr|verify_failed", ...}
    """
    payload = {"type": "REGULAR", "settings": settings, "regular": expression}
    resp = session.post("https://api.worldquantbrain.com/simulations", json=payload)
    if resp.status_code != 201:
        return {"error": "simulate_failed"}
    sim_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    while True:
        data = session.get(f"https://api.worldquantbrain.com/simulations/{sim_id}").json()
        if data.get("status") == "COMPLETE":
            alpha_id = data["alpha"]
            break
        if data.get("status") in ("ERROR", "FAILED"):
            return {"error": "simulation_error"}
        time.sleep(8)
    alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
    is_ = alpha.get("is", {})

    # 1. 基础指标过滤
    if is_.get("fitness", 0) < 1.7 or is_.get("sharpe", 0) < 1.5 or is_.get("turnover", 1) > 0.20:
        return {"alpha_id": alpha_id, "decision": "skip", "reason": "metrics", "metrics": is_}

    # 2. 相关性检查（基于日收益）
    def daily_rets(cum):
        return [cum[i+1] - cum[i] for i in range(len(cum) - 1)]

    if existing_pnls:
        new_pnl = fetch_pnl(session, alpha_id)
        new_ret = daily_rets(new_pnl)
        for old_id, old_pnl in existing_pnls.items():
            old_ret = daily_rets(old_pnl)
            if len(new_ret) == len(old_ret) and len(new_ret) > 20:
                corr = abs(float(np.corrcoef(new_ret, old_ret)[0, 1]))
                if corr >= 0.7:
                    # 例外：新 Sharpe 高于旧 Sharpe 10% 以上可提交
                    old_sharpe = None  # 需从外部传入或缓存
                    if old_sharpe is None or is_.get("sharpe", 0) < old_sharpe * 1.1:
                        return {"alpha_id": alpha_id, "decision": "high_corr", "corr_with": old_id, "corr": corr}

    # 3. 提交
    sub = session.post(f"https://api.worldquantbrain.com/alphas/{alpha_id}/submit")
    if sub.status_code not in (200, 201):
        return {"alpha_id": alpha_id, "decision": "submit_failed", "status": sub.status_code}

    # 4. 验证是否真正上线（BRAIN 可能因 SELF_CORRELATION 保持 UNSUBMITTED）
    for _ in range(20):
        time.sleep(10)
        alpha = session.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}").json()
        if alpha.get("status") == "ACTIVE":
            return {"alpha_id": alpha_id, "decision": "submitted", "status": "ACTIVE"}
        sc = next((c for c in alpha.get("is", {}).get("checks", []) if c["name"] == "SELF_CORRELATION"), {})
        if sc.get("result") == "FAIL":
            return {"alpha_id": alpha_id, "decision": "self_correlation_fail", "status": alpha.get("status")}

    return {"alpha_id": alpha_id, "decision": "verify_failed", "status": alpha.get("status")}
```

### 7.6 限流

- 模拟/提交间 sleep 2–5 秒。
- 遇 429 读取 `Retry-After`，指数退避。
- 批量建议单线程或 ≤ 2 并发。

### 7.7 提交后验证（201 ≠ 已上线）

`POST /alphas/{id}/submit` 返回 201 只表示请求被接受，**不代表 alpha 已变为 ACTIVE**。实战中常见：

- alpha 状态仍为 `UNSUBMITTED`（SELF_CORRELATION 未通过或审核中）。
- 同一信号换参数生成的新 alpha被系统判定为重复，无法真正提交。

**必须二次确认**：

```python
alpha = session.get(f"{API_BASE}/alphas/{alpha_id}").json()
print(alpha.get("status"))  # ACTIVE 才算真正提交成功

# 如果 status == UNSUBMITTED，查看 checks 中 SELF_CORRELATION 结果
for c in alpha.get("is", {}).get("checks", []):
    print(c["name"], c.get("result"), c.get("value"))
```

**获取全部 alpha 并统计 ACTIVE 数量**：

```python
def get_all_alphas(session, limit=100):
    all_alphas = []
    offset = 0
    while True:
        data = session.get(f"{API_BASE}/users/self/alphas", params={"limit": limit, "offset": offset}).json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        all_alphas.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return all_alphas

all_alphas = get_all_alphas(session)
active = [a for a in all_alphas if a.get("status") == "ACTIVE"]
print(f"total={len(all_alphas)}, ACTIVE={len(active)}")
```

---

## 8. 组合构建规则

### 8.1  diversified 组合示例

| 簇 | 代表表达式 |
|----|------------|
| 盈利能力 | `group_rank(ts_rank(operating_income/equity, 126), subindustry)` |
| 分析师 | `group_rank(ts_rank(est_eps/close, 252), subindustry)` |
| FCF | `group_rank(ts_rank(free_cash_flow_reported_value/equity, 126), industry)` |
| 低相关混合 | `0.5*rank(-(close/open-1)) + 0.5*rank(ts_rank(operating_income/equity, 126))` |
| 质量组合 | `0.5*group_rank(ts_rank(oi/equity,126),subindustry) + 0.5*group_rank(ts_rank(est_eps/close,126),industry)` |

### 8.2 提交优先级

1. 高 Fitness（≥ 1.5）且低 TO（< 15%）
2. 来自不同信号簇
3. 若 SELF_CORRELATION 冲突，保留高 Fitness 版本

### 8.3 相关性的真相

对 ACTIVE alpha 的日收益做相关分析，发现：

- **同一信号簇内相关性极高**：
  - 两个 open-close 反转 + OI/Equity 混合（权重不同）日收益相关 **0.84**
  - 两个分析师 EPS 相关 **0.74**
  - 两个杠杆/质量因子（`-equity/assets` vs `liabilities/assets`）相关 **0.84**
- **跨簇也不一定能分散**：基于 `scl12_buzz` 的情绪 alpha 与基于 `est_eps/close` 的分析师 alpha 相关仍达 **0.59–0.67**。
- **累计 PnL 相关性严重失真**： alpha 的累计 PnL 两两相关普遍 **> 0.90**，容易让人误以为所有因子都一样。

**结论**：

- 换窗口、换权重、换 neutralization **不能创造真正的低相关**。
- 真正的低相关来自 **完全不同的数据来源或经济逻辑**（如：宏观事件、期权流、跨境、另类数据）。
- 在常规 USA TOP3000 基本面/价量/分析师池子里，"低相关" 往往是 **0.3–0.6 的日收益相关**，不要追求 0。

---

## 9. 提交前 Checklist

- [ ] 已获取 **所有** alpha 列表（含 ACTIVE / UNSUBMITTED），不只是本次模拟
- [ ] 新因子与已有 ACTIVE alpha **日收益** 相关性 < 0.7（或新 Sharpe ≥ 旧 Sharpe × 1.1）
- [ ] 相关性基于 **日收益** 计算，不是累计 PnL
- [ ] 字段已验证
- [ ] 模拟无报错
- [ ] Sharpe ≥ 1.3（理想 ≥ 1.5）
- [ ] Fitness ≥ 1.1
- [ ] Turnover 1%–20%（可放宽至 ≤ 35%）
- [ ] Drawdown < 15%
- [ ] 所有 IS 检查 PASS
- [ ] 多空数量合理
- [ ] 提交后 **再次确认 status == ACTIVE**，201 不代表上线

---

## 10. 核心经验（一句话版）

1. **先生成因子前先拉取所有 ACTIVE alpha 的 PnL**，避免高相关重复。
2. **相关性必须算日收益**，累计 PnL 相关会把所有因子看成同一个。
3. **201 响应 ≠ 提交成功**：提交后必须确认 `status == ACTIVE`。
4. **基本面 > 混合 > 技术**：`operating_income/equity`、`est_eps/close`、`free_cash_flow_reported_value/equity` 是最稳起点。
5. **group_rank + ts_rank 是黄金组合**。
6. **SUBINDUSTRY 中性化通过率最高**。
7. **Decay 是控制换手的主杠杆**：基本面 0，技术 10–30。
8. **50/50 正交混合能降低换手，但未必能降低相关**；相关靠信号来源，不靠权重。
9. **字段先验证**，无效字段秒级报错。
10. **USA TOP3000 里真正的低相关很难做**；同一数据池的 "不同" 表达式往往高度相关。

---

## 11. 自进化机制

每次与 BRAIN 交互（提交、查询、分析）后，AI 应把新发现写回本 SKILL，使其随实战经验持续进化。

### 11.1 触发条件

以下任一情况发生后，运行一次 `scripts/evolve_skill.py`：

- 提交了一个或多个新 alpha
- 批量回测了一批 alpha
- 查询了 alpha 状态并发现变化（如 UNSUBMITTED → ACTIVE，或被拒绝）
- 发现了新的字段可用性/失效模式

### 11.2 运行方式

**前提**：设置 `WQ_BRAIN_USERNAME` / `WQ_BRAIN_PASSWORD`，或在 skill 目录下放置未跟踪的 `credential.txt`，内容为 BRAIN 账号密码 JSON 数组：

```json
["your_username", "your_password"]
```

```bash
# 1. 预览：生成建议追加的 markdown 片段，不修改任何文件
pyenv exec python scripts/evolve_skill.py

# 2. 提交：追加到 SKILL.md 并更新 alpha_db.json
pyenv exec python scripts/evolve_skill.py --apply
```

> 注意：**不带 `--apply` 的预览模式不会修改 `alpha_db.json` 和 `SKILL.md`**，你可以先审查再提交。脚本仅依赖 `requests` 和 `numpy`，**不需要 `wq-bus` 项目代码**。数据文件已随 SKILL 分发。

脚本会：

1. 拉取 `/users/self/alphas`（分页）获取全部 alpha。
2. 与本地 `alpha_db.json` 对比，找出 **新增** 或 **状态/指标变化** 的 alpha。
3. 对新 alpha 抓取 `recordsets/pnl`，计算与已有 ACTIVE alpha 的 **日收益相关性**。
4. 自动生成经验条目（指标评价 + 相关评价 + 表达式摘要）。
5. 第一次运行输出**批量快照**；后续运行输出**增量条目**。
6. `--apply` 模式下把条目追加到 `## 12. 实证记录（自动更新）`，并保存本地 `alpha_db.json`。

### 11.3 AI 应如何整理经验

脚本输出后，AI 需要**人工判断**哪些条目值得永久写入 SKILL：

- **保留**：高 Fitness 低换手的成功案例、新的低相关信号簇、意外的失败模式。
- **精简**：大量重复的同一信号簇条目应合并为一句话规律。
- **更新模板/阈值**：如果多次发现某个字段/模板失效，应回到第 4、5、6 节更新。

### 11.4 数据结构

- `alpha_db.json`：本地 alpha 快照库，包含状态、指标、表达式、PnL。该文件会包含个人研究记录，默认被 `.gitignore` 忽略，不应提交到公开仓库。
- `SKILL.md`：最终人类可读 playbook，第 12 节只保留脱敏后的通用经验。

## 12. 实证记录（自动更新）

> 本节仅保留机制说明。真实运行生成的 alpha ID、表达式、PnL、提交状态和相关性记录可能关联个人账号与研究资产，默认写入本地 `alpha_db.json`，不随仓库发布。
> 若需要沉淀通用经验，请人工汇总成脱敏规则后再写回第 4、5、6、8、10 节。

### 2026-07-06 09:58 UTC — 批量初始化快照

- 总 alpha：9997 | ACTIVE：10 | 非 ACTIVE：9987
- 信号簇分布：{'technical': 5603, 'other': 4242, 'cashflow': 126, 'sentiment': 23, 'analyst': 3}

**ACTIVE 高 Fitness Top 5**：
- `wpRZaR3d` (other): Sharpe=2.39, Fitness=1.92, TO=0.165 — `0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- `3qEmG50X` (technical): Sharpe=1.32, Fitness=1.88, TO=0.053 — `trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- `A1OQNXKd` (technical): Sharpe=1.62, Fitness=1.85, TO=0.029 — `trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- `gJ1b92Xm` (analyst): Sharpe=2.11, Fitness=1.68, TO=0.161 — `group_rank(ts_rank(est_eps / close, 126), industry)`
- `RRpNP0dn` (other): Sharpe=1.67, Fitness=1.52, TO=0.026 — `inverse(ts_backfill(book_leverage_ratio_3, 120))`

**ACTIVE 中日收益高相关对**：无 ≥ 0.7 的对（或 PnL 不足）

**明显失效信号（Fitness < 0.5，共 4209 个）**：
- 簇分布：{'other': 3667, 'technical': 404, 'cashflow': 122, 'sentiment': 15, 'analyst': 1}

**高换手（TO > 50%，共 262 个）**：
- 簇分布：{'other': 214, 'technical': 38, 'sentiment': 6, 'cashflow': 4}

---


### 2026-07-06 09:59 UTC — 批量初始化快照

- 总 alpha：9997 | ACTIVE：10 | 非 ACTIVE：9987
- 信号簇分布：{'technical': 5603, 'other': 4242, 'cashflow': 126, 'sentiment': 23, 'analyst': 3}

**ACTIVE 高 Fitness Top 5**：
- `wpRZaR3d` (other): Sharpe=2.39, Fitness=1.92, TO=0.165 — `0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- `3qEmG50X` (technical): Sharpe=1.32, Fitness=1.88, TO=0.053 — `trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- `A1OQNXKd` (technical): Sharpe=1.62, Fitness=1.85, TO=0.029 — `trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- `gJ1b92Xm` (analyst): Sharpe=2.11, Fitness=1.68, TO=0.161 — `group_rank(ts_rank(est_eps / close, 126), industry)`
- `RRpNP0dn` (other): Sharpe=1.67, Fitness=1.52, TO=0.026 — `inverse(ts_backfill(book_leverage_ratio_3, 120))`

**ACTIVE 中日收益高相关对**：无 ≥ 0.7 的对（或 PnL 不足）

**明显失效信号（Fitness < 0.5，共 4209 个）**：
- 簇分布：{'other': 3667, 'technical': 404, 'cashflow': 122, 'sentiment': 15, 'analyst': 1}

**高换手（TO > 50%，共 262 个）**：
- 簇分布：{'other': 214, 'technical': 38, 'sentiment': 6, 'cashflow': 4}

---


### 2026-07-06 15:15 UTC

- **d508gPpE** (UNSUBMITTED, other): Sharpe=0.63, Fitness=0.33, TO=0.0277, DD=0.2222。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **9qrPbbgK** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.35, TO=0.0308, DD=0.2217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **QPVrrWjK** (UNSUBMITTED, technical): Sharpe=-1.6, Fitness=-0.65, TO=0.6315, DD=1.0516。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 5)), divide(ts_std_dev(close, 20), sqrt(abs(zscore(volume))))))`
- **YP0wX1jM** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.92, TO=0.0115, DD=0.6558。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **omlwQq7k** (UNSUBMITTED, technical): Sharpe=-2.9, Fitness=-1.18, TO=0.7815, DD=1.3488。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(ts_rank(close, 20), 5), industry), multiply(zscore(volume), ts_std_dev(close, 2...`
- **QPVrmmJQ** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.18, TO=0.0128, DD=0.1719。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **O0ZwK17d** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.25, TO=0.0212, DD=0.2467。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **xAkwabVp** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **VkPwo6a0** (UNSUBMITTED, sentiment): Sharpe=0.03, Fitness=0.0, TO=0.2459, DD=0.236。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_alphadecay, ts_mean(anl46_sentiment, 10)))`
- **d508wnNg** (UNSUBMITTED, other): Sharpe=0.29, Fitness=0.12, TO=0.0648, DD=0.1192。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(annual_total_revenue, ts_rank(annual_total_assets_value, 30)))`
- **2rLqknYb** (UNSUBMITTED, technical): Sharpe=-0.46, Fitness=-0.09, TO=0.6053, DD=0.3678。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_rank(ts_delta(close, 5), 20) * rank(volume), sector))`
- **58O7VVzn** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.09, TO=0.0114, DD=0.1427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, ts_rank(ts_mean(add(annual_revenue_value, annual_total_assets_value), 20), 30)))`
- **RR8ZLn81** (UNSUBMITTED, sentiment): Sharpe=0.46, Fitness=0.2, TO=0.0794, DD=0.0905。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_std_dev(log(anl46_sentiment), 50), 20), 60))`
- **rKl6mgrd** (UNSUBMITTED, other): Sharpe=-1.0, Fitness=-0.54, TO=0.1373, DD=0.4966。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(log(abs(multiply(accounts_receivable_trade_current, accounts_payable_total_current))), 50))`
- **akn2v052** (UNSUBMITTED, technical): Sharpe=-1.15, Fitness=-0.19, TO=1.0378, DD=0.2996。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(group_zscore(ts_delta(close, 5), industry), zscore(ts_rank(volume, 20))))`
- **akn2v8Yw** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **qMlkqGAO** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.07, TO=0.7935, DD=0.1794。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(log(ts_rank(rank(accounts_receivable_current_assets), 20)))`
- **KP9YjZqk** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.13, TO=0.0847, DD=0.1127。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(rank(daily_volume_to_shares_outstanding), ts_mean(subtract(rank(current_enterprise_value), rank(annual_...`
- **KP9YjZ0N** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0175, DD=0.4584。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_receivable_trade_current, ts_rank(ts_rank(ts_rank(accounts_receivable_trade_current, 100), 100), 50)))`
- **E5E0XpYK** (UNSUBMITTED, analyst): Sharpe=1.41, Fitness=0.93, TO=0.0806, DD=0.052。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **MPQlRoxn** (UNSUBMITTED, analyst): Sharpe=1.57, Fitness=1.1, TO=0.1118, DD=0.0466。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **zqmwM9PX** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.07, TO=0.2084, DD=0.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **9qrPvzvV** (UNSUBMITTED, analyst): Sharpe=1.69, Fitness=1.14, TO=0.1522, DD=0.0464。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **XgnwGAbl** (UNSUBMITTED, analyst): Sharpe=0.65, Fitness=0.95, TO=0.0847, DD=0.6924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **781q7xV2** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **vRlnw9xa** (UNSUBMITTED, analyst): Sharpe=1.71, Fitness=1.01, TO=0.1638, DD=0.0465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **xAkwOg9J** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.1634, DD=0.4605。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(annual_total_revenue, ts_rank(ts_rank(rank(annual_total_assets_value), 30), 100)))`
- **9qrPqM71** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.09, TO=0.0118, DD=0.1428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_revenue_value, multiply(ts_rank(subtract(annual_total_revenue, annual_total_assets_value), 5), 5)))`
- **KP9YP7gz** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **RR8ZRNNz** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0258, DD=0.4656。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(log(annual_total_revenue), ts_rank(multiply(annual_net_income_incl_extraordinary, annual_total_assets_v...`
- **rKl61Mj8** (UNSUBMITTED, technical): Sharpe=-3.86, Fitness=-3.52, TO=0.51, DD=4.1383。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(ts_rank(volume, 20), group_neutralize(zscore(divide(close, ts_mean(close, 20))), industry)))`
- **QPVr1W6p** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.16, TO=0.0553, DD=0.0996。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(cash_per_share, ts_rank(annual_total_revenue, 50)))`
- **e708l93M** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.1659, DD=0.2638。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(annual_total_revenue * reverse(ts_rank(ts_mean(rank(annual_total_revenue), 50), 10)))`
- **KP9YKbNp** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.09, TO=0.0116, DD=0.1428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_revenue_value, subtract(rank(annual_total_assets_value), ts_rank(abs(annual_total_liabilities_value),...`
- **omlw13Wl** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.07, TO=0.1396, DD=0.1534。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(ts_rank(annual_total_revenue, 30), ts_rank(annual_total_liabilities_value, 100)))`
- **58O7Z77z** (UNSUBMITTED, other): Sharpe=-1.18, Fitness=-0.77, TO=0.1382, DD=0.6957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(log(divide(accounts_receivable_trade_current, ts_rank(ts_mean(rank(accounts_receivable_trade_current), 10), 50))))`
- **qMleQQnv** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.03, TO=0.0132, DD=0.2907。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(annual_total_revenue, subtract(annual_total_assets_value, multiply(annual_total_liabilities_value, add(...`
- **zqmXlE3X** (UNSUBMITTED, sentiment): Sharpe=0.8, Fitness=0.31, TO=0.2727, DD=0.0608。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(rank(anl46_sentiment), 100))`
- **gJM7nZ7m** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.11, TO=0.0237, DD=0.1056。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **QPVmwqoX** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.05, TO=0.8488, DD=0.1544。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(volume, 20), industry), ts_std_dev(ts_delta(close, 5), 20)))`
- **9qrgNQm2** (UNSUBMITTED, other): Sharpe=1.31, Fitness=0.38, TO=0.6163, DD=0.0432。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_zscore(ts_delta(close, 5), sector), zscore(ts_std_dev(close, 20))))`
- **xAkXJ6jn** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0229, DD=0.1077。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **aknXpG22** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0232, DD=0.1066。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **E5Eojdxm** (UNSUBMITTED, technical): Sharpe=-1.32, Fitness=-0.5, TO=0.611, DD=0.8807。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(close, 5), sector), divide(ts_std_dev(close, 20), rank(volume))))`
- **0mEnVVwr** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.13, TO=0.0241, DD=0.1045。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **blq7mMPr** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.06, TO=1.109, DD=0.0646。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(close, 20), zscore(ts_delta(volume, 5))), industry))`
- **N1rkE2oo** (UNSUBMITTED, technical): Sharpe=-0.63, Fitness=-0.15, TO=0.2492, DD=0.1636。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_corr(rank(log(volume)), rank(ts_delta(close, 5)), 20), industry))`
- **RR80xakn** (UNSUBMITTED, cashflow): Sharpe=0.5, Fitness=0.27, TO=0.008, DD=0.1707。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(annual_net_income_value + ts_rank(cashflow_op / ts_mean(assets, 10), 10))`
- **qMle2bNj** (UNSUBMITTED, other): Sharpe=-0.18, Fitness=-0.06, TO=0.0101, DD=0.4005。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_receivable_current_assets, ts_mean(rank(multiply(assets, cash)), 20)))`
- **2rLPVk6J** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.12, TO=0.0246, DD=0.1038。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **KP9xAPdN** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.09, TO=0.0115, DD=0.1437。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_revenue_value, ts_rank(ts_mean(add(annual_revenue_per_share, cash_per_share), 20), 30)))`
- **0mEn2aP8** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7119。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **VkPKbmmG** (UNSUBMITTED, technical): Sharpe=-4.41, Fitness=-3.62, TO=0.3938, DD=2.629。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(ts_delta(close, 5), 20), zscore(divide(ts_std_dev(volume, 20), ts_mean(volume,...`
- **WjGK2l8x** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.06, TO=0.0562, DD=0.1527。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(annual_total_revenue, ts_rank(annual_total_assets_value, 50)))`
- **mLbeWbxK** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.09, TO=0.0144, DD=0.1853。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **j20NKg0o** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.11, TO=0.0073, DD=0.264。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(assets, ts_mean(multiply(cash, cash_st), 20)))`
- **xAkXp02l** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.04, TO=0.0318, DD=0.3688。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(log(accounts_receivable_trade_current), divide(rank(accrued_expenses_4), ts_mean(rank(accounts_payable_total...`
- **GrLE5PGo** (UNSUBMITTED, other): Sharpe=-1.66, Fitness=-0.7, TO=0.5772, DD=1.027。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_zscore(zscore(ts_delta(close, 5)), industry), sqrt(ts_std_dev(close, 20))))`
- **RR80oKan** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0248, DD=0.4961。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(log(abs(add(subtract(accounts_payable_current_3, ts_mean(accounts_receivable_trade_current, 30)), accounts_recei...`
- **MPQ9n00k** (UNSUBMITTED, technical): Sharpe=-0.39, Fitness=-0.05, TO=0.5737, DD=0.1371。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(log(abs(divide(ts_delta(close, 5), ts_std_dev(close, 20)))), 10), zscore(ts_co...`
- **WjGKR6eQ** (UNSUBMITTED, technical): Sharpe=-2.79, Fitness=-1.71, TO=0.3022, DD=1.1301。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_zscore(ts_corr(rank(returns), rank(volume), 20), sector), ts_std_dev(close, 20)))`
- **RR80vOod** (UNSUBMITTED, technical): Sharpe=1.29, Fitness=1.18, TO=0.0217, DD=0.1152。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **rKlQng13** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=1.27, TO=0.0513, DD=0.3152。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **O0ZKg2M7** (UNSUBMITTED, technical): Sharpe=-0.59, Fitness=-0.11, TO=0.7273, DD=0.35。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(close, 5), sector), divide(ts_std_dev(close, 20), multiply(abs(ts_delta(volume,...`
- **9qrgkJWx** (UNSUBMITTED, technical): Sharpe=-1.53, Fitness=-0.59, TO=0.6279, DD=0.9576。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 5)), multiply(ts_std_dev(close, 20), sqrt(abs(zscore(volume))))))`
- **XgnXMEK5** (UNSUBMITTED, technical): Sharpe=-0.15, Fitness=-0.04, TO=0.0481, DD=0.1968。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(ts_mean(zscore(log(volume)), 20), ts_std_dev(zscore(close), 20)))`
- **omlQrGLn** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.33, TO=0.0452, DD=0.3158。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **9qrgmXnV** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.15, TO=0.049, DD=0.2942。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **d50eojbv** (UNSUBMITTED, other): Sharpe=-1.4, Fitness=-0.6, TO=0.6027, DD=1.1074。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(ts_delta(close, 5), sqrt(ts_mean(multiply(abs(ts_delta(close, 1)), abs(ts_delta(close, 1))), 20))))`
- **LL1Or7W2** (UNSUBMITTED, technical): Sharpe=-1.77, Fitness=-0.69, TO=0.5479, DD=0.8385。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(divide(ts_mean(volume, 20), ts_std_dev(volume, 20)), 10), ts_rank(divide(ts_co...`
- **vRla68Gb** (UNSUBMITTED, sentiment): Sharpe=-0.08, Fitness=-0.01, TO=0.2192, DD=0.1914。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(anl46_alphadecay, subtract(ts_rank(anl46_sentiment, 20), rank(add(anl46_indicator, anl46_performancepercenti...`
- **N1rkzO08** (UNSUBMITTED, technical): Sharpe=-3.74, Fitness=-2.14, TO=0.8753, DD=2.8317。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(close, 10), zscore(divide(volume, ts_mean(volume, 20)))), industry))`
- **58ON5v8M** (UNSUBMITTED, technical): Sharpe=-5.26, Fitness=-2.93, TO=1.2849, DD=3.8419。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(returns, 5), sector), multiply(ts_std_dev(returns, 20), sqrt(abs(ts_corr(close,...`
- **QPVmzmmg** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0263, DD=0.4954。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(abs(subtract(accounts_receivable_trade_current, accounts_payable_total_current)))`
- **blq7reoK** (UNSUBMITTED, technical): Sharpe=1.14, Fitness=1.31, TO=0.0474, DD=0.315。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **9qrgdnY9** (UNSUBMITTED, technical): Sharpe=-1.96, Fitness=-0.78, TO=0.5851, DD=0.9567。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(ts_delta(close, 5)), industry), sqrt(abs(ts_std_dev(volume, 20)))))`
- **6X9goNWK** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.16, TO=0.1932, DD=0.0633。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_corr(rank(close), rank(ts_mean(volume, 20)), 20), sector))`
- **wplX2OWY** (UNSUBMITTED, other): Sharpe=-3.03, Fitness=-1.53, TO=0.4121, DD=1.031。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(subtract(accounts_receivable_trade_current, rank(ts_rank(rank(accounts_receivable_trade_current), 100)))...`
- **aknXe5Kv** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.63, TO=0.0283, DD=0.3656。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **WjGK3Z5o** (UNSUBMITTED, technical): Sharpe=-0.33, Fitness=-0.06, TO=0.47, DD=0.1855。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(group_neutralize(zscore(ts_corr(rank(returns), rank(volume), 20)), subindustry), ts_rank(ts_delta(close...`
- **mLbeKrjK** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=1.18, TO=0.0519, DD=0.3127。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **wplXoVk2** (UNSUBMITTED, technical): Sharpe=1.08, Fitness=1.22, TO=0.0544, DD=0.3122。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **A1Pqxj3X** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.67, TO=0.0364, DD=0.437。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **lelJAwlx** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.2, TO=0.0564, DD=0.3153。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **RR80Erdd** (UNSUBMITTED, technical): Sharpe=-5.09, Fitness=-4.38, TO=0.5341, DD=3.822。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_zscore(ts_delta(close, 5), subindustry), ts_std_dev(volume, 20)))`
- **2rLPAJkw** (UNSUBMITTED, technical): Sharpe=0.33, Fitness=0.04, TO=0.7568, DD=0.0807。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 5)), multiply(ts_std_dev(close, 20), group_neutralize(rank(volume), industry))))`
- **blq78mAZ** (UNSUBMITTED, technical): Sharpe=-0.56, Fitness=-0.1, TO=0.5364, DD=0.2095。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(volume, 20), zscore(ts_corr(close, volume, 20))), industry))`
- **d50eK6bx** (UNSUBMITTED, other): Sharpe=-1.48, Fitness=-1.21, TO=0.047, DD=0.8731。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(actual_update_flag_bps, rank(subtract(accrued_expenses_4, multiply(rank(divide(accounts_receivable_trad...`
- **RR80Av7z** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.03, TO=0.126, DD=0.157。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(ts_rank(annual_total_revenue, 30), ts_rank(annual_normalized_net_income, 30)))`
- **E5EoVVe9** (UNSUBMITTED, technical): Sharpe=-4.23, Fitness=-3.65, TO=0.5605, DD=4.0408。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(ts_delta(close, 5)), industry), divide(ts_std_dev(close, 20), sqrt(abs(ts_mean(vo...`
- **N1rkeepq** (UNSUBMITTED, technical): Sharpe=-3.88, Fitness=-2.34, TO=0.8268, DD=2.9674。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(ts_delta(close, 10), 20), zscore(divide(volume, ts_mean(volume, 20)))) , indus...`
- **LL1O5gOn** (UNSUBMITTED, other): Sharpe=-1.32, Fitness=-0.39, TO=0.8247, DD=0.7892。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(ts_rank(ts_delta(close, 5), 20), divide(ts_std_dev(close, 20), multiply(abs(ts_delta(close, 5)), 1))))`
- **LL1O5XAe** (UNSUBMITTED, cashflow): Sharpe=0.75, Fitness=0.46, TO=0.016, DD=0.1335。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(cashflow_op, ts_rank(rank(assets), 50)))`
- **E5EoRjdL** (UNSUBMITTED, other): Sharpe=-1.64, Fitness=-0.88, TO=0.2774, DD=0.8088。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(rank(accounts_receivable_trade_current), 20), 5))`
- **9qrgWek1** (UNSUBMITTED, technical): Sharpe=-0.14, Fitness=-0.01, TO=0.7376, DD=0.1044。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_rank(ts_corr(rank(close), rank(volume), 20), 5), sector))`
- **A1Pqvp0l** (UNSUBMITTED, technical): Sharpe=0.08, Fitness=0.0, TO=1.0774, DD=0.2188。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_zscore(ts_rank(volume, 20), industry), multiply(zscore(ts_delta(close, 5)), ts_std_dev(returns, 20))))`
- **zqmXbEoo** (UNSUBMITTED, sentiment): Sharpe=0.09, Fitness=0.03, TO=0.1216, DD=0.3921。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(log(anl46_sentiment), 50), 100))`
- **P03jg7LE** (UNSUBMITTED, sentiment): Sharpe=0.83, Fitness=0.38, TO=0.2002, DD=0.0787。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_zscore(anl46_sentiment, 50), 5), 50))`
- **e70eQdVJ** (UNSUBMITTED, other): Sharpe=-0.63, Fitness=-0.31, TO=0.0946, DD=0.3713。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(actual_update_flag_bps, ts_rank(ts_mean(ts_rank(actual_update_flag_ebi, 100), 100), 50)))`
- **E5EoRWzR** (UNSUBMITTED, other): Sharpe=2.09, Fitness=1.26, TO=0.2241, DD=0.039。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **88Qg3wQo** (UNSUBMITTED, other): Sharpe=2.16, Fitness=1.1, TO=0.3828, DD=0.0422。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **3qRg9vWO** (UNSUBMITTED, other): Sharpe=-4.34, Fitness=-3.21, TO=0.5563, DD=2.9473。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(zscore(multiply(ts_rank(ts_delta(close, 5), 10), ts_rank(ts_std_dev(close, 20), 20))), industry))`
- **3qRg90QX** (UNSUBMITTED, technical): Sharpe=2.25, Fitness=0.49, TO=1.1207, DD=0.0344。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_rank(zscore(log(volume)), 20), industry))`
- **QPVm7gnr** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0128, DD=0.4595。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_total_revenue, multiply(rank(annual_net_income_incl_extraordinary), ts_rank(annual_earnings_before_ta...`
- **JjOR7x2E** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.05, TO=0.0146, DD=0.4684。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_payable_current_3, rank(divide(accounts_receivable_gross_4, accounts_receivable_trade_current))))`
- **GrLEl09o** (UNSUBMITTED, other): Sharpe=-2.81, Fitness=-1.5, TO=0.3912, DD=1.1099。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(ts_rank(rank(available_for_sale_investments * accounts_payable_current_3), 50), 30))`
- **blq7j77l** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.3433, DD=0.4615。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_alphadecay, ts_mean(anl46_experts, 10)))`
- **1Yd6prkz** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.91, TO=0.0477, DD=0.6879。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **2rLPpjXw** (UNSUBMITTED, other): Sharpe=1.57, Fitness=1.09, TO=0.1723, DD=0.0599。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **O0ZKGbOg** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.05, TO=0.1267, DD=0.1836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_delta(annual_total_revenue, 20), 20), 20))`
- **A1PqGaLl** (UNSUBMITTED, other): Sharpe=2.1, Fitness=1.33, TO=0.1634, DD=0.0409。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **1Yd6pYqz** (UNSUBMITTED, technical): Sharpe=-0.07, Fitness=-0.01, TO=0.3495, DD=0.2168。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(ts_mean(close,20),5), industry), divide(ts_std_dev(close,20), abs(ts_delta(volu...`
- **3qRgePYO** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.08, TO=0.3183, DD=0.1585。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_revenue_value, ts_mean(annual_total_revenue, 10)))`
- **781gnNX1** (UNSUBMITTED, other): Sharpe=-1.27, Fitness=-0.72, TO=0.2116, DD=0.7543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(anl46_alphadecay, ts_rank(rank(anl46_experts), 100)))`
- **1Yd6zxaR** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.09, TO=0.0824, DD=0.5195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(accounts_receivable_trade_current, ts_rank(multiply(accrued_expenses_4, ts_mean(multiply(accounts_payab...`
- **ZYnkK61Z** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.06, TO=0.4715, DD=0.0682。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_rank(ts_rank(annual_total_revenue, 10), 10), 30)`
- **2rLPLe8Z** (UNSUBMITTED, other): Sharpe=1.02, Fitness=0.35, TO=0.3329, DD=0.073。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(annual_revenue_value, ts_mean(ts_rank(log(abs(annual_total_assets_value)), 5), 20)), 20)`
- **YP0X0Jdl** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.02, TO=0.2178, DD=0.1662。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(annual_revenue_value, ts_mean(annual_total_revenue, 30)), 30)`
- **GrLELzVQ** (UNSUBMITTED, other): Sharpe=-0.67, Fitness=-0.32, TO=0.1532, DD=0.4047。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_delta(ts_mean(close, 20), 5), industry), sqrt(ts_std_dev(close, 20))))`
- **1Yd6dOeW** (UNSUBMITTED, other): Sharpe=-0.91, Fitness=-0.74, TO=0.014, DD=0.9149。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accumulated_depreciation_4, rank(divide(accounts_receivable_trade_current, divide(accounts_receivable_g...`
- **mLbeb6PK** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.09, TO=0.0132, DD=0.1388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(annual_total_revenue, ts_mean(rank(annual_total_revenue), 50)))`
- **RR8081ka** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.21, TO=0.0128, DD=0.3147。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, multiply(ts_mean(annual_total_revenue, 100), subtract(annual_net_income_available...`
- **LL1O1Xee** (UNSUBMITTED, other): Sharpe=-0.69, Fitness=-0.21, TO=0.4639, DD=0.5519。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(ts_rank(ts_delta(close, 5), 20), multiply(ts_std_dev(close, 20), 1)))`
- **9qrgrYAq** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.05, TO=0.0152, DD=0.464。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_payable_current_3, ts_rank(add(accounts_receivable_trade_current, ts_rank(rank(accounts_receivable_...`
- **6X9g9mxP** (UNSUBMITTED, other): Sharpe=-1.48, Fitness=-0.9, TO=0.2215, DD=0.922。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_rank(accounts_receivable_trade_current, 30), 10))`
- **58ONwXxk** (UNSUBMITTED, other): Sharpe=-3.14, Fitness=-1.43, TO=0.7246, DD=1.469。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_rank(rank(accounts_receivable_trade_current), 30), 10)`
- **omlQKrnk** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0131, DD=0.459。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, subtract(rank(multiply(annual_revenue_value, subtract(annual_total_assets_value, ...`
- **ZYnkpdP1** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=0.1852, DD=0.0979。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_delta(accounts_payable, 10), 100), 10))`
- **aknXdRZ6** (UNSUBMITTED, cashflow): Sharpe=0.66, Fitness=0.28, TO=0.2062, DD=0.0874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(log(abs(cashflow_op)), 20))`
- **GrLEwbxP** (UNSUBMITTED, other): Sharpe=0.82, Fitness=0.33, TO=0.2389, DD=0.1236。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(sign(log(mdl140_qes_sinc_sensitivity + abs(mdl140_qes_sinc_neut / mdl140_qes_sinc_comp))))`
- **3qRg738P** (UNSUBMITTED, other): Sharpe=-1.08, Fitness=-0.56, TO=0.2399, DD=0.7576。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(accounts_receivable_trade_current, accounts_payable_total_current), 20)`
- **A1Pqw6AQ** (UNSUBMITTED, other): Sharpe=-2.33, Fitness=-1.08, TO=0.4172, DD=0.9158。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(multiply(accounts_receivable_trade_current, rank(accounts_payable_total_current)), rank(accounts_rec...`
- **QPVmaLV5** (UNSUBMITTED, other): Sharpe=-1.74, Fitness=-0.65, TO=0.5696, DD=0.7978。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(ts_delta(close, 5)), subindustry), multiply(ts_std_dev(close, 20), 1)))`
- **E5EoKPe1** (UNSUBMITTED, other): Sharpe=-1.02, Fitness=-0.4, TO=0.468, DD=0.7475。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(close, 20), industry), sqrt(ts_std_dev(close, 20))))`
- **P03j1KbK** (UNSUBMITTED, other): Sharpe=-1.49, Fitness=-0.56, TO=1.7549, DD=2.7744。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(anl10_analyst_innovation_bps_revise_value_fy1, ts_rank(ts_mean(ts_rank(ts_rank(accounts_receivable_trade_cur...`
- **e70erEKM** (UNSUBMITTED, technical): Sharpe=0.52, Fitness=0.08, TO=0.4366, DD=0.0788。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(group_neutralize(ts_rank(log(abs(divide(ts_mean(close, 20), ts_std_dev(close, 20)))), 10), industry), z...`
- **d50eQYJx** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.08, TO=0.2527, DD=0.134。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(rank(annual_net_income_available_common), ts_rank(rank(annual_total_revenue), 30)))`
- **VkPK8ooV** (UNSUBMITTED, technical): Sharpe=0.81, Fitness=0.15, TO=0.9593, DD=0.1104。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(divide(ts_delta(zscore(close), 5), multiply(ts_std_dev(close, 20), zscore(volume))), industry))`
- **1Yd6gerR** (UNSUBMITTED, technical): Sharpe=-0.39, Fitness=-0.06, TO=0.2854, DD=0.1253。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(ts_corr(rank(close), rank(volume), 20), ts_std_dev(log(divide(high, low)), 20)))`
- **O0ZKnLeR** (UNSUBMITTED, technical): Sharpe=-0.6, Fitness=-0.16, TO=0.2645, DD=0.234。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(zscore(ts_corr(ts_rank(close, 20), ts_rank(volume, 20), 20)), sector))`
- **ZYnkjVGj** (UNSUBMITTED, other): Sharpe=-1.31, Fitness=-0.58, TO=0.4895, DD=0.9819。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_rank(zscore(close), 20), sector))`
- **O0ZKbrRg** (UNSUBMITTED, other): Sharpe=-1.26, Fitness=-0.26, TO=1.4152, DD=0.6318。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(ts_delta(ts_rank(close, 20), 1), sector))`
- **6X9gaqb5** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.1, TO=0.3781, DD=0.2105。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(ts_rank(annual_total_revenue, 10), divide(ts_rank(annual_net_income_incl_extraordinary, 10), 5)))`
- **YP0X2d3W** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.0223, DD=0.5059。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accrued_expenses_4, ts_mean(add(accounts_receivable_trade_current, ts_rank(rank(accounts_payable_total_curre...`
- **RR802nEo** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0168, DD=0.4477。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accounts_receivable_trade_current, rank(subtract(accounts_receivable_gross_4, rank(divide(accounts_rece...`
- **LL1Oloxm** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.04, TO=0.0177, DD=0.4475。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_receivable_trade_current, ts_rank(divide(accounts_payable_total_current, accounts_receivable_gross_...`
- **d50elK72** (UNSUBMITTED, other): Sharpe=-1.73, Fitness=-0.77, TO=1.7847, DD=3.5783。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl10_analyst_innovation_bps_innovation_score_fy1, ts_rank(accounts_receivable_trade_current, 100)))`
- **ZYnkWbR8** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.11, TO=0.0121, DD=0.126。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(multiply(annual_total_revenue, add(annual_ebitda_value, annual_net_income_available_common)), ts_rank(annual...`
- **d50elmgE** (UNSUBMITTED, other): Sharpe=-1.28, Fitness=-1.0, TO=0.1649, DD=1.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(accounts_payable_current_3 / inverse(ts_mean(accumulated_depreciation_4, 20)), 20))`
- **MPQ95lOk** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.04, TO=0.0507, DD=0.4843。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accounts_receivable_trade_current, ts_mean(multiply(accounts_receivable_gross_4, ts_rank(rank(accounts_...`
- **6X9gq5d5** (UNSUBMITTED, other): Sharpe=-0.67, Fitness=-0.54, TO=0.246, DD=1.6026。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(actual_update_flag_bps / ts_rank(log(abs(actual_update_flag_ebi - actual_update_flag_nav)), 10))`
- **LL1OXN2m** (UNSUBMITTED, technical): Sharpe=-3.43, Fitness=-3.16, TO=0.3997, DD=3.3174。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 10)), multiply(ts_std_dev(close, 20), ts_mean(volume, 20))))`
- **d50e7ne2** (UNSUBMITTED, technical): Sharpe=-1.58, Fitness=-0.55, TO=0.5619, DD=0.6919。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(multiply(ts_delta(close, 5), ts_mean(volume, 20))), subindustry), sqrt(abs(ts_cor...`
- **N1rkj1xo** (UNSUBMITTED, technical): Sharpe=-1.42, Fitness=-0.57, TO=0.5394, DD=0.8814。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(multiply(group_neutralize(ts_delta(close, 5), industry), ts_std_dev(volume, 20))))`
- **E5EobaAL** (UNSUBMITTED, technical): Sharpe=-2.76, Fitness=-1.88, TO=0.5004, DD=2.2891。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(close, 20), industry), multiply(ts_std_dev(volume, 20), sqrt(abs(ts_delta(close,...`
- **WjGKdd2P** (UNSUBMITTED, technical): Sharpe=-5.15, Fitness=-4.42, TO=0.7047, DD=5.0242。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(ts_rank(volume, 20), ts_delta(close, 5)), industry))`
- **qMlevp8v** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.02, TO=0.0135, DD=0.4638。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(rank(annual_revenue_value), rank(annual_total_assets_value)))`
- **XgnXPLO5** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0129, DD=0.4598。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, ts_mean(ts_rank(rank(annual_total_assets_value), 10), 20)))`
- **ZYnkqe0x** (UNSUBMITTED, other): Sharpe=-0.95, Fitness=-0.54, TO=0.362, DD=1.4704。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(scale(ts_zscore(subtract(accounts_receivable_trade_current, accounts_payable_total_current), 20)))`
- **vRlanXkQ** (UNSUBMITTED, other): Sharpe=1.61, Fitness=1.07, TO=0.1937, DD=0.0456。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl46_alphadecay, subtract(anl46_experts, anl46_indicator)))`
- **88QgkxrW** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.09, TO=0.0117, DD=0.1428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(annual_revenue_value + ts_rank(abs(annual_total_assets_value - annual_total_liabilities_value), 20))`
- **JjOR02Pn** (UNSUBMITTED, sentiment): Sharpe=1.39, Fitness=0.7, TO=0.3115, DD=0.0551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_sentiment, ts_rank(anl46_alphadecay, 50)))`
- **lelJ673O** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.06, TO=0.0143, DD=0.4618。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(abs(subtract(accounts_payable_current_3, rank(ts_rank(accounts_receivable_trade_current, 10) * divide(rank(accru...`
- **aknX2Y6O** (UNSUBMITTED, other): Sharpe=-0.56, Fitness=-0.25, TO=0.6912, DD=1.4197。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(actual_update_flag_bps, ts_rank(abs(subtract(accounts_receivable_trade_current, accounts_payable_total_cu...`
- **gJM77xkM** (UNSUBMITTED, technical): Sharpe=0.01, Fitness=0.0, TO=0.2618, DD=0.0687。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_corr(rank(volume), rank(returns), 20), subindustry), ts_std_dev(close, 20)))`
- **MPQ9wn1a** (UNSUBMITTED, technical): Sharpe=-0.88, Fitness=-0.26, TO=0.5839, DD=0.5272。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(divide(ts_delta(close, 20), ts_std_dev(close, 20))), subindustry), divide(abs(ts_...`
- **JjORl3VW** (UNSUBMITTED, technical): Sharpe=-1.78, Fitness=-0.76, TO=0.5933, DD=1.1045。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(zscore(ts_delta(close, 5)), sector), sqrt(ts_std_dev(volume, 20))))`

---


### 2026-07-06 15:44 UTC

- **xAkwP3bN** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.11, TO=0.3935, DD=0.0975。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(cash_per_share, ts_rank(rank(annual_revenue_value), 20)))`
- **lel6Rne5** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.34, TO=0.0205, DD=0.2209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **GrL03j5P** (UNSUBMITTED, other): Sharpe=-0.51, Fitness=-0.25, TO=0.0715, DD=0.3574。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(divide(ts_mean(log(1 + abs(close)), 20), ts_std_dev(close, 20))))`
- **58O762ZX** (UNSUBMITTED, technical): Sharpe=-1.67, Fitness=-0.6, TO=0.7373, DD=0.9786。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 5)), multiply(ts_std_dev(close, 20), sqrt(abs(ts_delta(volume, 5))))))`
- **j20lwxM5** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0218, DD=0.2249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **1YdVL8KW** (UNSUBMITTED, technical): Sharpe=-0.51, Fitness=-0.05, TO=1.1216, DD=0.1664。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(zscore(ts_delta(close, 5)), zscore(ts_rank(volume, 20))), market))`
- **omlwvbG2** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0246, DD=0.2261。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **pwlJoe5V** (UNSUBMITTED, technical): Sharpe=-0.21, Fitness=-0.01, TO=0.6829, DD=0.0759。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(group_neutralize(ts_rank(ts_delta(close, 5), 20), market), zscore(ts_corr(ts_mean(volume, 20), ts_std_d...`

---


### 2026-07-06 15:45 UTC

- **xAkwP3bN** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.11, TO=0.3935, DD=0.0975。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(cash_per_share, ts_rank(rank(annual_revenue_value), 20)))`
- **lel6Rne5** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.34, TO=0.0205, DD=0.2209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **GrL03j5P** (UNSUBMITTED, other): Sharpe=-0.51, Fitness=-0.25, TO=0.0715, DD=0.3574。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(divide(ts_mean(log(1 + abs(close)), 20), ts_std_dev(close, 20))))`
- **58O762ZX** (UNSUBMITTED, technical): Sharpe=-1.67, Fitness=-0.6, TO=0.7373, DD=0.9786。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(ts_delta(close, 5)), multiply(ts_std_dev(close, 20), sqrt(abs(ts_delta(volume, 5))))))`
- **j20lwxM5** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0218, DD=0.2249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **1YdVL8KW** (UNSUBMITTED, technical): Sharpe=-0.51, Fitness=-0.05, TO=1.1216, DD=0.1664。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(multiply(zscore(ts_delta(close, 5)), zscore(ts_rank(volume, 20))), market))`
- **omlwvbG2** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0246, DD=0.2261。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **pwlJoe5V** (UNSUBMITTED, technical): Sharpe=-0.21, Fitness=-0.01, TO=0.6829, DD=0.0759。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(group_neutralize(ts_rank(ts_delta(close, 5), 20), market), zscore(ts_corr(ts_mean(volume, 20), ts_std_d...`

---


### 2026-07-06 16:11 UTC

- **58O7M6PX** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **KP9YkY8E** (UNSUBMITTED, cashflow): Sharpe=0.41, Fitness=0.15, TO=0.1092, DD=0.0797。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(multiply(annual_net_income_value, ts_rank(divide(cashflow_op, assets), 50)), 50))`
- **akn2Nmqw** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.03, TO=0.0228, DD=0.3494。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(cash * ts_rank(log(accounts_receivable_current_assets), 20))`
- **1YdVo2gM** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.1656, DD=0.2141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(subtract(annual_total_revenue, ts_mean(annual_total_revenue, 30)), 30))`
- **d508nv7v** (UNSUBMITTED, technical): Sharpe=1.22, Fitness=1.11, TO=0.0521, DD=0.1506。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **N1rWnAmg** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0168, DD=0.447。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_receivable_trade_current, ts_rank(divide(accounts_receivable_gross_4, accounts_receivable_accrued),...`
- **mLb2q9nK** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.0562, DD=0.3923。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(accounts_payable_current_3, ts_rank(ts_mean(allowance_doubtful_trade_accounts, 20), 5)))`
- **LL1bnWX9** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.06, TO=0.4807, DD=0.1157。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(zscore(volume), sqrt(abs(ts_delta(close, 5)))))`
- **E5E0g9Er** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.1, TO=0.1267, DD=0.2325。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(mdl140_qes_sinc_sensitivity + sign(log(abs(mdl140_qes_sinc_neut * mdl140_qes_sinc_comp))))`
- **RR8Z2wKj** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0133, DD=0.4516。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, multiply(rank(annual_total_assets_value), add(annual_ebitda_amount, rank(annual_n...`
- **kq0k16Zz** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **2rLqa2Pb** (UNSUBMITTED, other): Sharpe=-0.81, Fitness=-0.23, TO=0.4028, DD=0.4214。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(group_neutralize(divide(ts_delta(ts_mean(close, 5), 3), ts_std_dev(close, 20)), subindustry))`

---


### 2026-07-07 04:43 UTC

- **akn2bqG9** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.12, TO=0.0126, DD=0.2647。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accounts_payable, ts_rank(abs(accounts_receivable_current_assets), 50)))`
- **1YdVwY1m** (UNSUBMITTED, sentiment): Sharpe=1.01, Fitness=0.36, TO=0.4177, DD=0.0927。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(anl46_indicator, divide(ts_rank(anl46_sentiment, 20), subtract(ts_rank(anl46_experts, 20), ts_rank(anl4...`
- **6X9PpL6O** (UNSUBMITTED, technical): Sharpe=-4.0, Fitness=-2.44, TO=0.73, DD=2.6396。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(ts_delta(close, 5), 20), sector), multiply(abs(ts_delta(volume, 5)), ts_std_dev(...`
- **xAkwNAbN** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.04, TO=0.045, DD=0.4344。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accrued_expenses_4, ts_rank(divide(accounts_receivable_trade_current, ts_mean(accounts_receivable_gross...`
- **KP9YEQrj** (UNSUBMITTED, other): Sharpe=-1.66, Fitness=-1.07, TO=0.1681, DD=0.698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(divide(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 20)), 20))`
- **akn2EwY9** (UNSUBMITTED, sentiment): Sharpe=-0.98, Fitness=-0.39, TO=0.336, DD=0.4041。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_performancepercentile, ts_rank(anl46_sentiment, 50)))`
- **xAkwdamp** (UNSUBMITTED, sentiment): Sharpe=0.14, Fitness=0.01, TO=0.599, DD=0.0977。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl46_sentiment, ts_rank(subtract(anl46_performancepercentile, ts_rank(divide(anl46_indicator, add(anl4...`
- **GrL0oKYJ** (UNSUBMITTED, technical): Sharpe=-0.21, Fitness=-0.02, TO=0.7467, DD=0.1932。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(divide(ts_delta(close, 5), ts_std_dev(close, 20)), 10), industry), sqrt(abs(zsco...`

---


### 2026-07-07 04:44 UTC

- **akn2bqG9** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.12, TO=0.0126, DD=0.2647。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accounts_payable, ts_rank(abs(accounts_receivable_current_assets), 50)))`
- **1YdVwY1m** (UNSUBMITTED, sentiment): Sharpe=1.01, Fitness=0.36, TO=0.4177, DD=0.0927。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(anl46_indicator, divide(ts_rank(anl46_sentiment, 20), subtract(ts_rank(anl46_experts, 20), ts_rank(anl4...`
- **6X9PpL6O** (UNSUBMITTED, technical): Sharpe=-4.0, Fitness=-2.44, TO=0.73, DD=2.6396。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(ts_delta(close, 5), 20), sector), multiply(abs(ts_delta(volume, 5)), ts_std_dev(...`
- **xAkwNAbN** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.04, TO=0.045, DD=0.4344。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accrued_expenses_4, ts_rank(divide(accounts_receivable_trade_current, ts_mean(accounts_receivable_gross...`
- **KP9YEQrj** (UNSUBMITTED, other): Sharpe=-1.66, Fitness=-1.07, TO=0.1681, DD=0.698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(divide(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 20)), 20))`
- **akn2EwY9** (UNSUBMITTED, sentiment): Sharpe=-0.98, Fitness=-0.39, TO=0.336, DD=0.4041。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_performancepercentile, ts_rank(anl46_sentiment, 50)))`
- **xAkwdamp** (UNSUBMITTED, sentiment): Sharpe=0.14, Fitness=0.01, TO=0.599, DD=0.0977。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl46_sentiment, ts_rank(subtract(anl46_performancepercentile, ts_rank(divide(anl46_indicator, add(anl4...`
- **GrL0oKYJ** (UNSUBMITTED, technical): Sharpe=-0.21, Fitness=-0.02, TO=0.7467, DD=0.1932。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(group_neutralize(ts_rank(divide(ts_delta(close, 5), ts_std_dev(close, 20)), 10), industry), sqrt(abs(zsco...`

---


### 2026-07-07 08:12 UTC

- **E5Eb038P** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-07 08:12 UTC

- **E5Eb038P** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 01:21 UTC

- **YP0QbXmv** (UNSUBMITTED, other): Sharpe=2.3, Fitness=1.14, TO=0.3769, DD=0.035。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **omlV6PGm** (UNSUBMITTED, other): Sharpe=2.16, Fitness=1.1, TO=0.3828, DD=0.0422。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **blqvRpGK** (UNSUBMITTED, other): Sharpe=2.14, Fitness=1.0, TO=0.4734, DD=0.0395。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **YP0Q7JKR** (UNSUBMITTED, other): Sharpe=1.84, Fitness=0.6, TO=0.9575, DD=0.0416。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 03:36 UTC

- **E5EkV6xG** (UNSUBMITTED, other): Sharpe=2.1, Fitness=1.33, TO=0.1634, DD=0.0409。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **P03vgLKL** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 04:24 UTC

- **A1Pkpvjd** (UNSUBMITTED, other): Sharpe=0.67, Fitness=0.98, TO=0.1142, DD=0.6534。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **e70LMWVE** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **zqmO7krV** (UNSUBMITTED, other): Sharpe=1.96, Fitness=1.31, TO=0.1144, DD=0.044。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 06:50 UTC

- **JjOdX2xW** (UNSUBMITTED, other): Sharpe=2.07, Fitness=0.85, TO=0.6276, DD=0.0401。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **1YdgLl1Q** (UNSUBMITTED, other): Sharpe=1.84, Fitness=0.6, TO=0.9575, DD=0.0416。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **blq9M60l** (UNSUBMITTED, other): Sharpe=1.64, Fitness=1.17, TO=0.1146, DD=0.0465。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **QPVQq8Ww** (UNSUBMITTED, other): Sharpe=1.91, Fitness=1.19, TO=0.2297, DD=0.0493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **np2WYE8M** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.24, TO=0.1133, DD=0.0448。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **pwl7o2p3** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.22, TO=0.1674, DD=0.0426。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **aknOMonO** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **pwl7QPxq** (UNSUBMITTED, other): Sharpe=2.14, Fitness=1.21, TO=0.2803, DD=0.0435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 07:35 UTC

- **P031pOOL** (UNSUBMITTED, other): Sharpe=2.16, Fitness=1.1, TO=0.3828, DD=0.0422。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **P031plKq** (UNSUBMITTED, other): Sharpe=1.66, Fitness=0.56, TO=0.9738, DD=0.0563。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **qMlXnbkA** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **xAknmNzn** (UNSUBMITTED, other): Sharpe=1.44, Fitness=0.5, TO=0.99, DD=0.0784。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-09 08:36 UTC

- **j20g8Xgj** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.24, TO=0.1133, DD=0.0448。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **JjOdQqpe** (UNSUBMITTED, other): Sharpe=2.3, Fitness=1.14, TO=0.3769, DD=0.035。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **np2WdYG3** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **JjOdx8dx** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.93, TO=0.1437, DD=0.6459。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **lel0jQGe** (UNSUBMITTED, other): Sharpe=1.95, Fitness=1.13, TO=0.2877, DD=0.0582。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **JjOd703l** (UNSUBMITTED, other): Sharpe=2.3, Fitness=1.14, TO=0.3769, DD=0.035。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **omlYN67b** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.22, TO=0.1674, DD=0.0426。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **vRlmlXNb** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.93, TO=0.1437, DD=0.6459。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **88QLQdWX** (UNSUBMITTED, other): Sharpe=1.44, Fitness=0.5, TO=0.99, DD=0.0784。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-10 11:33 UTC

- **2rLLp35b** (UNSUBMITTED, technical): Sharpe=-0.66, Fitness=-0.38, TO=0.144, DD=0.5435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(returns, 100), 500))`
- **pwllN8Yx** (UNSUBMITTED, technical): Sharpe=-0.93, Fitness=-0.2, TO=0.9913, DD=0.5488。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(volume, 20) + ts_mean(close, 20), 252))`
- **JjOOGqvA** (UNSUBMITTED, other): Sharpe=-0.73, Fitness=-0.4, TO=0.4208, DD=1.634。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(accounts_receivable_trade_current, 5), 20))`
- **e700xjXM** (UNSUBMITTED, cashflow): Sharpe=-0.08, Fitness=-0.02, TO=0.1083, DD=0.419。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(multiply(cashflow_op, subtract(ebitda, bookvalue_ps)), 5), 30))`
- **d500Rbqv** (UNSUBMITTED, technical): Sharpe=-0.02, Fitness=-0.0, TO=0.7926, DD=0.2837。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(close, 5) - ts_mean(ts_delta(volume, 5), 5), 5))`
- **ZYnnK7A1** (UNSUBMITTED, other): Sharpe=0.37, Fitness=0.18, TO=0.0094, DD=0.2231。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(accounts_payable + ts_rank(cash / ts_mean(assets, 10), 20))`
- **1Yddzgjm** (UNSUBMITTED, sentiment): Sharpe=-0.36, Fitness=-0.14, TO=0.0944, DD=0.2308。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(anl46_alphadecay - ts_mean(anl46_experts - ts_std_dev(anl46_indicator / ts_zscore(anl46_performancepercentile + ...`
- **vRlllpj3** (UNSUBMITTED, cashflow): Sharpe=0.72, Fitness=0.37, TO=0.0555, DD=0.0804。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(subtract(cashflow_op, rank(assets)), 50), 200))`
- **3qRRR9de** (UNSUBMITTED, technical): Sharpe=1.41, Fitness=0.6, TO=0.1875, DD=0.0512。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(daily_volume_to_shares_outstanding, ts_mean(sign(annual_revenue_change_percent), 50)), 200)`
- **QPVVV7WW** (UNSUBMITTED, other): Sharpe=-0.73, Fitness=-0.41, TO=0.1534, DD=0.5148。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(close, 5), 20) / ts_std_dev(ts_delta(close, 5), 20), 252))`
- **vRllldad** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.03, TO=0.0382, DD=0.0928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(annual_net_income_excl_extraordinary, ts_mean(annual_revenue_value, 5)), 252))`
- **58OOO3q5** (UNSUBMITTED, other): Sharpe=-1.34, Fitness=-0.85, TO=0.2531, DD=1.1341。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(accounts_payable_current_3, divide(accounts_receivable_trade_current, accounts_payable_total_current)), 20)`
- **aknnnqx9** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.05, TO=0.7428, DD=0.2165。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(sign(ts_delta(close, 10)), divide(volume, ts_mean(volume, 100))), 100))`
- **vRlll8br** (UNSUBMITTED, technical): Sharpe=-0.16, Fitness=-0.05, TO=0.0273, DD=0.3642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(close, 20) + ts_std_dev(volume - open, 60))`
- **3qRR7VXN** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.125, DD=0.1235。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_std_dev(close * ts_zscore(ts_mean(high / low, 50), 50), 50), 50)`
- **RR88pp50** (UNSUBMITTED, other): Sharpe=0.04, Fitness=0.0, TO=0.1319, DD=0.0786。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(ts_mean(annual_net_income_excl_extraordinary, 50), ts_std_dev(annual_revenue_value, 50)), 50...`
- **7811deRb** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.05, TO=0.5297, DD=0.1343。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(ebitda, cogs), 10))`
- **kq00KjQd** (UNSUBMITTED, other): Sharpe=0.84, Fitness=0.47, TO=0.0573, DD=0.0668。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(fnd17_2rhsfca, ts_mean(fnd17_2rhsfcq, 20)), 60))`
- **rKllW1LE** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.0124, DD=0.2879。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(annual_net_income_incl_extraordinary, ts_min(annual_total_revenue, 30)), 30))`
- **gJMMxlzJ** (UNSUBMITTED, other): Sharpe=-0.56, Fitness=-0.32, TO=0.2188, DD=0.9423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(accounts_receivable_trade_current, 30), 30), 30)`
- **QPVVEzxp** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.0091, DD=0.1578。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(annual_revenue_value, annual_total_assets_value), 5))`
- **3qRRzGJX** (UNSUBMITTED, other): Sharpe=-0.62, Fitness=-0.34, TO=0.2376, DD=0.8598。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_receivable_trade_current, log(add(accrued_expenses_4, multiply(accounts_payable_curren...`
- **9qrrJxRe** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.02, TO=0.8832, DD=0.7738。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(annual_revenue_value, 20), 5))`
- **88QQn5GX** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.07, TO=0.0117, DD=0.3643。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(cash, ts_mean(ts_std_dev(ts_delta(accounts_receivable_current_assets, 10), 50), 20)))`
- **mLbbqQY2** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.09, TO=0.3644, DD=0.1242。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(ts_mean(close, 20), ts_min(close, 20)), ts_std_dev(close, 20)), 100))`
- **0mEEAkgr** (UNSUBMITTED, cashflow): Sharpe=-0.04, Fitness=-0.0, TO=0.0021, DD=0.1335。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(log(ts_delta(cashflow_op, 20)), 2), 20))`
- **Xgnn2b90** (UNSUBMITTED, other): Sharpe=-1.66, Fitness=-0.6, TO=0.9047, DD=1.2577。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(close, ts_mean(close, 126)), ts_std_dev(close, 126)), 5))`
- **E5EEgeqm** (UNSUBMITTED, other): Sharpe=-0.77, Fitness=-0.39, TO=0.2815, DD=0.9853。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(subtract(accounts_receivable_trade_current, ts_delta(accumulated_depreciation_4, 10)), 50),...`
- **O0ZZbwjp** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.19, TO=0.1167, DD=0.2997。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(accounts_payable_current * ts_std_dev(ts_zscore(accounts_receivable_current, 10), 20), 20))`
- **e700d8mO** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.38, TO=0.0094, DD=0.1864。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ebitda - subtract(ts_rank(assets, 10), 50), 60))`
- **qMllPbmV** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.21, TO=0.0499, DD=0.0901。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(multiply(annual_ebitda_value, log(add(annual_total_shareholder_equity, annual_revenue_v...`
- **9qrrazO9** (UNSUBMITTED, other): Sharpe=-1.56, Fitness=-0.99, TO=0.0394, DD=0.5961。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(signed_power(accounts_receivable_trade_current / ts_min(accumulated_depreciation_4, 10), 2), 6...`
- **E5EEr3jR** (UNSUBMITTED, technical): Sharpe=0.76, Fitness=0.38, TO=0.1383, DD=0.1229。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(ts_mean(close, 100), ts_min(low, 100)), ts_std_dev(volume, 50)), 50))`
- **YP00klnl** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.08, TO=0.0105, DD=0.5899。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(add(accounts_payable_current_3, accounts_receivable_trade_current), 20)`
- **0mEEQjL6** (UNSUBMITTED, technical): Sharpe=-1.2, Fitness=-0.65, TO=0.2964, DD=0.8715。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(returns, 20), 252))`
- **9qrr6jQK** (UNSUBMITTED, technical): Sharpe=-0.11, Fitness=-0.02, TO=0.2501, DD=0.2895。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(multiply(ts_rank(ts_std_dev(returns, 20), 60), log(ts_mean(volume, 20))), 252))`
- **VkPPEx2A** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.25, TO=0.2369, DD=0.1139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(accounts_cash_and_equivalents, 20), 20))`
- **O0ZZqXAR** (UNSUBMITTED, other): Sharpe=0.73, Fitness=0.28, TO=0.2524, DD=0.1142。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(anl46_indicator, 10), 10)`
- **58OO3jZJ** (UNSUBMITTED, technical): Sharpe=-0.36, Fitness=-0.14, TO=0.1194, DD=0.3262。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(close * volume, 50), 50))`
- **ZYnnqKM8** (UNSUBMITTED, other): Sharpe=-0.18, Fitness=-0.06, TO=0.0287, DD=0.5168。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(accounts_receivable_trade_current * log(accounts_payable_total_current - ts_std_dev(accrued_expenses_4, ...`
- **rKllEW0j** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.023, DD=0.1299。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(divide(subtract(close, ts_mean(close, 200)), ts_std_dev(close, 200)), 60), 100))`
- **XgnnPLwx** (UNSUBMITTED, cashflow): Sharpe=-0.02, Fitness=-0.0, TO=0.0447, DD=0.1043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, sqrt(cashflow_op / log(abs(ts_delta(assets, 252))))), 504))`
- **KP99qqpg** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.04, TO=0.1061, DD=0.0954。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(annual_net_income_to_common, multiply(annual_revenue_per_share, log(ts_mean(add(annual_total_shareho...`
- **9qrrP92K** (UNSUBMITTED, other): Sharpe=-1.26, Fitness=-0.71, TO=0.091, DD=0.3886。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(accrued_expenses_4, ts_mean(rank(accounts_payable_current_3), 100)), 50)`
- **O0ZZwEXp** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.08, TO=0.2114, DD=0.7181。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(sqrt(accounts_receivable_trade_current * ts_mean(log(accrued_expenses_4), 10)), 20) - subtract(ts_zscore...`
- **XgnnXvKz** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.04, TO=0.0887, DD=0.1097。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(ts_av_diff(capex * assets, 10), ts_mean(ts_rank(ebitda * revenue, 20), 10)))`
- **XgnnXE55** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.11, TO=0.1011, DD=0.2721。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(anl46_alphadecay, 10), 100))`
- **pwllgm5x** (UNSUBMITTED, technical): Sharpe=-3.34, Fitness=-1.73, TO=0.6949, DD=1.8038。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_std_dev(ts_delta(returns, 100), 5), 10), 20)`
- **E5EEJzXP** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.11, TO=0.3379, DD=0.1525。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(ts_mean(close, 20), ts_min(close, 100)), ts_std_dev(close, 100)), 10))`
- **LL11J7Ge** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.14, TO=0.4598, DD=0.4814。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_rank(ts_mean(log(returns), 10), 60), 252))`
- **d500L7YK** (UNSUBMITTED, other): Sharpe=-1.37, Fitness=-0.72, TO=0.0532, DD=0.36。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(accounts_payable_current_3 + ts_mean(accounts_receivable_trade_current - ts_std_dev(accumulated_dep...`
- **QPVVXJZ5** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.05, TO=0.0137, DD=0.4585。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(accounts_payable_current_3, ts_rank(ts_mean(ts_std_dev(ts_delta(accounts_receivable_trade_current, 100), 100...`
- **rKllvMzE** (UNSUBMITTED, technical): Sharpe=-0.2, Fitness=-0.05, TO=0.0111, DD=0.1551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(sqrt(subtract(annual_debt_to_equity_ratio, ts_min(daily_volume_to_shares_outstanding, 30))), 60))`
- **d500AoPj** (UNSUBMITTED, other): Sharpe=-2.22, Fitness=-1.73, TO=0.192, DD=1.1555。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accounts_payable_current_3, subtract(accounts_receivable_trade_current, accounts_payable_total_current...`
- **0mE7Zp6K** (UNSUBMITTED, technical): Sharpe=-0.96, Fitness=-0.62, TO=0.1537, DD=0.6502。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(returns, 100), 200))`
- **2rL7odNb** (UNSUBMITTED, technical): Sharpe=-0.62, Fitness=-0.1, TO=0.8718, DD=0.2588。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_av_diff(returns, 20), multiply(log(volume), -1)), 100))`
- **A1Pw2wmX** (UNSUBMITTED, sentiment): Sharpe=-0.4, Fitness=-0.28, TO=0.097, DD=0.9494。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(anl46_sentiment), 50), 100))`
- **E5EwxYLr** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.08, TO=0.2023, DD=1.5426。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(multiply(assets, log(sqrt(subtract(ebitda, ts_mean(revenue, 20))))), debt))`
- **blqLnxaR** (UNSUBMITTED, other): Sharpe=0.71, Fitness=0.24, TO=0.2703, DD=0.0659。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_mean(annual_net_income_change_percent, 5), multiply(annual_debt_to_equity_ratio, sqrt(ts_std_de...`
- **781wmrM5** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.1541, DD=0.4422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(subtract(close, ts_mean(close, 20)), 10))`
- **gJM1GRlJ** (UNSUBMITTED, sentiment): Sharpe=0.41, Fitness=0.11, TO=0.2912, DD=0.1103。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(fnd17_1_usdtorepexrate, ts_rank(anl46_sentiment, 20)))`
- **ZYnpzlr0** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0471, DD=0.4819。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(annual_net_income_incl_extraordinary, ts_mean(divide(annual_total_revenue, ts_std_dev(annual_ebitda_amoun...`
- **akndzYkW** (UNSUBMITTED, technical): Sharpe=-0.06, Fitness=-0.01, TO=0.1844, DD=0.1369。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(returns, 20), 60) / sqrt(ts_mean(volume, 10) / multiply(high, low)))`
- **omlKG1Vn** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.11, TO=0.2154, DD=0.0699。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, multiply(assets, bookvalue_ps)), 30))`
- **58OwAOz6** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.2, TO=0.2259, DD=1.0551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(log(multiply(accounts_payable_current_3, accounts_receivable_trade_current)), 50))`
- **rKloNWL3** (UNSUBMITTED, other): Sharpe=-0.54, Fitness=-0.21, TO=0.1566, DD=0.3177。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(subtract(close, ts_mean(close, 20)), ts_std_dev(close, 20)), 30))`
- **YP0pEQdA** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.04, TO=0.0127, DD=0.4832。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(log(add(annual_total_revenue, ts_mean(annual_ebitda_amount, 20))))`
- **6X9wo8YO** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.02, TO=0.4095, DD=0.0862。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(rank(divide(annual_revenue_value, annual_total_assets_value)), 50))`
- **gJM1XXGJ** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.08, TO=0.3183, DD=0.1585。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, ts_mean(annual_total_revenue, 10)))`
- **E5Ewm9RR** (UNSUBMITTED, other): Sharpe=-0.74, Fitness=-0.39, TO=0.1374, DD=0.4225。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(accounts_receivable_trade_current, 30), 10))`
- **kq038J6P** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.0325, DD=0.5162。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(accounts_payable_total_current, rank(rank(accounts_receivable_trade_current))))`
- **mLb8KqkW** (UNSUBMITTED, other): Sharpe=-1.86, Fitness=-1.33, TO=0.1046, DD=0.655。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(rank(accounts_receivable_trade_current), 30), 30)`
- **N1rpNZbL** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.03, TO=0.0415, DD=0.3815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(rank(accounts_receivable_trade_current), divide(rank(accrued_expenses_4), add(rank(accounts_payable_total_cu...`
- **omlKozGv** (UNSUBMITTED, other): Sharpe=-1.38, Fitness=-0.52, TO=1.8127, DD=2.5693。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(multiply(anl10_analyst_innovation_bps_revise_value_fy1, ts_rank(ts_rank(rank(anl10_analyst_innovation_bps_revise...`
- **N1rpaK6p** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.03, TO=0.0129, DD=0.2358。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, add(annual_total_assets_value, annual_total_liabilities_value)))`
- **WjGpblVk** (UNSUBMITTED, sentiment): Sharpe=0.75, Fitness=0.35, TO=0.178, DD=0.1033。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(anl46_sentiment, 100))`
- **zqm9896E** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(100)`
- **rKlo5Gm1** (UNSUBMITTED, sentiment): Sharpe=0.6, Fitness=0.22, TO=0.2113, DD=0.1127。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(rank(anl46_sentiment), 50), 5))`
- **88Qz3VGz** (UNSUBMITTED, sentiment): Sharpe=-0.24, Fitness=-0.04, TO=0.3658, DD=0.2211。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(anl46_sentiment, 10))`
- **RR8pV6vb** (UNSUBMITTED, sentiment): Sharpe=0.78, Fitness=0.45, TO=0.1183, DD=0.1142。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(anl46_sentiment, 10), 100))`
- **zqm9Yzbd** (UNSUBMITTED, sentiment): Sharpe=1.19, Fitness=0.57, TO=0.3357, DD=0.0981。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_sentiment, ts_rank(ts_mean(subtract(anl46_experts, anl46_indicator), 20), 5)))`
- **LL1p9xd6** (UNSUBMITTED, sentiment): Sharpe=1.69, Fitness=1.22, TO=0.1739, DD=0.047。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl46_sentiment, subtract(anl46_experts, anl46_indicator)))`
- **JjOpxKrl** (UNSUBMITTED, sentiment): Sharpe=1.66, Fitness=1.28, TO=0.1516, DD=0.0521。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(anl46_sentiment, anl46_experts))`
- **JjOpxZam** (UNSUBMITTED, cashflow): Sharpe=1.24, Fitness=0.87, TO=0.0238, DD=0.0874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(cashflow_op, ts_mean(assets, 20)))`
- **ZYnp7VQY** (UNSUBMITTED, sentiment): Sharpe=0.2, Fitness=0.06, TO=0.0872, DD=0.1239。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(rank(anl46_sentiment), 50), 100))`
- **blqLjOMm** (UNSUBMITTED, other): Sharpe=0.31, Fitness=0.08, TO=0.3032, DD=0.1547。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, ts_mean(annual_revenue_value, 10)))`
- **JjOp7v8n** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.67, TO=0.0445, DD=1.3248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`sign(log(mdl140_qes_sinc_sensitivity * abs(mdl140_qes_sinc_neut + mdl140_qes_sinc_comp)))`
- **lelVjzvA** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.02, TO=0.0401, DD=0.4574。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(annual_revenue_value, ts_rank(annual_total_assets_value, 100)))`
- **0mE7pLx6** (UNSUBMITTED, other): Sharpe=-2.09, Fitness=-1.45, TO=0.1575, DD=0.7794。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(rank(accounts_receivable_trade_current), 30), 10)`
- **O0ZpG72Y** (UNSUBMITTED, cashflow): Sharpe=0.52, Fitness=0.29, TO=0.0081, DD=0.1755。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_net_income_value, ts_rank(multiply(cashflow_op, cash), 20)))`
- **d50xRYzK** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.0441, DD=0.3999。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(annual_total_revenue * ts_rank(ts_mean(ts_rank(annual_total_revenue, 30), 30), 100))`
- **GrLweEjQ** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0131, DD=0.4587。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_total_revenue, rank(multiply(rank(annual_net_income_incl_extraordinary), annual_total_assets_val...`
- **QPVaVxNp** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.1, TO=0.0113, DD=0.1406。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_revenue_value, ts_mean(ts_rank(ts_rank(rank(annual_revenue_value), 5), 20), 20)))`
- **1Yd7dAMm** (UNSUBMITTED, sentiment): Sharpe=-0.58, Fitness=-0.19, TO=0.2719, DD=0.4001。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_sentiment, ts_mean(anl46_alphadecay, 10)))`
- **E5EwE62m** (UNSUBMITTED, other): Sharpe=-1.04, Fitness=-0.53, TO=0.0751, DD=0.3675。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(abs(accrued_expenses_4 * accounts_receivable_trade_current), 50), 50))`
- **qMlAlxj1** (UNSUBMITTED, sentiment): Sharpe=-1.01, Fitness=-0.4, TO=0.4918, DD=0.8328。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_alphadecay, ts_rank(anl46_sentiment, 10)))`
- **GrLo9mnZ** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.36, TO=0.0425, DD=0.314。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **E5EKLxe1** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.2, TO=0.053, DD=0.3125。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **A1P3mG2w** (UNSUBMITTED, technical): Sharpe=1.23, Fitness=1.69, TO=0.0266, DD=0.3638。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **LL1RrGna** (UNSUBMITTED, technical): Sharpe=1.08, Fitness=1.18, TO=0.0495, DD=0.2967。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **ZYnozOnY** (UNSUBMITTED, technical): Sharpe=1.09, Fitness=1.24, TO=0.0562, DD=0.3153。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **j20gGJNo** (UNSUBMITTED, technical): Sharpe=1.05, Fitness=1.1, TO=0.0483, DD=0.2928。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **aknOzVd2** (UNSUBMITTED, technical): Sharpe=1.23, Fitness=1.55, TO=0.0461, DD=0.3215。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **MPQxz0m8** (UNSUBMITTED, technical): Sharpe=1.24, Fitness=1.58, TO=0.0309, DD=0.4158。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **E5EKzkJJ** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.36, TO=0.0527, DD=0.3155。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **omlYGnRE** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.4, TO=0.0485, DD=0.3063。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **j20gVYae** (UNSUBMITTED, other): Sharpe=1.71, Fitness=1.22, TO=0.1347, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **6X9EGRd5** (UNSUBMITTED, other): Sharpe=1.88, Fitness=1.3, TO=0.1325, DD=0.0431。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **A1P3Ve3E** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.8, TO=0.1973, DD=0.6388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **KP9LmVR8** (UNSUBMITTED, other): Sharpe=1.95, Fitness=1.13, TO=0.2877, DD=0.0582。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **58Ovjob1** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.54, TO=0.0222, DD=0.3255。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`

---


### 2026-07-25 14:07 UTC

- **ZYK6gY8x** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.0534, DD=0.0717。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_ero, 120)), 240)`
- **Vk3V8ZOV** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(divide(fnd109_total_score, fnd6_amq), 20), 20))`
- **9q7YJ0gd** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.0137, DD=0.233。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(zscore(annual_revenue_change_percent), 60))`
- **2rNMvexZ** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0406, DD=0.1984。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_cpx_value, 120)), 252)`
- **E5e1gjZ0** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.21, TO=0.0257, DD=0.0499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_net_income_excl_extraordinary, ts_mean(annual_total_liabilities_value, 120)), 252))`
- **bldXolJq** (UNSUBMITTED, other): Sharpe=-0.38, Fitness=-0.14, TO=0.0503, DD=0.1781。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_ewq_accdq, 120)), 240)`
- **kqZdL73K** (UNSUBMITTED, other): Sharpe=-0.54, Fitness=-0.24, TO=0.0199, DD=0.3948。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_eps_value, 120)), 252)`
- **0mMqkxWp** (UNSUBMITTED, other): Sharpe=0.37, Fitness=0.14, TO=0.0301, DD=0.0931。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 120)), 252)`
- **akE62XLx** (UNSUBMITTED, other): Sharpe=1.13, Fitness=0.69, TO=0.0249, DD=0.0531。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_cps_value, 120)), 252)`
- **akE6Jnj2** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.0672, DD=0.2141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)), 20)`
- **9q7Y0dgr** (UNSUBMITTED, other): Sharpe=1.02, Fitness=0.6, TO=0.0402, DD=0.0556。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_cps_value, 120)), 252)`
- **bldXE306** (UNSUBMITTED, other): Sharpe=-0.54, Fitness=-0.23, TO=0.0348, DD=0.2543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_eieac, 120)), 252)`
- **3qewr8lz** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.044, DD=0.104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_chech, 120)), 240)`
- **58kx0jon** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.07, TO=0.0439, DD=0.1116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(fnd6_dpsa, ts_mean(fnd6_dpsa, 120)), 252), 20)`
- **JjvqqnJn** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.08, TO=0.0369, DD=0.1151。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_ewq_eqrtq, 120)), 252)`
- **9q7Yqkqq** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.06, TO=0.1746, DD=0.1432。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(act_12m_eps_value, 120), 20), 60)`
- **2rN8Y68N** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.14, TO=0.0387, DD=0.1287。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_q_ebt_value, 60)), 120)`
- **kqZEwR0l** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.02, TO=0.0213, DD=0.18。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(act_12m_gps_value, ts_mean(act_12m_ebi_value, 30)), 100))`
- **0mMOLV0K** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.03, TO=0.1414, DD=0.0754。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(act_q_dps_surprisemean, 2)) * ts_rank(vec_avg(anl12_bbgnews_score), 252), 60)`
- **YPgL9rqJ** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.0203, DD=0.2297。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(fnd6_dvc, 120), 252))`
- **akEjGgbv** (UNSUBMITTED, other): Sharpe=0.71, Fitness=0.72, TO=0.0538, DD=0.2258。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roa_value, 120)), 252)`
- **bldGWrRM** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.381, DD=0.2794。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ts_delta(fnd6_capxy, 50), 5), 10))`
- **6XeXoebp** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7x76ROp** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.11, TO=0.0425, DD=0.1565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_av_diff(ts_mean(fnd6_amq, 30), 100), 200))`
- **mLVLL3V2** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.0344, DD=0.0689。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(fnd6_ero, ts_mean(ts_delta(ebitda_to_enterprise_value_ratio_2, 20), 60)), 252))`
- **MPLPjog9** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.11, TO=0.1094, DD=0.1688。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(ts_mean(fnd6_aqc, 60), ts_mean(fnd6_dpcy, 60)), 20), 120)`
- **E5eZP2XL** (UNSUBMITTED, other): Sharpe=-0.65, Fitness=-0.23, TO=0.631, DD=0.9268。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(zscore(ts_delta(vec_avg(negative_phrase_total), 20)), 60))`
- **bldY18dl** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.26, TO=0.0943, DD=0.081。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(annual_net_income_change_percent, ts_mean(deep_value_europe_composite_score, 60))), 20)`
- **1YzqRn16** (UNSUBMITTED, other): Sharpe=-0.65, Fitness=-0.23, TO=0.6307, DD=0.9301。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(zscore(ts_delta(vec_avg(negative_phrase_total), 20)), 60))`
- **ZYKR1X03** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.23, TO=0.0366, DD=0.1328。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(annual_earnings_before_tax, ts_mean(ts_delta(fnd6_ewq_amq, 20), 60)), 252))`
- **3qeMPEo0** (UNSUBMITTED, other): Sharpe=0.54, Fitness=0.28, TO=0.0119, DD=0.1077。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(zscore(annual_book_value_per_share), 120))`
- **rKP10Wzj** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.06, TO=0.0734, DD=0.0748。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(fnd6_aox, 252), 120), 20)`
- **xAdKveab** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.11, TO=0.1075, DD=0.22。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws76_version), 40), 40))`
- **bldY6P8R** (UNSUBMITTED, other): Sharpe=-0.57, Fitness=-0.32, TO=0.0771, DD=0.4456。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **QP91vrPp** (UNSUBMITTED, other): Sharpe=-0.34, Fitness=-0.12, TO=0.1769, DD=0.215。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws76_version), 40), 40))`
- **A17RVWbd** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws76_confidence), ts_mean(vec_avg(mws76_confidence), 60))) * zscore(fnd6_custadv...`
- **d5R2KraY** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0623, DD=0.1268。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **omg1oQXJ** (UNSUBMITTED, other): Sharpe=-0.63, Fitness=-0.22, TO=0.6322, DD=0.9061。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(zscore(ts_delta(vec_avg(negative_phrase_total), 20)), 60))`
- **0mMbj0Kk** (UNSUBMITTED, other): Sharpe=0.23, Fitness=0.06, TO=0.1235, DD=0.0709。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(anl9_consensusanalysis_dataitemvalue), 40), 40))`
- **rKP1e5Nm** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0213, DD=0.2295。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(fnd6_dvc, 60), 252))`
- **vRvKrW8Q** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.02, TO=0.0796, DD=0.5027。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **d5R2bWoJ** (UNSUBMITTED, sentiment): Sharpe=-0.05, Fitness=-0.01, TO=0.7537, DD=0.86。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ts_mean(vec_avg(mws36_sentiment_positive_confidence), 5), ts_std_dev(vec_avg(mws36_sentiment_wo...`
- **3qeMexwX** (UNSUBMITTED, other): Sharpe=0.92, Fitness=0.4, TO=0.0338, DD=0.0657。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(annual_net_income_change_percent, ts_mean(ts_delta(annual_price_to_sales_ratio, 20), 100)), 252))`
- **omg1KaPk** (UNSUBMITTED, other): Sharpe=0.29, Fitness=0.07, TO=0.0374, DD=0.1136。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(fnd6_ewq_accdq, 60), 252))`
- **kqZxK0zd** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.21, TO=0.1189, DD=0.3874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **YPgjAwMq** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.1109, DD=0.1144。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ts_mean(vec_avg(anl9_detail_dataitemvalue), 60), ts_mean(vec_avg(anl9_consensusv2span_incomeoth...`
- **mLVPZXEx** (UNSUBMITTED, technical): Sharpe=-0.25, Fitness=-0.07, TO=0.1309, DD=0.1659。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)) * ts_mean(zscore(multiply(annual_e...`
- **P0OJv9V7** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.01, TO=0.069, DD=0.4757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **RR1JdQ3g** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.1183, DD=0.1401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **gJ9Ym2ZO** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.17, TO=0.2076, DD=0.3981。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **QP91nxN5** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.0752, DD=0.1053。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws76_confidence), 60), 120))`
- **P0OJnRwM** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.0815, DD=0.1462。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **QP91nYv5** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.03, TO=0.1613, DD=0.1394。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)) * signed_power(ts_std_dev(act_12m_ner_value, 20), 0.5), 20)`
- **mLVPqYXK** (UNSUBMITTED, technical): Sharpe=-0.4, Fitness=-0.1, TO=0.2526, DD=0.194。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)) * ts_mean(zscore(multiply(annual_e...`
- **9q7z9pJr** (UNSUBMITTED, other): Sharpe=-0.36, Fitness=-0.12, TO=0.1278, DD=0.2278。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)) * signed_power(ts_std_dev(act_12m_ner_value, 20), 0.5), 20)`
- **WjVENgYQ** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.0575, DD=0.1107。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws76_confidence), 60), 120))`
- **e7xlnAwg** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.04, TO=0.0542, DD=0.2887。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **3qeMEwoz** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.02, TO=0.1856, DD=0.1256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)) * signed_power(ts_std_dev(act_12m_ner_value, 20), 0.5), 20)`
- **le3LQAq8** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.01, TO=0.1082, DD=0.1016。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws76_confidence), 60), 120))`
- **e7xlq57E** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0367, DD=0.2012。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(fnd6_cogssa, 60), 120), 20)`
- **vRvKJ2Qr** (UNSUBMITTED, technical): Sharpe=-0.42, Fitness=-0.13, TO=0.1833, DD=0.2069。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)) * ts_mean(zscore(multiply(annual_e...`
- **xAdKmKzW** (UNSUBMITTED, other): Sharpe=-0.63, Fitness=-0.22, TO=0.6322, DD=0.9061。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(zscore(ts_delta(vec_avg(negative_phrase_total), 20)), 60))`
- **1YzqmXNR** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.03, TO=0.1613, DD=0.1394。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)) * signed_power(ts_std_dev(act_12m_ner_value, 20), 0.5), 20)`
- **JjvVXjgx** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.02, TO=0.1856, DD=0.1256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ner_value, 60)) * signed_power(ts_std_dev(act_12m_ner_value, 20), 0.5), 20)`
- **QP91qM0g** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.08, TO=0.3208, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl9_consensusv2span_balancesheet_dataitemvalue), 60)), 20)`
- **vRvKn273** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.1434, DD=0.1306。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl9_consensusv2span_balancesheet_dataitemvalue), 60)), 20)`
- **1YzqVwXR** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.16, TO=0.2109, DD=0.4063。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl9_consensusv2span_incomeothers_splitfactor), 60)), 20)`
- **A17Rj2gY** (UNSUBMITTED, sentiment): Sharpe=0.16, Fitness=0.03, TO=1.5222, DD=0.6308。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))), 20)`
- **omlxxmAk** (UNSUBMITTED, sentiment): Sharpe=0.07, Fitness=0.01, TO=1.5301, DD=0.647。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))), 20)`
- **58OPXnmJ** (UNSUBMITTED, technical): Sharpe=0.45, Fitness=0.15, TO=0.1921, DD=0.1033。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)), 20)`
- **QPVwRKpQ** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0623, DD=0.1268。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **0mE1LKK1** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.04, TO=0.0542, DD=0.2887。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **omlxX1xE** (UNSUBMITTED, technical): Sharpe=-0.4, Fitness=-0.1, TO=0.2526, DD=0.194。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)) * ts_mean(zscore(multiply(annual_e...`
- **vRlWo7gw** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.17, TO=0.2076, DD=0.3981。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **MPQJ2zao** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_delta(add(vec_avg(estimated_metric_value), vec_avg(event_impact_value)), 20), 100), 30))`
- **VkPARJkG** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.0815, DD=0.1462。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **YP0RY36R** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.21, TO=0.1189, DD=0.3874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **xAkJ59dp** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.1183, DD=0.1401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cashflow_dividends, 60)), 120)`
- **A1PomKml** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.03, TO=0.1052, DD=0.0571。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl9_consensusv2span_incomeeps_totime), 60)), 20)`
- **1YdrPEQ6** (UNSUBMITTED, other): Sharpe=0.48, Fitness=0.07, TO=1.3903, DD=0.1138。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_rank(vec_avg(mws76_score), 100), 10))`
- **VkPAZdG8** (UNSUBMITTED, technical): Sharpe=-0.42, Fitness=-0.13, TO=0.1833, DD=0.2069。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_ebitda_amount, daily_volume_to_shares_outstanding)) * ts_mean(zscore(multiply(annual_e...`
- **mLbEKdY2** (UNSUBMITTED, other): Sharpe=-0.57, Fitness=-0.32, TO=0.0771, DD=0.4456。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_atq, 60)), 20)`
- **ZYnOQVn0** (UNSUBMITTED, sentiment): Sharpe=0.17, Fitness=0.03, TO=1.5203, DD=0.6413。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))), 20)`
- **j20qYkQZ** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws76_confidence), ts_mean(vec_avg(mws76_confidence), 60))) * zscore(fnd6_custadv...`
- **RR8G6Yw0** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.01, TO=0.069, DD=0.4757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **JjO6xjo2** (UNSUBMITTED, sentiment): Sharpe=0.04, Fitness=0.0, TO=1.5202, DD=0.738。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))) * ts_mean(zsc...`
- **RR8Gmvez** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.02, TO=0.0796, DD=0.5027。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 60)), 120)`
- **ZYnOEp58** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.02, TO=0.1127, DD=0.2798。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(zscore(act_12m_roe_value), multiply(-0.5, ts_mean(zscore(act_12m_roe_value), 60))), 20)`
- **omlxl09E** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws76_confidence), ts_mean(vec_avg(mws76_confidence), 60))) * zscore(fnd6_custadv...`
- **j20qZj6O** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws76_confidence), ts_mean(vec_avg(mws76_confidence), 60))) * zscore(fnd6_custadv...`
- **E5E9kVo9** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.2127, DD=0.2143。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_accdq), 20)`
- **RR8GN8Ko** (UNSUBMITTED, sentiment): Sharpe=-0.45, Fitness=-0.14, TO=0.5442, DD=0.8275。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws36_sentiment_phrase_positive) * vec_avg(mws36_sentiment_phrase_negative), 5), 100))`
- **d50Nl3jg** (UNSUBMITTED, sentiment): Sharpe=-0.03, Fitness=-0.0, TO=1.5263, DD=0.7746。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))) * ts_mean(zsc...`
- **rKlZre18** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.1023, DD=0.0927。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(act_q_dps_surprisemean, 2)) * ts_rank(vec_avg(anl12_bbgnews_score), 252), 60)`
- **d50NgobX** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.1569, DD=0.243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_accdq), 20)`
- **ZYnOqkl8** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.0754, DD=0.0971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(act_q_dps_surprisemean, 2)) * ts_rank(vec_avg(anl12_bbgnews_score), 252), 60)`
- **LL10bwk1** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.03, TO=0.1414, DD=0.0754。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(act_q_dps_surprisemean, 2)) * ts_rank(vec_avg(anl12_bbgnews_score), 252), 60)`
- **ZYnOw2zQ** (UNSUBMITTED, sentiment): Sharpe=0.02, Fitness=0.0, TO=1.5217, DD=0.75。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(vec_avg(mws36_sentiment_phrase_negative), log(vec_avg(mws36_total_words)))) * ts_mean(zsc...`
- **6X95gdOL** (UNSUBMITTED, other): Sharpe=-0.34, Fitness=-0.12, TO=0.2099, DD=0.3396。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(vec_avg(mws36_novelty), vec_avg(mws36_total_words)), 20), 30))`
- **E5E9oZa1** (UNSUBMITTED, sentiment): Sharpe=-0.54, Fitness=-0.19, TO=0.521, DD=0.895。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws36_sentiment_phrase_positive) * vec_avg(mws36_sentiment_phrase_negative), 5), 100))`
- **gJMnOQWM** (UNSUBMITTED, sentiment): Sharpe=-0.53, Fitness=-0.19, TO=0.5133, DD=0.8959。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws36_sentiment_phrase_positive) * vec_avg(mws36_sentiment_phrase_negative), 5), 100))`
- **e70Xw8Yd** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.1734, DD=0.2645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebs_surprisemean), 20)`
- **omlxpAmm** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(vec_avg(daily_event_earnings_release_time))`
- **JjO6wE02** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.04, TO=0.32, DD=0.1949。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_accdq), 20)`
- **E5E97OVK** (UNSUBMITTED, sentiment): Sharpe=0.05, Fitness=0.01, TO=0.2039, DD=0.3681。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(vec_avg(mws36_sentiment_phrase_positive), 50), 20))`
- **A1Po9GgQ** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.05, TO=0.611, DD=0.4753。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(rank(vec_avg(mws36_relevance)), 20), 5))`
- **RR8GMrKe** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.03, TO=0.1094, DD=0.2311。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebs_surprisemean), 20)`
- **XgndmxeX** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(vec_avg(daily_event_earnings_release_time))`
- **akn5jw5R** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.01, TO=0.2812, DD=0.2021。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebs_surprisemean), 20)`
- **xAkJO3bb** (UNSUBMITTED, other): Sharpe=0.55, Fitness=0.13, TO=1.3883, DD=0.268。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(anl9_daily_numupunfiltered)), 20)`
- **N1rYxQop** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.751, DD=0.4818。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws54_factor), 40)) * signed_power(rank(vec_avg(entity_relevance_score)), ts_mean(rank...`
- **1YdrYr6R** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=1.0516, DD=0.5643。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(negative_phrase_total) * vec_avg(mws36_relevance), 1)), 20)`
- **np2LpXnd** (UNSUBMITTED, other): Sharpe=0.77, Fitness=0.87, TO=0.097, DD=0.3024。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_bps_value, 60)), 252)`
- **zqmVJ2X1** (UNSUBMITTED, other): Sharpe=0.29, Fitness=0.04, TO=1.6037, DD=0.2666。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(anl16_aftercons_difference_fast_d1)), 20)`
- **6X9k1bvK** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.03, TO=0.1728, DD=0.0368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_afterest_stdvalue), 60)), 20)`
- **QPV8JoYX** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.12, TO=0.1334, DD=0.0368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_afterest_stdvalue), 60)), 20)`
- **VkPWVG38** (UNSUBMITTED, other): Sharpe=0.31, Fitness=0.04, TO=1.5809, DD=0.2553。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(anl16_aftercons_difference_fast_d1)), 20)`
- **j207zGZ9** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.03, TO=0.2498, DD=0.0574。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_afterest_stdvalue), 60)), 20)`
- **KP91Pb3z** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.04, TO=1.574, DD=0.2528。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(anl16_aftercons_difference_fast_d1)), 20)`
- **Xgn3032b** (UNSUBMITTED, other): Sharpe=-0.34, Fitness=-0.07, TO=0.2297, DD=0.1835。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_aftercons_numitems_fast_d1), 60)), 20)`
- **np2jjmnl** (UNSUBMITTED, sentiment): Sharpe=0.01, Fitness=0.0, TO=0.2783, DD=0.1563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws36_sentiment_negative_confidence), 60)), 20)`
- **d50MMjmK** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.02, TO=0.1541, DD=0.1308。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(annual_revenue_per_share, 120), 20), 60)`
- **O0ZLdN7Y** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.28, TO=0.1218, DD=0.0677。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(divide(fnd6_ewq_dvtq, current_enterprise_value), 60)), 20)`
- **WjGZrq7k** (UNSUBMITTED, other): Sharpe=-0.32, Fitness=-0.08, TO=0.1488, DD=0.185。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_aftercons_numitems_fast_d1), 60)), 20)`
- **O0ZLVe31** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.1566, DD=0.196。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(multiply(current_enterprise_value, fnd6_ewq_dfxaq), 60)), 20)`
- **JjOAzA8O** (UNSUBMITTED, other): Sharpe=-0.48, Fitness=-0.18, TO=0.1608, DD=0.3338。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_chechy) * signed_power(fnd6_amsa, ts_mean(fnd6_amsa, 120)), 20)`
- **JjOAzOp2** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.08, TO=0.0865, DD=0.2268。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cptnewq_ceqq) * signed_power(fnd6_dc, 0.5), 20)`
- **N1rdzAmo** (UNSUBMITTED, sentiment): Sharpe=0.09, Fitness=0.02, TO=0.0851, DD=0.1464。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_zscore(ts_rank(vec_avg(mws36_sentiment_words_positive), 20), 50), 100))`
- **xAkLGQkg** (UNSUBMITTED, other): Sharpe=-0.44, Fitness=-0.18, TO=0.1066, DD=0.3189。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_chechy) * signed_power(fnd6_amsa, ts_mean(fnd6_amsa, 120)), 20)`
- **9qreMbOo** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.01, TO=0.2393, DD=0.0729。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl82_delta_ebty_y1_mada, 60)), 20)`
- **xAkL2JYW** (UNSUBMITTED, other): Sharpe=-0.82, Fitness=-0.32, TO=0.1338, DD=0.2527。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ttmfcfp, 60)) * signed_power(mdl177_global_actrtn60m, 0.5), 20)`
- **d50M3xGg** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.03, TO=0.0661, DD=0.1225。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_chgollev_alt, 60)) * signed_power(fnd6_ewq_dvtq, 0.5), 20)`
- **2rLgX1YN** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.06, TO=0.1674, DD=0.074。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl82_delta_ebty_y1_mada, 60)), 20)`
- **omlbRLYJ** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.06, TO=0.2186, DD=0.3661。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebs_surprisenum) * signed_power(act_12m_eps_value, 0.5), 20)`
- **E5EjNGvL** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.1, TO=0.0764, DD=0.2495。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_chechy) * signed_power(fnd6_amsa, ts_mean(fnd6_amsa, 120)), 20)`
- **wpldNP0Y** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.1, TO=0.112, DD=0.1221。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(daily_volume_to_shares_outstanding, 60) * signed_power(fnd6_dvt, 0.5), 120), 20)`
- **88Q0GjMV** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.22, TO=0.179, DD=0.0793。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_apo, 60)) * signed_power(mdl177_eur_mgteff_qvaeur_alt, 0.5), 20)`
- **O0ZL6GeJ** (UNSUBMITTED, sentiment): Sharpe=-0.18, Fitness=-0.02, TO=1.6293, DD=0.3356。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_am, 120)) * signed_power(vec_avg(mws84_sentiment), 0.5), 60)`
- **np2j6oAq** (UNSUBMITTED, sentiment): Sharpe=-0.19, Fitness=-0.02, TO=1.6238, DD=0.3381。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_am, 120)) * signed_power(vec_avg(mws84_sentiment), 0.5), 60)`
- **wpldNwE1** (UNSUBMITTED, other): Sharpe=1.87, Fitness=1.34, TO=0.1475, DD=0.0348。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **d50Mazqg** (UNSUBMITTED, other): Sharpe=0.95, Fitness=0.47, TO=0.0533, DD=0.0556。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **xAkLv2kN** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.01, TO=0.0135, DD=0.5155。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(fnd6_chech, fnd6_accli), 20)`
- **d50MaaZJ** (UNSUBMITTED, other): Sharpe=-1.13, Fitness=-0.55, TO=0.1592, DD=0.4165。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ebitdaev_alt) * signed_power(mdl177_global_actrtn18m, 0.5), 60)`
- **np2jaZR8** (UNSUBMITTED, other): Sharpe=0.74, Fitness=0.34, TO=0.1429, DD=0.0692。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(add(multiply(ts_zscore(fnd6_dfxay, 60), -0.5), multiply(ts_zscore(mdl177_dvm_roe_alt, 120), 0.3))) * s...`
- **6X9WMP1J** (UNSUBMITTED, other): Sharpe=0.8, Fitness=0.24, TO=0.2922, DD=0.0565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_apo, 60)) * signed_power(mdl177_eur_mgteff_qvaeur_alt, 0.5), 20)`
- **LL1vKAKv** (UNSUBMITTED, technical): Sharpe=0.26, Fitness=0.06, TO=0.0938, DD=0.1112。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(daily_volume_to_shares_outstanding, 60) * signed_power(fnd6_dvt, 0.5), 120), 20)`
- **88Q0N5jv** (UNSUBMITTED, other): Sharpe=0.35, Fitness=0.25, TO=0.0695, DD=0.3256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_roe_value, 120)), 20)`
- **WjGZlElO** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.11, TO=0.1445, DD=0.3314。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebs_surprisenum) * signed_power(act_12m_eps_value, 0.5), 20)`
- **WjGZOeMO** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.26, TO=0.1169, DD=0.0773。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_apo, 60)) * signed_power(mdl177_eur_mgteff_qvaeur_alt, 0.5), 20)`
- **YP0VMEMl** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.25, TO=0.0079, DD=0.737。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(fnd6_chech, fnd6_accli), 20)`
- **kq0wg2a8** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.16, TO=0.0629, DD=0.1878。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ebitdaev_alt) * signed_power(mdl177_global_actrtn18m, 0.5), 60)`
- **MPQEa1An** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.16, TO=0.0947, DD=0.1427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(daily_event_record_start_time), 60)), 120)`
- **e70Y3nz6** (UNSUBMITTED, other): Sharpe=1.24, Fitness=0.14, TO=0.0946, DD=0.0004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_dpy) * signed_power(fnd109_stock_holdings, 0.5), 20)`
- **gJMl8vzK** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.1054, DD=0.1701。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_dvt, 60)), 20)`
- **0mEVpmwq** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.05, TO=1.5747, DD=0.7258。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_ebtq_q3_predict) * signed_power(vec_avg(anl16_afterest_difference_fast_d1), 0.5), 20)`
- **Xgn386zx** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.05, TO=0.0488, DD=0.1716。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_ebt_value * act_12m_sal_value, 60)), 120)`
- **VkPrPM70** (UNSUBMITTED, other): Sharpe=-0.44, Fitness=-0.2, TO=0.3322, DD=0.8813。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_eur_balshtrank_qvaeur_alt) * signed_power(fnd6_ewq_eqrtq, fnd6_cptnewq_dlttq), 20)`
- **A1PpPWAE** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.04, TO=0.1897, DD=0.1782。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cptnewq_ceqq) * signed_power(fnd6_dc, 0.5), 20)`
- **RR8OreGe** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.13, TO=0.2028, DD=0.7013。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_eur_balshtrank_qvaeur_alt) * signed_power(fnd6_ewq_eqrtq, fnd6_cptnewq_dlttq), 20)`
- **WjGZ9pvj** (UNSUBMITTED, technical): Sharpe=-0.3, Fitness=-0.07, TO=0.1505, DD=0.1559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(daily_volume_to_shares_outstanding, 0.5), 20)`
- **9qre9Eg2** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.1147, DD=0.0775。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(event_announcement_time), 60)), 20)`
- **VkPrX808** (UNSUBMITTED, other): Sharpe=-0.47, Fitness=-0.07, TO=1.5696, DD=0.5452。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_gpsq_q1_predict) * signed_power(vec_avg(anl16_aftercons_low_fast_d1), 0.5), 60)`
- **9qreaOn9** (UNSUBMITTED, other): Sharpe=-0.67, Fitness=-0.21, TO=0.0757, DD=0.1507。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_chgollev, 60)), 20)`
- **xAkLPWdb** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.19, TO=0.1426, DD=0.0719。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl9_d1_recommendationnumericvalue, 60)) * signed_power(act_q_bps_value, 0.5), 20)`
- **MPQEK779** (UNSUBMITTED, technical): Sharpe=-2.3, Fitness=-1.14, TO=0.2549, DD=0.647。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ebitdaev_alt) * signed_power(daily_volume_to_shares_outstanding, 0.5), 20)`
- **1Yd8a7nK** (UNSUBMITTED, technical): Sharpe=-0.16, Fitness=-0.03, TO=0.1046, DD=0.171。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(daily_volume_to_shares_outstanding, 0.5), 20)`
- **WjGZWm7G** (UNSUBMITTED, other): Sharpe=-0.48, Fitness=-0.07, TO=1.5634, DD=0.5479。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_gpsq_q1_predict) * signed_power(vec_avg(anl16_aftercons_low_fast_d1), 0.5), 60)`
- **58Om62nJ** (UNSUBMITTED, technical): Sharpe=-1.92, Fitness=-1.28, TO=0.1333, DD=0.6171。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ebitdaev_alt) * signed_power(daily_volume_to_shares_outstanding, 0.5), 20)`
- **1Yd8mPPR** (UNSUBMITTED, other): Sharpe=0.31, Fitness=0.06, TO=0.2894, DD=0.104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl9_d1_recommendationnumericvalue, 60)) * signed_power(act_q_bps_value, 0.5), 20)`
- **MPQEXwxL** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.16, TO=0.0791, DD=0.1068。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_q_ent_surprisenum, 60)), 20)`
- **9qrebNwr** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.08, TO=0.0702, DD=0.1147。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_q_eps_surprisestd, 60)), 20)`
- **d50Mg5bx** (UNSUBMITTED, other): Sharpe=1.24, Fitness=0.14, TO=0.0946, DD=0.0004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_dpy) * signed_power(fnd109_stock_holdings, 0.5), 20)`
- **kq0wk6YP** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.03, TO=0.7919, DD=0.8371。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws54_eventsdaily_situation), 60)) * signed_power(vec_avg(mws36_novelty_newest_span), ...`
- **mLbG2eKE** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.07, TO=0.187, DD=0.8508。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(fnd6_dpsa, ts_mean(fnd6_chee, 60))) * signed_power(ts_std_dev(fnd6_cshr, 20), 0.5), 20)`
- **58Om7RQk** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.1, TO=0.0541, DD=0.1397。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(employee, 120)) * signed_power(fnd6_apch, 0.5), 60)`
- **zqmxXn38** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.05, TO=0.1077, DD=0.1409。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_q_ent_surprisenum, 60)), 20)`
- **ZYn8Z370** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.12, TO=0.0416, DD=0.2262。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_epsq_q1_madp) * ts_mean(zscore(anl82_delta_epsq_q1_madp), 60), 20)`
- **QPVxdp0Q** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=1.8746, DD=0.6882。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(act_12m_ebt_value, ts_mean(act_12m_ebt_value, 60))) * signed_power(vec_avg(anl16_afterest_stdva...`
- **omlbe76v** (UNSUBMITTED, other): Sharpe=0.6, Fitness=0.26, TO=0.1254, DD=0.0844。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_ewq_amq) * signed_power(mdl177_global_actrtn2m, 0.5), 20)`
- **ZYn8Gr2n** (UNSUBMITTED, other): Sharpe=-0.66, Fitness=-0.25, TO=0.3982, DD=0.3419。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_roe_value) * signed_power(vec_avg(anl16_afterest_difference_fast_d1), 0.5), 20)`
- **P03R9QqK** (UNSUBMITTED, other): Sharpe=-2.53, Fitness=-1.57, TO=0.2482, DD=0.9984。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_dvm_eur_composite_alt, 0.5)) * ts_mean(fnd6_ewq_dfxaq, 60), 20)`
- **j20pb7go** (UNSUBMITTED, other): Sharpe=-1.07, Fitness=-0.53, TO=0.1649, DD=0.4427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws54_keydevelopments_headline), 60)), 20)`
- **vRlE36wQ** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.03, TO=0.7932, DD=0.844。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws54_eventsdaily_situation), 60)) * signed_power(vec_avg(mws36_novelty_newest_span), ...`
- **rKlqvW5d** (UNSUBMITTED, other): Sharpe=-0.65, Fitness=-0.24, TO=0.4001, DD=0.3393。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_roe_value) * signed_power(vec_avg(anl16_afterest_difference_fast_d1), 0.5), 20)`
- **akn0Zpj1** (UNSUBMITTED, technical): Sharpe=-1.32, Fitness=-0.76, TO=0.1276, DD=0.4488。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt * current_enterprise_value, 60)) * signed_power(daily_volume_to_shares...`
- **0mEV3Q7p** (UNSUBMITTED, other): Sharpe=-1.11, Fitness=-0.63, TO=0.102, DD=0.4438。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(mdl177_dvm_dvm_eur_composite_alt, ts_mean(mdl177_dvm_dvm_eur_composite_alt, 60))) * signed_powe...`
- **YP0VKmAq** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.14, TO=0.1369, DD=0.0912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_ebitdaev, 0.5)) * ts_zscore(fnd6_apchy, 60), 20)`
- **e70YwmZ6** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.03, TO=0.1638, DD=0.5375。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(fnd6_dpsa, ts_mean(fnd6_chee, 60))) * signed_power(ts_std_dev(fnd6_cshr, 20), 0.5), 20)`
- **d50MXbrw** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.09, TO=0.0366, DD=0.126。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(mdl177_dvm_ebitdaev, 60), 252), 60)`
- **E5Ej1M3L** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.062, DD=0.084。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(ebitda_to_enterprise_value_ratio_2, 60)) * signed_power(deep_value_europe_composite_score, 0.5...`
- **xAkLq5WN** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.12, TO=0.1176, DD=0.1085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_ebitdaev, 0.5)) * ts_zscore(fnd6_apchy, 60), 20)`
- **ZYn86dOQ** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.04, TO=0.1271, DD=0.4176。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(fnd6_dpsa, ts_mean(fnd6_chee, 60))) * signed_power(ts_std_dev(fnd6_cshr, 20), 0.5), 20)`
- **xAkLqjOg** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.1577, DD=0.0784。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 60)) * signed_power(mdl177_global_actrtn12m, 0.5), 20)`
- **pwl2mKVx** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.05, TO=0.102, DD=0.122。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(employee, 120)) * signed_power(fnd6_apch, 0.5), 60)`
- **Xgn3mz3x** (UNSUBMITTED, other): Sharpe=-0.64, Fitness=-0.21, TO=0.0723, DD=0.1608。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(rank(act_q_bps_surprisestd), ts_mean(rank(act_q_bps_surprisestd), 60)), 20)`
- **rKlqpeAd** (UNSUBMITTED, other): Sharpe=0.29, Fitness=0.08, TO=0.0633, DD=0.0539。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 60)) * signed_power(mdl177_global_actrtn12m, 0.5), 20)`
- **KP9olqv8** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.07, TO=0.0901, DD=0.0735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl9_d1_recommendationnumericvalue) * ts_mean(zscore(anl9_d1_recommendationnumericvalue), 60), 20)`
- **GrL21vr5** (UNSUBMITTED, other): Sharpe=-0.2, Fitness=-0.05, TO=0.1766, DD=0.3284。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_cpx_surprisemean), 20)`
- **j20p2Kre** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.02, TO=0.1239, DD=0.1153。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(mdl177_global_actrtn18m, 20)), zscore(ts_mean(fnd6_dpcy, 60))), 20)`
- **9qreq8Vr** (UNSUBMITTED, other): Sharpe=2.03, Fitness=0.29, TO=0.0946, DD=0.0002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_accdq, 60)) * signed_power(fnd109_equity_issuance_score, 0.5), 20)`
- **kq0wqgwK** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.03, TO=0.0966, DD=0.0696。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 60)) * signed_power(mdl177_global_actrtn12m, 0.5), 20)`
- **E5Ej5bG9** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.07, TO=1.5182, DD=0.0832。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_ebt_surprisemean) * signed_power(vec_avg(anl16_beforecons_mean), 0.5), 20)`
- **e70Yl9RO** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.05, TO=0.072, DD=0.1521。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(mdl177_global_actrtn18m, 20)), zscore(ts_mean(fnd6_dpcy, 60))), 20)`
- **N1rdXbPe** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.07, TO=1.5511, DD=0.5769。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_eps_surprisemean) * signed_power(vec_avg(anl16_afterest_difference_fast_d1), 0.5), 60)`
- **KP9oKXap** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.05, TO=0.0722, DD=0.1246。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(employee, 120)) * signed_power(fnd6_apch, 0.5), 60)`
- **9qrezQY2** (UNSUBMITTED, other): Sharpe=-2.28, Fitness=-1.51, TO=0.175, DD=0.7966。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ebitdaev_alt) * signed_power(mdl177_dvm_tw_ep, 0.5), 20)`
- **A1PXomVX** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.0952, DD=0.1432。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(mdl177_global_actrtn18m, 20)), zscore(ts_mean(fnd6_dpcy, 60))), 20)`
- **781PeLJ2** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.04, TO=1.5908, DD=0.2504。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_prr_value) * signed_power(vec_avg(anl16_beforecons_mean_fast_d1), 0.5), 20)`
- **zqm7lYJo** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.05, TO=0.1773, DD=0.1911。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_accdq, 60)) * signed_power(fnd6_dpcy, 0.5), 20)`
- **blq0Azvm** (UNSUBMITTED, other): Sharpe=-0.27, Fitness=-0.07, TO=0.0738, DD=0.2245。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(fnd6_chech, fnd6_aox), 20)`
- **LL1o3Ngv** (UNSUBMITTED, other): Sharpe=2.03, Fitness=0.29, TO=0.0946, DD=0.0002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_accdq, 60)) * signed_power(fnd109_equity_issuance_score, 0.5), 20)`
- **2rLVWwM5** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.04, TO=1.5844, DD=0.2534。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_prr_value) * signed_power(vec_avg(anl16_beforecons_mean_fast_d1), 0.5), 20)`
- **aknmQeY9** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.06, TO=0.0795, DD=0.0603。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(mdl177_global_actrtn3m, 20)), 1.5) * zscore(annual_debt_to_equity_ratio), 20)`
- **LL1omN7v** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.0583, DD=0.186。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev_alt, 60)) * signed_power(fnd6_chech, fnd6_aox), 20)`
- **A1PXr3XQ** (UNSUBMITTED, other): Sharpe=2.03, Fitness=0.29, TO=0.0946, DD=0.0002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_accdq, 60)) * signed_power(fnd109_equity_issuance_score, 0.5), 20)`
- **YP03ErQA** (UNSUBMITTED, sentiment): Sharpe=-0.04, Fitness=-0.0, TO=1.6571, DD=0.263。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cptnewq_actq) * signed_power(vec_avg(mws84_sentiment), 0.5), 20)`
- **E5EnNLEm** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.11, TO=0.0411, DD=0.1763。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(multiply(fnd6_cheb, divide(fnd17_10_rhsfcfq, annual_total_revenue)), 252), 60)`
- **gJMNrp90** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.11, TO=0.1668, DD=0.3522。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cflaoth) * signed_power(fnd6_dd1, 0.5), 20)`
- **LL1oKmQ2** (UNSUBMITTED, other): Sharpe=-0.94, Fitness=-0.5, TO=0.1332, DD=0.4265。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(ts_rank(fnd6_am, 60), signed_power(mdl177_dvm_past_alt, 0.5))), 20)`
- **zqm7kLr1** (UNSUBMITTED, other): Sharpe=-0.8, Fitness=-0.4, TO=0.1327, DD=0.3838。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(ts_rank(fnd6_am, 60), signed_power(mdl177_dvm_past_alt, 0.5))) * signed_power(ts_mean(fnd6_ch...`
- **LL1o7nLm** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.05, TO=0.0463, DD=0.1328。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_q_ebi_surprisenum, 60)), 120)`
- **O0ZdZm6p** (UNSUBMITTED, other): Sharpe=-1.23, Fitness=-0.52, TO=0.168, DD=0.3312。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ttmfcfp) * signed_power(mdl177_global_actrtn1m, 0.5), 20)`
- **9qr5wrWx** (UNSUBMITTED, technical): Sharpe=-0.61, Fitness=-0.2, TO=0.1431, DD=0.2322。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(deep_value_europe_composite_score, 60)) * signed_power(daily_volume_to_shares_outstanding, 0.5...`
- **mLbnXwv6** (UNSUBMITTED, other): Sharpe=0.35, Fitness=0.14, TO=0.1516, DD=0.1709。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(anl16_aftercons_low), 252)), 60)`
- **lelwrwrA** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.221, DD=0.3636。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cflaoth) * signed_power(fnd6_dd1, 0.5), 20)`
- **RR8xdvRn** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.1436, DD=0.433。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws54_factor), 60)), 252)`
- **QPVREOqQ** (UNSUBMITTED, technical): Sharpe=-0.55, Fitness=-0.19, TO=0.0982, DD=0.24。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(deep_value_europe_composite_score, 60)) * signed_power(daily_volume_to_shares_outstanding, 0.5...`
- **O0Zdo7Lb** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.02, TO=0.1061, DD=0.1083。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(zscore(mdl177_eur_mgteff_qvaeur), multiply(-0.5, zscore(ts_mean(deep_value_europe_composite_score, 60))))...`
- **blq0vpvp** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.1, TO=0.1278, DD=0.6284。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd6_cflaoth) * signed_power(fnd6_dd1, 0.5), 20)`
- **N1rEnYq7** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.03, TO=0.0653, DD=0.1416。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl82_delta_epsy_y1_mada, 60)), 252)`
- **P03Ln5EW** (UNSUBMITTED, other): Sharpe=-1.33, Fitness=-0.47, TO=0.2699, DD=0.3582。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ttmfcfp) * signed_power(mdl177_global_actrtn1m, 0.5), 20)`
- **58OKLwjX** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.03, TO=0.0356, DD=0.1125。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 120)), 60)`
- **LL1onxRv** (UNSUBMITTED, technical): Sharpe=-0.75, Fitness=-0.23, TO=0.1933, DD=0.2322。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(deep_value_europe_composite_score, 60)) * signed_power(daily_volume_to_shares_outstanding, 0.5...`
- **QPVR2gLW** (UNSUBMITTED, other): Sharpe=-0.79, Fitness=-0.12, TO=1.5098, DD=0.4922。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_cps_surprisemean) * signed_power(vec_avg(anl16_afterest_difference), 0.5), 20)`
- **ZYnV2WbQ** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.13, TO=0.1121, DD=0.1461。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 60)) * signed_power(mdl177_dvm_chgollev, 0.5), 20)`
- **vRl7eabz** (UNSUBMITTED, other): Sharpe=-0.99, Fitness=-0.45, TO=0.122, DD=0.2817。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(mdl177_dvm_ttmfcfp) * signed_power(mdl177_global_actrtn1m, 0.5), 20)`
- **P03LwJrK** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.0284, DD=0.1123。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl177_dvm_ebitdaev, 120)), 60)`
- **d50Jl99w** (UNSUBMITTED, other): Sharpe=-2.23, Fitness=-1.28, TO=0.2783, DD=0.9637。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_ebitdaev_alt, 0.5)) * signed_power(rank(fnd6_cogssa), ts_mean(rank(fnd6_cogssa...`
- **3qRmxbZ6** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.43, TO=0.096, DD=0.2152。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_eps_value, 60)) * signed_power(act_q_cps_value, act_12m_sal_value), 120)`
- **E5EnYqer** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.1998, DD=0.1762。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_q_eps_value) * ts_mean(zscore(act_12m_sal_value), 60), 20)`
- **vRl7nbZw** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.13, TO=1.7086, DD=0.125。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_eps_value) * signed_power(anl82_delta_epsq_q1_mada, 0.5), 20)`
- **wpl7wA96** (UNSUBMITTED, other): Sharpe=0.71, Fitness=0.13, TO=1.7155, DD=0.1317。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(act_12m_eps_value) * signed_power(anl82_delta_epsq_q1_mada, 0.5), 20)`
- **1Yd3VKAK** (UNSUBMITTED, other): Sharpe=-11.18, Fitness=-12.6, TO=1.0, DD=0.0102。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(daily_event_record_end_time)) * signed_power(vec_avg(event_certainty_score), 0.5), 20)`
- **N1rEW1pL** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.03, TO=0.6699, DD=0.2929。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(ts_zscore(fnd6_cptnewq_revtq, 20), signed_power(mdl177_dvm_roe, 0.5))) * ts_mean(zscore(s...`
- **gJMN7xNK** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.1653, DD=0.3758。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_ebitdaev_alt, 0.5)) * ts_zscore(fnd6_dfxa, 60), 20)`
- **9qr5gqA9** (UNSUBMITTED, other): Sharpe=0.76, Fitness=0.54, TO=0.0776, DD=0.1871。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(act_12m_eps_value, 60)) * signed_power(act_q_cps_value, act_12m_sal_value), 120)`
- **xAk7M5VW** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.01, TO=0.5084, DD=0.327。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(ts_zscore(fnd6_cptnewq_revtq, 20), signed_power(mdl177_dvm_roe, 0.5))) * ts_mean(zscore(s...`
- **WjGrm0XN** (UNSUBMITTED, other): Sharpe=-0.86, Fitness=-0.13, TO=1.5272, DD=0.4325。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_epsy_y1_predict) * signed_power(vec_avg(anl16_aftercons_difference), 0.5), 20)`
- **aknm3zq1** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.0, TO=0.1961, DD=0.1353。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(mdl177_eur_mgteff_qvaeur_alt), signed_power(ts_zscore(fnd6_ewq_eqrtq, 60), 0.5)), 20)`
- **E5EnAakG** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.04, TO=0.1696, DD=0.4449。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(mws54_keydevelopments_situation)) * signed_power(zscore(vec_avg(mws36_key_event_confidence)), ...`
- **d50Jwg52** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.1406, DD=0.3476。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl177_dvm_ebitdaev_alt, 0.5)) * ts_zscore(fnd6_dfxa, 60), 20)`
- **vRl7Vg6r** (UNSUBMITTED, other): Sharpe=0.47, Fitness=0.13, TO=0.5735, DD=0.1372。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(act_12m_opr_value, act_12m_ner_value)) * signed_power(vec_avg(anl16_aftercons_numitems), 0.5), 20)`
- **rKlaXPJd** (UNSUBMITTED, other): Sharpe=-0.94, Fitness=-0.14, TO=1.5532, DD=0.4558。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl82_delta_epsy_y1_predict) * signed_power(vec_avg(anl16_aftercons_difference), 0.5), 20)`
- **GrLjJE7P** (UNSUBMITTED, other): Sharpe=-1.69, Fitness=-1.1, TO=0.16, DD=0.7245。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(add(signed_power(divide(global_cash_to_liabilities_ratio, ts_mean(global_cash_to_liabilities_ratio, 12...`
- **1Yd3EvQz** (UNSUBMITTED, other): Sharpe=-2.16, Fitness=-1.09, TO=0.2928, DD=0.7752。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ebitda_to_enterprise_value_ratio_2) * signed_power(mdl177_dvm_ttmfcfp_alt, 0.5), 20)`
- **WjGr8MXk** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.04, TO=0.1696, DD=0.4499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(mws54_keydevelopments_situation)) * signed_power(zscore(vec_avg(mws36_key_event_confidence)), ...`
- **xAk70N1J** (UNSUBMITTED, other): Sharpe=0.46, Fitness=0.13, TO=0.5699, DD=0.1665。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(act_12m_opr_value, act_12m_ner_value)) * signed_power(vec_avg(anl16_aftercons_numitems), 0.5), 20)`
- **JjOaZ0al** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.136, DD=0.1245。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(mdl177_eur_mgteff_qvaeur_alt), signed_power(ts_zscore(fnd6_ewq_eqrtq, 60), 0.5)), 20)`
- **RR8xQama** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.18, TO=0.2578, DD=0.0725。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd6_cptnewq_ceqq * fnd6_cptnewq_atq, 60)) * signed_power(mdl177_dvm_chgollev, 0.5), 20)`
- **LL1oaaVa** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.04, TO=0.1696, DD=0.4514。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(mws54_keydevelopments_situation)) * signed_power(zscore(vec_avg(mws36_key_event_confidence)), ...`
- **QPVRJRXK** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.1501, DD=0.252。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(fnd6_chechy, signed_power(mdl177_dvm_past_alt, 0.5))) * ts_zscore(fnd6_acox, 60), 20)`
- **A1PXWEwe** (UNSUBMITTED, other): Sharpe=-2.04, Fitness=-1.28, TO=0.1767, DD=0.731。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ebitda_to_enterprise_value_ratio_2) * signed_power(mdl177_dvm_ttmfcfp_alt, 0.5), 20)`
- **58OKbz9k** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.1049, DD=0.1923。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(annual_total_shareholder_equity, 60), 20)`
- **vRl7qz7w** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.1301, DD=0.2593。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(fnd6_chechy, signed_power(mdl177_dvm_past_alt, 0.5))) * ts_zscore(fnd6_acox, 60), 20)`
- **3qRmbWkO** (UNSUBMITTED, other): Sharpe=-2.17, Fitness=-1.57, TO=0.1632, DD=0.8805。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(deep_value_europe_composite_score, signed_power(mdl177_dvm_ttmfcfp, 0.5))), 60)`
- **GrLj17KO** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.1249, DD=0.1609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(annual_total_shareholder_equity, 60), 20)`
- **pwlbwaZv** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.02, TO=0.1108, DD=0.2201。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(amortization_goodwill_intangibles, 60)), 20)`
- **d50J2Q8v** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.29, TO=0.0661, DD=0.127。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_abepsxclxo, 60)), 252)`
- **E5EnZaZ9** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.03, TO=0.1745, DD=0.1833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aebit, 120)), 40)`
- **j20k5Wp5** (UNSUBMITTED, other): Sharpe=0.54, Fitness=0.22, TO=0.2518, DD=0.1601。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_aebitd) * signed_power(anl46_performancepercentile, 0.5), 20)`
- **MPQNJkgr** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.09, TO=0.0723, DD=0.2144。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(amortization_goodwill_intangibles, 60)), 20)`
- **6X9L5aWp** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.02, TO=0.1132, DD=0.1975。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aebit, 120)), 40)`
- **VkPbW80w** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.03, TO=0.0481, DD=0.1844。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(current_enterprise_value, 60)), 120)`
- **6X9LWonK** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.0868, DD=0.0205。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(multifactor_residual_volatility, ts_mean(multifactor_residual_volatility, 60))) * signed_power(...`
- **VkPbQakY** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=0.4144, DD=0.0335。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl55_groupindustry_awcm_mga, 2)) * signed_power(vec_avg(mws50_g_ens_elapsed), 0.5), 20)`
- **np25G793** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.1, TO=0.0308, DD=0.1609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(downside_market_beta, 60)), 120)`
- **A1P88WaW** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.06, TO=0.2589, DD=0.3552。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(assets_curr) * signed_power(fnd17_aastturn, 0.5), 20)`
- **d50rrkOJ** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.0809, DD=0.1572。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aebit, 120)), 40)`
- **3qRvO8XX** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.07, TO=0.056, DD=0.1839。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_ase_mcwa, 60)), 252)`
- **E5EPMmQr** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.16, TO=0.1645, DD=0.1414。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aastturn, 60)), 20)`
- **E5EPM6q1** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.03, TO=0.0792, DD=0.3616。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(enterprise_value_to_ebitda_current, 60)), 20)`
- **rKlMwXGE** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=0.4144, DD=0.0335。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mdl55_groupindustry_awcm_mga, 2)) * signed_power(vec_avg(mws50_g_ens_elapsed), 0.5), 20)`
- **1YdRanom** (UNSUBMITTED, sentiment): Sharpe=0.44, Fitness=0.05, TO=1.5006, DD=0.0843。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mean_secondary_sentiment_score_transfer, 0.5)) * rank(skew_primary_sentiment_score_transf...`
- **0mELKzL6** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.2271, DD=0.2614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(rank(mdl140_qes_sinc_comp), ts_mean(rank(mdl140_qes_sinc_comp), 60)), 20)`
- **pwlk1nX6** (UNSUBMITTED, sentiment): Sharpe=1.44, Fitness=1.16, TO=0.0933, DD=0.0539。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.3333*rank(subtract(anl46_sentiment, ...`
- **88QZ6AEm** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.12, TO=0.1519, DD=0.0969。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_neut, 20)) * signed_power(rank(mdl140_qes_sinc_comp), 0.5), 20)`
- **lelY2g82** (UNSUBMITTED, other): Sharpe=-0.68, Fitness=-0.34, TO=0.2158, DD=0.673。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accrued_assets_total, 60)), 20)`
- **1YdR1akJ** (UNSUBMITTED, sentiment): Sharpe=0.36, Fitness=0.04, TO=1.5019, DD=0.0917。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(signed_power(mean_secondary_sentiment_score_transfer, 0.5)) * rank(skew_primary_sentiment_score_transf...`
- **GrLN0xg0** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.04, TO=0.1707, DD=0.1102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_neut, 20)) * signed_power(rank(mdl140_qes_sinc_comp), 0.5), 20)`
- **mLbNe7YW** (UNSUBMITTED, sentiment): Sharpe=1.64, Fitness=1.33, TO=0.14, DD=0.052。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.6*ts_rank(ts_mean(add(fnd17_2_reptoprcexrate, ts_std_dev(divide(fnd17_1_usdtorepexrate, inverse(fnd17_2_usd...`
- **omlXQJnn** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.01, TO=0.2134, DD=0.1147。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_neut, 20)) * signed_power(rank(mdl140_qes_sinc_comp), 0.5), 20)`
- **rKlwQe58** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.1056, DD=0.1697。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_agrosmgn2, 60)) * signed_power(fnd17_4_reptoprcexrate, 0.5), 20)`
- **MPQnwl5o** (UNSUBMITTED, other): Sharpe=0.47, Fitness=0.15, TO=0.1647, DD=0.0809。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(rank(mdl140_qes_sinc_comp), ts_mean(rank(mdl140_qes_sinc_comp), 60)), 20)`
- **9qr3QKEx** (UNSUBMITTED, other): Sharpe=-1.56, Fitness=-0.92, TO=0.2998, DD=0.7274。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(enterprise_value_to_ebitda_current) * signed_power(anl46_performancepercentile, 0.5), 20)`
- **3qROLj1Q** (UNSUBMITTED, other): Sharpe=-0.92, Fitness=-0.6, TO=0.1467, DD=0.4786。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(enterprise_value_to_ebitda_current) * signed_power(anl46_performancepercentile, 0.5), 20)`
- **88QZ1v6W** (UNSUBMITTED, other): Sharpe=0.04, Fitness=0.01, TO=0.0555, DD=0.2745。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_book_value_per_share, 60)), 252)`
- **np2lVNEM** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.0992, DD=0.3645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_book_value_per_share, 60)), 252)`
- **1YdREgrX** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=1.3542, DD=0.1001。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(mws50_ens)) * ts_mean(zscore(vec_avg(mws50_ens)), 60), 20)`
- **WjGR8Qqd** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.0981, DD=0.0306。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(historical_realized_volatility, ts_mean(historical_realized_volatility, 60))), 40)`
- **58O10Kjk** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.01, TO=0.1033, DD=0.0321。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(historical_realized_volatility, ts_mean(historical_realized_volatility, 60))), 40)`
- **3qROw2wP** (UNSUBMITTED, cashflow): Sharpe=1.87, Fitness=1.25, TO=0.0828, DD=0.0401。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **rKlwY0x9** (UNSUBMITTED, sentiment): Sharpe=1.64, Fitness=1.36, TO=0.1334, DD=0.0595。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.12088049110611111*ts_rank(ts_mean(add(fnd17_2_reptoprcexrate, ts_std_dev(divide(fnd17_1_usdtorepexrate, inv...`
- **mLbNwKw9** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=1.3551, DD=0.0997。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(vec_avg(mws50_ens)) * ts_mean(zscore(vec_avg(mws50_ens)), 60), 20)`
- **9qr2em6r** (UNSUBMITTED, sentiment): Sharpe=1.71, Fitness=1.27, TO=0.1674, DD=0.0486。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.3333*rank(subtract(anl46_sentiment, ...`
- **6X926m17** (UNSUBMITTED, cashflow): Sharpe=1.87, Fitness=1.25, TO=0.0828, DD=0.0401。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **xAkEExen** (UNSUBMITTED, cashflow): Sharpe=1.83, Fitness=1.22, TO=0.067, DD=0.0389。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **np2Xrqzx** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.0735, DD=0.1323。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_alphadecay, 60)), 20)`
- **N1r2e9pL** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.02, TO=0.4273, DD=0.0882。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accumulated_other_assets * accounts_total_current_assets_2, 60)) * signed_power(vec_avg(mws50_...`
- **rKlnPogE** (UNSUBMITTED, other): Sharpe=-0.92, Fitness=-0.36, TO=0.1851, DD=0.3113。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(subtract(mdl140_qes_sinc_sensitivity, ts_mean(mdl140_qes_sinc_sensitivity, 60)), ts_std_dev(mdl...`
- **P03A30vw** (UNSUBMITTED, sentiment): Sharpe=1.64, Fitness=1.36, TO=0.1334, DD=0.0595。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.8800457345255996*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.11995426547440037*ts_ran...`
- **JjO2p3O2** (UNSUBMITTED, sentiment): Sharpe=1.44, Fitness=0.39, TO=0.7998, DD=0.0558。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(mdl106_fmb, fnd17_acurliab)) * signed_power(rank(anl46_sentiment), 0.5), 20)`
- **vRloLdR3** (UNSUBMITTED, other): Sharpe=-1.63, Fitness=-0.5, TO=0.7998, DD=0.512。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(mdl106_mkt_cap, ts_mean(mdl106_mkt_cap, 120))) * signed_power(anl46_performancepercentile, 0.5)...`
- **ZYn1owK8** (UNSUBMITTED, cashflow): Sharpe=-0.18, Fitness=-0.04, TO=0.1042, DD=0.1165。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_agrosmgn) * ts_zscore(cashflow_op, 60), 20)`
- **pwlp8g1X** (UNSUBMITTED, sentiment): Sharpe=0.28, Fitness=0.05, TO=0.5329, DD=0.1941。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility, 60)) * signed_power(earnings_release_sentiment_score, 0.5), 20)`
- **6X92aJZL** (UNSUBMITTED, sentiment): Sharpe=0.41, Fitness=0.08, TO=0.69, DD=0.1178。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility, 60)) * signed_power(earnings_release_sentiment_score, 0.5), 20)`
- **9qr2ANQ2** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.03, TO=0.0571, DD=0.2317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_aroe_80pctl, 60)), 20)`
- **E5E2rpo9** (UNSUBMITTED, sentiment): Sharpe=1.65, Fitness=1.36, TO=0.1359, DD=0.0558。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.6*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.4*ts_rank(ts_mean(add(fnd17_2_reptoprce...`
- **RR8varxd** (UNSUBMITTED, cashflow): Sharpe=-0.2, Fitness=-0.05, TO=0.117, DD=0.131。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_agrosmgn) * ts_zscore(cashflow_op, 60), 20)`
- **P03A61Lw** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.02, TO=0.1181, DD=0.2478。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_aroe_80pctl, 60)), 20)`
- **78120GMO** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.06, TO=0.1379, DD=0.2847。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(fnd17_adebteps, signed_power(fnd17_adivchg, 0.5))) * ts_mean(zscore(multiply(fnd17_adebteps, ...`
- **gJM0qMzm** (UNSUBMITTED, other): Sharpe=-0.36, Fitness=-0.09, TO=0.0544, DD=0.0925。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws50_aes_2), 60)), 20)`
- **1Yd26ZAm** (UNSUBMITTED, sentiment): Sharpe=1.52, Fitness=1.06, TO=0.1909, DD=0.1296。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.25*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.25*rank(subtract(anl46_sentiment, subt...`
- **lelNxNQ8** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.03, TO=0.2013, DD=0.3233。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(fnd17_adebteps, signed_power(fnd17_adivchg, 0.5))) * ts_mean(zscore(multiply(fnd17_adebteps, ...`
- **58O2RaAz** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.05, TO=0.1033, DD=0.2458。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(cash * equity, 60)), 120)`
- **akng37E1** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.16, TO=0.0577, DD=0.1282。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_a2netmrgn, 252)), 60)`
- **gJM0zJkv** (UNSUBMITTED, sentiment): Sharpe=1.69, Fitness=1.43, TO=0.1286, DD=0.0558。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.3333*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.3333*rank(subtract(anl46_sentiment, ...`
- **O0Z2YwK7** (UNSUBMITTED, sentiment): Sharpe=1.62, Fitness=1.36, TO=0.1228, DD=0.0528。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.25*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.25*rank(add(anl46_sentiment, anl46_exp...`
- **zqmLMzm8** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.04, TO=1.3027, DD=0.0997。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_payable_deferred) * signed_power(vec_avg(mws50_ens_2), 0.5), 20)`
- **e70Wm8Vg** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.02, TO=0.3934, DD=0.0651。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multiply(annual_earnings_before_tax, signed_power(vec_avg(company_offer_unit_price), 0.5))) * ts_mean(...`
- **1Yd2koAk** (UNSUBMITTED, other): Sharpe=0.41, Fitness=0.04, TO=1.2723, DD=0.0807。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_payable_deferred) * signed_power(vec_avg(mws50_ens_2), 0.5), 20)`
- **A1P2jdpQ** (UNSUBMITTED, sentiment): Sharpe=1.19, Fitness=0.86, TO=0.0632, DD=0.0707。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore((0.25*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + (0.25*rank(add(anl46_sentiment, anl46_exp...`
- **wplvp6G5** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.1507, DD=0.438。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_payable_trade_creditors, 60)), 20)`
- **j20M5YZ5** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.08, TO=0.1744, DD=0.2822。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl46_alphadecay) * ts_mean(zscore(fnd17_aebitd2), 60), 20)`
- **LL12P5Lv** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.1332, DD=0.1956。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl46_alphadecay) * ts_mean(zscore(fnd17_aebitd2), 60), 20)`
- **d50P2jzY** (UNSUBMITTED, technical): Sharpe=0.26, Fitness=0.07, TO=0.0547, DD=0.0601。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(daily_volume_to_shares_outstanding, 60)), 120)`
- **gJM0Y60K** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.09, TO=0.3102, DD=0.6652。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_payable_trade_creditors, 60)), 20)`
- **RR8PGonz** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.11, TO=0.15, DD=0.4874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_payable_noncurrent), 60)`
- **6X9NkdaK** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.02, TO=0.0832, DD=0.1189。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(multiply(annual_avg_shares_outstanding, capital_spending_per_share), 252)), 60)`
- **9qrknjnV** (UNSUBMITTED, other): Sharpe=-0.69, Fitness=-0.35, TO=0.0656, DD=0.0703。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_performancepercentile, 60)), 20)`
- **QPV6x90K** (UNSUBMITTED, cashflow): Sharpe=1.56, Fitness=0.96, TO=0.0413, DD=0.04。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.3333*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), ...`
- **A1PE8PMe** (UNSUBMITTED, other): Sharpe=0.82, Fitness=0.59, TO=0.5092, DD=0.4598。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3333*(rank(ts_rank(add(subtract(anl10_analyst_innovation_bps_revise_value_fy2, ts_mean(ts_delta(anl10_analys...`
- **9qrkOR8V** (UNSUBMITTED, technical): Sharpe=1.58, Fitness=1.0, TO=0.0864, DD=0.0983。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3333*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.3333*(ts_rank(divide(daily_volume_to_s...`
- **blqA13lM** (UNSUBMITTED, technical): Sharpe=1.21, Fitness=0.67, TO=0.0434, DD=0.1031。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.3333*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.3333*(ts_rank(divide(daily_volume...`
- **wplWAka6** (UNSUBMITTED, sentiment): Sharpe=1.09, Fitness=0.81, TO=0.1096, DD=0.1408。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.3333*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.3333*(ts_rank(ts_mean(add(fnd17_...`
- **GrL9N8J3** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.43, TO=0.1253, DD=0.0574。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3333*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.3333*(rank(add(anl46_sentiment, anl46...`
- **1YdP0OVJ** (UNSUBMITTED, other): Sharpe=0.54, Fitness=0.25, TO=0.1403, DD=0.1114。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(multiply(annual_net_income_excl_extraordinary, annual_normalized_net_income_to_common), 60)), 20)`
- **mLb1QKbp** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.13, TO=0.0376, DD=0.1146。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_comp, 60)), 20)`
- **RR8KKg5a** (UNSUBMITTED, technical): Sharpe=0.69, Fitness=0.28, TO=0.1533, DD=0.0814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(daily_volume_to_shares_outstanding, 20)) * signed_power(fnd17_20_ev2ebitda_cur, 0.5), 20)`
- **LL1rK376** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.0733, DD=0.0564。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_20_ttmgrosmgn, 60)) * signed_power(ts_mean(fnd17_2anrhsfcfq, 60), 0.5), 20)`
- **omlroeWb** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(multiply(signed_power(vec_avg(mws50_ess_2), 0.5), log(1)), add(1, ts_mean(downside_tail_depende...`
- **pwlZvAg3** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(multiply(signed_power(vec_avg(mws50_ess_2), 0.5), log(1)), add(1, ts_mean(downside_tail_depende...`
- **9qrmWkKe** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.06, TO=0.0965, DD=0.1902。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_earnings_before_tax * annual_current_liabilities, 60)), 20)`
- **kq0Ojajd** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.02, TO=0.0962, DD=0.1826。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_comp, 60)), 20)`
- **9qrmXV9K** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(multiply(signed_power(vec_avg(mws50_ess_2), 0.5), log(1)), add(1, ts_mean(downside_tail_depende...`
- **9qrmXrMr** (UNSUBMITTED, sentiment): Sharpe=-0.84, Fitness=-0.16, TO=1.3973, DD=0.5164。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(enterprise_value_to_revenue, ts_mean(enterprise_value_to_revenue, 120))) * signed_power(sum_pri...`
- **ZYnM7618** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.0794, DD=0.2654。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(market_capitalization_usd_3_fast_d1, 252)), 60)`
- **omlrNjw6** (UNSUBMITTED, technical): Sharpe=1.36, Fitness=0.83, TO=0.0529, DD=0.1116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.5211*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.1678*(ts_rank(divide(daily_volume_to_s...`
- **58OepZGo** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.0506, DD=0.1641。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_comp, 60)), 20)`
- **pwlZKLJo** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.068, DD=0.151。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_comp, 60)), 20)`
- **d50o0GQE** (UNSUBMITTED, technical): Sharpe=1.39, Fitness=0.82, TO=0.0597, DD=0.0936。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.2000*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.2000*(ts_rank(divide(daily_volume...`
- **2rLWL9p6** (UNSUBMITTED, cashflow): Sharpe=1.81, Fitness=1.18, TO=0.0622, DD=0.0369。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.3333*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), ...`
- **pwlZldo6** (UNSUBMITTED, sentiment): Sharpe=1.68, Fitness=1.43, TO=0.1273, DD=0.0552。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.2000*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.2000*(rank(add(anl46_sentiment, ...`
- **mLb1bxk2** (UNSUBMITTED, other): Sharpe=0.77, Fitness=0.54, TO=0.5073, DD=0.4651。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.2500*(rank(ts_rank(add(subtract(anl10_analyst_innovation_bps_revise_value_fy2, ts_mean(ts_delta(anl10_a...`
- **JjO1Owve** (UNSUBMITTED, cashflow): Sharpe=1.48, Fitness=0.9, TO=0.0468, DD=0.05。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.5463*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **RR8KpPE1** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.02, TO=0.4144, DD=0.0661。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_receivable_current_assets, 60)) * signed_power(mdl55_groupindustry_aroc_mcwa, 0.5), 20)`
- **VkP5peXY** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.43, TO=0.1258, DD=0.0567。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2809*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.2459*(rank(add(anl46_sentiment, anl46...`
- **9qrmwYee** (UNSUBMITTED, cashflow): Sharpe=1.44, Fitness=0.87, TO=0.0464, DD=0.0533。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.4376*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **0mE67bKv** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.43, TO=0.1258, DD=0.056。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.1995*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.2218*(rank(add(anl46_sentiment, anl46...`
- **mLb1X5M1** (UNSUBMITTED, cashflow): Sharpe=1.74, Fitness=1.13, TO=0.0605, DD=0.0396。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3846*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **vRl6mvlz** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=0.67, TO=0.0363, DD=0.0957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2520*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.0388*(ts_rank(divide(daily_volume_to_s...`
- **rKlVWLA8** (UNSUBMITTED, other): Sharpe=-0.63, Fitness=-0.21, TO=0.1151, DD=0.1554。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(vec_avg(mws59_event_time_value_fast_d1), 40)) * ts_mean(zscore(ts_mean(vec_avg(mws59_event_tim...`
- **kq0OKRJd** (UNSUBMITTED, technical): Sharpe=1.42, Fitness=0.86, TO=0.0615, DD=0.0977。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2610*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.2034*(ts_rank(divide(daily_volume_to_s...`
- **3qR5z28Q** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.42, TO=0.126, DD=0.056。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2090*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.2058*(rank(add(anl46_sentiment, anl46...`
- **lel9rWV5** (UNSUBMITTED, cashflow): Sharpe=1.76, Fitness=1.15, TO=0.0619, DD=0.0394。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3717*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **LL1rkkg1** (UNSUBMITTED, technical): Sharpe=1.47, Fitness=0.89, TO=0.0684, DD=0.0944。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2121*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.2374*(ts_rank(divide(daily_volume_to_s...`
- **lel9r722** (UNSUBMITTED, sentiment): Sharpe=-0.3, Fitness=-0.09, TO=0.2538, DD=0.3238。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_aintcov) * signed_power(anl46_sentiment, 0.5), 20)`
- **3qR5Evj0** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.42, TO=0.1261, DD=0.0559。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2050*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.1967*(rank(add(anl46_sentiment, anl46...`
- **xAkWev2b** (UNSUBMITTED, cashflow): Sharpe=1.83, Fitness=1.22, TO=0.067, DD=0.0389。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.3333*(rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)),...`
- **QPVgne1K** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.02, TO=0.4144, DD=0.0661。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_receivable_current_assets, 60)) * signed_power(mdl55_groupindustry_aroc_mcwa, 0.5), 20)`
- **d50onLWE** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.42, TO=0.126, DD=0.0559。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2000*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.2000*(rank(add(anl46_sentiment, anl46...`
- **A1PmnWJY** (UNSUBMITTED, technical): Sharpe=1.42, Fitness=0.85, TO=0.0612, DD=0.0937。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2000*(rank(ts_mean(zscore(annual_net_income_change_percent), 5))) + 0.2000*(ts_rank(divide(daily_volume_to_s...`
- **A1Pmn9JW** (UNSUBMITTED, other): Sharpe=0.76, Fitness=0.53, TO=0.5074, DD=0.4637。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.2500*(rank(ts_rank(add(subtract(anl10_analyst_innovation_bps_revise_value_fy2, ts_mean(ts_delta(anl10_analys...`
- **2rLWaexb** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.18, TO=0.12, DD=0.1002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_ebitda_amount, 60)), 60)`
- **vRl6J5pw** (UNSUBMITTED, sentiment): Sharpe=-0.18, Fitness=-0.06, TO=0.1399, DD=0.2658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_aintcov) * signed_power(anl46_sentiment, 0.5), 20)`
- **RR8KkXLo** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.802, DD=0.0343。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(anl46_performancepercentile) * signed_power(mdl106_mkt_cap, 0.5), 20)`
- **WjG0XmoO** (UNSUBMITTED, sentiment): Sharpe=1.49, Fitness=0.87, TO=0.2711, DD=0.1128。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.3333*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.3333*(ts_rank(ts_mean(add(fnd17_...`
- **88QY7lJv** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(log(1)), 20)`
- **omlrwE6m** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(log(1)), 20)`
- **0mE6nRRv** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.2, TO=0.1465, DD=0.0547。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_20_ttmgrosmgn, 60)) * signed_power(annual_normalized_net_income_common, 0.5), 20)`
- **781MgKN5** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(log(1)), 20)`
- **qMlGw92A** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.06, TO=0.0411, DD=0.0323。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(multifactor_residual_volatility_fast_d1) * signed_power(rank(mdl55_groupindustry_adyx_50pctl), ts_mean...`
- **wplGPkPY** (UNSUBMITTED, other): Sharpe=0.48, Fitness=0.16, TO=0.1017, DD=0.0746。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_20_ttmgrosmgn, 60)) * signed_power(annual_normalized_net_income_common, 0.5), 20)`
- **aknzQgaw** (UNSUBMITTED, sentiment): Sharpe=1.05, Fitness=0.76, TO=0.1129, DD=0.224。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.349*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20))) + 0.236*rank(ts_mean(multiply(anl46_sen...`
- **xAkG2ldm** (UNSUBMITTED, sentiment): Sharpe=1.04, Fitness=0.75, TO=0.1244, DD=0.2093。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.228*ts_rank(ts_mean(fnd17_acurratio, 20), 100) + 0.244*rank(ts_mean(multiply(anl46_sentiment, ts_rank(t...`
- **RR8zlewj** (UNSUBMITTED, sentiment): Sharpe=1.69, Fitness=1.45, TO=0.1264, DD=0.0558。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.25*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20))) + 0.25*rank(add(anl46_sentiment, anl46_e...`
- **np2qeNZM** (UNSUBMITTED, sentiment): Sharpe=1.69, Fitness=1.45, TO=0.1263, DD=0.0559。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(zscore(0.260*rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20))) + 0.255*rank(add(anl46_sentiment, anl46...`
- **A1PzV1md** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.03, TO=0.0323, DD=0.1609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_aroe_mcwa, 60)), 252)`
- **j20G8K6e** (UNSUBMITTED, sentiment): Sharpe=1.27, Fitness=0.94, TO=0.1405, DD=0.1282。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.1429*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.1429*(rank(subtract(anl46_sentiment, ...`
- **gJMGZV3e** (UNSUBMITTED, sentiment): Sharpe=1.67, Fitness=1.43, TO=0.1256, DD=0.0565。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(0.25*(rank(divide(anl46_sentiment, ts_mean(anl46_indicator, 20)))) + 0.25*(rank(subtract(anl46_sentiment, subt...`
- **YP0zAoAw** (UNSUBMITTED, other): Sharpe=0.45, Fitness=0.2, TO=0.0854, DD=0.1483。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aebitd2, 252)), 60)`
- **VkPzOqob** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.06, TO=0.3175, DD=0.1104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(annual_normalized_net_income_common) * signed_power(mdl140_qes_sinc_sensitivity, 0.5), 20)`
- **LL1znpLm** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.1021, DD=0.3166。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_payable_current, 60)), 252)`
- **1YdKaK9M** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.045, DD=0.2593。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl106_price, 60)), 60)`
- **wplGzGY6** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.0624, DD=0.3465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(accounts_payable_current, 60)), 252)`
- **3qRPWv8e** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.04, TO=0.1768, DD=0.1292。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(annual_normalized_net_income_common) * signed_power(mdl140_qes_sinc_sensitivity, 0.5), 20)`
- **LL1m3wn9** (UNSUBMITTED, sentiment): Sharpe=-0.23, Fitness=-0.02, TO=1.4801, DD=0.2892。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(enterprise_value_to_revenue) * signed_power(mean_sentiment_score_transfer, 0.5), 60)`
- **YP0EaQeM** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.12, TO=0.0856, DD=0.337。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl106_price, 60)), 60)`
- **wpl2Qr7d** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.06, TO=0.06, DD=0.3032。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl106_price, 60)), 60)`
- **rKlNdVqE** (UNSUBMITTED, other): Sharpe=0.49, Fitness=0.22, TO=0.0568, DD=0.1554。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_aebitd2, 252)), 60)`
- **lel5KzG5** (UNSUBMITTED, sentiment): Sharpe=-0.2, Fitness=-0.02, TO=1.4981, DD=0.2478。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(enterprise_value_to_revenue) * signed_power(mean_sentiment_score_transfer, 0.5), 60)`
- **gJMgb8eJ** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.3277, DD=0.0993。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(current_ratio, 60), 20), 20)`
- **6X9olPlp** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.0812, DD=0.2248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(enterprise_value_to_revenue, 60)), 120)`
- **mLb08grK** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.4144, DD=0.0803。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility, 60)) * signed_power(mdl55_groupindustry_awcm_sca, 0.5), 20)`
- **WjGo9Z5j** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.0726, DD=0.0582。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_performancepercentile, 60)), 120)`
- **6X9oYkzK** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.026, DD=0.083。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(market_capitalization_usd_3, ts_mean(market_capitalization_usd_3, 60)), 60), 20)`
- **N1rJomEL** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.05, TO=0.051, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_debt_to_equity_ratio, 60)), 120)`
- **omlJOX22** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.06, TO=0.8, DD=0.0632。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(anl46_performancepercentile), signed_power(mdl106_rv, 0.5)), 20)`
- **YP0Eq07R** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.4144, DD=0.0803。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility, 60)) * signed_power(mdl55_groupindustry_awcm_sca, 0.5), 20)`
- **zqm21xrK** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.7996, DD=0.1256。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_agrosmgn) * signed_power(mdl106_risk, 0.5), 20)`
- **mLb0Rv39** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.4144, DD=0.0803。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility, 60)) * signed_power(mdl55_groupindustry_awcm_sca, 0.5), 20)`
- **QPVNkJ3X** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.01, TO=0.0156, DD=0.0346。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(downside_market_beta, 60)) * signed_power(capm_residual_volatility_fast_d1, 0.5), 20)`
- **zqm2M2OV** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.02, TO=0.2876, DD=0.0577。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(cash_per_share, 20)), 2) * signed_power(zscore(ts_rank(annual_revenue_value, 20))...`
- **rKlNY50E** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.7996, DD=0.1256。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(fnd17_agrosmgn) * signed_power(mdl106_risk, 0.5), 20)`
- **lel5pb9l** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.1469, DD=0.0806。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(ts_mean(cash_per_share, 20)), 2) * signed_power(zscore(ts_rank(annual_revenue_value, 20))...`
- **gJMgJ7eK** (UNSUBMITTED, other): Sharpe=0.41, Fitness=0.08, TO=0.0194, DD=0.0219。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(downside_market_beta, 60)) * signed_power(capm_residual_volatility_fast_d1, 0.5), 20)`
- **xAk2AXYW** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.04, TO=0.0171, DD=0.0271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(downside_market_beta, 60)) * signed_power(capm_residual_volatility_fast_d1, 0.5), 20)`
- **58OrPgwz** (UNSUBMITTED, other): Sharpe=0.94, Fitness=0.53, TO=0.1854, DD=0.0763。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(multifactor_residual_volatility, 60)), 20)`
- **RR89Od0g** (UNSUBMITTED, sentiment): Sharpe=0.59, Fitness=0.25, TO=0.1808, DD=0.0692。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_sentiment, 20)), 20)`
- **omlRXrwl** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.0, TO=0.0715, DD=0.0441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(market_capitalization_usd_3, ts_mean(market_capitalization_usd_3, 60))) * signed_power(vec_avg(...`
- **O0ZRjPkp** (UNSUBMITTED, sentiment): Sharpe=0.51, Fitness=0.23, TO=0.1376, DD=0.1024。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_sentiment, 20)), 20)`
- **d50YvP9J** (UNSUBMITTED, sentiment): Sharpe=0.31, Fitness=0.11, TO=0.1069, DD=0.1371。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(anl46_sentiment, 20)), 20)`
- **xAkV5kjb** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.13, TO=0.4144, DD=0.0427。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(mdl55_groupindustry_awcm_cda, 20)`
- **pwlxGJmV** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.08, TO=0.0431, DD=0.1236。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_revenue_change_percent, 60)), 120)`
- **7813vLEL** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.12, TO=0.0897, DD=0.18。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_sensitivity, 40)) * signed_power(anl46_performancepercentile, 0.5), 60)`
- **A1Pernze** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.04, TO=0.0249, DD=0.0489。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(capm_residual_volatility) * ts_mean(zscore(capm_residual_volatility), 60), 20)`
- **e70NNowg** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.06, TO=0.4144, DD=0.0329。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_aroc_mcwa, 60)) * ts_zscore(mdl55_groupindustry_awcm_cda, 20), 20)`
- **rKl90Z1d** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.03, TO=0.0536, DD=0.1532。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(annual_revenue_change_percent, 60)), 120)`
- **1YdOGklR** (UNSUBMITTED, sentiment): Sharpe=-0.19, Fitness=-0.03, TO=0.2295, DD=0.1262。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(multi_classifier_equity_sentiment_score, 60)), 20)`
- **zqmgAqp1** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.09, TO=0.0232, DD=0.1589。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl140_qes_sinc_comp, 60)), 252)`
- **1YdOWG3X** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.06, TO=0.4144, DD=0.0329。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(mdl55_groupindustry_aroc_mcwa, 60)) * ts_zscore(mdl55_groupindustry_awcm_cda, 20), 20)`
- **LL1EKLr1** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.0196, DD=0.0433。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(market_capitalization_usd_3) * signed_power(historical_realized_volatility, 0.5), 20)`
- **XgnV9J88** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.04, TO=0.7997, DD=0.1348。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(fnd17_acurratio, 20)) * signed_power(mdl106_global_evaluation, 0.5), 60)`
- **JjOoe0Wl** (UNSUBMITTED, other): Sharpe=0.48, Fitness=0.18, TO=0.1199, DD=0.0933。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(mdl140_qes_sinc_sensitivity, 60), 20)`
- **pwlxdw73** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.16, TO=0.0574, DD=0.2802。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(historical_realized_volatility_fast_d1, 60)), 120)`
- **j20oeK2E** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.1, TO=0.0584, DD=0.2683。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(market_capitalization_usd_3, 60)), 120)`
- **WjG3LYvO** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.02, TO=0.0241, DD=0.0618。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(market_capitalization_usd_3) * signed_power(historical_realized_volatility, 0.5), 20)`
- **QPVOY5wp** (UNSUBMITTED, other): Sharpe=-0.58, Fitness=-0.25, TO=0.2843, DD=0.6203。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(zscore(mdl106_price), rank(ts_zscore(fnd17_acurratio, 20))), 20)`
- **omlRo8Ok** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(log(1)), 20)`
- **VkPZ0Za8** (UNSUBMITTED, technical): Sharpe=0.64, Fitness=0.29, TO=0.1009, DD=0.0584。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(ts_mean(daily_volume_to_shares_outstanding, 60)), 20)`
- **GrLXdmG0** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(log(1)), 20)`
- **qMlOjpXO** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.02, TO=0.0898, DD=0.0995。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(market_capitalization_usd_3, ts_mean(market_capitalization_usd_3, 60))) * signed_power(vec_avg(...`
- **58OrOGwJ** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.26, TO=0.0111, DD=0.154。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(annual_net_income_excl_extraordinary, 10))`
- **e70N0zmN** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.1, TO=0.1163, DD=0.1427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_total_current_assets)...`
- **mLbdqYd2** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.14, TO=0.1143, DD=0.1548。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_receivable_total_6) * signed_power(divide(accounts_cash_and_equivalents, accounts_total_curre...`
- **KP9vnr88** (UNSUBMITTED, sentiment): Sharpe=-0.41, Fitness=-0.18, TO=0.122, DD=0.3246。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(ts_mean(subtract(fnd17_2rhsfca, fnd17_2rhsfcq), 10), anl46_sentiment), 10))`
- **58Oraoko** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.08, TO=0.0622, DD=0.2287。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(sqrt(assets), log(cash)), 5), 100))`
- **RR89kgRj** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.04, TO=0.2077, DD=0.4159。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(annual_net_income_excl_extraordinary, annual_total_assets_value), 30), 10))`
- **QPVO5dOG** (UNSUBMITTED, other): Sharpe=-0.36, Fitness=-0.13, TO=0.0497, DD=0.2265。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(sqrt(assets), log(cash)), 5), 100))`
- **omlRzwZm** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.12, TO=0.037, DD=0.172。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(annual_revenue_value, ts_mean(annual_revenue_value, 5)), 100))`
- **58Or9XzX** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.16, TO=0.1991, DD=0.3564。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_receivable_current) * signed_power(accounts_payable_current, ts_mean(accounts_payable_current...`
- **xAkVQw6w** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.04, TO=0.0536, DD=0.0666。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(add(annual_net_income_change_percent, multiply(annual_debt_to_equity_ratio, subtract(annual_revenue_...`
- **E5ENYNem** (UNSUBMITTED, other): Sharpe=-0.18, Fitness=-0.05, TO=0.1859, DD=0.3002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_cash_and_equivalents) * signed_power(accounts_receivable_current, accounts_payable_current), 20)`
- **pwlxom83** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.04, TO=0.0536, DD=0.0661。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(annual_net_income_change_percent, multiply(annual_debt_to_equity_ratio, subtract(annual_revenue_change_pe...`
- **E5ENYOrK** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.07, TO=0.2728, DD=0.2594。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(add(accounts_receivable_current, accounts_payable_current), subtract(accounts_total_current_ass...`
- **O0ZRq00R** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.03, TO=0.1271, DD=0.2712。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_current_assets, accounts_payable_current_2)) * signed_power(divide(accounts...`
- **ZYngwQzj** (UNSUBMITTED, technical): Sharpe=-0.49, Fitness=-0.14, TO=0.2249, DD=0.2175。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(daily_volume_to_shares_outstanding, multiply(annual_revenue_change_percent, annual_net_income_c...`
- **rKl96lG3** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.03, TO=0.1916, DD=0.2467。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_current, accounts_total_current_assets)) * signed_power(accounts_payable_cu...`
- **1YdOV9jz** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.11, TO=0.3049, DD=0.2964。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(add(accounts_receivable_current, accounts_payable_current), subtract(accounts_total_current_ass...`
- **XgnVXd11** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(fnd17_1_reptoprcexrate, ts_zscore(divide(fnd17_2_reptoprcexrate, ts_zscore(subtract(fnd17_3_reptoprcexrat...`
- **3qR1doMX** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.07, TO=0.2887, DD=0.2569。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_current, accounts_total_current_assets)) * signed_power(accounts_payable_cu...`
- **LL1Eea5a** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.19, TO=0.0326, DD=0.0994。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_net_income_to_common, ts_mean(subtract(annual_total_assets_value, add(annual_current_lia...`
- **YP08dmQq** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.02, TO=0.3934, DD=0.1078。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60))) * signed_power(vec_avg(company_offer_...`
- **kq0v5RNg** (UNSUBMITTED, sentiment): Sharpe=-0.09, Fitness=-0.02, TO=0.0453, DD=0.4584。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(multiply(fnd17_2rhsfcq, log(ts_std_dev(rank(anl46_indicator), 100))), sqrt(divide(ts_max(fnd17_2qe2d...`
- **XgnV6zJ0** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.05, TO=0.2892, DD=0.2594。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_current_assets, accounts_payable_current_2)) * signed_power(divide(accounts...`
- **xAkVgxWm** (UNSUBMITTED, sentiment): Sharpe=0.19, Fitness=0.06, TO=0.0784, DD=0.2488。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(anl46_indicator, anl46_performancepercentile) * ts_mean(ts_mean(ts_delta(divide(anl46_sentimen...`
- **pwlxAbRo** (UNSUBMITTED, other): Sharpe=-0.64, Fitness=-0.22, TO=0.1507, DD=0.2159。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(ebit, multiply(assets, ts_mean(cash, 100))), 20))`
- **pwlxAmWj** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.08, TO=0.2825, DD=0.4696。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_receivable_current) * signed_power(accounts_cash_and_equivalents, accounts_payable_current), 20)`
- **YP08KNgo** (UNSUBMITTED, other): Sharpe=0.29, Fitness=0.07, TO=0.1915, DD=0.1036。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ebit * subtract(assets, ts_mean(cash, 100)), 20))`
- **0mExlNRk** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.11, TO=0.2287, DD=0.1211。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_total_6, accounts_total_current_assets)) * signed_power(divide(accounts_pay...`
- **blqJkaGl** (UNSUBMITTED, technical): Sharpe=0.51, Fitness=0.16, TO=0.1005, DD=0.0439。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(ts_delta(subtract(annual_revenue_value, ts_mean(daily_volume_to_shares_outstanding, 10)), 2...`
- **WjG3q1JZ** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.2963, DD=1.2134。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_receivable_current) * signed_power(accounts_cash_and_equivalents, accounts_total_current_asse...`
- **akne6m2R** (UNSUBMITTED, other): Sharpe=0.75, Fitness=0.25, TO=0.17, DD=0.0389。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_zscore(ts_mean(add(divide(subtract(annual_revenue_value, annual_total_liabilities_value), annual_tota...`
- **A1Pe9EJE** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.0317, DD=0.1129。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(annual_revenue_per_share * ts_std_dev(log(annual_net_income_to_common), 120), 20))`
- **mLbdpXv6** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.07, TO=0.2654, DD=0.1313。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(accounts_receivable_current_assets, accounts_total_current_assets)) * signed_power(divide(accou...`
- **WjG3M6md** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.02, TO=0.257, DD=1.5473。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(assets, ts_mean(divide(debt_lt, ts_std_dev(ts_delta(accounts_payable, 5), 20)), 20)), 20)`
- **ZYng66w1** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`sign(log(add(abs(mdl140_qes_sinc_neut), 5)))`
- **N1rL0xQg** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.2424, DD=0.2317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(multiply(ebitda, ts_zscore(ts_mean(subtract(assets, log(cash)), 20), 20)), 20)`
- **QPVO1zgM** (UNSUBMITTED, sentiment): Sharpe=-0.5, Fitness=-0.22, TO=0.0558, DD=0.3598。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(ts_delta(ts_quantile(anl46_sentiment, 100), 100), 100), 100), 100)`
- **YP08jWlJ** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.02, TO=0.1081, DD=0.0758。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(multiply(ebitda, ts_zscore(ts_rank(assets_curr, 50), 50)), 20)`
- **58OrZ3Ao** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.04, TO=0.3934, DD=0.1567。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(divide(mdl140_qes_sinc_comp, vec_avg(company_offer_unit_price))), 20)`
- **9qrGNVaq** (UNSUBMITTED, sentiment): Sharpe=0.13, Fitness=0.03, TO=0.1145, DD=0.1665。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(log(ts_mean(multiply(anl46_indicator, anl46_sentiment), 50)), 50), 252)`
- **np26GdVl** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.34, TO=0.0416, DD=0.1771。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(divide(annual_net_income_to_common, ts_std_dev(ts_mean(add(annual_total_revenue, ts_delta(annual_book_va...`
- **LL18Yo0a** (UNSUBMITTED, other): Sharpe=0.78, Fitness=0.33, TO=0.0256, DD=0.063。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ebitda, multiply(cash, ts_mean(log(assets), 10))), 252))`
- **e701Zbdd** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.02, TO=0.3521, DD=0.4084。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(zscore(accounts_receivable_current), 20)`
- **pwlW7a0j** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0254, DD=0.2098。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(multiply(fnd23_4dls, sqrt(ts_mean(fnd17_8_usdtorepexrate, 100))), 100), 200)`
- **KP9VL0jE** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.09, TO=0.0158, DD=0.2166。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(sign(log(accounts_current_assets_equity)))`
- **e701nY1O** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.04, TO=0.0076, DD=0.2116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(fnd23_3dls, ts_std_dev(ts_delta(log(fnd23_3los), 5), 100)), 50))`
- **XgnN2ejz** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.0291, DD=0.1248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_delta(fnd23_3dls, 10), divide(ts_mean(fnd23_acos, 10), ts_std_dev(fnd23_54dls, 10))), 252))`
- **WjGYaWJN** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.06, TO=0.0991, DD=0.1934。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(multiply(fnd23_32dls, ts_rank(fnd23_32los, 100)), ts_delta(fnd23_32dls, 100)), 100), 20))`
- **zqmAzNEG** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.13, TO=0.0236, DD=0.195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(sign(log(accounts_current_assets_equity)))`
- **MPQgm7A6** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.12, TO=0.0222, DD=0.2225。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(sign(log(accounts_current_assets_equity)))`
- **88QG900l** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.09, TO=0.017, DD=0.1834。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`reverse(sign(log(accounts_current_assets_equity)))`
- **RR85Qd5o** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.16, TO=0.1167, DD=0.1801。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(add(log(abs(mdl140_qes_sinc_comp)), 20), 10)`
- **WjGYMxkQ** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.18, TO=0.057, DD=0.5803。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(fnd23_2dls, ts_mean(multiply(fnd23_2los, ts_zscore(fnd17_8_reptoprcexrate, 20)), 20)), 20)`
- **A1PL9VlY** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.05, TO=0.0559, DD=0.2912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(sign(log(add(abs(mdl140_qes_sinc_comp), 20))), 50)`
- **vRlY82Wb** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.39, TO=0.1069, DD=1.5788。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(fnd23_2dls, ts_mean(multiply(fnd23_2los, ts_zscore(fnd17_8_reptoprcexrate, 20)), 20)), 20)`
- **aknaLbdx** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.01, TO=0.4366, DD=0.124。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(mdl170_ccp_latest), 252)`
- **E5EQl6v1** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.36, TO=0.137, DD=1.1577。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(ts_std_dev(fnd23_1lcs, 60), ts_mean(ts_delta(ts_zscore(fnd23_1oscq, 120), 10), 20)), 20)`
- **781YjNlO** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.0978, DD=0.1943。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(accounts_receivable_gross), 252), 60)`
- **3qR0lR8g** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.0885, DD=0.0771。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(divide(accounts_receivable_total_5, accounts_total_current_assets), 252), 60)`
- **j20ajgpO** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.08, TO=0.1419, DD=0.1684。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(accounts_receivable_gross), 252), 60)`
- **pwlajVl6** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.0946, DD=0.1411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(accounts_receivable_gross), 252), 60)`
- **6X9Ml8gp** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.16, TO=0.1182, DD=0.6557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(ts_std_dev(fnd23_1lcs, 60), ts_mean(ts_delta(ts_zscore(fnd23_1oscq, 120), 10), 20)), 20)`
- **ZYnaEnGn** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.01, TO=0.4491, DD=0.1224。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(mdl170_ccp_latest), 252)`
- **mLbaV99W** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.01, TO=0.7941, DD=0.1761。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_delta(vec_avg(recent_earnings_momentum_score), 252), 1260)`
- **E5EQE83r** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(signed_power(ts_delta(vec_avg(company_offer_unit_price), 252), 2), 60)`
- **GrLmwad3** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.06, TO=0.7975, DD=0.3046。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(signed_power(ts_delta(vec_avg(latest_implied_valuation_price), 252), 2), 500)`
- **rKl7W6x9** (UNSUBMITTED, other): Sharpe=0.98, Fitness=0.25, TO=0.7997, DD=0.0644。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(mdl106_rv, 20))`
- **E5EQkaR1** (UNSUBMITTED, other): Sharpe=-0.61, Fitness=-0.43, TO=0.0167, DD=0.6912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(vec_avg(company_offer_unit_price), 252)`
- **3qR0Eld0** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.14, TO=0.7997, DD=0.0916。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(mdl106_rv, 20))`
- **lelaJAd7** (UNSUBMITTED, other): Sharpe=0.04, Fitness=0.0, TO=0.0191, DD=0.1471。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(ts_delta(rank(accounts_payable_current_2), 252))`
- **kq0aeQLz** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.0, TO=0.8033, DD=0.1175。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(vec_avg(recent_earnings_momentum_score), 252), 120)`
- **mLbaOWep** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.01, TO=0.786, DD=0.1352。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_delta(vec_avg(composite_fundamental_score), 252), 1260)`
- **MPQ6mJnL** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.03, TO=0.3934, DD=0.0664。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(company_offer_unit_price), 252)`
- **lelaXQe8** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.04, TO=0.4184, DD=0.1583。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(mdl170_dividendqualityscore), 252)`
- **2rL5brVY** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.4582, DD=0.2657。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`signed_power(ts_zscore(vec_avg(mdl170_ccp_latest), 252), 2)`
- **wploqMnl** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.18, TO=0.0584, DD=0.2418。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_std_dev(add(divide(signed_power(subtract(ts_zscore(fnd23_1nstq, 252), ts_mean(fnd23_1nstq, 252)), 2), ts_z...`
- **ZYnaPzWn** (UNSUBMITTED, other): Sharpe=-0.58, Fitness=-0.41, TO=0.1425, DD=0.85。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_std_dev(divide(fnd23_1nstq, ts_zscore(fnd17_7_usdtorepexrate, 100)), 5), 20), 20)`
- **58OJ8jaJ** (UNSUBMITTED, other): Sharpe=0.23, Fitness=0.04, TO=1.5512, DD=0.565。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(vec_avg(anl9_consensusv2span_incomeeps_dataitemvalue), 252), 200)`
- **YP0ajZmJ** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.08, TO=0.0116, DD=0.4935。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(ts_mean(vec_avg(mdl170_dividendyield_latest), 252))`
- **e705jePO** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.03, TO=0.7959, DD=0.0853。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(vec_avg(mdl170_ccp_latest), 252), 240)`
- **9qrxeYKe** (UNSUBMITTED, other): Sharpe=0.47, Fitness=0.13, TO=1.139, DD=0.383。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(anl9_consensusanalysis_dataitemvalue), 252)`
- **WjGO2ZlQ** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.1, TO=0.4375, DD=0.0721。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(ts_rank(vec_avg(recent_earnings_momentum_score), 252))`
- **GrLW5wao** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.05, TO=0.3003, DD=0.314。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(fnd17_5_usdtorepexrate, 20), 20)`
- **JjOekbvn** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.09, TO=0.0119, DD=0.5043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(vec_avg(mdl170_dividendyield_latest), 252)`
- **qMlLpZRv** (UNSUBMITTED, other): Sharpe=-0.2, Fitness=-0.09, TO=0.0076, DD=0.44。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(ts_std_dev(multiply(depre, abs(annual_fiscal_month_number)), 20), 50), 200))`
- **6X9d2ko7** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.01, TO=0.3934, DD=0.0759。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(company_offer_unit_price), 252)`
- **N1rN2Q5g** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.09, TO=0.007, DD=0.4393。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(ts_std_dev(multiply(depre, abs(annual_fiscal_month_number)), 20), 50), 200))`
- **mLbolVw2** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.05, TO=0.4329, DD=0.215。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`zscore(ts_rank(vec_avg(mdl170_dividendyield_latest), 252))`
- **wplQW0n1** (UNSUBMITTED, other): Sharpe=-0.18, Fitness=-0.02, TO=0.4487, DD=0.1794。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(mdl170_dividendqualityscore), 252)`
- **xAkr5Lkp** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=0.5264, DD=0.1766。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`signed_power(ts_zscore(vec_avg(mdl170_dividendqualityscore), 252), 2)`
- **pwld3Pmx** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.3925, DD=0.0733。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(company_offer_unit_price), 252)`
- **omlEZnam** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.04, TO=1.6136, DD=0.7645。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(vec_avg(anl9_consensusv2span_incomeeps_dataitemvalue)), 252), 252)`
- **QPVv61qM** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.02, TO=0.4387, DD=0.1144。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(mdl170_dividendyield_latest), 252)`
- **gJMedroJ** (UNSUBMITTED, other): Sharpe=-0.15, Fitness=-0.02, TO=0.4517, DD=0.1799。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(mdl170_dividendqualityscore), 252)`
- **YP01EJQ6** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.29, TO=0.3531, DD=0.1824。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(vec_avg(anl9_consensusanalysis_dataitemvalue), 252), 60)`
- **0mEYNP2k** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.02, TO=0.4477, DD=0.1727。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(mdl170_dividendqualityscore), 252)`
- **kq0NWlwd** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.07, TO=0.0117, DD=0.5045。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(vec_avg(mdl170_dividendyield_latest), 252)`
- **E5E68WWm** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(vec_avg(company_offer_unit_price)), 252), 20)`
- **zqm3gWgO** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.4288, DD=0.0999。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(composite_fundamental_score), 252)`
- **YP018KNw** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.03, TO=0.2555, DD=0.3008。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(vec_avg(anl9_consensusanalysis_dataitemvalue), 252), 60)`
- **MPQYg19n** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.35, TO=0.0114, DD=0.1843。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(vec_avg(mdl170_dividendyield_latest), 252)`
- **9qrxG7Y2** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_delta(zscore(vec_avg(company_offer_unit_price)), 252), 20)`
- **lelAgVN5** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.04, TO=0.3925, DD=0.1914。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(vec_avg(company_offer_unit_price), 252), 20)`
- **1YdNGnlm** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.02, TO=0.4476, DD=0.1651。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(mdl170_ccp_latest), 252)`
- **A1PVLOVl** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.4279, DD=0.098。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(composite_fundamental_score), 252)`
- **58OEg3Qk** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.12, TO=0.2581, DD=0.2772。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(fnd17_5_usdtorepexrate, 20), 20)`
- **mLbogGXK** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.04, TO=0.285, DD=0.3418。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(fnd17_5_usdtorepexrate, 20), 20)`
- **ZYnQ0MAn** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.03, TO=0.3916, DD=0.1071。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(actual_investment_round_total), add(1, log(abs(vec_avg(company_employee_count))))), 20)`
- **d50WjvKE** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(add(divide(vec_avg(company_employee_count), vec_avg(company_employee_count_2)), log(vec_avg(aggregate_dolla...`
- **QPVvnJpG** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_std_dev(ts_zscore(divide(subtract(fnd17_5_usdtorepexrate, fnd17_6_usdtorepexrate), 10), 50), 30), ...`
- **Xgn9YzO1** (UNSUBMITTED, other): Sharpe=-1.24, Fitness=-0.75, TO=0.1686, DD=0.6536。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(divide(subtract(fnd17_20_ev2ebitda_cur, annual_total_shareholders_equity), annual_total_sha...`
- **1YdN15xm** (UNSUBMITTED, other): Sharpe=0.35, Fitness=0.21, TO=0.1755, DD=0.5269。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(mdl106_ycc, ts_std_dev(fnd17_3_usdtorepexrate, 20)), 10), 30))`
- **A1PVdajE** (UNSUBMITTED, other): Sharpe=0.8, Fitness=0.53, TO=0.0154, DD=0.2005。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(ts_rank(subtract(fnd17_3_usdtorepexrate, fnd17_4_reptoprcexrate), 10), ts_rank(subtract(fnd17_5_reptoprce...`
- **qMlLqokZ** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(sqrt(add(mdl106_tt, ts_rank(divide(fnd17_adiv5yavg, ts_mean(multiply(fnd17_4_reptoprcexrate, ts_std_dev(fnd17_5_...`
- **E5E6XbW0** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.12, TO=0.201, DD=0.1308。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_std_dev(divide(mdl106_tre, fnd17_4_usdtorepexrate), 5), 10), 60)`
- **GrLWAk2o** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.15, TO=0.7997, DD=0.1517。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(mdl106_rv, 20))`
- **P03oWwYq** (UNSUBMITTED, other): Sharpe=-1.0, Fitness=-0.52, TO=0.3581, DD=1.0626。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(divide(rank(fnd17_3_reptoprcexrate), rank(annual_fiscal_year_number)), 5), 20), 20)`
- **781L7wgQ** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.01, TO=0.7998, DD=0.1193。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(ts_mean(multiply(mdl106_price, fnd17_2tcpngmpoa), 20), sqrt(add(mdl106_price, fnd17_2tcpngmp...`
- **ZYnQPwrx** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.03, TO=0.0522, DD=0.087。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(multiply(fnd17_2tcpngmpoa, debt_lt_curr), debt_st), 20), 60))`
- **QPVvZeGX** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.8914, DD=0.3162。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(subtract(fnd17_0_fcfq, capital_spending_per_share), 5), 20)`
- **e7057Vdp** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.07, TO=0.7997, DD=0.2196。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(multiply(rank(subtract(mdl106_pr, mdl106_risk)), sqrt(abs(rank(subtract(mdl106_pr, mdl106_risk)...`
- **j20Y2l1Z** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.7926, DD=0.1726。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(ts_rank(subtract(mdl106_price, ts_mean(mdl106_price, 100)), 100), 50), 20))`
- **omlE1Qmb** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0833, DD=0.1485。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(divide(subtract(fnd17_2tcpngmpoa, ts_mean(fnd17_2tcpngmpoa, 30)), ts_std_dev(fnd17_2tcpngmp...`
- **XgnRdXlx** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.105, DD=0.1614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(divide(subtract(fnd17_2tcpngmpoa, ts_mean(fnd17_2tcpngmpoa, 30)), ts_std_dev(fnd17_2tcpngmp...`
- **N1reGqlE** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.1368, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_rank(divide(subtract(mdl106_fnb, ts_mean(mdl106_fnb, 20)), ts_std_dev(mdl106_fnb, 20)), 10), 20))`
- **JjOP35GO** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.04, TO=0.0193, DD=0.3005。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(log(accounts_receivable_current), max(accounts_cash_and_equivalents, accounts_payable_current)), 252)`
- **vRlOA13r** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.03, TO=0.0697, DD=0.1291。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(add(acquisition_purchase_price, acquired_goodwill), 20), 20)`
- **XgnRa8d8** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.24, TO=0.0122, DD=0.2587。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(log(divide(accounts_receivable_current, accounts_receivable_current)), max(accounts_cash_and_equivalen...`
- **xAk1v9xb** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.01, TO=0.048, DD=0.0815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_current_assets_equity), 60)`
- **xAk1rZ3w** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.01, TO=1.1971, DD=0.1731。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_delta(analyst_recommendation_change_score_2, 10), 5), 30)`
- **rKldRNV1** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.04, TO=0.0652, DD=0.082。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(ts_rank(divide(acquired_goodwill, acquisition_purchase_price), 252), ts_delta(analyst_reco...`
- **KP9mJNzl** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.04, TO=0.0522, DD=0.113。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(ts_rank(divide(acquired_goodwill, acquisition_purchase_price), 252), ts_delta(analyst_reco...`
- **E5EV6qx0** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.04, TO=0.0547, DD=0.0879。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(ts_rank(divide(acquired_goodwill, acquisition_purchase_price), 252), ts_delta(analyst_reco...`
- **aknVVpwR** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.25, TO=0.0081, DD=0.0688。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(sqrt(abs(divide(acquisition_purchase_price, acquired_goodwill))), 20))`
- **mLbYYvZW** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.1885, DD=0.0624。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_av_diff(ts_rank(acquisition_purchase_price, 5), 10), 252))`
- **O0ZJJre1** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.4, TO=0.0109, DD=0.1425。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **e70660MJ** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.03, TO=1.1437, DD=0.1563。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_delta(analyst_recommendation_change_score_2, 10), 5), 30)`
- **QPVYYQ3K** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.14, TO=0.2885, DD=0.0554。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(ts_delta(signed_power(acquired_goodwill, 2), 100), 5), 20))`
- **lelMKEo2** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.25, TO=0.0273, DD=0.7479。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(divide(amortization_goodwill_intangibles, acquired_goodwill), 50)`
- **0mEjrGlK** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.22, TO=0.1287, DD=0.2177。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_std_dev(accounts_payable, 20), 20)`
- **GrLgOmQo** (UNSUBMITTED, other): Sharpe=0.6, Fitness=0.38, TO=0.0082, DD=0.2113。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **xAk1b96b** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.0455, DD=0.0953。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(log(accounts_receivable_current), ts_mean(log(accounts_receivable_current), 60)), 120)`
- **vRlO2VEb** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.11, TO=0.0236, DD=1.0336。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(divide(amortization_goodwill_intangibles, acquired_goodwill), 50)`
- **9qrEj2qq** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.05, TO=0.0209, DD=0.0819。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(log(abs(accounts_receivable_current)), 2), 252)`
- **E5EVpNpK** (UNSUBMITTED, other): Sharpe=0.63, Fitness=0.4, TO=0.0093, DD=0.1802。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **QPVYbYXX** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.02, TO=0.3182, DD=0.1982。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, mdl140_qes_sinc_neut), add(abs(mdl140_qes_sinc_sensitivity), 1)), 60)`
- **GrLgb8xP** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.06, TO=0.0497, DD=0.0931。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(log(accounts_receivable_current), ts_mean(log(accounts_receivable_current), 60)), 120)`
- **omlo6kam** (UNSUBMITTED, other): Sharpe=0.18, Fitness=0.03, TO=0.0242, DD=0.0786。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(log(abs(accounts_receivable_current)), 2), 252)`
- **LL1599L6** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.39, TO=0.0103, DD=0.1483。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **1Ydjxgp6** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.22, TO=0.0256, DD=0.0508。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_rank(subtract(log(accounts_cash_and_equivalents), log(accounts_payable_current)), 252), 20)`
- **d50KOdpx** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.02, TO=0.306, DD=0.379。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(divide(subtract(vec_avg(actual_investment_round_total), vec_avg(aggregate_dollar_amount)), add(abs(vec_avg(...`
- **aknVLNqW** (UNSUBMITTED, other): Sharpe=-0.58, Fitness=-0.12, TO=0.3916, DD=0.1985。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(company_employee_count), vec_avg(company_employee_count_2)), 252)`
- **lelM82qN** (UNSUBMITTED, other): Sharpe=0.46, Fitness=0.15, TO=0.3102, DD=0.1252。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_payable_current, 20))`
- **j20e3NqO** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.07, TO=0.3256, DD=0.1589。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_payable_current, 20))`
- **xAk1YgJm** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=1.1487, DD=0.4706。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(aggregate_dollar_amount), 60)`
- **e706zVVO** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.0, TO=0.2416, DD=0.0828。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ts_delta(analyst_recommendation_change_score_2, 10), 50), 10))`
- **1YdjwWdW** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.0656, DD=0.1388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(log(max(accounts_receivable_current, 1)), log(max(accounts_payable_current, 1))), 60)`
- **e706zJ2l** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.15, TO=0.0554, DD=0.1148。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(accounts_receivable_current, accounts_payable_current), abs(add(accounts_receivable_current, ...`
- **XgnR7mob** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.06, TO=0.1337, DD=0.2058。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(ts_zscore(accounts_payable_current, 60), 2), 120)`
- **kq0JPMez** (UNSUBMITTED, other): Sharpe=0.46, Fitness=0.16, TO=0.3292, DD=0.1391。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_payable_current, 20))`
- **aknV1zlv** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.02, TO=0.2505, DD=0.1031。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ts_delta(analyst_recommendation_change_score_2, 10), 50), 10))`
- **xAk1N2kq** (UNSUBMITTED, other): Sharpe=0.52, Fitness=0.23, TO=0.0594, DD=0.056。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_rank(multiply(divide(vec_avg(actual_investment_round_total), vec_avg(aggregate_dollar_amount)), log(vec_...`
- **gJMW8r8v** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.02, TO=0.2325, DD=0.0836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ts_delta(analyst_recommendation_change_score_2, 10), 50), 10))`
- **qMlEN09K** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.1884, DD=0.1578。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, mdl140_qes_sinc_neut), add(abs(mdl140_qes_sinc_sensitivity), 1)), 60)`
- **xAk1Nmmb** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.06, TO=0.3034, DD=0.2454。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(divide(signed_power(vec_avg(company_employee_count), 2), add(vec_avg(bookrunner_proceeds_amount), 1)), 60)`
- **A1PQGaJe** (UNSUBMITTED, other): Sharpe=0.41, Fitness=0.18, TO=0.0955, DD=0.1162。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_rank(multiply(divide(vec_avg(actual_investment_round_total), vec_avg(aggregate_dollar_amount)), log(vec_...`
- **LL15Gq61** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.06, TO=0.0546, DD=0.1595。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(divide(accounts_payable_current, accounts_receivable_current), 2), 60)`
- **RR8Am0Zb** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.1569, DD=0.2133。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), 2), 120)`
- **mLbY5OMX** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.1941, DD=0.1316。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, mdl140_qes_sinc_neut), add(abs(mdl140_qes_sinc_sensitivity), 1)), 60)`
- **QPVYGLQG** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.1409, DD=0.2081。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(divide(subtract(log(vec_avg(company_employee_count)), log(vec_avg(company_employee_count_2))), abs(signed_p...`
- **88QveMPv** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.1638, DD=0.1638。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), 2), 120)`
- **kq0JZLGz** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.09, TO=0.4646, DD=0.3167。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(mdl140_qes_sinc_comp, vec_avg(annual_price_peak)), 252)`
- **KP9mE3WE** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.04, TO=0.3871, DD=0.1445。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(vec_avg(company_employee_count), 60)`
- **ZYnmnOoj** (UNSUBMITTED, other): Sharpe=1.4, Fitness=0.73, TO=0.2748, DD=0.05。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(rank(mdl106_fmb), 10), 5)`
- **YP0x0VKA** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.04, TO=0.2351, DD=0.1859。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), 2), 120)`
- **P03M3Lg7** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.1011, DD=0.2551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_cash_and_equivalents)...`
- **ZYnmnVo0** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.01, TO=0.0947, DD=0.1015。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(capm_residual_volatility, 5), 50)`
- **omlolJ56** (UNSUBMITTED, other): Sharpe=-0.56, Fitness=-0.28, TO=0.0201, DD=0.3523。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(divide(subtract(mdl106_dividend, ts_mean(mdl106_dividend, 30)), ts_std_dev(mdl106_dividend, 3...`
- **e7060QZz** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.7135, DD=0.2683。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(aggregate_dollar_amount), add(vec_avg(bookrunner_proceeds_amount), vec_avg(aggregate_transacti...`
- **LL151Zx6** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.01, TO=1.0401, DD=0.559。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(aggregate_dollar_amount), add(vec_avg(bookrunner_proceeds_amount), vec_avg(aggregate_transacti...`
- **0mEjERnK** (UNSUBMITTED, other): Sharpe=-0.32, Fitness=-0.08, TO=0.0811, DD=0.1179。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(signed_power(ts_mean(analyst_recommendation_change_score_2, 30), 2), 252))`
- **0mEjEMY1** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.4684, DD=0.0776。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, vec_avg(latest_implied_valuation_price)), ts_std_dev(mdl140_qes_sinc_co...`
- **LL1516oe** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.0, TO=0.4872, DD=0.168。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(subtract(mdl140_qes_sinc_comp, vec_avg(annual_price_peak)), 2), 60)`
- **MPQ0prez** (UNSUBMITTED, other): Sharpe=0.48, Fitness=0.05, TO=0.8223, DD=0.015。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(signed_power(divide(subtract(beta_upper_confidence_band, beta_lower_confidence_band), beta_prediction_...`
- **omloKk5l** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.0986, DD=0.0656。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(capm_residual_volatility, 5), 50)`
- **1Ydj7JLQ** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.0, TO=0.5287, DD=0.0906。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(mdl140_qes_sinc_comp, vec_avg(latest_implied_valuation_price)), 60)`
- **781odPJO** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.13, TO=0.0779, DD=0.1709。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(ts_rank(add(accounts_payable_current, accounts_receivable_current), 252), 60)`
- **d50KQ6KX** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.11, TO=0.2041, DD=0.2156。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 40)), 20)`
- **d50KQ6mw** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.4945, DD=0.1668。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(signed_power(subtract(mdl140_qes_sinc_comp, vec_avg(annual_price_peak)), 2), 60)`
- **LL15R2Ee** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.08, TO=0.1649, DD=0.3613。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_cash_and_equivalents), 60)`
- **XgnRKNjl** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.02, TO=0.4582, DD=0.2937。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(divide(subtract(vec_avg(bookrunner_proceeds_amount), vec_avg(aggregate_dollar_amount)), add(abs(vec_avg(agg...`
- **O0ZJ9N9g** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.03, TO=0.0215, DD=0.3706。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_delta(sqrt(abs(mdl106_country)), 30), 10), 60))`
- **0mEjzV12** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.0, TO=0.0937, DD=0.0655。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(capm_residual_volatility, 5), 50)`
- **A1PQn7ve** (UNSUBMITTED, other): Sharpe=0.05, Fitness=0.01, TO=0.5399, DD=0.4269。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(aggregate_dollar_amount), add(vec_avg(bookrunner_proceeds_amount), 1)), 60)`
- **E5EVqkQ1** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.05, TO=0.2689, DD=0.1222。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(multiply(acquisition_purchase_price, acquired_goodwill), 20), 20)`
- **N1rennvp** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.0706, DD=0.2104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accounts_receivable_current_assets, accounts_payable_current), 60)`
- **GrLgnP5x** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.01, TO=0.9242, DD=0.7533。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(vec_avg(aggregate_dollar_amount), add(1, vec_avg(aggregate_transaction_proceeds))), 20)`
- **rKldJME9** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.11, TO=0.074, DD=0.2855。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accounts_receivable_current_assets, accounts_payable_current), 60)`
- **1YdjaZRJ** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.3916, DD=0.0651。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(company_employee_count), 60)`
- **omlo3Wan** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.21, TO=0.1232, DD=0.2505。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **LL15gd5m** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.04, TO=0.0233, DD=0.0555。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(capm_residual_volatility, subtract(annual_earnings_from_associates, ts_mean(add(acquired_goodwi...`
- **9qrEagl2** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.06, TO=0.2049, DD=0.135。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(subtract(annual_current_assets_value, annual_current_liabilities), 30), 20))`
- **j20e9Q8W** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.13, TO=0.1394, DD=1.1028。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(log(accounts_receivable_current_assets), 60)`
- **E5EVg5lK** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.08, TO=0.3934, DD=0.0387。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(company_employee_count_2), 252)`
- **zqmrPq5X** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.03, TO=0.0265, DD=0.056。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(capm_residual_volatility, subtract(annual_earnings_from_associates, ts_mean(add(acquired_goodwi...`
- **6X9AY65p** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.4, TO=0.0113, DD=0.1406。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **j20edxVE** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.09, TO=0.0389, DD=0.0631。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(company_employee_count_2), 60), 252)`
- **JjOP5ode** (UNSUBMITTED, other): Sharpe=0.0, Fitness=0.0, TO=0.021, DD=0.2378。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(divide(accounts_receivable_current_assets, accounts_payable_current), 60), 120)`
- **VkPdYGMY** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.02, TO=0.1469, DD=0.622。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(accounts_receivable_current_assets, accounts_payable_current), 20)`
- **d50KlX7j** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.1, TO=0.0278, DD=0.2971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(log(accounts_receivable_current_assets), 252), 20)`
- **kq0JmKK8** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.02, TO=0.024, DD=0.0555。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(capm_residual_volatility, subtract(annual_earnings_from_associates, ts_mean(add(acquired_goodwi...`
- **3qRj66dP** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.7141, DD=1.1534。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(analyst_recommendation_change_score_2), 30), 5))`
- **vRlO9oga** (UNSUBMITTED, other): Sharpe=-0.24, Fitness=-0.07, TO=0.0825, DD=0.3297。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(log(accounts_cash_and_equivalents), log(accounts_payable_current)), 60)`
- **YP0xmJKq** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.04, TO=0.9189, DD=1.0905。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(analyst_recommendation_change_score_2), 30), 5))`
- **MPQ0XZPa** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.02, TO=0.1638, DD=1.1125。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_zscore(log(accounts_receivable_current_assets), 60)`
- **aknVla7v** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.01, TO=0.3925, DD=0.0487。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(vec_avg(actual_investment_round_total), 252), 60)`
- **781oQ6PQ** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.14, TO=0.069, DD=0.306。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(log(accounts_cash_and_equivalents), log(accounts_payable_current)), 60)`
- **LL156lzM** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.0, TO=1.2805, DD=0.5512。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(vec_avg(bookrunner_proceeds_amount), 252), 20)`
- **E5EVbrZ0** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.03, TO=1.2809, DD=0.6975。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(vec_avg(bookrunner_proceeds_amount), 252), 20)`
- **kq0JXx18** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.05, TO=0.3916, DD=0.1132。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(vec_avg(company_employee_count), 60), 252)`
- **vRlOxYKd** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.3916, DD=0.0857。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(log(vec_avg(company_employee_count)), ts_mean(log(vec_avg(company_employee_count)), 252)), ts...`
- **O0ZJq5nv** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.1735, DD=0.1833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), ts_std_dev(mdl140_qes_sinc_comp, 60...`
- **P03MqakK** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.02, TO=0.1802, DD=0.1553。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), ts_std_dev(mdl140_qes_sinc_comp, 60...`
- **VkPdwmkw** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.04, TO=0.2638, DD=0.1772。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(mdl140_qes_sinc_comp, ts_mean(mdl140_qes_sinc_comp, 60)), ts_std_dev(mdl140_qes_sinc_comp, 60...`
- **O0ZJwaw1** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.1, TO=0.0659, DD=0.0426。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(annual_net_income_change_percent, 20))`
- **blq82GqM** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.05, TO=0.0246, DD=0.2658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(log(accounts_receivable_current), max(accounts_cash_and_equivalents, accounts_payable_current)), 252)`
- **qMlEeJvA** (UNSUBMITTED, other): Sharpe=-0.45, Fitness=-0.19, TO=0.2564, DD=0.6234。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(multiply(vec_avg(actual_investment_round_total), log(abs(vec_avg(company_employee_count)))), add(1, ve...`
- **mLbYeNvW** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.04, TO=0.0675, DD=0.2128。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(accounts_receivable_current, accounts_payable_current), 60)`
- **ZYnmkdVn** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.05, TO=0.0202, DD=0.3667。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(log(accounts_receivable_current), max(accounts_cash_and_equivalents, accounts_payable_current)), 252)`
- **2rLjPw3N** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.0608, DD=0.0954。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_current_assets_equity), 60)`
- **mLbYemrx** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.01, TO=0.0809, DD=0.0609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(divide(ts_mean(accumulated_amortization_of_capital_assets, 30), 50), ts_delta(accumulated_other_asse...`
- **xAk1XnGp** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.15, TO=0.0776, DD=0.2765。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(accumulated_amortization_of_capital_assets, multiply(accumulated_other_assets, sign(accumulate...`
- **xAk1XX5n** (UNSUBMITTED, other): Sharpe=-0.45, Fitness=-0.19, TO=0.2564, DD=0.6234。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(multiply(vec_avg(actual_investment_round_total), log(abs(vec_avg(company_employee_count)))), add(1, ve...`
- **e706eeeE** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.06, TO=0.0211, DD=0.2749。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(log(accounts_receivable_current), max(accounts_cash_and_equivalents, accounts_payable_current)), 252)`
- **gJMW7v80** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.2, TO=0.0189, DD=0.4361。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(sqrt(fnd17_2tcpngmpoa), multiply(log(fnd17_adiv5yavg), subtract(fnd17_aebitd5yr, fnd17_3_reptoprcexr...`
- **VkPdKj75** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.07, TO=0.0548, DD=0.1187。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accounts_receivable_current, accounts_payable_current), 60)`
- **e706epOg** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.04, TO=0.3043, DD=0.3759。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(multiply(vec_avg(actual_investment_round_total), log(abs(vec_avg(company_employee_count)))), add(1, ve...`
- **0mEjnbPK** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.08, TO=0.0577, DD=0.2891。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(subtract(accounts_receivable_current, accounts_payable_current), 60)`
- **lelMxQjN** (UNSUBMITTED, other): Sharpe=-0.27, Fitness=-0.06, TO=0.0818, DD=0.1243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_current_assets_equity), 60)`
- **vRlO0aza** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0502, DD=0.0858。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(accounts_receivable_current, accounts_payable_current), accounts_current_assets_equity), 60)`
- **qMlEZJVO** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.0, TO=0.3925, DD=0.0389。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(vec_avg(actual_investment_round_total), 60)`
- **JjOPLz1A** (UNSUBMITTED, other): Sharpe=0.79, Fitness=0.35, TO=0.3566, DD=0.1309。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(multiply(signed_power(vec_avg(actual_investment_round_total), 2), log(abs(add(vec_avg(aggregate_dollar...`
- **lelMZ3An** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.18, TO=0.0199, DD=0.4295。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(sqrt(fnd17_2tcpngmpoa), multiply(log(fnd17_adiv5yavg), subtract(fnd17_aebitd5yr, fnd17_3_reptoprcexr...`
- **6X9AbxPJ** (UNSUBMITTED, other): Sharpe=-0.32, Fitness=-0.14, TO=0.0168, DD=0.4214。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(sqrt(fnd17_2tcpngmpoa), multiply(log(fnd17_adiv5yavg), subtract(fnd17_aebitd5yr, fnd17_3_reptoprcexr...`
- **1YdZmw2K** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.1, TO=0.0212, DD=0.3774。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(sqrt(fnd17_2tcpngmpoa), multiply(log(fnd17_adiv5yavg), subtract(fnd17_aebitd5yr, fnd17_3_reptoprcexr...`
- **1YdZLMWK** (UNSUBMITTED, other): Sharpe=0.58, Fitness=0.17, TO=0.053, DD=0.0405。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(annual_net_income_change_percent, 20))`
- **j208XonO** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.14, TO=0.064, DD=0.0353。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(annual_net_income_change_percent, 20))`
- **58Og9JnN** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.08, TO=0.2241, DD=0.087。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(divide(annual_revenue_per_share, 1)), 10), 60))`
- **3qRVx6mZ** (UNSUBMITTED, other): Sharpe=0.34, Fitness=0.1, TO=0.1745, DD=0.1191。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(divide(annual_revenue_per_share, 1)), 10), 60))`
- **ZYnAxxPx** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.08, TO=0.2241, DD=0.087。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(annual_revenue_per_share), 10), 60))`
- **omlWvAZE** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.02, TO=0.1345, DD=0.1642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(divide(annual_revenue_per_share, 1)), 10), 60))`
- **lelK2q7N** (UNSUBMITTED, other): Sharpe=0.45, Fitness=0.16, TO=0.1507, DD=0.1135。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(divide(annual_revenue_per_share, 1)), 10), 60))`
- **d501mpAY** (UNSUBMITTED, other): Sharpe=0.34, Fitness=0.1, TO=0.1745, DD=0.1191。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(annual_revenue_per_share), 10), 60))`
- **2rLmQxL5** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.24, TO=0.1338, DD=0.1154。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(divide(annual_revenue_per_share, 1)), 10), 60))`
- **QPVKqNMW** (UNSUBMITTED, other): Sharpe=0.11, Fitness=0.02, TO=0.1345, DD=0.1642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(annual_revenue_per_share), 10), 60))`
- **YP0Mnxzq** (UNSUBMITTED, other): Sharpe=0.45, Fitness=0.16, TO=0.1507, DD=0.1135。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(annual_revenue_per_share), 10), 60))`
- **xAkb9Yqq** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.24, TO=0.1338, DD=0.1154。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(log(annual_revenue_per_share), 10), 60))`
- **88QP7laV** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.04, TO=0.2078, DD=0.1085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_net_income_excl_extraordinary, ts_mean(add(annual_total_revenue, annual_total_assets_val...`
- **LL1Zqb0L** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.06, TO=0.2007, DD=0.1413。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_net_income_excl_extraordinary, ts_mean(add(annual_total_revenue, annual_total_assets_val...`
- **6X9K3gPY** (UNSUBMITTED, other): Sharpe=1.19, Fitness=0.72, TO=0.0552, DD=0.071。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(annual_net_income_excl_extraordinary, divide(annual_total_shareholders_equity, ts_mean(annual_reve...`
- **omlWA11b** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.15, TO=0.0975, DD=0.2057。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **np2Pkrx3** (UNSUBMITTED, other): Sharpe=1.15, Fitness=0.66, TO=0.0567, DD=0.0647。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(annual_net_income_excl_extraordinary, divide(annual_total_shareholders_equity, ts_mean(annual_reve...`
- **qMl0kxXV** (UNSUBMITTED, other): Sharpe=-0.82, Fitness=-0.39, TO=0.0939, DD=0.3452。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **LL1ZbjKe** (UNSUBMITTED, other): Sharpe=0.87, Fitness=0.35, TO=0.2619, DD=0.1028。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(annual_net_income_change_percent, 5))`
- **7816g1zZ** (UNSUBMITTED, other): Sharpe=0.0, Fitness=0.0, TO=0.0375, DD=0.1119。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(annual_total_revenue), 50), 50))`
- **7816O3K1** (UNSUBMITTED, other): Sharpe=-0.21, Fitness=-0.05, TO=0.0446, DD=0.1267。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(annual_total_revenue), 50), 50))`
- **omlW2a1v** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.036, DD=0.1315。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(annual_total_revenue), 50), 50))`
- **np2P03G3** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.08, TO=0.0545, DD=0.129。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(annual_total_revenue), 50), 50))`
- **GrLOV8ZQ** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.0344, DD=0.1103。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(annual_total_revenue), 50), 50))`
- **O0Z8eO8Y** (UNSUBMITTED, other): Sharpe=-0.76, Fitness=-0.35, TO=0.0874, DD=0.3221。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **6X9KbjL5** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.0392, DD=0.1726。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(annual_debt_to_equity_ratio, multiply(annual_revenue_per_share, ts_mean(annual_net_income_to_comm...`
- **2rLmdl5Z** (UNSUBMITTED, other): Sharpe=-0.2, Fitness=-0.04, TO=0.1827, DD=0.1459。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(add(accounts_receivable_current, accounts_payable_current), 5), 50), 20))`
- **WjGe8GQQ** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.1, TO=0.0266, DD=0.0904。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **WjGe8aqO** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.13, TO=0.0286, DD=0.0607。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **9qrW06xd** (UNSUBMITTED, technical): Sharpe=0.1, Fitness=0.02, TO=0.0297, DD=0.1144。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(daily_volume_to_shares_outstanding, ts_mean(sign(annual_revenue_change_percent), 30)))`
- **np2PMGgx** (UNSUBMITTED, other): Sharpe=-0.36, Fitness=-0.11, TO=0.1306, DD=0.1843。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **e70Qoz6d** (UNSUBMITTED, other): Sharpe=-0.46, Fitness=-0.16, TO=0.1491, DD=0.2218。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(annual_net_income_change_percent, 20))`
- **kq0g20pd** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.04, TO=0.2148, DD=0.1539。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(add(accounts_receivable_current, accounts_payable_current), 5), 50), 20))`
- **xAkb8rKW** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.13, TO=0.0346, DD=0.0997。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **pwl5r1bX** (UNSUBMITTED, other): Sharpe=0.47, Fitness=0.15, TO=0.0377, DD=0.0705。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **zqmb6QvE** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.3376, DD=0.2159。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accrued_interest_liabilities_2, 20))`
- **lelKOOQ7** (UNSUBMITTED, other): Sharpe=0.47, Fitness=0.15, TO=0.0326, DD=0.0655。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **e70QwpJl** (UNSUBMITTED, sentiment): Sharpe=1.07, Fitness=0.69, TO=0.2338, DD=0.1139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(anl46_sentiment, 10), 5)`
- **QPVKkZOM** (UNSUBMITTED, sentiment): Sharpe=0.12, Fitness=0.03, TO=0.1265, DD=0.1376。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(anl46_sentiment, 10), 5)`
- **j208EKbj** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.06, TO=0.0267, DD=0.1143。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_ebitda_value, log(add(ts_mean(annual_revenue_value, 20), annual_total_assets_value))), 2...`
- **N1rV0Z6E** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.1, TO=0.0881, DD=0.0451。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(accumulated_other_comprehensive_assets, 20), 30))`
- **lelKdPQ7** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.07, TO=0.1671, DD=0.1082。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accrued_interest_payable_2, ts_std_dev(ts_mean(ts_delta(rank(accumulated_amortization_contracts), 10),...`
- **9qrWY2xe** (UNSUBMITTED, other): Sharpe=0.34, Fitness=0.08, TO=0.2216, DD=0.0905。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accrued_interest_payable_2, ts_std_dev(ts_mean(ts_delta(rank(accumulated_amortization_contracts), 10),...`
- **blqOXAjR** (UNSUBMITTED, other): Sharpe=0.25, Fitness=0.06, TO=0.0845, DD=0.0518。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(accumulated_other_comprehensive_assets, 20), 30))`
- **A1Pv9ONY** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.1234, DD=0.1288。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(accrued_interest_payable_2, ts_std_dev(ts_mean(ts_delta(rank(accumulated_amortization_contracts), 10),...`
- **P03gNE5E** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.17, TO=0.0716, DD=0.0488。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(accumulated_other_comprehensive_assets, 20), 30))`
- **E5EROP61** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.1593, DD=0.2375。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(ts_delta(anl46_experts, 50), 20), 20))`
- **3qRVQJOX** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0575, DD=0.1864。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_delta(anl46_alphadecay, 20), 60), 120), 252)`
- **A1Pvjm7X** (UNSUBMITTED, other): Sharpe=0.4, Fitness=0.13, TO=0.2542, DD=0.1478。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(anl46_indicator, 20), 20)`
- **E5EROmrJ** (UNSUBMITTED, other): Sharpe=-0.16, Fitness=-0.03, TO=0.1177, DD=0.1866。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(accrued_interest_liabilities, ts_mean(ts_std_dev(ts_delta(rank(accrued_interest_liabilities_2), 100), 5),...`
- **0mErOrg6** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.03, TO=0.2877, DD=0.7372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_mean(fnd17_agrosmgn2, 20), ts_std_dev(fnd17_aebitd2, 20)), 5))`
- **e70QkO2g** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.1, TO=0.3406, DD=0.4175。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_cash_and_equivalents, subtract(accounts_total_current_assets, accounts_receivable_curr...`
- **KP9rlLek** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.2584, DD=0.1603。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(anl46_indicator, 20), 20)`
- **xAkbOgPl** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.16, TO=0.0081, DD=0.4263。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(accrued_assets_total, ts_std_dev(accrued_interest_liabilities, 30)), 60))`
- **QPVKZMYp** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.16, TO=0.0078, DD=0.4242。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(accrued_assets_total, ts_std_dev(accrued_interest_liabilities, 30)), 60))`
- **P03g0mRp** (UNSUBMITTED, other): Sharpe=0.23, Fitness=0.09, TO=0.0087, DD=0.4003。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(multiply(accrued_interest_liabilities, ts_zscore(divide(accrued_interest_long_term, accrued_i...`
- **MPQ3PNva** (UNSUBMITTED, other): Sharpe=0.49, Fitness=0.32, TO=0.253, DD=0.5313。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(add(fnd17_2_reptoprcexrate, ts_std_dev(divide(fnd17_1_usdtorepexrate, inverse(fnd17_2_usdtorepexrate)...`
- **MPQ3PY7z** (UNSUBMITTED, other): Sharpe=0.97, Fitness=1.04, TO=0.1197, DD=0.2173。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(add(fnd17_2_reptoprcexrate, ts_std_dev(divide(fnd17_1_usdtorepexrate, inverse(fnd17_2_usdtorepexrate)...`
- **A1Pv1QYQ** (UNSUBMITTED, other): Sharpe=-0.76, Fitness=-0.37, TO=0.4619, DD=1.3654。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(signed_power(ts_delta(fnd17_ainventory, 10), 2), 5))`
- **2rLmraaN** (UNSUBMITTED, other): Sharpe=0.24, Fitness=0.07, TO=0.0525, DD=0.1792。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(accounts_payable_current, 50))`
- **78168KqZ** (UNSUBMITTED, other): Sharpe=-0.36, Fitness=-0.1, TO=0.3282, DD=0.4。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_cash_and_equivalents, subtract(accounts_total_current_assets, accounts_receivable_curr...`
- **LL1ZLAw9** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.02, TO=0.0249, DD=0.32。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(fnd17_2rhsfcq, 20))`
- **1YdZq32K** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.0457, DD=0.2159。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(ts_delta(anl46_alphadecay, 20), 20), 20))`
- **0mErb27G** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.09, TO=0.0665, DD=0.0969。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(accrued_assets_total, 20), 20))`
- **blqOYzjZ** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.2, TO=0.0285, DD=0.4349。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_agrosmgn, multiply(fnd17_aebtnorm, divide(fnd17_aepsinclxo, fnd17_aintcov))), 20))`
- **O0Z81Mrq** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.1, TO=0.0881, DD=0.1214。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_rank(divide(add(fnd17_aebit, fnd17_aepsnorm), 50), 20), 5))`
- **rKle19J3** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.19, TO=0.021, DD=0.3468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_aebitd, ts_mean(fnd17_adivchg, 5)), 10))`
- **aknxrRqv** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.21, TO=0.0311, DD=0.53。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_agrosmgn, multiply(fnd17_aebtnorm, divide(fnd17_aepsinclxo, fnd17_aintcov))), 20))`
- **blqOYvr6** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.03, TO=0.224, DD=0.4024。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(fnd17_aebitd, fnd17_aebit), 100), 20))`
- **wplb8J8d** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.4529, DD=0.3499。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(multiply(accumulated_depreciation_2, accumulated_depreciation_other_assets), 10))`
- **7816kOE8** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.11, TO=0.0423, DD=0.0478。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(abs(subtract(accrued_assets_total, accrued_interest_liabilities))), 20), 100))`
- **E5ERZJeK** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.42, TO=0.1124, DD=0.1521。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_rank(divide(add(fnd17_aebit, fnd17_aepsnorm), 50), 20), 5))`
- **2rLm1MPx** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.02, TO=0.1414, DD=0.7055。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(signed_power(divide(fnd17_aebitdmg, ts_std_dev(divide(fnd17_aepsnorm, ts_zscore(fnd17_aebit, 50)), 20)), 5))`
- **P03gJJNK** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.16, TO=0.1812, DD=0.8369。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(fnd17_aebitd, fnd17_aebit), 100), 20))`
- **P032k3Px** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.14, TO=0.2417, DD=0.4705。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(fnd17_aebitdmg, 30), 10), 100)`
- **omlLxlQk** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.0, TO=0.1243, DD=0.1211。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(multiply(accounts_receivable_long_term, accrued_acquisition_costs), 20), 30))`
- **np2dL21w** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.1501, DD=0.1219。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(accrued_interest_income, 20)`
- **rKlOZWKJ** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.17, TO=0.3526, DD=0.42。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(fnd17_aebitdmg, 30), 10), 100)`
- **6X9j5q8Y** (UNSUBMITTED, other): Sharpe=-0.48, Fitness=-0.26, TO=0.0212, DD=0.412。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_aebitd, ts_mean(fnd17_adivchg, 5)), 10))`
- **MPQaJlKM** (UNSUBMITTED, other): Sharpe=1.92, Fitness=1.25, TO=0.1426, DD=0.0494。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(divide(ts_mean(annual_earnings_before_tax, 20), multiply(current_enterprise_value, enterprise_value_to_re...`
- **XgnbdwPx** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.01, TO=0.153, DD=0.1256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(multiply(accounts_receivable_long_term, accrued_acquisition_costs), 20), 30))`
- **QPVbwd5p** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.04, TO=0.1265, DD=0.401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_adebteps, subtract(fnd17_adepexp, ts_mean(fnd17_adeprescfz, 20))), 10))`
- **KP9N112p** (UNSUBMITTED, other): Sharpe=1.47, Fitness=0.89, TO=0.0608, DD=0.0512。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(divide(ts_mean(annual_earnings_before_tax, 20), multiply(current_enterprise_value, enterprise_value_to_re...`
- **np2dEXew** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.03, TO=0.0567, DD=0.1396。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(annual_common_equity_value, 30), 20)`
- **Xgnb0J71** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.12, TO=0.0638, DD=0.1894。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(annual_common_equity_value, 30), 20)`
- **1YdXMZvk** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_zscore(ts_mean(inverse(fnd17_1_reptoprcexrate), 20), 30), 20))`
- **781NpJ5b** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.12, TO=0.273, DD=0.4204。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(sqrt(add(fnd17_adebteps, fnd17_adivshr)), 20), 60)`
- **j20A71p5** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.16, TO=0.2618, DD=0.4034。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(sqrt(add(fnd17_adebteps, fnd17_adivshr)), 20), 60)`
- **Xgnb0YKl** (UNSUBMITTED, other): Sharpe=-0.4, Fitness=-0.22, TO=0.3211, DD=1.5257。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(add(multiply(fnd17_adebteps, fnd17_adepexp), 50), 5), 20))`
- **lelvmZA8** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.06, TO=0.1292, DD=0.6403。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_adebteps, subtract(fnd17_adepexp, ts_mean(fnd17_adeprescfz, 20))), 10))`
- **omlLde8E** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.11, TO=0.259, DD=1.2599。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_adebteps, subtract(fnd17_adepexp, ts_mean(fnd17_adeprescfz, 20))), 10))`
- **e70bYXbN** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.2, TO=0.0768, DD=0.206。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(ts_delta(annual_basic_eps_excl_extraordinary, 50), 20), 10))`
- **RR8bOv50** (UNSUBMITTED, other): Sharpe=-0.52, Fitness=-0.19, TO=0.0763, DD=0.2153。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(ts_delta(annual_basic_eps_excl_extraordinary, 50), 20), 10))`
- **blqbmAgM** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.12, TO=0.0663, DD=0.1611。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(ts_delta(annual_basic_eps_excl_extraordinary, 50), 20), 10))`
- **rKlOq8z1** (UNSUBMITTED, other): Sharpe=1.09, Fitness=0.75, TO=0.0426, DD=0.1021。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(fnd17_acurratio, 20), 100)`
- **omlLbrxk** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.03, TO=0.2814, DD=0.7875。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_acogs, subtract(fnd17_acurast, ts_mean(subtract(fnd17_acurliab, fnd17_acurratio), 20))), ...`
- **WjGbZe6O** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.42, TO=0.1643, DD=0.3988。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(fnd17_2anrhsfcq, multiply(fnd17_abepsxclxo, fnd17_acapspps)), 50), 30))`
- **6X9jW16J** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.14, TO=0.1203, DD=0.3474。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(fnd17_2anrhsfcq, multiply(fnd17_abepsxclxo, fnd17_acapspps)), 50), 30))`
- **gJMblK9Q** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.0158, DD=0.2451。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(sqrt(accrued_interest_income), ts_delta(accounts_receivable_long_term, 100)), 50))`
- **YP0bVqeM** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.07, TO=0.4182, DD=0.1228。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(annual_net_income_excl_extraordinary, 100), 10))`
- **LL1NYvrL** (UNSUBMITTED, technical): Sharpe=-1.42, Fitness=-0.95, TO=0.0608, DD=0.3556。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_std_dev(ts_delta(subtract(normalized_volume_indicator_1, ts_mean(normalized_volume_indicator_2, 30...`
- **qMlxJ3nK** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.2471, DD=0.1496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(accum_depre, capex), 30), 100)`
- **E5EpPNa1** (UNSUBMITTED, other): Sharpe=0.37, Fitness=0.08, TO=1.6635, DD=0.514。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(anl10_analyst_innovation_cpx_revise_ratio_to_consensus_fy2, ts_mean(anl10_analyst_innovation_...`
- **lelvP812** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.08, TO=0.0352, DD=0.2566。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(cash_and_equivalents_annual_2, ts_mean(add(book_value_per_share_annual, ts_std_dev(multiply(common_equi...`
- **LL1NY16m** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.05, TO=0.2271, DD=0.2561。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(accounts_payable_year_end, 5), 30))`
- **88QjxaA7** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.07, TO=0.1569, DD=0.2158。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_receivable_gross_2, subtract(ts_mean(divide(accounts_total_receivables_current, invers...`
- **ZYnbvWj1** (UNSUBMITTED, other): Sharpe=-0.52, Fitness=-0.22, TO=0.0502, DD=0.2772。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(divide(enterprise_value_to_ebitda_current, current_ratio), 30), 50)`
- **XgnbAqq8** (UNSUBMITTED, other): Sharpe=0.0, Fitness=0.0, TO=0.0838, DD=0.314。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps))), 20), 20)`
- **88QjxbXX** (UNSUBMITTED, technical): Sharpe=-1.07, Fitness=-0.65, TO=0.1292, DD=0.3351。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(subtract(normalized_volume_indicator_0, ts_std_dev(normalized_trend_indicator_5, 50)), 100)...`
- **KP9Nppqk** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.01, TO=1.5329, DD=0.6754。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(anl10_analyst_innovation_cpx_revise_ratio_to_consensus_fy2, ts_mean(anl10_analyst_innovation_...`
- **RR8bo5Oo** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=1.5295, DD=0.6409。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(subtract(anl10_analyst_innovation_cpx_revise_ratio_to_consensus_fy2, ts_mean(anl10_analyst_innovation_...`
- **VkPaLagw** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.26, TO=0.0705, DD=0.2493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(normalized_trend_indicator_2, ts_mean(ts_std_dev(ts_delta(subtract(normalized_trend_indicator_3...`
- **aknb8EV2** (UNSUBMITTED, other): Sharpe=-0.5, Fitness=-0.25, TO=0.0517, DD=0.3086。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(normalized_trend_indicator_2, ts_mean(ts_std_dev(ts_delta(subtract(normalized_trend_indicator_3...`
- **mLbmNbo9** (UNSUBMITTED, other): Sharpe=-0.24, Fitness=-0.06, TO=0.0224, DD=0.1525。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(annual_ebit, add(annual_total_liabilities_value, annual_common_equity, filter=true)), 1...`
- **np2dlwOw** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.14, TO=0.0579, DD=0.4197。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps, filter=true))), 20), 20)`
- **kq0oMEeL** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.14, TO=0.0579, DD=0.4198。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps))), 20), 20)`
- **xAk3oKNW** (UNSUBMITTED, other): Sharpe=-0.26, Fitness=-0.05, TO=0.7902, DD=0.6261。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(vec_avg(mws50_rp_story_event_count), ts_std_dev(anl10_analyst_innovation_dps_innovate_increase_fy1, 30)))`
- **zqm8LnoK** (UNSUBMITTED, other): Sharpe=-0.37, Fitness=-0.08, TO=0.8532, DD=0.806。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(vec_avg(mws50_rp_story_event_count), ts_std_dev(anl10_analyst_innovation_dps_innovate_increase_fy1, 30)))`
- **aknbg8A6** (UNSUBMITTED, other): Sharpe=-0.49, Fitness=-0.16, TO=0.1661, DD=0.1743。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(rank(divide(normalized_trend_indicator_0, normalized_trend_indicator_1)), 30), 20), 100)`
- **E5Ep2QWP** (UNSUBMITTED, other): Sharpe=-0.24, Fitness=-0.06, TO=0.0224, DD=0.1523。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(annual_ebit, add(annual_total_liabilities_value, annual_common_equity)), 120), 252))`
- **np2dXN68** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.0241, DD=0.1883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(dividends_per_share_secondary, dividends_payable_short_term), 20))`
- **wplZvXP1** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.0153, DD=0.2898。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(subtract(annual_ebit, annual_depreciation_expense), 2), 5))`
- **aknbGE6w** (UNSUBMITTED, other): Sharpe=-0.47, Fitness=-0.21, TO=0.2673, DD=0.7244。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 2), 20))`
- **N1ra8pZ7** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0548, DD=0.3195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps, filter=true))), 20), 20)`
- **XgnbMwAx** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.2065, DD=0.1525。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(accum_depre, capex), 30), 100)`
- **d50boJ2g** (UNSUBMITTED, other): Sharpe=-0.34, Fitness=-0.13, TO=0.2551, DD=0.6222。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 20), 20))`
- **ZYnbMN2j** (UNSUBMITTED, other): Sharpe=-1.0, Fitness=-0.48, TO=0.1998, DD=0.4749。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(signed_power(subtract(anl10_analyst_innovation_bps_normal_increase_fy1, anl10_analyst_innovati...`
- **1YdXPK8W** (UNSUBMITTED, other): Sharpe=0.04, Fitness=0.0, TO=0.2036, DD=0.1627。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(accum_depre, capex), 30), 100)`
- **88QjYObz** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.02, TO=0.0548, DD=0.3184。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps))), 20), 20)`
- **blqbnomZ** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0285, DD=0.4672。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(amortization_expense_current, subtract(1, sqrt(rank(deposits_total)))), 50))`
- **2rLwWdJY** (UNSUBMITTED, other): Sharpe=-0.58, Fitness=-0.3, TO=0.1237, DD=0.3864。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **pwlRZAJ3** (UNSUBMITTED, other): Sharpe=0.28, Fitness=0.07, TO=0.2519, DD=0.2051。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(sqrt(ts_zscore(annual_net_income_available_common, 10)), 20))`
- **0mEXgak2** (UNSUBMITTED, cashflow): Sharpe=-0.09, Fitness=-0.01, TO=0.0843, DD=0.1152。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(cashflow_op, ts_mean(ts_delta(accum_depre, 50), 200)), 20))`
- **E5EpzV7J** (UNSUBMITTED, other): Sharpe=-0.03, Fitness=-0.0, TO=0.113, DD=0.3411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **58Oz5Nd5** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.01, TO=0.0955, DD=0.2922。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **P032zeex** (UNSUBMITTED, other): Sharpe=-0.23, Fitness=-0.06, TO=0.1559, DD=0.3573。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **JjONWQXl** (UNSUBMITTED, other): Sharpe=-0.24, Fitness=-0.07, TO=0.1277, DD=0.3213。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **6X9jZ2J7** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.17, TO=0.2635, DD=0.6547。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 20), 20))`
- **YP0b81XR** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.1128, DD=0.2274。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **QPVbOKLQ** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.134, DD=0.5106。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(multiply(fnd17_a2netmrgn, 2.5), ts_mean(fnd17_aastturn, 120)), 20))`
- **lelvEWLe** (UNSUBMITTED, other): Sharpe=-0.14, Fitness=-0.05, TO=0.0877, DD=0.3395。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps, filter=true))), 20), 20)`
- **0mEXxEk2** (UNSUBMITTED, other): Sharpe=-0.31, Fitness=-0.1, TO=0.1632, DD=0.2786。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **d50bYxpw** (UNSUBMITTED, other): Sharpe=-0.34, Fitness=-0.13, TO=0.0963, DD=0.2807。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **QPVbOlYW** (UNSUBMITTED, other): Sharpe=-0.48, Fitness=-0.21, TO=0.2347, DD=0.6118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 20), 20))`
- **mLbmdA95** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.04, TO=0.0877, DD=0.3427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(ts_mean(divide(assets_curr_oth, sqrt(add(equity, bookvalue_ps))), 20), 20)`
- **MPQadjQM** (UNSUBMITTED, other): Sharpe=-0.63, Fitness=-0.33, TO=0.1011, DD=0.3958。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **RR8b5Pv0** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.1404, DD=0.3226。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **9qrjGdp2** (UNSUBMITTED, other): Sharpe=-0.61, Fitness=-0.22, TO=1.2641, DD=1.4628。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_std_dev(normalize(anl10_analyst_innovation_bps_revise_ratio_to_close_fy2), 30), divide(anl10_an...`
- **N1raKPJ8** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.11, TO=1.4628, DD=0.7787。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_std_dev(normalize(anl10_analyst_innovation_bps_revise_ratio_to_close_fy2), 30), divide(anl10_an...`
- **XgnbNbal** (UNSUBMITTED, cashflow): Sharpe=0.25, Fitness=0.09, TO=0.071, DD=0.1653。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(cashflow_op, ts_mean(multiply(bookvalue_ps, add(capex, divide(debt_st, assets_curr_oth))), 20...`
- **3qRXGaJO** (UNSUBMITTED, other): Sharpe=-0.19, Fitness=-0.05, TO=0.0986, DD=0.2985。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(accounts_receivable_total_5, 20))`
- **3qRXGbvO** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.16, TO=0.1829, DD=0.6322。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(fnd17_2qe2dtlq, ts_mean(ts_std_dev(add(fnd17_2rhsfcq, fnd17_2rhsfca), 20), 20)), 60))`
- **O0ZNWR3R** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.6657, DD=1.4053。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(anl10_analyst_innovation_bps_revise_ratio_to_consensus_fy1, 60), 120))`
- **9qrjl6Md** (UNSUBMITTED, other): Sharpe=-0.05, Fitness=-0.01, TO=0.6666, DD=1.509。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(anl10_analyst_innovation_bps_revise_ratio_to_consensus_fy1, 60), 120))`
- **2rLw5Rb5** (UNSUBMITTED, other): Sharpe=-0.29, Fitness=-0.08, TO=0.1931, DD=0.2368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(anl10_analyst_innovation_bps_revise_ratio_to_consensus_fy1, anl10_analyst_innovation_cpx_revise_rati...`
- **A1PNVo1g** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.02, TO=0.1605, DD=0.1766。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(vec_avg(mws50_aes), 20), 20)`
- **aknbKza6** (UNSUBMITTED, other): Sharpe=-1.27, Fitness=-0.71, TO=0.6536, DD=2.1013。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_delta(depreciation_expense_4, 30), 20), 5), 20)`
- **58OzEgwk** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.19, TO=0.355, DD=0.604。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(rank(vec_avg(mws50_ens)), 20), 20), 10)`
- **9qrjxL02** (UNSUBMITTED, technical): Sharpe=-2.53, Fitness=-1.71, TO=0.0663, DD=0.5644。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(divide(mdl291_crowding_aunion2000_specific_returns, add(mdl291_fast_aunion2000_specific_ret...`
- **GrLbgNaO** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.08, TO=0.192, DD=0.0614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(rank(accounts_payable), 50), 20), 100)`
- **YP0bx9qv** (UNSUBMITTED, other): Sharpe=-1.27, Fitness=-0.6, TO=0.6479, DD=1.4709。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(last_close_price_5, ts_std_dev(multiply(last_close_price_6, ts_mean(available_monetary_instrume...`
- **rKlOddzj** (UNSUBMITTED, other): Sharpe=-2.21, Fitness=-1.07, TO=0.7737, DD=1.9014。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_delta(last_close_price_5, 10), 30), 10)`
- **xAk313gJ** (UNSUBMITTED, technical): Sharpe=-0.44, Fitness=-0.17, TO=0.702, DD=1.4052。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(mdl291_all_aunion2000_specific_returns, ts_std_dev(multiply(dividends_declared_per_share, ts_mean(cash...`
- **9qrjErlV** (UNSUBMITTED, other): Sharpe=-0.39, Fitness=-0.15, TO=0.2606, DD=0.52。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 2), 20))`
- **A1PNQgxX** (UNSUBMITTED, other): Sharpe=0.8, Fitness=0.57, TO=0.5132, DD=0.4641。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(subtract(anl10_analyst_innovation_bps_revise_value_fy2, ts_mean(ts_delta(anl10_analyst_innovation_cp...`
- **N1rae6PL** (UNSUBMITTED, other): Sharpe=0.32, Fitness=0.19, TO=0.2223, DD=0.7151。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(subtract(fnd4_chinascope_secmap, dividends_per_share_secondary), dividends_declared_per_share)...`
- **mLbm6voK** (UNSUBMITTED, other): Sharpe=-2.51, Fitness=-1.86, TO=0.0659, DD=0.6899。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_rank(divide(multiply(accumulated_amortization, accumulated_other_comprehensive_income), 20)...`
- **mLbm6WlK** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.07, TO=0.0734, DD=0.3623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_std_dev(ts_zscore(sqrt(divide(accumulated_other_comprehensive_income, ts_delta(accumulated_amortiz...`
- **P032gmgW** (UNSUBMITTED, other): Sharpe=-0.47, Fitness=-0.2, TO=0.2438, DD=0.5973。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl10_analyst_innovation_bps_revise_value_fy1, 1), 20), 20))`
- **np2dPqYx** (UNSUBMITTED, other): Sharpe=0.46, Fitness=0.21, TO=0.1027, DD=0.1361。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(add(anl10_analyst_innovation_bps_innovation_score_fy2, rank(anl10_analyst_innovation_cpx_innovation_score_fy2...`
- **0mEXrGMK** (UNSUBMITTED, other): Sharpe=-2.05, Fitness=-1.77, TO=0.0952, DD=0.9137。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_delta(accrued_interest_within_period, 10), 20), 60)`
- **88QjPlla** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.12, TO=0.0308, DD=0.3811。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(divide(anl10_analyst_innovation_bps_innovation_score_fy1, add(anl10_analyst_innovation_cpx_innovation_scor...`
- **blqbOQxq** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.36, TO=0.1088, DD=1.1387。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(ts_std_dev(advances_to_vendors, 50), 30), 20), 10)`
- **E5EpReMr** (UNSUBMITTED, other): Sharpe=0.43, Fitness=0.12, TO=0.1439, DD=0.0565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(eps, ts_mean(eps, 10)), 50))`
- **aknbxPYw** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.07, TO=0.0385, DD=1.1712。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(divide(cash_and_marketable_equivalents_assets, ts_mean(advances_to_suppliers_2, 100)), 30))`
- **XgnbJ5Vb** (UNSUBMITTED, other): Sharpe=-0.54, Fitness=-0.44, TO=0.1987, DD=2.195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_zscore(accounts_payable_noncurrent_2, 20), 20)`
- **88QjjXda** (UNSUBMITTED, other): Sharpe=-1.4, Fitness=-1.02, TO=0.0865, DD=0.6953。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(accrued_interest_payable_3, accounts_payable_noncurrent_2), 50))`
- **aknbbRb9** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.0336, DD=0.123。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(rank(accounts_receivable_gross), 100), 30)`
- **O0ZNNQGJ** (UNSUBMITTED, other): Sharpe=-0.96, Fitness=-0.7, TO=0.2998, DD=1.7446。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(multiply(accounts_payable_deferred_accruals, ts_mean(accounts_receivable_accrued, 10)), 100), 20))`
- **blqbbGql** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.04, TO=0.247, DD=1.1317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_payable_deferred_accruals, divide(accounts_receivable_accrued, accounts_receivable_g...`
- **d50bOomX** (UNSUBMITTED, other): Sharpe=-1.44, Fitness=-1.02, TO=0.1604, DD=0.9072。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_payable_deferred_accruals, ts_mean(divide(accounts_receivable_accrued, accounts_rece...`
- **O0ZNrRVY** (UNSUBMITTED, other): Sharpe=1.01, Fitness=0.5, TO=0.0222, DD=0.0735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(sign(annual_net_income_change_percent), 20))`
- **58OzQlOk** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.11, TO=0.0365, DD=0.0585。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(ebit, multiply(cogs, 0.8)), 252))`
- **XgnbWwvb** (UNSUBMITTED, other): Sharpe=-1.21, Fitness=-0.78, TO=0.0727, DD=0.573。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(divide(signed_power(ts_delta(accounts_payable_deferred_accruals, 50), 2), 30), sqrt(ts_std_dev(...`
- **1YdXxQOJ** (UNSUBMITTED, other): Sharpe=-0.53, Fitness=-0.5, TO=0.0197, DD=1.7903。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(divide(add(accounts_total_current_assets, ts_delta(accounts_receivable_current_assets, 20)), accounts_payable...`
- **xAk3j3Rg** (UNSUBMITTED, other): Sharpe=-0.27, Fitness=-0.12, TO=0.2021, DD=0.8183。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(ts_delta(accounts_payable_total_current, 100), ts_std_dev(accounts_payable_total_curren...`
- **aknb7OP2** (UNSUBMITTED, other): Sharpe=-0.13, Fitness=-0.05, TO=0.0951, DD=0.3253。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(ts_mean(divide(add(ebit, subtract(cash, debt)), bookvalue_ps), 20), rank(ts_zscore(divide(capex, assets_curr...`
- **P0327EXJ** (UNSUBMITTED, technical): Sharpe=-1.16, Fitness=-0.54, TO=0.1244, DD=0.2824。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(subtract(annual_revenue_change_percent, rank(daily_volume_to_shares_outstanding)), 20), 20)`
- **A1PN7r2l** (UNSUBMITTED, other): Sharpe=0.78, Fitness=0.46, TO=0.1786, DD=0.0861。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_std_dev(accounts_payable, 20), 20)`
- **QPVb9r8X** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.41, TO=0.0101, DD=0.1732。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(ebitda, log(divide(assets_curr, assets))), 20))`
- **zqm8mn9E** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.43, TO=0.0156, DD=0.1503。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(multiply(ebitda, ts_rank(assets, 100)), 20))`
- **wplZlNxl** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.0893, DD=0.1796。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_std_dev(multiply(annual_net_income_incl_extraordinary, annual_total_revenue), 60), 100), 20))`
- **1YdXdqkk** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.02, TO=0.128, DD=0.4502。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_delta(annual_revenue_value, 5), 20)`
- **blqbLvZr** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.2, TO=0.0966, DD=0.0365。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(divide(ts_delta(cash, 50), ts_mean(assets, 100)), 20))`
- **YP0bpmwo** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.04, TO=0.0525, DD=0.2426。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(accounts_cash_and_equivalents, 50))`
- **781Nw0O1** (UNSUBMITTED, other): Sharpe=-0.66, Fitness=-0.24, TO=0.1394, DD=0.2044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_payable, ts_mean(ts_delta(ebitda, 100), 100)), 20))`
- **xAk3xw8J** (UNSUBMITTED, other): Sharpe=-0.7, Fitness=-0.27, TO=0.046, DD=0.2128。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(ts_rank(multiply(annual_net_income_to_common, annual_revenue_per_share), 100), annual_book_va...`
- **88QjLl9l** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_regression(divide(signed_power(subtract(accounts_payable, cash), 2), bookvalue_ps), 100, 20), 30))`
- **qMlxXXzO** (UNSUBMITTED, other): Sharpe=0.89, Fitness=0.45, TO=0.4177, DD=0.1631。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(ebitda, log(ts_mean(multiply(assets, ts_zscore(cash, 10)), 20))), 5))`
- **gJMb3KXg** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.01, TO=0.0489, DD=0.0641。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_rank(multiply(annual_net_income_to_common, annual_revenue_per_share), 100), annual_book_value_p...`
- **vRlrmVGa** (UNSUBMITTED, other): Sharpe=0.43, Fitness=0.25, TO=0.0086, DD=0.4024。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(accounts_cash_and_equivalents, 20))`
- **rKlOAava** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=0.4415, DD=0.1412。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_delta(annual_revenue_value, 5), 5), 5)`
- **MPQak9ZM** (UNSUBMITTED, other): Sharpe=0.55, Fitness=0.26, TO=0.0929, DD=0.1462。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(anl46_alphadecay, subtract(ts_delta(anl46_indicator, 50), 50)), 20), 50))`
- **d50bn17x** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.4675, DD=1.3821。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(assets), 100), 10))`
- **omlLnYl2** (UNSUBMITTED, other): Sharpe=0.86, Fitness=0.44, TO=0.0218, DD=0.127。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(annual_net_income_change_percent, ts_rank(divide(annual_revenue_change_percent, abs(annual_debt_to_e...`
- **pwlRnE0v** (UNSUBMITTED, other): Sharpe=-0.41, Fitness=-0.09, TO=0.3436, DD=0.2249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(ebitda, multiply(assets, subtract(cash, debt))), 20), 60)`
- **0mEXewgv** (UNSUBMITTED, other): Sharpe=0.49, Fitness=0.22, TO=0.1392, DD=0.1031。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(annual_revenue_value, ts_mean(annual_revenue_value, 20)))`
- **pwlRVVKx** (UNSUBMITTED, other): Sharpe=-0.08, Fitness=-0.01, TO=0.0775, DD=0.1309。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(subtract(annual_revenue_value, annual_net_income_incl_extraordinary), 20), 100), 100)`
- **omlL9rm6** (UNSUBMITTED, other): Sharpe=0.03, Fitness=0.01, TO=0.1396, DD=0.9277。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_std_dev(subtract(accounts_receivable_current, accounts_payable_current), 20)`
- **WjGbW1bo** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.03, TO=0.2073, DD=0.1846。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(capex, ts_mean(signed_power(log(multiply(assets, bookvalue_ps)), 10), 30)), 20))`
- **aknbPbA2** (UNSUBMITTED, sentiment): Sharpe=0.76, Fitness=0.33, TO=0.2084, DD=0.0813。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(anl46_sentiment, 50), 10))`
- **RR8baZMz** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.04, TO=0.1377, DD=0.2302。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(ebitda, multiply(rank(accounts_payable), 100)), 20))`
- **gJMbK0J0** (UNSUBMITTED, sentiment): Sharpe=-0.51, Fitness=-0.43, TO=0.0643, DD=0.1569。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(subtract(anl46_alphadecay, ts_mean(divide(anl46_sentiment, ts_std_dev(anl46_performancepercentile, 5)), 10)),...`
- **2rLwR0r8** (UNSUBMITTED, other): Sharpe=-0.27, Fitness=-0.12, TO=0.0444, DD=0.3629。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(annual_net_income_incl_extraordinary, ts_std_dev(annual_total_revenue, 20)), 100), 200))`
- **QPVbq9NM** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.14, TO=0.0941, DD=0.2227。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(ts_std_dev(ts_delta(annual_net_income_change_percent, 20), 20), 20), 20))`
- **GrLbYeAP** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.09, TO=0.3475, DD=0.2381。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(annual_revenue_value, ts_std_dev(ts_delta(annual_net_income_incl_extraordinary, 20), 10)), 20))`
- **781NqpXv** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.01, TO=0.2889, DD=0.2206。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(multiply(annual_ebitda_amount, ts_zscore(subtract(annual_revenue_value, ts_mean(annual_net_income_incl_extrao...`
- **e70b8rlp** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.09, TO=0.1401, DD=0.3646。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_rank(fnd17_2rhsfcq, 30), 5)`
- **WjGbwjwG** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.15, TO=0.0419, DD=0.2061。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(ts_delta(annual_net_income_to_common, 20), annual_total_assets_value), 60))`
- **xAk3XJ9W** (UNSUBMITTED, technical): Sharpe=0.12, Fitness=0.01, TO=0.2052, DD=0.0676。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_zscore(add(multiply(annual_net_income_excl_extraordinary, ts_rank(daily_volume_to_shares_outstandi...`
- **omlL2r3v** (UNSUBMITTED, sentiment): Sharpe=-1.0, Fitness=-0.47, TO=0.2278, DD=0.5183。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(anl46_alphadecay, ts_std_dev(ts_delta(rank(anl46_sentiment), 20), 20)), 20)`
- **9qrjoXxq** (UNSUBMITTED, other): Sharpe=-0.43, Fitness=-0.11, TO=0.1599, DD=0.1337。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_zscore(add(ebitda, log(assets)), 50), 50))`
- **A1PN6wmQ** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.14, TO=0.0748, DD=0.5894。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_zscore(multiply(log(abs(fnd17_2qe2dtlq)), 50), 20), 10))`
- **9qrjo9Qd** (UNSUBMITTED, other): Sharpe=0.17, Fitness=0.03, TO=0.2931, DD=0.139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(subtract(assets, ts_mean(assets, 10)), 20), 10)`
- **omlLek06** (UNSUBMITTED, other): Sharpe=1.26, Fitness=0.7, TO=0.0362, DD=0.0432。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, ts_mean(add(assets, ts_std_dev(add(cash, debt_st, 60), 120), 252), 20)), 252))`
- **P032EPww** (UNSUBMITTED, other): Sharpe=-0.45, Fitness=-0.14, TO=0.1515, DD=0.1909。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(ts_delta(annual_net_income_change_percent, 30), 10), 100))`
- **aknb3bAW** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.04, TO=0.1078, DD=0.1693。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(ts_std_dev(ebitda, 30), ts_mean(ebitda, 5)), 50)`
- **j20AQnkO** (UNSUBMITTED, cashflow): Sharpe=0.33, Fitness=0.11, TO=0.0811, DD=0.0563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(cashflow_op, ts_mean(add(ebitda, log(assets_curr)), 20)), sqrt(ts_std_dev(debt_lt, 60)...`
- **A1PNKAag** (UNSUBMITTED, cashflow): Sharpe=-0.16, Fitness=-0.04, TO=0.0782, DD=0.1781。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, ts_mean(cashflow_op, 50)), 50))`
- **wplZgap5** (UNSUBMITTED, other): Sharpe=0.52, Fitness=0.19, TO=0.0995, DD=0.0493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(annual_revenue_change_percent, 50), 30), 20))`
- **blqbEWNZ** (UNSUBMITTED, other): Sharpe=-1.45, Fitness=-0.97, TO=0.0137, DD=0.5694。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(accounts_receivable_trade_current, accounts_payable_total_current), 100))`
- **wplZgw6d** (UNSUBMITTED, cashflow): Sharpe=0.46, Fitness=0.23, TO=0.0129, DD=0.1634。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(multiply(cashflow_op, subtract(log(assets), log(debt))), 30))`
- **pwlROgev** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.1546, DD=0.1398。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_delta(log(assets), 20), 20), 20), 20)`
- **wplZgxKl** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.26, TO=0.0118, DD=0.1551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(add(annual_net_income_to_common, ts_std_dev(ts_mean(sign(annual_revenue_value), 100), 10)))`
- **YP0bGajl** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.04, TO=0.054, DD=0.0859。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, ts_mean(cash_st, 20)), 100))`
- **zqm81rMV** (UNSUBMITTED, other): Sharpe=0.5, Fitness=0.26, TO=0.0218, DD=0.1362。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(accounts_payable_deferred_accruals, subtract(accounts_receivable_accrued, subtract(accrued_expenses_4, subtr...`
- **0mEX3e1p** (UNSUBMITTED, other): Sharpe=0.33, Fitness=0.08, TO=0.4092, DD=0.1454。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(annual_ebitda_amount, 10), 10), 100)`
- **qMlxr1rK** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.07, TO=0.0054, DD=0.7111。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(accounts_receivable_current, 10)`
- **d50bX71w** (UNSUBMITTED, sentiment): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(add(multiply(anl46_sentiment, log(ts_std_dev(anl46_performancepercentile, 50))), 50), 50), 10))`
- **O0ZNYaNp** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.04, TO=0.0743, DD=0.161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(anl46_alphadecay, 20), 20))`
- **pwlRXmN6** (UNSUBMITTED, other): Sharpe=-0.49, Fitness=-0.26, TO=0.3363, DD=1.476。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_receivable_trade_current, 20))`
- **LL1NjPQe** (UNSUBMITTED, other): Sharpe=-0.6, Fitness=-0.32, TO=0.0606, DD=0.4346。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(ebitda, multiply(assets, debt_lt)), 60))`
- **pwlRmZZj** (UNSUBMITTED, other): Sharpe=0.5, Fitness=0.23, TO=0.44, DD=0.4458。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ts_mean(fnd17_2rhsfcq, 20), sqrt(ts_std_dev(fnd17_2tcpngmpoa, 20))), 5))`
- **0mEXqEZ1** (UNSUBMITTED, other): Sharpe=-1.44, Fitness=-0.81, TO=0.1888, DD=0.6375。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(anl10_analyst_innovation_bps_revise_value_fy2, subtract(accounts_payable_current_3, acc...`
- **O0ZNOe9J** (UNSUBMITTED, other): Sharpe=-1.55, Fitness=-2.36, TO=0.1014, DD=0.218。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(sqrt(divide(accounts_receivable_trade_current, accumulated_depreciation_4)), ts_mean(log(abs(...`
- **qMlx9xmA** (UNSUBMITTED, other): Sharpe=-0.3, Fitness=-0.15, TO=0.13, DD=0.3004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(anl46_alphadecay, ts_mean(multiply(ts_std_dev(subtract(fnd17_2qe2dtlq, anl46_performancepercent...`
- **E5EpOENr** (UNSUBMITTED, other): Sharpe=0.1, Fitness=0.02, TO=0.1091, DD=0.2654。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(annual_total_revenue, ts_std_dev(ts_mean(subtract(annual_net_income_incl_extraordinary, ts_mean(annual_bo...`
- **58Oz8rq6** (UNSUBMITTED, sentiment): Sharpe=-1.04, Fitness=-0.67, TO=0.0712, DD=0.3768。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(anl46_alphadecay - ts_std_dev(sign(anl46_performancepercentile - ts_zscore(anl46_sentiment, 100)), 20), ...`
- **KP9NPNdE** (UNSUBMITTED, technical): Sharpe=0.08, Fitness=0.02, TO=0.0086, DD=0.2648。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(returns, sqrt(ts_mean(power(close - ts_delay(close, 1), 2), 20))), 60))`
- **vRlrRkJw** (UNSUBMITTED, other): Sharpe=-1.8, Fitness=-1.06, TO=0.0451, DD=0.4209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 10)), 252))`
- **JjONjdOO** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.02, TO=0.1565, DD=0.0907。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(ebitda, ts_mean(multiply(assets, rank(bookvalue_ps)), 30)), 30))`
- **MPQajpx8** (UNSUBMITTED, other): Sharpe=-0.42, Fitness=-0.19, TO=0.1424, DD=0.4707。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(accounts_receivable_trade_current, 5), 20))`
- **YP0bjAMR** (UNSUBMITTED, other): Sharpe=0.02, Fitness=0.0, TO=1.0157, DD=0.6701。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(multiply(sqrt(add(anl10_analyst_innovation_bps_revise_value_fy1, anl10_analyst_innovation_cpx_revise_v...`
- **2rLw1K0N** (UNSUBMITTED, other): Sharpe=0.12, Fitness=0.03, TO=0.0389, DD=0.3019。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(accounts_payable_current_3, ts_mean(subtract(accounts_receivable_trade_current, multiply(accumulated_depr...`
- **VkPavgo5** (UNSUBMITTED, cashflow): Sharpe=-0.0, Fitness=-0.0, TO=0.0807, DD=0.1497。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(multiply(bookvalue_ps, cashflow_op), 5), 50)`
- **j20A5EAO** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.02, TO=0.0053, DD=0.2868。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(ts_rank(assets, 100), ts_mean(cash, 20))`
- **E5Ev99o9** (UNSUBMITTED, other): Sharpe=1.14, Fitness=0.61, TO=0.0379, DD=0.0567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ebitda, ts_mean(ts_delta(cash, 10), 120)), 252))`
- **pwlP9zdj** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.12, TO=0.0136, DD=0.1632。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(divide(accounts_payable_current_3, accounts_payable_previous_year), 100))`
- **781Zeg8O** (UNSUBMITTED, other): Sharpe=-0.28, Fitness=-0.05, TO=1.7255, DD=0.9476。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl10_analyst_innovation_dps_innovation_score_fy1, ts_mean(multiply(anl10_analyst_innovation_bps_innova...`
- **vRlkQred** (UNSUBMITTED, other): Sharpe=-0.58, Fitness=-0.23, TO=0.0745, DD=0.2562。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_std_dev(accounts_payable + ts_zscore(cash / ts_mean(assets, 20), 10), 100), 100)`
- **88Q3w3gV** (UNSUBMITTED, other): Sharpe=-0.52, Fitness=-0.26, TO=0.0611, DD=0.4441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(ebitda, subtract(assets, debt)), 60))`
- **wplYrJRY** (UNSUBMITTED, other): Sharpe=-0.22, Fitness=-0.07, TO=0.0972, DD=0.2443。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_rank(ts_std_dev(annual_total_revenue / ts_mean(annual_net_income_incl_extraordinary, 30), 100), 20...`
- **aknL0vm1** (UNSUBMITTED, other): Sharpe=-1.51, Fitness=-0.9, TO=0.1929, DD=0.7483。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(accumulated_depreciation_4, 5), 100))`
- **qMlj63Wv** (UNSUBMITTED, sentiment): Sharpe=0.28, Fitness=0.05, TO=0.374, DD=0.111。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(add(divide(subtract(anl46_alphadecay, anl46_sentiment), anl46_performancepercentile), anl46_indicator), ...`
- **wpljENgd** (UNSUBMITTED, sentiment): Sharpe=0.15, Fitness=0.04, TO=0.0901, DD=0.1327。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(subtract(anl46_alphadecay, ts_mean(ts_min(ts_rank(anl46_sentiment, 100), 10), 20)), 30))`
- **781jn0Y1** (UNSUBMITTED, sentiment): Sharpe=0.34, Fitness=0.18, TO=0.1746, DD=0.2866。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_delta(log(anl46_sentiment), 50), 5))`
- **mLbjVkK5** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.04, TO=0.0898, DD=0.232。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_delta(anl46_alphadecay, 20), 60), 120), 252)`
- **lelj3XQO** (UNSUBMITTED, sentiment): Sharpe=0.91, Fitness=0.46, TO=0.1805, DD=0.0694。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(anl46_sentiment, ts_mean(anl46_sentiment, 50)), 100))`
- **mLbjV9L1** (UNSUBMITTED, sentiment): Sharpe=0.5, Fitness=0.19, TO=0.157, DD=0.0441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_delta(anl46_sentiment, 5), 100) / ts_std_dev(anl46_performancepercentile, 60), 200)`
- **akn7E6NW** (UNSUBMITTED, other): Sharpe=-0.71, Fitness=-0.7, TO=0.2015, DD=2.2837。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(add(accounts_receivable_trade_current, ts_zscore(ts_std_dev(accumulated_depreciation_4, 10), 10)), 10)`
- **QPV7VxaK** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.05, TO=0.1654, DD=0.6047。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`vector_neut(rank(close), rank(volume))`
- **VkP7PbnM** (UNSUBMITTED, sentiment): Sharpe=0.1, Fitness=0.02, TO=0.0822, DD=0.0883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_mean(multiply(anl46_indicator, sign(anl46_sentiment)), 20), ts_std_dev(anl46_performancepercent...`
- **np272lpl** (UNSUBMITTED, sentiment): Sharpe=1.22, Fitness=0.56, TO=0.2952, DD=0.0604。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(anl46_sentiment, 10), 100))`
- **vRljl6da** (UNSUBMITTED, sentiment): Sharpe=0.44, Fitness=0.17, TO=0.1535, DD=0.116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_av_diff(anl46_sentiment, 100), 200))`
- **A1PlPVoE** (UNSUBMITTED, other): Sharpe=0.2, Fitness=0.09, TO=0.0204, DD=0.5724。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(close)`
- **omlqlN0E** (UNSUBMITTED, other): Sharpe=-0.35, Fitness=-0.15, TO=0.3538, DD=1.2092。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_payable_current_3, accounts_receivable_trade_current), 20))`
- **xAkjkkxl** (UNSUBMITTED, sentiment): Sharpe=0.5, Fitness=0.16, TO=0.2476, DD=0.0852。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(anl46_sentiment, 20) * subtract(anl46_performancepercentile, divide(anl46_experts, ts_mean(anl46_indi...`
- **j20j0Wgk** (UNSUBMITTED, other): Sharpe=-0.57, Fitness=-0.28, TO=0.3103, DD=1.0692。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(subtract(accounts_receivable_trade_current, multiply(accumulated_depreciation_4, rank(advances_to_s...`
- **WjG7p0Jo** (UNSUBMITTED, other): Sharpe=0.15, Fitness=0.06, TO=0.0263, DD=0.2091。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(fnd17_2rhsfcq - ts_mean(log(ts_std_dev(anl46_indicator, 30)), 30), 30))`
- **omlqKrAv** (UNSUBMITTED, sentiment): Sharpe=0.11, Fitness=0.03, TO=0.0551, DD=0.13。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(anl46_alphadecay - ts_mean(anl46_performancepercentile * subtract(anl46_sentiment - ts_zscore(anl46_experts, 60)...`
- **A1Plw3mw** (UNSUBMITTED, other): Sharpe=-1.02, Fitness=-0.58, TO=0.1844, DD=0.6317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(accounts_receivable_trade_current * log(accounts_payable_current_3 - ts_mean(advances_to_suppliers_2, 10...`
- **omlqK1o6** (UNSUBMITTED, other): Sharpe=-0.0, Fitness=-0.0, TO=0.0396, DD=0.575。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(divide(fnd17_2rhsfcq, fnd17_2rhsfca), 20)`
- **rKljWVe3** (UNSUBMITTED, sentiment): Sharpe=0.39, Fitness=0.1, TO=0.2703, DD=0.0883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(fnd17_2rhsfca, ts_std_dev(ts_zscore(ts_mean(rank(anl46_sentiment), 20), 20), 10)), 60)`
- **d50jQYEY** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(accounts_payable_current_3 - subtract(ts_mean(ts_delta(accumulated_depreciation_4, 20), 100), 1), 1...`
- **YP07Alal** (UNSUBMITTED, sentiment): Sharpe=0.27, Fitness=0.05, TO=0.5686, DD=0.1719。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(multiply(anl46_performancepercentile, subtract(anl46_sentiment, divide(anl46_indicator, add(an...`
- **VkP78a1M** (UNSUBMITTED, sentiment): Sharpe=-0.53, Fitness=-0.26, TO=0.0557, DD=0.3127。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(anl46_sentiment, ts_mean(ts_delta(anl46_indicator, 5), 50)), 60))`
- **781jd1vx** (UNSUBMITTED, other): Sharpe=0.14, Fitness=0.03, TO=0.1629, DD=0.1198。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_delta(anl46_performancepercentile, 5) - ts_std_dev(anl46_indicator, 20), 10), 60), 120)`
- **Xgn7KKAl** (UNSUBMITTED, sentiment): Sharpe=0.21, Fitness=0.03, TO=0.7131, DD=0.1182。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(multiply(anl46_indicator, ts_rank(divide(anl46_sentiment, anl46_alphadecay), 5)), 20), 60)`
- **kq0jKQAK** (UNSUBMITTED, other): Sharpe=-1.84, Fitness=-1.07, TO=0.2175, DD=0.7384。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_zscore(subtract(accounts_receivable_trade_current, accounts_payable_total_current), 10), 60))`
- **WjG7gnjO** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.02, TO=0.339, DD=0.1398。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_alphadecay, ts_zscore(ts_mean(ts_delta(anl46_indicator, 20), 20), 20)))`
- **LL17RbLa** (UNSUBMITTED, other): Sharpe=0.08, Fitness=0.02, TO=0.2956, DD=0.77。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(subtract(fnd17_2rhsfca, ts_mean(fnd17_2rhsfca, 20)), ts_std_dev(fnd17_2rhsfca, 20)))`
- **O0Z79KGp** (UNSUBMITTED, other): Sharpe=-1.99, Fitness=-1.48, TO=0.0989, DD=0.6784。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(accounts_receivable_trade_current, 50), 50))`
- **KP97L36E** (UNSUBMITTED, sentiment): Sharpe=0.66, Fitness=0.35, TO=0.1253, DD=0.0649。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(rank(anl46_sentiment), 10), 100)`
- **MPQ7xjgM** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.36, TO=0.0601, DD=0.1557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(anl46_indicator, log(fnd17_2rhsfcq)), 20))`
- **A1PlkmdY** (UNSUBMITTED, sentiment): Sharpe=0.04, Fitness=0.01, TO=0.0847, DD=0.2978。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(divide(multiply(anl46_sentiment, anl46_experts), 5), 10), 5))`
- **omlqVRg5** (UNSUBMITTED, other): Sharpe=-1.3, Fitness=-0.82, TO=0.0311, DD=0.5385。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(sqrt(ts_mean(rank(accounts_payable_current_3), 50)), 252))`
- **58OlMEx6** (UNSUBMITTED, sentiment): Sharpe=0.97, Fitness=0.5, TO=0.2089, DD=0.0793。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_zscore(anl46_sentiment * anl46_indicator, 20), 5))`
- **blqjvQvm** (UNSUBMITTED, other): Sharpe=-0.89, Fitness=-0.56, TO=0.2478, DD=1.1062。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(divide(accumulated_depreciation_4, accounts_payable_total_current), 5) - subtract(accounts_receivable...`
- **VkP7OPv0** (UNSUBMITTED, other): Sharpe=-0.54, Fitness=-0.35, TO=0.2814, DD=1.5149。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(accumulated_depreciation_4, 20) / ts_std_dev(accounts_receivable_trade_current + ts_zscore(advances_t...`
- **JjO7bgZl** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.05, TO=0.642, DD=0.5039。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_2rhsfcq, fnd17_2rhsfca), 5))`
- **RR87dYeg** (UNSUBMITTED, other): Sharpe=-0.59, Fitness=-0.34, TO=0.3864, DD=1.5084。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(inverse(ts_std_dev(divide(accumulated_depreciation_4, accounts_payable_current_3), 20)), 60)`
- **RR87dZkd** (UNSUBMITTED, other): Sharpe=-0.98, Fitness=-0.79, TO=0.2541, DD=1.9026。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_payable_current_3, 60) * ts_delta(accumulated_other_comprehensive_income, 20))`
- **RR87dnve** (UNSUBMITTED, other): Sharpe=-1.81, Fitness=-1.75, TO=0.1965, DD=1.8824。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_payable_current_3, subtract(accumulated_depreciation_4, accounts_receivable_trade_current...`
- **RR87dQGj** (UNSUBMITTED, other): Sharpe=0.13, Fitness=0.03, TO=0.0554, DD=0.2675。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(log(divide(enterprise_value_to_ebitda_current, ts_mean(enterprise_value_to_ebitda_current, 50))), 50))`
- **vRlj5QLd** (UNSUBMITTED, other): Sharpe=-0.45, Fitness=-0.24, TO=0.021, DD=0.6066。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(subtract(fnd17_2rhsfcq, ts_std_dev(log(abs(fnd17_2tcpngmpoa)), 30)), 30)`
- **1Ydwo3vX** (UNSUBMITTED, other): Sharpe=-0.87, Fitness=-0.38, TO=0.5245, DD=1.2501。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(anl10_analyst_innovation_bps_innovation_score_fy1, 10) * multiply(ts_mean(anl10_analyst_innovation_bp...`
- **blqjNJx6** (UNSUBMITTED, sentiment): Sharpe=-0.87, Fitness=-0.45, TO=0.1647, DD=0.3277。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(subtract(anl46_sentiment, multiply(anl46_indicator, add(anl46_experts, ts_mean(anl46_performancepercentile, 20)))))`
- **np27n6Wq** (UNSUBMITTED, other): Sharpe=-0.5, Fitness=-0.19, TO=0.0445, DD=0.2488。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_receivable_trade_current, ts_mean(ts_delta(accumulated_depreciation_4, 1), 20)), 252))`
- **2rLlvbE6** (UNSUBMITTED, other): Sharpe=-0.02, Fitness=-0.0, TO=0.156, DD=0.4658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(fnd17_2qe2dtlq, ts_min(fnd17_2qe2dtlq, 120)), add(ts_max(fnd17_2qe2dtlq, 120), ts_min(...`
- **ZYn72N6n** (UNSUBMITTED, sentiment): Sharpe=0.26, Fitness=0.08, TO=0.1594, DD=0.1184。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(anl46_sentiment, ts_zscore(ts_mean(ts_rank(anl46_indicator, 20), 20), 10)), 60))`
- **e70zdRxM** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.09, TO=0.2737, DD=0.0912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_delta(fnd17_2rhsfcq, 50), 50) * ts_quantile(anl46_performancepercentile, 100))`
- **zqmkP1k1** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.04, TO=0.1688, DD=0.3192。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(fnd17_2rhsfcq, 5), 30)`
- **ZYn723N8** (UNSUBMITTED, other): Sharpe=-0.81, Fitness=-0.35, TO=0.2067, DD=0.4093。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(anl46_alphadecay, 5), 100), 20))`
- **9qrXaqYr** (UNSUBMITTED, other): Sharpe=1.13, Fitness=0.5, TO=0.2871, DD=0.0776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_av_diff(scale(anl46_indicator), 50), 100), 200)`
- **xAkjPKlW** (UNSUBMITTED, other): Sharpe=0.86, Fitness=0.4, TO=0.1968, DD=0.0774。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(signed_power(ts_delta(anl46_indicator, 5), 2), 20))`
- **j20jdpno** (UNSUBMITTED, sentiment): Sharpe=-0.1, Fitness=-0.01, TO=0.6572, DD=0.1586。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_zscore(ts_mean(multiply(anl46_sentiment, 5), 10), 5), 20))`
- **j20jdgNo** (UNSUBMITTED, sentiment): Sharpe=-0.34, Fitness=-0.13, TO=0.0452, DD=0.2851。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(subtract(fnd17_2rhsfca, ts_mean(ts_rank(anl46_sentiment, 30), 30)), fnd17_2rhsfcq))`
- **QPV75JGQ** (UNSUBMITTED, sentiment): Sharpe=0.61, Fitness=0.38, TO=0.2209, DD=0.3258。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_zscore(fnd17_2rhsfca, 100), 10) * anl46_sentiment)`
- **Xgn7Ymx5** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.12, TO=0.1125, DD=0.0695。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(anl46_alphadecay / ts_std_dev(fnd17_2rhsfca / ts_zscore(anl46_performancepercentile, 100), 20), 30), 50)`
- **1YdwmRxk** (UNSUBMITTED, other): Sharpe=-0.09, Fitness=-0.04, TO=0.1282, DD=1.0558。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(anl46_alphadecay), 50), 50))`
- **pwljzpZ6** (UNSUBMITTED, sentiment): Sharpe=1.3, Fitness=0.58, TO=0.414, DD=0.1179。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(rank(anl46_sentiment), ts_mean(rank(anl46_indicator), 10))`
- **781jXGwb** (UNSUBMITTED, other): Sharpe=0.44, Fitness=0.14, TO=0.6509, DD=0.4075。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(subtract(fnd17_2rhsfcq, fnd17_2rhsfca), 20), 5))`
- **6X9lqK0P** (UNSUBMITTED, sentiment): Sharpe=1.21, Fitness=0.85, TO=0.1204, DD=0.0603。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(inverse(sqrt(subtract(anl46_performancepercentile, ts_mean(anl46_sentiment, 20)))))`
- **akn7P3b2** (UNSUBMITTED, sentiment): Sharpe=-0.05, Fitness=-0.01, TO=0.2372, DD=0.2024。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_alphadecay, ts_zscore(ts_mean(add(anl46_indicator, anl46_sentiment), 20), 60)))`
- **1YdwmEKz** (UNSUBMITTED, sentiment): Sharpe=0.18, Fitness=0.05, TO=0.0508, DD=0.1648。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(ts_delta(ts_sum(anl46_sentiment, 10), 5), 20), 30))`
- **9qrX6Y1e** (UNSUBMITTED, other): Sharpe=-0.32, Fitness=-0.13, TO=0.2813, DD=0.7059。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(fnd17_2rhsfcq), 10), 30))`
- **e70zKjvd** (UNSUBMITTED, other): Sharpe=0.75, Fitness=0.41, TO=0.0357, DD=0.1228。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(divide(fnd17_2rhsfcq, fnd17_2rhsfca), 100), 30))`
- **N1r76Ede** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.26, TO=0.0994, DD=0.085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(multiply(ebitda, subtract(assets_curr, debt_st)), 60))`
- **j20jXPY9** (UNSUBMITTED, sentiment): Sharpe=-0.48, Fitness=-0.2, TO=0.0795, DD=0.196。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_performancepercentile, ts_mean(anl46_sentiment, 100)))`
- **781jQLrQ** (UNSUBMITTED, sentiment): Sharpe=-0.54, Fitness=-0.25, TO=0.0785, DD=0.2542。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(anl46_alphadecay - ts_zscore(anl46_experts + ts_rank(ts_mean(anl46_indicator - ts_rank(anl46_performance...`
- **zqmkjNOX** (UNSUBMITTED, sentiment): Sharpe=0.89, Fitness=0.41, TO=0.2113, DD=0.1092。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(divide(subtract(ts_mean(anl46_alphadecay, 20), ts_min(anl46_alphadecay, 60)), add(ts_std_dev(anl46...`
- **1YdwLdqM** (UNSUBMITTED, other): Sharpe=-0.06, Fitness=-0.01, TO=0.3433, DD=0.4615。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(multiply(anl46_alphadecay, 2), ts_mean(anl46_experts, 10)))`
- **kq0jXKG6** (UNSUBMITTED, sentiment): Sharpe=1.61, Fitness=1.16, TO=0.1677, DD=0.0469。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`subtract(anl46_indicator, ts_mean(anl46_sentiment, 20))`
- **9qrXKa0K** (UNSUBMITTED, sentiment): Sharpe=0.02, Fitness=0.0, TO=0.0364, DD=0.1496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(anl46_alphadecay + ts_rank(ts_std_dev(anl46_experts - ts_zscore(anl46_indicator + anl46_sentiment, 20), ...`
- **d50jmlWY** (UNSUBMITTED, sentiment): Sharpe=-0.64, Fitness=-0.21, TO=0.2956, DD=0.2307。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(subtract(anl46_alphadecay, anl46_performancepercentile), anl46_sentiment), 5))`
- **O0Z7wGjv** (UNSUBMITTED, sentiment): Sharpe=-0.58, Fitness=-0.28, TO=0.0775, DD=0.4622。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(anl46_alphadecay - ts_mean(ts_std_dev(rank(anl46_sentiment), 30), 30), 252))`
- **YP07wK6M** (UNSUBMITTED, sentiment): Sharpe=-0.19, Fitness=-0.05, TO=0.129, DD=0.1072。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(anl46_sentiment - ts_mean(anl46_performancepercentile * ts_std_dev(anl46_alphadecay - ts_delta(anl4...`
- **2rLlq0o6** (UNSUBMITTED, other): Sharpe=-0.01, Fitness=-0.0, TO=0.0988, DD=0.2194。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(divide(fnd17_2rhsfcq, inverse(anl46_indicator)), 30))`
- **vRljnwer** (UNSUBMITTED, sentiment): Sharpe=-0.23, Fitness=-0.07, TO=0.0768, DD=0.1245。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(subtract(anl46_alphadecay, ts_mean(subtract(anl46_performancepercentile, ts_zscore(multiply(anl46_ind...`
- **Xgn7XKMm** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.01, TO=0.425, DD=0.1333。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(anl46_performancepercentile, anl46_indicator), 20), 20)`
- **RR870aYb** (UNSUBMITTED, other): Sharpe=-0.04, Fitness=-0.0, TO=0.1028, DD=0.1528。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_mean(fnd17_2rhsfcq, 10), ts_std_dev(fnd17_2anrhsfcq, 30)), 60))`
- **MPQ79oXz** (UNSUBMITTED, other): Sharpe=0.96, Fitness=0.56, TO=0.0453, DD=0.0617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_rank(anl46_performancepercentile, 100), 100))`
- **YP07X6pJ** (UNSUBMITTED, other): Sharpe=0.09, Fitness=0.02, TO=0.1376, DD=0.2564。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_av_diff(fnd17_2rhsfca, 30), 100), 30))`
- **xAkjMG1l** (UNSUBMITTED, other): Sharpe=0.16, Fitness=0.04, TO=0.4139, DD=0.506。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(fnd17_2rhsfcq, ts_mean(fnd17_2rhsfcq, 20)), ts_std_dev(fnd17_2rhsfcq, 20)), 20))`
- **6X9lxj67** (UNSUBMITTED, other): Sharpe=0.26, Fitness=0.12, TO=0.0868, DD=0.2663。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_2rhsfcq, multiply(sqrt(divide(fnd17_2qe2dtlq, fnd17_2anrhsfcq)), 2)), 20))`
- **omlq2qab** (UNSUBMITTED, sentiment): Sharpe=0.45, Fitness=0.2, TO=0.0655, DD=0.1334。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(multiply(anl46_sentiment, rank(divide(anl46_performancepercentile, anl46_indicator))), ...`
- **e70zAzaO** (UNSUBMITTED, other): Sharpe=0.01, Fitness=0.0, TO=0.6734, DD=0.3724。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(subtract(fnd17_2rhsfcq, fnd17_2rhsfca), 5))`
- **leljx0L8** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.13, TO=0.0427, DD=0.1162。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_std_dev(fnd17_2rhsfcq, 20), 60))`
- **KP97e01j** (UNSUBMITTED, other): Sharpe=1.1, Fitness=0.45, TO=0.3185, DD=0.0668。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_av_diff(anl46_indicator, 20))`
- **KP97R1El** (UNSUBMITTED, sentiment): Sharpe=0.69, Fitness=0.38, TO=0.1171, DD=0.0704。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(divide(anl46_indicator, ts_std_dev(ts_delta(anl46_sentiment, 50), 50)))`
- **vRljVEXd** (UNSUBMITTED, other): Sharpe=0.07, Fitness=0.01, TO=0.2126, DD=0.1351。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(multiply(fnd17_2rhsfca, ts_mean(anl46_indicator, 20)), 5))`
- **QPV7d3ZW** (UNSUBMITTED, other): Sharpe=0.36, Fitness=0.13, TO=0.0686, DD=0.0902。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(sqrt(multiply(fnd17_2rhsfcq, ts_rank(divide(fnd17_2anrhsfcq, ts_mean(fnd17_2tcpngmpoa, 20)), 252))), 2...`
- **JjO7L7Ln** (UNSUBMITTED, other): Sharpe=-0.17, Fitness=-0.04, TO=0.3549, DD=0.3196。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(add(multiply(fnd17_2rhsfcq, fnd17_2tcpngmpoa), ts_zscore(ts_mean(divide(fnd17_2rhsfca, fnd17_2anrhsfc...`
- **Xgn7Eorz** (UNSUBMITTED, sentiment): Sharpe=1.03, Fitness=0.49, TO=0.2434, DD=0.0645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(anl46_sentiment, 30))`
- **88Qlq7KV** (UNSUBMITTED, sentiment): Sharpe=1.06, Fitness=0.67, TO=0.1395, DD=0.1。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(anl46_sentiment, abs(anl46_performancepercentile)), 30), 30))`
- **vRljgWpb** (UNSUBMITTED, other): Sharpe=1.14, Fitness=0.39, TO=0.5692, DD=0.0913。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(divide(anl46_indicator, 50), 50), 5))`
- **1YdwElqm** (UNSUBMITTED, other): Sharpe=0.3, Fitness=0.2, TO=0.1506, DD=0.6763。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(log(sqrt(abs(fnd17_2qe2dtlq))), 10), 30))`
- **1YdwExjX** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.13, TO=0.0148, DD=0.0992。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(divide(subtract(cash, ts_std_dev(ts_mean(divide(ebitda, assets), 30), 60)), ebitda), 60))`
- **xAkjgYNl** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.03, TO=0.0238, DD=0.3078。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(subtract(fnd17_2rhsfcq, ts_mean(fnd17_2tcpngmpoa, 20)), 60))`
- **RR87Wara** (UNSUBMITTED, other): Sharpe=0.71, Fitness=0.24, TO=0.3191, DD=0.0933。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(anl46_indicator, 5), 10))`
- **QPV7XLVQ** (UNSUBMITTED, other): Sharpe=0.06, Fitness=0.01, TO=0.1605, DD=0.5214。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(fnd17_2qe2dtlq, ts_mean(fnd17_2rhsfcq, 20)), 60))`
- **MPQ7mOQr** (UNSUBMITTED, other): Sharpe=-0.25, Fitness=-0.08, TO=0.2105, DD=0.4085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(fnd17_2rhsfcq, 20), 30))`
- **mLbjMQGX** (UNSUBMITTED, sentiment): Sharpe=0.12, Fitness=0.03, TO=0.0509, DD=0.1251。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(anl46_indicator - ts_std_dev(sqrt(anl46_performancepercentile * log(abs(anl46_sentiment - ts_rank(anl46_...`
- **mLbjM181** (UNSUBMITTED, sentiment): Sharpe=-0.95, Fitness=-0.41, TO=0.2449, DD=0.5211。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_av_diff(anl46_sentiment - anl46_indicator, 60), 60))`
- **QPV7LzGX** (UNSUBMITTED, other): Sharpe=-2.49, Fitness=-1.74, TO=0.0822, DD=0.6426。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(subtract(accounts_payable_total_current, ts_mean(ts_std_dev(subtract(accounts_receivable_trade_...`
- **9qrXLdkK** (UNSUBMITTED, other): Sharpe=-1.16, Fitness=-0.71, TO=0.1606, DD=0.6379。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_payable_current_3, subtract(accumulated_depreciation_4, ts_mean(accrued_expenses_4, ...`
- **6X9lvGbK** (UNSUBMITTED, sentiment): Sharpe=0.49, Fitness=0.37, TO=0.0668, DD=0.3293。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(log(anl46_sentiment), sqrt(abs(anl46_indicator))), 50))`
- **9qrXLEex** (UNSUBMITTED, other): Sharpe=-1.43, Fitness=-0.84, TO=0.0365, DD=0.477。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_sum(log(accounts_payable_current_3), 60) + ts_std_dev(accrued_expenses_4 + ts_mean(accounts_receiva...`
- **wpljMY92** (UNSUBMITTED, other): Sharpe=-0.33, Fitness=-0.18, TO=0.0861, DD=0.4978。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(subtract(fnd17_2qe2dtlq, ts_min(subtract(fnd17_2anrhsfcq, fnd17_2rhsfca), 10)), 20)`
- **VkP7gGNA** (UNSUBMITTED, other): Sharpe=0.22, Fitness=0.1, TO=0.0332, DD=0.6477。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(accounts_receivable_trade_current + ts_mean(accounts_payable_current_3 * log(accrued_expenses_4), 20))`
- **ZYn7eoxd** (UNSUBMITTED, other): Sharpe=-0.11, Fitness=-0.03, TO=0.0151, DD=0.4442。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(accounts_receivable_trade_current - subtract(ts_std_dev(accounts_payable_current_3, 10), 30), 20))`
- **QPV7Lngg** (UNSUBMITTED, other): Sharpe=-1.55, Fitness=-1.05, TO=0.1576, DD=0.7735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_payable_current_3, subtract(accumulated_depreciation_4, ts_mean(accrued_expenses_4, 20)))...`
- **e70zodjN** (UNSUBMITTED, other): Sharpe=0.21, Fitness=0.06, TO=0.1279, DD=0.1383。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(divide(fnd17_2rhsfcq, subtract(fnd17_2tcpngmpoa, fnd17_2anrhsfcq)), 50)`
- **P037djYL** (UNSUBMITTED, other): Sharpe=-2.36, Fitness=-1.66, TO=0.0562, DD=0.667。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_payable_current_3, multiply(accounts_receivable_trade_current, divide(accounts_payab...`
- **RR87nWPj** (UNSUBMITTED, other): Sharpe=-0.48, Fitness=-0.25, TO=0.0623, DD=0.5055。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(ts_zscore(subtract(fnd17_2rhsfcq, fnd17_2rhsfca), 50), 100))`
- **akn7qjx2** (UNSUBMITTED, other): Sharpe=-2.29, Fitness=-1.54, TO=0.0751, DD=0.5524。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_av_diff(accounts_receivable_trade_current, 20) - ts_mean(ts_delta(accrued_expenses_4, 10) * ts_std_...`
- **0mEw0mk6** (UNSUBMITTED, other): Sharpe=-1.44, Fitness=-0.98, TO=0.3146, DD=1.6881。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(accounts_payable_current_3 * ts_mean(accounts_payable_deferred_accruals * ts_std_dev(accounts_payable_...`
- **akn7Z0WO** (UNSUBMITTED, other): Sharpe=-2.31, Fitness=-1.77, TO=0.1183, DD=0.7422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(rank(accounts_receivable_trade_current), 50), 50), 30)`
- **leljOPqx** (UNSUBMITTED, other): Sharpe=-0.18, Fitness=-0.06, TO=0.0269, DD=0.3816。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(fnd17_2rhsfcq, 5))`
- **9qrX1kbq** (UNSUBMITTED, sentiment): Sharpe=0.09, Fitness=0.02, TO=0.0707, DD=0.1883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_zscore(anl46_sentiment, 100), 30)`
- **E5ElWx7L** (UNSUBMITTED, other): Sharpe=-1.73, Fitness=-1.14, TO=0.1689, DD=0.7774。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(subtract(accounts_receivable_trade_current, accounts_payable_total_current), 60), 30)`
- **N1r7m3oL** (UNSUBMITTED, other): Sharpe=-1.01, Fitness=-0.52, TO=0.1636, DD=0.4393。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(subtract(accounts_receivable_trade_current, ts_mean(accrued_expenses_4, 20)), 60))`
- **VkP7jZAM** (UNSUBMITTED, sentiment): Sharpe=0.03, Fitness=0.0, TO=0.0892, DD=0.1638。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(add(fnd17_2qe2dtlq, multiply(anl46_indicator, ts_mean(divide(anl46_performancepercentile, anl46_sentimen...`
- **VkP7j058** (UNSUBMITTED, other): Sharpe=-0.98, Fitness=-0.4, TO=0.8175, DD=1.6252。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_receivable_trade_current, ts_mean(accrued_expenses_4, 50)), 5))`
- **xAkj8bnm** (UNSUBMITTED, other): Sharpe=0.85, Fitness=0.42, TO=0.1786, DD=0.1032。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(ts_mean(anl46_indicator, 5), 50))`
- **leljO8mn** (UNSUBMITTED, other): Sharpe=-2.56, Fitness=-1.68, TO=0.1788, DD=0.793。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_std_dev(subtract(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 100)), ...`
- **Xgn7QWO1** (UNSUBMITTED, other): Sharpe=-0.82, Fitness=-0.3, TO=0.3824, DD=0.6394。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_std_dev(anl10_analyst_innovation_bps_revise_value_fy1 * ts_zscore(ts_mean(anl10_analyst_innovati...`
- **MPQ7RQ5a** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.19, TO=0.6058, DD=0.1219。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(ts_delta(anl46_alphadecay, 10), multiply(0.1, log(abs(anl46_indicator)))), 10))`
- **akn7ZAWO** (UNSUBMITTED, other): Sharpe=-2.2, Fitness=-1.13, TO=0.3218, DD=0.8519。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(add(accounts_payable_current_3, ts_mean(accounts_receivable_trade_current, 100)), 20))`
- **ZYn73Wd1** (UNSUBMITTED, other): Sharpe=-0.66, Fitness=-0.39, TO=0.1786, DD=0.8896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_av_diff(ts_mean(log(abs(accounts_payable_current_3)), 30), 30), 30))`
- **e70zwpzM** (UNSUBMITTED, other): Sharpe=-1.7, Fitness=-1.07, TO=0.1561, DD=0.703。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(divide(subtract(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 20)), ac...`
- **VkP7jvVA** (UNSUBMITTED, other): Sharpe=-3.83, Fitness=-1.95, TO=0.685, DD=1.7432。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(accounts_receivable_trade_current, 20) * ts_std_dev(rank(available_for_sale_investments), 5), 20)`
- **1Ydw9Knm** (UNSUBMITTED, other): Sharpe=0.27, Fitness=0.1, TO=0.2582, DD=0.3201。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(ts_mean(ts_delta(subtract(fnd17_2qe2dtlq, ts_mean(fnd17_2rhsfcq, 20)), 5), 5), 20))`
- **ZYn75Qod** (UNSUBMITTED, other): Sharpe=-2.97, Fitness=-2.19, TO=0.1581, DD=0.8524。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(subtract(accounts_payable_current_3 * ts_delta(log(accounts_receivable_trade_current), 50), 30), 50...`
- **pwljXdVv** (UNSUBMITTED, other): Sharpe=-2.05, Fitness=-1.36, TO=0.0864, DD=0.5372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_zscore(divide(accounts_receivable_trade_current, accounts_payable_total_current), 100))`
- **VkP79x10** (UNSUBMITTED, other): Sharpe=-0.07, Fitness=-0.03, TO=0.1668, DD=1.0748。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(accounts_payable_current_3 + subtract(accounts_payable_deferred_accruals / ts_std_dev(accou...`
- **9qrXvrXe** (UNSUBMITTED, other): Sharpe=-1.64, Fitness=-0.96, TO=0.2843, DD=1.0326。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(accounts_payable_total_current, ts_zscore(rank(accumulated_depreciation_4), 30)), 120)`
- **rKlj3WME** (UNSUBMITTED, sentiment): Sharpe=0.26, Fitness=0.09, TO=0.1209, DD=0.1912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(ts_mean(ts_std_dev(ts_delta(anl46_sentiment, 5), 10), 20), 60), 252)`
- **O0Z7Y5RY** (UNSUBMITTED, other): Sharpe=-2.02, Fitness=-1.4, TO=0.1, DD=0.5865。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(add(sqrt(divide(accounts_receivable_trade_current, ts_mean(accounts_payable_total_current, 30))), log(abs(amo...`
- **d50jXlbw** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.39, TO=0.0268, DD=0.1997。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_mean(divide(anl46_alphadecay, ts_std_dev(anl46_indicator, 30)), 20))`
- **6X9l8qVL** (UNSUBMITTED, other): Sharpe=-1.31, Fitness=-0.98, TO=0.1251, DD=0.7299。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(accounts_payable_current_3 / ts_std_dev(accounts_receivable_trade_current / ts_zscore(accounts_payabl...`
- **9qrXvbJx** (UNSUBMITTED, other): Sharpe=-0.72, Fitness=-0.54, TO=0.2537, DD=1.6271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_rank(accrued_expenses_4 - ts_mean(accounts_payable_current_3 - ts_zscore(accounts_receivable_trade_current, 2...`
- **leljq6rn** (UNSUBMITTED, other): Sharpe=-0.74, Fitness=-0.35, TO=0.6305, DD=2.0285。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(accounts_payable_current_3, accounts_receivable_trade_current), 10), 5)`
- **j20jEEVe** (UNSUBMITTED, other): Sharpe=-0.71, Fitness=-0.52, TO=0.1631, DD=1.169。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_mean(ts_delta(log(accounts_payable_current_3), 5), 20), 30)`

---


### 2026-07-25 16:41 UTC

- **0mMRl8Wk** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=0.98, TO=0.0688, DD=0.1712。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **rKP53J9m** (UNSUBMITTED, technical): Sharpe=1.21, Fitness=1.1, TO=0.0515, DD=0.1534。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **akELYjx6** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.04, TO=0.0498, DD=0.175。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **9q7VYrNK** (UNSUBMITTED, technical): Sharpe=1.19, Fitness=1.07, TO=0.0505, DD=0.164。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **MPL1Omzr** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=0.94, TO=0.0821, DD=0.1533。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **2rNOMzXZ** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=0.97, TO=0.0846, DD=0.1458。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **P0OZQv87** (UNSUBMITTED, technical): Sharpe=1.13, Fitness=0.9, TO=0.0932, DD=0.1219。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **RR1Vj0lg** (UNSUBMITTED, technical): Sharpe=1.22, Fitness=1.11, TO=0.0521, DD=0.1506。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **Vk361gWA** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.09, TO=0.0509, DD=0.1591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **gJ9Qk62v** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **bldRlnZr** (UNSUBMITTED, other): Sharpe=0.54, Fitness=0.29, TO=0.0178, DD=0.2177。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **bldRlJjZ** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **58kQ8zdn** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **wpEYpeM5** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.34, TO=0.0205, DD=0.2209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **vRvkRxLv** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0218, DD=0.2249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **omg61kdk** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **58kQZe0n** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.35, TO=0.0308, DD=0.2217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **LLd9Pz0a** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.32, TO=0.0236, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **1Yzxqp96** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.35, TO=0.0308, DD=0.2217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **JjvxVvoA** (UNSUBMITTED, other): Sharpe=0.38, Fitness=0.18, TO=0.0128, DD=0.1719。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **pwKPq8wq** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **YPg7ROKo** (UNSUBMITTED, analyst): Sharpe=0.65, Fitness=0.95, TO=0.0847, DD=0.6924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **P0O7kKAL** (UNSUBMITTED, other): Sharpe=0.53, Fitness=0.26, TO=0.0279, DD=0.2401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **9q7XNra2** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0x7lo31** (UNSUBMITTED, analyst): Sharpe=1.69, Fitness=1.14, TO=0.1522, DD=0.0464。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **QP97wrZ5** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.15, TO=0.1279, DD=0.0453。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **np87LRPw** (UNSUBMITTED, analyst): Sharpe=1.47, Fitness=1.0, TO=0.0923, DD=0.0491。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **j2rj7PjZ** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5eldN3R** (UNSUBMITTED, analyst): Sharpe=1.71, Fitness=1.01, TO=0.1638, DD=0.0465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **Jjv797kn** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5eld0vL** (UNSUBMITTED, analyst): Sharpe=1.32, Fitness=0.84, TO=0.0666, DD=0.0557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0x7L33b** (UNSUBMITTED, analyst): Sharpe=1.69, Fitness=1.14, TO=0.1522, DD=0.0464。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **QP97xp55** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **N1R7dP8L** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.07, TO=0.2084, DD=0.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **QP97xEGQ** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **Grel2VAP** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.19, TO=0.0194, DD=0.1383。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **e7xzYlkp** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0232, DD=0.1066。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **MPL7v1pr** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.12, TO=0.0246, DD=0.1038。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **j2rjknY5** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0234, DD=0.1063。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **Jjv7aYAA** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.11, TO=0.0237, DD=0.1056。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **mLVjnM3p** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.12, TO=0.0245, DD=0.1038。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **Xg87ZmJ8** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.13, TO=0.0241, DD=0.1045。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **YPg7o95l** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.09, TO=0.0139, DD=0.1876。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **MPL7N7mz** (UNSUBMITTED, technical): Sharpe=1.13, Fitness=1.3, TO=0.049, DD=0.3139。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **78njRdzZ** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **0mMw28n6** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0236, DD=0.1078。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **3qelvdEe** (UNSUBMITTED, technical): Sharpe=1.08, Fitness=1.18, TO=0.0495, DD=0.2967。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **le3jPOrN** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.55, TO=0.0282, DD=0.3536。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **2rNlxxkx** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.15, TO=0.049, DD=0.2942。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **YPg7Oa0R** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.67, TO=0.0364, DD=0.437。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **LLd7w7Ym** (UNSUBMITTED, technical): Sharpe=1.11, Fitness=1.3, TO=0.0519, DD=0.317。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **A17l5dXg** (UNSUBMITTED, technical): Sharpe=1.14, Fitness=1.31, TO=0.0474, DD=0.315。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **9q7X3YdK** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.4, TO=0.0485, DD=0.3063。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **omgqX82b** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=1.27, TO=0.0513, DD=0.3152。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **wpEjv0vx** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.36, TO=0.0425, DD=0.314。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **0mMwaL68** (UNSUBMITTED, technical): Sharpe=1.08, Fitness=1.22, TO=0.0544, DD=0.3122。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **bldjKJNm** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **2rNl25YZ** (UNSUBMITTED, technical): Sharpe=1.05, Fitness=1.1, TO=0.0483, DD=0.2928。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **58kl2jbX** (UNSUBMITTED, other): Sharpe=2.07, Fitness=0.85, TO=0.6276, DD=0.0401。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **wpEjvwwp** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **RR17v0wz** (UNSUBMITTED, other): Sharpe=1.84, Fitness=0.6, TO=0.9575, DD=0.0416。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Jjv72EJW** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **9q7Xk3p1** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Vk37emn8** (UNSUBMITTED, other): Sharpe=2.16, Fitness=1.1, TO=0.3828, DD=0.0422。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **N1R78O0X** (UNSUBMITTED, other): Sharpe=1.84, Fitness=0.6, TO=0.9575, DD=0.0416。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Xg87M23x** (UNSUBMITTED, other): Sharpe=2.1, Fitness=1.33, TO=0.1634, DD=0.0409。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **O0x7gel7** (UNSUBMITTED, other): Sharpe=2.14, Fitness=1.0, TO=0.4734, DD=0.0395。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **xAdj5gVN** (UNSUBMITTED, other): Sharpe=1.88, Fitness=1.3, TO=0.1325, DD=0.0431。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **A17lEj6d** (UNSUBMITTED, other): Sharpe=2.14, Fitness=1.21, TO=0.2803, DD=0.0435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-25 19:12 UTC

- **qM6WgMXP** (UNSUBMITTED, technical): Sharpe=1.08, Fitness=0.83, TO=0.0871, DD=0.1352。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **1Yzxo9QK** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.01, TO=0.0491, DD=0.1841。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **58kQazo1** (UNSUBMITTED, other): Sharpe=0.65, Fitness=0.35, TO=0.0308, DD=0.2217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **akELWzRv** (UNSUBMITTED, other): Sharpe=0.51, Fitness=0.25, TO=0.0212, DD=0.2467。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **9q7VAXZK** (UNSUBMITTED, other): Sharpe=0.63, Fitness=0.33, TO=0.0277, DD=0.2222。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **le38RVG2** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.92, TO=0.0115, DD=0.6558。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **mLVgxZEp** (UNSUBMITTED, other): Sharpe=0.63, Fitness=0.33, TO=0.0258, DD=0.2242。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **rKP5zrj1** (UNSUBMITTED, analyst): Sharpe=1.38, Fitness=0.84, TO=0.085, DD=0.0527。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **np8Kzxpx** (UNSUBMITTED, analyst): Sharpe=1.74, Fitness=1.16, TO=0.1534, DD=0.0451。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5evbjGP** (UNSUBMITTED, analyst): Sharpe=1.23, Fitness=0.76, TO=0.0528, DD=0.0594。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **akELlgzw** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5evbNqr** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0224, DD=0.1082。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **2rNOROJZ** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **GredYjxJ** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.12, TO=0.0246, DD=0.1038。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **d5ROg32j** (UNSUBMITTED, technical): Sharpe=1.29, Fitness=1.18, TO=0.0216, DD=0.1157。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **bldRVQLK** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.09, TO=0.0144, DD=0.1853。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **e7x982jJ** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.2, TO=0.053, DD=0.3125。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **1YzxVm1m** (UNSUBMITTED, technical): Sharpe=1.19, Fitness=1.61, TO=0.0301, DD=0.3661。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **akELX082** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=1.2, TO=0.0564, DD=0.3153。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **LLd9OoVv** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.63, TO=0.0283, DD=0.3656。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **le38JAqA** (UNSUBMITTED, technical): Sharpe=1.09, Fitness=1.24, TO=0.0562, DD=0.3153。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **A170qk8Y** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.34, TO=0.0437, DD=0.3156。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **LLd9e21e** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.24, TO=0.1133, DD=0.0448。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **vRvk08KQ** (UNSUBMITTED, other): Sharpe=1.81, Fitness=1.22, TO=0.1674, DD=0.0426。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **A170dlPR** (UNSUBMITTED, other): Sharpe=1.57, Fitness=1.09, TO=0.1723, DD=0.0599。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **GredvPa5** (UNSUBMITTED, other): Sharpe=2.09, Fitness=1.26, TO=0.2241, DD=0.039。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-25 21:44 UTC

- **KPEOmM8j** (UNSUBMITTED, technical): Sharpe=1.21, Fitness=1.1, TO=0.052, DD=0.1506。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **1Yzxjdvz** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.01, TO=0.0491, DD=0.1841。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **58kQjoPk** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.08, TO=0.0507, DD=0.1617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **omg6o5km** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.08, TO=0.0507, DD=0.1617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **KPEOrgl1** (UNSUBMITTED, other): Sharpe=0.62, Fitness=0.32, TO=0.0246, DD=0.2261。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **e7x9QQoE** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.05, TO=0.0531, DD=0.1917。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **KPEOr68N** (UNSUBMITTED, other): Sharpe=0.61, Fitness=0.31, TO=0.0229, DD=0.2269。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **xAdY3lXb** (UNSUBMITTED, other): Sharpe=0.39, Fitness=0.19, TO=0.0148, DD=0.1681。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **1YzxXm8z** (UNSUBMITTED, analyst): Sharpe=1.54, Fitness=1.1, TO=0.1105, DD=0.0494。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **RR1VbRke** (UNSUBMITTED, analyst): Sharpe=1.32, Fitness=0.84, TO=0.0666, DD=0.0557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **Jjvxx3Ln** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.07, TO=0.2084, DD=0.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **j2r33g65** (UNSUBMITTED, analyst): Sharpe=1.41, Fitness=0.93, TO=0.0806, DD=0.052。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5evv3bG** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0226, DD=0.1081。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **Vk3661d0** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=0.96, TO=0.2237, DD=0.043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0xr7x51** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.19, TO=0.0196, DD=0.1412。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **Vk367ORb** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.09, TO=0.0145, DD=0.1837。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **np8K79aM** (UNSUBMITTED, technical): Sharpe=1.29, Fitness=1.18, TO=0.0217, DD=0.1152。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **YPg57jMo** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.18, TO=0.0183, DD=0.1458。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **1Yzxp8vz** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7119。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **6Xerp0jJ** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0229, DD=0.1077。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **le38WVgA** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.64, TO=0.0339, DD=0.4245。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **ZYK0Kzon** (UNSUBMITTED, technical): Sharpe=1.23, Fitness=1.55, TO=0.0461, DD=0.3215。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **LLd91bZn** (UNSUBMITTED, other): Sharpe=1.71, Fitness=1.22, TO=0.1347, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Vk36prA0** (UNSUBMITTED, other): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Xg8Wp388** (UNSUBMITTED, other): Sharpe=1.88, Fitness=1.3, TO=0.1325, DD=0.0431。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 00:15 UTC

- **Jjvx1p5O** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.02, TO=0.0494, DD=0.1799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **YPg5JrWR** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=0.99, TO=0.0697, DD=0.167。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **kqZVGzj8** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.86, TO=0.0904, DD=0.1271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **LLd9zZl1** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.04, TO=0.0527, DD=0.1928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **akELzJEv** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.37, TO=0.0189, DD=0.2123。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **3qe9k2ng** (UNSUBMITTED, other): Sharpe=0.59, Fitness=0.3, TO=0.0168, DD=0.2236。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **9q7Vdkm1** (UNSUBMITTED, other): Sharpe=0.56, Fitness=0.3, TO=0.0238, DD=0.2146。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **LLd9m7zm** (UNSUBMITTED, analyst): Sharpe=1.47, Fitness=1.0, TO=0.0923, DD=0.0492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **RR1Vlaae** (UNSUBMITTED, analyst): Sharpe=1.57, Fitness=1.1, TO=0.1118, DD=0.0466。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **E5ev831L** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.92, TO=0.0498, DD=0.695。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **d5ROYvKX** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=1.19, TO=0.0228, DD=0.1123。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **RR1V9bYa** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.11, TO=0.0237, DD=0.1056。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **wpEY3VKQ** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.54, TO=0.0502, DD=0.3439。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **QP93WgqG** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.4, TO=0.045, DD=0.3281。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **9q7VGj6K** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.33, TO=0.0452, DD=0.3158。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **Jjvx3pxn** (UNSUBMITTED, other): Sharpe=1.73, Fitness=1.04, TO=0.2966, DD=0.0798。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **O0xr6q5J** (UNSUBMITTED, other): Sharpe=2.26, Fitness=0.91, TO=0.6182, DD=0.0338。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 02:47 UTC

- **xAdYZOKw** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.06, TO=0.0502, DD=0.1684。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **QP93xz1M** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=0.97, TO=0.0846, DD=0.1458。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **YPg5V1GJ** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.08, TO=0.0507, DD=0.1617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **KPEOoYGN** (UNSUBMITTED, technical): Sharpe=1.21, Fitness=1.1, TO=0.0515, DD=0.1534。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **MPL1vvEn** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.35, TO=0.0196, DD=0.2166。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **xAdY7zrb** (UNSUBMITTED, other): Sharpe=0.42, Fitness=0.21, TO=0.0108, DD=0.1546。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **bldR0ZpN** (UNSUBMITTED, analyst): Sharpe=0.65, Fitness=0.95, TO=0.0847, DD=0.6924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **zqRYnrzR** (UNSUBMITTED, analyst): Sharpe=0.63, Fitness=0.9, TO=0.0304, DD=0.6988。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **e7x9Z2eO** (UNSUBMITTED, analyst): Sharpe=0.66, Fitness=0.97, TO=0.1157, DD=0.6912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **A170861g** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **1YzxR0EJ** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.1, TO=0.0147, DD=0.1809。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **78nZrqqL** (UNSUBMITTED, technical): Sharpe=1.27, Fitness=1.7, TO=0.0343, DD=0.4328。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **j2r3JNKe** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.38, TO=0.0439, DD=0.3183。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **2rNOxkNb** (UNSUBMITTED, technical): Sharpe=1.28, Fitness=1.75, TO=0.0357, DD=0.4348。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **3qe92mrZ** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=1.12, TO=0.054, DD=0.296。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **gJ9Q08N0** (UNSUBMITTED, other): Sharpe=1.66, Fitness=0.56, TO=0.9738, DD=0.0563。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **QP93onJQ** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.91, TO=0.0477, DD=0.6879。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **LLd92xve** (UNSUBMITTED, other): Sharpe=1.65, Fitness=0.73, TO=0.659, DD=0.0849。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **88e321Ml** (UNSUBMITTED, other): Sharpe=2.14, Fitness=1.0, TO=0.4734, DD=0.0395。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 05:18 UTC

- **gJ9bpPkJ** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.04, TO=0.0524, DD=0.1938。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **6XejvpEY** (UNSUBMITTED, other): Sharpe=0.43, Fitness=0.22, TO=0.0105, DD=0.1491。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **bldb5ZeR** (UNSUBMITTED, other): Sharpe=0.64, Fitness=0.92, TO=0.0112, DD=0.6563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **Vk3aVRAV** (UNSUBMITTED, analyst): Sharpe=1.28, Fitness=0.75, TO=0.0702, DD=0.0552。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **np8d9eJl** (UNSUBMITTED, analyst): Sharpe=1.41, Fitness=0.93, TO=0.0806, DD=0.052。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **vRvr8qgd** (UNSUBMITTED, analyst): Sharpe=1.27, Fitness=0.8, TO=0.0584, DD=0.0579。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **9q7jZpNx** (UNSUBMITTED, technical): Sharpe=1.25, Fitness=1.1, TO=0.0235, DD=0.106。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **GrebrjZ5** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7117。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **1YzXYPJR** (UNSUBMITTED, technical): Sharpe=1.19, Fitness=1.35, TO=0.0448, DD=0.2847。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **WjVbE70x** (UNSUBMITTED, other): Sharpe=2.03, Fitness=0.65, TO=0.9462, DD=0.0356。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **Vk3av8WV** (UNSUBMITTED, other): Sharpe=0.68, Fitness=0.8, TO=0.1973, DD=0.6388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **1YzXqVVR** (UNSUBMITTED, other): Sharpe=2.03, Fitness=0.65, TO=0.9462, DD=0.0356。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 06:35 UTC

- **Xg8bpe25** (UNSUBMITTED, analyst): Sharpe=1.28, Fitness=0.75, TO=0.0702, DD=0.0552。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **9q7jwl81** (UNSUBMITTED, analyst): Sharpe=1.71, Fitness=1.01, TO=0.1638, DD=0.0465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **np8dWe03** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=1.2, TO=0.0224, DD=0.1129。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **zqR85VkX** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=1.18, TO=0.0519, DD=0.3127。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **WjVbNZXG** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.41, TO=0.0407, DD=0.2995。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **A17NO7KW** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.61, TO=0.0449, DD=0.3196。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **0mMXQ2X8** (UNSUBMITTED, other): Sharpe=0.67, Fitness=0.98, TO=0.1142, DD=0.6534。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **e7xbK68p** (UNSUBMITTED, other): Sharpe=1.73, Fitness=1.04, TO=0.2966, DD=0.0798。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **j2rAX29j** (UNSUBMITTED, other): Sharpe=0.66, Fitness=0.96, TO=0.0823, DD=0.6688。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 07:12 UTC

- **9q7jWvAq** (UNSUBMITTED, technical): Sharpe=1.51, Fitness=1.32, TO=0.0176, DD=0.0928。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **j2rAAO7e** (UNSUBMITTED, technical): Sharpe=1.41, Fitness=1.2, TO=0.0171, DD=0.1298。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **ZYKbbbMj** (UNSUBMITTED, technical): Sharpe=1.62, Fitness=1.47, TO=0.0203, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **2rNwwqgJ** (UNSUBMITTED, technical): Sharpe=1.61, Fitness=1.47, TO=0.02, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **bldbRAKr** (UNSUBMITTED, technical): Sharpe=1.52, Fitness=1.34, TO=0.0188, DD=0.0863。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **P0O2ZYVW** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **le3v8av8** (UNSUBMITTED, technical): Sharpe=1.61, Fitness=1.47, TO=0.02, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **ZYKb0E8Y** (UNSUBMITTED, technical): Sharpe=1.43, Fitness=1.22, TO=0.0168, DD=0.1223。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **KPENOYYl** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **QP9b3MZg** (UNSUBMITTED, other): Sharpe=-0.12, Fitness=-0.09, TO=0.0254, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzXw3kW** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **YPgb7aal** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR1b7e3g** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgLqglJ** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **wpEZjE5d** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **58kzp7Pk** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzXzRxm** (UNSUBMITTED, other): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **O0xNxjxR** (UNSUBMITTED, other): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdNd36e** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.06, TO=0.0243, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 08:09 UTC

- **Xg8bNg25** (UNSUBMITTED, other): Sharpe=0.37, Fitness=0.27, TO=0.0156, DD=0.21。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **akEba3jv** (UNSUBMITTED, other): Sharpe=0.19, Fitness=0.1, TO=0.0156, DD=0.3111。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **QP9bKVZX** (UNSUBMITTED, technical): Sharpe=1.51, Fitness=1.32, TO=0.0183, DD=0.0879。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **j2rA8ZNe** (UNSUBMITTED, technical): Sharpe=1.46, Fitness=1.49, TO=0.0144, DD=0.1918。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`

---


### 2026-07-26 10:43 UTC

- **e7xQRJnz** (UNSUBMITTED, other): Sharpe=1.36, Fitness=0.69, TO=0.0609, DD=0.0387。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_income / equity, 126), subindustry)`
- **88ePdMpz** (UNSUBMITTED, technical): Sharpe=1.22, Fitness=1.11, TO=0.0521, DD=0.1506。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **le3KbEMx** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=0.95, TO=0.0825, DD=0.1511。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **6XeKV0ZJ** (UNSUBMITTED, technical): Sharpe=1.14, Fitness=0.96, TO=0.068, DD=0.1763。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **JjvQwQjA** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.08, TO=0.0507, DD=0.1617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **58kgbvl6** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=1.09, TO=0.0512, DD=0.1563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **E5eROoeK** (UNSUBMITTED, other): Sharpe=0.54, Fitness=0.29, TO=0.0172, DD=0.2176。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **6Xej52WJ** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.01, TO=0.1356, DD=0.0478。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **np8dL3Va** (UNSUBMITTED, analyst): Sharpe=1.8, Fitness=1.08, TO=0.2061, DD=0.0451。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **j2rAqnmj** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.07, TO=0.2084, DD=0.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **kqZopoOL** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=1.19, TO=0.0228, DD=0.1123。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **akEb9m9x** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.18, TO=0.0187, DD=0.1423。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **0mMX2YPq** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.59, TO=0.0227, DD=0.345。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **wpEZA0Ll** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.37, TO=0.0433, DD=0.3166。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **pwKR3KOv** (UNSUBMITTED, other): Sharpe=-0.1, Fitness=-0.06, TO=0.0256, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **mLVmQrA1** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **le3v1LNn** (UNSUBMITTED, other): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-26 11:11 UTC

- **88ePr2NW** (UNSUBMITTED, news): Sharpe=-0.23, Fitness=-0.14, TO=0.02, DD=0.513。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPEr67Rz** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **qM60do8j** (UNSUBMITTED, news): Sharpe=0.16, Fitness=0.08, TO=0.014, DD=0.3266。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR16YJpj** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **le3KkrP8** (UNSUBMITTED, news): Sharpe=-0.09, Fitness=-0.06, TO=0.0241, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **E5eRYZkr** (UNSUBMITTED, news): Sharpe=-0.1, Fitness=-0.07, TO=0.0241, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7xQ8M5J** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPErYGjN** (UNSUBMITTED, news): Sharpe=-0.2, Fitness=-0.12, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Xg8JwExl** (UNSUBMITTED, news): Sharpe=0.16, Fitness=0.07, TO=0.0141, DD=0.3292。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 11:27 UTC

- **d5R1lRjw** (UNSUBMITTED, news): Sharpe=-0.1, Fitness=-0.06, TO=0.0253, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **3qeVnZPg** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **YPgMk8qW** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.027, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgWzlq6** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **bldOPo3l** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j2r8wb1Z** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.4971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 11:33 UTC

- **RR162Wqn** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.06, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 11:53 UTC

- **j2r81mpO** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPErX2Vl** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 14:19 UTC

- **Vk30Zomw** (UNSUBMITTED, news): Sharpe=-0.22, Fitness=-0.13, TO=0.0181, DD=0.5254。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **d5R19E6x** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **2rNmG1Eb** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78n6YqWx** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **MPL369nr** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPErg3ox** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **xAdbrWYN** (UNSUBMITTED, news): Sharpe=-0.11, Fitness=-0.07, TO=0.024, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **xAdbrdbm** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **d5R1WlYY** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR16E0lb** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78n6L8X1** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdZ5xj6** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7xQ677d** (UNSUBMITTED, news): Sharpe=-0.2, Fitness=-0.12, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **rKPeexl9** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzZZZzm** (UNSUBMITTED, news): Sharpe=-0.21, Fitness=-0.12, TO=0.0198, DD=0.4894。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdZZk9L** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **mLV6maGE** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **9q7Wj7Ae** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **P0Og23vq** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **JjvQNXll** (UNSUBMITTED, news): Sharpe=-0.11, Fitness=-0.08, TO=0.0259, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **O0x8NQ3J** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **9q7WV7je** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzZxdEm** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzZxm8m** (UNSUBMITTED, news): Sharpe=0.19, Fitness=0.1, TO=0.0156, DD=0.309。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **zqRbYj9O** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgW6QKE** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **wpEbj5N6** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Vk30GRdA** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **2rNmp6Nx** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMrpYl2** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.4963。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **9q7Wpoe9** (UNSUBMITTED, news): Sharpe=-0.09, Fitness=-0.06, TO=0.0239, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **MPL3GOWz** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **d5R1ROaX** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR168rgz** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.1, TO=0.0274, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR168Yxo** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **mLV68GQ6** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j2r8ZxOO** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMr7GPG** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPErLZrj** (UNSUBMITTED, news): Sharpe=0.41, Fitness=0.32, TO=0.012, DD=0.2166。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 17:35 UTC

- **le3MOenn** (UNSUBMITTED, fundamental): Sharpe=1.98, Fitness=1.3, TO=0.164, DD=0.0418。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **omgopP95** (UNSUBMITTED, fundamental): Sharpe=1.12, Fitness=0.62, TO=0.0535, DD=0.0717。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)`
- **np8AJ203** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0xJOdrR** (UNSUBMITTED, fundamental): Sharpe=1.23, Fitness=0.58, TO=0.0614, DD=0.0396。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_income / equity, 126), subindustry)`
- **E5eV15x1** (UNSUBMITTED, news): Sharpe=-0.2, Fitness=-0.12, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **9q7EZ2oe** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **JjvPMPVO** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.0252, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgo8YoJ** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **YPgxLmJv** (UNSUBMITTED, news): Sharpe=0.17, Fitness=0.08, TO=0.0138, DD=0.3235。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **kqZJqgv6** (UNSUBMITTED, news): Sharpe=0.42, Fitness=0.33, TO=0.012, DD=0.2166。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **bld8lqql** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **JjvPVddW** (UNSUBMITTED, news): Sharpe=-0.12, Fitness=-0.05, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **QP9Y1mnQ** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.0252, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRvOK0k3** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMr1eYr** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdZQ8l9** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRv2QrMQ** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RR16OKVb** (UNSUBMITTED, news): Sharpe=-0.2, Fitness=-0.12, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **WjVeZY5x** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **pwK5bkvb** (UNSUBMITTED, news): Sharpe=0.33, Fitness=0.23, TO=0.0156, DD=0.2192。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **QP9KRlZK** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.02, DD=0.4877。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMrZOg8** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **zqRbnbnK** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **88ePZ9do** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **A17v5j9Q** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j2r8OpOZ** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.4971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRv2PNRA** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.1, TO=0.0275, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRv26nb3** (UNSUBMITTED, news): Sharpe=-0.14, Fitness=-0.07, TO=0.0192, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 19:08 UTC

- **vRvO9oXG** (UNSUBMITTED, news): Sharpe=0.15, Fitness=0.07, TO=0.0144, DD=0.3331。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **qM6Ekzwv** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **A17QJ6Rl** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0156, DD=0.3131。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j2reNaRj** (UNSUBMITTED, news): Sharpe=-0.14, Fitness=-0.07, TO=0.0192, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1Yzj6ZrK** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0156, DD=0.3131。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **6XeAx9pp** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78noOxLZ** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1Yzjv1aK** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Xg8Rqqrm** (UNSUBMITTED, news): Sharpe=0.14, Fitness=0.06, TO=0.0156, DD=0.3366。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **xAd1M6zg** (UNSUBMITTED, news): Sharpe=0.37, Fitness=0.27, TO=0.0156, DD=0.21。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **6XeAxm67** (UNSUBMITTED, news): Sharpe=0.33, Fitness=0.23, TO=0.0156, DD=0.2192。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **gJ9Wzde0** (UNSUBMITTED, news): Sharpe=-0.11, Fitness=-0.07, TO=0.0262, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **O0xJv81g** (UNSUBMITTED, news): Sharpe=0.41, Fitness=0.32, TO=0.0132, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRvOVNgv** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.027, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **zqRrzRv1** (UNSUBMITTED, news): Sharpe=-0.23, Fitness=-0.14, TO=0.0182, DD=0.527。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **P0OM9LKK** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **E5eVJn8P** (UNSUBMITTED, news): Sharpe=-0.11, Fitness=-0.07, TO=0.0263, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 21:49 UTC

- **0mMjMgRp** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **YPgxgQYA** (UNSUBMITTED, news): Sharpe=-0.18, Fitness=-0.1, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRvO52xw** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Xg8R2vV1** (UNSUBMITTED, news): Sharpe=0.41, Fitness=0.32, TO=0.0132, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **A17QgGQY** (UNSUBMITTED, news): Sharpe=-0.18, Fitness=-0.1, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **mLVYxrax** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **9q7EAbro** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-26 23:35 UTC

- **zqRrrmQG** (UNSUBMITTED, news): Sharpe=0.42, Fitness=0.33, TO=0.0132, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgooYJb** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78noo9dL** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **E5eVRPd0** (UNSUBMITTED, news): Sharpe=-0.18, Fitness=-0.1, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **P0OMgPMx** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.027, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **2rNjmdgY** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **YPgxMLKo** (UNSUBMITTED, news): Sharpe=-0.12, Fitness=-0.05, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Vk3daQjA** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **58kjzJQJ** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **1YzjXQnz** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **E5eVvM9r** (UNSUBMITTED, news): Sharpe=0.16, Fitness=0.08, TO=0.0139, DD=0.3248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-27 01:18 UTC

- **KPEmzWMN** (UNSUBMITTED, news): Sharpe=-0.15, Fitness=-0.08, TO=0.0191, DD=0.4781。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78nom3OO** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.1, TO=0.0275, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLd5zdem** (UNSUBMITTED, news): Sharpe=-0.1, Fitness=-0.06, TO=0.0269, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **d5RKz0kx** (UNSUBMITTED, news): Sharpe=-0.22, Fitness=-0.14, TO=0.0182, DD=0.5267。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMjgWmv** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **WjVLoYWj** (UNSUBMITTED, news): Sharpe=-0.1, Fitness=-0.06, TO=0.0242, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **gJ9WgojM** (UNSUBMITTED, news): Sharpe=-0.18, Fitness=-0.1, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **pwKvMg66** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **ZYKmgVA0** (UNSUBMITTED, news): Sharpe=-0.09, Fitness=-0.06, TO=0.0246, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **rKPd0aX9** (UNSUBMITTED, news): Sharpe=0.45, Fitness=0.37, TO=0.0132, DD=0.1944。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **2rNjGKKY** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **MPL0g5nn** (UNSUBMITTED, news): Sharpe=-0.1, Fitness=-0.07, TO=0.0252, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **xAd1lwYN** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Vk3dMVLV** (UNSUBMITTED, news): Sharpe=0.33, Fitness=0.23, TO=0.0156, DD=0.2192。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`

---


### 2026-07-27 05:47 UTC

- **le3Ae72N** (UNSUBMITTED, fundamental): Sharpe=1.28, Fitness=1.17, TO=0.021, DD=0.1177。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **d5RW2nMw** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=0.66, TO=0.3936, DD=0.0983。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **QP9v112K** (UNSUBMITTED, fundamental): Sharpe=1.27, Fitness=1.13, TO=0.0241, DD=0.1045。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **le3MoYR7** (UNSUBMITTED, analyst): Sharpe=1.32, Fitness=0.69, TO=0.3886, DD=0.1986。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **A17QoewQ** (UNSUBMITTED, analyst): Sharpe=1.58, Fitness=0.88, TO=0.3348, DD=0.0955。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **d5RKNWa2** (UNSUBMITTED, analyst): Sharpe=1.01, Fitness=0.35, TO=0.5065, DD=0.1187。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **qM6EQn2E** (UNSUBMITTED, analyst): Sharpe=1.28, Fitness=0.55, TO=0.4283, DD=0.0976。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **QP9YwlmK** (UNSUBMITTED, analyst): Sharpe=1.33, Fitness=0.64, TO=0.4234, DD=0.11。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **vRvOWnEd** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=0.66, TO=0.3936, DD=0.0983。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **kqZJzrX6** (UNSUBMITTED, analyst): Sharpe=1.16, Fitness=0.46, TO=0.4628, DD=0.0989。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **QP9YwMMW** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=0.66, TO=0.3936, DD=0.0983。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **O0xJl1op** (UNSUBMITTED, analyst): Sharpe=1.9, Fitness=1.55, TO=0.2117, DD=0.1087。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **akEVp8Rv** (UNSUBMITTED, analyst): Sharpe=1.91, Fitness=1.68, TO=0.1915, DD=0.1169。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **Vk3dWZE5** (UNSUBMITTED, analyst): Sharpe=1.32, Fitness=0.69, TO=0.3886, DD=0.1986。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **pwKvLoKx** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=1.42, TO=0.0511, DD=0.3226。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **pwKv2kLq** (UNSUBMITTED, technical): Sharpe=1.12, Fitness=1.48, TO=0.0289, DD=0.3448。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **2rNjgjOZ** (UNSUBMITTED, technical): Sharpe=1.05, Fitness=1.12, TO=0.0549, DD=0.2973。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **qM6E2AOj** (UNSUBMITTED, fundamental): Sharpe=1.44, Fitness=0.5, TO=0.99, DD=0.0784。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **LLd5wYG9** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=0.96, TO=0.2237, DD=0.043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **GregNLNZ** (UNSUBMITTED, analyst): Sharpe=1.34, Fitness=0.86, TO=0.0661, DD=0.0559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **zqRrEol8** (UNSUBMITTED, analyst): Sharpe=1.49, Fitness=1.02, TO=0.0918, DD=0.0501。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`

---


### 2026-07-27 07:49 UTC

- **3qeoE57e** (UNSUBMITTED, news): Sharpe=-0.2, Fitness=-0.12, TO=0.0199, DD=0.4894。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7x5nLzz** (UNSUBMITTED, fundamental): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **LLdMnPEL** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7x5dWdO** (UNSUBMITTED, fundamental): Sharpe=1.29, Fitness=1.18, TO=0.0219, DD=0.1145。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **akEKAAPw** (UNSUBMITTED, fundamental): Sharpe=1.28, Fitness=1.17, TO=0.0214, DD=0.1158。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **ZYKQ2qm1** (UNSUBMITTED, fundamental): Sharpe=1.3, Fitness=1.19, TO=0.0228, DD=0.1123。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **P0OoXKeJ** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=0.66, TO=0.3936, DD=0.0983。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **vRv1Jlrd** (UNSUBMITTED, analyst): Sharpe=1.81, Fitness=1.43, TO=0.2393, DD=0.1436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **wpEQJl1l** (UNSUBMITTED, analyst): Sharpe=1.28, Fitness=0.55, TO=0.4283, DD=0.0976。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **d5RWlEKg** (UNSUBMITTED, analyst): Sharpe=1.42, Fitness=0.75, TO=0.3883, DD=0.1112。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **akEKWv6x** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.34, TO=0.242, DD=0.1044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **gJ9eoENK** (UNSUBMITTED, analyst): Sharpe=1.46, Fitness=0.77, TO=0.3892, DD=0.1139。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **le3AzAjA** (UNSUBMITTED, technical): Sharpe=1.26, Fitness=1.69, TO=0.0404, DD=0.4399。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **88eR6KVl** (UNSUBMITTED, technical): Sharpe=1.12, Fitness=1.21, TO=0.0451, DD=0.2865。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **58kE6nGX** (UNSUBMITTED, technical): Sharpe=1.09, Fitness=1.28, TO=0.0578, DD=0.3209。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **mLVoJQx2** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **GreW09AO** (UNSUBMITTED, fundamental): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **MPLYl8AL** (UNSUBMITTED, fundamental): Sharpe=2.14, Fitness=1.21, TO=0.2803, DD=0.0435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **np8vwW7a** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.92, TO=0.0498, DD=0.695。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`

---


### 2026-07-27 09:19 UTC

- **wpEQ3XeY** (UNSUBMITTED, analyst): Sharpe=1.83, Fitness=1.34, TO=0.242, DD=0.1044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **e7x51506** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=0.66, TO=0.3936, DD=0.0983。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **LLdM8Rev** (UNSUBMITTED, analyst): Sharpe=1.35, Fitness=0.65, TO=0.3912, DD=0.1087。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **9q7xGoeo** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=1.3, TO=0.0486, DD=0.2952。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **3qeoGWJ6** (UNSUBMITTED, analyst): Sharpe=1.68, Fitness=1.04, TO=0.2932, DD=0.0991。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **vRv1AZVa** (UNSUBMITTED, analyst): Sharpe=1.01, Fitness=0.35, TO=0.5065, DD=0.1187。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(close, volume, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_adjusted_netincome_ft, 120), std=...`
- **kqZNo72L** (UNSUBMITTED, fundamental): Sharpe=1.81, Fitness=1.24, TO=0.1133, DD=0.0448。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **2rNAOrGZ** (UNSUBMITTED, analyst): Sharpe=1.29, Fitness=0.82, TO=0.0578, DD=0.0581。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **P0Oo7lqW** (UNSUBMITTED, analyst): Sharpe=1.8, Fitness=1.08, TO=0.2061, DD=0.0451。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`

---


### 2026-07-27 10:03 UTC

- **88eRYr27** (UNSUBMITTED, fundamental): Sharpe=1.44, Fitness=0.5, TO=0.99, DD=0.0784。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **MPLYZXGn** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.62, TO=0.0181, DD=0.1191。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **MPLYz6Za** (UNSUBMITTED, analyst): Sharpe=1.59, Fitness=1.5, TO=0.0192, DD=0.1076。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **kqZNGNMO** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.47, TO=0.02, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **qM6LGjzV** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.47, TO=0.02, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **Vk3xzwMM** (UNSUBMITTED, analyst): Sharpe=1.56, Fitness=1.45, TO=0.0179, DD=0.1075。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **np8vqRN3** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.46, TO=0.02, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **78nLmWo1** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.62, TO=0.0169, DD=0.119。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **d5RW3Kj2** (UNSUBMITTED, analyst): Sharpe=1.43, Fitness=1.48, TO=0.0133, DD=0.1783。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **xAdr2j8b** (UNSUBMITTED, analyst): Sharpe=1.42, Fitness=1.47, TO=0.0128, DD=0.1798。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`

---


### 2026-07-27 10:21 UTC

- **qM6Lp3l2** (UNSUBMITTED, fundamental): Sharpe=1.43, Fitness=1.07, TO=0.1175, DD=0.0529。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **xAdrobZb** (UNSUBMITTED, fundamental): Sharpe=2.07, Fitness=0.85, TO=0.6276, DD=0.0401。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-27 13:21 UTC

- **GrempGjG** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **A17xWmze** (UNSUBMITTED, technical): Sharpe=1.13, Fitness=1.5, TO=0.0296, DD=0.3447。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **YPgarK7J** (UNSUBMITTED, analyst): Sharpe=1.54, Fitness=1.39, TO=0.0172, DD=0.1128。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **gJ9aAJJ0** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.44, TO=0.0205, DD=0.0901。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **qM6782pv** (UNSUBMITTED, analyst): Sharpe=1.5, Fitness=1.28, TO=0.0187, DD=0.0935。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **Jjv8qrXA** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.44, TO=0.0205, DD=0.0901。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **O0xWOxN1** (UNSUBMITTED, analyst): Sharpe=1.5, Fitness=1.28, TO=0.0187, DD=0.0935。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **gJ9a6x2O** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.44, TO=0.0205, DD=0.0901。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **ZYKaPJA0** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.74, TO=0.0128, DD=0.0781。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **omga8Nbk** (UNSUBMITTED, analyst): Sharpe=1.41, Fitness=1.17, TO=0.0172, DD=0.1213。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **O0xWQpqJ** (UNSUBMITTED, analyst): Sharpe=1.59, Fitness=1.47, TO=0.0196, DD=0.1071。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **58kJnwRM** (UNSUBMITTED, analyst): Sharpe=1.65, Fitness=1.5, TO=0.0216, DD=0.0872。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **N1RP1GJw** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.45, TO=0.0205, DD=0.0901。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **A17x15JR** (UNSUBMITTED, analyst): Sharpe=1.65, Fitness=1.5, TO=0.0216, DD=0.0872。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **MPL6Pzko** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.5, TO=0.0209, DD=0.0837。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **qM67MgLv** (UNSUBMITTED, analyst): Sharpe=1.31, Fitness=1.3, TO=0.011, DD=0.1838。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **P0O5JkJE** (UNSUBMITTED, analyst): Sharpe=1.62, Fitness=1.47, TO=0.0203, DD=0.0839。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **j2ra5AJQ** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.5, TO=0.0209, DD=0.0837。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **akEar3LR** (UNSUBMITTED, analyst): Sharpe=1.6, Fitness=1.53, TO=0.0198, DD=0.1078。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **xAdrJLbg** (UNSUBMITTED, fundamental): Sharpe=0.59, Fitness=0.32, TO=0.0146, DD=0.2065。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **WjVOvxzd** (UNSUBMITTED, fundamental): Sharpe=0.55, Fitness=0.29, TO=0.0164, DD=0.2157。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **88eRwRzW** (UNSUBMITTED, fundamental): Sharpe=1.17, Fitness=1.09, TO=0.0145, DD=0.1863。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **WjVOZ8JN** (UNSUBMITTED, fundamental): Sharpe=1.18, Fitness=1.1, TO=0.015, DD=0.1801。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **RR1ExoOn** (UNSUBMITTED, fundamental): Sharpe=1.29, Fitness=1.18, TO=0.0216, DD=0.1157。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **O0xAdKLY** (UNSUBMITTED, fundamental): Sharpe=1.66, Fitness=0.56, TO=0.9738, DD=0.0563。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **zqR3nm2G** (UNSUBMITTED, fundamental): Sharpe=1.84, Fitness=0.6, TO=0.9575, DD=0.0416。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-27 15:33 UTC

- **gJ9a9m5M** (UNSUBMITTED, technical): Sharpe=1.22, Fitness=1.67, TO=0.0307, DD=0.3654。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **YPga080v** (UNSUBMITTED, technical): Sharpe=1.15, Fitness=1.37, TO=0.0467, DD=0.32。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **j2ra0lL9** (UNSUBMITTED, analyst): Sharpe=1.52, Fitness=1.31, TO=0.0192, DD=0.0915。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **88eNQdZm** (UNSUBMITTED, analyst): Sharpe=1.59, Fitness=1.47, TO=0.0196, DD=0.1071。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **omgal1rJ** (UNSUBMITTED, analyst): Sharpe=1.39, Fitness=1.15, TO=0.0175, DD=0.1282。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **MPL6pevz** (UNSUBMITTED, analyst): Sharpe=1.73, Fitness=1.76, TO=0.0134, DD=0.0758。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **pwKa6vLx** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.46, TO=0.0209, DD=0.0897。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **qM67AjQ2** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.49, TO=0.0206, DD=0.0838。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **6XeMwpLG** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.5, TO=0.0209, DD=0.0837。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **QP90QzLX** (UNSUBMITTED, analyst): Sharpe=1.5, Fitness=1.37, TO=0.0164, DD=0.1073。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **ZYKaoeGQ** (UNSUBMITTED, analyst): Sharpe=1.42, Fitness=1.47, TO=0.0128, DD=0.1798。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **LLdKk3gM** (UNSUBMITTED, analyst): Sharpe=1.51, Fitness=1.32, TO=0.0176, DD=0.0928。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **kqZa13qd** (UNSUBMITTED, fundamental): Sharpe=1.17, Fitness=1.04, TO=0.0498, DD=0.175。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(volume, 10) > ts_mean(volume, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_adesinda_curcd, ...`
- **akEaWj8W** (UNSUBMITTED, fundamental): Sharpe=1.26, Fitness=1.18, TO=0.0185, DD=0.1444。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **QP90laQ5** (UNSUBMITTED, fundamental): Sharpe=1.26, Fitness=1.18, TO=0.0187, DD=0.1423。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`
- **omgavrP2** (UNSUBMITTED, fundamental): Sharpe=1.96, Fitness=1.02, TO=0.393, DD=0.0582。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **akEaM8Z1** (UNSUBMITTED, fundamental): Sharpe=1.44, Fitness=0.5, TO=0.99, DD=0.0784。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-28 16:19 UTC

- **rKP7d8v8** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **wpEobbLv** (UNSUBMITTED, analyst): Sharpe=1.6, Fitness=1.57, TO=0.0174, DD=0.1156。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **3qe0XgVz** (UNSUBMITTED, fundamental): Sharpe=0.52, Fitness=0.26, TO=0.0249, DD=0.2424。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **Vk3N6q0M** (UNSUBMITTED, fundamental): Sharpe=0.69, Fitness=0.63, TO=0.3304, DD=0.6457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-28 18:23 UTC

- **GreKV2bJ** (UNSUBMITTED, news): Sharpe=-0.09, Fitness=-0.05, TO=0.0248, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPE5RpVj** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(pv13_revere_level, 10) > ts_mean(pv13_revere_level, 60), group_zscore(ts_sum(winsorize(ts_backfill...`
- **gJ9gz9eQ** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(pv13_revere_level, 10) > ts_mean(pv13_revere_level, 60), group_zscore(ts_sum(winsorize(ts_backfill...`
- **GreKvYx5** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(pv13_revere_level, 10) > ts_mean(pv13_revere_level, 60), group_zscore(ts_sum(winsorize(ts_backfill...`
- **le35XrJe** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.34, TO=0.0205, DD=0.2209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **wpE2gJrx** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.19, TO=0.0164, DD=0.1665。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **LLdmAgqm** (UNSUBMITTED, fundamental): Sharpe=0.12, Fitness=0.03, TO=0.0182, DD=0.2752。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_cust, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_npq, 120)),densify(pv13_hierarchy_...`
- **GreKpEro** (UNSUBMITTED, fundamental): Sharpe=-0.02, Fitness=-0.0, TO=0.02, DD=0.376。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_cust, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_npq, 120)),densify(pv13_hierarchy_...`
- **d5R3Akzj** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.03, TO=0.0125, DD=0.2683。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_cust, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_npq, 120)),densify(pv13_hierarchy_...`

---


### 2026-07-28 20:51 UTC

- **kqZW0q6l** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **0mMNz2MG** (UNSUBMITTED, fundamental): Sharpe=1.87, Fitness=1.34, TO=0.1475, DD=0.0348。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **d5R3dOv2** (UNSUBMITTED, fundamental): Sharpe=1.87, Fitness=1.34, TO=0.1475, DD=0.0348。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **akEQodpv** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=1.41, TO=0.1408, DD=0.6791。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **wpE2LxMY** (UNSUBMITTED, fundamental): Sharpe=1.59, Fitness=1.12, TO=0.1582, DD=0.0542。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **3qekEmMO** (UNSUBMITTED, fundamental): Sharpe=1.91, Fitness=1.31, TO=0.165, DD=0.0417。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **xAd2e2vn** (UNSUBMITTED, fundamental): Sharpe=1.87, Fitness=1.34, TO=0.1475, DD=0.0348。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **58kALREX** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.13, TO=0.3026, DD=0.0439。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **e7xVnR16** (UNSUBMITTED, fundamental): Sharpe=2.14, Fitness=1.02, TO=0.3991, DD=0.0446。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **KPE5n0kl** (UNSUBMITTED, fundamental): Sharpe=0.94, Fitness=1.36, TO=0.0485, DD=0.6634。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **88eEaXaz** (UNSUBMITTED, fundamental): Sharpe=1.62, Fitness=1.16, TO=0.1412, DD=0.0542。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **JjvWgg52** (UNSUBMITTED, fundamental): Sharpe=1.56, Fitness=1.15, TO=0.1394, DD=0.0658。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **KPE5X63E** (UNSUBMITTED, fundamental): Sharpe=-0.24, Fitness=-0.14, TO=0.0251, DD=0.9216。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(ticker, 10) > ts_mean(ticker, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_newa2v1300_txach...`
- **N1RJg9dp** (UNSUBMITTED, fundamental): Sharpe=1.94, Fitness=1.35, TO=0.1547, DD=0.0289。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **88eEKwrz** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.07, TO=0.0277, DD=0.4385。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(ticker, 10) > ts_mean(ticker, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_newa2v1300_txach...`
- **9q7dAXO1** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0215, DD=0.3009。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_mean(ticker, 10) > ts_mean(ticker, 60), group_zscore(ts_sum(winsorize(ts_backfill(fnd6_newa2v1300_txach...`

---


### 2026-07-28 22:38 UTC

- **GreKOElZ** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdmNMmn** (UNSUBMITTED, analyst): Sharpe=-0.07, Fitness=-0.01, TO=0.0093, DD=0.351。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,returns,5),3),0.85),`
- **omgJLE8J** (UNSUBMITTED, analyst): Sharpe=1.64, Fitness=1.62, TO=0.0139, DD=0.1106。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **N1RJar9e** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.0105, DD=0.3497。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,returns,5),3),0.85),`
- **Xg8vbX0a** (UNSUBMITTED, analyst): Sharpe=1.62, Fitness=1.59, TO=0.0172, DD=0.1193。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **LLdmNWlL** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.49, TO=0.0195, DD=0.111。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **O0xMNOvq** (UNSUBMITTED, analyst): Sharpe=0.02, Fitness=0.0, TO=0.0093, DD=0.2886。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,returns,5),3),0.85),`
- **np8edxrE** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.61, TO=0.014, DD=0.103。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`

---


### 2026-07-29 01:01 UTC

- **xAd2V3Rb** (UNSUBMITTED, fundamental): Sharpe=0.97, Fitness=1.43, TO=0.0821, DD=0.663。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **9q7d8Vmx** (UNSUBMITTED, fundamental): Sharpe=0.96, Fitness=1.4, TO=0.07, DD=0.6604。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **wpE23176** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=1.41, TO=0.1408, DD=0.6791。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **omgJR8vn** (UNSUBMITTED, fundamental): Sharpe=2.06, Fitness=1.26, TO=0.2297, DD=0.0468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **Vk3mZkN8** (UNSUBMITTED, fundamental): Sharpe=1.87, Fitness=1.02, TO=0.2942, DD=0.0508。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **2rNXGeGN** (UNSUBMITTED, fundamental): Sharpe=1.73, Fitness=0.96, TO=0.2911, DD=0.0551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **78nvG6r5** (UNSUBMITTED, fundamental): Sharpe=0.29, Fitness=0.1, TO=0.0115, DD=0.1344。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ustomergraphrank_auth_rank, 60) > 2, group_zscore(-inverse(ts_backfill(domestic_assets_tota...`
- **LLdm81pL** (UNSUBMITTED, fundamental): Sharpe=2.11, Fitness=1.09, TO=0.316, DD=0.0388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **le35glr8** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.13, TO=0.3026, DD=0.0439。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **O0xM6naR** (UNSUBMITTED, fundamental): Sharpe=0.06, Fitness=0.01, TO=0.0085, DD=0.1892。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ustomergraphrank_auth_rank, 60) > 2, group_zscore(-inverse(ts_backfill(domestic_assets_tota...`
- **e7xV17Y6** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.16, TO=0.056, DD=0.167。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / volume - 1)) + 0.5 * rank(ts_rank(current_minimum_operating_lease_payment...`
- **9q7dl8zx** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.11, TO=0.0507, DD=0.2108。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / volume - 1)) + 0.5 * rank(ts_rank(current_minimum_operating_lease_payment...`
- **9q7dlEOq** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.1, TO=0.04, DD=0.1833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / volume - 1)) + 0.5 * rank(ts_rank(current_minimum_operating_lease_payment...`
- **wpE2oZNx** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.05, TO=0.0475, DD=0.2752。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / volume - 1)) + 0.5 * rank(ts_rank(current_minimum_operating_lease_payment...`

---


### 2026-07-29 02:53 UTC

- **QP9NR35p** (UNSUBMITTED, analyst): Sharpe=0.39, Fitness=0.17, TO=0.0122, DD=0.2。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,rel_ret_all,5),3),0.85),`
- **Xg8vZ2rX** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.16, TO=0.0116, DD=0.2152。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,rel_ret_all,5),3),0.85),`
- **omgJjvdn** (UNSUBMITTED, analyst): Sharpe=0.26, Fitness=0.1, TO=0.0101, DD=0.2353。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,rel_ret_all,5),3),0.85),`
- **58kAK8w1** (UNSUBMITTED, analyst): Sharpe=1.52, Fitness=1.31, TO=0.0186, DD=0.0948。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **mLV0WNlX** (UNSUBMITTED, analyst): Sharpe=1.64, Fitness=1.48, TO=0.0212, DD=0.0889。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **zqR2EbQV** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.92, TO=0.0148, DD=0.6591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`

---


### 2026-07-29 05:14 UTC

- **KPEz0x6l** (UNSUBMITTED, fundamental): Sharpe=0.35, Fitness=0.26, TO=0.012, DD=0.4195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_stkcpaq, 120)),densify(pv13_hi...`
- **0mMglWx1** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **A17zWRpY** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.23, TO=0.0103, DD=0.3499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_stkcpaq, 120)),densify(pv13_hi...`
- **QP9zMWqr** (UNSUBMITTED, fundamental): Sharpe=0.06, Fitness=0.02, TO=0.014, DD=0.4276。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_stkcpaq, 120)),densify(pv13_hi...`
- **le3Gdrb7** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=1.32, TO=0.1605, DD=0.6802。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **gJ9G6pbM** (UNSUBMITTED, fundamental): Sharpe=0.98, Fitness=1.45, TO=0.1011, DD=0.6705。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **QP9zMZmw** (UNSUBMITTED, fundamental): Sharpe=0.97, Fitness=1.43, TO=0.0821, DD=0.663。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **88eJ5nvz** (UNSUBMITTED, fundamental): Sharpe=0.97, Fitness=1.43, TO=0.0821, DD=0.663。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **LLdzVg0e** (UNSUBMITTED, fundamental): Sharpe=2.14, Fitness=1.02, TO=0.3991, DD=0.0446。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **QP9zZr9Q** (UNSUBMITTED, fundamental): Sharpe=0.97, Fitness=1.43, TO=0.0821, DD=0.663。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **JjvzjQ1x** (UNSUBMITTED, fundamental): Sharpe=1.01, Fitness=1.08, TO=0.2496, DD=0.6833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **2rN6rl2Z** (UNSUBMITTED, fundamental): Sharpe=1.97, Fitness=1.31, TO=0.172, DD=0.0336。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **GrezreJP** (UNSUBMITTED, fundamental): Sharpe=1.8, Fitness=1.18, TO=0.1924, DD=0.0487。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **QP9zPJ6p** (UNSUBMITTED, fundamental): Sharpe=1.7, Fitness=1.13, TO=0.191, DD=0.0558。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **d5Rz5koX** (UNSUBMITTED, fundamental): Sharpe=2.07, Fitness=1.3, TO=0.2046, DD=0.0413。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **np8qp1Pz** (UNSUBMITTED, fundamental): Sharpe=2.03, Fitness=1.32, TO=0.1972, DD=0.045。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **mLV7Pb7E** (UNSUBMITTED, fundamental): Sharpe=1.17, Fitness=1.09, TO=0.0137, DD=0.187。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`

---


### 2026-07-29 07:29 UTC

- **bldzvxwM** (UNSUBMITTED, news): Sharpe=0.13, Fitness=0.06, TO=0.0156, DD=0.3437。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **Vk3zYR68** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.92, TO=0.0112, DD=0.6563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **P0OzXXZw** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.3, TO=0.0238, DD=0.2146。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`

---


### 2026-07-30 07:29 UTC

- **omgGWPpk** (UNSUBMITTED, fundamental): Sharpe=1.84, Fitness=1.13, TO=0.2244, DD=0.0479。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **omgGWevv** (UNSUBMITTED, fundamental): Sharpe=1.72, Fitness=1.07, TO=0.2226, DD=0.0579。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **WjVzeqEQ** (UNSUBMITTED, fundamental): Sharpe=2.06, Fitness=1.26, TO=0.2297, DD=0.0468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **xAdGbqNm** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.23, TO=0.2383, DD=0.0443。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **e7xGbLwz** (UNSUBMITTED, fundamental): Sharpe=1.25, Fitness=1.1, TO=0.0224, DD=0.1082。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`

---


### 2026-07-30 17:58 UTC

- **3qe2gNae** (UNSUBMITTED, analyst): Sharpe=1.66, Fitness=1.5, TO=0.021, DD=0.09。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **gJ90vMGm** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **ZYK1ZllY** (UNSUBMITTED, fundamental): Sharpe=0.95, Fitness=1.38, TO=0.0614, DD=0.6606。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **d5RPw1R2** (UNSUBMITTED, fundamental): Sharpe=2.07, Fitness=1.2, TO=0.2571, DD=0.0468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **E5e2AJYr** (UNSUBMITTED, fundamental): Sharpe=0.98, Fitness=1.45, TO=0.1011, DD=0.6705。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **78n295N5** (UNSUBMITTED, fundamental): Sharpe=1.01, Fitness=1.08, TO=0.2496, DD=0.6833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`

---


### 2026-07-30 19:52 UTC

- **mLVNZ0XX** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e7xPnrMO** (UNSUBMITTED, analyst): Sharpe=1.49, Fitness=1.27, TO=0.018, DD=0.0966。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **88eZO567** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.92, TO=0.0148, DD=0.6591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **akE8Ad9x** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.94, TO=0.0095, DD=0.6531。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`

---


### 2026-07-30 21:59 UTC

- **N1RGVpgw** (UNSUBMITTED, option): Sharpe=0.33, Fitness=0.11, TO=0.0119, DD=0.0982。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(shares_issued_stock...`
- **le3YKRO2** (UNSUBMITTED, option): Sharpe=0.16, Fitness=0.04, TO=0.0106, DD=0.1046。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(shares_issued_stock...`
- **O0xj8mYb** (UNSUBMITTED, option): Sharpe=0.27, Fitness=0.08, TO=0.0124, DD=0.1233。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(shares_issued_stock...`
- **A175vdJQ** (UNSUBMITTED, option): Sharpe=0.17, Fitness=0.04, TO=0.009, DD=0.1037。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(shares_issued_stock...`
- **d5R6bGkY** (UNSUBMITTED, analyst): Sharpe=1.53, Fitness=1.46, TO=0.0151, DD=0.1259。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **MPLnaWe8** (UNSUBMITTED, fundamental): Sharpe=2.11, Fitness=1.09, TO=0.316, DD=0.0388。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **2rNxOWQJ** (UNSUBMITTED, fundamental): Sharpe=1.01, Fitness=1.23, TO=0.1915, DD=0.6819。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **rKPw5Eb1** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **wpEAjQrv** (UNSUBMITTED, fundamental): Sharpe=2.2, Fitness=0.87, TO=0.5513, DD=0.035。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **le3Yj875** (UNSUBMITTED, fundamental): Sharpe=1.85, Fitness=1.08, TO=0.2509, DD=0.0492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **LLdw7Gem** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.16, TO=0.2673, DD=0.0434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **YPgOvRew** (UNSUBMITTED, fundamental): Sharpe=1.72, Fitness=1.02, TO=0.2487, DD=0.0588。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **0mMLpV51** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.16, TO=0.2673, DD=0.0434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`

---


### 2026-07-31 00:53 UTC

- **P0ObzQaL** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRvbZlJa** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **RR1o9prd** (UNSUBMITTED, fundamental): Sharpe=1.67, Fitness=1.15, TO=0.1597, DD=0.0477。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **vRvbZ0Mr** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.19, TO=0.0164, DD=0.1665。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **78nrGn7Z** (UNSUBMITTED, fundamental): Sharpe=0.29, Fitness=0.11, TO=0.0125, DD=0.0925。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(acquisition_liabilities_assumed, 120)...`
- **LLdw8lLM** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0102, DD=0.0947。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(acquisition_liabilities_assumed, 120)...`
- **A175LaAR** (UNSUBMITTED, fundamental): Sharpe=-0.16, Fitness=-0.04, TO=0.0079, DD=0.1392。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(acquisition_liabilities_assumed, 120)...`

---


### 2026-07-31 04:50 UTC

- **6XeQ57mp** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.14, TO=0.0214, DD=0.1365。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(cap, 60) > 2, group_zscore(-inverse(ts_backfill(federal_income_tax_rate_statutory, 120)),densify...`
- **QP9A86VQ** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.15, TO=0.0119, DD=0.1629。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_gra...`
- **E5eMdVNr** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.23, TO=0.0117, DD=0.162。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_gra...`
- **GreNRGeG** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.06, TO=0.0172, DD=0.1664。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(cap, 60) > 2, group_zscore(-inverse(ts_backfill(federal_income_tax_rate_statutory, 120)),densify...`
- **Xg8x08ka** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.01, TO=0.0133, DD=0.186。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(cap, 60) > 2, group_zscore(-inverse(ts_backfill(federal_income_tax_rate_statutory, 120)),densify...`
- **d5R6Gd9Y** (UNSUBMITTED, technical): Sharpe=0.41, Fitness=0.19, TO=0.0087, DD=0.1872。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_gra...`
- **np8lEOG3** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.05, TO=0.0195, DD=0.1525。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(cap, 60) > 2, group_zscore(-inverse(ts_backfill(federal_income_tax_rate_statutory, 120)),densify...`
- **88eZwr1l** (UNSUBMITTED, technical): Sharpe=0.52, Fitness=0.26, TO=0.0107, DD=0.1689。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ompetitorgraphrank_hub_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_gra...`
- **Xg8xZOkm** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=1.32, TO=0.1605, DD=0.6802。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **omgXjrr2** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`

---


### 2026-07-31 06:49 UTC

- **A178azqw** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sedol,returns,5),3),0.85),`
- **bld1PLnN** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sedol,returns,5),3),0.85),`
- **WjV2dV9N** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sedol,returns,5),3),0.85),`

---


### 2026-07-31 09:19 UTC

- **kqZ6az8L** (UNSUBMITTED, news): Sharpe=0.45, Fitness=0.37, TO=0.0132, DD=0.1944。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omg0EzGk** (UNSUBMITTED, fundamental): Sharpe=2.01, Fitness=1.31, TO=0.1851, DD=0.0367。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **MPLN0Yon** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=1.32, TO=0.1605, DD=0.6802。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **akE9xzd9** (UNSUBMITTED, fundamental): Sharpe=1.01, Fitness=1.08, TO=0.2496, DD=0.6833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **le3PKAA2** (UNSUBMITTED, fundamental): Sharpe=2.19, Fitness=1.0, TO=0.4221, DD=0.0362。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **O0xX8ZRg** (UNSUBMITTED, fundamental): Sharpe=1.85, Fitness=1.08, TO=0.2509, DD=0.0492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **omg0LxqE** (UNSUBMITTED, fundamental): Sharpe=1.72, Fitness=1.02, TO=0.2487, DD=0.0588。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **bld1bz0m** (UNSUBMITTED, fundamental): Sharpe=2.09, Fitness=1.16, TO=0.2673, DD=0.0434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **0mM2XjK1** (UNSUBMITTED, fundamental): Sharpe=2.07, Fitness=1.2, TO=0.2571, DD=0.0468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **Vk3ba9lA** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **JjvJxJPE** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=1.47, TO=0.1164, DD=0.6743。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **A1780KMR** (UNSUBMITTED, fundamental): Sharpe=2.15, Fitness=1.05, TO=0.3565, DD=0.0372。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`

---


### 2026-07-31 12:45 UTC

- **P0OLenmq** (UNSUBMITTED, analyst): Sharpe=1.41, Fitness=1.17, TO=0.0172, DD=0.1213。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **vRv70nM3** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.92, TO=0.0102, DD=0.6562。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **E5enAme0** (UNSUBMITTED, fundamental): Sharpe=0.57, Fitness=0.31, TO=0.0153, DD=0.2115。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **0mMZvA9K** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.21, TO=0.0127, DD=0.2208。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_lcoq, 120)),densify(pv...`
- **LLdoJWAe** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.08, TO=0.0137, DD=0.1747。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_lcoq, 120)),densify(pv...`
- **zqR71eN1** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.19, TO=0.014, DD=0.2052。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_lcoq, 120)),densify(pv...`
- **2rNVbwNb** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.2, TO=0.0109, DD=0.2118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_lcoq, 120)),densify(pv...`

---


### 2026-07-31 19:18 UTC

- **1Yz33LlQ** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLdooe3L** (UNSUBMITTED, news): Sharpe=-0.11, Fitness=-0.07, TO=0.024, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgjXjvn** (UNSUBMITTED, technical): Sharpe=-0.05, Fitness=-0.02, TO=0.0113, DD=0.8587。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(net_profit_or_loss, 120)),densify(pv13_hierar...`
- **88eWZJlz** (UNSUBMITTED, technical): Sharpe=0.04, Fitness=0.01, TO=0.0085, DD=1.0422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(net_profit_or_loss, 120)),densify(pv13_hierar...`
- **ZYKV9awd** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.21, TO=0.0088, DD=0.4832。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(net_profit_or_loss, 120)),densify(pv13_hierar...`
- **GrejNYVx** (UNSUBMITTED, technical): Sharpe=0.25, Fitness=0.17, TO=0.0091, DD=0.4997。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(ticker, 60) > 2, group_zscore(-inverse(ts_backfill(net_profit_or_loss, 120)),densify(pv13_hierar...`
- **QP9RogMW** (UNSUBMITTED, analyst): Sharpe=1.74, Fitness=1.76, TO=0.0127, DD=0.0879。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **wpE7WgXv** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_term, pv13_reveremap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(lease_minimum_p...`

---


### 2026-07-31 21:02 UTC

- **3qeKqwv0** (UNSUBMITTED, fundamental): Sharpe=0.53, Fitness=0.26, TO=0.0279, DD=0.2401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **WjVrvZVZ** (UNSUBMITTED, fundamental): Sharpe=2.03, Fitness=0.65, TO=0.9462, DD=0.0356。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`

---


### 2026-07-31 23:11 UTC

- **88e0A0zv** (UNSUBMITTED, news): Sharpe=-0.12, Fitness=-0.09, TO=0.0274, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **np8j01nw** (UNSUBMITTED, analyst): Sharpe=1.52, Fitness=1.3, TO=0.0179, DD=0.0982。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **kqZw5pgk** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,pv13_ustomergraphrank_auth_rank,5),3),0.85),`
- **le3nZ1mN** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,pv13_ustomergraphrank_auth_rank,5),3),0.85),`
- **Xg83E9z0** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,pv13_ustomergraphrank_auth_rank,5),3),0.85),`
- **6XeWvGzG** (UNSUBMITTED, fundamental): Sharpe=0.61, Fitness=0.85, TO=0.0036, DD=0.7123。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(close, volume, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_adesinda_curcd, 120), std=4))...`

---


### 2026-08-01 00:34 UTC

- **YPgVkvj6** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **MPLEX2vL** (UNSUBMITTED, analyst): Sharpe=1.63, Fitness=1.47, TO=0.0204, DD=0.0912。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`

---


### 2026-08-01 02:38 UTC

- **xAdLRV2m** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0328, DD=0.4217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(high / pv13_revere_comproduct_company - 1)) + 0.5 * rank(ts_rank(fn_avg_diluted_sharesout_adj_a / fnd6_n...`
- **le3nrrJx** (UNSUBMITTED, fundamental): Sharpe=-0.12, Fitness=-0.05, TO=0.0344, DD=0.6683。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(high / pv13_revere_comproduct_company - 1)) + 0.5 * rank(ts_rank(fn_avg_diluted_sharesout_adj_a / fnd6_n...`
- **d5RMdXLx** (UNSUBMITTED, fundamental): Sharpe=0.59, Fitness=0.3, TO=0.0059, DD=0.1488。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_index_value,5),3),0.85),`
- **58kmL5eN** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.08, TO=0.0071, DD=0.2019。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_index_value,5),3),0.85),`
- **d5RMnbNK** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.1, TO=0.006, DD=0.1997。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_index_value,5),3),0.85),`
- **6XeWRjOK** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.07, TO=0.0082, DD=0.1951。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_index_value,5),3),0.85),`

---


### 2026-08-01 04:09 UTC

- **mLVGmPW5** (UNSUBMITTED, fundamental): Sharpe=0.62, Fitness=0.32, TO=0.0218, DD=0.2249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`

---


### 2026-08-01 06:29 UTC

- **omgbXldE** (UNSUBMITTED, news): Sharpe=0.41, Fitness=0.32, TO=0.0132, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j2rpGQK5** (UNSUBMITTED, fundamental): Sharpe=2.06, Fitness=1.26, TO=0.2297, DD=0.0468。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`
- **N1RdJEpg** (UNSUBMITTED, fundamental): Sharpe=1.84, Fitness=1.13, TO=0.2244, DD=0.0479。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_rank(ts_zscore(add(divide(fnd6_chee, annual_total_liabilities_value), divide(annual_ebitda_value, mdl177_dvm_ebitd...`

---


### 2026-08-01 06:37 UTC

- **A17Aj6RE** (UNSUBMITTED, fundamental): Sharpe=0.08, Fitness=0.02, TO=0.0069, DD=0.5315。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **1YzMkkbK** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.0, TO=0.0055, DD=0.617。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`

---


### 2026-08-01 09:18 UTC

- **58kXqJqo** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_ret_comp,5),3),0.85),`
- **2rNYnNkJ** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_ret_comp,5),3),0.85),`
- **N1RZ5OAp** (UNSUBMITTED, technical): Sharpe=-1.25, Fitness=-2.1, TO=0.0045, DD=0.3904。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_ret_comp,5),3),0.85),`
- **kqZALekk** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.08, TO=0.0089, DD=0.1927。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(returns, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(stock_issuance_co...`
- **O0x35vMg** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=1.08, TO=0.01, DD=0.7339。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(returns, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(stock_issuance_co...`
- **58kXqbbz** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.01, TO=0.0266, DD=0.8256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_custretsig_retsig,5),3),0.85),`
- **O0x3mLog** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.03, TO=0.007, DD=0.2204。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(returns, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(stock_issuance_co...`
- **Xg80lJWX** (UNSUBMITTED, analyst): Sharpe=0.1, Fitness=0.03, TO=0.0169, DD=0.3537。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_num_part,5),3),0.85),`
- **88ew63LV** (UNSUBMITTED, technical): Sharpe=0.39, Fitness=0.15, TO=0.0107, DD=0.1198。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(returns, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(stock_issuance_co...`
- **A17AaOWE** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.06, TO=0.0257, DD=0.5421。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_custretsig_retsig,5),3),0.85),`
- **kqZAmXe8** (UNSUBMITTED, analyst): Sharpe=0.2, Fitness=0.07, TO=0.019, DD=0.2827。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_num_part,5),3),0.85),`
- **O0x3m0wd** (UNSUBMITTED, analyst): Sharpe=0.45, Fitness=0.4, TO=0.0219, DD=0.4707。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_custretsig_retsig,5),3),0.85),`
- **xAdZQaob** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.3, TO=0.0257, DD=0.4153。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_custretsig_retsig,5),3),0.85),`
- **e7xjg0vp** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.11, TO=0.0085, DD=0.4836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,rel_ret_comp,5),3),0.85),`
- **A17AJ5RE** (UNSUBMITTED, analyst): Sharpe=0.26, Fitness=0.19, TO=0.0099, DD=1.0061。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,pv13_com_page_rank,5),3),0.85),`
- **3qeNY5pQ** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.07, TO=0.0078, DD=0.6156。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,rel_ret_comp,5),3),0.85),`
- **d5RG80Ow** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.16, TO=0.0089, DD=0.4565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,rel_ret_comp,5),3),0.85),`
- **wpErwqA1** (UNSUBMITTED, analyst): Sharpe=0.14, Fitness=0.05, TO=0.0066, DD=0.5971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,rel_ret_comp,5),3),0.85),`
- **akEp2koW** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.15, TO=0.0122, DD=0.5243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,pv13_com_page_rank,5),3),0.85),`
- **YPgeX9bo** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.92, TO=0.0112, DD=0.6563。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **1YzM6wRJ** (UNSUBMITTED, analyst): Sharpe=-0.41, Fitness=-0.32, TO=0.011, DD=1.184。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,pv13_com_page_rank,5),3),0.85),`
- **vRvQVdlA** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,rel_num_cust,5),3),0.85),`
- **A17Ad6WY** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,rel_num_cust,5),3),0.85),`
- **58kXVxQz** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,rel_num_cust,5),3),0.85),`
- **e7xjRGqE** (UNSUBMITTED, fundamental): Sharpe=0.01, Fitness=0.0, TO=0.008, DD=0.0671。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_com_page_rank, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a...`
- **QP98Xv9p** (UNSUBMITTED, fundamental): Sharpe=0.08, Fitness=0.01, TO=0.0068, DD=0.0648。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_com_page_rank, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a...`
- **QP98XK1G** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.0, TO=0.0087, DD=0.0711。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_com_page_rank, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a...`
- **e7xjROXJ** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.05, TO=0.0056, DD=0.0707。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_com_page_rank, pv13_revere_index_cap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a...`
- **np8EVJZd** (UNSUBMITTED, fundamental): Sharpe=0.78, Fitness=0.42, TO=0.0116, DD=0.0962。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_index_value, sharesout, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(effective_tax...`
- **bldw5omK** (UNSUBMITTED, fundamental): Sharpe=0.48, Fitness=0.25, TO=0.0076, DD=0.2815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_index_value, sharesout, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(effective_tax...`
- **le3mbQv5** (UNSUBMITTED, fundamental): Sharpe=-0.31, Fitness=-0.11, TO=0.0363, DD=0.2214。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(primary_sector_focused_company_count / cap - 1)) + 0.5 * rank(ts_rank(sales / expected_return_on_pension...`
- **GreRpV7J** (UNSUBMITTED, fundamental): Sharpe=-0.19, Fitness=-0.06, TO=0.0346, DD=0.1623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(primary_sector_focused_company_count / cap - 1)) + 0.5 * rank(ts_rank(sales / expected_return_on_pension...`
- **GreRAzzG** (UNSUBMITTED, fundamental): Sharpe=-0.42, Fitness=-0.31, TO=0.1629, DD=0.2959。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_zipcode / pv13_revere_company_total - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_spceepsq / fnd...`
- **e7xjw92d** (UNSUBMITTED, fundamental): Sharpe=-0.08, Fitness=-0.02, TO=0.1284, DD=0.2373。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_zipcode / pv13_revere_company_total - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_spceepsq / fnd...`
- **np8ERN8x** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.04, TO=0.0214, DD=0.2294。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(single_sector_pureplay_company_count / pv13_revere_term - 1)) + 0.5 * rank(ts_rank(option_award_expected...`
- **9q7n16Ao** (UNSUBMITTED, fundamental): Sharpe=-0.19, Fitness=-0.05, TO=0.0402, DD=0.1409。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(primary_sector_focused_company_count / cap - 1)) + 0.5 * rank(ts_rank(sales / expected_return_on_pension...`
- **0mMJl2z8** (UNSUBMITTED, fundamental): Sharpe=0.47, Fitness=0.37, TO=0.1052, DD=0.1725。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_zipcode / pv13_revere_company_total - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_spceepsq / fnd...`
- **O0x3YWW1** (UNSUBMITTED, fundamental): Sharpe=0.12, Fitness=0.03, TO=0.0181, DD=0.1409。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(single_sector_pureplay_company_count / pv13_revere_term - 1)) + 0.5 * rank(ts_rank(option_award_expected...`
- **pwKLXo6o** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.02, TO=0.0217, DD=0.1593。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(single_sector_pureplay_company_count / pv13_revere_term - 1)) + 0.5 * rank(ts_rank(option_award_expected...`
- **bldwkVlp** (UNSUBMITTED, fundamental): Sharpe=0.06, Fitness=0.01, TO=0.0155, DD=0.1978。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(single_sector_pureplay_company_count / pv13_revere_term - 1)) + 0.5 * rank(ts_rank(option_award_expected...`
- **e7xjpm0M** (UNSUBMITTED, fundamental): Sharpe=-0.14, Fitness=-0.03, TO=0.0119, DD=0.0937。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ustomergraphrank_page_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ibmii, 120)),de...`
- **E5ed1neR** (UNSUBMITTED, fundamental): Sharpe=-0.51, Fitness=-0.32, TO=0.0123, DD=0.6047。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_company_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_pstkrv, 120)),densify...`
- **vRvQ8YwA** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.03, TO=0.004, DD=0.1446。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_city, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_seniornotes, 120)),densify(p...`
- **mLVvpaQ2** (UNSUBMITTED, fundamental): Sharpe=-0.02, Fitness=-0.0, TO=0.0107, DD=0.0896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ustomergraphrank_page_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ibmii, 120)),de...`
- **rKPxYARo** (UNSUBMITTED, fundamental): Sharpe=0.08, Fitness=0.01, TO=0.0136, DD=0.0777。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_ustomergraphrank_page_rank, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ibmii, 120)),de...`
- **e7xjmAeE** (UNSUBMITTED, fundamental): Sharpe=-0.99, Fitness=-0.85, TO=0.0125, DD=0.9978。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_company_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_pstkrv, 120)),densify...`
- **mLVvpMnE** (UNSUBMITTED, fundamental): Sharpe=-0.97, Fitness=-0.85, TO=0.0127, DD=1.1033。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_company_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_pstkrv, 120)),densify...`
- **le3mpPmN** (UNSUBMITTED, fundamental): Sharpe=0.37, Fitness=0.14, TO=0.0035, DD=0.1444。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_city, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_seniornotes, 120)),densify(p...`
- **Xg80mAMm** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.13, TO=0.0038, DD=0.1432。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_city, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_seniornotes, 120)),densify(p...`
- **0mMJO796** (UNSUBMITTED, fundamental): Sharpe=0.07, Fitness=0.02, TO=0.0079, DD=0.4694。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`

---


### 2026-08-01 12:55 UTC

- **ZYKJNl18** (UNSUBMITTED, option): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_stock_option_comp_cost...`
- **np8Er06M** (UNSUBMITTED, option): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_stock_option_comp_cost...`
- **le3m9m1l** (UNSUBMITTED, option): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_stock_option_comp_cost...`
- **rKPxVro8** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,cap,5),3),0.85),`
- **78npM7qL** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,cap,5),3),0.85),`
- **le3mGY3l** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,cap,5),3),0.85),`
- **ZYKJznXn** (UNSUBMITTED, analyst): Sharpe=-0.08, Fitness=-0.02, TO=0.0145, DD=0.2675。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **omgdGVj2** (UNSUBMITTED, analyst): Sharpe=1.61, Fitness=1.44, TO=0.0205, DD=0.0901。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **Jjv9zbQn** (UNSUBMITTED, analyst): Sharpe=0.32, Fitness=0.12, TO=0.0381, DD=0.1445。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **E5edzrYJ** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.09, TO=0.0106, DD=0.2931。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_num_part,5),3),0.85),`
- **3qeNkPgZ** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.1, TO=0.0096, DD=0.3019。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_num_part,5),3),0.85),`
- **ZYKJd7qd** (UNSUBMITTED, analyst): Sharpe=-0.03, Fitness=-0.0, TO=0.0126, DD=0.2415。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **RR1glRw0** (UNSUBMITTED, analyst): Sharpe=-0.1, Fitness=-0.02, TO=0.0104, DD=0.2932。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **YPge83Vv** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.11, TO=0.0398, DD=0.1453。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **78np3ZVL** (UNSUBMITTED, analyst): Sharpe=0.2, Fitness=0.07, TO=0.0109, DD=0.2745。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_num_part,5),3),0.85),`
- **akEpe7jx** (UNSUBMITTED, analyst): Sharpe=0.34, Fitness=0.13, TO=0.0435, DD=0.147。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **P0OVxd3p** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,rel_num_comp,5),3),0.85),`
- **Xg80VGYm** (UNSUBMITTED, analyst): Sharpe=0.06, Fitness=0.01, TO=0.0084, DD=0.4809。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,cap,5),3),0.85),`
- **vRvQYjrd** (UNSUBMITTED, analyst): Sharpe=-0.04, Fitness=-0.01, TO=0.0059, DD=0.63。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,cap,5),3),0.85),`
- **pwKLa5V6** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,rel_num_comp,5),3),0.85),`
- **gJ92aMEO** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,rel_num_comp,5),3),0.85),`
- **P0OV5d1x** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.0, TO=0.0096, DD=0.4737。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,cap,5),3),0.85),`
- **QP98vgVQ** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,rel_num_comp,5),3),0.85),`
- **WjV5b1Xo** (UNSUBMITTED, fundamental): Sharpe=0.66, Fitness=0.69, TO=0.0821, DD=0.2305。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd4, 120)),densify(pv13_di_5l)), -1)`
- **np8EKv08** (UNSUBMITTED, fundamental): Sharpe=-0.21, Fitness=-0.1, TO=0.0067, DD=0.7176。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(primary_sector_focused_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **E5edvGg9** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.05, TO=0.0077, DD=0.4255。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(primary_sector_focused_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **le3m8717** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.2, TO=0.0757, DD=0.217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd4, 120)),densify(pv13_di_5l)), -1)`
- **A17A0jEg** (UNSUBMITTED, fundamental): Sharpe=-0.22, Fitness=-0.1, TO=0.0076, DD=0.6505。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(primary_sector_focused_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **wpErjA6v** (UNSUBMITTED, fundamental): Sharpe=0.46, Fitness=0.31, TO=0.0816, DD=0.1694。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd4, 120)),densify(pv13_di_5l)), -1)`
- **QP987OAw** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.02, TO=0.0089, DD=0.2888。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(rel_ret_cust, pv13_custretsig_retsig, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(inventory_w...`
- **kqZAjXXd** (UNSUBMITTED, fundamental): Sharpe=-0.17, Fitness=-0.08, TO=0.0077, DD=1.0085。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(single_sector_pureplay_company_count, pv13_ompetitorgraphrank_hub_rank, 20) < 0.5, group_rank(sqrt...`
- **1YzMw1VQ** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.05, TO=0.0063, DD=0.7959。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(single_sector_pureplay_company_count, pv13_ompetitorgraphrank_hub_rank, 20) < 0.5, group_rank(sqrt...`
- **MPLr7WqL** (UNSUBMITTED, fundamental): Sharpe=0.92, Fitness=1.25, TO=0.0018, DD=0.2947。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_custretsig_retsig, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_back...`
- **gJ9280Em** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.38, TO=0.0012, DD=0.2035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_custretsig_retsig, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_back...`
- **omgdNW3l** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0077, DD=0.2554。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(rel_ret_cust, pv13_custretsig_retsig, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(inventory_w...`
- **A17AGalE** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.01, TO=0.0077, DD=0.6309。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(single_sector_pureplay_company_count, pv13_ompetitorgraphrank_hub_rank, 20) < 0.5, group_rank(sqrt...`
- **78npzAbL** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.38, TO=0.0012, DD=0.2035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_custretsig_retsig, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_back...`
- **xAdZd1JJ** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.38, TO=0.0012, DD=0.2035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_custretsig_retsig, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_back...`
- **QP98V0pG** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.25, TO=0.0053, DD=0.3625。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(single_sector_pureplay_company_count, pv13_ompetitorgraphrank_hub_rank, 20) < 0.5, group_rank(sqrt...`
- **LLdQ1dde** (UNSUBMITTED, fundamental): Sharpe=-0.12, Fitness=-0.02, TO=0.3255, DD=0.2436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fnd6_itci / fnd2_a_seniornotes, 126))`
- **omgdlKP6** (UNSUBMITTED, fundamental): Sharpe=-0.23, Fitness=-0.09, TO=0.0237, DD=0.4083。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_revere_parent - 1)) + 0.5 * rank(ts_rank(fn_assets_fair_val_q / fnd2_q_flintasa...`
- **akEpnAj9** (UNSUBMITTED, fundamental): Sharpe=-0.4, Fitness=-0.12, TO=0.2687, DD=0.3002。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(rel_ret_part / rel_ret_cust - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_seqoq / fnd2_a_ltrmdmrepoplinnext1...`
- **0mMJEok6** (UNSUBMITTED, fundamental): Sharpe=-0.06, Fitness=-0.01, TO=0.0258, DD=0.4434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_revere_parent - 1)) + 0.5 * rank(ts_rank(fn_assets_fair_val_q / fnd2_q_flintasa...`
- **LLdQ1a7m** (UNSUBMITTED, fundamental): Sharpe=-0.04, Fitness=-0.01, TO=0.0202, DD=0.4016。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_revere_parent - 1)) + 0.5 * rank(ts_rank(fn_assets_fair_val_q / fnd2_q_flintasa...`
- **P0OV3N5q** (UNSUBMITTED, fundamental): Sharpe=-0.27, Fitness=-0.05, TO=0.3147, DD=0.1861。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(rel_ret_part / rel_ret_cust - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_seqoq / fnd2_a_ltrmdmrepoplinnext1...`
- **xAdZxjxw** (UNSUBMITTED, fundamental): Sharpe=-0.09, Fitness=-0.02, TO=0.0217, DD=0.3687。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_revere_parent - 1)) + 0.5 * rank(ts_rank(fn_assets_fair_val_q / fnd2_q_flintasa...`
- **78npwjXO** (UNSUBMITTED, fundamental): Sharpe=0.07, Fitness=0.01, TO=0.3433, DD=0.2171。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fnd6_itci / fnd2_a_seniornotes, 126))`
- **QP98a7MX** (UNSUBMITTED, fundamental): Sharpe=-0.31, Fitness=-0.07, TO=0.287, DD=0.1989。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(rel_ret_part / rel_ret_cust - 1)) + 0.5 * rank(ts_rank(fnd6_newqv1300_seqoq / fnd2_a_ltrmdmrepoplinnext1...`
- **KPE1b0rz** (UNSUBMITTED, fundamental): Sharpe=-0.13, Fitness=-0.01, TO=0.71, DD=0.2139。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fnd6_itci / fnd2_a_seniornotes, 126))`

---


### 2026-08-01 15:31 UTC

- **1YzrE9Pm** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_parent, vwap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(option_award_outstandin...`
- **zqRl1R6o** (UNSUBMITTED, technical): Sharpe=0.17, Fitness=0.03, TO=0.2579, DD=0.1502。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_parent / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_net_of_tax_a / exp...`
- **Jjv6ZOzj** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_parent, vwap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(option_award_outstandin...`
- **zqRl15EV** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_parent, vwap, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(option_award_outstandin...`
- **A17oZpAe** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.02, TO=0.2658, DD=0.1727。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_parent / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_net_of_tax_a / exp...`
- **KPEWdJYl** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,primary_sector_focused_company_count,5),3),0.85),`
- **2rN3zKQx** (UNSUBMITTED, analyst): Sharpe=0.88, Fitness=0.88, TO=0.022, DD=0.2415。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,pv13_revere_country,5),3),0.85),`
- **omgx53jl** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.11, TO=0.2645, DD=0.1336。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_parent / rel_ret_part - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_net_of_tax_a / exp...`
- **1Yzr9RV6** (UNSUBMITTED, analyst): Sharpe=0.32, Fitness=0.25, TO=0.0189, DD=0.7675。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,pv13_revere_country,5),3),0.85),`
- **vRvWqY13** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,primary_sector_focused_company_count,5),3),0.85),`
- **le3oqJ52** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_cust,primary_sector_focused_company_count,5),3),0.85),`
- **9q7NvLM2** (UNSUBMITTED, analyst): Sharpe=-0.03, Fitness=-0.0, TO=0.0115, DD=0.2317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_com_page_rank,5),3),0.85),`
- **88eMo90v** (UNSUBMITTED, analyst): Sharpe=-0.67, Fitness=-0.73, TO=0.0044, DD=1.6721。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,split,5),3),0.85),`
- **omgxp51n** (UNSUBMITTED, analyst): Sharpe=-0.08, Fitness=-0.03, TO=0.0033, DD=1.1084。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,split,5),3),0.85),`
- **P0OkNolL** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **d5RNpOVx** (UNSUBMITTED, analyst): Sharpe=0.34, Fitness=0.17, TO=0.0105, DD=0.33。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_com_page_rank,5),3),0.85),`
- **omgx7QKb** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **j2rqzqP5** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.07, TO=0.006, DD=0.1574。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,pv13_com_rk_au,5),3),0.85),`
- **np8Lx5Ex** (UNSUBMITTED, analyst): Sharpe=0.16, Fitness=0.05, TO=0.011, DD=0.2401。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_com_page_rank,5),3),0.85),`
- **P0OkQKEK** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.06, TO=0.0071, DD=0.1303。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,pv13_com_rk_au,5),3),0.85),`
- **omgx8Nq6** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **RR1Gj1wd** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **2rN3rWaN** (UNSUBMITTED, fundamental): Sharpe=0.52, Fitness=0.25, TO=0.0232, DD=0.2453。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`inverse(ts_backfill(book_leverage_ratio_3, 120))`
- **omgx1Jwn** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_level, 60) > 2, group_zscore(-inverse(ts_backfill(non_option_equity_awards_forfeited...`
- **RR1GJpxj** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.02, TO=0.0192, DD=0.1754。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(open, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_mfma2_opeps, 120)),densify(pv13_hierarchy_...`
- **E5e9Zq8r** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_level, 60) > 2, group_zscore(-inverse(ts_backfill(non_option_equity_awards_forfeited...`
- **78nekQvO** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_level, 60) > 2, group_zscore(-inverse(ts_backfill(non_option_equity_awards_forfeited...`
- **9q7NzoRV** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0158, DD=0.1625。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(open, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_mfma2_opeps, 120)),densify(pv13_hierarchy_...`
- **np8ELjPE** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(gross_customer_related_intangibles,...`
- **RR1gGzM0** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(gross_customer_related_intangibles,...`
- **wpEr02lv** (UNSUBMITTED, fundamental): Sharpe=-0.54, Fitness=-1.34, TO=0.0189, DD=4.2248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(open, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_txw, 120...`
- **9q7nN8or** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_level, 60) > 2, group_zscore(-inverse(ts_backfill(non_option_equity_awards_forfeited...`
- **ZYKJOlVn** (UNSUBMITTED, fundamental): Sharpe=0.48, Fitness=0.18, TO=0.0115, DD=0.1243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(rel_ret_comp, pv13_ustomergraphrank_auth_rank, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fn...`
- **vRvQW0xa** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.13, TO=0.009, DD=0.1367。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(rel_ret_comp, pv13_ustomergraphrank_auth_rank, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fn...`
- **1YzMM2PR** (UNSUBMITTED, fundamental): Sharpe=0.44, Fitness=0.15, TO=0.0076, DD=0.1317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(rel_ret_comp, pv13_ustomergraphrank_auth_rank, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fn...`
- **O0x33GLp** (UNSUBMITTED, fundamental): Sharpe=-0.27, Fitness=-0.32, TO=0.0075, DD=3.1499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(open, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_txw, 120...`
- **O0x33Z8p** (UNSUBMITTED, fundamental): Sharpe=-0.01, Fitness=-0.0, TO=0.0048, DD=1.6851。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(open, pv13_revere_key_sector_total, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd6_txw, 120...`
- **6Xekk9PJ** (UNSUBMITTED, fundamental): Sharpe=0.04, Fitness=0.01, TO=0.0255, DD=0.372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_reveremap / pv13_com_page_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa1v1300_chech / fnd6_cld2, 126))`
- **MPLrr98o** (UNSUBMITTED, fundamental): Sharpe=-0.06, Fitness=-0.01, TO=0.0248, DD=0.2929。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_reveremap - 1)) + 0.5 * rank(ts_rank(fnd2_asdm / fnd6_exre, 126))`
- **Xg800qa0** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.0, TO=0.0304, DD=0.3637。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_reveremap / pv13_com_page_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa1v1300_chech / fnd6_cld2, 126))`
- **YPgeVodw** (UNSUBMITTED, fundamental): Sharpe=-0.04, Fitness=-0.01, TO=0.0234, DD=0.316。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_level / pv13_reveremap - 1)) + 0.5 * rank(ts_rank(fnd2_asdm / fnd6_exre, 126))`
- **le3mn5ZA** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=0.0, TO=0.0321, DD=0.3499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_reveremap / pv13_com_page_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa1v1300_chech / fnd6_cld2, 126))`

---


### 2026-08-01 18:55 UTC

- **Jjv6N9Wl** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **omgx6lWJ** (UNSUBMITTED, option): Sharpe=0.39, Fitness=0.16, TO=0.0081, DD=0.2143。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(f...`
- **vRvWkVqz** (UNSUBMITTED, option): Sharpe=0.36, Fitness=0.12, TO=0.0093, DD=0.1188。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(f...`
- **Vk3A6V6b** (UNSUBMITTED, option): Sharpe=0.34, Fitness=0.1, TO=0.0107, DD=0.1101。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(f...`
- **A17olQ1d** (UNSUBMITTED, option): Sharpe=0.38, Fitness=0.12, TO=0.0097, DD=0.0957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(f...`
- **omgxqYVb** (UNSUBMITTED, option): Sharpe=0.07, Fitness=0.02, TO=0.0143, DD=0.2726。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_company_total, 60) > 2, group_zscore(-inverse(ts_backfill(option_grants_avg_exercise...`
- **zqRlkje1** (UNSUBMITTED, option): Sharpe=0.14, Fitness=0.04, TO=0.0102, DD=0.3036。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_company_total, 60) > 2, group_zscore(-inverse(ts_backfill(option_grants_avg_exercise...`
- **A17oGp7Y** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,pv13_revere_key_sector_total,5),3),0.85),`
- **KPEWGm91** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,pv13_revere_key_sector_total,5),3),0.85),`
- **Vk3AGa3w** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,pv13_revere_key_sector_total,5),3),0.85),`
- **gJ9n8YYm** (UNSUBMITTED, analyst): Sharpe=-0.11, Fitness=-0.03, TO=0.0092, DD=0.2616。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_term_sector_total,5),3),0.85),`
- **d5RNR10v** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,dividend,5),3),0.85),`
- **akE5E1bv** (UNSUBMITTED, analyst): Sharpe=-0.18, Fitness=-0.05, TO=0.0087, DD=0.2606。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,pv13_revere_term_sector_total,5),3),0.85),`
- **e7xXx8v6** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.06, TO=0.0026, DD=0.4768。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,split,5),3),0.85),`
- **vRvWlW3w** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,split,5),3),0.85),`
- **QP9wV29g** (UNSUBMITTED, analyst): Sharpe=0.26, Fitness=0.08, TO=0.0514, DD=0.1319。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **WjVvGq6x** (UNSUBMITTED, analyst): Sharpe=0.34, Fitness=0.24, TO=0.0035, DD=0.2752。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,split,5),3),0.85),`
- **58kPwANn** (UNSUBMITTED, analyst): Sharpe=0.46, Fitness=0.43, TO=0.0047, DD=0.3106。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,split,5),3),0.85),`
- **Xg8dpnpm** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,cap,5),3),0.85),`
- **KPEWbbrk** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.19, TO=0.0094, DD=0.3619。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **88eMz6kX** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.04, TO=0.0473, DD=0.1153。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **rKPZWnQ9** (UNSUBMITTED, analyst): Sharpe=0.21, Fitness=0.1, TO=0.0084, DD=0.441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **ZYKOorl8** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,cap,5),3),0.85),`
- **GreZoJ9x** (UNSUBMITTED, analyst): Sharpe=1.37, Fitness=1.39, TO=0.0119, DD=0.1806。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(close,volume,5),3),0.85),`
- **xAdJRj6J** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,cap,5),3),0.85),`
- **78neJj8O** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,cap,5),3),0.85),`
- **ZYKOrPa8** (UNSUBMITTED, fundamental): Sharpe=-0.09, Fitness=-0.03, TO=0.0022, DD=0.4277。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a_flint...`
- **P0OknLME** (UNSUBMITTED, fundamental): Sharpe=-0.45, Fitness=-0.19, TO=0.0022, DD=0.1513。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a_flint...`
- **zqRl5091** (UNSUBMITTED, fundamental): Sharpe=-0.56, Fitness=-0.25, TO=0.0026, DD=0.179。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a_flint...`
- **kqZznv3d** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.27, TO=0.0055, DD=0.1675。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_com_page_rank, rel_num_all, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(available_for_sa...`
- **6Xe5Rw2G** (UNSUBMITTED, fundamental): Sharpe=-0.41, Fitness=-0.16, TO=0.0024, DD=0.1427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, pv13_com_rk_au, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(fnd2_a_flint...`
- **88eMOOrX** (UNSUBMITTED, fundamental): Sharpe=0.2, Fitness=0.07, TO=0.0144, DD=0.3494。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_custretsig_retsig, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_gp, 120)),den...`
- **rKPZbE61** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.08, TO=0.0443, DD=0.4107。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(single_sector_pureplay_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **pwK9nqk6** (UNSUBMITTED, fundamental): Sharpe=0.92, Fitness=1.19, TO=0.0261, DD=0.3184。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(single_sector_pureplay_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **A17onRYe** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.1, TO=0.019, DD=0.3233。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_custretsig_retsig, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_gp, 120)),den...`
- **9q7NakxV** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.18, TO=0.0309, DD=0.5073。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(single_sector_pureplay_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **QP9w2YkK** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.28, TO=0.0255, DD=0.5473。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(single_sector_pureplay_company_count, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_...`
- **d5RNE0oJ** (UNSUBMITTED, fundamental): Sharpe=1.73, Fitness=0.87, TO=0.4997, DD=0.0789。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))`
- **GreZMo3x** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.06, TO=0.0168, DD=0.3685。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_custretsig_retsig, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_gp, 120)),den...`
- **MPLJKPea** (UNSUBMITTED, fundamental): Sharpe=-0.32, Fitness=-0.14, TO=0.018, DD=0.3045。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_cap / pv13_ustomergraphrank_hub_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa2v1300_seqo /...`
- **N1RY5NZo** (UNSUBMITTED, fundamental): Sharpe=-0.35, Fitness=-0.12, TO=0.0573, DD=0.2346。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_key_sector_total - 1)) + 0.5 * rank(ts_rank(fnd2_dbplanepdfbnfpnext12m / fnd6_new...`
- **zqRlJrRE** (UNSUBMITTED, fundamental): Sharpe=-0.4, Fitness=-0.14, TO=0.0707, DD=0.1969。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_key_sector_total - 1)) + 0.5 * rank(ts_rank(fnd2_dbplanepdfbnfpnext12m / fnd6_new...`
- **A17oO02R** (UNSUBMITTED, fundamental): Sharpe=-0.47, Fitness=-0.18, TO=0.0527, DD=0.2536。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_key_sector_total - 1)) + 0.5 * rank(ts_rank(fnd2_dbplanepdfbnfpnext12m / fnd6_new...`
- **WjVvWn3k** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.14, TO=0.0211, DD=0.2939。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_cap / pv13_ustomergraphrank_hub_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa2v1300_seqo /...`
- **xAdJm6ml** (UNSUBMITTED, fundamental): Sharpe=-0.47, Fitness=-0.24, TO=0.0205, DD=0.4197。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_cap / pv13_ustomergraphrank_hub_rank - 1)) + 0.5 * rank(ts_rank(fnd6_newa2v1300_seqo /...`
- **mLVEzdX2** (UNSUBMITTED, fundamental): Sharpe=-0.44, Fitness=-0.16, TO=0.0652, DD=0.191。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_key_sector_total - 1)) + 0.5 * rank(ts_rank(fnd2_dbplanepdfbnfpnext12m / fnd6_new...`
- **rKPZzQw8** (UNSUBMITTED, fundamental): Sharpe=-0.45, Fitness=-0.28, TO=0.0785, DD=0.5695。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / low - 1)) + 0.5 * rank(ts_rank(operating_expense / financing_costs_amortizatio...`
- **O0xlmYK7** (UNSUBMITTED, fundamental): Sharpe=-0.35, Fitness=-0.21, TO=0.0787, DD=0.6698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / low - 1)) + 0.5 * rank(ts_rank(operating_expense / financing_costs_amortizatio...`
- **P0Ok6XWJ** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0104, DD=0.1817。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,open,5),3),0.85),`
- **e7xXKo0z** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0112, DD=0.1532。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,open,5),3),0.85),`
- **e7xXgXqM** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.04, TO=0.0121, DD=0.1623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,open,5),3),0.85),`
- **3qe83lpz** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.3, TO=0.0223, DD=0.0735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **kqZzbqeO** (UNSUBMITTED, fundamental): Sharpe=4.13, Fitness=6.54, TO=0.1364, DD=0.0014。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **QP9wqPJG** (UNSUBMITTED, fundamental): Sharpe=0.79, Fitness=0.5, TO=0.0288, DD=0.0814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`

---


### 2026-08-01 21:57 UTC

- **LLd0YWq9** (UNSUBMITTED, option): Sharpe=0.73, Fitness=0.4, TO=0.028, DD=0.1086。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / pv13_revere_index_cap - 1)) + 0.5 * rank(ts_rank(fn_comp_options_exercises_wei...`
- **d5RN6M9X** (UNSUBMITTED, option): Sharpe=0.63, Fitness=0.33, TO=0.0246, DD=0.1298。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / pv13_revere_index_cap - 1)) + 0.5 * rank(ts_rank(fn_comp_options_exercises_wei...`
- **78nerrEb** (UNSUBMITTED, option): Sharpe=0.74, Fitness=1.16, TO=0.0117, DD=0.6777。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / pv13_revere_index_cap - 1)) + 0.5 * rank(ts_rank(fn_comp_options_exercises_wei...`
- **6Xe5QAQJ** (UNSUBMITTED, option): Sharpe=0.62, Fitness=0.34, TO=0.0243, DD=0.1287。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_index_value / pv13_revere_index_cap - 1)) + 0.5 * rank(ts_rank(fn_comp_options_exercises_wei...`
- **YPgRONzW** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.07, TO=0.0062, DD=0.8264。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(vwap, pv13_revere_zipcode, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(period_goodwill_acquis...`
- **YPgROmNq** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.03, TO=0.0051, DD=0.0796。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(vwap, pv13_revere_zipcode, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(period_goodwill_acquis...`
- **wpE0Ax3d** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **2rN32VJ5** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **2rN322O5** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **QP9woK9p** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.12, TO=0.0145, DD=0.2867。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_custretsig_retsig, 60) > 2, group_zscore(-inverse(ts_backfill(deferred_tax_liability_proper...`
- **88eM23xl** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.13, TO=0.012, DD=0.2921。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_custretsig_retsig, 60) > 2, group_zscore(-inverse(ts_backfill(deferred_tax_liability_proper...`
- **pwK9pjAv** (UNSUBMITTED, technical): Sharpe=1.18, Fitness=1.4, TO=0.0544, DD=0.3078。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(returns, 60) > 2, group_zscore(-inverse(ts_backfill(cash, 120)),densify(market)), -1)`
- **2rN32NnP** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.05, TO=0.0171, DD=0.069。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_profit_before_interest_tax / pv13_revere_parent, 126), sector)`
- **N1RY2pxX** (UNSUBMITTED, analyst): Sharpe=0.13, Fitness=0.02, TO=0.0199, DD=0.1089。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_profit_before_interest_tax / pv13_revere_parent, 126), sector)`
- **mLVElO5K** (UNSUBMITTED, analyst): Sharpe=0.53, Fitness=0.22, TO=0.083, DD=0.107。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_basic_af_v4_nd_sales_high / rel_num_all, 126), pv13_rha2_min20_sector)`
- **1Yzr2EbJ** (UNSUBMITTED, analyst): Sharpe=0.51, Fitness=0.21, TO=0.0811, DD=0.1328。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_basic_af_v4_nd_sales_high / rel_num_all, 126), pv13_rha2_min20_sector)`
- **d5RNPkzE** (UNSUBMITTED, analyst): Sharpe=-0.04, Fitness=-0.0, TO=0.0307, DD=0.0836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(operating_profit_before_interest_tax / pv13_revere_parent, 126), sector)`
- **9q7Nk5O1** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.04, TO=0.4699, DD=0.161。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimate_1qf_v4_nd_ptpr_low / rel_ret_part, 126), pv13_rha2_min20_sector)`
- **bldeA8Kp** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.14, TO=0.0147, DD=0.3399。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **MPLJVGW6** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,pv13_revere_level,5),3),0.85),`
- **Jjv6rXgx** (UNSUBMITTED, analyst): Sharpe=-0.0, Fitness=-0.0, TO=0.0025, DD=2.0434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,returns,5),3),0.85),`
- **d5RNvgdY** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,returns,5),3),0.85),`
- **O0xlgY8d** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,pv13_revere_level,5),3),0.85),`
- **xAdJ5Kbb** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,returns,5),3),0.85),`
- **GreZxZm3** (UNSUBMITTED, analyst): Sharpe=0.26, Fitness=0.11, TO=0.0135, DD=0.4049。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **qM6Q3NkA** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,pv13_revere_level,5),3),0.85),`
- **RR1GKq9a** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,pv13_revere_level,5),3),0.85),`
- **kqZzOkez** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_key_sector_total,returns,5),3),0.85),`
- **RR1GK0Oz** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_level,5),3),0.85),`
- **rKPZGnKE** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.0099, DD=0.8406。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,pv13_revere_term_sector_total,5),3),0.85),`
- **YPgRzbMJ** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_level,5),3),0.85),`
- **rKPZGOz8** (UNSUBMITTED, analyst): Sharpe=0.01, Fitness=0.0, TO=0.0083, DD=0.8552。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,pv13_revere_term_sector_total,5),3),0.85),`
- **mLVE7qoK** (UNSUBMITTED, analyst): Sharpe=-0.3, Fitness=-0.15, TO=0.0061, DD=0.4612。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,single_sector_pureplay_company_count,5),3),0.85),`
- **3qe8PWeP** (UNSUBMITTED, analyst): Sharpe=0.16, Fitness=0.06, TO=0.0126, DD=0.7015。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,pv13_revere_term_sector_total,5),3),0.85),`
- **6Xe508MG** (UNSUBMITTED, analyst): Sharpe=-0.05, Fitness=-0.01, TO=0.0067, DD=0.4222。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,single_sector_pureplay_company_count,5),3),0.85),`
- **d5RN3NpJ** (UNSUBMITTED, analyst): Sharpe=-0.01, Fitness=-0.0, TO=0.0062, DD=0.4656。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,single_sector_pureplay_company_count,5),3),0.85),`
- **qM6QYlpE** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.04, TO=0.0096, DD=0.143。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,dividend,5),3),0.85),`
- **le3o5VxA** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **E5e98kEL** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_level,5),3),0.85),`
- **rKPZNYE8** (UNSUBMITTED, analyst): Sharpe=0.02, Fitness=0.0, TO=0.0081, DD=0.231。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,dividend,5),3),0.85),`
- **wpE03dl2** (UNSUBMITTED, analyst): Sharpe=-0.14, Fitness=-0.04, TO=0.1987, DD=0.4234。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **omgxRR0J** (UNSUBMITTED, analyst): Sharpe=-0.26, Fitness=-0.11, TO=0.2261, DD=0.5067。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **QP9wOOY5** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.0092, DD=0.1088。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,dividend,5),3),0.85),`
- **vRvWZNLb** (UNSUBMITTED, fundamental): Sharpe=0.01, Fitness=0.0, TO=0.0031, DD=0.1036。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, adjfactor, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(net_deferred_fina...`
- **mLVEd5Z5** (UNSUBMITTED, fundamental): Sharpe=-0.04, Fitness=-0.0, TO=0.0034, DD=0.0728。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, adjfactor, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(net_deferred_fina...`
- **e7xXN38g** (UNSUBMITTED, fundamental): Sharpe=0.08, Fitness=0.04, TO=0.0034, DD=1.516。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_revere_country, 20) < 0.5, group_rank(sqrt(winsorize(ts_backf...`
- **pwK9xz0x** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.1, TO=0.0038, DD=0.1081。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_revere_zipcode, adjfactor, 20) < 0.5, group_rank(sqrt(winsorize(ts_backfill(net_deferred_fina...`
- **LLd0Exv6** (UNSUBMITTED, fundamental): Sharpe=-0.08, Fitness=-0.01, TO=0.0046, DD=0.1553。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_revere_country, 20) < 0.5, group_rank(sqrt(winsorize(ts_backf...`
- **A17oeWxE** (UNSUBMITTED, fundamental): Sharpe=-0.07, Fitness=-0.01, TO=0.0042, DD=0.1534。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_corr(pv13_ustomergraphrank_hub_rank, pv13_revere_country, 20) < 0.5, group_rank(sqrt(winsorize(ts_backf...`
- **QP9wWKGr** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.25, TO=0.0307, DD=0.2792。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(fnd2_a_dbplanservicec...`
- **58kPGz8z** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.27, TO=0.0267, DD=1.2562。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(fnd2_a_dbplanservicec...`
- **omgxP3jk** (UNSUBMITTED, fundamental): Sharpe=-0.17, Fitness=-0.03, TO=0.0451, DD=0.1322。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_country - 1)) + 0.5 * rank(ts_rank(fnd2_unrgtxbnfrdsrefpstf / fnd6_newa1v1300_dpc...`
- **qM6Q5vY2** (UNSUBMITTED, fundamental): Sharpe=-0.16, Fitness=-0.06, TO=0.0233, DD=0.3349。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_city / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(fnd2_a_dbplanservicec...`
- **A17oLW1X** (UNSUBMITTED, fundamental): Sharpe=-0.24, Fitness=-0.06, TO=0.0467, DD=0.1875。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(dividend / pv13_revere_country - 1)) + 0.5 * rank(ts_rank(fnd2_unrgtxbnfrdsrefpstf / fnd6_newa1v1300_dpc...`
- **58kPJJWn** (UNSUBMITTED, fundamental): Sharpe=0.93, Fitness=0.63, TO=0.027, DD=0.0571。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **RR1Ge1pj** (UNSUBMITTED, fundamental): Sharpe=4.13, Fitness=6.54, TO=0.1364, DD=0.0014。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **2rN35nnb** (UNSUBMITTED, fundamental): Sharpe=0.86, Fitness=0.92, TO=0.0541, DD=0.2578。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **np8Lakaa** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.05, TO=0.0107, DD=0.2645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_fatc, 120)),densify(pv13_hierarc...`
- **xAdJvgxl** (UNSUBMITTED, fundamental): Sharpe=-0.02, Fitness=-0.0, TO=0.0124, DD=0.2566。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_fatc, 120)),densify(pv13_hierarc...`
- **A17ox9rd** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.08, TO=0.0121, DD=0.1549。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(high, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_excesstxbnffsbcpnoprat, 120)),densify(pv...`
- **Jjv68q7e** (UNSUBMITTED, fundamental): Sharpe=0.49, Fitness=0.26, TO=0.0176, DD=0.1412。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(high, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_excesstxbnffsbcpnoprat, 120)),densify(pv...`
- **78neL5qv** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.09, TO=0.0149, DD=0.1609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(high, 60) > 2, group_zscore(-inverse(ts_backfill(fnd2_a_excesstxbnffsbcpnoprat, 120)),densify(pv...`
- **blde6gqm** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.08, TO=0.0092, DD=0.2333。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_fatc, 120)),densify(pv13_hierarc...`
- **1YzrN02R** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.02, TO=0.0122, DD=0.27。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_fatc, 120)),densify(pv13_hierarc...`

---


### 2026-08-02 01:01 UTC

- **0mpbO6p8** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.07, TO=0.0154, DD=0.3523。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(sharesout, 60) > 2, group_zscore(-inverse(ts_backfill(lease_minimum_payments_due_thereafter, 120...`
- **9qpzZxQ2** (UNSUBMITTED, technical): Sharpe=0.59, Fitness=0.35, TO=0.005, DD=0.1671。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_country, 60) > 2, group_zscore(-inverse(ts_backfill(raw_material_inventory_total, 12...`
- **leWLp8Al** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.08, TO=0.0185, DD=0.3189。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(sharesout, 60) > 2, group_zscore(-inverse(ts_backfill(lease_minimum_payments_due_thereafter, 120...`
- **blQYG9w6** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.39, TO=0.0055, DD=0.1907。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_country, 60) > 2, group_zscore(-inverse(ts_backfill(raw_material_inventory_total, 12...`
- **mL5PwqzW** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.09, TO=0.0248, DD=0.3178。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(sharesout, 60) > 2, group_zscore(-inverse(ts_backfill(lease_minimum_payments_due_thereafter, 120...`
- **blQYGpKp** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.16, TO=0.0139, DD=0.3947。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,single_sector_pureplay_company_count,5),3),0.85),`
- **9qpzZzJx** (UNSUBMITTED, technical): Sharpe=0.51, Fitness=0.37, TO=0.0124, DD=0.4471。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,single_sector_pureplay_company_count,5),3),0.85),`
- **A1GR18LX** (UNSUBMITTED, technical): Sharpe=0.29, Fitness=0.17, TO=0.0122, DD=0.5943。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,single_sector_pureplay_company_count,5),3),0.85),`
- **xANKAoNN** (UNSUBMITTED, technical): Sharpe=0.11, Fitness=0.04, TO=0.0108, DD=0.7527。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_index_value,single_sector_pureplay_company_count,5),3),0.85),`
- **ZYERYAkZ** (UNSUBMITTED, analyst): Sharpe=-0.14, Fitness=-0.02, TO=0.1341, DD=0.0757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cfo_median / adv20, 126), pv13_5l_scibr)`
- **gJ8YJjWe** (UNSUBMITTED, analyst): Sharpe=-0.18, Fitness=-0.04, TO=0.1101, DD=0.0917。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cfo_median / adv20, 126), pv13_5l_scibr)`
- **E5GZ5E10** (UNSUBMITTED, analyst): Sharpe=1.08, Fitness=0.3, TO=0.4594, DD=0.0642。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actual_1qf_v4_nd_cfi_value / rel_ret_all, 126), pv13_hierarchy_min10_top3000_513_sector)`
- **d5Z25daY** (UNSUBMITTED, analyst): Sharpe=-0.09, Fitness=-0.02, TO=0.0941, DD=0.1423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cfo_median / adv20, 126), pv13_5l_scibr)`
- **npN1pOX3** (UNSUBMITTED, analyst): Sharpe=-0.25, Fitness=-0.03, TO=0.628, DD=0.1476。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_number / pv13_custretsig_retsig, 126), pv13_hierarchy_...`
- **6XpnX3GG** (UNSUBMITTED, analyst): Sharpe=0.61, Fitness=0.18, TO=0.3581, DD=0.0803。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actual_1qf_v4_nd_cfi_value / rel_ret_all, 126), pv13_hierarchy_min10_top3000_513_sector)`
- **RRmJR0Yb** (UNSUBMITTED, analyst): Sharpe=-0.08, Fitness=-0.01, TO=0.1083, DD=0.1376。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cfo_median / adv20, 126), pv13_5l_scibr)`
- **WjAEj89O** (UNSUBMITTED, analyst): Sharpe=1.06, Fitness=0.26, TO=0.5201, DD=0.0605。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actual_1qf_v4_nd_cfi_value / rel_ret_all, 126), pv13_hierarchy_min10_top3000_513_sector)`
- **58pZZmAJ** (UNSUBMITTED, analyst): Sharpe=-0.03, Fitness=-0.0, TO=0.017, DD=0.1924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank,rel_ret_cust,5),3),0.85),`
- **omN11kYv** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.09, TO=0.0114, DD=0.1558。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,dividend,5),3),0.85),`
- **E5GZZqM0** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.06, TO=0.0137, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,dividend,5),3),0.85),`
- **vRNKKzQA** (UNSUBMITTED, analyst): Sharpe=0.08, Fitness=0.03, TO=0.0368, DD=0.8826。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **O0G11mng** (UNSUBMITTED, analyst): Sharpe=0.3, Fitness=0.22, TO=0.0278, DD=0.6428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **WjAEEwZd** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.05, TO=0.0159, DD=0.1125。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,dividend,5),3),0.85),`
- **mL5PP2kK** (UNSUBMITTED, analyst): Sharpe=0.09, Fitness=0.01, TO=0.0178, DD=0.1565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_comp,dividend,5),3),0.85),`
- **mLVEEQ8E** (UNSUBMITTED, analyst): Sharpe=0.3, Fitness=0.22, TO=0.0327, DD=0.7812。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **MPLJJdmr** (UNSUBMITTED, analyst): Sharpe=0.01, Fitness=0.0, TO=0.0352, DD=0.8721。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **GreZZgMZ** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,adv20,5),3),0.85),`
- **A17ooGZg** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,adv20,5),3),0.85),`
- **mLVEEZPx** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(returns,adv20,5),3),0.85),`
- **A17ooq8R** (UNSUBMITTED, analyst): Sharpe=0.29, Fitness=0.14, TO=0.0099, DD=0.2165。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(vwap,dividend,5),3),0.85),`
- **np8LLwbE** (UNSUBMITTED, analyst): Sharpe=0.14, Fitness=0.05, TO=0.0068, DD=0.4549。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,open,5),3),0.85),`
- **A17ooMAY** (UNSUBMITTED, analyst): Sharpe=0.32, Fitness=0.15, TO=0.0106, DD=0.3407。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,open,5),3),0.85),`
- **YPgRRPl6** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.17, TO=0.0068, DD=0.1829。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(vwap,dividend,5),3),0.85),`
- **gJ9nnJO0** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.15, TO=0.0091, DD=0.2093。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(vwap,dividend,5),3),0.85),`
- **E5e9dzmK** (UNSUBMITTED, analyst): Sharpe=0.43, Fitness=0.23, TO=0.0082, DD=0.2032。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(vwap,dividend,5),3),0.85),`
- **WjVv5elo** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.26, TO=0.0141, DD=0.3003。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_key_sector_total,5),3),0.85),`
- **kqZzAgnL** (UNSUBMITTED, analyst): Sharpe=0.72, Fitness=0.74, TO=0.0169, DD=0.2629。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_key_sector_total,5),3),0.85),`
- **RR1Ggb7d** (UNSUBMITTED, analyst): Sharpe=-0.25, Fitness=-0.07, TO=0.0135, DD=0.3306。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,pv13_com_rk_au,5),3),0.85),`
- **A17oAlJR** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.17, TO=0.0143, DD=0.3407。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_key_sector_total,5),3),0.85),`
- **j2rq7jE5** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.0154, DD=0.2469。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,pv13_com_rk_au,5),3),0.85),`
- **xAdJZe0W** (UNSUBMITTED, analyst): Sharpe=-0.11, Fitness=-0.02, TO=0.0114, DD=0.3417。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(high,pv13_com_rk_au,5),3),0.85),`
- **LLd0Qqe2** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.13, TO=0.0525, DD=0.3397。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_comproduct_company, pv13_ustomergraphrank_auth_rank, 5), 3) * group_zscore(log(winsorize(...`
- **A17oAdzw** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.12, TO=0.0361, DD=0.2345。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_comproduct_company, pv13_ustomergraphrank_auth_rank, 5), 3) * group_zscore(log(winsorize(...`
- **xAdJZKnl** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_reveremap, pv13_revere_comproduct_company, 5), 3) * group_zscore(log(winsorize(ts_backfill(max_f...`
- **np8LE10E** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.03, TO=0.044, DD=0.2547。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_comproduct_company, pv13_ustomergraphrank_auth_rank, 5), 3) * group_zscore(log(winsorize(...`
- **YPgRVOAw** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_reveremap, pv13_revere_comproduct_company, 5), 3) * group_zscore(log(winsorize(ts_backfill(max_f...`
- **6Xe5Wj7L** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_reveremap, pv13_revere_comproduct_company, 5), 3) * group_zscore(log(winsorize(ts_backfill(max_f...`
- **2rN3glm5** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.06, TO=0.0142, DD=0.1241。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(equity_awards_nonoption_forfeited_count,...`
- **xAdJLRjW** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0185, DD=0.0896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(equity_awards_nonoption_forfeited_count,...`
- **WjVvZ9Gx** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.2, TO=0.0279, DD=0.172。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **j2rqp9MZ** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.04, TO=0.0178, DD=0.1035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_all, 60) > 2, group_zscore(-inverse(ts_backfill(equity_awards_nonoption_forfeited_count,...`
- **88eM016X** (UNSUBMITTED, fundamental): Sharpe=4.13, Fitness=6.54, TO=0.1364, DD=0.0014。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **np8LGjZd** (UNSUBMITTED, fundamental): Sharpe=0.29, Fitness=0.17, TO=0.051, DD=0.3207。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **6Xe56Qrp** (UNSUBMITTED, fundamental): Sharpe=0.72, Fitness=0.41, TO=0.0288, DD=0.0686。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`

---


### 2026-08-02 04:11 UTC

- **vRNKJ5wv** (UNSUBMITTED, option): Sharpe=0.88, Fitness=0.53, TO=0.0111, DD=0.0899。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_compensation_cost_nonveste...`
- **9qpzAqv9** (UNSUBMITTED, option): Sharpe=0.93, Fitness=0.57, TO=0.0088, DD=0.0792。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_compensation_cost_nonveste...`
- **qMNKmKE2** (UNSUBMITTED, option): Sharpe=0.87, Fitness=0.51, TO=0.0127, DD=0.1243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(unrecognized_compensation_cost_nonveste...`
- **A1GRa82Q** (UNSUBMITTED, technical): Sharpe=0.1, Fitness=0.02, TO=0.3, DD=0.3971。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, pv13_revere_term_sector_total, 5), 3) * group_zscore(log(winsorize(ts_backfill(ebit_max, 120), ...`
- **rK21zd68** (UNSUBMITTED, technical): Sharpe=0.45, Fitness=0.18, TO=0.4048, DD=0.5382。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, pv13_revere_term_sector_total, 5), 3) * group_zscore(log(winsorize(ts_backfill(ebit_max, 120), ...`
- **zqNvoPeV** (UNSUBMITTED, technical): Sharpe=-0.17, Fitness=-0.07, TO=0.0084, DD=0.5813。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,primary_sector_focused_company_count,5),3),0.85),`
- **kqPxXzAO** (UNSUBMITTED, technical): Sharpe=-0.22, Fitness=-0.1, TO=0.0088, DD=0.6043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,primary_sector_focused_company_count,5),3),0.85),`
- **6Xpn1oqY** (UNSUBMITTED, technical): Sharpe=0.04, Fitness=0.01, TO=0.008, DD=0.6032。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,primary_sector_focused_company_count,5),3),0.85),`
- **ak1rleZ2** (UNSUBMITTED, technical): Sharpe=-0.08, Fitness=-0.02, TO=0.0087, DD=0.5797。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,primary_sector_focused_company_count,5),3),0.85),`
- **wpa81l31** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_grants_q, 120)),den...`
- **ZYERxPGd** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.02, TO=0.0129, DD=0.1165。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,rel_ret_comp,5),3),0.85),`
- **ak1rM0lO** (UNSUBMITTED, technical): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_term, 60) > 2, group_zscore(-inverse(ts_backfill(fn_comp_non_opt_grants_q, 120)),den...`
- **kqPxb8Ek** (UNSUBMITTED, analyst): Sharpe=-0.11, Fitness=-0.02, TO=0.0136, DD=0.1509。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,rel_ret_comp,5),3),0.85),`
- **ZYERq0EQ** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,vwap,5),3),0.85),`
- **1Ypq1dnz** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,vwap,5),3),0.85),`
- **1Ypq11Mm** (UNSUBMITTED, analyst): Sharpe=-0.53, Fitness=-0.15, TO=0.133, DD=0.1265。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(vwap, pv13_com_page_rank, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_actuals_basic_af_nd...`
- **MPGjqRJn** (UNSUBMITTED, analyst): Sharpe=-0.66, Fitness=-0.2, TO=0.1337, DD=0.1369。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(vwap, pv13_com_page_rank, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_actuals_basic_af_nd...`
- **A1GRJOaR** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, pv13_revere_key_sector_total, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances...`
- **gJ8Yqkqe** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, pv13_revere_key_sector_total, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances...`
- **P0GJjkxw** (UNSUBMITTED, analyst): Sharpe=-0.24, Fitness=-0.06, TO=0.1327, DD=0.156。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(vwap, pv13_com_page_rank, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_actuals_basic_af_nd...`
- **O0G1KX9v** (UNSUBMITTED, analyst): Sharpe=-0.6, Fitness=-0.19, TO=0.1328, DD=0.1471。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(vwap, pv13_com_page_rank, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_actuals_basic_af_nd...`
- **P0GJjnLJ** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, pv13_revere_key_sector_total, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances...`
- **RRmJ0YQa** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,pv13_revere_comproduct_company,5),3),0.85),`
- **MPGj9wko** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.15, TO=0.0151, DD=0.2629。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **leWLJOPA** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.15, TO=0.0102, DD=0.2669。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **blQY7Zq6** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.15, TO=0.012, DD=0.2802。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **2rp1P0kx** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(open,pv13_revere_comproduct_company,5),3),0.85),`
- **YPvjZz2J** (UNSUBMITTED, analyst): Sharpe=0.16, Fitness=0.02, TO=0.8514, DD=0.1959。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actuals_advanced_af_nd_bvps_value / returns, 126), pv13_h_min52_1k_sector)`
- **QPG1evOp** (UNSUBMITTED, analyst): Sharpe=-0.15, Fitness=-0.03, TO=0.0383, DD=0.102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_capex_low / pv13_revere_company_total, 126), pv13_new_4l_s...`
- **ak1rJ3j5** (UNSUBMITTED, analyst): Sharpe=0.19, Fitness=0.02, TO=0.8567, DD=0.1645。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actuals_advanced_af_nd_bvps_value / returns, 126), pv13_h_min52_1k_sector)`
- **GrGqVp55** (UNSUBMITTED, analyst): Sharpe=0.13, Fitness=0.02, TO=0.0307, DD=0.0821。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_capex_low / pv13_revere_company_total, 126), pv13_new_4l_s...`
- **MPGjwoga** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.0, TO=0.0279, DD=0.1035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_capex_low / pv13_revere_company_total, 126), pv13_new_4l_s...`
- **ZYERLJEZ** (UNSUBMITTED, analyst): Sharpe=0.3, Fitness=0.04, TO=0.8701, DD=0.1288。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_actuals_advanced_af_nd_bvps_value / returns, 126), pv13_h_min52_1k_sector)`
- **KPGKRpLz** (UNSUBMITTED, analyst): Sharpe=0.01, Fitness=0.0, TO=0.0042, DD=0.7314。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,adv20,5),3),0.85),`
- **88pmqNrv** (UNSUBMITTED, analyst): Sharpe=-0.11, Fitness=-0.04, TO=0.0054, DD=0.6264。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,adv20,5),3),0.85),`
- **0mpbWjQ8** (UNSUBMITTED, analyst): Sharpe=-0.12, Fitness=-0.04, TO=0.0046, DD=0.5112。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,adv20,5),3),0.85),`
- **rK21mjmJ** (UNSUBMITTED, analyst): Sharpe=-0.12, Fitness=-0.04, TO=0.0061, DD=0.5334。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,adv20,5),3),0.85),`
- **gJ8YzwWm** (UNSUBMITTED, fundamental): Sharpe=-4.18, Fitness=-4.77, TO=1.0, DD=0.0。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **KPGKaWvx** (UNSUBMITTED, fundamental): Sharpe=4.13, Fitness=6.54, TO=0.1364, DD=0.0014。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **A1GRKAwR** (UNSUBMITTED, fundamental): Sharpe=0.91, Fitness=0.61, TO=0.0288, DD=0.0571。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **zqNvpLLd** (UNSUBMITTED, fundamental): Sharpe=6.1, Fitness=7.43, TO=1.0, DD=0.0。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **gJ8YpxgM** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.33, TO=0.1351, DD=1.1762。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **kqPxlQkd** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.3, TO=0.0223, DD=0.0735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **6XpnOzOP** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.18, TO=0.0064, DD=0.4327。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,open,5),3),0.85),`
- **O0G1a15d** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.24, TO=0.0089, DD=0.3692。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,open,5),3),0.85),`
- **78zkERdv** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.19, TO=0.0078, DD=0.4431。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,open,5),3),0.85),`
- **Xgoj5xZz** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.27, TO=0.0113, DD=0.3466。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(low,open,5),3),0.85),`
- **zqNv1ro1** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.27, TO=0.0458, DD=0.0827。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_min_guidance_quarterly / pv13_com_rk_au, 126), pv13_hierarchy_min51_f1_513_sector)`
- **wpa8MZJY** (UNSUBMITTED, fundamental): Sharpe=0.62, Fitness=0.24, TO=0.0494, DD=0.0912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_min_guidance_quarterly / pv13_com_rk_au, 126), pv13_hierarchy_min51_f1_513_sector)`
- **6Xpnvp87** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.3, TO=0.0223, DD=0.0735。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **0mpb0Ma6** (UNSUBMITTED, fundamental): Sharpe=0.66, Fitness=0.28, TO=0.0444, DD=0.0686。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_min_guidance_quarterly / pv13_com_rk_au, 126), pv13_hierarchy_min51_f1_513_sector)`
- **MPGjo9ro** (UNSUBMITTED, fundamental): Sharpe=-0.09, Fitness=-0.03, TO=0.015, DD=0.428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,single_sector_pureplay_company_count,5),3),0.85),`
- **A1GRZAqw** (UNSUBMITTED, fundamental): Sharpe=0.72, Fitness=0.41, TO=0.0288, DD=0.0686。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **npN1RQX3** (UNSUBMITTED, fundamental): Sharpe=0.44, Fitness=0.21, TO=0.0176, DD=0.226。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_comp, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_chq, 120)),densify(pv13_...`
- **JjGVEW6n** (UNSUBMITTED, fundamental): Sharpe=0.44, Fitness=0.23, TO=0.0115, DD=0.1912。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_comp, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_chq, 120)),densify(pv13_...`
- **6XpnVo5P** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.2, TO=0.0153, DD=0.2202。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_comp, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newqv1300_chq, 120)),densify(pv13_...`

---


### 2026-08-02 07:22 UTC

- **j265YR3W** (UNSUBMITTED, technical): Sharpe=-0.03, Fitness=-0.0, TO=0.0085, DD=0.3557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_term_sector_total,5),3),0.85),`
- **1YpqjAkk** (UNSUBMITTED, technical): Sharpe=-0.06, Fitness=-0.01, TO=0.0094, DD=0.3209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_term_sector_total,5),3),0.85),`
- **rK21dNa3** (UNSUBMITTED, technical): Sharpe=-0.08, Fitness=-0.02, TO=0.0081, DD=0.4561。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,pv13_revere_term_sector_total,5),3),0.85),`
- **mL5PYg9X** (UNSUBMITTED, technical): Sharpe=-0.19, Fitness=-0.04, TO=0.0075, DD=0.1551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(goodwill_accounting_adjustments, 120)...`
- **E5GZVl71** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.01, TO=0.017, DD=0.2336。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_all, 60) > 2, group_zscore(-inverse(ts_backfill(doubtful_accounts_provision, 120)),densi...`
- **58pZj6Ro** (UNSUBMITTED, technical): Sharpe=-0.05, Fitness=-0.01, TO=0.0094, DD=0.1844。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(goodwill_accounting_adjustments, 120)...`
- **58pZjox6** (UNSUBMITTED, technical): Sharpe=-0.29, Fitness=-0.08, TO=0.0086, DD=0.1661。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_com_rk_au, 60) > 2, group_zscore(-inverse(ts_backfill(goodwill_accounting_adjustments, 120)...`
- **d5Z2KVOw** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.03, TO=0.0191, DD=0.2106。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_all, 60) > 2, group_zscore(-inverse(ts_backfill(doubtful_accounts_provision, 120)),densi...`
- **ZYERAN7Q** (UNSUBMITTED, technical): Sharpe=0.05, Fitness=0.01, TO=0.0142, DD=0.2203。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_all, 60) > 2, group_zscore(-inverse(ts_backfill(doubtful_accounts_provision, 120)),densi...`
- **E5GZRm0R** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.09, TO=0.0121, DD=0.3546。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_revere_country,5),3),0.85),`
- **N1bXVPzp** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.07, TO=0.0145, DD=0.3763。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_revere_country,5),3),0.85),`
- **blQYOWnR** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.07, TO=0.0167, DD=0.3443。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_country,pv13_revere_country,5),3),0.85),`
- **1YpqZ51Q** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.06, TO=0.0205, DD=0.0671。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_parent,5),3),0.85),`
- **LLGPNQA9** (UNSUBMITTED, technical): Sharpe=0.72, Fitness=0.27, TO=0.0358, DD=0.0658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_parent,5),3),0.85),`
- **LLGPN3Ga** (UNSUBMITTED, technical): Sharpe=0.39, Fitness=0.12, TO=0.0237, DD=0.0583。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_parent,pv13_revere_parent,5),3),0.85),`
- **78zkNzzO** (UNSUBMITTED, analyst): Sharpe=2.71, Fitness=2.5, TO=0.6321, DD=0.0147。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_country, vwap, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances_advanced...`
- **e73lbxEl** (UNSUBMITTED, analyst): Sharpe=2.38, Fitness=1.56, TO=0.8019, DD=0.0193。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_country, vwap, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances_advanced...`
- **omN1LQl6** (UNSUBMITTED, analyst): Sharpe=2.24, Fitness=1.89, TO=0.676, DD=0.0147。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_country, vwap, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_guidances_advanced...`
- **zqNv8zLG** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.01, TO=0.3636, DD=0.1752。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_custretsig_retsig, rel_ret_cust, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_detail_...`
- **QPG1bX8X** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.02, TO=0.4116, DD=0.1086。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(open, adv20, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_detail_estimates_advanced_af_nd_...`
- **MPGj1rx8** (UNSUBMITTED, analyst): Sharpe=-0.05, Fitness=-0.01, TO=0.3597, DD=0.2485。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_custretsig_retsig, rel_ret_cust, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_detail_...`
- **P0GJZeZx** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.17, TO=0.0104, DD=0.8258。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_num_cust,5),3),0.85),`
- **pwNqj9Ex** (UNSUBMITTED, analyst): Sharpe=0.16, Fitness=0.09, TO=0.0068, DD=0.598。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_num_cust,5),3),0.85),`
- **vRNKjbqG** (UNSUBMITTED, analyst): Sharpe=-0.28, Fitness=-0.25, TO=0.0074, DD=1.2888。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_reveremap,rel_num_cust,5),3),0.85),`
- **58pZl7No** (UNSUBMITTED, analyst): Sharpe=-0.17, Fitness=-0.07, TO=0.0453, DD=0.6102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,dividend,5),3),0.85),`
- **e73lz8p6** (UNSUBMITTED, analyst): Sharpe=-0.23, Fitness=-0.12, TO=0.0366, DD=0.6392。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,dividend,5),3),0.85),`
- **VkGv7okV** (UNSUBMITTED, analyst): Sharpe=-0.12, Fitness=-0.04, TO=0.0412, DD=0.6366。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,dividend,5),3),0.85),`
- **2rp1pxE6** (UNSUBMITTED, analyst): Sharpe=0.02, Fitness=0.0, TO=0.0095, DD=0.2607。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_num_part,5),3),0.85),`
- **P0GJG58W** (UNSUBMITTED, analyst): Sharpe=-0.01, Fitness=-0.0, TO=0.0119, DD=0.305。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,high,5),3),0.85),`
- **78zkzKrv** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.11, TO=0.0113, DD=0.3329。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,high,5),3),0.85),`
- **A1GRGMNR** (UNSUBMITTED, analyst): Sharpe=-0.06, Fitness=-0.02, TO=0.03, DD=0.6742。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_zipcode,dividend,5),3),0.85),`
- **d5Z2Zkbv** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.03, TO=0.0101, DD=0.1995。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_num_part,5),3),0.85),`
- **A1GRGRqw** (UNSUBMITTED, analyst): Sharpe=3.81, Fitness=6.94, TO=0.75, DD=0.0487。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **1YpqzONm** (UNSUBMITTED, analyst): Sharpe=0.19, Fitness=0.07, TO=0.0121, DD=0.1692。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,high,5),3),0.85),`
- **LLGPdZde** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.009, DD=0.1963。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_num_part,5),3),0.85),`
- **0mpbEZJv** (UNSUBMITTED, analyst): Sharpe=3.23, Fitness=4.21, TO=0.6667, DD=0.0134。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **e73l0ZKO** (UNSUBMITTED, analyst): Sharpe=-24.84, Fitness=-45.45, TO=0.6667, DD=0.0119。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **58pZOEOz** (UNSUBMITTED, analyst): Sharpe=-0.15, Fitness=-0.05, TO=0.0376, DD=0.1892。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **ak1rnK3W** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.05, DD=0.1361。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_mean / pv13_com_page_rank, 126), pv13_hierarchy_min30_...`
- **0mpbEAEK** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.11, TO=0.0416, DD=0.152。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_netdebt_high / rel_num_comp, 126), pv13_hierarchy23_sector)`
- **1YpqdvPJ** (UNSUBMITTED, analyst): Sharpe=0.5, Fitness=0.19, TO=0.0476, DD=0.1284。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_netdebt_high / rel_num_comp, 126), pv13_hierarchy23_sector)`
- **0mpbEWa6** (UNSUBMITTED, analyst): Sharpe=-0.0, Fitness=-0.0, TO=0.0591, DD=0.0843。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_mean / pv13_com_page_rank, 126), pv13_hierarchy_min30_...`
- **ZYERpVj1** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.05, TO=0.0594, DD=0.1077。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_guidances_advanced_qf_nd_shrb_minguidance / rel_num_comp, 126), pv13_hierarchy_min20_513_s...`
- **qMNKA301** (UNSUBMITTED, analyst): Sharpe=0.18, Fitness=0.04, TO=0.0566, DD=0.1104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_guidances_advanced_qf_nd_shrb_minguidance / rel_num_comp, 126), pv13_hierarchy_min20_513_s...`
- **gJ8Y1Xbg** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0727, DD=0.078。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_mean / pv13_com_page_rank, 126), pv13_hierarchy_min30_...`
- **88pmzvNm** (UNSUBMITTED, analyst): Sharpe=-0.01, Fitness=-0.0, TO=0.0719, DD=0.0833。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_mean / pv13_com_page_rank, 126), pv13_hierarchy_min30_...`
- **gJ8Y1KM0** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.12, TO=0.0364, DD=0.1038。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_netdebt_high / rel_num_comp, 126), pv13_hierarchy23_sector)`
- **XgojKvr5** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_comp,pv13_revere_company_total,5),3),0.85),`
- **vRNKmAZa** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_comp,pv13_revere_company_total,5),3),0.85),`
- **npN135wz** (UNSUBMITTED, fundamental): Sharpe=2.94, Fitness=3.76, TO=0.1395, DD=0.0063。高 Fitness 低换手，优秀候选；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **xANKR2dn** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_comp,pv13_revere_company_total,5),3),0.85),`
- **RRmJd58z** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.17, TO=0.0145, DD=0.2205。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(vwap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_dp, 120)),densify(pv13_hierarch...`
- **npN13dRx** (UNSUBMITTED, fundamental): Sharpe=0.37, Fitness=0.17, TO=0.0162, DD=0.1698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(vwap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_dp, 120)),densify(pv13_hierarch...`
- **YPvjQm3v** (UNSUBMITTED, fundamental): Sharpe=0.09, Fitness=0.02, TO=0.0433, DD=0.0804。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **mL5PZ3vK** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.19, TO=0.0127, DD=0.2239。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(vwap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_dp, 120)),densify(pv13_hierarch...`
- **QPG1n6WM** (UNSUBMITTED, fundamental): Sharpe=-4.3, Fitness=-5.22, TO=1.0, DD=0.0。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`

---


### 2026-08-02 10:25 UTC

- **YPvP6Jjw** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **gJ8J6Kvl** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.2, TO=0.1805, DD=0.0953。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_term / rel_ret_all - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_q /...`
- **78z8WOxQ** (UNSUBMITTED, technical): Sharpe=0.32, Fitness=0.12, TO=0.1725, DD=0.1606。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_term / rel_ret_all - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_q /...`
- **blQlGe1l** (UNSUBMITTED, technical): Sharpe=0.47, Fitness=0.19, TO=0.1764, DD=0.0948。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_term / rel_ret_all - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_q /...`
- **zqNqKLaV** (UNSUBMITTED, technical): Sharpe=0.28, Fitness=0.05, TO=0.628, DD=0.1125。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_term / rel_ret_all - 1)) + 0.5 * rank(ts_rank(fn_accum_oth_income_loss_fx_adj_net_of_tax_q /...`
- **9qpqZpwx** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.12, TO=0.0191, DD=0.2196。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,cap,5),3),0.85),`
- **A1G1jqAw** (UNSUBMITTED, technical): Sharpe=0.17, Fitness=0.06, TO=0.0157, DD=0.3771。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,cap,5),3),0.85),`
- **KPGPlP2N** (UNSUBMITTED, technical): Sharpe=0.17, Fitness=0.06, TO=0.0177, DD=0.3286。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,cap,5),3),0.85),`
- **VkGkke55** (UNSUBMITTED, technical): Sharpe=0.64, Fitness=0.48, TO=0.0127, DD=0.4153。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **QPGPPXeQ** (UNSUBMITTED, technical): Sharpe=0.09, Fitness=0.02, TO=0.0126, DD=0.393。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(cap,cap,5),3),0.85),`
- **ak1kkq71** (UNSUBMITTED, technical): Sharpe=0.65, Fitness=0.5, TO=0.0106, DD=0.4178。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **58p8Z2R5** (UNSUBMITTED, technical): Sharpe=-0.13, Fitness=-0.03, TO=0.0125, DD=0.1694。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_cust, 60) > 2, group_zscore(-inverse(ts_backfill(db_plan_actuarial_gain_loss, 120)),dens...`
- **ak1krKZW** (UNSUBMITTED, technical): Sharpe=0.01, Fitness=0.0, TO=0.0151, DD=0.2131。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_cust, 60) > 2, group_zscore(-inverse(ts_backfill(db_plan_actuarial_gain_loss, 120)),dens...`
- **JjGjVvJm** (UNSUBMITTED, technical): Sharpe=-0.1, Fitness=-0.02, TO=0.0151, DD=0.1568。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_ret_cust, 60) > 2, group_zscore(-inverse(ts_backfill(db_plan_actuarial_gain_loss, 120)),dens...`
- **d5Z52xbv** (UNSUBMITTED, technical): Sharpe=0.76, Fitness=0.4, TO=0.0179, DD=0.0636。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(open, 60) > 2, group_zscore(-inverse(ts_backfill(debt_unamortized_discount_premium_net_value, 12...`
- **YPvPjqWw** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.11, TO=0.6426, DD=0.0849。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_low / rel_ret_all, 126), pv13_hierarchy_min51_f4_513_s...`
- **JjGjVEmm** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=0.36, TO=0.0193, DD=0.0889。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(open, 60) > 2, group_zscore(-inverse(ts_backfill(debt_unamortized_discount_premium_net_value, 12...`
- **kqPxzzrz** (UNSUBMITTED, analyst): Sharpe=0.27, Fitness=0.05, TO=0.5186, DD=0.1042。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_advanced_af_nd_cff_low / rel_ret_all, 126), pv13_hierarchy_min51_f4_513_s...`
- **GrGqZjWZ** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.0179, DD=0.349。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_city,pv13_revere_term_sector_total,5),3),0.85),`
- **58pZPQaX** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.09, TO=0.0337, DD=0.616。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_all,5),3),0.85),`
- **leWLo0zx** (UNSUBMITTED, analyst): Sharpe=-0.41, Fitness=-0.36, TO=0.0469, DD=1.2144。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_all,5),3),0.85),`
- **QPG1w22r** (UNSUBMITTED, analyst): Sharpe=0.09, Fitness=0.02, TO=0.0121, DD=0.33。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_city,pv13_revere_term_sector_total,5),3),0.85),`
- **Xgojd6rb** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.05, TO=0.016, DD=0.3378。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_city,pv13_revere_term_sector_total,5),3),0.85),`
- **RRmJgGpg** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.05, TO=0.0408, DD=0.5949。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_all,5),3),0.85),`
- **9qpznq2o** (UNSUBMITTED, analyst): Sharpe=-0.04, Fitness=-0.01, TO=0.0756, DD=0.0968。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_rk_au,pv13_com_rk_au,5),3),0.85),`
- **9qpznq89** (UNSUBMITTED, analyst): Sharpe=0.48, Fitness=0.25, TO=0.0685, DD=0.0575。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_rk_au,pv13_com_rk_au,5),3),0.85),`
- **gJ8YlPkm** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.13, TO=0.0717, DD=0.073。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_rk_au,pv13_com_rk_au,5),3),0.85),`
- **E5GZj37P** (UNSUBMITTED, analyst): Sharpe=0.34, Fitness=0.19, TO=0.0097, DD=0.5221。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_comp,rel_ret_comp,5),3),0.85),`
- **KPGKodoN** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.0, TO=0.0883, DD=0.0859。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_rk_au,pv13_com_rk_au,5),3),0.85),`
- **xANK77Ow** (UNSUBMITTED, analyst): Sharpe=-0.43, Fitness=-0.25, TO=0.0218, DD=0.6345。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **MPGjvLVa** (UNSUBMITTED, analyst): Sharpe=-24.84, Fitness=-45.45, TO=0.6667, DD=0.0119。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **LLGPode2** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.0286, DD=0.3416。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **N1bXEAP8** (UNSUBMITTED, analyst): Sharpe=0.39, Fitness=0.21, TO=0.0127, DD=0.408。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_ret_comp,rel_ret_comp,5),3),0.85),`
- **npN1GwmE** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.0326, DD=0.3309。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **88pmWorV** (UNSUBMITTED, fundamental): Sharpe=0.19, Fitness=0.04, TO=0.0412, DD=0.1075。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(cash_flow_from_operations / pv13_ustomergraphrank_hub_rank, 126), pv13_hierarchy_min30_3000_mapped...`
- **xANK7KmN** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.06, TO=0.0541, DD=0.0942。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(cash_flow_from_operations / pv13_ustomergraphrank_hub_rank, 126), pv13_hierarchy_min30_3000_mapped...`
- **E5GZP2V9** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.06, TO=0.0353, DD=0.0704。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(cash_flow_from_operations / pv13_ustomergraphrank_hub_rank, 126), pv13_hierarchy_min30_3000_mapped...`
- **zqNvnG6o** (UNSUBMITTED, fundamental): Sharpe=0.82, Fitness=0.37, TO=0.1371, DD=0.0945。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(min_gross_income_guidance_2 / pv13_revere_index_value, 126), pv13_rha2_min5_1000_513_sector)`
- **VkGvbxr0** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.1, TO=0.0223, DD=0.1988。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(primary_sector_focused_company_count / pv13_revere_term_sector_total - 1)) + 0.5 * rank(ts_rank(fnd2_a_p...`
- **LLGPY7LL** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.46, TO=0.0397, DD=0.3642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(deferred_...`
- **omN10nPb** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.18, TO=0.0459, DD=0.3496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(deferred_...`
- **E5GZPX1r** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.1, TO=0.0314, DD=0.2578。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.5 * rank(-(pv13_revere_key_sector_total / single_sector_pureplay_company_count - 1)) + 0.5 * rank(ts_rank(deferred_...`
- **d5Z26RrJ** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,pv13_revere_zipcode,5),3),0.85),`
- **1Ypq2wpQ** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,pv13_revere_zipcode,5),3),0.85),`
- **XgojOo58** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,pv13_revere_zipcode,5),3),0.85),`
- **ak1rgPpW** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_auth_rank,pv13_revere_zipcode,5),3),0.85),`
- **QPG16ER5** (UNSUBMITTED, fundamental): Sharpe=8.48, Fitness=15.46, TO=1.0, DD=0.0。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **A1GREnQl** (UNSUBMITTED, fundamental): Sharpe=-0.02, Fitness=-0.0, TO=0.0064, DD=0.4124。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **VkGve28Y** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **d5Z2oRKY** (UNSUBMITTED, fundamental): Sharpe=0.09, Fitness=0.02, TO=0.0099, DD=0.2893。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **leWL9QqA** (UNSUBMITTED, fundamental): Sharpe=0.06, Fitness=0.01, TO=0.0077, DD=0.349。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **VkGv5wz8** (UNSUBMITTED, fundamental): Sharpe=0.06, Fitness=0.01, TO=0.0089, DD=0.31。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,pv13_com_page_rank,5),3),0.85),`
- **O0G1Vv7Y** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_key_sector_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_invt, 1...`
- **vRNK6Mlb** (UNSUBMITTED, fundamental): Sharpe=-2.47, Fitness=-6.92, TO=0.0192, DD=0.285。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_key_sector_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_invt, 1...`
- **d5Z2oVAg** (UNSUBMITTED, fundamental): Sharpe=-2.47, Fitness=-6.92, TO=0.0192, DD=0.285。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_revere_key_sector_total, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_newa1v1300_invt, 1...`

---


### 2026-08-02 11:07 UTC

- **1YpY6ZGW** (UNSUBMITTED, fundamental): Sharpe=6.1, Fitness=7.43, TO=1.0, DD=0.0。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **58p8NNQM** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.17, TO=0.0297, DD=0.2538。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **0mpmnlpp** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.1, TO=0.0195, DD=0.3542。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **pwNw0kex** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.12, TO=0.0225, DD=0.3473。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **ZYEYZGwj** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ompetitorgraphrank_hub_rank,pv13_ompetitorgraphrank_hub_rank,5),3),0.85),`
- **KPGPRoE1** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.17, TO=0.0297, DD=0.2298。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_page_rank,pv13_ustomergraphrank_page_rank,5),3),0.85),`
- **ak1k3PQv** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_term_sector_total,pv13_revere_term_sector_total,5),3),0.85),`
- **zqNqpxl8** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_term_sector_total,pv13_revere_term_sector_total,5),3),0.85),`
- **d5Z5LMMx** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_term_sector_total,pv13_revere_term_sector_total,5),3),0.85),`

---


### 2026-08-02 13:05 UTC

- **E5G5wjzL** (UNSUBMITTED, technical): Sharpe=-0.21, Fitness=-0.08, TO=0.007, DD=0.5933。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **LLGLpKdn** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.01, TO=0.0102, DD=0.2578。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **j262ZApW** (UNSUBMITTED, technical): Sharpe=-0.0, Fitness=-0.0, TO=0.0112, DD=0.3112。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(fn_business_combination_purchase_price_...`
- **xANAx99g** (UNSUBMITTED, technical): Sharpe=0.11, Fitness=0.02, TO=0.0125, DD=0.2493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(fn_business_combination_purchase_price_...`
- **YPvPpPXw** (UNSUBMITTED, technical): Sharpe=-0.1, Fitness=-0.02, TO=0.0091, DD=0.3338。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(rel_num_part, 60) > 2, group_zscore(-inverse(ts_backfill(fn_business_combination_purchase_price_...`
- **leWe0wmn** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.09, TO=0.0583, DD=0.0429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(financing_cashflow_reported_value / pv13_reveremap, 126), pv13_hierarchy23_513_sector)`
- **3qpqA5oe** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.03, TO=0.0392, DD=0.0995。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(financing_cashflow_reported_value / pv13_reveremap, 126), pv13_hierarchy23_513_sector)`
- **omNmYWel** (UNSUBMITTED, technical): Sharpe=0.2, Fitness=0.04, TO=0.0457, DD=0.056。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(financing_cashflow_reported_value / pv13_reveremap, 126), pv13_hierarchy23_513_sector)`
- **78z8dNE5** (UNSUBMITTED, analyst): Sharpe=-0.26, Fitness=-0.17, TO=0.0445, DD=0.6988。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),3),0....`
- **QPGPQQ2G** (UNSUBMITTED, analyst): Sharpe=0.12, Fitness=0.03, TO=0.0092, DD=0.3279。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **N1b1OW6w** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.04, TO=0.0109, DD=0.2398。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **qMNMXe71** (UNSUBMITTED, analyst): Sharpe=-0.09, Fitness=-0.04, TO=0.0328, DD=0.7927。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),3),0....`
- **LLGLkvge** (UNSUBMITTED, analyst): Sharpe=-0.54, Fitness=-0.56, TO=0.045, DD=1.4968。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),3),0....`
- **LLGLk1J6** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.1, TO=0.0123, DD=0.3469。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_level,pv13_revere_level,5),3),0.85),`
- **gJ8Jxmle** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.0, TO=0.0058, DD=0.4208。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **rK2KAb3m** (UNSUBMITTED, analyst): Sharpe=0.62, Fitness=0.47, TO=0.0118, DD=0.4232。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **KPGPk3Yx** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.12, TO=0.0128, DD=0.3415。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_level,pv13_revere_level,5),3),0.85),`
- **3qpqzMxX** (UNSUBMITTED, analyst): Sharpe=0.2, Fitness=0.08, TO=0.011, DD=0.3785。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_level,pv13_revere_level,5),3),0.85),`
- **vRNR5lg3** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_term_sector_total, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfi...`
- **omNmnV26** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.03, TO=0.0073, DD=0.3372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **vRNR59gb** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_term_sector_total, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfi...`
- **kqPqnEAP** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.09, TO=0.2128, DD=0.3461。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank, sharesout, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_de...`
- **1YpYoqmQ** (UNSUBMITTED, analyst): Sharpe=0.34, Fitness=0.12, TO=0.195, DD=0.179。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank, sharesout, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_de...`
- **QPGP28XW** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.4266, DD=0.0917。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(rel_ret_all, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_cfo_flag, ...`
- **xANAPoEg** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_revere_term_sector_total, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfi...`
- **E5G5gvNL** (UNSUBMITTED, analyst): Sharpe=0.09, Fitness=0.01, TO=0.3297, DD=0.0941。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(rel_ret_all, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_cfo_flag, ...`
- **QPGP29WX** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.07, TO=0.3316, DD=0.0823。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(rel_ret_all, pv13_revere_index_value, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_cfo_flag, ...`
- **omNm313k** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.03, TO=0.6479, DD=0.0873。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_capex_value / rel_ret_all, 126), pv13_hierarchy_min20_sector)`
- **6XpXY5QJ** (UNSUBMITTED, analyst): Sharpe=0.45, Fitness=0.19, TO=0.2108, DD=0.2336。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank, sharesout, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_de...`
- **2rprn9kZ** (UNSUBMITTED, analyst): Sharpe=0.54, Fitness=0.21, TO=0.0442, DD=0.1155。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_basic_qf_v4_nd_cfps_low / rel_num_part, 126), pv13_h_min5_3000_sector)`
- **N1b15Nq8** (UNSUBMITTED, analyst): Sharpe=0.29, Fitness=0.1, TO=0.1811, DD=0.1582。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank, sharesout, 5), 3) * group_zscore(log(winsorize(ts_backfill(anl4_fs_de...`
- **E5G5rlW9** (UNSUBMITTED, analyst): Sharpe=0.38, Fitness=0.07, TO=0.5602, DD=0.1188。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_capex_value / rel_ret_all, 126), pv13_hierarchy_min20_sector)`
- **rK2KrllE** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.28, TO=0.0307, DD=0.1399。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_basic_qf_v4_nd_cfps_low / rel_num_part, 126), pv13_h_min5_3000_sector)`
- **VkGkYEEw** (UNSUBMITTED, analyst): Sharpe=0.39, Fitness=0.07, TO=0.4918, DD=0.1289。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_capex_value / rel_ret_all, 126), pv13_hierarchy_min20_sector)`
- **O0G05Eb7** (UNSUBMITTED, analyst): Sharpe=0.5, Fitness=0.22, TO=0.0261, DD=0.1513。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(anl4_fs_detail_estimates_basic_qf_v4_nd_cfps_low / rel_num_part, 126), pv13_h_min5_3000_sector)`
- **3qpq61k0** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.11, TO=0.1414, DD=0.3656。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **zqNqo87X** (UNSUBMITTED, analyst): Sharpe=-0.03, Fitness=-0.01, TO=0.1603, DD=0.7482。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **9qpq6Pzd** (UNSUBMITTED, analyst): Sharpe=0.35, Fitness=0.2, TO=0.008, DD=0.4786。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_revere_company_total,5),3),0.85),`
- **E5G5aAYJ** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.14, TO=0.0066, DD=0.6044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_revere_company_total,5),3),0.85),`
- **78z8QrKx** (UNSUBMITTED, analyst): Sharpe=0.42, Fitness=0.24, TO=0.0103, DD=0.3658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_revere_company_total,pv13_revere_company_total,5),3),0.85),`
- **RRmRYPxg** (UNSUBMITTED, fundamental): Sharpe=0.02, Fitness=0.0, TO=0.0097, DD=0.1419。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(low, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd, 120)),densify(pv13_hierarchy_min5_f3g2_...`
- **zqNqjgZ1** (UNSUBMITTED, analyst): Sharpe=0.1, Fitness=0.03, TO=0.1612, DD=0.2764。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(pv13_ustomergraphrank_hub_rank,pv13_ustomergraphrank_hub_rank,5),3),0.85),`
- **d5Z5mbpJ** (UNSUBMITTED, fundamental): Sharpe=0.55, Fitness=0.8, TO=0.0038, DD=1.4543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_reveremap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ivstch, 120)),densify(pv13_h_min...`
- **zqNqjPXd** (UNSUBMITTED, fundamental): Sharpe=-0.06, Fitness=-0.02, TO=0.0035, DD=1.0837。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_reveremap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ivstch, 120)),densify(pv13_h_min...`
- **e737KAjl** (UNSUBMITTED, fundamental): Sharpe=-0.22, Fitness=-0.17, TO=0.0027, DD=1.4591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(pv13_reveremap, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_ivstch, 120)),densify(pv13_h_min...`
- **9qpqbMZx** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.04, TO=0.0115, DD=0.1543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(low, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd, 120)),densify(pv13_hierarchy_min5_f3g2_...`
- **LLGLqKbM** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0132, DD=0.1936。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(ts_zscore(low, 60) > 2, group_zscore(-inverse(ts_backfill(fnd6_dd, 120)),densify(pv13_hierarchy_min5_f3g2_...`
- **zqNqQbQd** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **wpapOOWx** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **KPGPqq5E** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **KPGPYpWg** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`

---


### 2026-08-02 13:39 UTC

- **vRNRNPea** (UNSUBMITTED, fundamental): Sharpe=0.17, Fitness=0.06, TO=0.0099, DD=0.3223。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **ZYEYEmKY** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.08, TO=0.0207, DD=0.2747。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **2rprpw8N** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.22, TO=0.0097, DD=0.4004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **d5Z5Zk82** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.13, TO=0.0087, DD=0.3423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **0mpmMLEp** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.12, TO=0.0184, DD=0.2623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **xANAdebJ** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.21, TO=0.0132, DD=0.219。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **78z8nKp8** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.17, TO=0.0153, DD=0.2194。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **ZYEYKLGZ** (UNSUBMITTED, fundamental): Sharpe=0.8, Fitness=0.19, TO=0.5009, DD=0.0731。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / rel_ret_part, 126), currency)`
- **58p8kZb1** (UNSUBMITTED, fundamental): Sharpe=0.2, Fitness=0.06, TO=0.0104, DD=0.3266。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **vRNRl1QQ** (UNSUBMITTED, fundamental): Sharpe=-0.2, Fitness=-0.05, TO=0.1263, DD=0.1118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(gross_income_avg / volume, 126), exchange)`
- **npNp2Pz8** (UNSUBMITTED, fundamental): Sharpe=-0.22, Fitness=-0.03, TO=0.4521, DD=0.1217。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(gross_income_avg / volume, 126), exchange)`
- **kqPq0glg** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.52, TO=0.3939, DD=0.6794。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / rel_ret_part, 126), currency)`
- **LLGL1pXL** (UNSUBMITTED, fundamental): Sharpe=0.85, Fitness=0.18, TO=0.5621, DD=0.0612。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / rel_ret_part, 126), currency)`
- **88p8Qb9z** (UNSUBMITTED, technical): Sharpe=-0.05, Fitness=-0.01, TO=0.0087, DD=0.3818。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`

---


### 2026-08-02 14:18 UTC

- **0mpmrd7q** (UNSUBMITTED, analyst): Sharpe=0.47, Fitness=0.2, TO=0.0066, DD=0.1672。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **LLGLZ6X2** (UNSUBMITTED, analyst): Sharpe=0.27, Fitness=0.08, TO=0.008, DD=0.1604。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **MPGPaVPr** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.12, TO=0.0086, DD=0.1118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **GrGrbQvG** (UNSUBMITTED, fundamental): Sharpe=0.54, Fitness=0.31, TO=0.1338, DD=0.1493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **78z8NYm1** (UNSUBMITTED, fundamental): Sharpe=0.19, Fitness=0.07, TO=0.0085, DD=0.4048。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **9qpqjQax** (UNSUBMITTED, fundamental): Sharpe=0.8, Fitness=0.5, TO=0.1358, DD=0.1023。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **gJ8JQKoe** (UNSUBMITTED, fundamental): Sharpe=0.01, Fitness=0.0, TO=0.0182, DD=0.4139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **xANAYMjN** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.19, TO=0.0115, DD=0.3567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **d5Z5Ow6K** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.06, TO=0.0061, DD=0.5428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **vRNRjjdr** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0207, DD=0.2814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **9qpqXr0K** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.14, TO=0.0074, DD=0.5687。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **A1G1lPjl** (UNSUBMITTED, fundamental): Sharpe=0.35, Fitness=0.19, TO=0.009, DD=0.4665。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`

---


### 2026-08-02 14:29 UTC

- **blQl8NVm** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.22, TO=0.0093, DD=0.4484。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **qMNMEP9A** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.16, TO=0.0066, DD=0.4649。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **omNmo1R6** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.05, TO=0.3744, DD=0.1296。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_income_adjusted / rel_ret_cust, 126), market)`
- **rK2Kd1v8** (UNSUBMITTED, fundamental): Sharpe=0.58, Fitness=0.22, TO=0.0722, DD=0.0945。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_income_adjusted / rel_ret_cust, 126), market)`
- **vRNR2bgQ** (UNSUBMITTED, fundamental): Sharpe=0.35, Fitness=0.07, TO=0.3258, DD=0.0691。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_income_adjusted / rel_ret_cust, 126), market)`
- **LLGLZMvM** (UNSUBMITTED, analyst): Sharpe=-0.01, Fitness=-0.0, TO=0.0053, DD=0.3701。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`

---


### 2026-08-02 15:21 UTC

- **vRNRp30w** (UNSUBMITTED, analyst): Sharpe=0.57, Fitness=0.28, TO=0.0455, DD=0.1044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ebitda / adjfactor, 126), sector)`
- **MPGPdG8z** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.16, TO=0.006, DD=0.3809。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **pwNwW98v** (UNSUBMITTED, analyst): Sharpe=0.2, Fitness=0.07, TO=0.0116, DD=0.3079。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **GrGrQ2OJ** (UNSUBMITTED, analyst): Sharpe=0.39, Fitness=0.2, TO=0.0089, DD=0.3372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **mL5LK7l6** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.17, TO=0.0074, DD=0.4003。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **N1b1KQ5w** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.06, TO=0.0087, DD=0.366。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **E5G5QV1R** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.09, TO=0.009, DD=0.2424。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **vRNRAr7r** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.05, TO=0.0109, DD=0.281。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **9qpql7Ad** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.04, TO=0.0128, DD=0.2866。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **mL5LaJNx** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0294, DD=0.5053。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **blQla7d6** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0311, DD=0.3427。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **9qpqxMex** (UNSUBMITTED, analyst): Sharpe=-0.05, Fitness=-0.01, TO=0.0243, DD=0.6347。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **P0G0o2gJ** (UNSUBMITTED, analyst): Sharpe=0.17, Fitness=0.04, TO=0.0143, DD=0.2525。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **A1G1VqVl** (UNSUBMITTED, fundamental): Sharpe=0.5, Fitness=0.16, TO=0.0237, DD=0.0423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **1YpYN6pM** (UNSUBMITTED, fundamental): Sharpe=0.96, Fitness=0.39, TO=0.0324, DD=0.0307。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **GrGrWJlQ** (UNSUBMITTED, fundamental): Sharpe=0.95, Fitness=0.58, TO=0.1398, DD=0.0942。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **1YpYjZYX** (UNSUBMITTED, fundamental): Sharpe=0.48, Fitness=0.29, TO=0.0102, DD=0.356。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`

---


### 2026-08-02 17:21 UTC

- **qMNM2vpP** (UNSUBMITTED, technical): Sharpe=0.78, Fitness=0.44, TO=0.2362, DD=0.2918。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_decay_linear(close / vwap, 10))) + 0.50*(rank(-ts_std_dev(returns, 20)))`
- **e737Mgl6** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=0.61, TO=0.3485, DD=0.1223。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)) + 0.50*(rank(volume / adv20))`
- **omNmjOnk** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.13, TO=0.0836, DD=0.6975。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **blQl0kWM** (UNSUBMITTED, technical): Sharpe=0.81, Fitness=0.34, TO=0.3466, DD=0.1003。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_mean(returns, 33))) + 0.50*(rank(volume / adv20))`
- **leWeweJ5** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.13, TO=0.0682, DD=0.7738。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **O0G0XdXb** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.13, TO=0.0805, DD=0.6701。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **npNp5qYx** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **ak1k9zY6** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **omNm0oZE** (UNSUBMITTED, technical): Sharpe=0.77, Fitness=0.21, TO=0.4912, DD=0.1601。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **rK2KMJaa** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=0.6, TO=0.415, DD=0.1643。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **WjAj2aEk** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.19, TO=0.4943, DD=0.1418。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **xANApXop** (UNSUBMITTED, technical): Sharpe=1.28, Fitness=0.74, TO=0.2839, DD=0.0861。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **qMNMJqAE** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=0.72, TO=0.281, DD=0.1257。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **P0G0mQYw** (UNSUBMITTED, technical): Sharpe=1.29, Fitness=0.73, TO=0.419, DD=0.1221。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **E5G5MnX1** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.23, TO=0.1212, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **1YpYRRjk** (UNSUBMITTED, technical): Sharpe=0.48, Fitness=0.29, TO=0.0736, DD=0.138。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **58p812pz** (UNSUBMITTED, technical): Sharpe=1.58, Fitness=0.78, TO=0.3803, DD=0.0884。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **GrGrNd60** (UNSUBMITTED, technical): Sharpe=2.03, Fitness=0.78, TO=0.8341, DD=0.0868。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **gJ8J5jdm** (UNSUBMITTED, technical): Sharpe=1.71, Fitness=0.72, TO=0.845, DD=0.0853。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **88p8ZK8X** (UNSUBMITTED, technical): Sharpe=0.56, Fitness=0.37, TO=0.129, DD=0.1559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **E5G5M71K** (UNSUBMITTED, technical): Sharpe=1.94, Fitness=0.82, TO=0.6094, DD=0.0599。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **E5G52MAr** (UNSUBMITTED, technical): Sharpe=0.28, Fitness=0.13, TO=0.0109, DD=0.4371。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **78z82lkv** (UNSUBMITTED, technical): Sharpe=0.38, Fitness=0.17, TO=0.0164, DD=0.1836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **1YpY2e9k** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.04, TO=0.0107, DD=0.3174。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **WjAjxjXj** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.09, TO=0.0091, DD=0.5565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **A1G1EXve** (UNSUBMITTED, technical): Sharpe=0.29, Fitness=0.12, TO=0.015, DD=0.2368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **RRmRP69g** (UNSUBMITTED, technical): Sharpe=0.06, Fitness=0.01, TO=0.0074, DD=0.7604。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **3qpqJgWz** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.16, TO=0.0148, DD=0.1888。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **JjGjrM2A** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.0132, DD=0.2803。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **vRNR61da** (UNSUBMITTED, technical): Sharpe=0.1, Fitness=0.03, TO=0.0341, DD=0.3903。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **6XpXJrjG** (UNSUBMITTED, technical): Sharpe=0.32, Fitness=0.14, TO=0.0151, DD=0.2369。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **xANAWdmw** (UNSUBMITTED, technical): Sharpe=0.16, Fitness=0.05, TO=0.0327, DD=0.3361。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **JjGj1gzl** (UNSUBMITTED, analyst): Sharpe=0.04, Fitness=0.01, TO=0.0042, DD=0.463。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **O0G0VaJ7** (UNSUBMITTED, analyst): Sharpe=0.06, Fitness=0.01, TO=0.0052, DD=0.4559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **JjGj1K5m** (UNSUBMITTED, analyst): Sharpe=0.06, Fitness=0.01, TO=0.0062, DD=0.3795。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **MPGPZPN6** (UNSUBMITTED, analyst): Sharpe=0.1, Fitness=0.02, TO=0.0065, DD=0.3182。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **leWeGNJn** (UNSUBMITTED, fundamental): Sharpe=0.94, Fitness=0.5, TO=0.1633, DD=0.095。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **0mpmg6Z1** (UNSUBMITTED, fundamental): Sharpe=1.92, Fitness=0.91, TO=0.4348, DD=0.0854。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.40*(rank((high + low) / 2 - close)) + 0.40*(rank(-ts_zscore(enterprise_value / ebitda, 63))) + 0.20*(rank(volume / ...`
- **blQlzz8q** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.24, TO=0.1409, DD=0.2957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_std_dev(returns, 20))) + 0.50*(rank(-ts_zscore(enterprise_value / ebitda, 63)))`
- **6XpX0dAK** (UNSUBMITTED, fundamental): Sharpe=1.81, Fitness=0.85, TO=0.428, DD=0.0757。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank((high + low) / 2 - close)) + 0.50*(rank(-ts_zscore(enterprise_value / ebitda, 63)))`
- **6XpX0RoL** (UNSUBMITTED, fundamental): Sharpe=0.84, Fitness=0.39, TO=0.0539, DD=0.0856。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported_value / split, 126), sector)`
- **zqNqGjEV** (UNSUBMITTED, fundamental): Sharpe=0.73, Fitness=0.3, TO=0.0637, DD=0.0749。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported_value / split, 126), sector)`
- **JjGjzLpA** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.34, TO=0.0217, DD=0.2205。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **N1b1z9Lo** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.27, TO=0.0175, DD=0.2321。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **pwNwGXbo** (UNSUBMITTED, fundamental): Sharpe=0.87, Fitness=0.45, TO=0.0511, DD=0.0717。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported_value / split, 126), sector)`
- **1YpYlwGQ** (UNSUBMITTED, analyst): Sharpe=0.53, Fitness=0.25, TO=0.0485, DD=0.13。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ebitda / adjfactor, 126), sector)`

---


### 2026-08-02 19:22 UTC

- **npNxJNe3** (UNSUBMITTED, news): Sharpe=0.42, Fitness=0.33, TO=0.012, DD=0.2172。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **88p5beW7** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0909, DD=0.6614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **O0GQOeLJ** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.2, TO=0.488, DD=0.2021。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **LLGVWJM9** (UNSUBMITTED, technical): Sharpe=0.94, Fitness=0.34, TO=0.2843, DD=0.1055。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **3qpQww56** (UNSUBMITTED, technical): Sharpe=1.19, Fitness=0.7, TO=0.2746, DD=0.1343。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **ZYEP6Ya3** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.43, TO=0.2197, DD=0.317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **leWppwM5** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.72, TO=0.2363, DD=0.1662。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **omN88PWn** (UNSUBMITTED, technical): Sharpe=1.44, Fitness=0.79, TO=0.4245, DD=0.1101。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **0mpOOjEp** (UNSUBMITTED, technical): Sharpe=1.01, Fitness=0.62, TO=0.2102, DD=0.0855。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **JjGMMOex** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.33, TO=0.1248, DD=0.1829。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **E5GOOwzK** (UNSUBMITTED, technical): Sharpe=0.59, Fitness=0.84, TO=0.06, DD=0.7969。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **npNxxOQa** (UNSUBMITTED, technical): Sharpe=1.28, Fitness=0.68, TO=0.2879, DD=0.0838。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **N1bxxWk7** (UNSUBMITTED, technical): Sharpe=1.87, Fitness=0.74, TO=0.8402, DD=0.0824。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **ZYEPPGpx** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.07, TO=0.0108, DD=0.3435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **1YpkkeZK** (UNSUBMITTED, technical): Sharpe=1.78, Fitness=0.8, TO=0.5039, DD=0.0496。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **npNxp5dx** (UNSUBMITTED, technical): Sharpe=0.2, Fitness=0.08, TO=0.0091, DD=0.3623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **leWpeEMO** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.09, TO=0.012, DD=0.3098。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **P0GQ0O8W** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.05, TO=0.0076, DD=0.4124。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **zqNKqPKE** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **GrG1rrkG** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.03, TO=0.0073, DD=0.5018。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **RRmjJPA1** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.11, TO=0.008, DD=0.2325。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **O0GQ1M3b** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.12, TO=0.0071, DD=0.2931。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **gJ8kYZVe** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.11, TO=0.0088, DD=0.3732。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **pwNYqjv3** (UNSUBMITTED, fundamental): Sharpe=0.71, Fitness=1.06, TO=0.0045, DD=0.543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **9qpZzbjr** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.11, TO=0.0088, DD=0.3732。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **9qpZzQkV** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0112, DD=0.2806。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **j262qoQ9** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.18, TO=0.0059, DD=0.4065。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **2rpr3qGb** (UNSUBMITTED, fundamental): Sharpe=0.34, Fitness=0.18, TO=0.0073, DD=0.4299。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **E5G5932L** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.1, TO=0.0241, DD=0.3029。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **mL5LEO79** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.08, TO=0.0278, DD=0.2915。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **N1b1YwV7** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.03, TO=0.0073, DD=0.5018。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`

---


### 2026-08-02 21:49 UTC

- **e73k27pE** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.14, TO=0.0761, DD=0.703。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **mL5wAlZ6** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.12, TO=0.1332, DD=0.6335。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **A1Gjb7GW** (UNSUBMITTED, technical): Sharpe=1.79, Fitness=0.82, TO=0.6419, DD=0.0744。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **9qpZKJnr** (UNSUBMITTED, technical): Sharpe=0.85, Fitness=0.45, TO=0.1677, DD=0.1007。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **j26zWYnO** (UNSUBMITTED, technical): Sharpe=0.52, Fitness=0.32, TO=0.088, DD=0.143。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **ak1jMEeR** (UNSUBMITTED, technical): Sharpe=0.25, Fitness=0.08, TO=0.0184, DD=0.1237。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_cashflow_financing_est / rel_num_cust, 126), country)`
- **KPGlqk2z** (UNSUBMITTED, technical): Sharpe=0.65, Fitness=0.95, TO=0.0969, DD=0.8764。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_reported_value / adv20, 126), subindustry)`
- **npNxY3ed** (UNSUBMITTED, technical): Sharpe=0.63, Fitness=0.25, TO=0.0286, DD=0.0543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_cashflow_financing_est / rel_num_cust, 126), country)`
- **kqPEbRdk** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.27, TO=0.0329, DD=0.0515。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_cashflow_financing_est / rel_num_cust, 126), country)`
- **qMN9vZYV** (UNSUBMITTED, technical): Sharpe=0.57, Fitness=0.27, TO=0.0688, DD=0.1116。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_reported_value / adv20, 126), subindustry)`
- **YPvLnrdv** (UNSUBMITTED, technical): Sharpe=0.54, Fitness=0.2, TO=0.0907, DD=0.0698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_reported_value / adv20, 126), subindustry)`
- **vRNwnEqr** (UNSUBMITTED, technical): Sharpe=0.12, Fitness=0.03, TO=0.0338, DD=0.3772。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **ZYEPwgk8** (UNSUBMITTED, technical): Sharpe=0.16, Fitness=0.05, TO=0.033, DD=0.3297。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **WjA1wP3o** (UNSUBMITTED, technical): Sharpe=-0.42, Fitness=-0.24, TO=0.0221, DD=0.6385。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **78z7qz0b** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.11, TO=0.0188, DD=0.2757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **LLGVbdNm** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.05, TO=0.0289, DD=0.3606。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **LLGVbRAm** (UNSUBMITTED, technical): Sharpe=0.18, Fitness=0.06, TO=0.0117, DD=0.3318。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **QPGZrjE5** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.05, TO=0.0081, DD=0.3712。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **2rp8q00x** (UNSUBMITTED, technical): Sharpe=0.29, Fitness=0.12, TO=0.0247, DD=0.3467。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **omN8w7b2** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.11, TO=0.028, DD=0.3004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **78z7gLNQ** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.07, TO=0.0096, DD=0.3436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **kqPEeN3k** (UNSUBMITTED, technical): Sharpe=0.33, Fitness=0.15, TO=0.0215, DD=0.3051。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **88p5g7Yo** (UNSUBMITTED, analyst): Sharpe=0.04, Fitness=0.01, TO=0.0109, DD=0.3434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **N1bxkxqL** (UNSUBMITTED, fundamental): Sharpe=0.94, Fitness=0.45, TO=0.0495, DD=0.0451。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_book_value_per_share_est / rel_ret_part, 126), exchange)`
- **gJ8kv5j0** (UNSUBMITTED, analyst): Sharpe=0.1, Fitness=0.02, TO=0.0077, DD=0.288。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **RRmjXvAe** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.07, TO=0.0106, DD=0.3006。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **kqPER8Qk** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **d5ZkqeQJ** (UNSUBMITTED, fundamental): Sharpe=0.77, Fitness=0.27, TO=0.2704, DD=0.06。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_book_value_per_share_est / rel_ret_part, 126), exchange)`
- **pwNYgWAj** (UNSUBMITTED, fundamental): Sharpe=0.19, Fitness=0.04, TO=0.0293, DD=0.0653。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **GrG1vb7Z** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.12, TO=0.0322, DD=0.0469。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **78z7VwYL** (UNSUBMITTED, fundamental): Sharpe=0.79, Fitness=0.23, TO=0.3125, DD=0.0511。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_book_value_per_share_est / rel_ret_part, 126), exchange)`
- **3qpQLNAe** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.09, TO=0.0239, DD=0.2445。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **N1bx9dvX** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.1, TO=0.0196, DD=0.2828。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **O0GQaAE1** (UNSUBMITTED, fundamental): Sharpe=0.6, Fitness=0.2, TO=0.0369, DD=0.0466。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`

---


### 2026-08-03 00:10 UTC

- **P0GQpzlJ** (UNSUBMITTED, technical): Sharpe=0.69, Fitness=0.5, TO=0.0103, DD=0.3348。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **O0GQp6lp** (UNSUBMITTED, technical): Sharpe=1.44, Fitness=0.75, TO=0.4159, DD=0.0975。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **vRNwLL1r** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **d5ZkxgYK** (UNSUBMITTED, technical): Sharpe=-0.02, Fitness=-0.0, TO=0.008, DD=0.4816。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **O0GQpwgg** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.4, TO=0.1354, DD=0.1434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **WjA1pKmO** (UNSUBMITTED, technical): Sharpe=2.05, Fitness=0.82, TO=0.6942, DD=0.0674。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **kqPEKJg6** (UNSUBMITTED, technical): Sharpe=0.03, Fitness=0.0, TO=0.0087, DD=0.408。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **xANOn3GN** (UNSUBMITTED, technical): Sharpe=-0.02, Fitness=-0.0, TO=0.007, DD=0.5722。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **npNxWK63** (UNSUBMITTED, technical): Sharpe=0.71, Fitness=0.53, TO=0.0087, DD=0.2928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **npNxWNVx** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=0.51, TO=0.0133, DD=0.3303。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **VkG18E5w** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.07, TO=0.0094, DD=0.2594。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **XgomKj10** (UNSUBMITTED, analyst): Sharpe=0.1, Fitness=0.02, TO=0.0077, DD=0.288。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **GrG1k523** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.07, TO=0.0106, DD=0.3006。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **VkG1Oe08** (UNSUBMITTED, analyst): Sharpe=0.04, Fitness=0.01, TO=0.0102, DD=0.343。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **Xgom1Nla** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.04, TO=0.0219, DD=0.3858。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **78z7JLKZ** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.07, TO=0.008, DD=0.4894。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **9qpZJLwq** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.07, TO=0.0346, DD=0.2494。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **rK2pAgoa** (UNSUBMITTED, fundamental): Sharpe=0.2, Fitness=0.08, TO=0.0093, DD=0.4202。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **88p5nblW** (UNSUBMITTED, fundamental): Sharpe=0.7, Fitness=1.0, TO=0.003, DD=0.5377。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **9qpZ9WN9** (UNSUBMITTED, fundamental): Sharpe=0.63, Fitness=0.91, TO=0.0085, DD=0.7722。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **6XpmRj2K** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.0, TO=0.0188, DD=0.5441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **58pnLlnX** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.04, TO=0.0243, DD=0.1256。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **P0GQn3ZK** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.01, DD=0.277。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **88p5O7WW** (UNSUBMITTED, fundamental): Sharpe=0.03, Fitness=0.0, TO=0.0197, DD=0.2111。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **2rp8vqL6** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.04, TO=0.0073, DD=0.4919。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **0mpOAno2** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.12, TO=0.0088, DD=0.3703。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **vRNwe6RQ** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0097, DD=0.3448。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **A1GjgzGw** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0097, DD=0.3422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **leWpQEjl** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0081, DD=0.3631。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **78z7aEK1** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0101, DD=0.3319。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **A1GjgMbY** (UNSUBMITTED, fundamental): Sharpe=0.74, Fitness=1.07, TO=0.0033, DD=0.5249。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **zqNKP1XV** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0075, DD=0.4609。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`

---


### 2026-08-03 01:57 UTC

- **RRmjVvGb** (UNSUBMITTED, technical): Sharpe=0.77, Fitness=1.09, TO=0.0339, DD=0.5005。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **P0GQZM5K** (UNSUBMITTED, technical): Sharpe=1.72, Fitness=0.86, TO=0.5304, DD=0.0808。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **O0GQrr8v** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=0.54, TO=0.2281, DD=0.0815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **O0GQ7lXb** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.04, TO=0.0102, DD=0.2115。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **88p5lZJX** (UNSUBMITTED, technical): Sharpe=0.03, Fitness=0.0, TO=0.008, DD=0.3068。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **Xgom7aXx** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.07, TO=0.0329, DD=0.2174。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsa / adv20, 126), country)`
- **LLGV7GZn** (UNSUBMITTED, analyst): Sharpe=0.53, Fitness=0.28, TO=0.0409, DD=0.1014。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsa / adv20, 126), country)`
- **rK2pjAvd** (UNSUBMITTED, analyst): Sharpe=0.25, Fitness=0.08, TO=0.0669, DD=0.1824。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsa / adv20, 126), country)`
- **vRNwNolz** (UNSUBMITTED, fundamental): Sharpe=-0.05, Fitness=-0.01, TO=0.0111, DD=0.3241。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **6XpmpGAL** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0106, DD=0.3004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **ak1j11vW** (UNSUBMITTED, fundamental): Sharpe=-0.08, Fitness=-0.02, TO=0.0057, DD=0.3958。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **3qpQpYqN** (UNSUBMITTED, fundamental): Sharpe=-0.28, Fitness=-0.1, TO=0.006, DD=0.302。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **ak1j13ox** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.14, TO=0.005, DD=0.3496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **GrG1GA2o** (UNSUBMITTED, fundamental): Sharpe=-0.31, Fitness=-0.11, TO=0.0076, DD=0.2768。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **gJ8k8J80** (UNSUBMITTED, fundamental): Sharpe=-0.6, Fitness=-0.1, TO=1.2021, DD=0.4921。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / dividend, 126), subindustry)`
- **leWpWeV8** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.01, TO=0.3643, DD=0.2334。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / dividend, 126), subindustry)`
- **e73kxjNl** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.03, TO=0.0268, DD=0.0923。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(gross_income_max / primary_sector_focused_company_count, 126), market)`
- **1YpkzRQW** (UNSUBMITTED, fundamental): Sharpe=-0.37, Fitness=-0.07, TO=0.8718, DD=0.6454。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / dividend, 126), subindustry)`
- **npNx8e9w** (UNSUBMITTED, fundamental): Sharpe=-0.02, Fitness=-0.0, TO=0.0321, DD=0.1381。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(gross_income_max / primary_sector_focused_company_count, 126), market)`
- **QPGZ9OwQ** (UNSUBMITTED, fundamental): Sharpe=-0.36, Fitness=-0.08, TO=0.6602, DD=0.8449。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_minimum / dividend, 126), subindustry)`

---


### 2026-08-03 04:03 UTC

- **xANO2k9p** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **O0GQMOpg** (UNSUBMITTED, news): Sharpe=-0.12, Fitness=-0.05, TO=0.0188, DD=0.4776。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **j26zV3rQ** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.13, TO=0.0736, DD=0.6757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **78z7GK0Q** (UNSUBMITTED, technical): Sharpe=0.95, Fitness=0.62, TO=0.2285, DD=0.1867。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **58pnG69X** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **MPGMglja** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.66, TO=0.2447, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **GrG1m585** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **6XpmMJkJ** (UNSUBMITTED, technical): Sharpe=1.16, Fitness=0.59, TO=0.2539, DD=0.0722。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **YPvLaadA** (UNSUBMITTED, technical): Sharpe=0.55, Fitness=0.25, TO=0.0975, DD=0.0739。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_pretax_income_est / high, 126), sector)`
- **d5ZkaQvE** (UNSUBMITTED, technical): Sharpe=2.19, Fitness=0.82, TO=0.8274, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **9qpZlRMo** (UNSUBMITTED, technical): Sharpe=0.55, Fitness=0.35, TO=0.1027, DD=0.1465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **O0GQWERv** (UNSUBMITTED, technical): Sharpe=0.72, Fitness=0.53, TO=0.0131, DD=0.3195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **3qpQ0b6P** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=0.51, TO=0.0118, DD=0.3195。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **RRmje3qa** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=0.5, TO=0.01, DD=0.3167。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **1YpkNKEW** (UNSUBMITTED, technical): Sharpe=0.72, Fitness=0.53, TO=0.0084, DD=0.2811。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **vRNw1pdA** (UNSUBMITTED, analyst): Sharpe=0.29, Fitness=0.04, TO=0.421, DD=0.0926。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsr / rel_ret_cust, 126), sector)`
- **LLGVMdYa** (UNSUBMITTED, analyst): Sharpe=0.21, Fitness=0.03, TO=0.3657, DD=0.0974。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsr / rel_ret_cust, 126), sector)`
- **E5GO6kN0** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.04, TO=0.4768, DD=0.0899。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsr / rel_ret_cust, 126), sector)`
- **omN8E2bk** (UNSUBMITTED, analyst): Sharpe=0.27, Fitness=0.05, TO=0.3333, DD=0.0741。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_epsr / rel_ret_cust, 126), sector)`
- **omN8E2eJ** (UNSUBMITTED, analyst): Sharpe=0.18, Fitness=0.06, TO=0.0111, DD=0.314。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **3qpQoQjz** (UNSUBMITTED, fundamental): Sharpe=0.69, Fitness=0.29, TO=0.0573, DD=0.1106。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported / rel_num_all, 126), sector)`
- **O0GQA017** (UNSUBMITTED, analyst): Sharpe=0.23, Fitness=0.09, TO=0.0122, DD=0.2979。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **LLGV5Qje** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.05, TO=0.0076, DD=0.3471。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **npNxAXww** (UNSUBMITTED, fundamental): Sharpe=0.7, Fitness=0.32, TO=0.0511, DD=0.1243。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported / rel_num_all, 126), sector)`
- **XgomRema** (UNSUBMITTED, fundamental): Sharpe=0.61, Fitness=0.26, TO=0.0516, DD=0.1213。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported / rel_num_all, 126), sector)`
- **GrG1gQko** (UNSUBMITTED, fundamental): Sharpe=0.67, Fitness=0.26, TO=0.0644, DD=0.0856。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(earnings_per_share_reported / rel_num_all, 126), sector)`
- **xANO1q8m** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.17, TO=0.0281, DD=0.2981。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **KPGlmKNE** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.23, TO=0.0244, DD=0.2752。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **YPvLMRoo** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.1, TO=0.0185, DD=0.4013。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`

---


### 2026-08-03 06:22 UTC

- **A1G9RRmd** (UNSUBMITTED, news): Sharpe=-0.08, Fitness=-0.05, TO=0.0245, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **58pnXvXo** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **78z7p72Q** (UNSUBMITTED, technical): Sharpe=0.69, Fitness=0.89, TO=0.1698, DD=0.6719。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **mL5wGdox** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **j26zkJWj** (UNSUBMITTED, technical): Sharpe=2.18, Fitness=0.58, TO=1.3143, DD=0.0439。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **blQG1AgK** (UNSUBMITTED, technical): Sharpe=0.25, Fitness=0.1, TO=0.0126, DD=0.3104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **9qpZO8L9** (UNSUBMITTED, technical): Sharpe=0.16, Fitness=0.06, TO=0.0098, DD=0.3616。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **YPvLogZq** (UNSUBMITTED, technical): Sharpe=0.89, Fitness=0.44, TO=0.0884, DD=0.0507。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(pretax_income_actual_reported_value / open, 126), subindustry)`
- **A1Gj86Vl** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.07, TO=0.01, DD=0.3253。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **88p5x1Qq** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.02, TO=0.008, DD=0.4273。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **xANOpqnl** (UNSUBMITTED, technical): Sharpe=0.97, Fitness=0.54, TO=0.0835, DD=0.0471。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(pretax_income_actual_reported_value / open, 126), subindustry)`
- **e73kPN3g** (UNSUBMITTED, analyst): Sharpe=0.72, Fitness=0.16, TO=0.5036, DD=0.0846。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(lowest_sales_estimate / rel_ret_part, 126), currency)`
- **e73kPLVN** (UNSUBMITTED, analyst): Sharpe=0.68, Fitness=0.15, TO=0.4719, DD=0.0618。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(lowest_sales_estimate / rel_ret_part, 126), currency)`
- **1YpkRLRz** (UNSUBMITTED, analyst): Sharpe=0.65, Fitness=0.95, TO=0.0847, DD=0.6924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **vRNwoPPz** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.51, TO=0.394, DD=0.6763。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(lowest_sales_estimate / rel_ret_part, 126), currency)`
- **pwNYpZ1X** (UNSUBMITTED, analyst): Sharpe=0.76, Fitness=0.15, TO=0.5645, DD=0.0721。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(lowest_sales_estimate / rel_ret_part, 126), currency)`
- **gJ8kLe1K** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.12, TO=0.009, DD=0.4831。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **6XpmNaXE** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.08, TO=0.0073, DD=0.6035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **npNxQlV3** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0156, DD=0.3917。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **vRNw6Paz** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0132, DD=0.4567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **N1bx3Lb7** (UNSUBMITTED, fundamental): Sharpe=1.29, Fitness=0.65, TO=0.0603, DD=0.0436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_count_quarterly / rel_num_all, 126), subindustry)`
- **e73kv6Gz** (UNSUBMITTED, fundamental): Sharpe=1.1, Fitness=0.48, TO=0.063, DD=0.0433。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_count_quarterly / rel_num_all, 126), subindustry)`
- **zqNK0rWK** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.07, TO=0.0061, DD=0.6014。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`

---


### 2026-08-03 08:26 UTC

- **2rpMq3OZ** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.13, TO=0.1106, DD=0.6452。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **QPGMr3dp** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **gJ86qmQe** (UNSUBMITTED, technical): Sharpe=0.72, Fitness=0.82, TO=0.2267, DD=0.6928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **blQX238m** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.4, TO=0.1354, DD=0.1434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **88pbgMAX** (UNSUBMITTED, technical): Sharpe=0.25, Fitness=0.1, TO=0.0132, DD=0.2761。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **88pbgVeo** (UNSUBMITTED, technical): Sharpe=2.18, Fitness=0.58, TO=1.3143, DD=0.0439。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **N1b0kKgg** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.03, TO=0.0069, DD=0.3926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **O0GOKGbJ** (UNSUBMITTED, technical): Sharpe=0.09, Fitness=0.02, TO=0.0106, DD=0.3187。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **wpaqX5rv** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.05, TO=0.0066, DD=0.368。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **qMN8eZRv** (UNSUBMITTED, analyst): Sharpe=0.11, Fitness=0.03, TO=0.0071, DD=0.3884。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **88pbAMxm** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **zqNZaVdK** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0192, DD=0.3202。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **E5G13nA1** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0092, DD=0.3499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **gJ86vRoe** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0107, DD=0.3334。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **MPGOwoYa** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.09, TO=0.0163, DD=0.3183。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **XgoGEzgx** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0077, DD=0.3742。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **gJ86zr3l** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.08, TO=0.0122, DD=0.3122。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **ak163ap5** (UNSUBMITTED, fundamental): Sharpe=0.6, Fitness=0.2, TO=0.0369, DD=0.0466。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **6Xp7bbXE** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.11, TO=0.0323, DD=0.0483。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **RRmMWPEo** (UNSUBMITTED, fundamental): Sharpe=0.9, Fitness=0.35, TO=0.0424, DD=0.0323。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **vRN8gkXw** (UNSUBMITTED, fundamental): Sharpe=0.6, Fitness=0.2, TO=0.0369, DD=0.0466。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **A1G9MoGQ** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0083, DD=0.3418。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **ZYE6eJQ0** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.05, TO=0.0293, DD=0.0642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **MPGOoNJ6** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.04, TO=0.0293, DD=0.0653。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **j26vb53O** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.16, TO=0.0074, DD=0.4174。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **YPv6K3v6** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0106, DD=0.3004。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **MPGORZNz** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.05, TO=0.0117, DD=0.3077。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **j26vRw29** (UNSUBMITTED, fundamental): Sharpe=0.37, Fitness=0.19, TO=0.0081, DD=0.357。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **78zWbVpv** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0091, DD=0.3102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **e73mpXep** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.05, TO=0.0076, DD=0.2883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **ZYE65wY8** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.07, TO=0.0132, DD=0.2815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **3qpwbMp6** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.15, TO=0.0059, DD=0.3982。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **ZYE66vrx** (UNSUBMITTED, fundamental): Sharpe=-0.05, Fitness=-0.01, TO=0.0118, DD=0.3232。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`

---


### 2026-08-03 10:56 UTC

- **88pbl1jq** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **MPGOGlpL** (UNSUBMITTED, technical): Sharpe=0.78, Fitness=0.44, TO=0.2362, DD=0.2918。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_decay_linear(close / vwap, 10))) + 0.50*(rank(-ts_std_dev(returns, 20)))`
- **mL5p5LqK** (UNSUBMITTED, technical): Sharpe=1.2, Fitness=0.61, TO=0.3485, DD=0.1223。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)) + 0.50*(rank(volume / adv20))`
- **XgoG8AN1** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.13, TO=0.0836, DD=0.6975。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **QPGM9pvW** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.14, TO=0.0761, DD=0.703。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **vRN8vXVw** (UNSUBMITTED, technical): Sharpe=0.81, Fitness=0.34, TO=0.3466, DD=0.1003。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_mean(returns, 33))) + 0.50*(rank(volume / adv20))`
- **ZYE6KdKx** (UNSUBMITTED, technical): Sharpe=1.0, Fitness=0.42, TO=0.2291, DD=0.0942。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **j26vrale** (UNSUBMITTED, technical): Sharpe=1.29, Fitness=0.73, TO=0.419, DD=0.1221。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **vRN8v1oA** (UNSUBMITTED, technical): Sharpe=1.44, Fitness=0.79, TO=0.4245, DD=0.1101。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **58pxkMgX** (UNSUBMITTED, technical): Sharpe=1.28, Fitness=0.74, TO=0.2839, DD=0.0861。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **O0GOxoqR** (UNSUBMITTED, technical): Sharpe=1.43, Fitness=0.72, TO=0.3277, DD=0.0842。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **omN7gQV5** (UNSUBMITTED, technical): Sharpe=1.28, Fitness=0.68, TO=0.2879, DD=0.0838。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **qMN86o5P** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.33, TO=0.1248, DD=0.1829。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **88pbemeo** (UNSUBMITTED, technical): Sharpe=0.56, Fitness=0.37, TO=0.129, DD=0.1559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **leWdloel** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.23, TO=0.1212, DD=0.2161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **9qpYrOrr** (UNSUBMITTED, technical): Sharpe=1.63, Fitness=0.75, TO=0.4392, DD=0.0563。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **9qpYr8KK** (UNSUBMITTED, technical): Sharpe=2.03, Fitness=0.78, TO=0.8341, DD=0.0868。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **A1G9PbGW** (UNSUBMITTED, technical): Sharpe=-0.03, Fitness=-0.01, TO=0.0103, DD=0.7928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **A1G9PR6e** (UNSUBMITTED, technical): Sharpe=-0.03, Fitness=-0.01, TO=0.0409, DD=0.5595。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **N1b0rXx7** (UNSUBMITTED, technical): Sharpe=-0.05, Fitness=-0.01, TO=0.0337, DD=0.6571。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **d5ZpxXWw** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.05, TO=0.0124, DD=0.5596。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **e73mrXjE** (UNSUBMITTED, technical): Sharpe=-0.44, Fitness=-0.39, TO=0.0459, DD=1.1657。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **mL5pX1vE** (UNSUBMITTED, technical): Sharpe=-0.15, Fitness=-0.07, TO=0.046, DD=0.5729。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **ak16OodO** (UNSUBMITTED, technical): Sharpe=0.09, Fitness=0.02, TO=0.0107, DD=0.4958。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **LLGWRbjv** (UNSUBMITTED, technical): Sharpe=0.09, Fitness=0.02, TO=0.0093, DD=0.5635。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **E5G1k92J** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.02, TO=0.0117, DD=0.4539。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **RRmMdGne** (UNSUBMITTED, technical): Sharpe=0.33, Fitness=0.15, TO=0.0123, DD=0.3806。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **WjAM90Qo** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.011, DD=0.4311。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **blQXvakN** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.16, TO=0.006, DD=0.3809。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **YPv6QMmA** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.05, TO=0.0075, DD=0.5633。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **1YpeJ50W** (UNSUBMITTED, analyst): Sharpe=0.39, Fitness=0.2, TO=0.0087, DD=0.3372。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **QPGMELZw** (UNSUBMITTED, analyst): Sharpe=0.24, Fitness=0.1, TO=0.009, DD=0.4348。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **mL5pqNA5** (UNSUBMITTED, analyst): Sharpe=0.45, Fitness=0.25, TO=0.0098, DD=0.2924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **P0GNnKmM** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.14, TO=0.0101, DD=0.3724。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **1YpeoOAQ** (UNSUBMITTED, analyst): Sharpe=0.01, Fitness=0.0, TO=0.006, DD=0.7859。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **d5ZpEMrE** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.06, TO=0.0061, DD=0.5428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **MPGOKnzL** (UNSUBMITTED, fundamental): Sharpe=0.73, Fitness=0.39, TO=0.0848, DD=0.0761。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **RRmM2MRa** (UNSUBMITTED, fundamental): Sharpe=0.2, Fitness=0.08, TO=0.0074, DD=0.4674。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **gJ86oln0** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.09, TO=0.0092, DD=0.3633。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **P0GNXAJx** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.08, TO=0.0208, DD=0.0611。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **leWdR887** (UNSUBMITTED, fundamental): Sharpe=0.5, Fitness=0.16, TO=0.0237, DD=0.0423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **JjGq5G1j** (UNSUBMITTED, fundamental): Sharpe=0.68, Fitness=0.24, TO=0.0282, DD=0.0435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **mL5pxApK** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0115, DD=0.2785。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **LLGWlq06** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.04, TO=0.0073, DD=0.4919。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **ak16WX3W** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.06, TO=0.0103, DD=0.3113。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`

---


### 2026-08-03 13:00 UTC

- **A1G9En2Q** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.13, TO=0.0682, DD=0.7738。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **E5G1xJvm** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0909, DD=0.6614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **XgoGM6E5** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.19, TO=0.4943, DD=0.1418。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **9qpYkqlr** (UNSUBMITTED, technical): Sharpe=0.55, Fitness=0.35, TO=0.1027, DD=0.1465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **ZYE6NY31** (UNSUBMITTED, technical): Sharpe=0.77, Fitness=0.21, TO=0.4912, DD=0.1601。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **rK2YVMP3** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.71, TO=0.1792, DD=0.7179。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **1YpeP03J** (UNSUBMITTED, technical): Sharpe=1.07, Fitness=0.64, TO=0.2332, DD=0.0913。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **3qpw5PEZ** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **1YpePGjm** (UNSUBMITTED, technical): Sharpe=1.17, Fitness=0.72, TO=0.281, DD=0.1257。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **MPGOZa2a** (UNSUBMITTED, technical): Sharpe=1.71, Fitness=0.72, TO=0.845, DD=0.0853。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **npN9QglM** (UNSUBMITTED, analyst): Sharpe=0.91, Fitness=0.5, TO=0.0579, DD=0.0841。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ptp / rel_num_all, 126), market)`
- **MPGOZxx8** (UNSUBMITTED, analyst): Sharpe=0.8, Fitness=0.35, TO=0.072, DD=0.0591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ptp / rel_num_all, 126), market)`
- **d5ZpodOw** (UNSUBMITTED, technical): Sharpe=2.19, Fitness=0.82, TO=0.8274, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **GrGPx0O3** (UNSUBMITTED, analyst): Sharpe=1.69, Fitness=1.14, TO=0.1522, DD=0.0464。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0GOVKnv** (UNSUBMITTED, analyst): Sharpe=0.65, Fitness=0.95, TO=0.0847, DD=0.6924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **O0GOVYGY** (UNSUBMITTED, analyst): Sharpe=0.97, Fitness=0.61, TO=0.0552, DD=0.0812。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ptp / rel_num_all, 126), market)`
- **npN9qE1z** (UNSUBMITTED, analyst): Sharpe=0.85, Fitness=0.41, TO=0.064, DD=0.0706。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ptp / rel_num_all, 126), market)`
- **O0GOzWVg** (UNSUBMITTED, fundamental): Sharpe=0.54, Fitness=0.31, TO=0.1338, DD=0.1493。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **QPGMzK8K** (UNSUBMITTED, analyst): Sharpe=1.74, Fitness=1.16, TO=0.1534, DD=0.0451。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **N1b0zWWE** (UNSUBMITTED, fundamental): Sharpe=0.84, Fitness=0.48, TO=0.1273, DD=0.083。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **88pbEWEm** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.11, TO=0.0113, DD=0.2623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **P0GNYPaw** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.12, TO=0.0096, DD=0.2355。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **GrGPKVn5** (UNSUBMITTED, fundamental): Sharpe=0.44, Fitness=0.25, TO=0.0094, DD=0.3422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **rK2Y9xZj** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.22, TO=0.0084, DD=0.3765。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **npN9mqe3** (UNSUBMITTED, fundamental): Sharpe=0.96, Fitness=0.39, TO=0.0324, DD=0.0307。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **kqPdvWGl** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.08, TO=0.0158, DD=0.2653。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **LLGWEXVn** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0097, DD=0.3448。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **vRN8ZqLb** (UNSUBMITTED, fundamental): Sharpe=0.5, Fitness=0.16, TO=0.0237, DD=0.0423。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **3qpwGNV6** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.25, TO=0.0095, DD=0.3383。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **ZYE6XM10** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.16, TO=0.0057, DD=0.4193。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **xANqllQg** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.08, TO=0.0208, DD=0.0611。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **gJ86rEGO** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0114, DD=0.3303。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **RRmM5RG1** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.07, TO=0.0129, DD=0.3037。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **E5G1mZ0K** (UNSUBMITTED, fundamental): Sharpe=0.68, Fitness=0.24, TO=0.0282, DD=0.0435。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **npN9aQYa** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0077, DD=0.3742。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **88pbNYbq** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.08, TO=0.0122, DD=0.3122。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **xANqvRmb** (UNSUBMITTED, fundamental): Sharpe=0.32, Fitness=0.17, TO=0.0071, DD=0.4364。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **MPGOYVZM** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.19, TO=0.0116, DD=0.3583。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **RRmME7V0** (UNSUBMITTED, fundamental): Sharpe=0.44, Fitness=0.25, TO=0.0094, DD=0.3422。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **O0GOAeV1** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0116, DD=0.3327。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **2rpMAbeb** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.16, TO=0.0057, DD=0.4196。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **88pbRmRq** (UNSUBMITTED, fundamental): Sharpe=0.35, Fitness=0.19, TO=0.009, DD=0.4664。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **vRN8OW9v** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.2, TO=0.0974, DD=0.0999。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(shareholders_equity_avg / open, 126), currency)`
- **KPG3mZ01** (UNSUBMITTED, fundamental): Sharpe=-0.11, Fitness=-0.02, TO=0.0205, DD=0.0973。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_min / single_sector_pureplay_company_count, 126), currency)`
- **P0GNM8oK** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0092, DD=0.3499。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **A1G9QvzQ** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.35, TO=0.1047, DD=0.0775。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(shareholders_equity_avg / open, 126), currency)`
- **RRmMA691** (UNSUBMITTED, fundamental): Sharpe=0.6, Fitness=0.28, TO=0.038, DD=0.0629。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(shareholders_equity_avg / open, 126), currency)`
- **1YpejZNk** (UNSUBMITTED, fundamental): Sharpe=-0.13, Fitness=-0.02, TO=0.025, DD=0.0854。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_min / single_sector_pureplay_company_count, 126), currency)`

---


### 2026-08-03 14:55 UTC

- **YPvr6GgR** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.2, TO=0.488, DD=0.2021。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **ZYE565A1** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.12, TO=0.1332, DD=0.6335。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **wpamKArp** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **RRm3jPne** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **RRm3j6Na** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **zqNMqmjE** (UNSUBMITTED, technical): Sharpe=1.87, Fitness=0.74, TO=0.8402, DD=0.0824。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **e73p7rNl** (UNSUBMITTED, technical): Sharpe=2.19, Fitness=0.82, TO=0.8274, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **MPGWPkwo** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.05, TO=0.015, DD=0.2886。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **6Xp8XO6G** (UNSUBMITTED, fundamental): Sharpe=-0.01, Fitness=-0.0, TO=0.005, DD=0.5221。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **npNJ1Nw3** (UNSUBMITTED, technical): Sharpe=0.17, Fitness=0.05, TO=0.0163, DD=0.2738。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **O0GY19qY** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.08, TO=0.0134, DD=0.3028。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **JjGwVb5x** (UNSUBMITTED, technical): Sharpe=0.25, Fitness=0.09, TO=0.0099, DD=0.2952。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **QPGJ1qjM** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.24, TO=0.1409, DD=0.2957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank(-ts_std_dev(returns, 20))) + 0.50*(rank(-ts_zscore(enterprise_value / ebitda, 63)))`
- **kqP7xkA6** (UNSUBMITTED, analyst): Sharpe=1.71, Fitness=1.01, TO=0.1638, DD=0.0465。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **kqP7x5El** (UNSUBMITTED, fundamental): Sharpe=1.81, Fitness=0.85, TO=0.428, DD=0.0757。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.50*(rank((high + low) / 2 - close)) + 0.50*(rank(-ts_zscore(enterprise_value / ebitda, 63)))`
- **omNp15Gl** (UNSUBMITTED, fundamental): Sharpe=1.92, Fitness=0.91, TO=0.4348, DD=0.0854。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`0.40*(rank((high + low) / 2 - close)) + 0.40*(rank(-ts_zscore(enterprise_value / ebitda, 63))) + 0.20*(rank(volume / ...`
- **blQXe0vm** (UNSUBMITTED, fundamental): Sharpe=0.95, Fitness=0.58, TO=0.1398, DD=0.0942。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **YPv6RoYl** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **d5ZpN6XJ** (UNSUBMITTED, fundamental): Sharpe=0.69, Fitness=0.38, TO=0.0276, DD=0.227。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share / split, 126), subindustry)`
- **VkGVAxE5** (UNSUBMITTED, fundamental): Sharpe=0.81, Fitness=0.44, TO=0.0316, DD=0.1905。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share / split, 126), subindustry)`
- **O0GOl8X1** (UNSUBMITTED, fundamental): Sharpe=1.48, Fitness=1.03, TO=0.0421, DD=0.0431。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_total / vwap, 126), sector)`
- **blQXed5N** (UNSUBMITTED, fundamental): Sharpe=-0.41, Fitness=-0.24, TO=0.0694, DD=0.6366。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(reporting_currency_code_9 / adjfactor, 126), currency)`
- **A1G9oJ0X** (UNSUBMITTED, fundamental): Sharpe=-0.34, Fitness=-0.2, TO=0.0551, DD=0.7322。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(reporting_currency_code_9 / adjfactor, 126), currency)`
- **LLGW0e7n** (UNSUBMITTED, fundamental): Sharpe=-0.45, Fitness=-0.23, TO=0.1025, DD=0.4793。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(reporting_currency_code_9 / adjfactor, 126), currency)`
- **rK2YZpgE** (UNSUBMITTED, fundamental): Sharpe=0.88, Fitness=0.52, TO=0.0277, DD=0.1973。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share / split, 126), subindustry)`
- **leWdoe55** (UNSUBMITTED, fundamental): Sharpe=1.63, Fitness=1.15, TO=0.1166, DD=0.0552。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_total / vwap, 126), sector)`
- **kqPdAA9k** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.52, TO=0.0234, DD=0.1284。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share / split, 126), subindustry)`
- **RRmMgK1g** (UNSUBMITTED, fundamental): Sharpe=0.47, Fitness=0.18, TO=0.0185, DD=0.0788。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **wpaqr3Yp** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.18, TO=0.0091, DD=0.4678。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **omN7dPoE** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.12, TO=0.0214, DD=0.0567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **omN7dLOl** (UNSUBMITTED, fundamental): Sharpe=0.55, Fitness=0.19, TO=0.0305, DD=0.0508。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **kqPdA3j8** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.15, TO=0.0107, DD=0.4181。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **blQXw7NZ** (UNSUBMITTED, fundamental): Sharpe=0.47, Fitness=0.15, TO=0.0263, DD=0.0526。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **A1G9pXog** (UNSUBMITTED, fundamental): Sharpe=0.37, Fitness=0.18, TO=0.0114, DD=0.3645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **JjGqA1ze** (UNSUBMITTED, fundamental): Sharpe=0.09, Fitness=0.02, TO=0.0069, DD=0.3887。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **LLGWovEe** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.12, TO=0.009, DD=0.4831。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **O0GOddop** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.08, TO=0.0073, DD=0.6035。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **RRmMxlee** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.03, TO=0.0063, DD=0.4379。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **rK2YMng9** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.07, TO=0.0061, DD=0.6014。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **j26vKMv5** (UNSUBMITTED, fundamental): Sharpe=0.09, Fitness=0.02, TO=0.008, DD=0.3765。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(high,high,5),3),0.85),`
- **N1b0l217** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.1, TO=0.0086, DD=0.5345。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`

---


### 2026-08-03 17:27 UTC

- **P0GWn3pE** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **ZYE5j2zn** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **KPG0nwQk** (UNSUBMITTED, news): Sharpe=-0.09, Fitness=-0.05, TO=0.0243, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **78zAK3xv** (UNSUBMITTED, technical): Sharpe=0.98, Fitness=0.39, TO=0.2504, DD=0.1015。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **2rp0nOzP** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.72, TO=0.2363, DD=0.1662。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **YPvrWwr6** (UNSUBMITTED, technical): Sharpe=0.95, Fitness=0.62, TO=0.2285, DD=0.1867。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **E5G7rodm** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.43, TO=0.2197, DD=0.317。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **j26EdQJj** (UNSUBMITTED, technical): Sharpe=1.73, Fitness=0.79, TO=0.4881, DD=0.0864。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **2rp0ZV15** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **wpamzXNd** (UNSUBMITTED, technical): Sharpe=0.28, Fitness=0.12, TO=0.0151, DD=0.2329。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **leWqzJp2** (UNSUBMITTED, technical): Sharpe=1.77, Fitness=0.75, TO=0.7089, DD=0.0799。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **wpam1AN5** (UNSUBMITTED, technical): Sharpe=0.09, Fitness=0.02, TO=0.0106, DD=0.3187。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **A1GWbLbQ** (UNSUBMITTED, technical): Sharpe=0.05, Fitness=0.01, TO=0.0216, DD=0.3501。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **e73pKroE** (UNSUBMITTED, technical): Sharpe=0.38, Fitness=0.14, TO=0.0247, DD=0.1914。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **leWqkEae** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.1, TO=0.0301, DD=0.2063。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **zqNMQYYV** (UNSUBMITTED, technical): Sharpe=0.4, Fitness=0.13, TO=0.0343, DD=0.1926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(primary_sector_focused_company_count,primary_sector_focused_company_count,5),...`
- **N1bwqj3e** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.16, TO=0.0075, DD=0.4273。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **j26ElO2j** (UNSUBMITTED, analyst): Sharpe=0.43, Fitness=0.24, TO=0.0106, DD=0.3268。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **O0GYw83b** (UNSUBMITTED, analyst): Sharpe=0.38, Fitness=0.2, TO=0.0088, DD=0.3645。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **O0GYwN6g** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0089, DD=0.2591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **VkG9Kzgb** (UNSUBMITTED, analyst): Sharpe=0.29, Fitness=0.15, TO=0.006, DD=0.4095。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **9qpvgx1q** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=0.0, TO=0.0077, DD=0.3305。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **xAN6X1xl** (UNSUBMITTED, analyst): Sharpe=0.13, Fitness=0.03, TO=0.0108, DD=0.2213。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **QPGJm9dG** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **E5G7oYjL** (UNSUBMITTED, fundamental): Sharpe=0.8, Fitness=0.5, TO=0.1358, DD=0.1023。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **xAN6XgQp** (UNSUBMITTED, fundamental): Sharpe=1.17, Fitness=0.8, TO=0.0986, DD=0.0739。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(dividend_estimate_median_value / vwap, 126), currency)`
- **rK23Qvpo** (UNSUBMITTED, fundamental): Sharpe=0.85, Fitness=0.61, TO=0.0811, DD=0.1277。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(dividend_estimate_median_value / vwap, 126), currency)`
- **58pbN0wJ** (UNSUBMITTED, fundamental): Sharpe=0.63, Fitness=0.13, TO=0.4804, DD=0.0627。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / rel_ret_part, 126), exchange)`
- **0mploa2r** (UNSUBMITTED, fundamental): Sharpe=1.49, Fitness=0.9, TO=0.1321, DD=0.0419。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_min / low, 126), subindustry)`
- **VkG9nZ6Y** (UNSUBMITTED, fundamental): Sharpe=0.52, Fitness=0.36, TO=0.0702, DD=0.2231。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(dividend_estimate_median_value / vwap, 126), currency)`
- **leWqxlNn** (UNSUBMITTED, fundamental): Sharpe=1.0, Fitness=0.65, TO=0.0841, DD=0.0646。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_min / low, 126), subindustry)`
- **YPvrZpew** (UNSUBMITTED, fundamental): Sharpe=0.67, Fitness=0.15, TO=0.4448, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / rel_ret_part, 126), exchange)`
- **58pbRwXo** (UNSUBMITTED, fundamental): Sharpe=1.11, Fitness=0.8, TO=0.0758, DD=0.0787。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(dividend_estimate_median_value / vwap, 126), currency)`
- **QPGJejbp** (UNSUBMITTED, fundamental): Sharpe=0.66, Fitness=0.11, TO=0.7668, DD=0.0494。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / rel_ret_part, 126), exchange)`
- **kqP7R2JO** (UNSUBMITTED, fundamental): Sharpe=0.68, Fitness=0.13, TO=0.5456, DD=0.0486。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / rel_ret_part, 126), exchange)`
- **88poqkMq** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.14, TO=0.0149, DD=0.3597。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **WjAqmwGx** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.07, TO=0.0228, DD=0.2728。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **1Yp959Xk** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.07, TO=0.0285, DD=0.2271。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **wpamgx0Y** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0092, DD=0.5157。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **d5ZXLV3v** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.09, TO=0.0182, DD=0.2986。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(vwap,vwap,5),3),0.85),`
- **d5ZXLpOE** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.11, TO=0.0134, DD=0.4104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`

---


### 2026-08-03 18:58 UTC

- **XgorbLg0** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0909, DD=0.6614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **vRNqrVkr** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **xAN630Ym** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=0.6, TO=0.415, DD=0.1644。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **xAN6YWMq** (UNSUBMITTED, technical): Sharpe=1.06, Fitness=0.54, TO=0.2281, DD=0.0815。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **6Xp8rMm7** (UNSUBMITTED, technical): Sharpe=0.68, Fitness=0.35, TO=0.2343, DD=0.1337。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **vRNqkxNa** (UNSUBMITTED, analyst): Sharpe=-0.6, Fitness=-0.11, TO=1.0775, DD=0.5426。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(highest_sales_estimate / dividend, 126), currency)`
- **npNJK0Gx** (UNSUBMITTED, analyst): Sharpe=-0.64, Fitness=-0.12, TO=1.2088, DD=0.5712。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(highest_sales_estimate / dividend, 126), currency)`
- **LLGj70be** (UNSUBMITTED, analyst): Sharpe=-0.28, Fitness=-0.06, TO=0.6579, DD=0.824。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(highest_sales_estimate / dividend, 126), currency)`
- **A1GWlvNw** (UNSUBMITTED, fundamental): Sharpe=0.71, Fitness=0.32, TO=0.0667, DD=0.0949。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_max / sharesout, 126), exchange)`
- **wpamjZal** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=0.55, TO=0.044, DD=0.1252。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_debt_amount / sharesout, 126), currency)`
- **omNpqNvk** (UNSUBMITTED, fundamental): Sharpe=0.7, Fitness=0.34, TO=0.0577, DD=0.1288。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_max / sharesout, 126), exchange)`
- **qMN1jmgK** (UNSUBMITTED, fundamental): Sharpe=0.75, Fitness=0.4, TO=0.0377, DD=0.15。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_debt_amount / sharesout, 126), currency)`
- **omNpq9pl** (UNSUBMITTED, fundamental): Sharpe=1.02, Fitness=0.55, TO=0.0504, DD=0.1044。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(net_debt_amount / sharesout, 126), currency)`
- **78zAjqP1** (UNSUBMITTED, fundamental): Sharpe=0.64, Fitness=0.34, TO=0.0429, DD=0.1071。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_max / sharesout, 126), exchange)`
- **blQkQ9b6** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.21, TO=0.0076, DD=0.457。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **KPG0Gwel** (UNSUBMITTED, fundamental): Sharpe=0.23, Fitness=0.08, TO=0.0153, DD=0.267。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **mL535zr2** (UNSUBMITTED, fundamental): Sharpe=0.48, Fitness=0.29, TO=0.0102, DD=0.356。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **KPG0EmnE** (UNSUBMITTED, fundamental): Sharpe=0.17, Fitness=0.05, TO=0.0195, DD=0.3199。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **E5G7epVP** (UNSUBMITTED, fundamental): Sharpe=0.34, Fitness=0.2, TO=0.0062, DD=0.4483。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_all,rel_num_all,5),3),0.85),`
- **qMN16jMV** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.07, TO=0.0138, DD=0.2932。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **qMN16KJE** (UNSUBMITTED, fundamental): Sharpe=0.77, Fitness=1.18, TO=0.0074, DD=0.5615。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **1Yp9zqlJ** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.12, TO=0.0096, DD=0.2355。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **A1GWP7Nd** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.11, TO=0.0113, DD=0.2624。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`

---


### 2026-08-03 20:56 UTC

- **blQknrQZ** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **e73pvwE6** (UNSUBMITTED, news): Sharpe=3.03, Fitness=6.74, TO=0.1538, DD=0.0476。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **GrGazPmP** (UNSUBMITTED, technical): Sharpe=1.62, Fitness=0.83, TO=0.4719, DD=0.0845。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **npNJq9WE** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0909, DD=0.6614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **zqNM2dXK** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.16, TO=0.5794, DD=0.1271。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **rK23NAdE** (UNSUBMITTED, technical): Sharpe=0.58, Fitness=0.38, TO=0.1151, DD=0.1463。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **LLGjmlza** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.08, TO=0.0115, DD=0.3106。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **npNJe9Lz** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.05, TO=0.0081, DD=0.3712。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **9qpv82a2** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.07, TO=0.0096, DD=0.3436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **kqP7vvrP** (UNSUBMITTED, technical): Sharpe=-0.5, Fitness=-0.31, TO=0.021, DD=0.6801。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **YPvr8lm6** (UNSUBMITTED, technical): Sharpe=0.18, Fitness=0.06, TO=0.0114, DD=0.3324。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **mL53daMX** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.04, TO=0.0276, DD=0.3337。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **QPGJOMeK** (UNSUBMITTED, technical): Sharpe=0.16, Fitness=0.05, TO=0.0328, DD=0.3794。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **zqNMAxOR** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.04, TO=0.0293, DD=0.3309。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **WjAqYozZ** (UNSUBMITTED, analyst): Sharpe=0.28, Fitness=0.1, TO=0.0118, DD=0.2751。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **YPvrln7R** (UNSUBMITTED, analyst): Sharpe=0.31, Fitness=0.12, TO=0.0096, DD=0.2557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **ZYE5XG7Z** (UNSUBMITTED, analyst): Sharpe=0.3, Fitness=0.11, TO=0.013, DD=0.2477。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **RRm353Kb** (UNSUBMITTED, analyst): Sharpe=0.33, Fitness=0.14, TO=0.0082, DD=0.2262。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **58pbJMgM** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.11, TO=0.0113, DD=0.2623。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **JjGw8gj2** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.08, TO=0.0119, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **RRm3e09b** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0105, DD=0.3328。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **GrGaWkr3** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0398, DD=0.5217。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **O0GYA5g1** (UNSUBMITTED, fundamental): Sharpe=-0.06, Fitness=-0.02, TO=0.0466, DD=0.4246。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **A1GWVb5w** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.05, TO=0.0089, DD=0.3523。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`

---


### 2026-08-03 22:56 UTC

- **A1GWA7Ll** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.0274, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **vRNqQ8RA** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **blQkmeMR** (UNSUBMITTED, technical): Sharpe=1.53, Fitness=0.8, TO=0.4316, DD=0.0851。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **ak1Y0Ex1** (UNSUBMITTED, technical): Sharpe=0.2, Fitness=0.07, TO=0.0111, DD=0.3248。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **N1bwdndp** (UNSUBMITTED, technical): Sharpe=0.06, Fitness=0.01, TO=0.0074, DD=0.7599。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **pwNXbZeX** (UNSUBMITTED, technical): Sharpe=-0.38, Fitness=-0.3, TO=0.0446, DD=1.0283。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **vRNq7693** (UNSUBMITTED, technical): Sharpe=0.26, Fitness=0.1, TO=0.0137, DD=0.3102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **1Yp93ObW** (UNSUBMITTED, technical): Sharpe=-0.01, Fitness=-0.0, TO=0.0329, DD=0.6057。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **MPGWvqjr** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.011, DD=0.437。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **9qpv5gMq** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.02, TO=0.008, DD=0.4273。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **MPGWvRzr** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.09, TO=0.0091, DD=0.5562。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **6Xp86VYK** (UNSUBMITTED, technical): Sharpe=0.19, Fitness=0.07, TO=0.0096, DD=0.3436。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **KPG0A0NE** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.09, TO=0.0129, DD=0.3071。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **WjAq25jZ** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.1, TO=0.0604, DD=0.0865。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_total_goodwill_estimates_quarter / adv20, 126), currency)`
- **GrGa527J** (UNSUBMITTED, technical): Sharpe=0.18, Fitness=0.06, TO=0.0114, DD=0.3324。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **JjGwJArA** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.13, TO=0.0534, DD=0.1316。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_total_goodwill_estimates_quarter / adv20, 126), currency)`
- **xAN6powl** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.11, TO=0.0784, DD=0.0874。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_total_goodwill_estimates_quarter / adv20, 126), currency)`
- **RRm3wo0d** (UNSUBMITTED, technical): Sharpe=0.4, Fitness=0.13, TO=0.0422, DD=0.1。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_total_goodwill_estimates_quarter / adv20, 126), currency)`
- **O0GYXwN1** (UNSUBMITTED, analyst): Sharpe=0.47, Fitness=0.2, TO=0.0066, DD=0.1672。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **qMN1JkX2** (UNSUBMITTED, analyst): Sharpe=0.27, Fitness=0.09, TO=0.0072, DD=0.161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **omNp0weE** (UNSUBMITTED, analyst): Sharpe=0.36, Fitness=0.12, TO=0.0086, DD=0.1118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **0mpl2lar** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **88poZn7m** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.18, TO=0.0517, DD=0.0546。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **2rp0xv7b** (UNSUBMITTED, fundamental): Sharpe=0.2, Fitness=0.05, TO=0.0292, DD=0.0668。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **leWqY2Q7** (UNSUBMITTED, fundamental): Sharpe=0.9, Fitness=0.35, TO=0.0424, DD=0.0323。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(close,close,5),3),0.85),`
- **VkG9Lw9V** (UNSUBMITTED, fundamental): Sharpe=-0.16, Fitness=-0.02, TO=1.225, DD=0.5834。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense / dividend, 126), sector)`
- **gJ8A57NK** (UNSUBMITTED, fundamental): Sharpe=0.37, Fitness=0.11, TO=0.2151, DD=0.2226。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense / dividend, 126), sector)`
- **omNpXeYk** (UNSUBMITTED, fundamental): Sharpe=-0.15, Fitness=-0.02, TO=0.6397, DD=0.7754。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense / dividend, 126), sector)`
- **88poZo3V** (UNSUBMITTED, fundamental): Sharpe=-0.05, Fitness=-0.0, TO=0.9129, DD=0.6575。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense / dividend, 126), sector)`
- **P0GWbWEL** (UNSUBMITTED, fundamental): Sharpe=0.0, Fitness=0.0, TO=0.0216, DD=0.0919。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_median / single_sector_pureplay_company_count, 126), currency)`
- **MPGWnOZn** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.0, TO=0.0289, DD=0.1124。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebitda_median / single_sector_pureplay_company_count, 126), currency)`

---


### 2026-08-04 00:22 UTC

- **QPGkMq0X** (UNSUBMITTED, technical): Sharpe=0.22, Fitness=0.13, TO=0.0608, DD=0.7784。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **A1GZ9qjR** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **blQZXXrK** (UNSUBMITTED, technical): Sharpe=1.39, Fitness=0.75, TO=0.3703, DD=0.0856。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **78zbW7o5** (UNSUBMITTED, technical): Sharpe=0.85, Fitness=0.45, TO=0.1677, DD=0.1007。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **npNRxjk3** (UNSUBMITTED, technical): Sharpe=1.78, Fitness=0.8, TO=0.5039, DD=0.0496。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **88p95pOv** (UNSUBMITTED, technical): Sharpe=-0.32, Fitness=-0.23, TO=0.0452, DD=0.878。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **MPGRMpV9** (UNSUBMITTED, technical): Sharpe=0.06, Fitness=0.02, TO=0.0379, DD=0.4759。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **vRNMweoA** (UNSUBMITTED, technical): Sharpe=0.06, Fitness=0.02, TO=0.0308, DD=0.5017。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **MPGRMmJa** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.09, TO=0.0075, DD=0.4797。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **qMNr9MjV** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.0089, DD=0.3553。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **LLGaLQZm** (UNSUBMITTED, technical): Sharpe=0.79, Fitness=0.34, TO=0.0383, DD=0.0452。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_cashflow_financing_est / rel_num_all, 126), country)`
- **blQZlwVR** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.16, TO=0.0097, DD=0.3088。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **wpaxpkRl** (UNSUBMITTED, technical): Sharpe=0.86, Fitness=0.38, TO=0.0443, DD=0.0446。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_cashflow_financing_est / rel_num_all, 126), country)`
- **O0GP0Jav** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **ZYE3Yn1Y** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **9qp1qwr2** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.23, TO=0.0086, DD=0.3725。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **qMNrMgVV** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.11, TO=0.0323, DD=0.0487。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **1YpbYbzK** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.18, TO=0.0306, DD=0.0503。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **zqN6qZk1** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.05, TO=0.0293, DD=0.0642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **kqPrqqk6** (UNSUBMITTED, fundamental): Sharpe=0.34, Fitness=0.18, TO=0.0073, DD=0.4299。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **blQZY0KR** (UNSUBMITTED, fundamental): Sharpe=0.72, Fitness=0.38, TO=0.0553, DD=0.0765。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share_actual_value / low, 126), currency)`
- **qMNrK23P** (UNSUBMITTED, fundamental): Sharpe=0.84, Fitness=0.4, TO=0.0906, DD=0.0928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share_actual_value / low, 126), currency)`
- **vRNMK7rd** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.12, TO=0.5, DD=0.0669。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_sga_estimates_quarter / rel_ret_all, 126), currency)`
- **vRNMKo6Q** (UNSUBMITTED, fundamental): Sharpe=0.81, Fitness=0.42, TO=0.0888, DD=0.1061。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_sga_estimates_quarter / rel_ret_all, 126), currency)`
- **1Ypbq2lX** (UNSUBMITTED, fundamental): Sharpe=0.74, Fitness=0.36, TO=0.0674, DD=0.0896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(free_cash_flow_per_share_actual_value / low, 126), currency)`
- **P0GaJKpJ** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.12, TO=0.6016, DD=0.068。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_sga_estimates_quarter / rel_ret_all, 126), currency)`

---


### 2026-08-04 01:42 UTC

- **rK2gv5XE** (UNSUBMITTED, technical): Sharpe=1.01, Fitness=0.62, TO=0.2102, DD=0.0855。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **78zbEnP5** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **1YpbQmNX** (UNSUBMITTED, technical): Sharpe=1.03, Fitness=0.56, TO=0.0928, DD=0.042。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(cashflow_per_share_median_value / vwap, 126), sector)`
- **ak1ZqMgR** (UNSUBMITTED, technical): Sharpe=0.72, Fitness=1.04, TO=0.0033, DD=0.5161。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **XgoQ5X31** (UNSUBMITTED, technical): Sharpe=0.64, Fitness=0.27, TO=0.0484, DD=0.0718。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(investing_cashflow_reported_value / open, 126), sector)`
- **0mp30n91** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.14, TO=0.0675, DD=0.0939。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(investing_cashflow_reported_value / open, 126), sector)`
- **9qp1L0Vo** (UNSUBMITTED, technical): Sharpe=0.64, Fitness=0.35, TO=0.0627, DD=0.2132。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(cashflow_per_share_median_value / vwap, 126), sector)`
- **2rpzbbO5** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.18, TO=0.1026, DD=0.08。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(investing_cashflow_reported_value / open, 126), sector)`
- **VkGjg1kJ** (UNSUBMITTED, technical): Sharpe=0.51, Fitness=0.2, TO=0.0774, DD=0.0869。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(investing_cashflow_reported_value / open, 126), sector)`
- **3qprr8gz** (UNSUBMITTED, analyst): Sharpe=1.72, Fitness=1.14, TO=0.1539, DD=0.0437。满足基础提交门槛；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **LLGaa9w9** (UNSUBMITTED, fundamental): Sharpe=0.89, Fitness=0.49, TO=0.1473, DD=0.0926。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **XgoQQnwb** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.11, TO=0.0088, DD=0.3732。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **GrGAAnr3** (UNSUBMITTED, fundamental): Sharpe=0.1, Fitness=0.02, TO=0.0196, DD=0.3684。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **A1GZZg2e** (UNSUBMITTED, fundamental): Sharpe=0.17, Fitness=0.06, TO=0.0124, DD=0.4739。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **mL5RRzR2** (UNSUBMITTED, fundamental): Sharpe=0.11, Fitness=0.03, TO=0.0073, DD=0.5018。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **0mp33o28** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0112, DD=0.2806。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **YPvKKZkv** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0103, DD=0.3121。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_part,rel_num_part,5),3),0.85),`
- **3qprrbrN** (UNSUBMITTED, fundamental): Sharpe=0.78, Fitness=0.47, TO=0.0277, DD=0.1008。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_avg / rel_num_comp, 126), exchange)`
- **xAN8866N** (UNSUBMITTED, fundamental): Sharpe=0.99, Fitness=0.5, TO=0.028, DD=0.0796。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_avg / rel_num_comp, 126), exchange)`
- **LLGaj00v** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0147, DD=0.4584。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **58p0b1oN** (UNSUBMITTED, fundamental): Sharpe=0.92, Fitness=0.5, TO=0.0328, DD=0.061。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_avg / rel_num_comp, 126), exchange)`
- **LLGaj2an** (UNSUBMITTED, fundamental): Sharpe=0.83, Fitness=0.38, TO=0.0486, DD=0.0978。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(book_value_per_share_avg / rel_num_comp, 126), exchange)`

---


### 2026-08-04 03:40 UTC

- **YPvKkLVl** (UNSUBMITTED, news): Sharpe=0.0, Fitness=None, TO=0.0, DD=0.0。模拟失败或数据缺失；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **ak1ZMxp1** (UNSUBMITTED, technical): Sharpe=1.72, Fitness=0.86, TO=0.5304, DD=0.0808。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **2rpzQNeP** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **GrGAY8A3** (UNSUBMITTED, technical): Sharpe=0.71, Fitness=0.53, TO=0.0087, DD=0.2928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **QPGkqdag** (UNSUBMITTED, technical): Sharpe=0.7, Fitness=0.51, TO=0.0126, DD=0.3308。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **2rpzQzJZ** (UNSUBMITTED, technical): Sharpe=0.69, Fitness=0.5, TO=0.0103, DD=0.3348。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **78zbq6lx** (UNSUBMITTED, technical): Sharpe=0.05, Fitness=0.01, TO=0.0092, DD=0.2924。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **mL5R2gLK** (UNSUBMITTED, technical): Sharpe=0.06, Fitness=0.01, TO=0.008, DD=0.3078。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **zqN6wjdV** (UNSUBMITTED, fundamental): Sharpe=0.39, Fitness=0.22, TO=0.0077, DD=0.3974。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **YPvKXVPv** (UNSUBMITTED, fundamental): Sharpe=0.32, Fitness=0.08, TO=0.0374, DD=0.0495。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **6XpVgpwK** (UNSUBMITTED, fundamental): Sharpe=0.34, Fitness=0.19, TO=0.0066, DD=0.448。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **gJ8O79LK** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.24, TO=0.0085, DD=0.3749。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **KPGdx62p** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.19, TO=0.0052, DD=0.4289。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **88p9gknm** (UNSUBMITTED, fundamental): Sharpe=0.4, Fitness=0.21, TO=0.0115, DD=0.3491。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **1Ypb6QMQ** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.06, TO=0.0303, DD=0.0679。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **wpaxXqxl** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.18, TO=0.0118, DD=0.3654。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **LLGaer3a** (UNSUBMITTED, fundamental): Sharpe=0.31, Fitness=0.15, TO=0.0113, DD=0.4188。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **pwNr0jqj** (UNSUBMITTED, fundamental): Sharpe=0.35, Fitness=0.18, TO=0.0097, DD=0.4012。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **MPGRwXpz** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.15, TO=0.0073, DD=0.5618。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **d5ZVqwNj** (UNSUBMITTED, fundamental): Sharpe=0.36, Fitness=0.2, TO=0.0089, DD=0.4606。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(single_sector_pureplay_company_count,single_sector_pureplay_company_count,5),...`
- **omN52ee5** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.18, TO=0.0091, DD=0.4678。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **j26RLboW** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.13, TO=0.0075, DD=0.5698。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`

---


### 2026-08-04 05:20 UTC

- **1YpbpmdQ** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0909, DD=0.6614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **e73wxwpN** (UNSUBMITTED, technical): Sharpe=1.19, Fitness=0.7, TO=0.2746, DD=0.1343。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **9qp17Zo1** (UNSUBMITTED, technical): Sharpe=1.79, Fitness=0.82, TO=0.6419, DD=0.0744。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **wpaxloE2** (UNSUBMITTED, technical): Sharpe=0.76, Fitness=0.4, TO=0.1507, DD=0.1057。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **npNR2Akq** (UNSUBMITTED, technical): Sharpe=0.64, Fitness=0.4, TO=0.152, DD=0.1408。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **vRNMLAd3** (UNSUBMITTED, technical): Sharpe=0.08, Fitness=0.01, TO=0.0089, DD=0.2605。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **YPvKpbG6** (UNSUBMITTED, technical): Sharpe=0.65, Fitness=0.72, TO=0.2136, DD=0.7283。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **3qpr7zvX** (UNSUBMITTED, technical): Sharpe=0.03, Fitness=0.0, TO=0.0077, DD=0.3323。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **RRmQp0La** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.1, TO=0.0804, DD=0.0819。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_avg / adv20, 126), currency)`
- **JjGEpl7O** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.12, TO=0.0701, DD=0.0992。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_avg / adv20, 126), currency)`
- **vRNMLqLa** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.09, TO=0.0621, DD=0.0846。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_avg / adv20, 126), currency)`
- **blQZ9mjq** (UNSUBMITTED, technical): Sharpe=0.31, Fitness=0.11, TO=0.0549, DD=0.1334。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(total_goodwill_avg / adv20, 126), currency)`
- **VkGj8LE5** (UNSUBMITTED, analyst): Sharpe=1.47, Fitness=1.0, TO=0.0923, DD=0.0491。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_eps / close, 126), industry)`
- **rK2gWzA9** (UNSUBMITTED, fundamental): Sharpe=1.11, Fitness=0.53, TO=0.2431, DD=0.0984。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **QPGkE3Ap** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.025, DD=0.2403。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **vRNMd9Ed** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.07, TO=0.0294, DD=0.1896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **vRNMdxmG** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0207, DD=0.2814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **6XpVR5RO** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0107, DD=0.3174。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **omN5nWwn** (UNSUBMITTED, fundamental): Sharpe=0.52, Fitness=0.18, TO=0.0415, DD=0.046。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_pretax_income_est / split, 126), subindustry)`
- **d5ZVnb9Y** (UNSUBMITTED, fundamental): Sharpe=0.27, Fitness=0.12, TO=0.0132, DD=0.2803。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **2rpzvplx** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.17, TO=0.0164, DD=0.1836。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **zqN655ME** (UNSUBMITTED, fundamental): Sharpe=1.07, Fitness=0.61, TO=0.0607, DD=0.064。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_adj_net_income_quarterly_estimate / sharesout, 126), subindustry)`
- **88p9OObm** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.16, TO=0.0422, DD=0.0415。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_pretax_income_est / split, 126), subindustry)`
- **RRmQN2Xd** (UNSUBMITTED, fundamental): Sharpe=0.95, Fitness=0.48, TO=0.0418, DD=0.0722。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_adj_net_income_quarterly_estimate / sharesout, 126), subindustry)`
- **blQZN7X6** (UNSUBMITTED, fundamental): Sharpe=0.98, Fitness=0.52, TO=0.0619, DD=0.0658。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_adj_net_income_quarterly_estimate / sharesout, 126), subindustry)`

---


### 2026-08-04 06:35 UTC

- **O0GPWARg** (UNSUBMITTED, technical): Sharpe=0.67, Fitness=0.98, TO=0.1266, DD=0.743。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **E5GWQwr1** (UNSUBMITTED, technical): Sharpe=0.48, Fitness=0.29, TO=0.0736, DD=0.138。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **9qp1x5Ax** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.05, TO=0.0073, DD=0.5305。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **vRNM1xZr** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.04, TO=0.0083, DD=0.4716。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **RRmQAxVa** (UNSUBMITTED, technical): Sharpe=0.11, Fitness=0.03, TO=0.0059, DD=0.5587。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **78zbo3gO** (UNSUBMITTED, technical): Sharpe=0.12, Fitness=0.03, TO=0.0091, DD=0.4315。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **9qp1Ejxq** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.17, TO=0.038, DD=0.0739。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_free_cashflow_est / single_sector_pureplay_company_count, 126), sector)`
- **wpax9wAY** (UNSUBMITTED, fundamental): Sharpe=0.83, Fitness=0.15, TO=0.738, DD=0.0673。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actual_sales_value_annual / rel_ret_part, 126), subindustry)`
- **mL5R6n29** (UNSUBMITTED, fundamental): Sharpe=0.76, Fitness=0.15, TO=0.5575, DD=0.0626。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actual_sales_value_annual / rel_ret_part, 126), subindustry)`
- **QPGkK0eG** (UNSUBMITTED, fundamental): Sharpe=0.93, Fitness=0.23, TO=0.4839, DD=0.0573。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actual_sales_value_annual / rel_ret_part, 126), subindustry)`
- **0mp3rMLq** (UNSUBMITTED, fundamental): Sharpe=0.56, Fitness=0.74, TO=0.0377, DD=0.8115。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / single_sector_pureplay_company_count, 126), sector)`
- **0mp3rE9r** (UNSUBMITTED, fundamental): Sharpe=-0.1, Fitness=-0.02, TO=0.0245, DD=0.1028。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / single_sector_pureplay_company_count, 126), sector)`
- **YPvKMmwA** (UNSUBMITTED, fundamental): Sharpe=0.41, Fitness=0.15, TO=0.023, DD=0.0851。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_free_cashflow_est / single_sector_pureplay_company_count, 126), sector)`
- **vRNM293w** (UNSUBMITTED, fundamental): Sharpe=0.42, Fitness=0.16, TO=0.0234, DD=0.1203。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_free_cashflow_est / single_sector_pureplay_company_count, 126), sector)`
- **A1GZvdEg** (UNSUBMITTED, fundamental): Sharpe=-0.26, Fitness=-0.07, TO=0.0386, DD=0.104。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_max / single_sector_pureplay_company_count, 126), sector)`

---


### 2026-08-04 08:23 UTC

- **JjGE9q8x** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.13, TO=0.0805, DD=0.6701。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **blQZmV6m** (UNSUBMITTED, technical): Sharpe=1.3, Fitness=0.65, TO=0.2947, DD=0.0799。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **RRmQxz3j** (UNSUBMITTED, technical): Sharpe=0.49, Fitness=0.29, TO=0.0794, DD=0.1402。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **3qprm0zO** (UNSUBMITTED, technical): Sharpe=-0.17, Fitness=-0.06, TO=0.0066, DD=0.4632。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **rK2gaRqJ** (UNSUBMITTED, technical): Sharpe=2.18, Fitness=0.58, TO=1.3143, DD=0.0439。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **gJ8OVxmJ** (UNSUBMITTED, technical): Sharpe=0.08, Fitness=0.02, TO=0.01, DD=0.3162。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **E5GWP7Jm** (UNSUBMITTED, technical): Sharpe=-0.04, Fitness=-0.01, TO=0.0091, DD=0.3567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **xAN8ol5m** (UNSUBMITTED, technical): Sharpe=-0.07, Fitness=-0.01, TO=0.008, DD=0.399。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **blQZgNqq** (UNSUBMITTED, technical): Sharpe=0.73, Fitness=0.56, TO=0.0126, DD=0.3565。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **LLGa2EqM** (UNSUBMITTED, technical): Sharpe=0.79, Fitness=0.63, TO=0.0087, DD=0.3072。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **P0GaAORM** (UNSUBMITTED, analyst): Sharpe=0.06, Fitness=0.01, TO=0.006, DD=0.379。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **qMNrw6XP** (UNSUBMITTED, analyst): Sharpe=-0.09, Fitness=-0.03, TO=0.0366, DD=0.59。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **blQZKLlq** (UNSUBMITTED, technical): Sharpe=0.75, Fitness=0.57, TO=0.0103, DD=0.3425。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **RRmQvZzd** (UNSUBMITTED, analyst): Sharpe=0.06, Fitness=0.01, TO=0.0052, DD=0.4559。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_cust,rel_num_cust,5),3),0.85),`
- **P0GaAdvw** (UNSUBMITTED, analyst): Sharpe=0.64, Fitness=0.88, TO=0.0037, DD=0.6732。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **GrGA7a1J** (UNSUBMITTED, analyst): Sharpe=-0.09, Fitness=-0.02, TO=0.0065, DD=0.4429。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **E5GWxPdR** (UNSUBMITTED, analyst): Sharpe=0.09, Fitness=0.02, TO=0.0083, DD=0.2829。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **rK2gVzLm** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.04, TO=0.0219, DD=0.3858。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **qMNr3v5P** (UNSUBMITTED, fundamental): Sharpe=-0.03, Fitness=-0.0, TO=0.0188, DD=0.5441。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **N1bm3oJw** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.04, TO=0.0227, DD=0.3079。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`

---


### 2026-08-04 10:06 UTC

- **npNMzOoM** (UNSUBMITTED, news): Sharpe=-0.13, Fitness=-0.09, TO=0.027, DD=1.411。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **P0Gdqgjw** (UNSUBMITTED, technical): Sharpe=0.23, Fitness=0.12, TO=0.0988, DD=0.6543。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **omNMANrE** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.66, TO=0.2447, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **QPGLrzW5** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.4, TO=0.1354, DD=0.1434。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **zqN1w5ZG** (UNSUBMITTED, technical): Sharpe=2.19, Fitness=0.82, TO=0.8274, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **A1GMqL3Y** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.04, TO=0.0175, DD=0.2767。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **d5ZAegAK** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.31, TO=0.1249, DD=0.108。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sg_and_a_expense_avg / open, 126), subindustry)`
- **vRN3aazw** (UNSUBMITTED, technical): Sharpe=0.1, Fitness=0.03, TO=0.011, DD=0.3364。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **wpaMXqK1** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.29, TO=0.135, DD=0.1196。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sg_and_a_expense_avg / open, 126), subindustry)`
- **LLGAeQna** (UNSUBMITTED, technical): Sharpe=0.12, Fitness=0.03, TO=0.0128, DD=0.3146。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_cust,rel_ret_cust,5),3),0.85),`
- **88pdAE0v** (UNSUBMITTED, technical): Sharpe=0.42, Fitness=0.19, TO=0.0963, DD=0.1103。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sg_and_a_expense_avg / open, 126), subindustry)`
- **3qpZdk66** (UNSUBMITTED, technical): Sharpe=0.56, Fitness=0.27, TO=0.1155, DD=0.131。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sg_and_a_expense_avg / open, 126), subindustry)`
- **rK2vk2V3** (UNSUBMITTED, analyst): Sharpe=0.74, Fitness=0.34, TO=0.0612, DD=0.125。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ebitda / rel_num_comp, 126), sector)`
- **QPGLelqp** (UNSUBMITTED, analyst): Sharpe=0.7, Fitness=0.37, TO=0.0421, DD=0.1018。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ebitda / rel_num_comp, 126), sector)`
- **6XpvxmpL** (UNSUBMITTED, fundamental): Sharpe=0.62, Fitness=0.89, TO=0.0707, DD=0.7646。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **O0GEvM2g** (UNSUBMITTED, analyst): Sharpe=0.68, Fitness=0.32, TO=0.06, DD=0.1447。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ebitda / rel_num_comp, 126), sector)`
- **ak1q3aMO** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.11, TO=0.0141, DD=0.4134。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **2rpbkMNb** (UNSUBMITTED, fundamental): Sharpe=0.05, Fitness=0.01, TO=0.0115, DD=0.2992。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **88pd1Jlq** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.13, TO=0.0115, DD=0.4632。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **E5GXJEX0** (UNSUBMITTED, fundamental): Sharpe=0.16, Fitness=0.05, TO=0.0076, DD=0.2883。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **vRN33LPa** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.03, TO=0.0091, DD=0.3102。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **zqN11wOX** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0095, DD=0.5234。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_num_comp,rel_num_comp,5),3),0.85),`
- **d5ZAA5LE** (UNSUBMITTED, fundamental): Sharpe=-0.05, Fitness=-0.01, TO=0.0118, DD=0.3232。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_part,rel_ret_part,5),3),0.85),`
- **j26bRkMQ** (UNSUBMITTED, fundamental): Sharpe=0.54, Fitness=0.2, TO=0.0489, DD=0.109。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense_reported_value / rel_num_cust, 126), exchange)`
- **leWbONA7** (UNSUBMITTED, fundamental): Sharpe=0.3, Fitness=0.1, TO=0.0283, DD=0.0853。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense_reported_value / rel_num_cust, 126), exchange)`
- **blQ5ZA36** (UNSUBMITTED, fundamental): Sharpe=0.62, Fitness=0.24, TO=0.0315, DD=0.0816。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(selling_general_admin_expense_reported_value / rel_num_cust, 126), exchange)`

---


### 2026-08-04 12:18 UTC

- **KPGjmvoN** (UNSUBMITTED, news): Sharpe=-0.19, Fitness=-0.11, TO=0.0188, DD=0.496。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **LLGA5Z81** (UNSUBMITTED, news): Sharpe=0.18, Fitness=0.09, TO=0.0132, DD=0.3141。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(ts_std_dev(ts_delta(log(ts_mean(vec_avg(mws54_eventcallbasicinfo_postponedflag), 20)), 5), 50))`
- **RRmn658a** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.12, TO=0.1332, DD=0.6335。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **WjA6eXZQ** (UNSUBMITTED, technical): Sharpe=0.74, Fitness=0.18, TO=0.4994, DD=0.117。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(volume / adv20)`
- **N1bvaQKE** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.0087, DD=0.3551。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **zqN1Y7GR** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.09, TO=0.0075, DD=0.4796。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adv20,adv20,5),3),0.85),`
- **e73o9Wnp** (UNSUBMITTED, technical): Sharpe=0.54, Fitness=0.36, TO=0.0102, DD=0.3516。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **gJ8EQ1lv** (UNSUBMITTED, technical): Sharpe=0.6, Fitness=0.42, TO=0.0074, DD=0.3174。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **leWbj9j2** (UNSUBMITTED, technical): Sharpe=0.15, Fitness=0.04, TO=0.0097, DD=0.2139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **mL5MjoR5** (UNSUBMITTED, technical): Sharpe=0.03, Fitness=0.0, TO=0.008, DD=0.3069。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **KPGj7kjj** (UNSUBMITTED, technical): Sharpe=-0.13, Fitness=-0.03, TO=0.0065, DD=0.4557。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **wpaMjnov** (UNSUBMITTED, technical): Sharpe=0.61, Fitness=0.21, TO=0.0277, DD=0.0593。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **LLGA7e0m** (UNSUBMITTED, technical): Sharpe=0.2, Fitness=0.05, TO=0.0198, DD=0.064。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **9qpLp5Zo** (UNSUBMITTED, technical): Sharpe=0.67, Fitness=0.24, TO=0.0262, DD=0.0659。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **A1GMGe6E** (UNSUBMITTED, technical): Sharpe=0.08, Fitness=0.01, TO=0.0092, DD=0.2362。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(low,low,5),3),0.85),`
- **wpaMabXx** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.09, TO=0.0229, DD=0.0599。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **A1GMGg6R** (UNSUBMITTED, technical): Sharpe=0.13, Fitness=0.04, TO=0.0321, DD=0.3419。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **RRmnmnga** (UNSUBMITTED, technical): Sharpe=0.37, Fitness=0.11, TO=0.0255, DD=0.1074。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **pwNANYzv** (UNSUBMITTED, technical): Sharpe=0.21, Fitness=0.05, TO=0.0207, DD=0.1231。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **j26brPpW** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.16, TO=0.0097, DD=0.3088。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **j26brz3o** (UNSUBMITTED, technical): Sharpe=0.07, Fitness=0.02, TO=0.0061, DD=0.6928。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **MPGoQr79** (UNSUBMITTED, technical): Sharpe=0.27, Fitness=0.12, TO=0.0089, DD=0.3553。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **E5GXENLJ** (UNSUBMITTED, technical): Sharpe=0.36, Fitness=0.1, TO=0.029, DD=0.0896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **omNMlE2m** (UNSUBMITTED, technical): Sharpe=-0.5, Fitness=-0.31, TO=0.021, DD=0.68。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **O0GEZ7k7** (UNSUBMITTED, technical): Sharpe=0.3, Fitness=0.09, TO=0.0179, DD=0.1042。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **88pdLwOz** (UNSUBMITTED, fundamental): Sharpe=-0.04, Fitness=-0.0, TO=0.0277, DD=0.1209。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **78zEdl02** (UNSUBMITTED, fundamental): Sharpe=0.07, Fitness=0.01, TO=0.031, DD=0.1183。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **78zEdmpv** (UNSUBMITTED, fundamental): Sharpe=-0.1, Fitness=-0.02, TO=0.0228, DD=0.1319。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **xAN0RLKN** (UNSUBMITTED, fundamental): Sharpe=0.28, Fitness=0.11, TO=0.0128, DD=0.2796。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **qMNogxR1** (UNSUBMITTED, fundamental): Sharpe=0.32, Fitness=0.13, TO=0.0089, DD=0.2428。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **wpaMLep6** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.12, TO=0.0185, DD=0.2659。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`

---


### 2026-08-04 12:45 UTC

- **VkGgzVaG** (UNSUBMITTED, analyst): Sharpe=-0.21, Fitness=-0.06, TO=0.1922, DD=0.4358。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ffo / dividend, 126), country)`
- **zqN1GZpd** (UNSUBMITTED, technical): Sharpe=0.59, Fitness=0.84, TO=0.06, DD=0.7969。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_mean(returns, 33))`
- **P0GdYNQq** (UNSUBMITTED, analyst): Sharpe=-0.34, Fitness=-0.11, TO=0.6408, DD=1.0976。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ffo / dividend, 126), country)`
- **blQ5J076** (UNSUBMITTED, fundamental): Sharpe=0.13, Fitness=0.04, TO=0.0304, DD=0.3042。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_rnd_expense_est / sharesout, 126), currency)`
- **e73oNEEd** (UNSUBMITTED, analyst): Sharpe=-0.36, Fitness=-0.07, TO=1.0408, DD=0.5752。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(est_ffo / dividend, 126), country)`
- **pwNAxagv** (UNSUBMITTED, fundamental): Sharpe=0.65, Fitness=0.93, TO=0.0253, DD=0.6972。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(pretax_income_median / split, 126), country)`
- **N1bvLNZo** (UNSUBMITTED, fundamental): Sharpe=0.82, Fitness=0.44, TO=0.0461, DD=0.0575。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(pretax_income_median / split, 126), country)`
- **JjGZoGLn** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.06, TO=0.0377, DD=0.1054。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_rnd_expense_est / sharesout, 126), currency)`
- **A1GMePXY** (UNSUBMITTED, fundamental): Sharpe=0.12, Fitness=0.04, TO=0.0231, DD=0.4803。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(num_rnd_expense_est / sharesout, 126), currency)`
- **MPGodkk8** (UNSUBMITTED, fundamental): Sharpe=0.91, Fitness=0.57, TO=0.0438, DD=0.0814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(pretax_income_median / split, 126), country)`

---


### 2026-08-04 14:45 UTC

- **WjA6vgNx** (UNSUBMITTED, technical): Sharpe=1.1, Fitness=0.66, TO=0.2447, DD=0.1492。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)`
- **RRmngJNz** (UNSUBMITTED, technical): Sharpe=2.18, Fitness=0.58, TO=1.3143, DD=0.0439。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **88pd0OEl** (UNSUBMITTED, technical): Sharpe=0.73, Fitness=0.56, TO=0.0117, DD=0.3569。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **Xgo5Z7W8** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.04, TO=0.0114, DD=0.3324。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **1YpQ3ogJ** (UNSUBMITTED, technical): Sharpe=0.11, Fitness=0.03, TO=0.0086, DD=0.3669。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **wpaM7qg5** (UNSUBMITTED, technical): Sharpe=0.14, Fitness=0.04, TO=0.0102, DD=0.3425。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **xAN0p7db** (UNSUBMITTED, analyst): Sharpe=-0.05, Fitness=-0.01, TO=0.0243, DD=0.6347。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **1YpQA0JQ** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0294, DD=0.5053。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **ak1q972R** (UNSUBMITTED, analyst): Sharpe=-0.02, Fitness=-0.0, TO=0.0367, DD=0.5207。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **1YpQAzAM** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0132, DD=0.4567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **RRmnoKg0** (UNSUBMITTED, fundamental): Sharpe=0.26, Fitness=0.1, TO=0.0241, DD=0.3029。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **QPGLAvVr** (UNSUBMITTED, fundamental): Sharpe=0.14, Fitness=0.04, TO=0.0325, DD=0.3173。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **ZYEe9AJj** (UNSUBMITTED, fundamental): Sharpe=-0.3, Fitness=-0.12, TO=0.0061, DD=0.3207。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **blQ5KvXp** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.07, TO=0.0111, DD=0.4642。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **78zE2KlZ** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.12, TO=0.0071, DD=0.2931。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **qMNowvzK** (UNSUBMITTED, fundamental): Sharpe=-0.33, Fitness=-0.11, TO=0.0087, DD=0.231。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(returns,returns,5),3),0.85),`
- **1YpQ0an6** (UNSUBMITTED, fundamental): Sharpe=0.15, Fitness=0.05, TO=0.0156, DD=0.3917。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(rel_ret_all,rel_ret_all,5),3),0.85),`
- **WjA6JWLZ** (UNSUBMITTED, fundamental): Sharpe=0.04, Fitness=0.0, TO=0.0377, DD=0.3043。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(volume,volume,5),3),0.85),`
- **QPGL6qb5** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0192, DD=0.3203。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **qMNo3XJP** (UNSUBMITTED, fundamental): Sharpe=0.24, Fitness=0.12, TO=0.0094, DD=0.568。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **qMNo3Pmj** (UNSUBMITTED, fundamental): Sharpe=0.25, Fitness=0.09, TO=0.0163, DD=0.3183。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`
- **xAN0WX6W** (UNSUBMITTED, fundamental): Sharpe=0.19, Fitness=0.06, TO=0.0213, DD=0.2788。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(sharesout,sharesout,5),3),0.85),`

---


### 2026-08-04 16:21 UTC

- **2rpdEEY5** (UNSUBMITTED, technical): Sharpe=0.24, Fitness=0.13, TO=0.0736, DD=0.6757。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_std_dev(returns, 20))`
- **1YpEve7W** (UNSUBMITTED, technical): Sharpe=1.14, Fitness=0.65, TO=0.2673, DD=0.0968。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(returns * volume / adv20, 5))`
- **xANga7dW** (UNSUBMITTED, technical): Sharpe=0.94, Fitness=0.49, TO=0.1923, DD=0.0972。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **kqPl50AK** (UNSUBMITTED, technical): Sharpe=2.19, Fitness=0.82, TO=0.8274, DD=0.064。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank((high + low) / 2 - close)`
- **j26mQdbj** (UNSUBMITTED, technical): Sharpe=0.51, Fitness=0.19, TO=0.026, DD=0.0813。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **gJ8pzqe0** (UNSUBMITTED, technical): Sharpe=0.47, Fitness=0.17, TO=0.0185, DD=0.0683。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **d5ZLwwQK** (UNSUBMITTED, technical): Sharpe=0.34, Fitness=0.1, TO=0.0227, DD=0.0914。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **vRNgVqZQ** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.14, TO=0.4644, DD=0.097。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_median / volume, 126), market)`
- **RRmWLRX1** (UNSUBMITTED, technical): Sharpe=0.26, Fitness=0.08, TO=0.0146, DD=0.1304。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **2rpdk1mY** (UNSUBMITTED, technical): Sharpe=0.66, Fitness=0.17, TO=0.454, DD=0.1077。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_median / volume, 126), market)`
- **P0G99z7w** (UNSUBMITTED, technical): Sharpe=0.77, Fitness=0.24, TO=0.441, DD=0.1099。换手偏高，需增大 decay 或混合稳定信号；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(ebit_median / volume, 126), market)`
- **78z99mQ1** (UNSUBMITTED, analyst): Sharpe=0.18, Fitness=0.07, TO=0.0089, DD=0.4197。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **vRNggYAQ** (UNSUBMITTED, analyst): Sharpe=0.03, Fitness=0.0, TO=0.0062, DD=0.6083。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **1YpEEXV6** (UNSUBMITTED, analyst): Sharpe=0.22, Fitness=0.08, TO=0.0093, DD=0.3657。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **RRmWWjlj** (UNSUBMITTED, analyst): Sharpe=0.0, Fitness=0.0, TO=0.0077, DD=0.3305。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **RRmWnzZa** (UNSUBMITTED, analyst): Sharpe=-0.18, Fitness=-0.06, TO=0.0062, DD=0.5118。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **2rpdbL7J** (UNSUBMITTED, analyst): Sharpe=0.15, Fitness=0.05, TO=0.0076, DD=0.4908。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **xANg0nKb** (UNSUBMITTED, analyst): Sharpe=0.05, Fitness=0.01, TO=0.0089, DD=0.2591。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **Xgo6Qab5** (UNSUBMITTED, fundamental): Sharpe=0.82, Fitness=0.47, TO=0.115, DD=0.0745。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_zscore(enterprise_value / ebitda, 63))`
- **88p19qpa** (UNSUBMITTED, fundamental): Sharpe=0.21, Fitness=0.05, TO=0.0293, DD=0.0643。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **vRNgq1zz** (UNSUBMITTED, fundamental): Sharpe=0.38, Fitness=0.2, TO=0.0081, DD=0.3506。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **VkGJ9pNV** (UNSUBMITTED, fundamental): Sharpe=0.81, Fitness=0.3, TO=0.0301, DD=0.0308。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(split,split,5),3),0.85),`
- **KPGa0jP1** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.25, TO=0.0097, DD=0.3047。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(dividend,dividend,5),3),0.85),`
- **MPGmWR16** (UNSUBMITTED, fundamental): Sharpe=-0.22, Fitness=-0.05, TO=0.0126, DD=0.1147。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actuals_value_currency_code / primary_sector_focused_company_count, 126), subindustry)`
- **GrGJP2kx** (UNSUBMITTED, fundamental): Sharpe=-0.15, Fitness=-0.03, TO=0.015, DD=0.0903。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actuals_value_currency_code / primary_sector_focused_company_count, 126), subindustry)`
- **Xgo6Gvd1** (UNSUBMITTED, fundamental): Sharpe=-0.31, Fitness=-0.08, TO=0.0107, DD=0.1614。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actuals_value_currency_code / primary_sector_focused_company_count, 126), subindustry)`
- **88p1bERz** (UNSUBMITTED, fundamental): Sharpe=-0.15, Fitness=-0.03, TO=0.0139, DD=0.0967。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(actuals_value_currency_code / primary_sector_focused_company_count, 126), subindustry)`

---


### 2026-08-04 17:19 UTC

- **xANgPRKN** (UNSUBMITTED, technical): Sharpe=0.62, Fitness=0.88, TO=0.0701, DD=0.7561。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(-ts_decay_linear(close / vwap, 10))`
- **xANgz2Xw** (UNSUBMITTED, technical): Sharpe=-0.08, Fitness=-0.02, TO=0.0296, DD=0.4349。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **88p16Gjm** (UNSUBMITTED, technical): Sharpe=-0.5, Fitness=-0.3, TO=0.0229, DD=0.6808。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **YPvqkMOM** (UNSUBMITTED, technical): Sharpe=-0.01, Fitness=-0.0, TO=0.0352, DD=0.4343。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **O0GamNd1** (UNSUBMITTED, technical): Sharpe=0.88, Fitness=0.52, TO=0.0639, DD=0.0476。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_reported_pretax_profit_quarterly_estimate / low, 126), country)`
- **mL59zX51** (UNSUBMITTED, technical): Sharpe=0.96, Fitness=0.55, TO=0.0727, DD=0.0508。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_reported_pretax_profit_quarterly_estimate / low, 126), country)`
- **QPGXlnxK** (UNSUBMITTED, technical): Sharpe=1.05, Fitness=0.57, TO=0.0907, DD=0.0567。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(max_reported_pretax_profit_quarterly_estimate / low, 126), country)`
- **1YpEL7E6** (UNSUBMITTED, fundamental): Sharpe=0.01, Fitness=0.0, TO=0.0182, DD=0.4139。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **xANgQ9jW** (UNSUBMITTED, fundamental): Sharpe=0.18, Fitness=0.05, TO=0.0207, DD=0.2814。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **xANgQAxn** (UNSUBMITTED, fundamental): Sharpe=0.45, Fitness=0.25, TO=0.0098, DD=0.3418。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **6XpO3w1L** (UNSUBMITTED, fundamental): Sharpe=0.33, Fitness=0.18, TO=0.0059, DD=0.4065。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(adjfactor,adjfactor,5),3),0.85),`
- **mL59JXJE** (UNSUBMITTED, fundamental): Sharpe=0.61, Fitness=0.85, TO=0.0111, DD=0.6723。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **Xgo6PLdb** (UNSUBMITTED, fundamental): Sharpe=0.58, Fitness=0.24, TO=0.0402, DD=0.0918。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(shareholders_equity_avg / adjfactor, 126), sector)`
- **j26mWlao** (UNSUBMITTED, fundamental): Sharpe=1.08, Fitness=0.49, TO=0.0607, DD=0.0331。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_standard_deviation / rel_num_comp, 126), subindustry)`
- **gJ8pwpVO** (UNSUBMITTED, fundamental): Sharpe=0.22, Fitness=0.07, TO=0.0294, DD=0.1896。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`rank(trade_when(greater(ts_mean(ts_corr(open,open,5),3),0.85),`
- **ak1vMjmO** (UNSUBMITTED, fundamental): Sharpe=0.51, Fitness=0.18, TO=0.0468, DD=0.0957。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(shareholders_equity_avg / adjfactor, 126), sector)`
- **JjGKYjbl** (UNSUBMITTED, fundamental): Sharpe=0.93, Fitness=0.42, TO=0.058, DD=0.0497。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_standard_deviation / rel_num_comp, 126), subindustry)`
- **VkGJwANA** (UNSUBMITTED, fundamental): Sharpe=1.25, Fitness=0.58, TO=0.0692, DD=0.0272。指标一般，需继续优化；暂无 ACTIVE alpha 可比相关
  - 表达式：`group_rank(ts_rank(sales_estimate_standard_deviation / rel_num_comp, 126), subindustry)`

---

