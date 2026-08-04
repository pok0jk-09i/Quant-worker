# STDD 工程纪律：SDD × 专业 TDD 双轨范式（Quant worker 团队绑定方法论）

> 宪法地位：本文件是《团队宪章 CHARTER.md》Cross-Validation 宪法的**工程实现层**。任何 Agent 在实现功能前，必须先遵守本纪律。
> 设计原则（用户铁律）：**专业、详细、全面、稳定**。SDD 拥有宏观（"做什么"/架构/契约），TDD 拥有微观（"做对了"/实现正确性），二者**双向可追溯咬合**，禁止朴素 TDD、禁止假功能/demo。

---

## 0. 命名与边界

- **STDD = Spec-Test-Driven Development**：SDD 管"规格即事实源、架构、接口契约、验收标准"，TDD 管"test-first + 专业测试技术栈"。
- 来源交叉验证：
  - SDD 宏观/微观分层 + "SDD 定做什么、TDD 确保做对"：CSDN《规范驱动开发深度解析》、niteshrijal《SDD the next evolution》、besthub.dev《From Vibe Coding to Spec Coding》(提出 STDD 合并术语) 三源一致。
  - GitHub Spec Kit 内嵌 TDD："If tests are requested, test tasks are written before implementation"（besthub.dev、CSDN dongnihao 双重印证）。
- **本纪律不替代宪章**，而是把宪章 Article I/II（联网+交叉验证）与 Article III/IV（反假功能+集成门）落到"怎么写代码、怎么写测试"的可操作步骤。

---

## 1. 为什么必须双轨，且 TDD 不能是"朴素版"

### 1.1 朴素 TDD（红→绿→重构）的三大失效模式（来源：joegaebel《Principled Agentic Software Development》、cc.bruniaux《TDD with Claude Code》、nplus.wiki《Advanced TDD》）

1. **写后补不算 TDD**：先实现再补测试 = reactive verification，测试会"天然通过"，失去"强迫理解行为/解耦"的价值。必须 test-first。
2. **Mockist 脆弱性**：只写单元测试 + 大量 mock，套件充满脆断、与实现细节耦合的测试，重构即崩。
3. **覆盖率幻觉**：100% coverage 可作弊（跑过路径但不断言）。必须看 **mutation score** 而非 coverage 数字（joegaebel、nopaccelerate、cc.bruniaux 三源一致）。

### 1.2 单一 AI 大改的翻车模式（即用户担心的"假功能/demo 不咬合"）

- 无规格 → 各 Agent 对"做什么"理解分歧 → 实现互相不咬合。
- 无 test-first → 测试沦为装饰 → 假功能通过"看起来能跑"。
- 无独立评估 → 写代码者自证完成 → Anthropic harness 研究实证：裸跑 20 分钟报"完成"但全坏；加独立评估器后跑 6 小时交付可用（cc.bruniaux 引用 Anthropic harness-design 研究）。
- **双轨 + 独立评估 + Merge Gate 是根治方案**（对应我们宪章的 Merge Gate 由 Tech Lead 把守）。

---

## 2. SDD 层（宏观框架，拥有"做什么"）

### 2.1 规格即单一事实源（Single Source of Truth）
- 当 需求 / 代码 / 测试 冲突时，**回到规格仲裁**（CSDN SDD、niteshrijal）。
- 规格贯穿全生命周期：规划→设计→实现→测试→维护；需求变更**先改规格**，再同步设计/实现/测试（CSDN SDD）。

### 2.2 规格必须"可验证"（Verifiable Spec）
好规格必须能被：① 测试用例验证 ② 契约测试检查 ③ 自动化工具解析 ④ AI 工具理解执行（CSDN SDD）。**不可验证的规格 = 无效规格**。

### 2.3 本项目适配的规范格式（不照搬 REST 工具链）
| 用途 | 格式 | 说明 |
|---|---|---|
| 架构决策 | ADR（Architecture Decision Record） | Architect 产出，含上下文/选项/决定/后果 |
| 模块接口契约 | Python `typing` + `dataclass` + JSON Schema | 函数签名/返回值结构即契约；跨进程用 `pact-python` |
| 算法/阈值规格 | 数值规范文档（联网交叉验证） | Quant Researcher 产出，是 PBT 的 oracle |
| 行为验收 | Gherkin 风格 Given-When-Then | PM 产出，驱动 BDD→TDD 派生 |

