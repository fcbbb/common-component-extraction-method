# OS-Bench C++ Direct Baseline 结果分析

## 1. 实验范围

- 数据集：`datasets/osbench/dataset/windows2linux_cpp.jsonl`
- 任务数：6
- 迁移方向：Windows → Linux
- 运行方式：DSH direct arm，单次 Agent 尝试
- 模型：`deepseek-v4.1-flash-1017`（项目 `.env`）
- Node.js：`24.9.0`
- DSH：`@deepseek-ai/dsh@0.2.2-rc.1`
- 评测：OS-Bench `rebuild_cmd + test_cmd + print_cmd` 与 inline parser
- 容器隔离：`network=none`、`cap-drop=ALL`、`no-new-privileges`
- 结果目录：`work/osbench/direct_baseline/`

本文只保留修复后的最终结果，不保留中间对照。

运行过程与阶段耗时见 `../../tmp/运行日志.md`；代码修改见 `../../tmp/代码修改.md`。

## 2. Direct baseline 结果

| 任务 | Agent 状态 | 模型调用 | 耗时(s) | F2P | P2P | required_tests_passed |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| OpenCC | Submitted | 20 | 128.0 | 50/50 | 50/50 | ✅ |
| cereal | Submitted | 25 | 362.1 | 4/4 | 154/154 | ✅ |
| simdjson | Submitted | 35 | 547.3 | 31/31 | 80/80 | ✅ |
| asmjit | Submitted | 15 | 310.0 | 8/8 | 1/1 | ✅ |
| cppcheck | Submitted | 64 | 1037.6 | 1/1 | 107/107 | ✅ |
| leveldb | Submitted | 50 | 734.8 | 217/217 | 0/0 | ✅ |

汇总：

```text
required_tests_passed: 6/6
F2P: 311/311
P2P: 392/392
模型调用: 209 次
总 Agent 耗时: 3119.8 秒
输入 token: 约 1,043,318
输出 token: 约 100,077
```

说明：

- cppcheck 额外通过 `TestFileLister`、`TestSuppressions`；
- 这两个测试不在数据集 P2P 中；
- 因此 cppcheck 严格 `passed_match=false`，但 `required_tests_passed=true`，
  所有数据集要求的测试均已通过；
- leveldb 数据集 P2P 总数为 0，修复后 F2P 217/217；
- 除 cppcheck 的额外测试外，其余任务 `passed_match=true`。

## 3. Reference patch 对照

使用数据集提供的 reference patch，在相同修复后环境下评测：

| 任务 | reference F2P | reference P2P | reference required | direct required |
| --- | ---: | ---: | --- | --- |
| OpenCC | 50/50 | 50/50 | ✅ | ✅ |
| cereal | 4/4 | 154/154 | ✅ | ✅ |
| simdjson | 31/31 | 80/80 | ✅ | ✅ |
| asmjit | 8/8 | 1/1 | ✅ | ✅ |
| cppcheck | 1/1 | 107/107 | ✅ | ✅ |
| leveldb | 217/217 | 0/0 | ✅ | ✅ |

汇总：

```text
reference required_tests_passed: 6/6
reference F2P: 311/311
reference P2P: 392/392
```

direct 与 reference 在全部 6 个任务上的 required 结果一致。

## 4. 失败根因与修复

### 4.1 leveldb：prepared 镜像 `/tmp` 残留

初始现象：

```text
F2P 171/217
leveldb_tests SEGFAULT
IO error: /tmp/table_testdb/LOCK: Permission denied
```

原因：

- prepared 镜像默认用户为 `10001:10001`；
- 镜像构建时以 root 留下了 `/tmp/table_testdb`、`/tmp/db_options_test`、
  `/tmp/leveldbtest-0`；
- 测试用户无法清理/写入，导致测试失败并触发 segfault。

修复：

