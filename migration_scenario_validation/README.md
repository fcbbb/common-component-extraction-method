# 迁移场景验证：三个代码迁移 benchmark

本目录用同一套方法论构造并验证三个迁移场景：

1. **Intel IPP → VSIPL / VSIPL++**（电子通信 / 信号处理 C++）——`v1/ipp_vsipl_tasks/`
2. **Windows/MSVC C++ → 麒麟 V10 + GCC/CMake**——`v1/windows_to_kylin/`
3. **NVIDIA CUDA → 摩尔线程 MUSA**——`v1/cuda_to_musa/`（原 `cuda_to_ascend/` 已归档）

## 目录布局

V1 的任务包统一归在 [`v1/`](v1/)：三套场景（`ipp_vsipl_tasks/`、`windows_to_kylin/`、`cuda_to_musa/`）加 `archive/` 归档。
`docs/` 存放设计与方法文档，[`shared/`](shared/)、[`tools/`](tools/)、[`env/`](env/) 和根目录入口脚本是共享判分链路，不随任务版本移动。
V2（库优先的任务族）设计见 [docs/task_design_v2.md](docs/task_design_v2.md)。V2 的 6 个任务包已并入 V3，`v2/windows_to_kylin/` 仅保留设计、slate 与冻结库作为历史记录。
V3 的当前状态、证据位置、复跑命令与未完成项见 [docs/current_state.md](docs/current_state.md)。
V3 把 Windows → 麒麟的全部任务包收敛到 [v3/windows_to_kylin/tasks/](v3/windows_to_kylin/tasks/)：仓库级切分（建库来源 libuv/libarchive、pilot libgit2、held-out POCO/nginx/curl/opencv）见 [SPLIT.md](v3/windows_to_kylin/SPLIT.md)，机器可读清单见 [slate.yaml](v3/windows_to_kylin/slate.yaml)，方法论组件库见 [v3/windows_to_kylin/library/](v3/windows_to_kylin/library/)。

## 目标

构建代码迁移 benchmark：

> 给 agent 一个源仓库（或其中一部分）和迁移要求，看它能否产出可编译、行为等价、通过隐藏测试的目标实现；用同一批任务配对比较“先做组件抽取再迁移”与“直接让 agent 迁移”。

公开数据集、性能基准套件、厂商样例提供**题目素材**和**判卷环境**。

## 入口

| 场景 | 设计 | 题目 slate | 任务包 | 题数 |
|---|---|---|---|---|
| IPP → VSIPL | [migration_benchmark_design.md](docs/migration_benchmark_design.md) | [ipp_to_vsipl_task_slate.md](docs/ipp_to_vsipl_task_slate.md) | [v1/ipp_vsipl_tasks/](v1/ipp_vsipl_tasks/) | 20 |
| Windows → 麒麟（V1 历史） | [v1/windows_to_kylin/design.md](v1/windows_to_kylin/design.md) | [v1/windows_to_kylin/task_slate.md](v1/windows_to_kylin/task_slate.md) | [v1/windows_to_kylin/tasks/](v1/windows_to_kylin/tasks/) | 13 |
| Windows → 麒麟（V3 当前） | [v3/windows_to_kylin/SPLIT.md](v3/windows_to_kylin/SPLIT.md) | [v3/windows_to_kylin/slate.yaml](v3/windows_to_kylin/slate.yaml) | [v3/windows_to_kylin/tasks/](v3/windows_to_kylin/tasks/) | 19 可运行 + 6 规划（slate 25） |
| CUDA → MUSA | [v1/cuda_to_musa/design.md](v1/cuda_to_musa/design.md) | [v1/cuda_to_musa/task_slate.md](v1/cuda_to_musa/task_slate.md) | [v1/cuda_to_musa/tasks/](v1/cuda_to_musa/tasks/) | 20 |

每个场景另有 `slate.yaml`（可再生成）和 `provenance.csv`（仓库/commit/license）。环境定义在 [env/](env/)，共享基础设施在 [shared/](shared/)。

**执行顺序、正控/负控命令和记录模板见 [RUNBOOK.md](RUNBOOK.md)。**

## 统一入口（三臂）

