# BRAIN 仿真 35% 挂死根因分析与生成端规避（2026-08-02）

> 用户选待办 B：分析 27 个 TIMEOUT 表达式的共同算子/字段模式，若可关联到 35% 卡死，则在生成端规避。
> 方法论：控制变量、数据驱动、不拍脑袋。所有结论来自 `candidate_submit_results.json`（27 TIMEOUT / 42 COMPLETE）。

## 1. 现象（已确证，非猜测）

重启后 69 条结果里 **27 条 TIMEOUT（39%）**。日志 `Still waiting (progress unchanged at 35%)` 在重启后所有轮次出现 **9092 次（占卡死 97.7%）**，正常完成（`Alpha ID:` 打印）2184 次。

- ❌ 不是"本地超时阈值太短误杀"：progress 卡在 35% **纹丝不动**，把 `POLL_TIMEOUT` 提到 1800s 也没用。
- ❌ 不是"BRAIN 单纯慢"：慢是 progress 持续推进；这里是**固定进度静止 = 挂起**。
- ✅ 根因在 **BRAIN 侧**（特定阶段算力/队列分配黑盒），但**字段维度可本地规避**。

## 2. 控制变量分析（算子 vs 字段）

### 2.1 算子层面：家族相关但非决定性

| 算子 | #TIMEOUT | #COMPLETE | 超时率 |
|---|---|---|---|
| ts_corr / zscore / greater / winsorize / log / ts_mean / ts_backfill / trade_when (Family B) | 24 | 9 | **0.73** |
| rank / ts_rank / group_rank / group_zscore / ts_zscore / densify / inverse (rank 家族) | 0~2 | 8~27 | **0.07** |

但**同一套 Family B 算子签名**（8 个算子全相同）既出现在 24 条 TIMEOUT，也出现在 9 条 COMPLETE —— 算子本身不是决定变量。

### 2.2 字段层面：在受控家族内彻底分开（决定性信号）

把仅含 Family B 签名的 33 条表达式单独对照字段：

- **15 个字段 100% 超时（T≥1, C=0）**，其中 **14 个 T≥2**：`net_income_total_2`、`cap`、`net_debt_reported_value`、`research_development_expense_reported_value`、`rel_ret_comp`、`anl4_fs_guidances_advanced_af_nd_epsr_maxguidance`、`anl4_fs_detail_estimate_1qf_v4_nd_sh_equity_median`、`max_book_value_per_share_guidance_2`、`max_gross_income_guidance_2`、`pv13_ustomergraphrank_auth_rank`、`pv13_ustomergraphrank_page_rank`、`pv13_com_rk_au`、`pv13_revere_zipcode`、`pv13_ompetitorgraphrank_hub_rank`。
- **7 个字段 0% 超时（C≥1, T=0）**：`rel_ret_all`、`rel_ret_part`、`pv13_revere_city`、`anl4_ptp_number`、`anl4_fs_detail_estimate_1qf_v4_nd_cff_median`、`anl4_fs_detail_estimate_1qf_v4_nd_cfi_mean` 等。
- **唯一混淆项** `pv13_com_page_rank`（T=4, C=3, rate 0.57）—— 既非决定性，**不拦**。

全局字段表也确认：这 14 个字段在**全部 42 条 COMPLETE 里 C=0** → 跨模板稳定信号。

### 2.3 机制假设（合理、未经 BRAIN 内部验证）

超时字段多为**稀疏 / 时点性 / 另类数据**（`anl4_*` 分析师预估、`pv13_*` 图谱排名、`max_*_guidance_*`、部分基本面）。它们作为**时序算子实参**（`ts_corr` / `ts_mean` / `ts_backfill` 的第一实参）流过时，BRAIN 回填/求值阶段在 ≈35% 因覆盖率缺口冻结。
> 注：初判"字段作 `ts_backfill` 实参才挂"被数据推翻 —— 23 处样本里字段实际是 `ts_corr` 实参、`ts_backfill` 在另一安全字段上。故护栏按"字段全局出现"拦截（观测精度 100%，见 §4 取舍说明）。

## 3. 实施（STDD test-first）

新建 `core/infrastructure/timeout_field_guard.py`：

- `TIMEOUT_PRONE_FIELDS`：数据驱动的 14 字段黑名单（由 `rebuild_timeout_blocklist()` 从结果文件重建，避免写死魔法值）。
- `extract_fields(expr)` / `is_timeout_prone(expr)` / `timeout_prone_fields_in(expr)`。
- `rebuild_timeout_blocklist(results_path, min_timeout=2)`：扫描结果文件，返回 `T≥2 且 C==0` 的字段集，随数据积累可刷新。

接线：

- **R3-C 生成端**（`candidate_generator.py`）：① `_substitute_fields` 不把超时字段选作替换目标；② `main()` 落盘前过滤含超时字段候选。
- **R3-A 提交端**（`candidate_submitter.py`）：借 session **之前**返回 `sim.status="SKIPPED_TIMEOUT_RISK"`（兜底安全网，省下 600s 空等）。

测试：`core/infrastructure/tests/test_timeout_field_guard.py`（6 passed + 20 subtests）。全量 **89 passed / 0 failed**。

## 4. 端到端验证（重启监督树后）

- 杀旧树 + 重拉 `start.py`（新树 CreationDate 8/2 19:04，心跳/8766 正常）。
- 新生成器重写 `candidates.json`（mtime 19:07:40）：**80 → 72**，日志 `R3-C: dropped 8 timeout-prone candidate(s)`，**含超时字段候选 = 0**。
- 提交端 `SKIPPED_TIMEOUT_RISK` 接线已落盘，作为兜底。

### 取舍说明（诚实标注）

全局字段拦截在观测数据上 **100% 精度**（45 次出现、0 次 COMPLETE），属保守策略。其中 `cap` 等在 rank 家族（`ts_zscore(cap,60)`）理论上可能跑完、被一并拦，但生成器有 4367 个字段可补位、本轮仅丢 8 个必挂候选、吞吐无损。若后续观测到某字段在 rank 家族能完成，可将其降级为"仅 Family B 上下文拦截"。

## 5. 预期收益与剩余待办

- **预期**：39% 的 TIMEOUT 浪费（每条白等 600s）将大幅下降，仿真预算利用率提升。
- **待办 A（可选诊断）**：给 TIMEOUT 返回加 `last_progress` + `elapsed_sec` 透传结果文件，以后不用翻日志即可见卡死点。
- **待办 P1-A（战略级，待拍板）**：因子预测质量本身低（sharpe/fitness 普遍近零/负），需生成配方硬化（横截面 rank 包裹 + 区域感知中性化 + 降 IND truncation）才能让因子真正达 1.5 门槛、IND 真 0→ACTIVE。
