# 统一入口：默认 DSH 与方法 DSH（单主 agent）

本目录有两个一键入口，覆盖同一批 60 个迁移任务包，使用同一套判分：

| 入口 | 条件 | DSH profile | 会话数 |
|---|---|---|---|
| `./run-default.sh` | A：直接迁移 | `component-method` | 1 |
| `./run-method.sh` | B：组件方法 | `component-method-migration`（单主 agent，仅方法工具） | 1 |

两个入口都调用同一个 runner（`tools/baseline_trial.py`）、同一个判分器
（`shared/harness/runner.py`）、同一个模型路由和同一份任务镜像。B 与 A 的差异只有：

1. B 的主 agent 额外加载组件方法工具，系统提示里有一段**固定工作流**；
2. B 的主 agent 先把组件库建好并物化到 `/workspace/component_bundle`，然后在
   **同一个会话**里完成迁移。

任务提示、任务镜像、构建/判分命令、`controlled_bash` 工具面完全一致。**被判分的
产物是主 agent 的工作区。**

## 一键启动

```bash
# 0. 一次性自检：Python/DSH/Node/插件/镜像/凭据
./bootstrap.sh                               # --fix 跑 npm ci/build，--build-images 建镜像
python3 tools/bench.py doctor
python3 tools/bench.py doctor --arm method   # 额外检查方法 profile 与固定提示词

# 1. 静态校验（不需要编译器/GPU）
python3 tools/bench.py verify

# 2. 构建 bench.yaml 里声明的镜像（MUSA 无自动构建，会标 MANUAL）
python3 tools/bench.py env --scenario windows_to_kylin

# 3. 正控（判分链路自证）
python3 tools/bench.py gold --scenario windows_to_kylin --level L1

# 4. 两臂各跑一次 smoke（每个场景 1 题）
./run-default.sh
./run-method.sh

# 5. 全量（60 题 × 配置的 runs）
./run-default.sh --all --runs 3 --label default_v1
./run-method.sh  --all --runs 3 --label method_v1

# 6. 证据
python3 tools/bench.py report --label default_v1
python3 tools/bench.py compare --default-label default_v1 --method-label method_v1
```

不用凭据、不花钱的接线自测：

```bash
./run-default.sh --dry-run
./run-default.sh --scenario windows_to_kylin --only l1_poco_thread --fake-model --label selftest
./run-method.sh  --scenario windows_to_kylin --only l1_poco_thread --fake-model --label selftest_m
```

`--fake-model` 会启动本地 fixture 模型，只验证 DSH profile 加载、工具调用、
提交协议和判分链路，不产生能力信号。方法臂在 `--fake-model` 下通常不会产生
`component_bundle`，该次尝试记为 `error`，不会伪装成通过。

## 配置单源

| 文件 | 作用 | 是否提交 |
|---|---|---|
| [bench.yaml](../bench.yaml) | 两臂 profile、镜像、预算、场景开关、构建命令 | 提交 |
| `bench.env` | 本机凭据、`VSIPL_ROOT`、可选准备参数 | 不提交（已 ignore） |
| [bench.env.example](../bench.env.example) | 上者的模板 | 提交 |
| `../.env`（仓库根） | 模型路由，优先级高于 shell 环境 | 不提交 |
| [env/version_matrix.yaml](../env/version_matrix.yaml) | 工具链/运行时版本记录 | 提交 |

`bench.py` 支持 `${VAR}` 和 `${VAR:-default}`。模型凭据不由 `bench.yaml`
接管：`baseline_trial.py` 的优先级是 CLI flag > 仓库根 `.env` > 继承环境，
避免 shell 里过期的路由覆盖项目自己的 `.env`。

预算口径：

```yaml
budgets:
  step_limit: 150              # 仅 A 臂（直接迁移）
  total_timeout: 5400          # 仅 A 臂
  command_timeout: 600
  method_main_timeout: 14400   # B 主 agent 的墙钟安全上限，不是预算
  method_step_limit: null      # 可选：设成 A 的 step_limit 做同预算对照
  method_extraction_workers: 2
  method_review_workers: 2
  method_agent_timeout: 3600
```