三个条件各有一条一键入口，共享同一份配置 [bench.yaml](bench.yaml)、同一套任务包和同一个判分器：

| 入口 | 条件 | DSH profile | 会话 |
|---|---|---|---|
| `./run-default.sh` | A：直接迁移（默认 DSH） | `component-method` | 1 |
| `./run-method.sh` | B：组件方法 DSH | `component-method-migration`（单主 agent，仅方法工具） | 1 |
| `./run-origin.sh` | Origin：单次上下文直调大模型 | 无 DSH | 无 |

`run-origin.sh` 不是 Agent：它把任务 spec、文件树和预算内的源码打包成一个 prompt，
只调用一次 `/chat/completions`，把返回的文件写入 workspace，然后交给同一个 judge。
它用于和 DSH 基线/组件方法区分“模型单次生成能力”与“Agent 环境闭环能力”。

B 臂由同一个主 agent 先在工作区里完成组件扫描、抽取、发布、检索和物化
（`/workspace/component_bundle/`），然后**在同一会话里**完成迁移。主 agent 默认
没有步数上限（组件开销不计入任务预算），只有墙钟安全超时；设置
`budgets.method_step_limit` 可做同预算对照。判分对象就是它的工作区。
任务提示、镜像和判分命令与 A 臂相同。

```bash
./bootstrap.sh                            # 一次性预检（--fix 可代跑 npm ci/build）
python3 tools/bench.py doctor             # 环境/DSH/插件/镜像/凭据自检
./run-default.sh                          # 默认 smoke：每场景 1 题
./run-method.sh                           # 方法臂 smoke
./run-default.sh --all --runs 3 --label default_v1
./run-method.sh  --all --runs 3 --label method_v1
./run-origin.sh  --scenario ipp_to_vsipl --only l1_aubio_dct \
  --model DeepSeek-V4.1-Flash-1017 --label origin_smoke
python3 tools/bench.py compare --default-label default_v1 --method-label method_v1
```

`bench.py` 另有 `verify`、`env`、`gold`、`report` 子命令。各臂的差异、预算口径、一致性保证和后续工作项见 [docs/unified_entry.md](docs/unified_entry.md)；接收者需要自备的镜像、Node、网络、凭据和磁盘条件见 [REQUIREMENTS.md](REQUIREMENTS.md)。

## 三类东西的关系

| 东西 | 是什么 | 在 benchmark 中的角色 |
|---|---|---|
| 源仓库（IPP 项目 / Windows 模块 / CUDA kernel） | 待迁移代码 | **题目** |
| 目标运行时（VSIPL 实现 / 麒麟 + GCC / MUSA SDK） | 编译运行环境 | **考场** |
| 隐藏测试 + 参考解 + golden 输出 | 判分依据 | **判卷标准** |
| 公开数据集 / 基准套件（RadioML、HeCBench、Rodinia 等） | 输入样本或性能基线 | **题目素材** |

```text
benchmark      = 考试题库
源仓库          = 题目正文
公开数据/套件    = 题目里引用的素材
目标运行时       = 考场
隐藏测试/参考解   = 判卷标准
```

## 三个场景的差异

| 维度 | IPP → VSIPL | Windows → 麒麟 | CUDA → MUSA |
|---|---|---|---|
| 源 | Intel IPP C/C++ | 仅 Windows 可编译的平台层 | CUDA model / PyTorch 算子契约 |
| 目标 | 单一标准（VSIPL/VSIPL++） | 麒麟 V10 SP3 + GCC 13/CMake | MUSA C + MUSA SDK 5.2（MTT S4000） |
| 主要难点 | API 映射、数值约定、覆盖缺口 | Win32 → POSIX、构建系统、GUI/TLS 后端 | CUDA API → MUSA API、`torch.cuda` → `torch.musa`、构建路径 |
| 判分硬件 | CPU | 麒麟 x86_64 | 摩尔线程 MTT S4000 |
| gold | 源侧固定输入输出 | 上游同一 commit 的 POSIX 实现 | 上游 MUSA 样例（2 题）+ 项目自写正控（18 题）；20 题真机已验证（原 18 题 + 2026-11-16 替换的 2 题） |
| 判分入口 | 任务自带 `run_hidden.py` | 上游测试二进制 + API 门 | 上游 evaluator + API 门 + kernel 结构门 |

