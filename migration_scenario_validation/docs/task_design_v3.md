# 任务设计 V3：迁移经验组件 × 共性组件的双层验证

- 日期：2026-11-20
- 状态：已实现并完成首轮配对验证（2026-11-22）；实现状态、证据与未完成项见
  [current_state.md](current_state.md)
- 文档定位：在 V2 的基础上，把“组件方法”拆成共性组件（anchor）与迁移经验组件（transformation）两层，并用“原始迁移记录 vs 整理后的组件”作为主对照，分离“额外信息”与“答案泄漏”
- 关联文档：[task_design_v2.md](task_design_v2.md)、[v2/windows_to_kylin/design.md](../v2/windows_to_kylin/design.md)、[migration_benchmark_design.md](migration_benchmark_design.md)、[task_scale_limitations.md](task_scale_limitations.md)、[ipp_to_vsipl_task_slate.md](ipp_to_vsipl_task_slate.md)、[unified_entry.md](unified_entry.md)

## 本稿的关键改动

1. 组件分两层：**共性组件（anchor）** 与 **迁移经验组件（transformation）**，两者 join 成 **迁移 playbook**；
2. 实验主对照从“有没有组件库”改为 **A1（原始迁移记录）vs B（整理后的组件）**，把“额外信息”与“答案泄漏”分开；
3. **三个场景并行**：`windows_to_kylin`、`cuda_to_musa`、`ipp_to_vsipl` 都是一等验证对象；POCO 只是 `windows_to_kylin` 的一个数据集，不是场景名，也不承担“边界/负对照”的特殊角色。

## 0. 一句话

V3 把组件方法拆成两层：**共性组件**回答“在哪里、要守住什么”，**迁移经验组件**回答“怎么变、有什么坑”；两者 join 成迁移 playbook。实验要证明的是：**整理过的迁移经验**是否比**原始迁移记录**更有用。三个场景（`windows_to_kylin`、`cuda_to_musa`、`ipp_to_vsipl`）并行验证，按场景/数据集分别报告。

## 1. 为什么需要 V3

### 1.1 V2 做了什么

- 在 POCO Foundation 数据集上完成源侧冻结库（`source_snapshot`）与 6 个任务；
- 建立 A / B / B0 / C 四条件入口与判分链路；
- 用 `evaluator_side` 把目标平台实现排除出抽取语料；
- 复用 V1 的判分器、镜像和 `prepare.sh` 机制。

### 1.2 V2 暴露的三个问题

1. **部分数据集与命题错配。** POCO 这个数据集的平台层是一对一移植：一个 `*_POSIX.cpp` 对应一个 Windows 孪生文件，迁移动作集中在单个文件，调用方几乎不改。这不代表整个 `windows_to_kylin` 场景——同一场景里还有 nginx、libgit2、curl 等多文件/构建系统任务。但它说明：**数据集选择**会直接决定组件方法有没有“多处一致”的杠杆。
2. **公平性三难。** 组件要给 B 信息优势；信息必须来自 A 也能看到的语料；目标实现不可见但构建要能跑。三者在“平台移植”语料上互相冲突。
3. **效果与泄漏难分离。** 库含 gold 就是答案；库不含 gold，B 与 A 的信息差又可能小到测不出。

### 1.3 关键判断

问题不是“多给信息”，而是“多给的信息正好是当前任务的答案”。来自**其他迁移**的经验不是当前任务的答案；只要时间、项目、文件切分干净，它就是合法的额外输入，不叫泄漏。

这也解释了 V2 在 POCO 数据集上的困境：源侧冻结库无论怎么排除 `*_POSIX.cpp`，抽取出来的“组件”仍然只是 Windows 实现的摘要，而 Windows 实现就在工作区里。B 的优势只能是“少读几个文件”，不足以形成可测差异。换到 nginx/libgit2/curl 等多文件数据集，或者换到 CUDA/IPP 场景，情况会不同——V3 要把这种差异作为实验变量，而不是把 POCO 当成整个 OS 迁移场景。

### 1.4 V3 的定位

- 仍是方法验证场景，不是排行榜；
- 主结论限定在设计场景内；
- V2 的资产不丢弃：源侧冻结库成为 anchor 层，6 个 POCO 任务作为 `windows_to_kylin` 的一个任务族保留，判分链路继续复用；
- V3 新增的不是“更多题”，而是**另一种信息来源**（历史迁移）和**一个公平的对照**（原始记录）。

