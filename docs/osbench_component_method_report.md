# OS-Bench C++ 共性组件方法验证报告：cereal 与 leveldb

## 摘要

本报告记录共性组件提取方法在 OS-Bench Windows → Linux C++ 迁移任务上的验证结果。实验分为两个层次：

1. **cereal 最小闭环验证**：只使用 1 个最小 packet，验证任务盲组件抽取、review、validation、publish、retrieval、run_task 和官方评测的完整链路；
2. **leveldb 完整 packet 集验证**：对候选生成的 5 个 packet 全部执行 Stage A，验证方法在多 packet、多组件场景下的可用性和边界。

结果为：

```text
cereal：
  1 个 validated component
  Stage B 选中 component-001
  F2P 4/4，P2P 154/154

leveldb：
  5/5 packets 处理
  6 drafts，4 validated components
  Stage B 选中 component-004
  F2P 217/217，P2P 0/0
```

两个任务的组件方法都达到了 direct baseline 的 required tests，但没有超过
direct baseline 的通过率。当前数据集上 direct baseline 已达到 required
ceiling，因此组件方法的价值主要体现为迁移模式分析、源码能力复用和验证
harness，而不是提升 required pass rate。

## 1. 研究目标与验证问题

实验验证以下问题：

- **RQ1 提取有效性**：不读取任务说明、F2P/P2P 测试和标准补丁时，能否从
  固定版本的 C++ 生产源码形成结构完整、证据可追溯、可审核的组件？
- **RQ2 使用可行性**：组件库冻结后，后续任务能否从完整库中检索到相关组件，
  并在任务执行中实际使用？
- **RQ3 任务效用**：组件条件下的补丁能否通过 OS-Bench 官方 required tests，
  并与 direct baseline 对比？

实验保持任务盲边界：

```text
源码 / 候选 / packet / 组件抽取 / review
    → 组件库冻结
        → 后续任务 problem statement 可见
            → retrieval / run_task / evaluation
```

## 2. 数据集与任务选择

数据集：

```text
datasets/osbench/dataset/windows2linux_cpp.jsonl
SHA-256：e54c29fe11dbb9ca795fb6339548cb92a95a729c9871d18140f3793f6454be44
```

共 6 个 Windows → Linux C++ 迁移任务。当前完整验证：

- cereal：最小 packet 闭环；
- leveldb：剩余 5 个任务中选择 1 个，完整 packet 集。

其余 4 个任务只完成了准备和 direct baseline，没有运行组件 Stage A/B。

| 任务 | 源码文件 | 源码 byte | compile_commands | direct F2P | direct P2P |
| --- | ---: | ---: | ---: | ---: | ---: |
| OpenCC | 341 | 3,930,767 | 51 | 50/50 | 50/50 |
| cereal | 177 | 1,975,006 | 39 | 4/4 | 154/154 |
| simdjson | 388 | 10,221,534 | 153 | 31/31 | 80/80 |
| asmjit | 152 | 4,031,219 | 136 | 8/8 | 1/1 |
| cppcheck | 303 | 5,846,900 | 171 | 1/1 | 107/107 |
| leveldb | 133 | 882,433 | 93 | 217/217 | 0/0 |

选择 leveldb 的原因：

- 剩余任务中源码规模最小：133 个文件、882 KB；
- direct baseline 已成功；
- 任务难但子系统边界相对清晰，适合验证多 packet 和组件边界；
- 可以检验 logger、cache、range probe 等平台适配能力。

## 3. 方法流程

| 阶段 | 主要操作 | 输出 |
| --- | --- | --- |
| 源码扫描 | 读取固定源码快照、compile_commands，提取 C++ unit | source manifest、units |
| 语义/结构信号 | C2LLM embedding、clone、skeleton、AST、协议关系 | signals |
| 候选生成 | 语义近邻、重复代码、结构匹配、协议关系融合 | `protocol_candidates_v2.json` |
| packet 生成 | 候选去重、覆盖选择、focus/context 分组 | `protocol_packets_v2.json` |
| 组件抽取 | 任务盲 agent 在只读源码中抽取 artifact v2 | extraction response |
| review | 共性、证据、artifact 忠实度、协议契约、smoke case | review.json |
| validation | 编译/执行 smoke，观察 concrete linkage | validation.json |
| publish | 只发布 validated artifact | component library |
| retrieval | 对任务 problem statement 做全库选择 | selection.json |
| run_task | 把选中组件挂载到 `/testbed/component_bundle` | patch + result |
| evaluation | 官方 rebuild/test/print/parser | F2P/P2P |

## 4. 实验设置

```text
模型：deepseek-v4.1-flash-1017
Agent：DSH 0.2.2-rc.1
Node：24.9.0
Embedding：codefuse-ai/C2LLM-0.5B
  revision bd6d0ddb29f0c9a3d0f14281aedc9f940bb8d67a
  896 维，L2 normalize，max_seq_length 4096
GPU：RTX 3050 Laptop 4 GiB
容器：network=none，cap-drop=ALL，no-new-privileges，只读源码
```