### 2.4 各 Agent 的 SDD 产出（宏观责任）
- **PM**：PRD → Epics → Stories + **GWT 验收场景**（业务语言、具体值、每场景单行为、声明式非命令式 — agilemechanics BDD 三层最佳实践）。
- **Architect**：系统架构规格 + **接口契约**（typing/dataclass/JSON Schema）+ 非功能约束（延迟/吞吐/韧性）。
- **Quant Researcher**：阈值/公式规范（**Article I/II 联网双源交叉验证**，禁止凭记忆下结论）。
- **Data**：feature store schema 契约 + 数据完整性契约。

---

## 3. 专业 TDD 层（微观，拥有"做对了"）—— 拒绝朴素版

### 3.1 Outside-In TDD（feature-complete 测试先行）
来源：joegaebel《Principled Agentic Software Development》（Pivotal/XP 实践）。
- 先写**特性完成验收测试**（能断言"用户价值已交付"的最低层级测试，常是集成/E2E）。
- 该测试"因正确原因失败"后，再在合适层级写更小测试，做 Red-Green-Refactor 内循环，直到特性测试通过。
- 价值：避免只写单元测试导致"套件绿但用户价值未交付"。

### 3.2 三层验证栈（Lint → Unit/Integration → E2E）
来源：cc.bruniaux《TDD with Claude Code》三层验证栈。每层抓不同类失败：
1. **Lint**（ruff/flake8）：语法/风格，最快，先挡明显错误。
2. **Unit + Integration**：组件功能正确性（pytest）。
3. **E2E / Journey**：用户/外部调用视角的**行为契约**；能抓单元测试看不到的状态传播/生命周期错误。
- **跳过任何一层都留缺口**。CI 必须三层全过才算绿。

### 3.3 Property-Based Testing（不变量/阈值穿透）
来源：datasea《TDD+Property-Based Testing 双驱动》（滴滴风控落地）、cc.bruniaux、nopaccelerate。
- 对具备**数学性质/不变量**的函数（阈值缩放、排序、序列化、校验），用 `hypothesis` 生成随机但符合约束的输入，自动探索边界与反直觉缺陷。
- 本项目高价值目标：`submit_gate` 的 sub_sharpe 缩放公式、self-correlation 判定、区域硬指标阈值——这些**数学不变量必须用 PBT**，人工枚举必漏。
- 配合 Quant Researcher 的联网验证值作 oracle（如 D1 `√252 × max(0.065, ratio×0.15)` 的绝对下限）。

### 3.4 Mutation Testing（用 mutation score 替代 coverage 幻觉）
来源：joegaebel、nopaccelerate、cc.bruniaux（Meta JiTTesting 4x 回归捕获）。
- 注入变异（AND→OR、`<`→`<=`、常量篡改）重跑测试；测试**不挂**说明该代码未被真测到。
- **禁止用 100% coverage 自我安慰**；以 **mutation score（≥ 阈值，建议 ≥70%）** 为质量门。
- 工具：`mutmut`（基于 pytest，Python 首选）、`cosmic-ray`（更强但重）。

### 3.5 Characterization Tests（接手遗留模块）
来源：cc.bruniaux《TDD with Legacy Code》。
- 重构 `candidate_submitter.py` 等既有模块前，先写测试**捕获当前行为**，再重构保绿。禁止"理解不清就重写"。

### 3.6 Contract Tests（Agent/模块间接口契约，consumer-driven）
来源：eBay 案例（innovation.ebayinc.com）、mvpfactory、nemanjatanaskovic、garnetwiki、inferensys（五源交叉）。
- **这正是多 Agent "不要弄崩整棵树"的工程解**：每个 Agent 的产出是另一 Agent 的"提供者"，接口即契约。
- 模式（对标 Pact consumer-driven）：
  - 消费者（调用方 Agent）写契约测试：声明"我调用 X，期望返回结构 Y"。
  - 提供者（实现方 Agent）验证：其实现满足所有消费者契约。
  - `can-i-deploy` 式硬门：契约失败 = 构建红 = 部署/合并阻断。
- Schema 演化规则（mvpfactory/garnetwiki）：**加可选字段安全；删字段/改类型 Breaking**；用 tolerant reader（忽略未知字段）。
- 本项目落地：模块边界用 `pytest` 契约测试断言接口 schema；跨进程 HTTP（如监控面板 API）用 `pact-python`。

### 3.7 Independent Evaluator 原则（写 ≠ 证）
来源：cc.bruniaux（引用 Anthropic harness-design）+ 我们宪章 Merge Gate。
- **写代码的 Agent 不得是判定"完成"的同一调用**。由 **QA Agent** 独立跑测试并读 exit code 认证。
- 理由：写代码者会对模糊输出做善意解读；独立评估者不会（上下文影响判断）。

