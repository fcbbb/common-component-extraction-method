# 当前状态与接手说明

- 更新：2026-11-23
- 分支：`refactor/atomic-stage-blocks`
- 范围：`migration_scenario_validation/`（三场景迁移 benchmark）与 `src/component_method/`（组件方法流水线）

本文只回答三件事：现在哪一版是主线、证据在哪里、下一步做什么。设计原理见
[task_design_v3.md](task_design_v3.md)，执行细则见 [../RUNBOOK.md](../RUNBOOK.md)。

## 1. 先读哪里

| 想了解 | 文档 |
|---|---|
| 当前主线、已完成结果、未完成项 | 本文件 |
| V3 方法设计：anchor / transformation、语料、泄漏边界 | [task_design_v3.md](task_design_v3.md) |
| Windows → 麒麟的仓库切分 | [../v3/windows_to_kylin/SPLIT.md](../v3/windows_to_kylin/SPLIT.md) |
| 最终验证结果与结论边界 | [migration_scenario_validation_report.md](migration_scenario_validation_report.md) |
| P0/P1/P2 执行、镜像、gold 正控 | [../RUNBOOK.md](../RUNBOOK.md) |
| 三臂入口、预算与对照设置 | [unified_entry.md](unified_entry.md)、[../README.md](../README.md) |

## 2. 版本现状

| 版本 | 位置 | 状态 |
|---|---|---|
| V1 | `v1/ipp_vsipl_tasks/`、`v1/windows_to_kylin/tasks/`、`v1/cuda_to_musa/tasks/` | 历史任务包，保留用于基线 |
| V2 | `v2/windows_to_kylin/` | 任务包已并入 V3，仅保留设计、slate 与冻结库 |
| V3 | `v3/windows_to_kylin/` | **当前主线** |

V3 任务集：

- `v3/windows_to_kylin/tasks/` 有 20 个目录，其中 19 个含 `task.yaml`；`synthetic_multi_call_site` 只有骨架。
- `slate.yaml` 共 25 项，尚未打包的 6 项：`v2_poco_process`、`v2_nginx_process`、
  `v2_nginx_thread`、`v2_curl_thread`、`v2_curl_file`、`synthetic_multi_call_site`。
- 静态校验合计 **72 题**：20 IPP + 13 V1 Kylin + 20 MUSA + 19 V3。

组件库有两套：

| 库 | 位置 | 组件数 | 使用方 |
|---|---|---:|---|
| 手写 transformation 库 | `v3/windows_to_kylin/library/` | 5（T1–T5） | 18 个 V3 任务（`task.yaml` 默认引用） |
| 流水线生成库 | `v3/windows_to_kylin/library_generated/demo_new_flow_v4/` | 1 | 仅 `v3_poco_fs_stack` |

## 3. 已完成的验证与证据

证据目录被 `.gitignore` 排除，只保留在跑过实验的机器上；路径相对
`migration_scenario_validation/`。

| 项 | 结果 | 证据 |
|---|---|---|
| 静态结构 | 72/72 通过 | `tools/verify_task.py` |
| pin 检查（离线） | `ok=59 fail=0 judge_only=18` | `tools/check_pins.py --offline` |
| 麒麟 gold 正控 | 19/19 | `reports/gold_sanity/` |
| IPP gold 正控 | 20/20 | `reports/gold_sanity_ipp20/` |
| MUSA gold 正控 | 20/20 | `reports/gold_sanity/` |
| P2 agent 小样本（麒麟） | 6/6 判分通过 | `reports/agent_trial/p2_kylin/` |
| V3 `v3_poco_fs_stack` 配对 | 直接迁移 0/1；组件方法 1/1；gold 1/1 | `reports/bench/v3_poco_fs_stack_validation_report.md`；`reports/bench/v3_poco_fs_stack_*` |

`v3_poco_fs_stack` 的方法臂在 `method_r8` 检索到 1 个 bundle：
`posix-file-and-directory-request-backend-behind-a-96ebe29d`。成本、失败机制与结论边界见
[migration_scenario_validation_report.md](migration_scenario_validation_report.md) §3.2.1、§4。

## 4. V3 建库链路（重跑方法）

语料的 `before` 取建库任务的 `work/`，`after` 取 `gold/`（上游项目自身已完成的目标平台实现）；
**不取 agent 运行结果**，agent 运行只用于评测。

```bash
# 0) 先物化建库任务（需要网络与上游缓存）
bash v3/windows_to_kylin/tasks/l2_libuv_fs/prepare.sh
# 其余 4 个建库任务同样执行 prepare.sh

# 1) 构建历史语料（输出到 history/examples、index.json、lock.json，均不提交）
python3 tools/build_history_corpus.py --spec v3/windows_to_kylin/history/spec.yaml

# 2) 抽取 → 审核 → 发布 → 回放验证；产物默认写入 library_generated/
python3 tools/extract_transformation.py --stage all \
  --spec v3/windows_to_kylin/history/spec.yaml --resume
python3 tools/extract_transformation.py --stage verify \
  --spec v3/windows_to_kylin/history/spec.yaml
```

- 默认输出目录是 `v3/windows_to_kylin/library_generated/`，不会覆盖手写库
  `v3/windows_to_kylin/library/`。
