# CUDA → 昇腾：正控覆盖审计

**日期**：2026-11-15  
**范围**：[cuda_to_ascend/tasks/](tasks/) 的 20 个任务包  
**结论**：**3/20 有上游 Ascend C 标准答案（正控）**；其余 **17/20 目前是 judge-only**，只能证明“判卷器存在”，不能证明“判卷器会接受一个正确实现”。

> 术语：**正控** = 把标准答案提交进去，整条链路（编译 → 数值 → 反作弊）必须通过。  
> **judge-only** = 只有判卷器，没有可运行的标准答案；这类题的通过率不能计入有效通过率。

---

## 1. 为什么必须先做正控

现在这 20 个包的判分入口都是上游的：

- **MultiKernelBench（MKBench，6 题）**：`eval_single_runner.py --language ascendc`，提交是六个字符串组成的 Python 文件；
- **CANN Bench（14 题）**：`scripts/run_evaluation.sh`，提交是 `submission/` 下的 Ascend C 工程。

这两个评测器都不是我们写的。如果不先用标准答案跑通，可能出现：

1. 评测器本身在当前镜像/驱动上跑不起来（CANN 版本、SoC 架构、Python 环境不匹配）；
2. 评测器能跑，但反作弊/编译规则把正确实现也拒了；
3. 题目声明的 op 名、dtype、shape、提交路径和评测器实际期望不一致。

这三种情况都会让 agent 的通过率失去意义。**先证明标准答案能过，再谈 agent。**

---

## 2. 场景 B（昇腾）逐题覆盖

| 题目 | 级别 | 子基准 | 上游 gold | 正控状态 | 备注 |
|---|---|---|---|---|---|
| `b_l1_mk_leaky_relu` | L1 | MKBench | `prompts/ascendc_new_model_leaky_relu.py` | **有，未运行** | 最优先跑通 |
| `b_l1_mk_mse_loss` | L1 | MKBench | `prompts/ascendc_new_model_mse_loss.py` | **有，未运行** | 最优先跑通 |
| `b_l2_mk_layer_norm` | L2 | MKBench | `prompts/ascendc_new_model_layer_norm.py` | **有，未运行** | 最优先跑通 |
| `b_l1_mk_sum_reduction` | L1 | MKBench | 无 drop-in | judge-only | 上游 `ascendc_new_model_reduce_sum.py` 是整张量 reduce；本题是按 dim reduce，需改写，不能直接当 gold |
| `b_l2_mk_cumsum` | L2 | MKBench | 无 | judge-only | 上游没有 cumsum 样例 |
| `b_l2_mk_standard_matmul` | L2 | MKBench | 无 | judge-only | 上游是 `matmul_add`，多了 add，需改写 |
| `b_l1_exp` | L1 | CANN Bench | 无 | judge-only | 建议作为第一个补正控的题 |
| `b_l1_softmax` | L1 | CANN Bench | 无 | judge-only | 建议作为第二个补正控的题 |
| `b_l1_swi_glu` | L1 | CANN Bench | 无 | judge-only |  |
| `b_l2_arg_max` | L2 | CANN Bench | 无 | judge-only |  |
| `b_l2_cross_entropy_loss` | L2 | CANN Bench | 无 | judge-only |  |
| `b_l2_gather` | L2 | CANN Bench | 无 | judge-only |  |
| `b_l2_rms_norm` | L2 | CANN Bench | 无 | judge-only | 建议作为第三个补正控的题 |
| `b_l2_top_k` | L2 | CANN Bench | 无 | judge-only |  |
| `b_l3_conv_2d` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |
| `b_l3_gqa` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |
| `b_l3_grouped_matmul` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |
| `b_l3_lstm` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |
| `b_l3_nms` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |
| `b_l3_selective_scan` | L3 | CANN Bench | 无 | judge-only | L3 最后处理 |

汇总：

| 子基准 | 题数 | 有上游 gold | judge-only |
|---|---:|---:|---:|
| MultiKernelBench | 6 | 3 | 3 |
| CANN Bench | 14 | 0 | 14 |
| **合计** | **20** | **3** | **17** |

---