## 2. 两层组件模型

### 2.1 定义

| | 共性组件（anchor） | 迁移经验组件（transformation） |
|---|---|---|
| 语料 | 当前源码、调用方、公共头、可见测试 | 过去的迁移结果（diff、commit、issue、测试） |
| 回答 | 什么是共性的、哪里必须一致 | 类似代码过去怎么迁、有什么坑 |
| 作用 | 定位、契约、调用点、一致性 | 目标映射、改编规则、错误语义 |
| 范围 | 当前代码库内部 | 跨项目/版本/批次 |
| 输出 | 稳定实现、协作协议、调用点清单、证据 | 源模式、目标模式、映射规则、语义差异、坑、适用边界、证据 |
| 风险 | 含 gold 就是答案 | 与当前任务同源就是泄漏 |

一句话：**anchor 回答“在哪里、要守住什么”，transformation 回答“怎么变”。** 迁移需要两者相乘。

### 2.2 为什么要两层

- **信息性质不同**：anchor 是结构性的（调用点、契约），transformation 是变换性的（映射、差异）。
- **复用方向不同**：一个 transformation 可以服务多个 anchor；一个 anchor 可以挂多个 transformation（多目标平台/多方案）。
- **评审标准不同**：anchor 审证据/覆盖/调用点完整性；transformation 审映射正确性/适用边界/泄漏风险。
- **可消融**：实验能区分“定位与一致性”和“目标知识”各自的贡献，而不是把两者混成一个“组件库有没有用”的黑盒结论。

### 2.3 组件 schema

anchor：

```yaml
id: thread-lifecycle
kind: anchor
capability: threading
contract:
  summary: 线程启动、加入、超时、优先级与 TLS 清理的外部行为
  invariants:
    - start() 后 isRunning() 为真，join() 后为假
    - join(timeout) 超时返回并可再次 join
    - 线程退出时 TLS 析构按注册逆序执行
positions:
  - Foundation/src/Thread.cpp
  - Foundation/src/ThreadPool.cpp
  - Foundation/src/Timer.cpp
  - Foundation/src/Activity.cpp
  - Foundation/src/ThreadLocal.cpp
evidence:
  - 公共头文件、调用方、可见测试
applicability: source-side; target-agnostic
```

transformation：

```yaml
id: pthread-thread-lifecycle
kind: transformation
capability: threading
source_pattern:
  platform: win32
  apis: [CreateThread, WaitForSingleObject, TlsAlloc, TlsSetValue]
target_pattern:
  platform: linux/posix
  apis: [pthread_create, pthread_join, pthread_timedjoin_np, pthread_key_create]
mapping_rules:
  - thread start -> pthread_create + trampoline
  - join with timeout -> pthread_timedjoin_np (fallback: condvar)
  - TLS -> pthread_key_create + destructor
semantic_deltas:
  - Win32 thread priority -> nice / sched_setscheduler (partial)
  - SEH -> signal handling (not equivalent)
pitfalls:
  - pthread_join on a detached thread is undefined
  - EAGAIN on thread creation under resource pressure
  - TLS destructor ordering and re-registration
applicability:
  os: linux
  libc: glibc >= 2.30
  constraints: no C++11 std::thread
evidence:
  - provenance: {project: <other-project>, commit: <sha>, date: 2025-xx-xx, split: dev}
confidence: high
leakage_class: cross-project
```

playbook（join）：

```yaml
id: playbook-thread-lifecycle-linux
anchor: thread-lifecycle
transformations: [pthread-thread-lifecycle]
task_families: [poco_foundation_thread, synthetic_dsp_thread_pool]
verification_points:
  - anchor.positions 全部编译并通过
  - 跨位置一致性：同一错误映射、同一 join 语义
expected_failure_modes:
  - 漏掉位置（例如 Timer 走了另一条 join 路径）
  - 超时处理不一致
adaptation_notes:
  - POCO 用 Poco::Event 唤醒；transformation 的 condvar fallback 需要按当前上下文改编
```

### 2.4 例子：thread lifecycle × pthread mapping（`windows_to_kylin` / POCO 数据集）

这是 POCO 数据集的一个例子，用来说明结构，不代表整个 `windows_to_kylin` 场景。