B 的主 agent **默认不设步数上限**：组件抽取开销大，用 A 的 `step_limit` 卡它会让
方法臂在准备阶段就被截断。需要严格比较“同样步数预算下方法是否值得”时，把
`budgets.method_step_limit` 设成与 A 相同的值即可；它是可选项，默认 `null`。
命令行等价写法是 `./run-method.sh --method-step-limit 150`（`bench.py run` 也接受
同名参数）。
如果以后额外启动一个专门执行迁移任务的子 agent，那个子 agent 才使用 A 的预算
口径；当前 runner 不启动这个子 agent。

## 一致性是如何保证的

- 同一 `--parent` / `--only` 选出的任务包、同一 `prepare.sh`、同一 `runner.py`；
- 同一模型、同一任务镜像、同一 `command_timeout`、同一判分命令；
- B 只增加方法工具和固定工作流提示，任务提示与 A 相同；
- 每次尝试的 `attempt.json` 记录 `arm`、`condition`、`dsh_profile`、
  `method_profile`、`method_budget`（`step_limit` 默认 `null`）、固定提示词的
  SHA-256（`method_prompt_hashes`）、组装后系统提示的 SHA-256
  （`method_prompt_sha256`）、按工具名统计的 `method_tool_calls`、
  `method_stage_usage`（嵌套抽取/检索的实际用量）、`component_bundle` 状态、
  `task_image`（`Id`/`RepoDigests`/`Created`），以及完整 `dsh_runtime`：DSH 版本、
  Node 版本、lockfile SHA-256、profile patch SHA-256、全部插件 bundle 的 SHA-256；
- `summary.json` 记录同一组身份和预算；`bench.py compare` 按 task 配对，并标出
  没有产出可用 bundle 的无效 B 尝试。

`doctor` 会显式提示 `COMPONENT_DSH_PROFILE` 是否污染当前 shell；运行时会按
请求级 `profile_name` 覆盖它。

## 方法臂：单主 agent

方法插件调用的是 `python3 -m component_method.dsh_kernel`。每个尝试先由
[tools/method_adapter.py](../tools/method_adapter.py) 把当前迁移任务映射成方法侧
任务根：

```text
<attempt>/method/
├── registry.json                 # COMPONENT_DSH_RUN_REGISTRY
├── adapter.json                  # 本次映射清单（run_id/task_id/workspace）
├── tasks/<task_id>/config.json   # 方法阶段读取的配置
├── tasks/<task_id>/task.json
├── tasks/<task_id>/outputs/full_library/   # 主 agent 发布到这里
└── offline_tasks/<task_id>/task.json
```

`config.json` 使用 `source_scan_mode: migration`：`prepare` 块直接扫描本次尝试的
工作区（不依赖预先冻结的候选文件）。抽取之后走与 20 题方法相同的组件审核流程
（`build` 冻结审核输入，`audit` 完成审核与返修，`max_review_repair_rounds: 1`，
含一次返修与定向复审），`publish` 从 `review_v1/` 发布 schema-8 组件库；只有审核
通过的组件会进入库。
语言后端由场景决定：IPP/Kylin 用 `cpp@1`，MUSA 用 `python@1`。

### 固定工作流

固定提示词只有一份：[config/prompts/method_workflow_system.txt](../config/prompts/method_workflow_system.txt)。
它被追加在场景的基础迁移系统提示之后，并附上本次的注册身份
（`run_id` / `task_id`）。B 臂使用最小 profile `component-method-migration`，
只加载 `controlled_bash`、**唯一的方法入口** `component_run_stage`，以及 DSH 内置的
作业工具（`job_output` / `job_list` / `job_kill`，由 `tool-jobs` 提供）。逐阶段插件和
任务执行/报表插件不加载，模型只能从 `component_run_stage` 的 `stage` 进入。提示词
写明本次要执行哪些块；kernel 仍允许调用工作区不支持的阶段，但会返回
`STAGE_UNSUPPORTED`，让失败以结果单的形式出现，而不是靠工具表隐藏。

主 agent 按顺序调用同一个工具，用 `stage` 选择块：

