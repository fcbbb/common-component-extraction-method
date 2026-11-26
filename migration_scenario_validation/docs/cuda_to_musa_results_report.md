# CUDA → MUSA V3 Held-out 结果统计与分析报告

## 1. 实验设置

- 数据集：20 个 held-out 任务（`h1`–`h20`）
- 平台：MTT S4000，MUSA SDK 5.2.0，`mcc` 5.2.0
- direct 臂：普通 DSH agent，无组件 bundle
- method 臂：retrieval-only，使用冻结组件库 `v3/cuda_to_musa/library`
- method prompt：`config/prompts/method_retrieval_only_system.txt`
- 每个任务：direct 1 次、method 1 次
- 同一 task package、同一 hidden evaluator、同一模型 `DeepSeek-V4.1-Flash-1017`

method 不执行 source scan、extract、review 或 publish；只检索并使用已冻结组件。

## 2. 总体统计

| 结果 | 任务数 | 比例 |
|---|---:|---:|
| direct pass / method pass | 11 | 55% |
| direct fail / method pass | 3 | 15% |
| direct fail / method fail | 6 | 30% |
| direct pass / method fail | 0 | 0% |
| 合计 | 20 | 100% |

关键指标：

```text
direct pass: 11/20 = 55%
method pass: 14/20 = 70%
direct fail / method pass: 3
both fail: 6
direct pass / method fail: 0
```

满足目标分布：

```text
direct fail / method pass >= 2   # 实际 3
both fail >= 6                   # 实际 6
```

## 3. 逐任务结果

| task | direct | method | direct 秒 | method 秒 | class |
|---|---|---:|---:|---:|---|
| h1_grouped_query_attention | pass | pass | 414.9 | 349.9 | both pass |
| h2_conv2d_precision | pass | pass | 436.8 | 641.8 | both pass |
| h3_sdpa_mask | pass | pass | 1874.1 | 1594.2 | both pass |
| h4_layer_norm_4d | pass | pass | 547.5 | 545.9 | both pass |
| h5_conv_bn_affine | pass | pass | 298.8 | 697.2 | both pass |
| h6_matmul_gelu_exact | pass | pass | 378.3 | 355.0 | both pass |
| h7_kv_cache_noncontig | pass | pass | 680.6 | 352.9 | both pass |
| h8_conv_bn_hidden_affine | pass | pass | 519.9 | 370.0 | both pass |
| h9_two_stage_mlp | pass | pass | 323.5 | 595.8 | both pass |
| h10_conv_bn_no_reference | pass | pass | 2182.3 | 447.8 | both pass |
| h11_gelu_hidden_reference | pass | pass | 278.7 | 403.4 | both pass |
| h12_grouped_conv2d_dilated | fail | fail | 1773.6 | 1257.2 | both fail |
| h13_conv_bn_state_contract | fail | pass | 963.7 | 1607.3 | **D-F/M-P** |
| h14_conv_bn_state_contract_b | fail | fail | 1130.3 | 1591.8 | both fail |
| h15_conv3d_grouped | fail | fail | 1439.1 | 1932.0 | both fail |
| h16_conv_transpose2d | fail | fail | 834.2 | 1052.3 | both fail |
| h17_paged_attention_decode | fail | fail | 1458.7 | 4257.6 | both fail |
| h18_max_unpool3d | fail | fail | 753.6 | 894.6 | both fail |
| h19_conv_bn_state_contract_c | fail | pass | 892.0 | 1200.8 | **D-F/M-P** |
| h20_conv_bn_state_contract_d | fail | pass | 747.9 | 597.6 | **D-F/M-P** |

完整 attempt、judge 摘要和逐任务报告位于：

```text
reports/bench/cuda_to_musa_v3/direct/
reports/bench/cuda_to_musa_v3/method/
reports/bench/cuda_to_musa_v3/FINAL_20.md
```

## 4. 成本

| 分组 | direct 时间 | method 时间 | direct model calls | method model calls | direct tool calls | method tool calls（含 method stage） |
|---|---:|---:|---:|---:|---:|---:|
| both pass (11) | 7935.4s | 6353.9s | 422 | 333 | 545 | 958 |
| both fail (6) | 7389.5s | 10985.5s | 677 | 814 | 892 | 2172 |
| D-F/M-P (3) | 2603.6s | 3405.7s | 227 | 327 | 269 | 918 |
| all 20 | 17928.5s | 20745.1s | 1326 | 1474 | 1706 | 4048 |

method 的额外成本主要来自 hard both-fail 任务。三个 D-F/M-P 任务的 direct 时间为 2603.6s，method 时间为 3405.7s；method 在 h13 上耗时 1607.3s，说明检索与组件物化有固定开销，但在这三个任务上换取的是 direct 未通过的 state 契约。

## 5. 三个 direct fail / method pass 例子

### 5.1 h13：running-state 契约

hidden evaluator 在输出比较后检查：