- **anchor**：`thread-lifecycle`——契约、状态机、5 个调用点（Thread/ThreadPool/Timer/Activity/TLS）、证据。
- **transformation**：`pthread-thread-lifecycle`——Win32 `CreateThread/WaitForSingleObject/TlsAlloc` → `pthread_create/join/timedjoin/key_create`，错误映射、栈大小、detach 策略、取消、TLS 析构顺序、坑。
- **playbook**：`thread-lifecycle × pthread-thread-lifecycle`——“在这 5 个位置应用这套映射，验证这些不变量，避开这些坑。”

这个结构的好处：

- 一个 transformation 可以服务多个 anchor；
- 一个 anchor 可以挂多个 transformation；
- 评审标准分开，问题定位清楚；
- agent 检索时先找 anchor，再找 transformation，最后组合。

### 2.5 与 V2 组件的关系

V2 的四要素（稳定实现、协作协议、调用点清单、证据）就是 anchor 的前身。V3 不替换它，只补上 transformation 和 join：

- V2 的组件库 → V3 的 `anchors/`；
- V2 的 `evaluator_side` 排除规则 → 继续适用于 `source_snapshot`；
- V2 的任务族 → V3 在 `windows_to_kylin` 下的一个任务族（POCO 数据集），继续保留；
- V3 新增 `history/`、`transformations/`、`playbooks/`。

## 3. 语料、切分与泄漏边界

### 3.1 两个快照

| 快照 | 内容 | 作用 |
|---|---|---|
| `source_snapshot` | 当前仓库的源侧生产代码、公共头、调用方、构建文件；排除目标平台实现、测试、任务包 | anchor 抽取 |
| `history_snapshot` | 过去的迁移记录：diff、commit、issue、测试、评审意见；带 provenance 和 split 标签 | transformation 抽取 |

`history_snapshot` 不是“当前任务的 gold 集合”，而是**其他迁移**的语料。它必须记录：

- `project`、`commit`、`date`、`source_task_id`；
- `split`：`dev` / `holdout`；
- `license`（使用开源迁移记录时）；
- `similarity_to_test`：与当前测试任务 gold 的相似度计算结果。

当前 `windows_to_kylin` 的实现里，`history_snapshot` 由 `tools/build_history_corpus.py` 从建库任务包生成：`before` 取该任务的 `work/`（源侧实现），`after` 取 `gold/`（上游项目自身已完成的目标平台实现，由 `prepare.sh` 从可见工作区移入评测侧）。因此抽取用的是**上游既有的迁移结果**，不是智能体在某次运行中产出的代码；agent 运行（default / method / origin）只用于评测，不作为建库输入。

### 3.2 切分规则

1. **时间切分**：库来自测试任务之前完成的迁移。
2. **项目切分**：库来自其他项目、其他版本或其他批次；测试任务是 held-out。
3. **文件/模块切分**：测试任务的 gold、隐藏测试、任务包不得进入任一快照。
4. **开发集/测试集**：没有跨项目记录时，用开发集跑迁移，成功 diff 入库；测试集完全 held-out，建库者不看测试集。

最干净的版本是**跨项目**：用项目 A 的 Windows→Linux 迁移记录建库，测项目 B 的任务。这样连“同源 sibling”的嫌疑都没有，额外信息是真正的可迁移经验。

### 3.3 泄漏审计

- **路径/哈希审计**：当前 gold 文件、隐藏测试、任务包不在库中；
- **相似度审计**：AST / token / embedding 相似度阈值；近邻重复排除；
- **改编审计**：隐藏测试包含“原样复制会失败、必须改编”的用例；
- **评审审计**：建库者不看测试集；建库协议与任务集 pre-register；
- **历史审计**：`history_snapshot` 的泄漏防护主要靠来源切分和相似度，而不是路径排除——因为历史项目与当前项目的路径不同，但代码可能近邻。

### 3.4 允许的额外信息

| 信息 | 是否允许 | 说明 |
|---|---|---|
| 当前任务源码、头文件、调用方、可见测试 | 允许 | A 也看得到 |
| 其他项目的迁移记录 | 允许 | A1 也看得到；B 的差异是“整理过” |
| 当前任务的 gold、隐藏测试、任务说明、评测命令 | 不允许 | 这是答案泄漏 |
| 当前任务同源 sibling 的 gold | 不允许（除非 A 也可见） | 否则 B 拿到的是近邻答案 |
| 模型自己生成的开发集迁移结果 | 允许 | 成本计入建库；测试集必须 held-out |

