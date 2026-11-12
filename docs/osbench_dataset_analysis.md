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
```

OpenCC 旧 embedding 和 simdjson 不完整 embedding 已删除；当前不保留无效结果。
完整阶段 A 的 extraction/review/publish 尚未对 cereal 全量调用大模型。

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
