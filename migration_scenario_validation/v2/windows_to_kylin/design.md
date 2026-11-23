# V2 场景实现：POCO Foundation 库 + 任务族

- 日期：2026-11-20
- 状态更新（2026-11-23）：任务包已并入 `v3/windows_to_kylin/tasks/`，本目录只保留设计、
  slate 与冻结库；下文中指向 `v2/windows_to_kylin/tasks/` 的命令不再可执行。
- 状态：13 个任务包已构建；宿主机 gold 正控 POCO 6/6、libgit2 3/3、nginx 2/2
  通过（非麒麟镜像）；curl 2 题需要带系统 TLS 头文件的目标镜像；冻结库待发布
- 设计依据：[docs/task_design_v2.md](../../docs/task_design_v2.md)
- 读者：本项目组

## 1. 本目录是什么

本目录把 [task_design_v2.md](../../docs/task_design_v2.md) 的 Windows → 麒麟主场景
落成可执行的任务包：

```text
v2/windows_to_kylin/
├── library/               # 冻结库：语料定义、快照锁、发布记录
│   ├── freeze.yaml        # POCO 数据集
│   ├── lock.json          # 由 tools/freeze_library.py 生成
│   ├── libgit2/           # libgit2 数据集（freeze.yaml + lock.json）
│   ├── nginx/             # nginx 数据集（freeze.yaml + lock.json）
│   ├── curl/              # curl 数据集（freeze.yaml + lock.json）
│   └── README.md
├── tasks/                 # 13 个任务包（由 slate.yaml 生成）
│   ├── v2_thread/         # POCO 6 题
│   ├── v2_file/
│   ├── v2_path/
│   ├── v2_shared_library/
│   ├── v2_rwlock_semaphore/
│   ├── v2_foundation_full/
│   ├── v2_libgit2_file/   # libgit2 3 题
│   ├── v2_libgit2_process/
│   ├── v2_libgit2_util_full/
│   ├── v2_nginx_files/    # nginx 2 题
│   ├── v2_nginx_full/
│   ├── v2_curl_tls/       # curl 2 题
│   └── v2_curl_build/
├── slate.yaml             # 任务族的单一来源
├── task_slate.md          # 渲染后的清单
├── provenance.csv         # 仓库 / commit / license
└── design.md              # 本文件
```

与 V1 的区别只在于验证单位和任务说明的写法；判分器、镜像、任务格式和
`prepare.sh` 机制全部复用 V1，不另起链路。

## 2. 库优先：先冻结，再出题

### 2.1 选库

选用 **POCO Foundation**，固定到 `pocoproject/poco@d6bd48a94c5f`
（`poco-1.13.3-release`，BSL-1.0）。理由：

- 平台层边界清晰：每个子系统有 `*_WIN32` 源侧实现和同 commit 内的目标平台实现；
- 公共头文件、调用方和构建入口都在同一棵树里，适合表达“外部契约”；
- 上游自带 Foundation testsuite，可按子系统组合隐藏测试；
- V1 已用它做过 L1/L3 校准，工具链和判分命令有基础。

### 2.2 冻结语料

`library/freeze.yaml` 定义抽取语料：源侧生产代码、公共头文件和构建文件。
**测试、样例、Windows 工程文件、一切任务包，以及目标平台（`*_POSIX.cpp` /
`*_UNIX.cpp`）实现都不进入语料。** 最后一项是本任务族的 gold，虽然和源侧代码
在同一个上游 commit 里，但必须在 `snapshot.evaluator_side` 中显式排除；否则
B 臂拿到的是答案，而不是组件知识。
抽取在任务信息引入之前完成（`snapshot.task_blind: true`），因此库的内容不可能
针对某一题裁剪。

`tools/freeze_library.py snapshot` 把语料选中的每个文件按内容哈希记录到
`library/lock.json`：

```text
sha256( concat(sorted("path\0sha256(content)\n")) )
```

