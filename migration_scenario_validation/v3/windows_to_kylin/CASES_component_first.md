# 组件优先案例登记（Windows → Kylin）

- 建立：2026-11-23
- 目的：把「先建组件库，再围绕组件能力构造任务」的每个案例固定成一行可核对记录。
- 冻结库：[LIBRARY_full_20261123.md](LIBRARY_full_20261123.md)（5 个组件，digest `20612e42…57808`）
- 能力矩阵：[capability_matrix/matrix.md](capability_matrix/matrix.md)
- 待办：[TODO_component_first.md](TODO_component_first.md)

## 1. 案例总表

| 案例 | 任务 | 主组件（生成库） | 正控 | default | method | 状态 |
|---|---|---|---|---|---|---|
| C-POCO-PROC | `v2_poco_process` | `process-spawn-…-c7216288` | PASS（2126.7 s，快照） | 待跑 | 待跑 | 正控通过 |
| C-NGINX-PROC | `v2_nginx_process` | `process-spawn-…-c7216288` | PASS（276.9 s） | FAIL r1（1779.9 s） | 跑第 1 轮 | 配对中 |
| C-NGINX-THREAD | `v2_nginx_thread` | `portable-threading-…-96ad6495` | PASS（302.1 s） | 待跑 | 待跑 | 正控通过 |

对照：首次跑通的原案例 `v3_poco_fs_stack`（file 组件，`method_r8` 通过）见
[docs/current_state.md §5.1](../../docs/current_state.md)。

## 2. 多对多覆盖

来自 [capability_matrix/matrix.md](capability_matrix/matrix.md)：

- 一个组件服务多个任务：process 组件同时覆盖 `v2_poco_process`、`v2_nginx_process`（以及来源任务 `l2_libuv_process`）；threading 组件覆盖 `v2_nginx_thread`、`v2_curl_thread`、`v2_thread` 等。
- 一个任务使用多个组件：`v3_poco_fs_stack`、`v2_file`、`v2_path`、`v2_nginx_files`、`v2_curl_file` 等 8 个任务有 ≥2 个 primary 组件。

## 3. 每个案例的复现命令

通用前缀（在 `migration_scenario_validation/` 下）：

```bash
LIB=v3/windows_to_kylin/library_generated/full_20261123/library/manifest.json
../.venv/bin/python tools/verify_task.py --task-root v3/windows_to_kylin/tasks/<task> --json
../.venv/bin/python tools/gold_sanity.py --task-root v3/windows_to_kylin/tasks/<task> \
  --label <label> --timeout 3600

../.venv/bin/python tools/bench.py run --arm default --scenario windows_to_kylin_v3 \
  --only <task> --runs 3 --label default_<case>
../.venv/bin/python tools/bench.py run --arm method --scenario windows_to_kylin_v3 \
  --only <task> --runs 3 --label method_<case> \
  --method-prompt config/prompts/method_retrieval_only_system.txt \
  --bundle $LIB \
  --method-stage-image migration/kylin:sp3-p2
../.venv/bin/python tools/bench.py compare \
  --default-label default_<case> --method-label method_<case>

# 汇总各臂 attempt.json 成一张登记表
../.venv/bin/python tools/collect_case_results.py \
  --label default_<case> --label method_<case>
```

## 4. 结果与证据

### 4.1 gold 正控

| 案例 | 结果 | 耗时 | 备注 |
|---|---|---:|---|
| C-POCO-PROC | PASS | 2126.7 s | 在 `library_generated/gold_snapshots/v2_poco_process/` 快照上跑（`--no-prepare`），避免与其它任务共用 `work/`；build/tests/regression/api_removal/target_api 全 pass |
| C-NGINX-PROC | PASS | 276.9 s | `reports/gold_sanity/v2_nginx_process.json` |
| C-NGINX-THREAD | PASS | 302.1 s | `reports/gold_sanity/v2_nginx_thread.json` |

### 4.2 default 臂

`C-NGINX-PROC` r1（证据 `reports/bench/default_nginx_proc_r1/v2_nginx_process/run1/attempt.json`）：

- agent 正常提交（Submitted），92 次模型调用，输入 1,920,500 tokens / 输出 107,880 tokens，总耗时 1779.9 s。
- build **ok**；静态 smoke **PASS**（`NGINX_SMOKE=PASS port=28082`）。
- master/worker 探针 **FAIL**：起 worker、SIGHUP 换 worker 都正确，但 `SIGQUIT` 后 master 2565 未退出。
  `NGINX_PROCESS_PROBE=FAIL master 2565 did not exit on SIGQUIT`。
- 判别规则：构建与基本服务能力不区分两臂；区分点是“退出信号触发 master 结束、worker/pid 文件回收”的进程生命周期契约。

### 4.3 method 臂

待回填。