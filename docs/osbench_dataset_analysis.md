# OS-Bench windows2linux C++ 数据集分析

## 1. 数据集概况

- 数据源：`datasets/osbench/dataset/windows2linux_cpp.jsonl`
- 原始 parquet：`datasets/osbench/dataset_raw/data/windows2linux-00000-of-00001.parquet`
- 任务数：6
- 语言：C++（`c++17`）
- 迁移方向：Windows → Linux
- 任务类型：`cross_platform_migration`
- 数据集 SHA-256：`e54c29fe11dbb9ca795fb6339548cb92a95a729c9871d18140f3793f6454be44`

| 任务 | 仓库 | 难度 | F2P | P2P | 源文件 | 源字节 | compile_commands |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| BYVoid | BYVoid/OpenCC | hard | 50 | 50 | 341 | 3,930,767 | 51 |
| USCiLab | USCiLab/cereal | medium | 4 | 154 | 177 | 1,975,006 | 39 |
| simdjson | simdjson/simdjson | hard | 31 | 80 | 388 | 10,221,534 | 153 |
| asmjit | asmjit/asmjit | hard | 8 | 1 | 152 | 4,031,219 | 136 |
| danmar | danmar/cppcheck | hard | 1 | 107 | 303 | 5,846,900 | 171 |
| google | google/leveldb | hard | 217 | 0 | 133 | 882,433 | 93 |

数据集级注意点：

- `test_patch` 通常为空，测试已经存在于仓库中；
- 评测必须先执行 `rebuild_cmd`，再执行 `test_cmd` 和 `print_cmd`；
- 日志解析使用数据集中提供的 inline `parser(log)`；
- P2P 数量和 reference patch 来自原始 OS-Bench parquet，不由本项目重新生成。

## 2. 准备阶段状态

- 6/6 任务已生成独立任务包和工作区；
- 6/6 任务已准备源码快照、`compile_commands.json` 和运行镜像；
- 工作区同时作为 `COMPONENT_METHOD_RELEASE_ROOT` 和 `COMPONENT_METHOD_RUN_ROOT`；
- 镜像前缀：`component-method/osbench-cpp:<task_id>`，非 root 用户 `10001:10001`；
- 官方镜像：`repolaunch/osbench:<task_id>`；
- preflight 默认对 C++ 仓库做 20 个文件的有界扫描，避免首次全量 libclang
  扫描超时；`--scan-limit 0` 才表示全量。

## 3. 与现有流水线的兼容性

已适配：

- OS-Bench 数据集读取与任务包生成；
- C++ 源码扫描和 `compile_commands.json` 归一化；
- OS-Bench inline parser 与 `rebuild/test/print` evaluator；
- direct DSH 任务运行、patch 采集和 patch 应用校验；
- direct baseline 结果与 direct ceiling 判定；
- C++ 任务盲候选生成：后端解析缓存、clone/skeleton 信号、协议候选。

仍需注意：

- OS-Bench 是仓库级跨平台迁移任务，不是“复用某个已有组件实现功能”；
- 镜像/构建树可能包含陈旧源码副本或 root-owned 测试目录；
- C++ 首次 libclang 解析和 n-gram 匹配成本明显高于 Python。

## 4. 任务盲构建当前状态

本次只选择 cereal 作为阶段 A 测试任务：

```text
任务：USCiLab__cereal-a56bad8__cpp__linux__54d544
源文件：177
units：3550
embedding：3550 × 896
strict candidates：275
protocol candidates：23
packets：9
```

当前有效产物：

```text
work/osbench/offline_artifacts/embeddings/USCiLab__cereal-a56bad8__cpp__linux__54d544/
work/osbench/tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/signals/
work/osbench/tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/candidates/
  protocol_candidates_v2.json
  protocol_packets_v2.json
```

`protocol_packets_v2.json` 记录 9 个 packet 及其来源 candidate、文件、
unit 和 packet 配置。

阶段 A 的最小 packet smoke test 已经进入真实抽取和 review：

