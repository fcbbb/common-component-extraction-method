# Scenario B — NVIDIA CUDA/Triton → 昇腾 Ascend C/CANN

## 1. 这个场景在测什么

给 agent 一个**上游算子评测仓库的固定快照**和一个算子契约，要求它用 Ascend C
写出能在昇腾 910B 上编译、运行、数值正确的实现。CUDA 侧的参考语义来自上游
PyTorch `golden.py`、`proto.yaml`、`desc.md` 和测试用例；MKBench 的部分算子
还保留了上游的 CUDA 模型与 AscendC 样例对。

判分调用**上游自己的 evaluator**：编译提交、在 NPU
上跑上游参考、比对每个用例。我们只在其上补统一的 API 清除门和结果解析。

- 源：CUDA/PyTorch 语义（MKBench 提供 CUDA model + PyTorch reference；
  CANN Bench 提供 proto/desc/golden/cases）。
- 目标：Ascend 910B2，CANN 9.1.0，bisheng 编译器。
- gold：MKBench 中上游自带的 AscendC 样例（`prompts/ascendc_new_model_*.py`）
  在 `prepare.sh` 里被移到 `gold/` 并从 `work/` 删除；没有 AscendC 样例的
  算子由上游 judge 直接判分，不伪造 gold。
- 判分：上游 compile / correctness / anti-cheat + 源码 CUDA 残留门。

## 2. 任务包结构

与场景 A 相同，是 recipe：

```text
cuda_to_ascend/tasks/<task_id>/
├── task.yaml          # 题目、提交路径、上游 judge 命令、门禁
├── provenance.json    # repo / commit / license / 可见文件 / gold 文件
├── prepare.sh         # 克隆固定 commit → work/，移走 AscendC 样例
├── gold/              # evaluator-only（仅 MKBench 的 few-shot 样例）
├── harness/           # run_task.py / check_api_removal.sh / check_result.py
└── README.md
```

`layout: repo`：`work/` 是完整的 pinned 上游快照。这样 evaluator、测试数据、
构建脚本都在原位，agent 不能靠“改 judge”通过——隐藏测试在 `{build}` 下的
独立目录运行，且 `work/` 会在每次 `prepare.sh` 时重置。

## 3. 题目清单（20 题）

“上游级别”指 CANN Bench `tasks/levelN/` 或 MKBench 的难度标注；本仓库的
L1/L2/L3 是**课程难度标定**，不逐条照抄上游目录。

| 级别 | 任务 | 上游 | 上游级别 | 提交物 | 判分入口 |
|---|---|---|---|---|---|
| L1 | `b_l1_exp` | CANN Bench | L1 | `submission/` + `build.sh` | `run_evaluation.sh --operator Exp` |
| L1 | `b_l1_swi_glu` | CANN Bench | L1 | 同上 | `--operator SwiGlu` |
| L1 | `b_l1_mk_leaky_relu` | MKBench | easy | `submission/leaky_relu_submission.py` | `eval_single_runner.py --op leaky_relu` |
| L1 | `b_l1_mk_mse_loss` | MKBench | easy | `.../mse_loss_submission.py` | `--op mse_loss` |
| L1 | `b_l1_mk_sum_reduction` | MKBench | easy | `.../sum_reduction_over_a_dimension_submission.py` | `--op sum_reduction_over_a_dimension` |
| L1 | `b_l1_softmax` | CANN Bench | L2 | 同 CANN 格式 | `--operator Softmax` |
| L2 | `b_l2_mk_layer_norm` | MKBench | medium | `.../layer_norm_submission.py` | `--op layer_norm` |
| L2 | `b_l2_rms_norm` | CANN Bench | L2 | 同 CANN 格式 | `--operator RmsNorm` |
| L2 | `b_l2_gather` | CANN Bench | L2 | 同上 | `--operator Gather` |
| L2 | `b_l2_cross_entropy_loss` | CANN Bench | L2 | 同上 | `--operator CrossEntropyLoss` |
| L2 | `b_l2_arg_max` | CANN Bench | L2 | 同上 | `--operator ArgMax` |
| L2 | `b_l2_top_k` | CANN Bench | L3 | 同上 | `--operator TopK` |
| L2 | `b_l2_mk_standard_matmul` | MKBench | medium | `.../standard_matrix_multiplication_submission.py` | `--op standard_matrix_multiplication` |
| L2 | `b_l2_mk_cumsum` | MKBench | medium | `.../cumsum_submission.py` | `--op cumsum` |
| L3 | `b_l3_conv_2d` | CANN Bench | L3 | 同 CANN 格式 | `--operator Conv2D` |
| L3 | `b_l3_nms` | CANN Bench | L3 | 同上 | `--operator NMS` |
| L3 | `b_l3_grouped_matmul` | CANN Bench | L3 | 同上 | `--operator GroupedMatmul` |
| L3 | `b_l3_gqa` | CANN Bench | L4 | 同上 | `--operator GQA` |
| L3 | `b_l3_lstm` | CANN Bench | L4 | 同上 | `--operator LSTM` |
| L3 | `b_l3_selective_scan` | CANN Bench | L4 | 同上 | `--operator SelectiveScan` |