### 3.5 规模与质量

- `history_snapshot` 必须足够大，使“检索”本身有成本；否则 A1 直接读完全部记录，B 的索引/蒸馏没有价值；
- 记录样本量、项目数、迁移类型、覆盖的能力族；
- transformation 的 `confidence` 和 `applicability` 必须显式，不允许“看起来像”；
- 每个 transformation 至少有一个独立回放证据（在留出样例上编译/测试/静态检查）。

## 4. 任务族设计

### 4.1 任务成立条件

一个 V3 任务必须同时满足：

1. **多个迁移位置**（至少 3 个），同一约定或模式重复出现；
2. **约定是隐含的**：不在头文件里，而在多个调用方的共同假设里；
3. **不使用组件时有可测量的失败模式**：漏位置、约定不一致、目标 API 映射错误；
4. **目标映射不能从当前源码直接得到**：否则 A 也能推出来；
5. **隐藏测试覆盖全部位置** + 跨位置一致性 + 边界/错误语义；
6. **任务必须让旧 API 不可用或契约改变**，迫使 agent 改所有调用点；否则迁移动作又退回一个文件。

对 `windows_to_kylin` 的平台移植数据集，Windows 孪生文件可能已经给出大部分 API 映射；这类任务要把“多文件一致、构建系统、跨项目约定”作为主要变量，而不是指望 API 映射本身成为难点。

### 4.2 场景与数据集

| 场景 | 数据集/任务形态 | 迁移动作 | 组件杠杆 |
|---|---|---|---|
| `windows_to_kylin` | POCO（平台层一对一）、libuv/nginx/libgit2/curl（多文件、构建系统、调用点迁移） | 平台 API 替换、构建系统手术、多文件一致修改 | 数据集之间差异很大：POCO 测单文件契约；nginx/libgit2/curl 测定位、跨文件一致、构建 |
| `cuda_to_musa` | MultiKernelBench 多算子；每算子一个 kernel，族内共享模板 | kernel / launch / tiling 迁移 | 跨任务摊销；transformation 主导 |
| `ipp_to_vsipl` | 合成仓库族（wrapper + 8–12 模块 + 多调用点）；现有 20 题作为组件级补充 | API 变更，调用点分散 | anchor 提供定位/一致性，transformation 提供目标映射 |

三个场景都是一等验证对象；每个场景内部再按数据集/任务族分层报告。POCO 只是 `windows_to_kylin` 的一个数据集，不能代表整个场景，也不应被贴上“边界/负对照”的标签。

**`windows_to_kylin`**：至少两条任务线——

1. 平台层移植线：POCO 17 个平台文件、libuv 的 `*_unix` 层、nginx `src/os/unix`、libgit2 `src/util/unix`；
2. 构建/调用点线：curl 的 CMake 迁移、跨模块 API 替换、多调用点一致性。

POCO 适合测“单文件契约 + 依赖闭包”；nginx/libgit2/curl 适合测“定位 + 多文件 + 构建系统”。两者都保留。

**`cuda_to_musa`**：每个任务是 held-out 算子；同一族共享 `load_inline` 模板、tiling、reduction tree、dtype 处理和 launch config。它测跨任务复用，也测单任务内的数值/边界；transformation 层在这里是主力。

**`ipp_to_vsipl`**：合成仓库族是主形态，现有 20 题作为组件级补充。共享脚手架（FFT plan、buffer、window、streaming state）+ 8–12 个业务模块，每个模块 3–5 个 IPP 调用点；任务必须让 IPP 不可用或 wrapper 契约改变，迫使调用点全部修改。这个形态直接对应 [task_scale_limitations.md](task_scale_limitations.md) §5.3 的“合成仓库族”：现有单文件 L1/L2 无法测量“定位、跨文件一致修改、预算管理”，而这三项正是组件方法最应该起作用的地方。

### 4.3 任务说明

沿用 V2 §3 的七项检查表：只写迁移目标、公共接口、外部行为、验收口径、目标环境；不写实现路径、目标 API、文件名、测试名、隐藏用例。V3 增加一条：

- **验收口径必须覆盖多个调用点和跨位置一致性**，不能只写“某个函数通过”。