```text
run_stage(stage=prepare)
  → run_stage(stage=build)               # 后台作业，返回 job_id + status: running
  → run_stage(stage=audit)               # 后台作业
  → run_stage(stage=publish)             # 只发布审核通过的组件
  → run_stage(stage=retrieval)           # 后台作业
  → run_stage(stage=validate_selection)
  → run_stage(stage=materialize_selection)
  → 读取 component_bundle 并完成迁移
```

长块（`build`、`audit`、`retrieval`）通过 `ctx.jobs` 启动：工具立即返回
`status: "running"` 和 `job_id`，主 agent 用
`job_output {"job_id": ..., "wait": true, "timeout_ms": 600000}` 等到终态（作业结束时
内置运行时也会发**完成通知**，空闲的主 agent 会被唤醒，两种方式拿到的是同一张结果
单）。短块（`prepare`、`publish`、`validate_selection`、`materialize_selection`）
同步执行，直接返回同一张结果单。原来自制的
`component_job_status` / `component_job_cancel` 已删除，等待、通知、唤醒都由 DSH
内置作业运行时提供。

迁移仍然是任务提示要求的那一套：改源码、构建、提交完成标记。bundle 只作为参考
材料；agent 仍然对完整迁移负责，且不得修改 bundle 内的文件。

kernel 会为这些阶段做额外保护：

- **前置条件**：缺少上一阶段产物时直接返回 `error_code=STAGE_INPUT_MISSING`，
  不启动子进程；`run_stage` 按请求的 `stage` 字段检查同一套条件。
- **并发锁**：同一任务根的阶段互斥。同步调用在锁被占用时返回
  `error_code=STAGE_BUSY`；`build`/`audit`/`retrieval` 这类作业块由
  `component_method.workflow.stage_lock` 包装进程持有同一把锁，作业会排队等待，
  不与同步阶段并发写同一个任务根。不同迁移任务各有自己的任务根，因此仍可
  并行。
- **迁移工作区限制阶段**：当 `config.json` 的 `source_scan_mode` 为 `migration`
  时，kernel 拒绝 `task`/`report`（`error_code=STAGE_UNSUPPORTED`）。迁移任务由主
  agent 在同一会话完成；`retrieval` 仍可运行，用于物化组件 bundle。抽取、审核与
  检索块在迁移工作区照常运行。
- **工作区冻结**：`prepare` 记录本次工作区所有可抽取文件的
  `workspace_sha256`/`workspace_files`；`build` 启动前会重新计算并比对，
  工作区被主 agent 改动时直接失败（`workspace changed after source_scan`），
  防止“先抽取、后改源码”造成的方法/任务环境漂移。
- **统一结果单**：同步阶段、后台作业、失败响应都返回同一组字段
  `status` / `summary` / `artifacts` / `error_code`。`summary` 从阶段自己的
  `summary.json` / `manifest.json` 读取，`artifacts` 给出产物路径；
  `status` 取 `succeeded` / `running` / `failed` / `cancelled`。失败时还带
  `error_code`（如 `STAGE_FAILED`、`STAGE_BUSY`、`STAGE_INPUT_MISSING`、
  `STAGE_UNSUPPORTED`、`BAD_REQUEST`）和 `error` 文本。后台作业结束时同一张
  JSON 单作为作业的 `result` 交给完成通知或 `job_output`，agent 不需要解析
  stdout，也不存在“同步一种格式、异步另一种格式”的切换。
- **实验身份**：每次尝试记录任务镜像的 `Id`/`RepoDigests`/`Created`、
  `method_stage_image`、远端 MUSA 运行时版本、固定提示词（工作流、抽取、检索、
  协议契约 schema）的 SHA-256，以及
  嵌套抽取/检索阶段的实际模型调用、token 和上报成本，便于事后核对两臂是否真的
  跑在同一环境。

### 有效性判定

主 agent 的会话结束后，runner 检查工作区里的 `component_bundle`：目录里必须有
文件；若 `manifest.json` 声明了 `component_count`，则它必须大于 0。没有可用
bundle 的尝试记为 `error`，`detail` 说明原因，不进入判分。这样“跳过方法直接
迁移”不会冒充 B 臂结果。

## 预算口径