```text
smoke9 extraction：Submitted，20 次模型调用
extraction schema：ok，accepted component
smoke9 review：NoValidatedSubmission，17 次模型调用
review_retry：0 次（输出路径问题）
review_retry2：22 次（review cwd 问题）
review_retry3：Submitted，68 次模型调用，review confirmed
component validation/publish：citation 校验已修复；C++ template smoke 约束已修复，
尚未重新调用模型验证
```

当前阻塞根因：

- review agent 使用 host cwd，未使用容器 `/testbed`；
- controlled-bash 的 allowed cwd 只包含 `/testbed` / `/testbed/...`。

已修复：

- review/submission 提示明确 cwd `/testbed`；
- `DshHeadlessBackend` 设置 `COMPONENT_DSH_DEFAULT_CWD`；
- controlled-bash 对非法 cwd 回退到显式配置的容器 cwd；
- review artifact citation 支持 `component_bundle/...`；
- C++ smoke 必须使用非模板 concrete wrapper。

失败输出保留在：

```text
work/osbench/stage_a_cereal_smoke9/
```

启动阶段已支持 `unit_cache` 复用候选阶段 units；cereal 的 177 文件/3550 units
加载实测约 0.4 秒，不再重复完整 libclang 解析。

## 5. 方法适配性

**强相关：**

- 平台抽象、条件编译、文件 I/O、路径处理、CPU/时间/编码兼容逻辑；
- clone/skeleton/semantic/protocol 信号可用于发现跨平台重复模式；
- 组件协议契约可作为迁移边界和平台差异的参考。

**弱相关：**

- OS-Bench 目标是修复全部跨平台问题，而不是复用某个已有组件；
- direct baseline 修复后已在 6/6 任务达到 required ceiling；
- 组件方法更适合迁移模式分析，而不是提高通过率。

## 6. Direct baseline 结果概况

修复评测环境问题后：

```text
direct required_tests_passed: 6/6
direct F2P: 311/311
direct P2P: 392/392
reference required_tests_passed: 6/6
reference F2P: 311/311
reference P2P: 392/392
```

cppcheck 有 2 个额外通过但未登记在 P2P 的测试：

```text
TestFileLister
TestSuppressions
```

因此严格 `passed_match=false`，但 `required_tests_passed=true`。

详细结果、失败根因和修复见：

```text
docs/osbench_direct_baseline_report.md
../../tmp/运行日志.md
```

## 7. 产物索引

```text
work/osbench/
  config.json
  tasks.json
  preparation_manifest.json
  offline_artifacts/tasks/<task_id>/
  offline_artifacts/embeddings/_bootstrap/
  offline_artifacts/embeddings/USCiLab__cereal-a56bad8__cpp__linux__54d544/
  tasks/<task_id>/
  tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/signals/
  tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/candidates/
  direct_baseline/results_summary.json
  direct_baseline/results_summary.csv
  direct_baseline/reference_vs_direct.json
  direct_baseline/reference_vs_direct.csv
```

## 8. 单任务完整组件方法验证（cereal / leveldb）

在 direct baseline 之外，已选择两个任务做完整组件方法验证：

```text
cereal：
  1 个 validated component，library_stage_a
  Stage B 选中 component-001
  F2P 4/4，P2P 154/154

leveldb：
  5/5 packets，6 drafts，4 validated components
  Stage B 选中 component-004
  F2P 217/217，P2P 0/0
```

leveldb 的完整流程、阶段耗时、模型调用、失败组件和与 cereal 的对比见：

```text
docs/osbench_component_method_report.md
```

leveldb 归档：

```text
work/osbench/tasks/google__leveldb-ac69108__cpp__linux__b9bf34/
  stage_a/
  stage_b/
  README.md
  test_summary.json
```

## 9. 任务级分析与组件方法适用性

### 9.1 六个任务的基本面

| 任务 | repo | 源码文件 | 源码 byte | compile_commands | direct F2P | direct P2P |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| OpenCC | BYVoid/OpenCC | 341 | 3,930,767 | 51 | 50/50 | 50/50 |
| cereal | USCiLab/cereal | 177 | 1,975,006 | 39 | 4/4 | 154/154 |
| simdjson | simdjson/simdjson | 388 | 10,221,534 | 153 | 31/31 | 80/80 |
| asmjit | asmjit/asmjit | 152 | 4,031,219 | 136 | 8/8 | 1/1 |
| cppcheck | danmar/cppcheck | 303 | 5,846,900 | 171 | 1/1 | 107/107 |
| leveldb | google/leveldb | 133 | 882,433 | 93 | 217/217 | 0/0 |