评测以 OS-Bench 官方 `rebuild_cmd + test_cmd + print_cmd` 和 inline parser
为准；任务通过以 `required_tests_passed` 为准，同时记录 F2P/P2P 和
`passed_match`。

## 5. 结果汇总

| 项目 | cereal | leveldb |
| --- | --- | --- |
| 任务 | `USCiLab__cereal-a56bad8__cpp__linux__54d544` | `google__leveldb-ac69108__cpp__linux__b9bf34` |
| Stage A packet | 9 个中只使用 1 个 | 5/5 全部处理 |
| drafts | 1 | 6 |
| validated components | 1 | 4 |
| Stage A calls | 52 | 449 |
| retrieval calls | 8 | 14 |
| run_task calls | 54 | 47 |
| selected bundle | component-001 | component-004 |
| F2P | 4/4 | 217/217 |
| P2P | 154/154 | 0/0 |
| direct F2P | 4/4 | 217/217 |

### 5.1 cereal：最小 packet 闭环

```text
packet：protocol_packet_dd1c0e3e0767
component：cereal-sequence-roundtrip-harness
extraction：20 calls
review：32 calls
review：confirmed / faithful
protocol：confirmed_with_warnings
validation：2/2 smoke cases validated
```

Stage B：

```text
retrieval：8 calls，component-001
run_task：54 calls
component usage：
  component-001 / cereal_test::run_binary_sequence_matrix
  component-001 / cereal_test::run_portable_binary_sequence_matrix
F2P：4/4
P2P：154/154
```

cereal 的 9 个 packet 中只用了 1 个，是最小闭环验证，不是完整 packet 集验证。

### 5.2 leveldb：完整 packet 集

Stage A：

```text
packets：5/5
drafts：6
validated：4
model calls：449
wall：约 6561 s
```

| packet | candidates | 结果 |
| --- | ---: | --- |
| `protocol_packet_2725ce543b89` | 6 | 1 validated |
| `protocol_packet_e598ee8d2039` | 15 | 1 validated |
| `protocol_packet_1c1bc85fdbc7` | 2 | 1 validated |
| `protocol_packet_383fba5fd440` | 1 | 1 validated |
| `protocol_packet_c14d4fed3daa` | 2 | 2 drafts 未 validated |

validated：

```text
leveldb-sharded-lru-cache
leveldb-benchmark-opstats
leveldb-approximate-range-size-probe
leveldb-logger-dispatch
```

withheld：

```text
table_block_reader
table_file_cache
```

两者通过 review，但 standalone smoke link 仍依赖未随 artifact 提供的
leveldb 符号，例如 `ReadBlock`、`Block`、`NewLRUCache`、`Table::Open`。
因此未发布，但没有绕过 validation。

Stage B：

```text
retrieval：14 calls，154.18 s，component-004
run_task：47 calls，562.46 s
component usage：
  component-004 / leveldb::Logger
  component-004 / leveldb::Logger::Logv
  component-004 / leveldb::Log
  component-004 / leveldb::PosixLogger
  component-004 / leveldb::PosixLogger::Logv
F2P：217/217
P2P：0/0
```

## 6. 阶段耗时

### cereal

```text
review_retry5：516.5 s
当前代码复验：64.4 s（无新增模型调用）
run_task：693.3 s
```

cereal 的 Stage A 是单 packet 最小闭环，extraction 只读取 9 个 unit / 7 个文件。

### leveldb

```text
embedding：4054 × 896，1021.34 s
candidates：26 → 5 packets，328.86 s（wall 约 619 s）
Stage A：5/5 packets，6 drafts，4 validated，约 6561 s
retrieval：154.18 s
run_task：562.46 s
evaluation：约 112 s
```

leveldb Stage A 的完整步骤：

```text
sources+units：103.1 s
graph：0.0 s（缓存）
semantic：1.1 s
clone：110.1 s
skeleton：106.3 s
strict：2.1 s
protocol：4.5 s
```

## 7. 为什么 leveldb 更小却调用更多

关键不是源码 byte 数，而是 Stage A 的 packet 和组件数量：

```text
cereal：
  1 个 packet
  1 个 component
  20 extraction + 32 review = 52

leveldb：
  5 个 packet
  6 drafts
  extraction：40 + 51 + 31 + 25 + 40 = 187
  review：47 + 43 + 23 + 29 + 61 + 59 = 262
  合计：449
```

`api_calls` 是实际 agent API 调用，不是 449 次 HTTP 失败重试。调用量来自：

- 5 个 packet 的 extraction；
- 最大 packet 60 primary units / 17 files；
- 第一个 extraction task 文本约 364 KB；
- agent 进行多轮文件阅读、编译、自检和提交；
- 6 个组件 review；
- p5 两个 review 分别 61、59 次。

