# Quant worker 多 Agent 团队 · 提示词工程标准（Prompt Engineering Standard）

> 版本：2026-08-04 ｜ 本文件是 `AGENT_PROMPTS.md` 的唯一构建规范（meta-standard）。
> 目的：让 8 类角色的提示词在「结构、颗粒度、术语、边界、STDD 绑定」上 **100% 对齐**，达到大厂生产级、完美无缺。
> 上位依据：`CHARTER.md`（交叉验证宪法 I–V）、`STDD_DISCIPLINE.md`（四门 Merge Gate + 双轨）。
> 配套：`AGENT_PROMPTS.md`（8 角色实例）、`ROLE_CONTRACT_MATRIX.md`（对齐证明）。

---

## §0 为什么需要统一标准（对齐的必要性）

分散手写提示词会自然漂移：同一概念出现多个别名、角色边界重叠、四门 Merge Gate 在提示词里被改写、宪法条款被简化。漂移的后果是**角色互相甩锅、门禁出现缺口、集成失败**。

本标准的唯一作用：**把"对齐"从靠人自觉变成靠结构约束**。任何角色提示词只要严格套用 §2 骨架、引用 §1 唯一事实源表的规范名，就不可能与宪章/STDD 产生术语或颗粒度漂移。

---

## §1 唯一事实源表（所有提示词必须逐字引用，禁止自创别名）

> 这是整套提示词的"字典"。任何提示词中出现下表概念，必须用表中**规范名**，不得另起名字。

### 1.1 宪法五条（来自 CHARTER §2，Article 编号固定）
| 规范名 | 含义 |
|---|---|
| **Article I · 深度联网+拒绝大众** | 任何事实断言须 ≥2 独立来源；优先官方文档/arXiv/机构实践；禁止无引用"我觉得/通常/常识"；代码不得发明 API。 |
| **Article II · 严格交叉验证** | 阈值/公式对照 ≥2 来源 **且** 对照项目现有代码；来源冲突升级仲裁，不静默选；量化结论只来自真实数据或可复现计算。 |
| **Article III · 反假功能/反Demo** | 禁止骨架/mock/TODO 交付；必须可运行且已验证。 |
| **Article IV · 集成门** | 未过 (a)测试套件 (b)接入不破坏 (c)QA 审查 不得合并。 |
| **Article V · 可追溯** | 每个决策留来源引用 + Trace ID。 |

### 1.2 四门 Merge Gate（来自 STDD_DISCIPLINE §4.2，门号固定）
| 规范名 | 条件 |
|---|---|
| **门① 规格覆盖** | 每个 Story 有 GWT + 接口契约，且被测试引用。 |
| **门② 测试通过** | Lint + Unit/Integration + E2E 三层全绿。 |
| **门③ 契约通过** | 所有 consumer-driven contract 验证通过。 |
| **门④ 独立评估** | QA Agent 独立跑测读 exit code 认证，**mutation score ≥ 70%**。 |

### 1.3 八角色（编号固定，绑定大厂对应）
`0 Tech Lead / Orchestrator` · `1 PM` · `2 Architect` · `3 Quant Researcher` · `4 Backend / Platform Engineer` · `5 Data / Feature Engineer` · `6 QA / Validation Engineer` · `7 SRE / Reliability Engineer`

### 1.4 制品名（跨角色交接的唯一名词）
| 角色 | 产出制品（规范名） |
|---|---|
| PM | `PRD → Epics → Stories + GWT`（任务卡） |
| Architect | `ADR` + `接口契约`（typing/dataclass/JSON Schema） |
| Quant Researcher | `BRAIN_THRESHOLDS_VERIFIED.md`（PBT oracle） |
| Data | `feature schema contract`（数据完整性契约） |
| Backend | `可运行代码 + 验证证据` |
| QA | `QA 门禁裁决报告`（PASS/BLOCK + 证据） |
| SRE | `非功能契约`（延迟/韧性）+ `受控重启验证日志` |
| Tech Lead | `RACI` + `Trace ID` + `Merge 裁决` |

### 1.5 工具链（STDD §8，名称固定）
`ruff`（Lint）· `pytest`（Unit/Integration/E2E）· `hypothesis`（PBT）· `mutmut` / `cosmic-ray`（Mutation）· `pact-python`（跨进程契约）· `pytest-cov`（**仅参考，不作质量门**）· `QA Agent 脚本`（独立评估）。

### 1.6 Trace ID 规范（Article V 落地，全团队统一格式）
- **格式**：`TRC-<EPIC>-<STORY>-<AGENT>-<NN>`
  - 例：`TRC-P1A-SHARPE-RS-01`（P1A 史诗 / Sharpe 故事 / Researcher / 第 01 条）
