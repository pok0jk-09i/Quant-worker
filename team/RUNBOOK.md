# Quant worker 多 Agent 团队 · Gen-4 工程化 Runbook

> 版本：2026-08-04 ｜ 本文件是「第四代概念框架」的工程化交付说明：把团队 OS（CHARTER/STDD/PROMPT_STANDARD/AGENT_PROMPTS/ROLE_CONTRACT_MATRIX）落成**可运行、可 CI 门禁、交付级**的系统。

---

## 1. 架构（五件一套 → 可运行代码）

| 层 | 文件 | 作用 |
|---|---|---|
| 规范事实源 | `team/CHARTER.md` `STDD_DISCIPLINE.md` `PROMPT_STANDARD.md` `AGENT_PROMPTS.md` `ROLE_CONTRACT_MATRIX.md` | 不可漂移的规范（宪法/四门/八角色/骨架） |
| 可运行 runtime | `team/runtime/registry.py` `trace.py` `orchestrator.py` | 角色单一事实源 + Trace ID 账本 + Tech Lead 合并裁决 |
| 四门门禁 | `team/gates/{gate_spec,gate_tests,gate_contract,gate_qa,run_all}.py` | 门①-门④ 真实可执行 |
| CI | `team/ci/run_merge_gate.py` `.github/workflows/merge_gate.yml` | 每次 PR/push 自动跑四门 |
| 首个交付物 | `core/infrastructure/seed_pool.py` + `tests/test_seed_pool*.py` | 走完四门的真实父池工程 |

---

## 2. 四门 Merge Gate（任一失败 = PR 红，禁止合并）

| 门 | 名称 | 负责(Accountable) | 检查内容 | 实现 |
|---|---|---|---|---|
| **门①** | 规格覆盖 | PM / Tech Lead | 每 Story 有 GWT + 接口契约 + **引用它的测试** | `gate_spec.py` 读 `team/specs/stories_manifest.json`，校验 GWT 文件存在、契约非空、测试文件存在且含 story marker |
| **门②** | 测试通过 | Backend | ruff 干净 + pytest(单元/集成/PBT) 全绿 | `gate_tests.py` 跑 `scripts/`+`core/` lint 与 `tests/`+`core/infrastructure/tests/` |
| **门③** | 契约通过 | Architect | consumer-driven contract 测试全过 | `gate_contract.py` 跑 `team/contracts/contracts.json` 声明的契约测试 |
| **门④** | 独立评估 | QA | 写者不自证：ruff + 测试 + **cosmic-ray 变异 score≥70%** | `gate_qa.py` 复用 `team/qa_gate.py` 变异解析，指向 `team/ci/cosmic_seed_pool.toml` |

`run_all.py` 按 门①→②→③→④ 顺序执行，写 `team/qa_gate_report.json`，exit code 反映最终裁决。

### Nightly Gate（不在 merge 阻塞链，按调度跑）

| 门 | 名称 | 负责 | 检查内容 | 实现 |
|---|---|---|---|---|
| **Nightly** | 重集成覆盖 | SRE / QA | 全量 pytest（**含 `real_db` 真实数据路径**，加载 14MB `alpha_db.json`）+ ruff；merge 门为速度排除该集成测试 | `team/ci/run_nightly_gate.py` 写 `team/specs/nightly_gate_<STORY>.json` |

设计原则：快速门（门①②③④）每次 PR 秒级；**真实数据路径不静默丢弃**，移入 nightly 按 cron/调度跑，互不拖累。门③ 契约当前含 2 条：`seed_pool ↔ candidate_generator` 与 `timeout_field_guard ↔ candidate_generator/candidate_submitter`（钉住护栏消费者接口，防黑名单变更静默破坏生成/提交）。

---

## 3. Trace ID（Article V 可追溯）

格式：`TRC-<EPIC>-<STORY>-<AGENT>-<NN>`
例：`TRC-P1A-SEEDPOOL-TL-01`