### 4.4 任务与组件的对齐

- 每个任务在评测侧声明它依赖的 anchor 和 transformation（不写进题面）；
- 任务族至少覆盖 2 个 anchor family 和 2 个 transformation family；
- 任务不得与库中的具体迁移记录同源；相似度审计通过后才能入库；
- 一个任务可以依赖多个 playbook；一个 playbook 可以服务多个任务。

### 4.5 难度校准

- 先跑 A0 / A1，目标通过率区间 **20%–60%**（沿用 `migration_benchmark_design.md` 的校准目标）；
- A0 100% 通过 → 任务太简单，增加位置数/隐含契约/规模；
- A0 100% 失败 → 检查是否不公平或不可解；
- A1 与 A0 的差距过大 → 检查原始记录是否泄漏或检索成本是否被低估。

### 4.6 任务规模

- 每族至少 3 题，覆盖不同能力族；
- 每题至少 3 个迁移位置，建议 5–10 个；
- 任务工作区保留源侧代码、公共头、调用方、构建入口；目标实现和 gold 在评测侧；
- 隐藏测试覆盖：全部位置、跨位置一致性、边界/错误语义、回归。

## 5. 抽取与发布流水线

### 5.1 anchor 抽取

沿用 V2：

```text
prepare -> build -> audit -> publish
```

其中 `build` 包含 extract/curate/prepare_reviews，`audit` 包含 review。

新增要求：

- `capability` 标签（线程、同步、文件系统、IPC、动态加载、错误/异常、时间、内存）；
- `positions` 必须是可验证的代码位置，不是“模块名”；
- `invariants` 必须可被隐藏测试或探针验证；
- 目标平台实现仍由 `evaluator_side` 排除。

### 5.2 transformation 抽取

```text
history_scan -> align -> abstract -> validate -> classify -> review -> publish
```

- **history_scan**：采集过去的迁移 diff、commit、issue、测试、评审意见；记录 provenance 和 split；
- **align**：before/after 对齐（文件、符号、hunk）；
- **abstract**：归纳 `source_pattern` / `target_pattern` / `mapping_rules` / `semantic_deltas` / `pitfalls`；
- **validate**：在留出样例上回放；能编译的编译，能跑测试的跑测试，不能跑的做静态检查；至少一个独立证据；
- **classify**：标注适用边界（OS、libc、版本、约束）、`confidence`、`leakage_class`；
- **review**：检查映射正确性、适用性、是否包含整文件 gold、是否与测试集近邻。

transformation 的粒度是“规则/决策”，不是“整文件代码”。允许少量 before/after 片段作为证据，但主体必须是可迁移的规则和契约。

### 5.3 join

- 共享能力词表：线程、同步、文件系统/路径、IPC/进程、动态加载、错误/异常、时间/时区、内存；
- 匹配键：`capability` + `source_pattern` + `contract` + 调用点上下文；
- 一个 anchor 可以匹配多个 transformation，按 `confidence` 和 `applicability` 排序；
- join 结果生成 playbook，并做一次人工/模型评审：映射是否真的适用于这些位置，是否有冲突；
- join 失败时保留部分组件：只有 anchor 或只有 transformation，供检索层降级使用。

### 5.4 发布与冻结

- `library/lock.json` 记录：
  - `source_snapshot` digest；
  - `history_snapshot` digest；
  - `join_version`；
  - `publication.status`；
  - 每个 transformation 的 provenance 和 `split`；
- `freeze_library.py` 扩展为双快照：
  - `snapshot.evaluator_side` 继续约束 source；
  - 新增 `history_evaluator_side`，约束 history 中不得出现当前测试任务的 gold/隐藏测试/任务包；
  - `verify` 同时重算两个 digest，并检查 join manifest；
- 库版本 = `source_digest + history_digest + join_version`，任何一层变化都产生新版本。

### 5.5 质量门槛

| 组件 | 门槛 |
|---|---|
| anchor | 证据充分；调用点完整；契约可验证；不含目标实现 |
| transformation | 映射正确；适用边界清楚；至少一个回放证据；无整文件 gold；与测试集相似度低于阈值 |
| playbook | join 正确；覆盖任务所需位置；无冲突；有预期失败模式 |

## 6. 实验设计

### 6.1 条件