说明：

- **CANN Bench 任务**（14 题）的“源”是算子契约，不是一份可编译的 CUDA
  实现。上游 `tasks/<level>/<op>/` 四件套是 `proto.yaml`（签名/dtype/shape）、
  `desc.md`（数学定义与边界条件）、`golden.py`（PyTorch 参考）、
  `cases.yaml|csv`（用例与容差）。这正是 CUDA 生态里 kernel 的规格来源，
  迁移时要求实现满足同一契约。
- **MKBench 任务**（6 题）是真正的“CUDA model + PyTorch reference + AscendC
  样例”三元组。样例被移入 `gold/`，agent 只能看到 CUDA 模型和参考，
  `eval_single_runner.py --language ascendc` 会编译 `submission/*.py` 中的
  六个源码字符串（msopgen 工程、host tiling、host op、kernel、pybind、model）。

## 4. 判分设计

1. **编译门**：上游 evaluator 调 `msopgen`/`cmake`/bisheng 构建并安装算子。
   - CANN Bench：`scripts/run_evaluation.sh --source-dir submission ...
     --no-perf`，编译失败直接非零退出。
   - MKBench：`eval_single_runner.py` 把编译结果写进 `result.json`，
     `shared/harness/check_result.py --require-compiled` 再判一次。
2. **正确性门**：上游对每个 `cases.yaml|csv` 用例跑 PyTorch golden，按任务
   自带容差比较（fp16/bf16 的容差由用例定义，本仓库不另设）。
   `--no-perf` 是刻意的：性能不进 pass/fail，只作为可选报告。
3. **反作弊门**：
   - MKBench 有 `utils/cheating_detection.py`，`check_result.py --forbid-cheating`
     要求结果中 `cheating` 为假；
   - CANN Bench 没有统一的反作弊器，因此靠“必须编译出 AscendC 算子 + NPU
     实跑用例 + 源码 CUDA 残留门”约束。**这是一个已知缺口**：理论上仍可在
     kernel 里调用 PyTorch 算子。若需要更严格，应在目标环境给 CANN Bench
     补一个类似 MKBench 的 detector；文档里不能写成已有。
4. **API 清除门**：在 `work/submission/` 上扫
   `__global__|__shared__|threadIdx|blockIdx|<<<|cudaXxx(|#include <cuda...>|nvcc`。
   这条门只覆盖提交物，不扫上游仓库——上游本身就包含 CUDA 参考实现和
   Triton 示例，扫整树会误报。
5. **gold 隔离**：MKBench 的三个算子（leaky_relu、mse_loss、layer_norm）有
   上游 AscendC few-shot 样例，已移入 `gold/`。其余 MKBench 算子没有对应
   AscendC 样例，CANN Bench 也没有 gold 实现；这些题只靠 judge 判分，
   `provenance.json` 的 `gold_kind` 标为 `benchmark-judge`，不生成假 gold。

## 5. 为什么选这两个 benchmark