- 任务使用的库由 `task.yaml` 的 `library_manifest` 决定；`slate.yaml` 第 110 行只是默认值。
- 手工库含 5 个组件；`demo_new_flow_v4` 是 `v3_poco_fs_stack` 的复现用产物（1 个组件）。
- `demo_new_flow_v4/runs/run_manifest.json` 记录的建库输入只有 `l2_libuv_fs`；上面的命令按
  spec 的 5 个任务重建，得到的组件集不保证与 `demo_new_flow_v4` 相同。

## 5. 复跑一次配对

需要麒麟镜像（`migration/kylin:sp3-p2`）与模型凭据；凭据读取顺序见
[../bench.yaml](../bench.yaml) 的注释与 [../REQUIREMENTS.md](../REQUIREMENTS.md)。

```bash
python3 tools/bench.py verify

python3 tools/bench.py run --arm default --scenario windows_to_kylin_v3 \
  --only v3_poco_fs_stack --label default_rN
python3 tools/bench.py run --arm method --scenario windows_to_kylin_v3 \
  --only v3_poco_fs_stack --label method_rN
python3 tools/bench.py gold --scenario windows_to_kylin_v3 \
  --only v3_poco_fs_stack --label gold_rN

python3 tools/bench.py compare --default-label default_rN --method-label method_rN
```

`windows_to_kylin_v3` 在 `bench.yaml` 中默认关闭，用 `--scenario` 显式选择。其余场景：

- `windows_to_kylin`：V1 历史任务（13 题）。
- `windows_to_kylin_v2` 已移除：V2 任务包并入 V3。
- `ipp_to_vsipl`、`cuda_to_musa`：V1 任务与 gold 正控。

### 5.1 已跑通的一次方法臂（`method_r8`）

`reports/bench/v3_poco_fs_stack_method_r8/`（本机，未提交）记录了一次完整通过的方法臂运行。
复现所需的配置如下，取值来自该次运行的 `attempt.json` 与终端记录：

| 项 | 值 |
|---|---|
| 任务 / 场景 | `v3_poco_fs_stack` / `windows_to_kylin_v3` |
| 臂 / DSH profile | `method` / `component-method-migration` |
| 模型 | `DeepSeek-V4.1-Flash-1017`（paratera 网关；凭据按 `bench.yaml` 注释从 `repository/.env` 读取） |
| DSH / Node | `0.2.2-rc.1` / `24.9.0` |
| 判分镜像 | `migration/kylin:sp3-p2`（`windows_to_kylin_v3` 的默认镜像） |
| 方法 prompt | `config/prompts/method_retrieval_only_system.txt`（`--method-prompt`，替换默认 workflow） |
| 组件库 | `library_generated/demo_new_flow_v4/library/manifest.json`（1 个组件） |
| 检索结果 | `posix-file-and-directory-request-backend-behind-a-96ebe29d` |
| 结果 | build ok；隐藏测试 72 项 pass；回归 22 项 pass；api gates pass；34 次迁移调用 + 5 次检索调用；2,019.5 s |

等价命令（模型也可由 `.env` 提供；库由 `task.yaml` 的 `library_manifest` 指定）：

```bash
python3 tools/bench.py run --arm method --scenario windows_to_kylin_v3 \
  --only v3_poco_fs_stack --label method_rN \
  --model DeepSeek-V4.1-Flash-1017 \
  --method-prompt config/prompts/method_retrieval_only_system.txt \
  --method-stage-image migration/kylin:sp3-p2
```

两个前提：

- **库不随仓库分发。** `library_generated/` 未提交；新环境要么从跑过实验的机器复制
  `demo_new_flow_v4/`，要么按 §4 重建。重建的输入与 `demo_new_flow_v4` 不同（见 §4），
  不能保证复现同一组件或同一 bundle id。
- **证据未提交。** `attempt.json`、`selection.json`、工作区与完整复盘
  （`reports/bench/v3_poco_fs_stack_validation_report.md`）都在 `reports/` 下，新环境不可见。
  复盘报告记录了判分与 agent view 的两处 harness 修复、r5/r8 配对口径和结论边界。

## 6. 未完成项

1. 补齐 slate 中 6 个任务包；`synthetic_multi_call_site` 目前只有目录骨架。
2. IPP → VSIPL 与 CUDA → MUSA 的 A/B 真实模型配对尚未开始。
3. 消融实验（仅共性组件、仅经验组件、两类同时）尚未执行。
4. `v3_poco_fs_stack` 每条件仅 1 次运行，且只由一条判别规则区分两组；结论不能外推为方法整体能力。
5. 组件库抽象层级仍有改进空间：审核后的卡片仍包含构建顺序与个别完整调用序列，见最终报告 §4。

## 7. 不提交 / 需单独决定的产物

以下由脚本生成或属于本机证据，不进入提交：

- `reports/`：运行证据、日志与工作区快照；
- 各任务的 `work/`、`build*/`（由任务目录内的 `.gitignore` 排除）；
- `v3/windows_to_kylin/history/examples/`、`index.json`、`lock.json`、`README.md`；
- `v3/windows_to_kylin/history/runs/`、`v3/windows_to_kylin/library_generated/`。

`gold/` 是 evaluator-only 的参考实现：V1 与 V3 已入库任务的 gold 随任务包提交，但不进入
`work/`；`v3_poco_fs_stack/gold/` 由 `prepare.sh` 从上游 checkout 复制生成，是否提交需显式决定
（提交后他人可直接跑 gold 正控，不提交则必须先执行 `prepare.sh`）。