- 同一 Story 跨角色流转 Trace ID 不变，仅 `<AGENT>` 段随角色变（TL/PM/AR/RS/BE/DA/QA/SR）。
- 每条决策/产物/门禁结论都写入 `team/runtime/.trace_ledger.jsonl`。
- 生成：`python -m team.runtime.trace`（自测）或 `from team.runtime.trace import log`。

---

## 4. 本地如何运行

```bash
# 0) 对齐自检（代码与 ROLE_CONTRACT_MATRIX 零漂移）
python -m team.runtime.registry

# 1) 跑四门（针对 SEEDPOOL story）
python team/ci/run_merge_gate.py P1A SEEDPOOL
#   等价：python team/runtime/orchestrator.py --epic P1A --story SEEDPOOL

# 1b) 跑 Nightly 门（含真实数据集成路径 real_db，按 cron/调度跑，勿每次 PR 跑）
python team/ci/run_nightly_gate.py P1A SEEDPOOL

# 2) 单独跑某一门
python -m team.gates.gate_spec        # 门①
python -m team.gates.gate_tests       # 门②
python -m team.gates.gate_contract    # 门③
python -m team.gates.gate_qa          # 门④

# 3) 门④ 变异（cosmic-ray）
#    ⚠️ 重要：必须从【原生 Windows 控制台】跑（PowerShell 或 cmd.exe），
#    不要从 Git-Bash / MSYS 跑！cosmic-ray 8.4.6 的 local distributor 在
#    MSYS 下派生 worker 子进程会挂死（无 .cosmic-ray 进度、session 不增长、
#    零输出）。在 PowerShell/cmd 下 11 个变异体 ~30s 跑完，完全正常。
#    gate_qa 已加 1800s 墙钟 + 明确裁决（Git-Bash 下挂死会 fail-fast 提示
#    改从原生控制台，绝不空转）。
E:/Python311/Scripts/cosmic-ray.exe init --force team/ci/cosmic_seed_pool.toml cr-session-seedpool.json
E:/Python311/Scripts/cosmic-ray.exe exec team/ci/cosmic_seed_pool.toml cr-session-seedpool.json   # ← 从 PowerShell/cmd 跑
E:/Python311/Scripts/cosmic-ray.exe dump cr-session-seedpool.json > cr-dump-seedpool.jsonl
```

> 在 WorkBuddy 内跑四门：用 **PowerShell 工具**（原生 Windows 控制台）执行
> `E:/Python311/python.exe team/ci/run_merge_gate.py P1A SEEDPOOL`，
> 不要从 Bash(Git-Bash) 工具跑 —— 否则门④ 变异挂死。

> 解释器固定为 `E:/Python311/python.exe`（PINNED_PYTHON），ruff/cosmic-ray 在 `E:/Python311/Scripts/`。Gate 脚本已硬编码该路径，勿改。

---

## 5. 大厂交付标准清单（不遗漏任何细节）

- [x] 八角色提示词 100% 对齐骨架（PROMPT_STANDARD §2 八节）
- [x] 四门命名全目录零漂移（`门①~门④`，已机器校验）
- [x] 角色单一事实源在代码（registry.py）与文档（ROLE_CONTRACT_MATRIX）双写且可机器校验
- [x] Trace ID 规范 + JSONL 运行账本
- [x] 门① GWT 可追溯（每 Story 有 spec + 引用测试）
- [x] 门② 三层验证栈（lint + unit/integration + PBT）
- [x] 门③ consumer-driven 契约（2 条：seed_pool ↔ candidate_generator；timeout_field_guard ↔ candidate_generator/candidate_submitter，钉住护栏消费者接口防回归）
- [x] Nightly 门（真实数据集成路径 `real_db` 不静默排除，纳入调度门禁，写 `nightly_gate_SEEDPOOL.json`）
- [x] 门④ 独立评估 + 变异 score≥70%（写者不自证）— **变异须从原生 Windows 控制台跑**（Git-Bash/MSYS 下 `cosmic-ray exec` 挂死，已加 1800s 墙钟 + 明确裁决 fail-fast；PowerShell/cmd 下正常）
- [x] CI 自动跑四门（GitHub Actions）+ 人工可跑入口
- [x] 首个走完四门的真实工程交付物（seed_pool，A1–A27）
- [x] 反假功能七禁 + 宪法 Article I–V 内嵌于提示词