### 3.8 TDD as Mandatory Gate（无失败测试不写实现）
来源：Superpowers 插件（cc.bruniaux、besthub）"code written before a failing test exists gets deleted and redone"。
- 纪律：**任何实现代码必须先有失败测试**（Red 阶段存在）方可写。违反 = 该实现删除重来。
- **WIP=1**：一次只活跃一个 Story，验证缺口只影响一个（cc.bruniaux）。

### 3.9 London vs Chicago 学派选择指导
来源：nplus.wiki《Advanced TDD》。
- **London（Outside-In，多 mock/spy，确定性>灵活性）**：用于跨架构边界（确保正确调用协作者）。
- **Chicago（Inside-Out，value/property tests，灵活性>确定性）**：用于组件内部（降低耦合与脆断）。
- 本项目：**跨 Agent/跨模块边界用 London 式契约/sply 验证；模块内部算法用 Chicago 式 value + PBT**。融合为最佳。

### 3.10 反模式清单（禁止）
- ❌ 写后补测试当 TDD。
- ❌ 只追 100% coverage，不看 mutation score。
- ❌ 大量 mock 导致测试与实现细节耦合。
- ❌ 写代码者自证完成。
- ❌ skeleton/mock/TODO 当"完成"（宪章 Article III）。

---

## 4. 双轨咬合：可追溯矩阵（让"稳定"落地）

### 4.1 映射链（每链路可回溯）
```
PM Story (GWT 验收)
   └─> Architect 接口契约
         └─> Backend: Outside-In 特性测试 → 派生 N 个 TDD 单元/PBT/契约测试
               └─> Quant Researcher 阈值规范 = PBT oracle
                     └─> QA 独立评估 + Contract 验证
                           └─> Tech Lead Merge Gate（四门全过）
```
- 每个 Story 有 **Trace ID**，串联：规格 ↔ 测试 ↔ 实现 ↔ merge 记录。
- 改规格 → 自动定位受影响测试（spec-first 变更传播）。

### 4.2 Merge Gate 四门（Tech Lead 把守，CI 硬门）
| 门 | 条件 | 来源 |
|---|---|---|
| 门① 规格覆盖 | 每个 Story 有 GWT + 接口契约，且被测试引用 | SDD 可验证 |
| 门② 测试通过 | Lint + Unit/Integration + E2E 全绿 | 三层验证栈 |
| 门③ 契约通过 | 所有 consumer-driven contract 验证通过 | Pact 模式 |
| 门④ 独立评估 | QA Agent 独立跑测读 exit code 认证，mutation score ≥ 阈值 | Independent Evaluator |

**四门缺一，PR 红，禁止合并。**

---

## 5. 多 Agent 分工执行矩阵

| Agent | SDD 产出（宏观） | TDD 职责（微观） |
|---|---|---|
| **Tech Lead（我）** | 派发 + 仲裁 Merge Gate | 确保四门执行；冲突升级仲裁 |
| **PM** | Stories + GWT 验收（业务语言） | 验收场景即最外层 BDD 规格 |
| **Architect** | 架构规格 + 接口契约（typing/JSON Schema/ADR） | 定义契约测试边界 |
| **Quant Researcher** | 阈值/公式规范（联网双源验证） | **PBT 的 oracle**（提供期望不变量值） |
| **Backend** | 依契约实现 | Outside-In + PBT + mutation + characterization |
| **Data** | feature store schema 契约 | schema 契约测试 + 完整性测试 |
| **QA** | — | **独立评估器** + contract 验证 + 反 demo 门禁 |
| **SRE** | 非功能契约（延迟/韧性） | 把 contract/mutation 接进 CI 硬门 + 看门狗监测 |

**关键约束**：QA 必须独立于写代码 Agent；Researcher 的验证值必须作为 PBT 的断言依据，禁止 Backend 自行编造阈值。

---

## 6. 反"假功能/demo"硬约束（宪法级，7 条禁令）

1. 禁止无规格实现（SDD first）。
2. 禁止 test-after 充作 TDD（必须 test-first，Red 先存在）。
3. 禁止 skeleton/mock/TODO/占位当"完成"（宪章 Article III）。
4. 禁止以 100% coverage 自我安慰（看 mutation score）。
5. 禁止写代码者自证完成（Independent Evaluator）。
6. 禁止阈值/公式凭记忆或单源写入（Article I/II 双源联网 + Researcher 验证）。
7. 禁止未经四门 Merge Gate 合并（Article IV）。

---