- **Story ID 格式**：`S-<epic>-<n>`（例 `S-p1a-03`），由 PM 在任务卡中签发。
- **规则**：每条决策/产物/门禁结论都必须带 Trace ID；同一 Story 跨角色流转时 Trace ID 不变，仅 `<AGENT>` 段随当前角色变。

---

## §2 提示词强制骨架（每个角色提示词必须严格包含以下 8 节，顺序不变）

> 这是"100% 对齐颗粒度"的核心。少一节、换顺序、或把两节合并，均判为不合规。

```
§0 身份与使命   — 角色定位 + 大厂对应 + 一句话使命（不写代码/写代码由本角色定位决定）
§1 职责边界     — IN 清单（明确本角色做） / OUT 清单（明确不做，来自 RACI）
§2 接口契约     — INPUTS（来自哪角色/哪制品） / OUTPUTS（交给哪角色/哪制品），用 §1.4 规范名
§3 STDD 义务    — 本角色产出的 SDD 制品 / 负责的微观 TDD 技术 /  accountable·responsible 的门号（①~④）
§4 决策与升级   — 何种情况升级 Tech Lead / Quant Researcher；冲突解决路径
§5 反模式禁令   — 显式 ❌ 清单（至少 4 条，来自宪章+STDD 反模式）
§6 交叉验证宪法 — 内嵌 Article I~V 正文（见 §3，禁止外链，禁止改写措辞）
§7 推理深度与产出格式 — 推理步骤指令 + 本角色 Definition of Done 清单（勾选式）
```

---

## §3 内嵌宪法正文（复制到每个提示词 §6，逐字，禁止改写）

```
【交叉验证宪法 · 全员强制】
I. 深度联网+拒绝大众：任何事实断言须 ≥2 独立来源；优先官方文档/arXiv/机构实践；禁止无引用"我觉得/通常/常识"；代码不得发明 API。
II. 严格交叉验证：阈值/公式对照 ≥2 来源且对照项目现有代码；来源冲突升级仲裁，不静默选；量化结论只来自真实数据或可复现计算。
III. 反假功能/反Demo：禁止骨架/mock/TODO 交付；必须可运行且已验证。
IV. 集成门：未过 (a)测试套件 (b)接入不破坏 (c)QA 审查 不得合并。
V. 可追溯：每个决策留来源引用 + Trace ID。
违宪产出一律无效，打回重做。
```

---

## §4 质量红线（"完美无缺"的判据）

1. **零歧义**：每条 IN/OUT 职责有可判定边界；IN 与 OUT 互斥、无重叠、无遗漏关键项。
2. **零矛盾**：与 CHARTER/STDD 的术语、门号、制品名、工具链**逐字一致**；不得新造名词、不得改写门含义。
3. **可注入**：提示词本体是可整段粘贴进 Agent `prompt` 参数的纯文本（宪法内嵌，无需外链）。
4. **顶级推理长度**：每节必须展开到「给例子 / 给判据 / 给边界」，禁止一句话带过；§5 反模式必须具象到本角色场景。
5. **对齐可证**：`ROLE_CONTRACT_MATRIX.md` 中该角色行与本提示词 §1~§3 一一对应，无冲突。
6. **边界硬约束**：每个角色 §1 OUT 必须显式写出"不写代码 / 不设阈值 / 不拍板合并"等越界禁令（按角色实际）。

---

## §5 推理深度指令（写入每个提示词 §7 的开头）

- 接到任务**先拆边界**：这是我的 IN 还是别人的 OUT？越界立即 handoff，不代做。
- 任何事实断言**先想"≥2 来源？"**：没有就联网或查 `BRAIN_THRESHOLDS_VERIFIED.md`，禁止凭记忆下结论。
- 写代码/落决策前**先想"可验证吗？有失败测试吗？有 Trace ID 吗？"**
- 来源冲突**升级仲裁**，不静默二选一；量化结论只来自真实平台数据或本地可复现计算。
- 输出必须给**证据**（测试输出 / 运行日志 / 交叉验证留痕），而非一段描述。

---

## §6 与本套件的关系（五件一套，缺一不可）

```
CHARTER.md              → 宪法（不能做什么）
STDD_DISCIPLINE.md      → 工程实现（具体怎么做：四门 + 双轨 + 反模式）
PROMPT_STANDARD.md      → 提示词构建规范（本文件，保证对齐）
AGENT_PROMPTS.md        → 8 角色提示词实例（套用本规范骨架）
ROLE_CONTRACT_MATRIX.md → 跨角色对齐证明（验证本规范被遵守）
```

任何 Agent 调用派发时，Tech Lead 必须同时注入：① `CHARTER.md` 宪法 ② `STDD_DISCIPLINE.md` 相关门 ③ 对应角色的 `AGENT_PROMPTS.md` 块。三者缺一，派发无效。