| 角色 | 是否受预算约束 | 记录位置 |
|---|---|---|
| A 主 agent（直接迁移） | 是：`budgets.step_limit` / `total_timeout` | `attempt.json: agent_*` |
| B 主 agent（组件工作流 + 迁移） | **默认否**：只有 `method_main_timeout` 墙钟安全上限；显式设置 `method_step_limit` 时与 A 同预算 | `attempt.json: agent_*`、`method_budget` |
| 可选的额外任务执行子 agent | 是：与 A 同预算（当前不启动） | 将来单独记录 |

报告时给出两臂的任务指标（resolved/compile/numerical/API-removal），并同时给出
B 的组件工作流调用量与 bundle 规模；不能把组件开销挤进 A 的任务步数。

## 已知边界

- **MUSA `ssh` 传输：整个执行面都在远端，方法阶段没有 Docker**：租用机没有
  Docker daemon、没有 `CAP_SYS_ADMIN`、也没有 Node/DSH，因此不能在那里套容器。
  现在 pinned DSH（0.2.2-rc.1 + Node 24.9.0）直接装在远端，主 agent、方法内核
  和判分器都在远端运行；尝试目录（`<remote_root>/runs/<label>/<tag>`）就是远端
  上的唯一副本，没有 rsync 镜像。方法阶段由 `COMPONENT_DSH_STAGE_RUNTIME=host`
  选择 host 平面：抽取/检索阶段是远端 DSH 进程里的普通子进程，agent 用 stock
  `bash` 工具，提交目录由 runner 自己校验（`submission_mode=none`）。代价与边界：
  - **没有文件系统/网络隔离**：阶段 agent 与主 agent 使用同一 uid、同一网络，
    只靠提示词约束“仓库只读、只写提交目录”；
  - **只读靠合同 + 哈希**：runner 在阶段前后对工作区做 sha256 快照
    （`workspace_integrity.json`），发现变化直接失败，但不阻止写入；
  - **检索无法掩盖仓库**：容器平面可以把仓库从检索 agent 视野里隐藏，host 平面
    做不到，`metadata.json` 会记录这一限制；
  - 阶段不能跨尝试恢复（没有容器可复用），中断后按工作流重跑。
- **本地 Docker 场景：阶段进程在宿主机运行，容器只是沙箱**：`run_stage` 由
  宿主机 Python 启动，抽取/检索再通过 `DOCKER_HOST` 在 `runtime_image` 里执行。
  因此宿主机需要 `component_method` 可导入、Docker 可访问；镜像需要目标工具链。
  MUSA 远端没有 Docker，改用上面的 host 平面。
- **方法工作流要求主 agent 只读源码、把方法产物写到 `component_bundle/`**；
  方法侧配置和库都在 `<attempt>/method/`，不在工作区内。
- **`component_bundle/` 不参与判分**：判分器只构建/测试任务目标文件，bundle 中
  的参考文件不会进入构建，也不会覆盖隐藏测试。

## 还应该做哪些内容

1. **真实模型 A/B 全量**：两臂各 60 题 × 3 次的配对运行尚未开始；先跑 smoke，
   再按 `bench.py compare` 的配对结果报告。
2. **镜像可复现性**：`bench.yaml` 目前记录镜像 tag；runner 已在每次尝试中记录
   `task_image` 的 `Id`/`RepoDigests`/`Created`，可据此核对两臂环境。正式实验仍应
   在 `bench.yaml` 里固定 image digest，避免 `:cpu` / `:sp3-p2` 被重建后漂移。
3. **检索阶段的镜像验证**：Kylin/IPP 镜像内尚未实测 `run_stage(stage=retrieval)` 的
   完整流程（需要 `python3` 和检索运行时）；先在两场景各跑一次并保存
   `retrieval_v1/result.json`。
4. **MUSA 方法策略（host 平面已接）**：整个执行面在远端，方法阶段用
   `COMPONENT_DSH_STAGE_RUNTIME=host` 在远端 DSH 进程里跑，不再需要
   `method_stage_image`，也没有工作区镜像。仍待用真实模型验证的是 58 包抽取在
   host 平面的总时长，以及 host 阶段没有隔离带来的风险是否可接受。