当前锁：**635 个文件，6,477,368 字节，
`sha256:eff13f0cf703b37bd7307e5213ff5dfdc66f33858d3086f5725122aac92baa38`**。
`verify` 可随时重算并比对；任何语料变化都会使任务族读到不同的库。

### 2.3 发布与冻结

`lock.json` 的 `publication.status` 当前是 `pending_publication`。组件库由方法
流水线（`source_scan → extract → curate → prepare_reviews → review →
publish_library`）产出并通过审核后，用同一工具登记发布树：

```bash
python3 tools/freeze_library.py publish \
  --spec v2/windows_to_kylin/library/freeze.yaml \
  --library-root <published-library> --component-count <n>
python3 tools/freeze_library.py verify \
  --spec v2/windows_to_kylin/library/freeze.yaml
```

族内 6 个任务的 `library_manifest` 都指向同一份 `lock.json`；发布后不再改动，
后续任务只读不写。

## 3. 任务族

| # | Task ID | 族类型 | 移除范围 | 直接覆盖 | 复用/一致性覆盖 | 回归 |
|---:|---|---|---|---|---|---|
| 1 | `v2_thread` | 模式族 | 线程子系统 | `ThreadTest` | `ThreadPoolTest`、`ThreadLocalTest`、`TimerTest`、`ActivityTest`、`ActiveThreadPoolTest` | `FileTest`、`PathTest`、`SharedLibraryTest` |
| 2 | `v2_file` | 隐含契约 | 文件子系统 | `FileTest` | `FileStreamTest`、`DirectoryIteratorsTest`、`GlobTest` | `ThreadTest`、`PathTest`、`SharedLibraryTest` |
| 3 | `v2_path` | 隐含契约 | 路径子系统 | `PathTest` | `GlobTest`、`DirectoryIteratorsTest`、`DirectoryWatcherTest` | `FileTest`、`ThreadTest`、`SharedLibraryTest` |
| 4 | `v2_shared_library` | 模式族 | 动态加载子系统 | `SharedLibraryTest` | `ClassLoaderTest`、`ManifestTest` | `FileTest`、`ThreadTest`、`PathTest` |
| 5 | `v2_rwlock_semaphore` | 隐含契约 | 读写锁 + 信号量 | `RWLockTest`、`SemaphoreTest` | `ThreadPoolTest`、`TimerTest` | `FileTest`、`PathTest`、`SharedLibraryTest` |
| 6 | `v2_foundation_full` | 定位型 | 整个平台层（17 个实现文件） | 平台层 23 个测试类 | 同左 | 完整 Foundation 套件重跑（含隐藏套件） |

“复用/一致性覆盖”不引入新的测试夹具：它直接运行同一子系统在其他模块中的上游
测试。线程、定时器、线程池、活动派发、线程局部存储共享同一份线程契约；文件、
路径、目录迭代、glob 和文件流共享同一份文件系统契约。一个调用点单独“猜对”
不够，多个调用点必须同时成立。

### 3.1 顺序族的成本曲线

`sequence` 固定为 1…6，`v2_foundation_full` 是整库题。四条件实验里首题与后续题
的单位成本差异由 §6 的建库成本摊销记录，不写进任务判分。

## 4. 任务说明只写外部契约

6 个 `spec` 都按 [task_design_v2.md §3](../../docs/task_design_v2.md) 的七项检查表
写作：

1. 迁移目标与边界：哪个子系统、目标运行时；
2. 公共接口与构建入口：保留哪些公共头、产物是什么；
3. 外部可观察行为：生命周期、错误语义、状态、所有权；
4. 验收口径：哪些行为被覆盖；
5. 目标环境与可用依赖：麒麟 V10、GCC 13.3、CMake 3.16.5、libm；
6. 实现路径留在求解空间；
7. 题面只含契约与工作区信息，不含数据集元数据、仓库/commit、评测命令、门禁与隐藏测试。

题面（spec 加上渲染外壳）中**不出现**：

- 被删除的实现文件名；
- 目标平台 API 名称（`pthread_*`、`dlopen`、`open/stat` 等）；
- 算法、调用序列、目录布局；
- 测试名、隐藏用例、评测器路径。