| 条件 | 组件库 | 原始迁移记录 | 用途 |
|---|---|---|---|
| A0 | 无 | 无 | 直接迁移基线 |
| A1 | 无 | 有（可检索） | 控制“多给资料” |
| B_common | anchor | 有 | 共性层单独贡献 |
| B_trans | transformation | 有 | 经验层单独贡献 |
| B_both | playbook（anchor + transformation） | 有 | 完整方法 |
| C | 无关组件 | 无关记录 | 控制“上下文长度/相关性” |
| B0（可选） | 任务内现抽 | 有 | 区分“预建”与“现抽” |

A1 和 B 系都拥有同一份原始迁移记录、同样的检索工具和预算；B 的差异是**整理过的组件**。这样比较的是“整理”的价值，而不是“有没有资料”。条件在每个场景内独立运行，按场景/数据集分别报告；不把三个场景混成一个总分。

### 6.2 公平性与成本

- 同一模型、同一任务镜像、同一预算（步数、token、墙钟）；
- 库构建成本单独记录：anchor 抽取、transformation 抽取、join、评审；
- 报告**盈亏平衡任务数** = 建库成本 / 单题节省成本；
- 题面、公开测试、判分命令在所有条件之间保持一致；
- 建库者不看测试集；任务集与建库协议 pre-register。

### 6.3 指标

| 指标 | 定义 |
|---|---|
| 通过率 | 构建、行为、目标 API、回归四项全部通过的任务比例 |
| 检索命中率 | 期望的 anchor/transformation 出现在 agent 检索记录中的比例 |
| 检索精度 | 检索到的组件中真正被采用的比例 |
| 改编成功率 | 在“必须改编”隐藏用例上的通过率 |
| 复制率 | 与库组件 AST/token 相似度超阈值且无上下文修改的补丁比例 |
| 漏掉的调用点数 | 与 ground-truth 调用点对比 |
| 跨位置不一致数 | 同一约定在不同位置的实现差异数量 |
| 摊销成本 | 建库成本 / 任务数 + 单题成本 |
| 回归率 | 既有功能测试出现失败的次数 |

### 6.4 成功判据

- **主判据**：`B_both > max(B_common, B_trans)`，且在成本可接受的前提下成立；
- **经验层**：`B_trans > A1`，说明整理后的迁移经验优于原始记录；
- **共性层**：`B_common > A1`，说明共性组件的整理有独立贡献；
- **改编**：改编成功率高于阈值，复制率低于阈值，排除“检索 + 粘贴”；
- **成本**：摊销后接近或低于 A1，或盈亏平衡任务数在可接受范围；
- **负结果**：如果 `B_trans ≈ B_both`，说明共性层贡献有限；如果 `B_common ≈ A0`，说明旧方法在 POCO 类任务上无效；这些按边界条件如实报告。

### 6.5 校准与消融

- 先跑 A0 / A1 做难度校准，目标通过率 20%–60%；
- 消融：
  - anchor 去掉 `positions`，只留契约；
  - transformation 去掉 `pitfalls`，只留映射；
  - playbook 去掉 `applicability`，只留 join；
  - 看哪一部分真正起作用；
- 每族至少 3 题，每条件至少 3 次运行，按任务配对汇总。

### 6.6 统计与报告

- 报告均值、区间、效应量，不只报单点通过率；
- 通过率效应与成本效应分开报告；
- 负结果和边界结论与正结果同等重要；
- 不把不同场景、不同 L 层级混成一个总分。

### 6.7 预期假设

| 场景 / 数据集 | 预期 |
|---|---|
| `windows_to_kylin` / POCO | `B_trans` 主导；`B_common` 增量有限；用来验证“单文件平台移植”这一端 |
| `windows_to_kylin` / nginx、libgit2、curl | `B_both` 更好；anchor 提供定位/调用点，transformation 提供构建/API 映射 |
| `ipp_to_vsipl` / 合成仓库族 | `B_both` 最好；anchor 提供定位/一致性，transformation 提供目标映射 |
| `cuda_to_musa` / MultiKernelBench | `B_trans` 主导；主要收益是跨任务摊销 |

这些是假设，不是结论；实验要允许它们被推翻。

## 7. 与 V2 的关系