## 3. 场景 A（麒麟）的对照

场景 A 的正控覆盖要好得多：19 道正向题都有上游同一 commit 的 POSIX 实现作为 gold，`prepare.sh` 会把它复制到 `gold/`，再从 agent 可见的 `work/` 删除。

| 级别 | 正向题 | 有 gold | 备注 |
|---|---:|---:|---|
| L1 | 5 | 5 | POCO 平台层 |
| L2 | 10 | 10 | curl / libarchive / libgit2 / libuv / nginx / OpenCV |
| L3 | 4 | 4 | curl / libgit2 / nginx / POCO 全量 |
| 负向题 | 1 | 0 | `negative_win32_eventlog`：正确答案是写不可移植说明，不是移植代码 |
| **合计** | **20** | **19** | |

所以麒麟侧要做的是把已有的 gold 真正跑一遍。见 [RUNBOOK.md](../../../RUNBOOK.md)。

---

## 4. 建议的校准集

先补这 3 道，覆盖三种典型 Ascend C 模式：

1. **`b_l1_exp`** —— elementwise 一元超越函数。  
   验证：对齐/尾块处理、dtype、反作弊、`run_evaluation.sh` 全链路。
2. **`b_l1_softmax`** —— 行内 reduce（max → exp → sum → div）。  
   验证：reduce 轴、数值稳定性、tiling。
3. **`b_l2_rms_norm`** —— reduce + rsqrt + 广播。  
   验证：多输入、广播、精度阈值。

选它们的理由：都是 L1/L2，实现量可控；三种模式覆盖了后续 L2/L3 的大部分公共结构；即使判分链路有问题，定位成本也最低。

---

## 5. 参考实现来源（候选，均未在本项目验证）

> 下面这些仓库是“写参考实现时可以看的上游代码”，**不是可以直接拷进 `submission/` 的 gold**。  
> 它们使用各自的算子工程布局（op_host / op_kernel / op_api / tiling），需要适配成 CANN Bench 的提交格式，并在 910B2 + CANN 9.1 上重新验证。  
> 仓库 HEAD 会移动，使用前必须 pin commit。

### 5.1 `cann/ops-math`（Exp 候选）

- 仓库：`https://gitcode.com/cann/ops-math.git`
- 本次探测 HEAD：`02ebd8f91b08365560eafa24cd947df880e60e80`（2026-11-15）
- 可参考路径：
  - `experimental/math/exp/op_kernel/exp.cpp`
  - `experimental/math/exp/op_kernel/exp.h`
  - `experimental/math/exp/op_host/`
  - `math/exp/op_kernel/exp_apt.cpp`（完整算子实现）
- **注意**：本次看到的 `math/exp/op_host/config/` 只有 `ascend350` / `ascend950` / `ascend960*`，没有 `ascend910b`。910B2 上能否直接编译需要实测；更稳妥的做法是从 `examples/aclnn_launch_example` 的 Sqrt 模板改一个 Exp，直接搬这个算子库风险较高。

### 5.2 `cann/ops-nn`（Softmax / RMSNorm 候选）

- 仓库：`https://gitcode.com/cann/ops-nn.git`
- 本次探测 HEAD：`1338f06dc07d3d24ec3d461a99effee198f92cef`（2026-11-15）
- Softmax：
  - `activation/softmax_v2/op_kernel/softmax_v2_apt.cpp`
  - `activation/softmax_v2/op_kernel/arch35/softmax_v2_*.h`
  - `activation/softmax_v2/op_host/`
  - **注意**：op_host config 同样只见 `ascend350` / `ascend950` / `ascend960*`，没有 `ascend910b`。
- RMSNorm：
  - `norm/rms_norm/op_kernel/rms_norm.cpp`
  - `norm/rms_norm/op_kernel/rms_norm.h`
  - `norm/rms_norm/op_host/config/ascend910b/rms_norm_binary.json` ← 本次看到的候选里唯一明确带 910B 配置的
  - 这是三道校准题里最有希望直接适配的一道，但仍需改提交布局并在 NPU 上验证。

### 5.3 `ascend/samples`（背景参考，不是 CANN Bench gold）

