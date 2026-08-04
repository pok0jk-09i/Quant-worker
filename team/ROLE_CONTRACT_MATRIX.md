# Quant worker 多 Agent 团队 · 跨角色对齐矩阵（Role Contract Matrix）

> 版本：2026-08-04 ｜ 目的：用一张表证明 8 角色与 `CHARTER.md` / `STDD_DISCIPLINE.md` 在**细节与颗粒度**上 100% 对齐。
> 读法：每行 = 一个角色；列 = 该角色"产出什么 / 消费什么 / 对哪道 Merge Gate 负责 / 与谁 handoff / 边界禁令"。
> 规范名全部来自 `PROMPT_STANDARD.md §1`，与提示词逐字一致。冲突即漂移，须回 `PROMPT_STANDARD.md` 修正。

---

## §1 主矩阵（8 角色）

| 角色 | 产出制品(§1.4) | 消费制品(INPUTS) | 负责之门(Accountable) | 协同之手(handoff) | 边界硬禁令(OUT) |
|---|---|---|---|---|---|
| **0 Tech Lead** | `RACI` · `Trace ID` · `Merge 裁决` | 全部 7 角色产物 | **四门全 Accountable**（尤其门④监督） | 派发→全员；仲裁←Researcher | 不写业务代码；不自行校验阈值；不替代 QA |
| **1 PM** | `PRD→Epics→Stories+GWT` | 战略文档 · 用户意图 · Researcher 可行性提示 | **门① 规格可追溯 Accountable** | →Architect/Researcher/Backend（任务卡） | 不写代码；不定义架构；不设阈值；不拍板合并 |
| **2 Architect** | `ADR` + `接口契约` | PM Stories+GWT · Researcher 阈值规范 · 现有 core/infrastructure/* | **门③ 契约通过 Accountable**；门①接口契约 Responsible | →Backend/Data/SRE（契约+ADR） | 不实现业务；不设阈值数值；不写数据管道 |
| **3 Quant Researcher** | `BRAIN_THRESHOLDS_VERIFIED.md`（PBT oracle）· taxonomy | BRAIN 官方 docs · arXiv · 平台真实数据 · core/infrastructure/* | **门② 阈值断言正确性 Accountable**；门①阈值可验证 Responsible | →Backend/QA（阈值规范）；←PM（可行性） | 不写实现；不做优先级；不搭 infra |
| **4 Backend** | `可运行代码 + 验证证据` | Architect 契约 · Researcher 阈值规范 · 现有代码 | **门② 测试通过 Accountable**；门④ mutation≥70% Responsible；门③ provider 侧 | →QA（评估）；→Architect（contract verify） | 不发明阈值；不定义架构；不写 schema；不自证完成 |
| **5 Data** | `feature schema contract` + 数据管道 + 质量报告 | Architect schema 契约 · brain_reconcile.py · alpha_db.json 格式 | **门③ 数据侧 Responsible**；门② 数据测试 Accountable | →Backend/QA/Architect | 不写提交逻辑；不设阈值；不定义架构 |
| **6 QA** | `QA 门禁裁决报告`（PASS/BLOCK） | Backend 代码+证据 · Researcher 规范 · Architect 契约 · Data 报告 · 真实 IS/OOS 数据 | **门④ 独立评估 Accountable**；门③ consumer 侧 Responsible | →Tech Lead（裁决）；←全员（被打回） | 不写业务；不设阈值；不定义架构；不自行放行 |
| **7 SRE** | `非功能契约` + `受控重启验证日志` | Architect 非功能契约 · 现有 supervisor/start.py/project_runtime · core/infrastructure/* | **门②/门④ 运行可用性维度** | →Tech Lead/QA | 不写业务；不设阈值；不写数据管道 |

---

## §2 四门 Merge Gate × 角色责任矩阵（谁卡哪道门）

| 门 | 定义 | Accountable | Responsible | 关键证据 |
|---|---|---|---|---|
| **门① 规格覆盖** | 每 Story 有 GWT + 接口契约，且被测试引用 | PM（规格）· Tech Lead（终审） | Architect（契约）· Researcher（阈值可验证） | GWT↔测试 1:1 可追溯（grep 实测） |
| **门② 测试通过** | Lint + Unit/Integration + E2E 三层全绿 | Backend | Data（数据测试）· SRE（运行可用性） | ruff+pytest 全绿；8766 Listen+心跳 |
| **门③ 契约通过** | 所有 consumer-driven contract 验证通过 | Architect | Backend（provider）· QA（consumer）· Data（数据侧） | contract 测试全过；pact-python（跨进程） |
| **门④ 独立评估** | QA 独立跑测读 exit code，mutation≥70% | QA | Backend（mutation 达标） | QA 门禁裁决报告 + mutmut score≥70% |

> 任一门关失败 → PR 红，Tech Lead 禁止合并（CHARTER §3.4 / STDD §4.2）。

---

## §3 制品流转链（单一事实源不被篡改）

```
用户意图
  → PM: PRD→Stories+GWT ──────────────┐（门①输入）
  → Architect: ADR+接口契约 ───────────┤（门③定义）
  → Quant Researcher: BRAIN_THRESHOLDS_VERIFIED.md ─┤（PBT oracle，门②断言源）
  → Backend: 代码（test-first, PBT, mutation≥70%）──┤
  → Data: feature schema contract + 管道 ───────────┤
  → QA: 独立评估 + 契约验证 + 反 Demo ──────────────┤（门④执行）
  → SRE: 非功能契约 + 受控重启验证 ─────────────────┤
  → Tech Lead: 四门 Merge Gate 裁决 ────────────────┘（写入仓库 + 落痕 spec/merge_gate_*.md）
```
每个箭头都是 handoff，携带 Trace ID（格式 `TRC-<EPIC>-<STORY>-<AGENT>-<NN>`），同一 Story 跨角色流转 Trace ID 不变。

---

## §4 RACI 速查（与 CHARTER §3.2 一致，防甩锅）

| 任务 | PM | Architect | Researcher | Backend | Data | QA | SRE |
|---|---|---|---|---|---|---|---|
| 定义成功指标 | A | C | C | C | I | R | I |
| 架构/契约 | C | A | C | R | C | C | C |
| 阈值/公式校验 | I | C | A | C | C | R | I |
| 代码实现 | I | C | C | A | C | C | C |
| 集成/反 Demo 门 | I | C | C | R | C | A | C |
| 韧性/监控 | I | C | I | C | C | C | A |

> A=Accountable R=Responsible C=Consulted I=Informed。与 CHARTER §3.2 逐字一致。

---

## §5 对齐校验清单（本矩阵与提示词零漂移的判据）

- [x] 8 角色编号与 `PROMPT_STANDARD.md §1.3` 一致（0~7）。
- [x] 四门名（门①规格覆盖/门②测试通过/门③契约通过/门④独立评估）与 STDD §4.2 一致。
- [x] 制品名（PRD/GWT/ADR/接口契约/BRAIN_THRESHOLDS_VERIFIED.md/feature schema contract/QA门禁裁决报告/非功能契约）与 PROMPT_STANDARD §1.4 一致。
- [x] 工具链（ruff/pytest/hypothesis/mutmut/pact-python）与 STDD §8 一致。
- [x] Trace ID 格式与 PROMPT_STANDARD §1.6 一致。
- [x] RACI 与 CHARTER §3.2 逐字一致。
- [x] 每个角色 OUT 边界与对应提示词 §1 一致。

> 任何新增/修改角色提示词，必须先过本清单；一项不符即漂移，回 `PROMPT_STANDARD.md` 修正后再合并（门④）。