agent 从 CMake 构建入口、公共头、调用方和 Windows 实现里自行恢复这些信息。
`tools/lint_dataset.py` 会对可见 spec 做目标 API 词表检查，并对渲染后的题面做
元数据/评测词检查；V2 的 6 个任务均通过。

## 5. 判分与门禁

每个任务声明四类门禁，实际执行由统一 runner 完成：

| 门禁 | 实现 |
|---|---|
| 构建 | `build.command`：上游 CMake，Foundation only，`ENABLE_TESTS=ON`（agent 侧关闭测试） |
| 行为 | `hidden_tests.command`：多套件上游测试 |
| 目标 API | `taskmodel.target_api_gate`：扫描重建文件是否实际调用目标平台 API |
| 回归 | `regression_tests.command`：未受改动影响的 Foundation 套件 |

`shared/harness/runner.py` 现在会分别记录 `build` / `tests` / `regression` /
`api_removal` / `target_api`，任一失败即任务失败。`regression_tests` 是 V2 新增的
可选段；没有该段的任务保持原行为。

每题在 `gates.api_removal.source_dirs` 中声明被移除的实现文件（1、2 或 17 个）。
反向门禁只扫描这些文件里残留的 Windows API；目标 API 门禁复用同一组路径，检查
重建实现确实调用了目标平台接口。这些路径不是写死在 spec 里的实现细节：POCO 的
可移植调用方用 `#include "Thread_POSIX.cpp"`、`#include "File_UNIX.cpp"` 这样的
形式直接包含平台实现，因此被移除的文件名在可见树里就是构建契约的一部分，agent
可以自行发现。扫描范围限定在这些文件，而不是整个 `Foundation/src`，是因为后者
包含 zlib/pcre2 捆绑代码和 `_MSC_VER` 可移植性守卫，会产生与任务无关的命中。

反向词表对 POCO 自己的类型名做过一次收窄：可移植实现里的
`throw CreateFileException(...)` 会命中 `CreateFile` 子串，因此正则写成
`CreateFile(?!Exception)`，仍能抓到 `CreateFileA/W/Mapping` 等 Win32 调用，
但不会把 POCO 的异常类当成平台调用。该误报是 `v2_foundation_full` 的 gold
正控首次跑到 API 门禁时发现的。

### 5.1 公开测试

按本轮决策，**不向 agent 暴露上游测试源码**：可见工作区只有头文件、调用方、
Windows 实现和构建入口。验收口径写在 spec 中，隐藏测试负责判分。这与设计文档
“工作区保留公开测试”的表述有一处偏离，原因和后续选项见 §8。

### 5.2 题面构造

agent 实际收到的题面由 `shared/harness/agent_prompt.py` 生成，只有五部分：
**标题、spec、目标环境、工作区、构建命令与提交方式**。以下内容一律不出现：

- 数据集元数据：scenario、level、family、family_type、sequence、difficulty；
- provenance：仓库 URL、commit、tag；
- 评测实现：评测命令、门禁名称、隐藏测试的存在或内容、“参考实现已被删除”之类的
  题目构造说明。

具体规则：

- 目标环境从 `task.yaml:target` 渲染成一行中性描述；spec 自己已经写明
  “Target environment” 时不再重复。
- 构建命令用 `taskmodel.agent_build_command()`，测试开关被替换为 `OFF`；judge
  实际执行的 `build.command`（`ENABLE_TESTS=ON`）只留在 `task.yaml`，不进题面。
- `tools/lint_dataset.py` 会**真实渲染**每个任务的 prompt，再对数据集元数据、
  provenance 和 judge 词表做检查。题面泄漏和 spec 泄漏一样会让 lint 失败，不再
  依赖作者记得。

工作区侧同理：`agent_view.copy_agent_view()` 除了过滤测试目录，还会过滤
`prepare.remove` / `prepare.remove_globs` 列出的实现文件；judge 侧
`runner._make_judge_work()` 先从 pristine 树里删掉这些路径，再由 agent overlay
提供重建实现。`verify_task.py` 静态检查 `work/` 中不得残留被移除文件。这三处
共同保证“干净工作区 + 外部契约”是由机制保证的，而不是靠约定。