5. **可选的任务执行子 agent**：如果要把“迁移阶段”严格压到 A 的预算，可以让主
   agent 只做准备，再额外启动一个带 A 预算的子 agent；该模式尚未实现，也不是
   默认路径。当前可用 `method_step_limit` 让整个 B 主 agent 与 A 使用同一预算。
6. **负例**：方法工具要有 `expect_fail` 负例（引用未发布组件、篡改库内文件必须被
   checker 拒绝）；两臂各保留一次 gold 正控。
7. **打包/分发**：本目录已移入 `repository/`，`work/`、`gold/`、`build*/`、
   `reports/`、`bench.env`、`env/remote.yaml` 由 `.gitignore` 排除（`gold/` 由
   `prepare.sh` 重新生成）。接收者在 `./bootstrap.sh` 通过后即可启动；镜像与
   MUSA 环境由使用者按 [REQUIREMENTS.md](../REQUIREMENTS.md) 自备。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `doctor` FAIL `dsh plugin bundles` | 插件没构建 | `cd ../dsh && npm ci && npm run build`（或 `./bootstrap.sh --fix`） |
| `doctor` FAIL `node` | Node 版本不是 24.9.0 | `nvm use 24.9.0`；或设 `COMPONENT_DSH_NODE_BIN` |
| `doctor` WARN `method prompts` | 固定提示词缺失 | 恢复 `config/prompts/method_workflow_system.txt` |
| `bundle=missing` / `status=error` | 主 agent 没有产出可用 bundle | 看 `agent/` 日志与 `attempt.json.method_tool_calls`；先确认 `method_adapter` 成功、镜像内有工具链 |
| `error_code=STAGE_INPUT_MISSING` | 跳过了前置阶段 | 按固定工作流重跑；kernel 不会读 stdout 猜测进度 |
| `error_code=STAGE_BUSY` | 同步阶段与正在运行的作业/另一个同步阶段冲突 | 先用 `job_output(wait=true)` 等到该作业终态或等完成通知，再继续；不同任务可并行 |
| `error_code=STAGE_UNSUPPORTED` | 在迁移工作区调用了任务执行/报表阶段 | 按固定工作流跑到 `materialize_selection` 为止，迁移由主 agent 自己在会话里完成 |
| `error_code=STAGE_FAILED` / `JOB_MISSING` | 作业失败，或 `job_id` 不属于当前会话 | 看完成通知 / `job_output` 返回的 `summary` 和 `error`；`job_list` 可以列出本会话的作业。不要重试已失败的作业，按工作流重新启动阶段 |
| `workspace changed after source_scan` | 抽取启动前工作区与冻结哈希不一致 | 撤销对工作区的改动后重跑；抽取期间源码必须保持不变 |
| `method_stage_image ... is not present` | 本地 Docker 场景的准备容器在宿主机跑，目标镜像不在本地 | 设 `METHOD_STAGE_IMAGE`（本地有 bash + python3 的镜像）或 `--method-stage-image`；MUSA `ssh` 的 host 平面不需要镜像 |
| `workspace push failed`（MUSA） | 仅 `--musa-transport local` 的 shim 自检会镜像 rsync；`ssh` 传输不镜像 | 检查 ssh/rsync、远端目录权限与 `agent_user` 的免密 sudo；push 失败时命令不会执行 |
| `ERROR no model credential` | 没有凭据 | 填仓库根 `.env` 或 `bench.env`，或 `--fake-model` |
| `language backend is not installed: cpp` | 用系统 `python3` 启动，解释器缺 `libclang`/`tree-sitter`，cpp 后端不注册 | 用仓库 `.venv/bin/python` 运行 `tools/baseline_trial.py`（先按 README 建 venv） |
| API 返回 `team_model_access_denied`，报错里的模型名带部署后缀（如 `-P029`） | `MODEL_NAME` 用了非规范别名，网关把它路由到本 key 未授权的部署，长跑必挂 | `MODEL_NAME` 填 `/v1/models` 列出的规范 id（`DeepSeek-V4.1-Flash-1017`）；换模型后 A/B 两臂一起重跑 |
| `agent=LimitsExceeded` | A 臂步数预算不足 | 调整 `budgets.step_limit` 并重跑；不要把截断当通过 |
| `build=fail`（空工作区） | 正常负控结果 | 判分链路已工作，不是入口故障 |