| V2 | V3 |
|---|---|
| 源侧冻结库 | `source_snapshot` + `anchors/` |
| B：预建冻结库 | 拆成 `B_common`（anchor）和 `B_both`（playbook） |
| B0：任务内现抽 | 保留为可选对照 |
| 6 个 POCO 任务 | `windows_to_kylin` 的一个任务族/数据集，继续保留；不代表整个场景 |
| `evaluator_side` | 对 `source_snapshot` 和 `history_snapshot` 都生效 |
| `freeze_library.py` | 扩展为双快照 + join manifest |
| 判分器、镜像、`prepare.sh` | 直接复用 |

V2 的结论仍然有效，但适用范围要改写：它证明的是“源侧共性组件在 POCO 单文件平台移植上的效果”，不能单独支撑“组件方法在迁移中普遍有效”。V3 在三个场景里补上 transformation 层和分散任务，才是完整命题。

## 8. 试点计划

**阶段 0：单族试点（跨场景各选一个最小任务）**

- 选一个契约族：`thread-lifecycle` 或 `error/exception`；
- 在三个场景里各选一个最小任务：`windows_to_kylin` 用 POCO 或 libuv，`cuda_to_musa` 用一个算子，`ipp_to_vsipl` 用一个小模块；
- 每个场景建 anchor（复用源侧抽取）+ 2–3 个 transformation（来自其他迁移/开发集）；
- 每个场景跑 A0 / A1 / B_common / B_trans / B_both；
- 先看 transformation 是否在 anchor 之上还有增量，以及三个场景的增量是否不同。

**阶段 1：多族扩展**

- 每个场景扩到 2 个族、3–5 题；
- 做相似度审计、改编审计、检索命中率分析；
- 校准难度，淘汰饱和或不可解的题。

**阶段 2：三场景扩展**

- `windows_to_kylin`：POCO 数据集（17 个平台文件）+ nginx/libgit2/curl 多文件/构建任务；
- `cuda_to_musa`：MultiKernelBench 多算子族；
- `ipp_to_vsipl`：合成仓库族 + 现有 20 题；
- 各场景跑满条件（A0/A1/B_common/B_trans/B_both），每条件至少 3 次。

**阶段 3：汇总与边界**

- 按场景、数据集、L 层级分别汇总；
- 写清“哪些数据集/任务形态有增益，哪些没有”；
- 汇总成本、复用率、一致性、回归率；不把三个场景混成一个总分。

## 9. 风险与限制

| 风险 | 说明 | 缓解 |
|---|---|---|
| 历史迁移稀缺/质量不一 | 跨项目记录可能拿不到或不可比 | 开发集自建；记录 provenance/confidence；先单族试点 |
| 分布漂移 | 其他项目的 transformation 不适用 | 测改编成功率；按 capability 分层报告 |
| 近邻泄漏 | 历史记录与当前 gold 太像 | 相似度审计；跨项目切分；隐藏测试含改编用例 |
| join 错误 | 能力词表太粗，匹配错 | 人工/模型评审；join 失败时降级为部分组件 |
| 检索失败 | 历史库太大，agent 找不到 | 建索引；测命中率/精度；A1 用同样检索工具 |
| 单数据集饱和（如 POCO） | 某个数据集任务太简单，区分度低 | 数据集内难度校准；换/加 nginx、libgit2、curl 等多文件数据集；不把数据集结论当成场景结论 |
| 成本不摊销 | 建库成本高于收益 | 报告盈亏平衡任务数；先小库试点 |
| 模型先验 | 常见映射模型本来就会 | 选项目特有/非显然约定；用改编用例区分 |
| 外部效度 | 合成仓库族不代表真实客户代码 | 明确限定；客户代码到位后再做 L3 |

## 10. 工件与复现（草案）

```text
v3/
├── windows_to_kylin/
│   ├── library/
│   │   ├── source/             # source_snapshot（可复用 v2 的冻结语料）
│   │   ├── history/            # Windows→Linux 迁移记录 + provenance
│   │   ├── anchors/
│   │   ├── transformations/
│   │   ├── playbooks/
│   │   ├── freeze.yaml
│   │   └── lock.json           # source digest + history digest + join version
│   └── tasks/                  # POCO、libuv、nginx、libgit2、curl...
├── cuda_to_musa/
│   ├── library/                # source / history / anchors / transformations / playbooks
│   └── tasks/                  # MultiKernelBench 算子族
├── ipp_to_vsipl/
│   ├── library/                # source / history / anchors / transformations / playbooks
│   └── tasks/                  # 合成仓库族 + 现有 20 题
└── slate.yaml                  # 三场景共享的任务集清单
```