## 6. 实验条件

V2 的四条件与现有入口的对应关系：

| 条件 | 含义 | 本轮状态 |
|---|---|---|
| A | 直接迁移，无组件库 | 已可跑：`./run-default.sh --scenario windows_to_kylin_v2` |
| B | 全族共享冻结库 | 待发布：需要先完成 `lock.json` 的 `publish` |
| B0 | 每个 attempt 现建库 | 已可跑：现有 `./run-method.sh` 语义即 B0 |
| C | 无关库对照 | 待实现：需要一个与 POCO 无关的冻结库和注入方式 |

`bench.yaml` 新增 `windows_to_kylin_v2` 任务集，默认 `enabled: false`，避免和 V1
诊断集混跑：

```bash
python3 tools/bench.py verify
./run-default.sh --scenario windows_to_kylin_v2 --smoke
```

建库成本单独记录：`freeze_library.py` 的语料哈希和 `publish` 时间戳进入
`lock.json`；实验侧按任务数摊销。

## 7. 与 V1 的关系

- V1 的 20 个 Kylin 任务继续作为组件级诊断集，目录、判分和结果都不改动；
- V2 只新增 `v2/windows_to_kylin/` 和 `windows_to_kylin_v2` 任务集；
- 两者共用 `shared/harness/runner.py`、镜像和模型路由，结果分开汇报；
- V1 的 `l1_poco_*` / `l3_poco_foundation_full` 与 V2 任务同源但不同约束：
  V1 spec 指向文件和目标 API，V2 spec 只写契约，且 V2 多了族内一致性与回归门禁。

## 8. 已知限制

1. **尚未在麒麟镜像里实测**：6 个任务的隐藏套件组合来自上游套件的静态映射；
   目标环境首次运行时，需要按实际结果调整套件和 `cppignore.lnx`。宿主机
   （WSL2、GCC 13.3）上的 gold 正控 6/6 通过，构建、隐藏测试、回归和双向 API
   门禁均为 pass（`reports/gold_sanity/v2/`）；这不是目标镜像的实测结果。
2. **冻结库尚未发布**：`publication.status` 仍是 `pending_publication`，
   B 臂在发布前不能启动。
3. **公开测试未曝光**：按本轮决策，测试源码不进入 agent 工作区。若后续要满足
   设计文档的“公开测试”要求，可在 `public_tests` 段增加精选子集，并在
   `agent_view.is_judge_protected` 中保护判分用的 pristine 测试。
4. **回归套件是静态选择**：子系统任务的回归集是“未受改动影响的相邻套件”，
   不是完整套件；`v2_foundation_full` 回归十个确定性顶层套件（Core、Streams、
   Crypt、Logging、Filesystem、UUID、Text、URI、Hashing、SharedLibrary，
   共 601 个测试），线程、定时器、进程、事件、缓存等时序敏感套件由隐藏测试
   覆盖。
5. **任务难度未实测**：V1 的 `difficulty` 是作者标注；V2 同样如此，需四条件实验
   给出通过率后才能校准。
6. **判分构建会连带编译 XML/JSON**：上游 `CMakeLists.txt` 在
   `if(ENABLE_TESTS)` 下无条件 `set(ENABLE_XML ON CACHE BOOL ... FORCE)`，
   JSON 同理（第 255–259 行），因此 `-DENABLE_XML=OFF` 不生效，
   每个判分构建都会额外编译 XML/JSON 测试运行器。这是上游行为，不影响判分，
   只增加约几分钟构建时间；不要通过改构建文件绕过（构建入口是判分侧
   pristine 文件）。
