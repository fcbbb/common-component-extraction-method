# DSH Agent Runtime 迁移实施方案

## 1. 目标

本方案将仓库中的多轮软件工程 Agent 从 `mini-swe-agent` 迁移到
DeepSeek Harness（下文简称 DSH），同时保持共性组件方法的实验边界、Docker
隔离、文件提交协议、补丁校验、缓存身份和结果审计能力。

迁移后，Python 流水线继续负责阶段编排、Docker 容器生命周期、输入输出校验和
实验制品；DSH 负责模型调用、Agent 循环、工具调用和会话恢复。模型生成的命令仍
只能在指定的离线任务容器内执行，不能获得宿主机 shell、Docker socket、模型
凭证或额外网络能力。

本方案不修改已经发布的 20 任务历史结果。使用 DSH 得到的结果必须进入新的运行
目录和报告，不能覆盖 `results/` 与 `docs/final_report_20_tasks.md` 中的
mini-swe-agent 实验记录。

### 1.1 固定版本基线

首轮实现固定使用以下版本，不使用 `latest`、`next`、`^`、`~` 或 `npx` 的隐式
版本解析：

```text
@deepseek-ai/dsh = 0.2.2-rc.1
Node.js = 24.9.0
```

`dsh/package.json` 必须写入精确版本，`dsh/package-lock.json` 必须提交。运行身份同时
记录 DSH 版本、Node 版本和 lockfile SHA-256。升级 DSH 必须作为独立变更执行完整
Agent runtime 验收，不能在普通流水线改动中自动升级。

如果 `0.2.2-rc.1` 在 headless JSON、session resume 或自定义 shell provider 的
POC 中出现阻塞性问题，允许在独立兼容分支回退到 `0.2.1-rc.5` 做对照；是否回退
必须形成明确记录，不能在运行脚本中动态选择版本。

### 1.2 实施进度（2026-11-07）

- 阶段 0、1 已完成：公共 request/result/status 和批处理后端身份已经落地。
- 阶段 2 已完成 POC：固定 Node/DSH lockfile、最小 headless profile、
  `controlled_bash`、严格 JSONL 解析、运行身份、文件 checker 和 session resume
  均已实现。真实 DSH 进程由本地假 OpenAI-compatible 流式服务驱动，在
  `network=none`、只读根文件系统容器中完成两轮工具调用、文件提交和同 session
  恢复；该验收未产生外部模型费用。
- 阶段 3 已完成代码接线：`ComponentAgentRunner` 固定使用 DSH，保留原有容器、
  只读挂载和文件提交校验。仍需使用生产模型跑一个真实
  抽取和审核样本，确认提示词质量与服务端 compatibility 参数。
- 阶段 4 已完成代码接线和 fixture 验证：retrieval 使用统一 DSH backend，保留
  完整 catalog、只读组件库、任务仓库遮蔽、显式总超时和步骤上限，并由受控
  checker 对 `coverage.json` 与 `selection.json` 做二次机械校验。Python 单测、
  TypeScript 检查和本地 Docker fixture 均通过；按运行限制尚未执行真实 retrieval
  任务，生产模型单样本验收仍待完成。
- 阶段 5 已完成代码接线和 fixture 验证：最终 task Agent 固定使用 DSH，Python
  继续负责官方容器生命周期、`/testbed`
  初始化和实际离线网络证明；完成信号使用 `patch` transport，容器内临时 Git
  index 与主机侧全新官方镜像分别执行 clean-baseline apply check，最终 patch 只
  来自真实 worktree。结果记录会话、token、网络证明、DSH runtime identity 和
  `component_usage`。Python 全量测试、TypeScript/Node 测试、本地假模型 DSH
  集成和 Docker checker fixture 均通过；按运行限制没有执行真实 task，direct 与
  components 的生产模型单任务验收仍待完成。
- 阶段 6 已完成代码接线和 fixture 验证：新增框架无关 `ModelClient`，leakage
  auditor 不再通过 MiniSWE 模型包装器发起单次请求。客户端固定 OpenAI-compatible
  路由、显式超时、零隐式传输重试和最多两次 JSON 结构修复，严格校验
  `decision/reasons`，并记录每次响应的内容哈希、token、结束原因和非敏感 runtime
  identity；客户端源码也已加入冻结输入哈希。全量 Python 测试通过，按运行限制
  没有调用真实 API。