工具扩展（草案）：

- `freeze_library.py`：双快照、`history_evaluator_side`、join manifest；
- `history_scan.py`：采集迁移记录与 provenance；
- `extract_transformation.py`：对齐、抽象、验证、分类；
- `join_playbooks.py`：anchor × transformation 匹配；
- `lint_dataset.py`：增加泄漏/相似度/改编检查；
- `runner.py`：注入 A0/A1/B_common/B_trans/B_both 条件；
- `verify_task.py`、`check_pins.py`：沿用。

复现命令（草案）：

```bash
# 以 windows_to_kylin 为例；三个场景各自独立建库、独立跑
SCENARIO=windows_to_kylin

# 1. 冻结两个快照
python3 tools/freeze_library.py snapshot --spec v3/$SCENARIO/library/freeze.yaml
python3 tools/freeze_library.py verify   --spec v3/$SCENARIO/library/freeze.yaml

# 2. 建库（三个场景共用同一条流水线；各场景只需自己的 spec）
python3 tools/build_history_corpus.py --spec v3/$SCENARIO/history/spec.yaml
python3 tools/extract_transformation.py --stage scan   --spec v3/$SCENARIO/history/spec.yaml
python3 tools/extract_transformation.py --stage all    --spec v3/$SCENARIO/history/spec.yaml --resume
python3 tools/extract_transformation.py --stage verify --spec v3/$SCENARIO/history/spec.yaml
# history_scan.py / join_playbooks.py 尚未实现

# 3. 校验任务与泄漏
python3 tools/verify_task.py --parent v3/$SCENARIO/tasks
python3 tools/lint_dataset.py

# 4. 跑一个条件
python3 shared/harness/runner.py \
  --task-root v3/$SCENARIO/tasks/<task> \
  --library-condition B_both \
  --base-work-dir v3/$SCENARIO/tasks/<task>/work \
  --work-dir <attempt-workspace> \
  --build-dir /tmp/judge-build-v3-$SCENARIO
```

三个场景共用 `build_history_corpus.py` → `extract_transformation.py` 同一条链路；
场景差异全部收敛到各自的 `history/spec.yaml`：

- `scenario` / `library_id`：写入语料 index 与发布库；
- `library_source_repos` / `held_out_repos`：该场景的历史来源与禁止泄漏的仓库；
- `language` / `backend_id`（以及可选的 `scan_extensions`、`caller_suffixes`、
  `header_scan`）：扫描器身份，默认 `cuda_to_musa` 用 `python@1`，其余用 `cpp@1`；
- `dataset_root` / `output_root`：任务目录与语料目录。

`extract` 之后的 curate / review / publish / verify 不再读取场景名，只读语料。

## 11. 对外表述边界

- V3 回答“迁移经验组件与共性组件各自/共同是否带来增益”，限定在设计场景；
- 不声称通用优越性、排行榜结论或跨模型普适性；
- 负结果与边界结论必须如实报告；
- 单数据集（如 POCO）的结论不能代表整个 `windows_to_kylin` 场景；
- 合成仓库族的结论不能直接外推到客户真实代码；
- 库的收益必须与建库成本一起报告。

## 12. 开放问题

1. **历史迁移从哪来？** 开源项目的平台移植 commit、开发集自建迁移、客户历史 PR，三者的质量和可比性不同。
2. **如何定义“同一约定”的 ground truth？** 跨位置不一致数需要可判定的基线，可能要为每个族手工标注。
3. **如何给建库和检索定价？** token/墙钟/人力三种口径，是否统一折算。
4. **一个 anchor 挂多少 transformation？** 多了会稀释检索，少了会覆盖不足。
5. **join 的质量如何规模化评审？** 人工评审不可扩展，模型评审又有偏差。
6. **如何防止库编码测试集的 idiom？** 跨项目切分 + 相似度审计 + 改编用例，是否足够。
7. **跨项目迁移经验真的可迁移吗？** 这是 V3 的核心假设，需要阶段 0 先验证。
8. **三场景如何汇总？** 任务数、数据集、难度不同，是按场景分别报告，还是加权汇总；加权口径是什么。