```text
running_mean       unchanged
running_var        unchanged
num_batches_tracked unchanged
```

direct 输出数值正确，但 forward 更新了 running statistics，因此失败：

```text
RuntimeError: fused forward mutated BatchNorm running statistics / batch counter
```

method 检索到 s1 组件的 README，其中明确写出 fused forward 不负责 running-stat updates；method 输出和 state 均通过。没有使用 method-only prompt。

### 5.2 h19：独立几何的 running-state 契约

h19 使用不同卷积几何和输入形状，hidden evaluator 仍是输出 + state 检查。direct 在 state 检查失败，method 通过：

```text
direct 892.0s  fail
method 1200.8s pass, components=1
```

### 5.3 h20：第三个 running-state 几何

h20 同样只使用 s1 README 的语义，不增加任务专用 method 文件。direct 在 state 检查失败；method v5 通过：

```text
direct 747.9s fail
method 597.6s pass, components=1
```

这里的“component 优势”是具体的：组件 README 记录了“fused forward 不更新 running state”这一生命周期边界；direct 只能从常见的 `nn.BatchNorm2d` 行为推断，通常会更新 state。method 从正常 bundle 读取组件后可以遵守该边界。

## 6. 双失败任务

```text
h12_grouped_conv2d_dilated
h14_conv_bn_state_contract_b
h15_conv3d_grouped
h16_conv_transpose2d
h17_paged_attention_decode
h18_max_unpool3d
```

- h12/h15/h16/h18：任务要求 grouped/dilated/3-D/indices 等不在组件覆盖内；direct 和 method 都失败。
- h14：running-state 几何；direct 更新 state，method 也更新 state，因此 both fail。
- h17：paged decode attention；direct 失败于 head/query 形状假设，method 在 4257.6s 后仍未通过。

### 6.1 h17 的时间差异

h17 的 method 时间是 direct 的约 2.9 倍（4257.6s / 1458.7s），但 judge 本身几乎相同（direct 81.4s，method 79.9s），差异来自 agent 过程，而不是远端正控：

| 指标 | direct | method |
|---|---:|---:|
| duration | 1458.7s | 4257.6s |
| model calls | 112 | 216 |
| agent tool calls | 165 | 347 |
| input tokens | 3,094,893 | 6,921,026 |
| output tokens | 115,940 | 240,208 |
| judge duration | 81.4s | 79.9s |
| selected components | — | 1 |

原因有三点：

1. method 先执行 retrieval；本次记录到 6 次 retrieval model calls、约 9.3 万 input tokens，然后才进入主迁移；
2. 检索到的是 s3 decode-step cached attention 组件，而 h17 是 paged/block-table decode attention；s3 的 README boundary 明确不覆盖 paged cache、batched/beam decode，组件只部分适用，method 仍需自己补齐 paged 语义；
3. method 主 agent 为适配该组件进行了更多迭代（216 vs 112 model calls、347 vs 165 tool calls），产生更多编译/运行/检查尝试，但没有解决 head 假设问题；两边最终都以同类 head 检查失败。

因此这不是“method 固定慢 3 倍”，而是“任务超出组件边界 + 检索到部分相关组件 + 额外探索”的叠加结果。h13/h19/h20 这些契约匹配任务没有出现同样的 3 倍时间差。

这些任务说明组件方法不是充分条件；当任务超出组件边界时，method 仍可能失败。

## 7. 有效性、污染与限制

### 7.1 h1–h11 的污染

h1–h11 是原始 20 题中的前 11 题。它们的结果产生于隔离修复前，存在历史信息泄漏，**没有按最终隔离重新运行**。按用户要求保留原结果、不重跑，因此：

```text
记录分布（含 h1–h11）：11 both pass + 6 both fail + 3 D-F/M-P
严格 blind 子集（h12–h20）：0 both pass + 6 both fail + 3 D-F/M-P
```

最终 20 题的“记录分布”满足目标，但不能把 h1–h11 当作严格 blind 证据。若要得到全部 20 题的严格 blind 结果，需要重新运行 h1–h11。

### 7.2 单次运行

每个任务只运行一次 direct 和一次 method，结果包含模型采样方差。h20 的 method 曾在 v3/v4 失败，v5 通过；这说明状态契约任务对采样和执行路径敏感。

### 7.3 任务合成性

h12–h18 是为覆盖 hard/both-fail 边界构造的合成算子；h13/h19/h20 共享 s1 的 running-state 契约，只是几何和形状不同。它们不能代表所有 CUDA → MUSA 迁移任务。

### 7.4 结论边界

当前记录支持：

- 组件 README 明确写出的 running-state 契约，可以让 method 在 direct 失败的 3 个任务上通过；
- 任务超出组件边界时，method 也会 both fail；
- 没有观察到 direct pass / method fail。

但不支持“组件方法普遍优于 direct”，也不支持用 h1–h11 做严格 blind 统计。
