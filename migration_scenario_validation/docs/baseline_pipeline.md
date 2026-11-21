# 基线链路（condition A：直接迁移，不做组件抽取）

本目录把「直接用 DSH agent 迁移」这条臂跑通，作为后续配对 A/B 的对照。
基线条件不给 agent 组件库、不给参考实现、不给隐藏测试，只给 workspace、
任务 spec 和一个受控 bash。判分与 gold 正控用完全相同的 harness。

## 1. 覆盖范围

三个场景各一道，已在本机做过端到端管线自检：

| 场景 | 任务 | 执行方式 | 判分方式 |
|---|---|---|---|
| `ipp_to_vsipl` | `l2_rubberband_fft` | 本机 Docker `migration/ipp:cpu` | 本机 Docker，jvsip 只读挂载 |
| `windows_to_kylin` | `l2_libuv_thread` | 本机 Docker `migration/kylin:sp3-p2` | 本机 Docker |
| `cuda_to_musa` | `b_l2_layer_norm` | 远端 MTT S4000 上的 pinned DSH（`bash` 工具） | 远端 MTT S4000，同一文件系统 |

MUSA 机器上没有 Docker，但可以运行 Node：pinned DSH 安装在租用机上，agent 的
命令、方法阶段和判分都在远端执行，工作区只有远端这一份副本。
`--musa-transport local` 仍保留 `tools/docker_api_shim.py`，只用于不连远端的
工具路径自检。

## 2. 组成

```
tools/baseline_trial.py    三个场景的统一编排器（本轮新增）
tools/docker_api_shim.py   Docker API 子集 → 本地/SSH shell（本轮新增）
env/Dockerfile.ipp         IPP CPU 沙箱（本轮新增，已构建）
env/remote.yaml            MUSA 连接信息（需自行创建，未提交）
reports/baseline/<label>/  每次运行的 attempt.json、diff、summary.json
```

`baseline_trial.py` 复用了 `tools/agent_trial.py` 的 prepare、workspace
复制、chown、DSH backend、fake model、判分命令，避免两套行为漂移。

## 3. 快速自检（不花钱，不需要 GPU）

```bash
cd common-component-extraction-method/repository/migration_scenario_validation

# 3.1 只检查选择、参数和摘要，不起容器
python3 tools/baseline_trial.py \
  --only l2_rubberband_fft --only l2_libuv_thread --only b_l2_layer_norm \
  --runs 1 --fake-model --dry-run --label dryrun_three
# SUMMARY pass=0 fail=0 error=0 skip=3

# 3.2 判分正控：把 gold 塞进 workspace，证明判分链路能 PASS
python3 tools/baseline_trial.py --only l2_rubberband_fft \
  --runs 1 --fake-model --seed-gold --label plumbing_ipp
python3 tools/baseline_trial.py --only l2_libuv_thread \
  --runs 1 --fake-model --seed-gold --label plumbing_kylin
# 期望：PASS，build=ok tests=pass api=pass

# 3.3 负控：不迁移，判分必须 FAIL（当前源码编译不过）
python3 tools/baseline_trial.py --only l2_rubberband_fft \
  --runs 1 --fake-model --label negative_ipp
python3 tools/baseline_trial.py --only l2_libuv_thread \
  --runs 1 --fake-model --label negative_kylin
# 期望：FAIL，build=fail tests=skipped

# 3.4 MUSA 工具路径自检：不连远端、不判分
python3 tools/baseline_trial.py --only b_l2_layer_norm \
  --runs 1 --fake-model --seed-gold --musa-transport local --label plumbing_musa
# 期望：SKIP（agent=Submitted），shim 日志里每个 exec 都是 200/201
```

`--seed-gold` 只用于验证「判分器能过」。它把 gold 复制进 workspace，
**不能**用来统计基线通过率；正式基线不要带这个参数。

## 4. 正式运行

### 4.1 IPP 与 Kylin（本机）

```bash
# 先确认镜像
docker image inspect migration/ipp:cpu >/dev/null
docker image inspect migration/kylin:sp3-p2 >/dev/null

python3 tools/baseline_trial.py \
  --only l2_rubberband_fft --only l2_libuv_thread \
  --runs 1 --label baseline_local_v1
```

模型凭据来自仓库根 `.env`（`../.env`，`OPENAI_API_BASE` / `OPENAI_API_KEY` /
`MODEL_NAME`），也可用 `--api-base/--api-key/--model` 覆盖。默认
`deepseek-v4.1-flash-1017` 由 `.env` 决定（如未写则用 `--model`）。

### 4.2 MUSA（远端 MTT S4000）

1. 创建 `env/remote.yaml`（模板见 `env/remote.yaml.example`）：