## 7. 工作流实例：P0 sub_sharpe 缩放公式走一遍 STDD

> 背景：我们已联网交叉验证出正确公式 `√252 × max(0.065, ratio×0.15)`（D1），旧文档的 `0.75·√(sub/uni)` 被判定不可信。现用 STDD 落地。

1. **PM Story + GWT**：
   ```
   Feature: sub-universe Sharpe 闸门
   Scenario: D1 alpha 在 ratio=0.5 时下限
     Given region=USA, delay=D1, sub_size/uni_size=0.5
     When 计算 sub_sharpe 下限
     Then 结果应 ≈ 1.19（√252×0.075）且不低于 0.065 绝对 floor
   ```
2. **Architect 接口契约**：`def sub_sharpe_floor(region, delay, ratio) -> float`，返回值类型 + 边界（ratio∈(0,1]）。
3. **Quant Researcher oracle**：已验证值 `√252×max(0.065, ratio×0.15)`（D1）/ `×0.25`（D0）写入 `BRAIN_THRESHOLDS_VERIFIED.md`，作为 PBT 断言。
4. **Backend TDD**：
   - Red：写 `test_sub_sharpe_floor` 断言上述值 → 失败。
   - Green：实现公式。
   - PBT（`hypothesis`）：随机 ratio∈(0,1]，断言 `floor ≥ 0.065` 且 `floor == √252×max(0.065, ratio×k)`。
   - Mutation：`mutmut` 跑，确保 `<`→`<=` 等变异被测抓。
   - Characterization：若改 `submit_gate` 既有分支，先捕获旧行为。
5. **QA 独立评估**：独立调用 pytest + mutmut，读 exit code，确认 mutation score ≥70%。
6. **Tech Lead Merge Gate**：四门全过 → 合入 `submit_gate`。

---

## 8. 工具链与 CI 门禁（Python）

| 类别 | 工具 | 用途 |
|---|---|---|
| Lint | `ruff` | 风格/语法，第一道快门 |
| 测试 | `pytest` | Unit/Integration/E2E |
| PBT | `hypothesis` | 不变量/阈值穿透 |
| Mutation | `mutmut` / `cosmic-ray` | mutation score 门 |
| Contract | `pytest`（进程内）+ `pact-python`（跨进程 HTTP） | 接口契约验证 |
| Coverage | `pytest-cov` | 仅参考，**不**作质量门 |
| 独立评估 | QA Agent 脚本 | 独立跑测读 exit code |

**CI 硬门顺序**：`ruff` → `pytest(unit+PBT)` → `mutmut(score≥70)` → `contract verify` → **QA 独立评估**。任一红 = 阻断。

---

## 9. Definition of Done（每 Story 验收）

一个 Story 标记为完成，**必须同时满足**：
- [ ] 有 PM 的 GWT 验收场景 + Architect 接口契约（规格可追溯）。
- [ ] test-first：实现前有失败测试（Red 存在证据）。
- [ ] Lint + Unit/Integration + E2E 三层全绿。
- [ ] 数学/阈值不变量有 PBT（hypothesis）覆盖。
- [ ] mutation score ≥ 70%。
- [ ] 所有 consumer-driven contract 验证通过。
- [ ] **QA Agent 独立评估通过**（非写代码者自证）。
- [ ] 经 Tech Lead Merge Gate 四门合入。

---

## 10. 来源索引（交叉验证留痕）

- SDD 宏观/微观分层、STDD 合并：CSDN《规范驱动开发深度解析》、niteshrijal.com/blog、besthub.dev/articles/from-vibe-coding-to-spec-coding。
- Spec Kit 内嵌 TDD：besthub.dev、CSDN dongnihao。
- Outside-In TDD / Mutation / Principled Dev：joegaebel.com/articles/principled-agentic-software-development。
- 三层验证栈 / Independent Evaluator / TDD as gate：cc.bruniaux.com/guide/tdd-workflow（引 Anthropic harness-design）。
- PBT 双驱动（滴滴落地）：datasea.cn Go TDD+PBT 案例。
- BDD/GWT/Specification by Example：agilemechanics.com、cstopics.com、aicodereview.cc、bitloops.com、codelucky.com。
- Contract Testing（Pact/eBay）：innovation.ebayinc.com、mvpfactory.io、nemanjatanaskovic.com、thegarnetwiki.com、inferensys.com。
- London vs Chicago / Test Doubles / TDD Uncertainty：nplus.wiki/clean-craftsmanship Advanced TDD。
- 高级 TDD 技术栈（2025）：nopaccelerate.com/test-driven-development-guide-2025。