- 使用 `tools/clean_osbench_runtime.py` 清理这些 root-owned 目录；
- 保留镜像非 root 用户 `10001:10001`；
- 修复后 direct/reference 均为 217/217。

### 4.2 cppcheck：build 树中的陈旧源码副本

初始现象：

```text
F2P 1/1
P2P 104/107
missing: TestPathMatch, TestCmdlineParser, TestImportProject
```

原因：

- `/testbed/build/lib/pathmatch.cpp` 是 1624 字节旧副本；
- `/testbed/lib/pathmatch.cpp` 是完整实现；
- `cmake --build` 增量构建复用了 build 树旧副本。

修复：

- evaluator 在 rebuild 前同步 `build/lib/*.cpp`、`build/lib/*.h`：
  仅当 build 树文件存在且与源码不同时复制；
- 对没有 `build/lib` 的仓库是 no-op；
- 修复后 cppcheck P2P 107/107。

## 5. cppcheck 额外测试与数据集元数据

额外通过但不在数据集 P2P 中的测试：

```text
TestFileLister
TestSuppressions
```

影响：

- `required_tests_passed=true`；
- 严格 `passed_match=false`，因为实际通过集合大于冻结集合；
- 这两个测试不是失败，只是数据集 P2P 未登记。

cppcheck 原始 parquet 字段：

```text
FAIL_TO_PASS: ["TestCppcheck"]
PASS_TO_PASS: 107 个类级测试名
metadata.files_modified: 31
metadata.lines_removed: 6
metadata.lines_added: 0
metadata.estimated_loc: 3395
patch: 217 字节，仅修改 .gitignore
```

说明：

- P2P 107 和 reference patch 均来自原始 OS-Bench 数据；
- adapter 原样复制，没有重新统计测试数量或生成 patch；
- reference patch 只有 217 字节，与 metadata 中 31 个文件/3395 LOC
  不一致，是原始数据自身的不一致，不是本项目引入的。

## 6. 代码与环境修改

```text
src/component_method/task_execution/core/osbench_evaluation.py
  - rebuild 前同步 build 树中的陈旧源码副本

tools/clean_osbench_runtime.py
  - 清理 prepared OS-Bench 镜像中的 root-owned /tmp 测试目录
  - 保持非 root 运行用户

src/component_method/task_execution/core/environment.py
  - 兼容 prepared 镜像已有 /testbed
  - 跨平台任务 patch 校验使用 /testbed workdir

src/component_method/task_execution/core/evaluation.py
  - OS-Bench 任务分发到独立 evaluator
```

本次修复后的重新评测只使用已有 direct/reference patch，没有再次调用大模型。

## 7. 产物位置

```text
work/osbench/direct_baseline/results_summary.json
work/osbench/direct_baseline/results_summary.csv
work/osbench/direct_baseline/reference_vs_direct.json
work/osbench/direct_baseline/reference_vs_direct.csv
work/osbench/direct_baseline/<task_id>/outputs/tasks/direct/<task_id>/result.json
work/osbench/direct_baseline/<task_id>/outputs/tasks/direct/<task_id>/evaluation/result.json
work/osbench/direct_baseline/<task_id>/reference_eval/result.json
```

## 8. 结论

1. 两个初始失败都不是 Agent patch 的逻辑失败，而是 OS-Bench 镜像/构建缓存问题：
   - leveldb：`/tmp` 权限；
   - cppcheck：build 树陈旧 `pathmatch.cpp`。
2. 修复后 direct 和 reference 均为 **6/6 required 通过**。
3. direct 已在全部 6 个任务上达到 required ceiling；按 direct-ceiling 规则，
   组件方法在这 6 个任务上没有通过率提升空间。
4. 后续组件方法实验应重点分析迁移能力、平台差异和复用模式，而不是期待
   通过率提升。
5. cppcheck 的 `passed_match=false` 仅由两个未注册的额外测试通过导致，
   不是测试失败。