| 仓库 | 作用 | 为什么适合 |
|---|---|---|
| [MultiKernelBench](https://github.com/wzzll123/MultiKernelBench)（MIT） | 6 题 | 自带 CUDA model、PyTorch reference、AscendC 样例和反作弊器；`eval_single_runner.py --language ascendc` 是可复现的编译/正确性 judge |
| [CANN Bench](https://gitcode.com/cann/cann-bench)（CANN OSL 2.0） | 14 题 | 官方 CANN 评测集，任务带 proto/desc/golden/cases 与容差，覆盖 elementwise → reduction → conv/attention/fused；`run_evaluation.sh` 是上游自己的判分入口 |

两者都固定 commit，license 记在 `provenance.json`：

- MKBench `460a972c9be7ce18035984321d38b910e27df95f`
- CANN Bench `53ea611a1b88da922b82812f2721dd0b2fa33476`

## 6. 评估过但未入选

| 候选 | 未入选原因 |
|---|---|
| `triton-ascend-ops` | 固定 commit 下没有可运行的 evaluator/测试入口，无法形成可复现判分；只适合作为阅读材料 |
| 自己写 CUDA kernel 再要求迁移 | 违反“用已有 benchmark/repo”的要求，且会变成自造 gold |
| MKBench 的 `add`/`matmul_add`/`reduce_sum` | 仓库中没有对应 reference 实现（只有 CUDA model），judge 无法给出可信正确性结论 |

## 7. 环境

见 [`../env/version_matrix.yaml`](../env/version_matrix.yaml) 与
[`../env/`](../env/) 下的 Dockerfile。要点：

- **两套 Python 环境**，不能混：
  - CANN Bench profile：`torch==2.10.0`、`torch_npu==2.10.0.post4`、
    CANN ≥ 9.1.0（见其 `pyproject.toml`）；
  - MKBench profile：`torch_npu==2.7.1`（见其 README）。
  同一台机器上用不同 venv/容器，`ASCEND_HOME_PATH` 指向对应 CANN。
- 需要真实 Ascend 910B2 NPU；`torch_npu` 无 CPU 等价路径。本仓库所有
  Scenario B 任务都要求 `--device npu`。
- `CMake` 用 3.31 以下或确认上游已规避 bisheng 不支持
  `--dependency-file` 的问题（CANN Bench 已内置规避，但自建镜像仍应固定版本）。
- CANN Bench 的 NMS 需要 `torchvision`（`uv sync --extra vision`）。

## 8. 本地能验证到什么程度

开发机是 WSL，无 NPU、无 CANN、无 `torch`/`torch_npu`，因此：

- 已做：40 个包的静态校验；`prepare.sh` 对 CANN Bench 与 MKBench 的实际
  物化；AscendC 样例确实从 `work/` 删除并出现在 `gold/`；`check_result.py`
  对 clean / compiled=false / correct=false / cheating=true 四种
  `result.json` 的单测；API 门对干净提交和含 CUDA 构造的提交的正反例。
- 未做：任何 msopgen 编译、NPU 执行、上游数值比对。**没有在 NPU 上跑过的
  结果不能写成通过。**

目标环境推荐顺序：

```bash
# 1. 物化
bash cuda_to_ascend/tasks/b_l1_mk_leaky_relu/prepare.sh

# 2. 静态校验（gold 未泄漏、schema 完整）
python3 tools/verify_task.py --parent cuda_to_ascend/tasks

# 3. 先在 NPU 上用 MKBench profile 跑一题，确认环境
python3 shared/harness/runner.py \
  --task-root cuda_to_ascend/tasks/b_l1_mk_leaky_relu \
  --build-dir cuda_to_ascend/tasks/b_l1_mk_leaky_relu/build_hidden

# 4. CANN Bench 任务换 CANN Bench profile 再跑
```

## 9. 已知风险

- **两个 upstream 的“级别”和方法学不同**：CANN Bench 按 `tasks/levelN`
  组织，MKBench 按 easy/medium 标注；本仓库的 L1/L2/L3 是课程标定，
  上表同时保留上游级别，避免把两者混为一谈。
- **CANN Bench 缺少反作弊器**：见 4.3。评测报告应把这条写成限制，不应
  把“编译通过 + 数值正确”表述为“确实手写了 AscendC”。
- **提交格式不统一**：CANN Bench 要一个带 `build.sh` 的源码树，MKBench 要
  一个含六个源码字符串的 Python 文件。题目里已分别写明，不能互换。
- **硬件依赖**：910B2 与 CANN 9.1.0 的组合是固定的；换卡/换 CANN 版本需要
  重新跑 smoke，尤其是 `aclnn_kernels/contiguous.h` 只在 9.1.0+ 存在。
- **`--no-perf`**：本场景只评测“能迁移且正确”，不评测性能。性能基线
  （HAP）由上游 `metadata/<hardware>.json` 提供，后续若加性能门，需要单独
  设计并固定硬件。