- 仓库：`https://gitee.com/ascend/samples.git`
- 本次探测 HEAD：`6511a5f4a45a1f68bd5e617989e68560f2f35cd6`（2026-11-15）
- 可参考：
  - `operator_contrib/LayerNormSample/`
  - `operator_contrib/InstanceNormSample/`
  - `cplusplus/level1_single_api/4_op_dev/.../softmax_tik.py`（TBE/TIK，不是 Ascend C）
- 结论：有归一化类样例和旧版 Softmax 样例，但没有与本项目 14 道 CANN Bench 题一一对应的 Ascend C 提交。

### 5.4 CANN Bench 自带的示例（只够验证流水线，不够验证题目）

- `cuda_to_ascend/tasks/b_l1_exp/work/examples/aclnn_launch_example/` —— Add / Sqrt 的 ACLNN 工程模板
- `cuda_to_ascend/tasks/b_l1_exp/work/examples/direct_launch_example/` —— 直调工程模板
- `cuda_to_ascend/tasks/b_l1_exp/work/examples/tasks/level1/sqrt/`、`level2/add/` —— 评测 fixture（`golden.py` + `proto.yaml` + `cases.yaml`）
- 用途：跑通 `scripts/run_evaluation.sh --source-dir examples/aclnn_launch_example --task-dir examples/tasks/level1/sqrt --no-perf`，证明**编译/执行/判分流水线本身**是通的。
- **不能**用它证明 Exp / Softmax / RMSNorm 的判分正确：fixture 只评 Add/Sqrt。

---

## 6. 补正控的顺序

1. 跑现成的 3 个 MKBench gold：`b_l1_mk_leaky_relu`、`b_l1_mk_mse_loss`、`b_l2_mk_layer_norm`。  
   命令：`python3 tools/gold_sanity.py --parent cuda_to_ascend/tasks --only b_l1_mk_leaky_relu ...`
2. 用 CANN Bench 自带 Add/Sqrt fixture 跑通评测流水线（不要求 NPU 上跑题目的 judge）。
3. 为 `b_l1_exp` 写 evaluator-only 参考提交，在 910B2 上验证编译 + 数值 + 反作弊。
4. 为 `b_l1_softmax` 写参考提交并验证。
5. 为 `b_l2_rms_norm` 写参考提交并验证。
6. 其余 14 道按 L1 → L2 → L3 补；L3 最后。

每一道题只有满足下面全部条件，才能从 judge-only 改成“正控已验证”：

- 参考提交能在目标镜像（CANN 9.1.0、910B2、固定 driver）上编译；
- 全部 `cases.yaml` 用例数值通过；
- 反作弊检测通过；
- 报告中记录了镜像 digest、driver 版本、日期和提交 hash。

---

## 7. 报告规则

- 没有跑过正控的题，报告中必须写 **`judge-only, unverified`**。
- 有效通过率的分母要么排除 judge-only 题，要么同时给出两个数字：
  - `resolve_rate_all`（含未验证题，仅作参考）；
  - `resolve_rate_verified`（只含正控通过的题，作为主指标）。
- 不允许把 judge-only 题的 agent 通过写成“判分链路已验证”。
- 正控失败时先修题目/环境，不要改 agent 或模型参数。

---

## 8. 当前可执行的命令

```bash
# 1. 检查 pin 是否仍然有效（不联网时用 --offline）
python3 tools/check_pins.py

# 2. 跑 3 个现成的 MKBench 正控（需要昇腾主机）
python3 tools/gold_sanity.py \
  --parent cuda_to_ascend/tasks \
  --only b_l1_mk_leaky_relu \
  --only b_l1_mk_mse_loss \
  --only b_l2_mk_layer_norm \
  --label mkbench_gold

# 3. 跑 CANN Bench 流水线 smoke（需要昇腾主机）
cd cuda_to_ascend/tasks/b_l1_exp/work
bash scripts/run_evaluation.sh \
  --source-dir examples/aclnn_launch_example \
  --task-dir examples/tasks/level1/sqrt --no-perf
```

更多环境准备和负控步骤见 [RUNBOOK.md](../../../RUNBOOK.md)。