- 阶段 7 已完成代码清理和 fixture 验证：默认且唯一后端为 `dsh`，旧 Agent backend、
  action adapter、专用 environment/completion 适配器及 Python 依赖已经删除；
  preflight、batch identity、README 和第三方说明已经同步更新。静态扫描不再在
  `src`、`tests`、`pyproject.toml` 或 `requirements.txt` 中发现旧后端依赖。
  公共路径通过 backend registry/factory 创建实现，当前只注册 `dsh`，未来新增实现
  不需要修改组件、检索、任务、preflight 或 batch identity。随后使用配置的真实
  OpenAI-compatible endpoint 完成一次受控 runtime smoke：一个 DSH session、两次
  模型调用和两次 `controlled_bash`，从只读工作区复制 sentinel 到独立输出目录，
  checker 验证通过并得到 `Submitted`；记录 2179 input tokens、1424 output tokens，
  服务未返回成本。该 smoke 不含正式任务数据，未执行抽取、检索或 SWE 任务。
- 阶段 8 已完成一轮真实独立阶段采样，尚未通过正式实验验收。按每个 Agent
  阶段一个 session、失败不重启的限制，对真实冻结输入运行抽取、审核、修复、
  检索和 direct/components；六个 session 均在 480 秒上限触发 `Timeout`。
  发布和基线评测、报告链路已验证；详情见下文阶段 8 的采样记录。所有输出位于
  `work/dsh-stage8-samples-20261107/`，没有覆盖历史结果。

## 2. 当前耦合范围

当前代码不是仅通过一个 CLI 使用 mini-swe-agent，耦合分为五类。

| 耦合类型 | 当前位置 | 迁移要求 |
| --- | --- | --- |
| Agent 循环和模型对象 | `component_build/extraction/runner.py`、`retrieval/service.py`、`task_execution/core/task.py` | 改为统一 DSH 后端 |
| 命令执行环境 | `task_execution/runtime_support/docker_environment.py` | 改为 DSH Docker shell provider |
| 完成和错误控制流 | `completion.py`、`component_agent.py`、`task.py` | 不再依赖 `Submitted`、`FormatError` 异常 |
| DeepSeek action 解析 | `task_execution/adapters/action_protocol.py` | DSH 原生工具调用稳定后删除 |
| trajectory、恢复和统计 | `build_helpers.py`、`cache/review.py`、各阶段 runner | 增加 DSH JSONL 事件适配层 |

此外，`task_execution/core/components.py` 中的泄漏审核使用
`minisweagent.models.get_model` 执行单次模型请求。该调用不是 Agent 循环，应迁移到
独立的 `ModelClient`，避免为了单次 JSON 判断启动 DSH session。

## 3. 不可破坏的约束

1. 任务命令只在指定 Docker 容器内运行。
2. 组件抽取和审核工作区保持只读，只有 `/component-output` 可写。
3. 最终任务容器保持 `network=none`，不注入模型 API key。
4. DSH 进程不能向模型暴露宿主机文件系统、用户配置或其他运行目录。
5. 组件阶段必须通过文件提交 checker 后才能成功。
6. 最终任务必须从真实仓库 diff 抓取补丁，并通过干净基线
   `git apply --check`。
7. direct 和 components 两臂必须使用相同 DSH 版本、模型路由、基础 profile、
   请求参数和资源限制。
8. task-blind 阶段不能获得任务说明、目标测试或标准补丁。
9. 所有运行必须记录模型、容器镜像、profile 哈希、插件哈希、session ID、
   工具事件和完成原因。

## 4. 目标架构

```text
Python workflow
  |
  +-- AgentBackend.run(AgentRunRequest)
        |
        +-- DshHeadlessBackend
              |
              +-- dsh --mode json --profile component-method
                    |
                    +-- controlled-bash tool
                    |     |
                    |     +-- Docker Engine API -> selected container
                    |
                    +-- completion-guard plugin
                          |
                          +-- file checker / patch submission state

Python controller
  +-- validates normalized events
  +-- validates submitted files or patch
  +-- writes existing result/status contracts
  +-- removes Docker container
```