## 共用设计原则

1. **任务 = 代码迁移**：判分看编译、数值等价、API 清除、隐藏测试。
2. **golden 来自源程序或上游参考**：不从 agent 的迁移结果反推“正确答案”。
3. **隐藏测试与参考解**：agent 只能看规格、公开测试和上游参考实现；目标实现放 evaluator-only 的 `gold/`。
4. **跨仓库重复模式**：组件抽取只在多个仓库共享相似结构时才有价值。
5. **配对实验**：同任务、同模型、同任务提示和判分；A 直接迁移，B 由同一个主 agent 先从当次可见工作区抽取组件并物化 bundle，再在同一会话里迁移。B 的主 agent 默认不设步数上限，组件开销不挤占任务预算；`method_step_limit` 可显式启用同预算对照。
6. **抽取可见性**：主 agent 只能看它本来就可见的工作区（不含 `gold/`、隐藏测试和 evaluator）；抽取包由 `source_scan` 机械划分，不读取题面或判分信息。这样 B 的组件构建成本可归因到同一任务，同时不泄漏答案。
7. **没有跑过的 gate 不写成 pass**：目标环境缺失时报告 `skipped`/`not run`。

## 已知限制：题目规模

当前 slate 为**组件级**迁移 benchmark。IPP 20 题每题可见源码是一个 `.c` + 一个 `.h`（`src/` 36–932 行）；Kylin 的 `work/` 是完整上游仓库（如 poco 4747 个文件 / 71 MB），但范围内改动通常只有 1 个文件，多文件 diff 只出现在 L3（`l3_poco_foundation_full` 17 个文件、`l3_nginx_full` 整个 `src/os/unix`）；MUSA 提交物是单个 Python 文件。

成因（IPP 闭源无官方样例、开源仓库里 IPP 只是可选后端、设计上 L3 只定义到 500–3000 LOC）、对外部效度的影响、补题方案，以及需要向客户确认的问题清单，见 [docs/task_scale_limitations.md](docs/task_scale_limitations.md)。

**对外结论需限定范围**：当前题目可支撑“组件抽取对重复 API 契约有帮助”，不足以单独支撑“能预测真实大仓库上的迁移效果”。

## 任务包约定

场景 A/B 的每个任务包只记录来源（repo / commit / 可见文件）和准备步骤，上游源码由 `prepare.sh` 在任务物化时拉取。IPP 场景是例外：
它的 20 个任务把源快照 vendored 在包内（`source.vendored: true`），
`prepare.sh` 只做本地复制，不联网：

```text
<scenario>/tasks/<task_id>/
├── task.yaml        # 题目、构建、隐藏测试、门禁
├── provenance.json  # repo / commit / license / 可见文件 / gold 文件
├── prepare.sh       # 克隆固定 commit → work/，隔离 gold
├── gold/            # evaluator-only（物化后生成）
├── harness/         # run_task.py / check_api_removal.sh / check_result.py
└── README.md
```

占位符 `{root}`、`{work}`、`{build}`、`{golden}` 由 `shared/harness/taskmodel.py` 展开，统一 runner 是 `shared/harness/runner.py`。

IPP 包的 `src/` 是 Intel IPP 原始实现，`gold/` 是 VSIPL 参考迁移；
`prepare.sh` 把 `src/ include/ test/ CMakeLists.txt` 复制进 `work/`，
gold 永远不会进入 agent 可见树。

## 快速开始

```bash
# 一次性环境预检（可加 --fix 执行 npm ci && npm run build，--build-images 构建镜像）
./bootstrap.sh

# 环境自检 + 静态校验全部 72 个任务包（不需要编译器 / GPU）
python3 tools/bench.py doctor
python3 tools/bench.py verify
# 等价于直接调用：
#   python3 tools/verify_task.py --parent v1/ipp_vsipl_tasks \
#     --parent v1/windows_to_kylin/tasks --parent v1/cuda_to_musa/tasks \
#     --parent v3/windows_to_kylin/tasks

# 物化一个任务（下载并固定上游 commit）
bash v1/windows_to_kylin/tasks/l1_poco_thread/prepare.sh

# 在目标环境跑构建 + 隐藏测试 + API 门
python3 shared/harness/runner.py \
  --task-root v1/windows_to_kylin/tasks/l1_poco_thread \
  --build-dir /tmp/build_l1_poco_thread
```