7. **上游 `-all` 不适合做回归门禁**：宿主机实测 `-all`（831 个测试）会偶发
   `UniqueExpireLRUCacheTest.testExpireN`（缓存过期计时）、
   `LocalDateTimeTest.testTimezone`（墙上时钟换算）和
   `BasicEventTest.testExpireReRegister`（事件过期计时）失败，与平台层实现无关。
   因此 `v2_foundation_full` 的回归改成显式的确定性套件列表，而不是给时序测试
   逐个加 ignore（后者是打地鼠）。不要为了“全量”放宽退出码判定，也不要把
   这些时序测试重新放进回归门禁。

## 9. 复现命令

```bash
# 1. 静态校验任务包
python3 tools/verify_task.py --parent v2/windows_to_kylin/tasks
python3 tools/lint_dataset.py
python3 tools/check_pins.py --offline --parent v2/windows_to_kylin/tasks

# 2. 冻结语料
python3 tools/freeze_library.py verify \
  --spec v2/windows_to_kylin/library/freeze.yaml

# 3. 物化单个任务（需要网络或本地 repo 缓存）
bash v2/windows_to_kylin/tasks/v2_thread/prepare.sh

# 4. 目标环境里判一题
python3 shared/harness/runner.py \
  --task-root v2/windows_to_kylin/tasks/v2_thread \
  --base-work-dir v2/windows_to_kylin/tasks/v2_thread/work \
  --work-dir <attempt-workspace> \
  --build-dir /tmp/judge-build-v2-thread

# 5. bench 入口
python3 tools/bench.py verify
./run-default.sh --scenario windows_to_kylin_v2 --only v2_thread --label v2_smoke
```

## 10. 多数据集扩展（2026-11-21）

POCO 数据集的平台层是一对一移植，迁移动作集中在一个文件，组件方法没有
“一处决策、多处位置”的杠杆。为在不改变 V2 契约的前提下增加任务形态，本目录
新增三个数据集、共 7 个任务；它们和 POCO 6 题一样只写外部契约，目标实现
evaluator-side，隐藏测试与判分链路复用现有机制。

| 数据集 | 任务 | 任务形态 | 冻结语料 |
|---|---|---|---|
| libgit2 | `v2_libgit2_file`、`v2_libgit2_process`、`v2_libgit2_util_full` | 单文件契约 → 整个 `src/util/unix` 目录 | `library/libgit2/` |
| nginx | `v2_nginx_files`、`v2_nginx_full` | 单文件 → 整个 `src/os/unix` OS 层 | `library/nginx/` |
| curl | `v2_curl_tls`、`v2_curl_build` | TLS 后端 → 自建 CMake 构建系统 | `library/curl/` |

每个数据集有自己的 `freeze.yaml` + `lock.json`，语料在任务出现前冻结
（`task_blind: true`），`snapshot.evaluator_side` 排除该数据集全部目标实现。
任务包各自声明 `library_manifest`，不共享 POCO 的锁。

与 V1 同名任务的区别只在题面和门禁：V1 spec 直接写被删文件与目标 API；V2
spec 只写外部契约，构建/隐藏测试/API 门沿用同一套上游命令。`v2_curl_build`
要求 agent 自己写 CMake，因此 `agent_view.is_judge_protected` 和
`taskmodel.target_api_gate` 对任何以 `curl_build` 结尾的任务 ID 都放行构建
文件，而不是只认 V1 的 `l3_curl_build`。

宿主机（WSL2、GCC 13.3）验证：

- `v2_libgit2_file`、`v2_libgit2_process`、`v2_libgit2_util_full` gold 正控
  3/3 通过；
- `v2_nginx_files`、`v2_nginx_full` gold 正控 2/2 通过；
- `v2_curl_tls`、`v2_curl_build` 未在宿主机构建：本机没有系统 TLS 开发头文件，
  需要在目标镜像里首次运行。静态校验（verify/lint/check_pins）均通过。

nginx 冒烟测试原先用 18080/18081，宿主机上 18080 已被其他服务占用，V2 任务
改用 28080/28081；V1 任务保持原端口不动。

当前可运行的是 A（直接迁移）和 B0（attempt 内现建库）。B 臂要等四个数据集的
冻结库发布后才会启动。