确实有失败，但失败主要在 schema/validation/link：

- packet 1：class/struct entrypoint 匹配；
- packet 2：entrypoint `id` 字段；
- packet 3：review member 字符串；
- packet 5：qualified name 与 entrypoint id 不一致；
- p5：standalone smoke link 缺 leveldb 符号。

失败后复用了已有 extraction submission/review，没有重新抽取 packet 1/2。

## 8. 代码修改的通用性

cereal 成功后 leveldb 仍需修改代码，是因为 cereal 只覆盖了一个最小 packet，
leveldb 暴露了更多通用 C++ 输出形态。修改都在通用路径，没有按 `task_id`
分支：

- `Entrypoint.from_json` 支持 `id`/`entrypoint_id`/`header` 等字段；
- class/struct/method 类型别名；
- overload 参数个数兜底；
- review member 字符串 file path / unit key；
- protocol field issue 无 `claim`；
- artifact runtime 忽略 `dependencies`/`notes`；
- artifact source 不在 compile_commands 时使用标准 include/standard；
- review 的 qualified name 映射到 artifact entrypoint id；
- 非 concrete smoke case 标记 skipped；
- component draft 的 `id`/`title`/`additional_evidence` 容错；
- 超长 embedding unit 使用 CPU fallback。

cereal 已用当前代码重新验证：

```text
validation_current：validated
elapsed：64.4 s
新增模型调用：0
```

因此这些修改没有破坏 cereal 的已验证结果。

## 9. 和 direct / reference 的关系

direct baseline：

```text
required_tests_passed：6/6
F2P：311/311
P2P：392/392
```

本报告中的两个组件任务：

```text
cereal direct：4/4 F2P，154/154 P2P
leveldb direct：217/217 F2P，0/0 P2P
```

组件方法结果：

```text
cereal component：4/4 F2P，154/154 P2P
leveldb component：217/217 F2P，0/0 P2P
```

结论：

- 两个任务都达到 direct baseline 的 required 结果；
- 没有产生额外通过率提升；
- 本数据集上 direct 已达到 required ceiling，组件方法的价值是迁移模式
  分析和可复用能力，而不是提高 required pass rate。

## 10. 限制

1. **cereal 不是完整 packet 集验证**：9 个 packet 只用了 1 个最小 packet。
2. **leveldb 有 2 个 withheld 组件**：通过 review 但未通过 standalone smoke
   link，说明局部 translation unit 抽取不自动等于可独立复用组件。
3. **模型调用成本高**：leveldb Stage A 449 次调用、约 1.8 小时；不适合
   无条件对全部任务全量运行。
4. **embedding 的 WSL CUDA 长序列不稳定**：已加入 CPU fallback，但这是
   运行环境适配，不是模型能力变化。
5. **未运行其余 4 个任务**：本报告不能代表 6 任务全量组件方法结果。

## 11. 产物与复现

### cereal

```text
work/osbench/tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/
  stage_a/
  stage_b/
  direct_baseline/
  README.md
  test_summary.json
```

### leveldb

```text
work/osbench/tasks/google__leveldb-ac69108__cpp__linux__b9bf34/
  stage_a/
    extraction/
    components/
    library/
    summary.json
    FINAL_RESULT.json
  stage_b/
    attempts/retrieval_01/
    task_attempts/task_01/
  README.md
  test_summary.json
```

### 组件库

```text
work/osbench/offline_artifacts/tasks/USCiLab__cereal-a56bad8__cpp__linux__54d544/component_library/
work/osbench/offline_artifacts/tasks/google__leveldb-ac69108__cpp__linux__b9bf34/component_library/
```

### 相关文档

```text
docs/osbench_dataset_analysis.md
docs/osbench_direct_baseline_report.md
../tmp/代码修改.md
../tmp/运行日志.md
```

### 模型调用

```text
cereal component method：52 + 8 + 54 = 114
leveldb component method：449 + 14 + 47 = 510
两项合计：624
累计已知（含 direct/smoke 等）：1014
```

## 12. 结论

1. cereal 证明了组件方法可以从任务盲源码抽取、审核、验证并发布一个可复用
   组件，且检索和任务执行会实际使用它。
2. leveldb 证明了多 packet 可以完整进入 Stage A；4 个组件发布，2 个组件因
   standalone link 边界不完整被 withheld。
3. 两个任务都达到 direct baseline 的 required tests，但组件方法没有提高
   required pass rate；当前数据集上 direct 已处于 ceiling。
4. leveldb 的调用量和耗时高于 cereal，主要原因是 5 个 packet、6 个组件和
   更宽的 packet，而不是源码文件更小。
5. 通用代码修改已覆盖多种 agent 输出形态，并用 cereal 当前代码复验确认没有
   破坏既有成功结果。