```yaml
host: <远端 IP 或域名>
user: <ssh 用户>
port: 22
remote_root: /data/migration-bench
ssh_opts:
  - "-o"
  - "StrictHostKeyChecking=accept-new"
  - "-o"
  - "ConnectTimeout=10"
# 无 tty 的 ssh/rsync 通过该脚本回答密码提示
askpass: /home/fcbbbb/.ssh/musa-askpass.sh
# 可选：低权限 agent 用户（强烈建议）
# agent_user: bench
# 该租用容器没有 CAP_SYS_ADMIN，unshare -n 不可用；用死代理做软隔离
isolate_network: false
block_network_env: true
```

密码不写进 `remote.yaml`：`askpass` 指向的脚本从 0600 文件读取，
`remote.yaml` 本身在 `.gitignore` 中。

2. 确认免密 SSH、远端有 `python3`、`PyYAML`、`torch_musa`、`rsync`，
   以及（启用网络隔离时）`unshare -n`：
   编排器会在跑任何任务前执行 preflight，失败直接退出 2。shim 会读取远端
   login shell 的 `PATH` 并前置到每条命令，保证 `mcc` 可见；其它环境变量
   不复制，避免把凭据暴露给 agent。

   ```bash
   ssh <user>@<host> 'python3 -c "import yaml, torch, torch_musa; print(torch.musa.is_available())"'
   ```

3. 若使用 `agent_user`，该用户必须能被 ssh 用户免密 sudo：

   ```bash
   ssh <user>@<host> 'sudo -n -u bench -- id'
   ```

4. 运行：

```bash
python3 tools/baseline_trial.py --only b_l2_layer_norm \
  --runs 1 --label baseline_musa_v1
```

每次尝试会自动：

- 把本仓库同步到 `<remote_root>/repo`（排除 `work/`、`gold*/`、`reports/`、
  `env/remote.yaml`、`.env`、密钥文件）；
- 把 workspace 同步到 `<remote_root>/runs/<label>/<tag>/workspace`；
- 启动 shim，把 `/workspace` 映射到远端 workspace；
- agent 结束后拉回 workspace，做 diff；
- 在远端按同一 harness 判分，取回 JSON 报告。

### 4.3 三题一起跑

```bash
python3 tools/baseline_trial.py \
  --only l2_rubberband_fft --only l2_libuv_thread --only b_l2_layer_norm \
  --runs 1 --label baseline_three_v1
```

## 5. 产物与判定

```
reports/baseline/<label>/
  summary.json
  <task>/run<N>/attempt.json
  <task>/run<N>/workspace.diff
  <task>/run<N>/agent/             # DSH 会话输出
  workspaces/<task>-r<N>/          # 跑完的 workspace
```

`attempt.json` 关键字段：

- `condition: baseline_direct`、`scenario`、`level`、`model`、`dsh_runtime`
- `transport`: `docker` / `ssh` / `local`
- `agent_status`: DSH 返回的 `Submitted`、`LimitsExceeded` 等
- `judge.report`: runner 的 build/tests/api_removal 完整结果
- `gold_seeded`: 仅自检时存在
- `status`: `pass` / `fail` / `error` / `skip`

退出码：`0` 无失败（允许 skip）、`1` 有尝试失败、`2` 环境/准备错误、
`3` 没选到任务。

## 6. 隔离与已知限制

- **gold 不上远端**：`repo` 同步显式排除了 `gold`、`gold_authored`、
  `upstream_nonconforming`，agent 只能看到 `work/` 快照。
- **远端用户隔离**：建议配置 `agent_user`。shim 用
  `sudo -n -u <agent_user> --` 执行命令，并在同步后 `chmod 700 repo`。
  未配置时 agent 以 ssh 用户身份运行，同机其他 run 目录对它可见；
  正式统计前应补齐该用户。
- **网络隔离**：`isolate_network: true` 用 `unshare -n` 包住每条命令；
  当前租用容器没有 `CAP_SYS_ADMIN`（`unshare` 报 Operation not permitted），
  因此改用 `block_network_env: true`，给每条命令注入指向 `127.0.0.1:9`
  的 `HTTP(S)_PROXY`。这是软门（pip/curl/wget/git/PyTorch 会遵守），
  不是内核级防火墙；正式统计时若换成有权限的机器，应改回 `unshare -n`。
- **远端 root**：当前只有 root 账号，未配置 `agent_user`，agent 以 root
  执行。域名/密码只在本机；远端只同步 `work/` 快照与判分所需 harness，
  gold 目录与 `musa_new_model_*` 实测为 0 个。
- **MUSA `--musa-transport local` 只验证 agent 工具路径**，判分为
  `skip`；它不能作为 MUSA 通过率证据。
- **`--seed-gold` 不是基线**：只证明判分器可过。负控（不迁移）必须
  `FAIL`，这也是每次改 harness 后的必跑项。
- **时间**：单次 MUSA 基线按题难度约 10–70 分钟；三题一轮预计
  1–2 小时（不含镜像/远端同步）。完整 20 题 ×1 的预估见
  `reports/agent_trial` 与既有估算（中位约 7 小时）。
- **workspace 复用**：每次尝试重建 workspace；Kylin/IPP 的旧 workspace
  属于 uid 10001，由 `_copy_workspace` 在 root 容器里删除。