场景 B（MUSA）需要真实 MTT S4000，先用 [env/README.md](env/README.md) 里的镜像说明配置 MUSA SDK 5.2.0 + `torch_musa`；也可以经 `shared/harness/run_remote.py` 在远端 MUSA 主机执行。原昇腾场景已移到 [`v1/archive/cuda_to_ascend/`](v1/archive/cuda_to_ascend/)，不再计入当前三场景。

## 验证状态（如实）

- **已做（V3 收敛与建库，2026-11-22）**：Windows → 麒麟的任务包收敛到 `v3/windows_to_kylin/tasks/`，共 19 个可运行包（slate 25 项，6 项待打包）；仓库级切分见 `v3/windows_to_kylin/SPLIT.md`。建库链路 `tools/build_history_corpus.py` → `tools/extract_transformation.py` 产出 `v3/windows_to_kylin/library_generated/demo_new_flow_v4/`（1 个组件）。语料的 `after` 侧取上游既有目标实现（`gold/`），不取 agent 运行结果。
- **已做（V3 配对，2026-11-22）**：`v3_poco_fs_stack`（POCO Foundation 文件栈，L3）在麒麟 V10 SP3 镜像内完成配对：直接迁移 0/1（复制到自身失败），组件方法 1/1（隐藏检查 + 72 项公开测试 + 22 项回归 + API 门），gold 1/1。证据在 `reports/bench/v3_poco_fs_stack_validation_report.md` 与 `reports/bench/v3_poco_fs_stack_{method_r7,method_r8,default_r4,default_r5,gold_r1}/`。
- **已做**：72 个任务包（20 IPP + 13 V1 Kylin + 20 MUSA + 19 V3）静态校验通过；`tools/check_pins.py --offline` 通过（`ok=59`、`fail=0`，`judge_only=18` 为预期）；20 道 IPP 题在宿主机 GCC 13.3 + jvsip 上 gold 正控 20/20 通过（`reports/gold_sanity_ipp20/`）；Kylin V10 SP3 2403 镜像已拉取、检查并构建出带 GCC 13.3.1 的 `migration/kylin:sp3`；API 门正反例（含 `expect_fail` 负向对照）；`check_result.py` 的 clean/编译失败/数值错误/作弊四类输入单测。
- **已做（Kylin 侧）**：`migration/kylin:sp3` 内 gold 正控 19/19 通过（build + 隐藏测试 + API 门）：L1 5/5、L2 10/10、L3 4/4，结果在 `reports/gold_sanity/`。过程中修掉 7 类题目包缺陷（静态库产物名、测试工作目录、被 CMake 依赖选项关掉的测试、缺失的上游测试文件、API 门两条误杀规则），详见 RUNBOOK §3.2。
- **已做（负控）**：IPP 未迁移状态 `l1_vec_db_mag` 编译失败（`ipp.h` 缺失，rc=1）；Kylin 空实现 `l1_poco_thread`（缺 `Thread_POSIX.cpp`）与 `l2_libuv_thread`（缺 `src/unix/thread.c`）均 `build=fail`、runner rc=1，失败原因与缺失实现一致。
- **已做（P2 agent 小样本，麒麟两题）**：[tools/agent_trial.py](tools/agent_trial.py) 用 DSH（`@deepseek-ai/dsh` 0.2.2-rc.1 + `controlled-bash`）驱动 agent，再用 `shared/harness/runner.py` 判分，模型为 `deepseek-v4.1-flash-1017`。`l1_poco_thread` ×3、`l2_libuv_thread` ×3 共 6 次，**判分 6/6 通过**（build + 隐藏测试 + API 门），每题只改动目标实现文件，未碰测试/构建文件。证据在 `reports/agent_trial/p2_kylin/`。**限制**：`l1` 有 2 次是 150 步上限截断（`LimitsExceeded`），工作区判分通过但 agent 没有走完提交协议，属于“产物通过、未正常收尾”；MUSA 半场尚未开始（S4000 硬件已可用），所以 **P2 只完成了麒麟半场，不能写成 4 题×3 次通过**。
- **已做（基线链路，2026-11-16）**：新增 [tools/migration_trial.py](tools/migration_trial.py)（三场景 A/B 两臂统一编排器）、[tools/docker_api_shim.py](tools/docker_api_shim.py)（Docker API 子集 → SSH shell，MUSA 远端用）、[env/Dockerfile.ipp](env/Dockerfile.ipp)（IPP CPU 沙箱）。三场景各一题（`l2_rubberband_fft` / `l2_libuv_thread` / `b_l2_layer_norm`）的链路自检：IPP、Kylin 的 gold 播种判分 PASS（52.4s / 64.3s），未迁移负控均 FAIL（`build=fail`）；MUSA 远端链路已在租用 MTT S4000 上走通（`env/remote.yaml` 已配置但不提交，repo/workspace 双向同步 + shim over SSH + 远端 harness，gold 播种判分 **PASS**，59.0s，远端无 gold 泄漏）。**真实模型的基线尚未开跑**。详见 [docs/baseline_pipeline.md](docs/baseline_pipeline.md)。
- **已做（题目级负向题）**：`negative_win32_eventlog` 在 Kylin 容器内双向验证——正确的"不可移植说明"判 pass（build skipped、hidden test pass、`expect_fail` API 门 pass）；假移植（删掉 Windows API 的存根）被 API 门抓住，runner rc=1。证据在 `reports/negative_win32_eventlog/`。
- **已做（MUSA 静态侧）**：20 个 `cuda_to_musa` 包 `prepare.sh` 实际物化；每个 `work/` 中零个 `musa_new_model_*.py`；2 份有效上游 gold 位于各自 `gold/`，`layer_norm` 的上游样例因二维/四维契约不符移到 `upstream_nonconforming/`；2 份上游 gold 与 18 份项目自写正控（`gold_authored/`）全部通过 `check_musa_submission.py`（kernel 结构门）与 `api_removal.py`（CUDA API 清除门）；修复了 `api_removal.py` 在相对路径下崩溃的问题。
- **已做（MUSA 真机正控）**：在一台租用的 MTT S4000（Ubuntu 22.04.5、driver 5.2.0-server、`mcc` 5.2.0、torch 2.11.0.post1、torch_musa 2.11.0.post1+b431668）上经 SSH 运行，**18/20 题正控通过**：`musa_gold_final` 3/3（leaky_relu、mse_loss、layer_norm），`musa_batch1` 3/3（relu、sigmoid、swish），`musa_batch2` 2/7（softmax、cumsum 通过；其余为题包缺陷，修复后进入后续批次），`musa_batch3` 0/7（缺陷修复后重跑），`musa_batch4` 9/10（sum_reduce、argmax、gather、cross_entropy、standard_matmul、gqa、sdpa、matmul_gelu_softmax、kv_cached_attention 通过），`musa_batch5` 1/1（conv2d 关闭 muDNN 默认 TF32 后通过）。最终用一条命令合并重跑全部 18 题：`musa_all18` **`SUMMARY pass=18 fail=0 skip=0 error=0`、`GOLD_SANITY_RC=0`**（20.7 分钟），逐题 `tests=pass`、`api_removal=pass`、`MUSA_SUBMISSION=PASS`。每次 PASS 都经过 `mcc` 编译、5 次数值比对、反作弊、API 门和 kernel 结构门。加上 2026-11-16 的两道替换题（`musa_batch6` 2/2），当前 slate 的 **20/20 题全部真机验证通过**。证据在 `reports/gold_sanity/`。
- **MUSA 换题（2026-11-16）**：`b_l2_rms_norm`、`b_l3_group_norm` 的 8.59 GB fp32 张量无法在 47.90 GB 卡上完成判卷器的 `torch.allclose`（OOM；即使原地别名输入也在 44 GiB 时 OOM），已连同证据移入 [`v1/archive/cuda_to_musa_blocked_oom/`](v1/archive/cuda_to_musa_blocked_oom/)，**不计入通过数**。补位的是 `b_l2_cosine_similarity_loss`（1M 元素）与 `b_l3_conv2d_batch_norm_scaling`（输入 16.7M、输出 130M 元素），两者在 S4000 上实测通过：`musa_batch6` **`SUMMARY pass=2 fail=0 skip=0 error=0`**（cosine 79.1s、conv+BN 105.9s；`tests=pass`、`api_removal=pass`、`MUSA_SUBMISSION=PASS`、`worst_rel=0`），证据在 `reports/gold_sanity/musa_batch6/`。
- **已做（方法臂单主 agent，2026-11-17）**：`--arm method` 是一个 DSH 会话：主 agent（`component-method-migration`，只加载方法入口与作业工具；任务执行/报表插件不加载，迁移工作区下 kernel 也拒绝这两类阶段）按固定工作流在当前工作区完成 `prepare → build → audit → publish → retrieval`，产出 `/workspace/component_bundle/`，然后在同一会话里按任务提示完成迁移。组件审核与 20 题方法一致：`audit` 是后台作业，含一次返修与定向复审（`max_review_repair_rounds: 1`），只有审核通过的组件会发布进库。默认不设步数上限（`method_main_timeout` 只是墙钟安全上限）；设置 `budgets.method_step_limit` 后主 agent 与 A 臂使用同一预算，便于做同预算对照。只有将来额外启动任务执行子 agent 时才对那个子 agent 再单独施加预算。kernel 为阶段增加前置条件、任务级并发锁、`summary`/`artifacts` 回传和 `STAGE_INPUT_MISSING`/`BAD_REQUEST`/`STAGE_BUSY`/`STAGE_FAILED`/`JOB_MISSING` 错误码；抽取前会校验工作区的 `workspace_sha256`/`workspace_files` 与 `prepare` 冻结时一致，工作区被改动则直接失败。每次尝试还记录任务镜像的 `Id`/`RepoDigests`、远端 MUSA 运行时版本、固定提示词哈希和嵌套阶段（抽取/审核/检索）的实际模型调用/token/成本。MUSA `ssh` 传输下方法臂显式不支持。**真实模型的方法臂状态更新（2026-11-22）**：已在 `v3_poco_fs_stack` 上跑通，见本节 V3 条目。
- **接口收敛（2026-11-17）**：方法臂的阶段工具收成唯一入口 `component_run_stage`（用 `stage` 选块）；`build`/`audit`/`retrieval` 改为通过 DSH 内置 `ctx.jobs` 启动，profile 打开 `tool-jobs`，等待、完成通知和空闲唤醒都由内置运行时负责；自制的 `component_job_status`/`component_job_cancel` 已删除；同步与异步结果统一为 `status`/`summary`/`artifacts`/`error_code` 一张单，后台作业结束时同一张 JSON 单作为作业 `result`；迁移 profile 不再挂逐阶段和评审系列工具，工具表与工作区能力一致。
- **未做**：三场景两臂（A/B）的真实模型配对只完成了 Windows → 麒麟的一题（`v3_poco_fs_stack`）；IPP → VSIPL 与 CUDA → MUSA 的配对尚未开始；MUSA P2 agent 小样本（4 题 × 3 次）尚未开始；`env/Dockerfile.musa` 尚未实际构建；性能测量。
- 因此，IPP 场景正控 20/20 已实测；Kylin 场景正控 19/19、P1 负控 2 题、题目级负向题 1 题、P2 麒麟半场 6/6 判分通过；MUSA 场景 **20/20 正控已验证**（原 18 题 + 替换后的 2 题；原 2 题因判卷器 OOM 归档，不计入），P2 完整门槛（4 题 × 3 次）未达。没有跑过的 gate 不会写成 pass。原昇腾场景保留在 `v1/archive/cuda_to_ascend/`，不计入当前统计。

## 旧版调研文档

本轮任务包之前的调研与设计文档（IPP 数据调研、构建筛选、CUDA 数据调研与 benchmark
设计、两场景 v1 方案）属于过程材料，部分结论已被上述 `design.md` 和实际任务包取代，
不随仓库分发。