DSH 运行在宿主机受控子进程中，以便访问模型接口。模型工具不能使用 DSH 默认的
宿主机 shell 和 filesystem provider，只注册本项目提供的受控 bash 工具。受控
bash 工具通过 Docker Engine API 对单个、预先创建的容器执行命令。

## 5. 建议目录结构

```text
repository/
  dsh/
    package.json
    package-lock.json
    tsconfig.json
    profiles/component-method/
      package.json
      cordis.patch.yaml
    plugins/controlled-bash/src/index.ts
    plugins/completion-guard/src/index.ts
    plugins/run-audit/src/index.ts
  src/component_method/agent_runtime/
    __init__.py
    contracts.py
    backend.py
    dsh_headless.py
    events.py
    model_client.py
    status.py
  tests/agent_runtime/
    test_dsh_events.py
    test_dsh_backend.py
    test_completion_contract.py
    test_runtime_identity.py
```

`dsh/` 保存固定版本的 Node 依赖、profile 和插件源码；`agent_runtime/` 保存
Python 控制器和稳定的数据契约。业务阶段不直接解析 DSH JSONL，也不直接拼接
DSH CLI 参数。

## 6. Python 后端契约

### 6.1 请求

```python
@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    role: str
    model: str
    system_prompt: str
    task_prompt: str
    output_dir: Path
    container_name: str
    container_cwd: str
    command_timeout_seconds: int
    total_timeout_seconds: int | None
    step_limit: int | None
    submission_mode: Literal["files", "patch", "none"]
    submission_role: str | None
    resume_session_id: str | None = None
```

请求中不传 Docker client、API key 明文或任意 shell 命令模板。模型凭证只通过 DSH
子进程环境提供；工具插件收到容器名和受控运行参数，但不会把 DSH 进程环境复制进
容器。

### 6.2 结果

```python
@dataclass(frozen=True)
class AgentRunResult:
    status: str
    session_id: str | None
    final_output: str
    messages: list[dict]
    tool_calls: list[dict]
    model_calls: int
    input_tokens: int | None
    output_tokens: int | None
    reported_cost_usd: float | None
    completion_validated: bool
    error: str | None
```

业务阶段只依赖该结构。DSH event 名称、内部 session 格式和插件事件格式由
`events.py` 统一转换。

### 6.3 状态映射

| DSH/控制器状态 | 项目状态 |
| --- | --- |
| checker 或 patch 校验成功 | `Submitted` |
| 达到步骤限制 | `LimitsExceeded` |
| 达到总运行时间 | `Timeout` |
| 用户中断 | `StoppedByUser` |
| DSH 进程非零退出 | `AgentProcessError` |
| 容器不存在或停止 | `TaskEnvironmentLost` |
| session 无法恢复 | `ResumeError` |
| Agent 正常结束但未提交 | `NoValidatedSubmission` |

保留 `Submitted` 字符串是为了兼容现有结果消费者，不再使用 mini-swe-agent 的
`Submitted` 异常实现控制流。

## 7. DSH 插件设计

### 7.1 `controlled-bash`

插件只提供一个 bash 工具，输入为：

```json
{
  "command": "...",
  "cwd": "/testbed",
  "timeout_seconds": 120
}
```

执行规则：

1. 容器名必须等于控制器通过 `COMPONENT_DSH_CONTAINER_NAME` 指定的名称。
2. `cwd` 必须位于允许的容器路径中。
3. 使用 Docker Engine API 的 exec 接口，不调用宿主机 `/bin/bash -c`。
4. 命令以 uid/gid `10001:10001` 运行。
5. 容器环境仅包含白名单变量；禁止继承 API key、代理、token 和 DSH 配置。
6. 每次命令使用独立超时和输出上限。
7. 原始命令、cwd、退出码、耗时和输出摘要写入审计事件。
8. 容器消失后立即终止 session，不让 Agent 继续重试未知环境。