## 7. 本轮已执行的自检记录

| 检查 | 结果 |
|---|---|
| `py_compile` 两个新工具 | 通过 |
| IPP 镜像构建 | `migration/ipp:cpu`（GCC 13.3 / CMake 3.28 / Python 3.12 + PyYAML） |
| IPP gold 播种判分 | PASS，52.4s |
| Kylin gold 播种判分 | PASS，64.3s |
| IPP 未迁移负控 | FAIL（build=fail），8.9s |
| Kylin 未迁移负控 | FAIL（build=fail），14.5s |
| MUSA `--musa-transport local` 工具路径自检（fake model） | SKIP，agent=Submitted，4.0s（只验证 shim 工具名，不是链路证据） |
| 三题 dry-run | 选择正确，退出 0 |
| MUSA 远端链路（SSH + askpass + 远端 pinned DSH + 远端判分） | **PASS**；`dsh 0.2.2-rc.1` / Node 24.9.0 / profile `component-method-host-operator`，工作区只有远端一份副本 |
| MUSA 方法臂 host 阶段平面（fake model） | 适配器 `active (remote)`（`--workspace` 指向尝试工作区），会话环境含 `COMPONENT_DSH_STAGE_RUNTIME=host`，无 Docker 报错；fixture 不产出提交，按约定以 `NoValidatedSubmission` 结束 |
| MUSA 远端 58 包抽取（host 平面，fake model） | 58/58 包走 host 阶段 agent；`agent_task.txt` 无 `/testbed`、`/component-output`、`controlled_bash`；`workspace_integrity.json` unchanged（572 文件） |
| 远端 job 状态持久化 | `source_scan --job`（kernel CLI，starter 退出后轮询）→ `succeeded`，58 包 summary 可读；修复了监控线程随 kernel 退出导致的永久 `running` |
| 远端 gold 泄漏检查 | repo 内 `gold`/`gold_authored`/`work` 目录 0 个、`musa_new_model_*` 0 个；workspace 0 个 |

MUSA 链路已连通（`env/remote.yaml` 已配置，密码在 `~/.ssh/` 下的 0600
文件）。剩余步骤只是用真实模型跑基线：

```bash
python3 tools/baseline_trial.py --only b_l2_layer_norm --runs 1 --label baseline_musa_v1
```

## 8. 方法臂（condition B）：单主 agent

同一个 `baseline_trial.py` 用 `--arm method` 驱动 B 臂，或用
`./run-method.sh`（内部调用 `bench.py run --arm method`）。每次尝试只有一个
DSH 会话，使用 `component-method-migration`（唯一方法入口
`component_run_stage` + `controlled_bash` + DSH 内置作业工具；不加载逐阶段和
任务执行/报表插件，迁移工作区下 kernel 也拒绝任务执行/报表阶段）。主 agent 在当前
尝试的工作区上依次调用同一个入口的
`stage=prepare → build → audit → publish → retrieval →
validate_selection → materialize_selection`，把选中的
组件物化到 `/workspace/component_bundle/`，然后**在同一个会话里**按任务提示完成迁移。
组件审核与 20 题方法一致（`max_review_repair_rounds: 1`，一次返修 + 定向复审），只有
审核通过的组件会发布进库。`build`/`audit`/`retrieval` 是后台作业，由内置运行时
负责等待、完成通知和空闲唤醒；所有结果（同步/异步）都是同一张
`status`/`summary`/`artifacts`/`error_code` 单。
固定工作流提示词在
[config/prompts/method_workflow_system.txt](../config/prompts/method_workflow_system.txt)。

预算口径：这个主 agent **默认不设步数上限**，`bench.yaml` 的
`method_main_timeout` 只是墙钟安全上限；需要同预算对照时把
`method_step_limit` 设成与 A 相同的值。`method_extraction_workers` /
`method_review_workers` / `method_agent_timeout` 控制内部抽取并发。
`attempt.json` 记录 `method_budget`（`step_limit` 默认 `null`）、`method_tool_calls`、
`method_prompt_sha256`、`component_bundle`、`task_image`（`Id`/`RepoDigests`）以及
`method_stage_usage`（嵌套抽取/检索的模型调用、token 和成本）。只有将来额外启动
一个专门执行迁移任务的子 agent 时，那个子 agent 才使用 A 臂的预算口径；当前
runner 不启动它。
工作流没有产出可用 bundle 时该尝试记为 `error`，不能当作 B 臂的通过或失败。

阶段产物与保护机制见 [unified_entry.md](unified_entry.md) 的“方法臂：单主 agent”。
MUSA `ssh` 传输下整个执行面都在远端：pinned DSH 装在租用机上，方法阶段用
`COMPONENT_DSH_STAGE_RUNTIME=host` 在同一文件系统里跑（租用机没有 Docker），
不需要 `--method-stage-image`。host 平面没有 namespace 隔离，仓库只读靠提示词
约定和阶段前后 sha256 校验；检索阶段也无法对 agent 掩盖仓库。