---

## 6. 红线（与因子逻辑无关，但必须守住）

- **提交闸 1.5/1.5/0.30 绝不降**（用户目标：提交高标准因子，非为提交而提交）。
- **OOS-by-construction**：种子只信 BRAIN 真评估，不信本地 sim（A19）。
- **不发明 API / 不凭记忆下阈值**：事实断言须双源（Article I/II）。

---

## 7. 已知环境约束 / 故障排查（2026-08-04 实测）

> 这些坑都在本机（Windows / Git-Bash / WorkBuddy sandbox）实测踩过，写于此避免重蹈。

### 7.1 门④ 变异：必须从原生 Windows 控制台跑（最关键）
- **现象（Git-Bash/MSYS 下）**：`cosmic-ray exec` 启动后无任何输出、`.cosmic-ray/` 目录不生成、session 文件大小零增长，持续 9+ 分钟不结束（最小 1 函数模块 + 1 测试对照实验同样挂死 → 与配置/业务代码无关）。
- **根因**：cosmic-ray 8.4.6 的 `local` distributor 在 **MSYS/Git-Bash** 下派生 worker 子进程时卡死（multiprocessing spawn 在 MSYS 控制台语义下无法回连）。**这不是代码缺陷、也不是 cosmic-ray 本身的问题**——在 PowerShell/cmd 原生 Windows 控制台下，11 个变异体 ~30s 跑完、dump 正常。
- **处置**：门④ `gate_qa.py` 已加 `MUTATION_TIMEOUT_SECONDS=1800` 墙钟 + 明确裁决。若在 Git-Bash 下挂死超时，报错会提示「改从原生 Windows 控制台(PowerShell/cmd)跑」。**合并门永不空转**。
- **正确跑法**：在 WorkBuddy 内用 **PowerShell 工具**执行 `E:/Python311/python.exe team/ci/run_merge_gate.py P1A SEEDPOOL`；或在 GitHub Actions（Linux，`.github/workflows/merge_gate.yml`）跑。本机 WSL 当前未安装。

### 7.2 块缓冲日志假象
- 用 `> log 2>&1` 重定向时 Python **块缓冲**，进程不退出就不 flush，日志文件全程为空，让人误以为"卡住/中断"。
- **处置**：前台跑用 `python -u`（或 `PYTHONUNBUFFERED=1`）；后台跑用 `run_in_background` 由工具收集输出；不要靠重定向文件判断进度。

### 7.3 safe-delete 拦截 rm/unlink
- 本沙箱把 `rm`/`unlink`/`os.remove` 劫持到"安全删除"shim，删文件常失败（报 `trash operation aborted` 或"文件被占用"）。
- **处置**：门④ 改用 `cosmic-ray init --force` 覆盖旧 session，而非先 unlink；需要真删文件时用 Git Bash 的 `rm -f` 可能也被拦，必要时用 Python `os.remove` 仍可能被拦——优先用 `--force` 类语义。

### 7.4 全量门② 暴露的历史红测试
- 跑四门时门② 全量套件曾红在 `test_timeout_field_guard.py::test_rebuild_is_consistent_with_frozen_on_real_data`。
- **根因**：`candidate_submit_results.json` 当前数据相对 2026-08-01 已漂移——旧 14 个卡死字段（analyst/pv13）因护栏拦截不再出现；新出现 5 个现金流/收益类字段 100% 卡死（`free_cash_flow_per_share`/`net_profit_adjusted_value`/`op_cash_flow_median`/`rel_ret_cust`/`rel_ret_part`），但冻结黑名单未覆盖（真漏洞）；`rel_ret_part` 还被错放进 SAFE_FIELDS。
- **处置**：冻结黑名单改为旧14历史 ∪ 新5当前 = 19 字段（预防并集，不丢历史证据）；测试不变量改为 `rebuilt <= TIMEOUT_PRONE_FIELDS`（护栏不能有洞）；`rel_ret_part` 移出 SAFE 进 STALL。修复后门② 全绿（158 passed / 24 subtests）。