首个版本不注册 DSH 的本地 read/write/edit/search/shell/web/subagent 工具。代码阅读、
搜索和修改全部通过容器内 bash 完成，以保持与现有实验的单工具交互边界一致。

### 7.2 `completion-guard`

插件检查 bash 输出第一条有效行是否为：

```text
COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

文件提交模式：

1. 在同一容器中运行对应 role 的 submission checker。
2. checker 失败时将错误作为工具结果返回，Agent 继续修复。
3. checker 成功时写入宿主输出目录中的 `validated_submission.json`。
4. 请求 DSH 停止当前 turn，并将完成原因记录为 `validated_files`。

补丁提交模式：

1. 插件只记录 Agent 已请求完成，不自行信任补丁文本。
2. Python 控制器从实际 Git worktree 抓取二进制安全 diff。
3. Python 控制器在干净任务镜像执行 `git apply --check`。
4. 校验成功后写入 `submitted.patch` 和 `patch_capture.json`。

### 7.3 `run-audit`

至少记录：

- DSH 版本和 profile 名称；
- profile、插件、prompt 和 model route 的 SHA-256；
- session ID、父 session ID 和 resume 次数；
- 每次模型完成事件的 token usage；
- 每次工具调用的规范化参数和结果；
- 最终停止原因。

## 8. Prompt 和配置迁移

角色语义提示继续使用现有的 extraction、review、repair、proposal、
proposal_review、retrieval 和 task 提示词。

需要删除或替换的 mini-swe-agent 专用要求：

- “exactly one Bash code block”；
- `action_observation_template`；
- `format_error_template`；
- mini-swe-agent 默认 system prompt 拼接；
- `mode: yolo` 和 `confirm_exit`；
- 依赖 Markdown bash block 的 action parser。

新的 DSH profile 必须明确：

1. 只允许 `controlled-bash` 工具。
2. 不启用 web search、URL fetch、浏览器、delegation 和宿主 filesystem。
3. 禁止交互式权限询问，所有允许动作已经由工具边界机械限制。
4. 组件阶段保持只读源码和文件提交协议。
5. 任务阶段保持只修改非测试源码的现有要求。
6. direct/components 两臂只允许组件提示和只读组件挂载不同。

模型路由由受控配置生成器创建，不读取用户全局 DSH profile。路由至少固定：模型
ID、OpenAI-compatible base URL、API key 环境变量、请求超时、最大输出 token、重试
次数及已验证的 compatibility 参数。

## 9. 运行制品

每个 Agent 运行目录新增或保留：

```text
agent_task.txt
prompt_input/system.txt
prompt_input/user.txt
dsh_events.jsonl
dsh_session.json
trajectory.json
agent.log
agent_status.json
validated_submission.json       # 成功时
agent_result.json               # 文件型提交成功时
submitted.patch                 # patch 型提交成功时
patch_capture.json              # patch 型提交成功时
```

`dsh_events.jsonl` 是原始审计记录；`trajectory.json` 是项目统一格式。统一 trajectory
至少包含 `messages`、`tool_calls`、`info.exit_status`、`info.model_stats` 和
`info.runtime_identity`，使现有报告和依赖分析可以逐步迁移。

`cache/review.py::observed_dependencies` 应优先读取规范化 `tool_calls`，不能依赖 DSH
私有事件结构。

## 10. 分阶段实施

### 阶段 0：冻结基线

- 记录当前 `pytest` 结果。
- 选择一个组件抽取任务和一个最终 SWE 任务作为迁移样本。
- 保存 mini-swe-agent 样本的 prompt、容器证明、状态文件和输出结构。
- 增加 `AGENT_BACKEND=mini_swe|dsh`，迁移期间默认仍为 `mini_swe`。

验收：现有流水线无行为变化，基线制品可用于字段级对照。

### 阶段 1：引入稳定后端接口

- 新建 `src/component_method/agent_runtime/`。
- 将公共 request/result/status 定义迁入该目录。
- 用 `MiniSweBackend` 包装现有实现，不改变执行结果。
- 业务阶段通过 backend 接口调用，不再直接 import mini-swe-agent。

验收：默认后端下现有单测和样本运行结果结构不变。

### 阶段 2：完成 DSH Docker shell POC

- 新建 `dsh/` Node workspace，固定 DSH 精确版本并提交 lockfile。
- 实现 `controlled-bash`、最小 profile 和 JSONL runner。
- Python `DshHeadlessBackend` 启动 DSH 子进程并解析事件。
- 跑通只读组件 workspace 中的多轮 `ls`、`rg`、`sed`。
- 证明 Agent 无法访问宿主 cwd、API key 和 Docker socket。

验收：DSH 能在 `network=none` 容器内连续执行命令，宿主机凭证不进入工具环境。

### 阶段 3：迁移组件抽取、审核和修复

- 将 `MiniSweComponentRunner` 重命名为框架无关的 `ComponentAgentRunner`。
- 保留现有 Docker 创建、只读挂载和 runtime probe。
- 将 `_agent_command`、trajectory resume 和 `_extract_submission` 替换为 backend。
- 实现文件完成 checker 和失败反馈。
- 将 agent config identity 改为 DSH 版本、profile、插件和 prompt 哈希。

验收：一个抽取样本和一个审核样本生成有效 `agent_result.json`；checker 拒绝场景能
在同一 session 中修复后再次提交。

### 阶段 4：迁移组件检索

- 保留现有组件库只读挂载、任务仓库遮蔽和 selection checker。
- 使用统一 backend 替换 `CheckedRetrievalAgent`。
- 将无限步骤语义改为显式总超时和可配置步骤上限，避免无界 session。
- 成功条件继续要求 `coverage.json`、`selection.json` 和机械校验全部通过。

验收：检索 Agent 无法读取任务仓库路径；有效选择可由 `validate_selection` 再次
独立验证。

### 阶段 5：迁移最终任务 Agent

- Python 继续创建官方任务镜像、初始化 `/testbed` 并执行网络证明。
- DSH 通过 `controlled-bash` 操作任务容器。
- 完成时从真实 worktree 抓取 diff，执行 clean-baseline apply check。
- 从规范化消息或显式提交元数据中收集 `component_usage`。
- direct/components 两臂共享同一 backend identity。

验收：direct 和 components 各完成一个任务；结果文件包含可应用 patch、容器证明、
模型统计和 DSH runtime identity。

### 阶段 6：迁移单次模型请求

- 新建 `ModelClient`，复用 OpenAI-compatible endpoint。
- 迁移 leakage review 等 `get_model().query()` 调用。
- 为 JSON 输出增加结构校验、重试上限和使用量记录。

验收：所有单次模型请求路径不再 import `minisweagent`，并能独立记录结构校验与
使用量；旧 Agent 回滚路径中的 MiniSWE import 在阶段 7 统一删除。

### 阶段 7：移除旧后端

- 默认切换为 `dsh`，完成稳定验证后删除 `MiniSweBackend`。
- 删除 `action_protocol.py`、mini 专用 environment 和 completion 异常适配。
- 从 Python 依赖、preflight 和 batch environment identity 中移除 mini-swe-agent。
- 更新 README、运行命令和第三方 notice。

验收：`rg -i 'miniswe|minisweagent|mini-swe-agent' src tests pyproject.toml requirements.txt`
只允许命中历史迁移说明，不命中生产代码。

### 阶段 8：重新运行实验

可复用的非 Agent 冻结阶段：source scan、signal analysis、protocol candidate
generation/freeze。

必须重新运行：component extraction、review/repair、library publish、retrieval、
direct/components task execution、evaluation 和 reporting。

新结果写入独立 run root。只有完整性校验和配对实验完成后，才新增 DSH 实验报告。

#### 2026-11-07 真实独立阶段采样

本次按照用户确认的“每阶段一个 Agent 会话，会话内允许多轮模型和工具交互，
失败不重新启动”执行，不是完整端到端实验。使用 `.env` 配置的 `GLM-5.3-Flash`
和 `elastic__curator-1085` 的真实冻结源码、候选、组件与本地官方镜像。
每会话设置 24 步、480 秒总上限、零传输重试，未拉取镜像或安装模型依赖。

| 阶段 | 会话数 | 完成的模型响应数 | 原始状态 |
| --- | ---: | ---: | --- |
| component extraction | 1 | 23 | Timeout，未提交 |
| review | 1 | 11 | Timeout，未提交 |
| repair | 1 | 16 | Timeout，已生成修复文件但完成校验被拒 |
| retrieval | 1 | 3 | Timeout，未提交 selection |
| direct task | 1 | 16 | Timeout，无补丁 |
| components task | 1 | 17 | Timeout，无补丁 |

轨迹共记录 91 次模型步骤开始、86 次模型响应完成；5 个未完成步骤的用量无法
完整统计。已记录 273204 input tokens、100240 output tokens，服务没有返回成本，
不将缺失成本记为零。原始轨迹和状态保留在独立 run root，未恢复或重跑任何真实
Agent 会话。

采样额外发现并修复了容器侧 checker 的 Python 3.7 兼容性问题：文件与引用路径
校验不再使用 `Path.is_relative_to()`，补丁 checker 的临时 index 清理不再使用
`unlink(missing_ok=True)`。修复 Agent 曾自行找到镜像内的 Python 3.12 并验证文件，
但控制器二次校验仍使用默认 Python 3.7，因此无法完成提交。这一问题通过真实
Python 3.7 官方镜像中的无模型测试复现，修复后文件和真实 worktree patch checker
均通过。已有修复文件也通过生产服务的字段范围、合同与源码校验，新增模型调用
为零；该事后验证不会将原 session 的 `Timeout` 改写为 `Submitted`。

非 Agent 阶段独立验证如下：

- 发布：将一个历史审核合格组件重新发布到新目录，明确记录历史审核输入身份。
  检索独立使用历史完整 32 组件库，components task 独立使用历史选中 bundle；
  这些历史输入不计作本轮 DSH 抽取或审核的成功产物。
- 评测：首次加载暴露了分发包缺少 `lib/agent/swe_constants.py`；补齐解析器所需
  的四种测试状态常量，保留官方 evaluator 和 parser 源码。由于两臂均没有产生
  补丁，仅运行一次无解题补丁的官方离线基线评测，F2P 为 0/18，P2P 为 243/243。
  这是评测链路验证，不是 DSH 解题成绩。
- 报告：生产 reporting 入口只接收独立样本记录，配对比较资格为零。详细样本
  报告写入 `sample_report.json` 和 `sample_report.md`，不新增正式 DSH 实验报告。

结论：真实阶段入口、模型路由和隔离链路已执行验证，修复与评测发现的问题已
完成无模型回归；在本次受限预算下仍没有完整有效的 Agent 提交，阶段 8 正式实验
验收保持未通过。

## 11. 逐文件改造清单

| 文件 | 动作 |
| --- | --- |
| `pyproject.toml`、`requirements.txt` | 迁移结束时移除 mini 依赖；Node 依赖由 `dsh/package-lock.json` 管理 |
| `component_build/extraction/runner.py` | 保留容器管理，Agent 启动和恢复改为 backend |
| `retrieval/service.py` | 删除内嵌 Agent 子类，改为 DSH 运行和 selection 完成回调 |
| `task_execution/core/task.py` | 删除 mini Agent/Environment，保留任务初始化、补丁抓取和评测输入 |
| `task_execution/runtime_support/docker_environment.py` | 功能迁移到 DSH controlled-bash 插件后删除 |
| `task_execution/runtime_support/completion.py` | 改为框架无关完成状态或删除 |
| `task_execution/adapters/component_agent.py` | 由 `DshHeadlessBackend` 取代 |
| `task_execution/adapters/action_protocol.py` | DSH 原生工具调用验证稳定后删除 |
| `task_execution/core/components.py` | 单次调用改用 `ModelClient` |
| `component_build/cache/review.py` | 从规范化 tool calls 统计依赖 |
| `workflow/run_batch.py` | 环境身份增加 DSH/Node/profile/plugin 哈希 |
| `tools/preflight.py` | 检查 Node、DSH bundle、profile 和插件构建产物 |
| `README.md` | 更新安装、运行、恢复和审计说明 |

## 12. 测试矩阵

单元测试：

- DSH JSONL 事件解析和未知事件 fail-closed。
- session ID 提取、resume 命令构建和 cwd 校验。
- DSH 状态到项目状态映射。
- tool call 到统一 trajectory 的转换。
- token/cost 缺失时使用 `null`，不能伪造为零成本。
- config identity 对 DSH 版本、prompt、profile 和插件变化敏感。

插件和集成测试：

- 只能连接指定容器，cwd 越界被拒绝。
- 命令超时后进程组被终止。
- 输出截断保留头尾并记录原始字节数。
- API key、代理和 DSH_HOME 不进入容器。
- checker 失败返回可修复错误，成功写入验证记录。
- 容器被删除后返回 `TaskEnvironmentLost`。
- 只读组件工作区不能修改源码。
- retrieval 看不到任务仓库路径。
- task 容器通过实际 outbound connection probe。
- patch 只能来自实际 Git diff，不能来自 final answer 文本。
- direct/components 的 runtime identity 除组件 prompt 和 mount 外一致。

端到端至少覆盖：

1. 一个小型组件抽取和审核任务；
2. 一个检索结果非空的任务；
3. 一个 direct/components 都能完成补丁提交的 SWE 任务；
4. 一个 checker 首次拒绝、Agent 修复后成功的故障注入任务；
5. 一个中断后使用 session ID 恢复的任务。

## 13. 运行身份与缓存失效

新的 Agent identity 至少包含：

```json
{
  "backend": "dsh",
  "dsh_version": "0.2.2-rc.1",
  "node_version": "24.9.0",
  "profile_sha256": "...",
  "plugin_bundle_sha256": "...",
  "system_prompt_sha256": "...",
  "task_prompt_sha256": "...",
  "model_route_sha256": "...",
  "container_policy_sha256": "..."
}
```

任何字段变化都必须使抽取、审核或任务缓存失效。旧 mini-swe-agent identity 不得与
DSH identity 等价，也不能自动复用未完成 trajectory。

## 14. 回滚方案

阶段 7 后不再提供运行时后端回滚开关；`AGENT_BACKEND` 省略时默认为 `dsh`，显式
设置时也只接受 `dsh`。如需回滚，必须恢复阶段 7 之前的代码和依赖，并使用新的输出
目录；不能把 DSH 输出改写为旧 trajectory，也不能混用不同 backend 的 session、
成本统计或缓存。

删除旧后端前需要满足：

1. DSH 完成组件抽取、审核、检索和任务执行四类端到端样本。
2. 全部安全边界测试通过。
3. 连续两轮样本运行没有不可恢复的 session 或容器泄漏。
4. 新运行制品能被 reporting 和完整性校验消费。

## 15. 实施批次和预估

| 批次 | 内容 | 预估 |
| --- | --- | ---: |
| A | 基线冻结、Backend 契约、MiniSweBackend 包装 | 1–2 人日 |
| B | DSH workspace、controlled-bash、JSONL parser | 2–3 人日 |
| C | 组件抽取/审核/修复迁移 | 2–3 人日 |
| D | retrieval 和最终 task 迁移 | 2–3 人日 |
| E | 单次模型调用、依赖清理、文档和全套测试 | 1–2 人日 |

完整工程迁移预计 8–13 人日，不包含 20 任务模型运行时间和 API 成本。首个可验证
POC 应在批次 B 结束时产生，范围限定为一个只读组件工作区、多轮命令、文件提交
校验和 session resume。

## 16. 完成定义

- 生产代码不再依赖 mini-swe-agent。
- 所有 Agent shell 动作都经过 DSH controlled-bash 并进入指定容器。
- 文件提交和 patch 提交均通过独立机械校验。
- DSH session 可以恢复，失败状态可审计且不会静默重跑。
- direct/components 两臂保持除组件输入外的运行等价性。
- 旧 20 任务结果保持不变，新 DSH 结果使用独立报告和清单。
- 单元、集成和选定端到端测试全部通过。