共同点：

- 都是 Windows → Linux 的 C++ 迁移任务；
- 都存在平台分支、文件 I/O、路径、时间、编码、线程/锁或序列化差异；
- direct baseline 都能达到 required tests；组件方法的主要价值不是提升
  required pass rate。

### 9.2 cereal 的任务特征

cereal 是 header-heavy 的序列化库：

- 源码以 `include/cereal/**/*.hpp` 和 `unittests/*.hpp` 为主；
- 大量测试是模板化的容器/归档组合；
- 跨平台差异集中在归档字节序、类型宽度和序列化路径；
- 最小 packet 的 9 个 unit/7 个文件就能抽出“序列化容器 roundtrip harness”；
- 组件可以复用 `run_binary_sequence_matrix` 和
  `run_portable_binary_sequence_matrix` 这类 concrete wrapper；
- 适合用组件方法展示“测试模式抽取”和“可复用验证 harness”。

### 9.3 leveldb 的任务特征

leveldb 是 I/O、文件系统、线程和日志密集的存储引擎：

- 源码 133 个文件，但 `compile_commands` 有 93 条；
- 平台差异集中在 `util/env_posix.cc`、`util/posix_logger.h`、
  `db/filename.cc`、`port/posix_logger` 等；
- 迁移问题往往横跨文件系统 API、锁、日志、错误码和时间；
- F2P 粒度很细：217 个 required assertions；
- 适合检验：
  - 多个 packet 是否能覆盖不同迁移模式；
  - 组件是否能抽出 logger、cache、range probe 等局部能力；
  - 组件边界是否足以 standalone 编译/链接。

leveldb 的 5 个 packet 共产生 6 个 drafts：

- 4 个 validated：sharded LRU cache、benchmark stats、range-size probe、
  logger dispatch；
- 2 个 withheld：table block reader、table file cache；
- withheld 的原因是 artifact 仍依赖未提供的 leveldb 仓库符号，
  说明“局部 translation unit 抽取”不等于“可独立复用组件”。

### 9.4 哪些任务更适合组件方法

**更适合：**

- cereal：模板化、重复测试模式明显，组件边界相对容易闭合；
- leveldb：存在多个清晰平台适配层，logger/cache/range 等可独立表达；
- OpenCC：平台适配和转换管线较多，但源码规模较大；
- asmjit：代码生成/后端抽象，可能存在可复用模式。

**更困难：**

- simdjson：源码大、header 多、编译配置复杂；
- cppcheck：仓库包含大量第三方/测试/构建材料，候选和 review 噪声大。

### 9.5 任务规模与组件成本不完全是线性关系

leveldb 的源文件数/字节数比 cereal 小，但：

- leveldb 的 packet 更“宽”（最多 60 primary units / 17 files）；
- 每个 packet 的 extraction/review agent 需要更多工具调用；
- leveldb 产生了 5 个 packet 和 6 个 drafts，而 cereal 只跑了 1 个最小 packet；
- leveldb 的 review/validation 触及 logger、cache、table、range 等多个子系统。

因此：

```text
源码小 ≠ Stage A 调用少
```

组件方法的成本主要由 **packet 数、packet 宽度、draft 数、review 轮次和
validation 编译/链接** 决定，而不是单纯由仓库总字节数决定。

### 9.6 本数据集上的结论

1. 6 个任务的 direct baseline 都达到 required ceiling；
2. cereal 证明组件方法可以端到端闭环；
3. leveldb 证明多 packet 可以完整进入 Stage A，但会暴露组件边界问题；
4. 组件方法当前更适合作为“迁移模式分析 + 可复用验证 harness”，
   而不是“提升 required pass rate”；
5. 后续若要扩展到其余 4 个任务，应先按 packet 宽度、组件边界和 review
   成本做预算，而不是直接 6 任务全量运行。
