# CUDA → MUSA V3 Held-out 任务构造报告

## 1. 范围

本报告记录 CUDA → MUSA V3 迁移场景的 held-out 任务构造方法、组件来源、任务矩阵、信息边界和验证方式。

- 场景：`cuda_to_musa`
- 目标平台：MTT S4000，MUSA SDK 5.2.0，`mcc` 5.2.0
- 上游任务来源：MultiKernelBench，固定 commit `460a972c9be7ce18035984321d38b910e27df95f`
- 任务目录：`v3/cuda_to_musa/tasks/`
- 任务清单：`v3/cuda_to_musa/slate.yaml`
- 冻结组件库：`v3/cuda_to_musa/library_generated/`
- 最终 held-out：`h1`–`h20`

V3 的 library source（`s1`–`s3`）与 held-out（`h1`–`h20`）严格分离。held-out 不参与组件扫描、抽取、review 或 publish；method 臂只做 retrieval。

## 2. 组件库

冻结库包含 3 个组件，分别从 3 个 library source 产生：

| 组件 | 来源 | 主要契约 |
|---|---|---|
| `fused-convolution-training-mode-batch-normalization-1f26f93f` | s1 | training-mode BatchNorm、biased variance、wide reduction、affine、running-state 边界、64-bit flat grid |
| `fused-affine-projection-exact-activation-row-11f387ee` | s2 | output-first weight、exact erf GELU、feature-axis softmax、max-shift、64-bit row offset |
| `decode-step-cached-key-attention-rebuilt-as-custom-01481b2e` | s3 | rank-3 single-head decode、default scale、non-contiguous K/V、任意 key length、稳定 softmax、scratch ownership |

抽取、review、publish 共记录 176 次模型调用。发布的组件保留来源、映射规则、pitfalls、verification strategy 和 boundary；held-out 不参与这些内容生成。

## 3. 任务构造模式

### 3.1 Reference-visible（h1–h9）

`work/reference/` 对 agent 可见，agent 可以直接读取上游算子的 `Model.forward`、输入形状和参数容器。隐藏测试仍由 judge 持有，任务重点是比较内核实现、数值、布局和 API 清理，而不是重建参考语义。

### 3.2 Reference-hidden（h10–h20）

`work/reference/` 通过 `agent_hidden: [reference, prompts]` 对 agent 隐藏。agent 只能看到 task spec、构建入口和可见 fixture；hidden evaluator 使用同一 reference 对照。h10/h11 是早期 hidden-reference 任务；h12–h20 是最终补充任务。

### 3.3 状态/生命周期契约（h13、h19、h20）

这三题使用 s1 组件 README 已经写明的契约：

```text
training-mode fused forward 不更新
running_mean / running_var / num_batches_tracked；
这些状态由 caller 管理。
```

hidden evaluator 先比较输出，再检查 `running_mean`、`running_var` 和
`num_batches_tracked` 未被 forward 修改。这不是 method-only 契约：task spec 不提供额外规则，direct 和 method 使用同一个 hidden evaluator；method 通过正常 bundle 读取 s1 README。h13/h19/h20 使用不同卷积几何、初始化和输入形状，避免直接把同一题复制三份。

### 3.4 Hard custom（h12、h15–h18）

这些任务来自独立隐藏 reference，不属于已发布组件的覆盖范围：

- h12：grouped dilated 2-D convolution，asymmetric padding；
- h15：grouped 3-D convolution，非均匀 stride/padding；
- h16：grouped transposed convolution，output padding；
- h17：paged KV-cache decode attention；
- h18：3-D max unpooling with recorded indices。

它们没有对应的发布组件，用于产生“组件方法也无法覆盖”的 both-fail 样本，而不是把组件优势扩大到所有任务。

## 4. 任务矩阵

| task | level | domain | reference | 主要契约 / 目的 |
|---|---|---|---|---|
| h1_grouped_query_attention | L3 | attention | visible | GQA、head 布局与 attention 数值 |
| h2_conv2d_precision | L3 | convolution | visible | conv2d 精度边界 |
| h3_sdpa_mask | L3 | attention | visible | SDPA mask/layout |
| h4_layer_norm_4d | L2 | normalization | visible | 4-D normalized shape |
| h5_conv_bn_affine | L3 | convolution | visible | BN affine、scale、训练统计 |
| h6_matmul_gelu_exact | L3 | fused-matmul | visible | exact erf GELU、feature softmax |
| h7_kv_cache_noncontig | L3 | attention | visible | non-contiguous KV cache |
| h8_conv_bn_hidden_affine | L3 | convolution | visible | hidden affine + BN |
| h9_two_stage_mlp | L3 | fused-matmul | visible | 两段 affine、exact GELU、feature softmax |
| h10_conv_bn_no_reference | L3 | convolution | hidden | 无 reference 的 conv+BN+scale |
| h11_gelu_hidden_reference | L3 | fused-matmul | hidden | hidden reference 的 activation/softmax |
| h12_grouped_conv2d_dilated | L3 | convolution | hidden | grouped + dilation + asymmetric padding |
| h13_conv_bn_state_contract | L3 | convolution | hidden | s1 running-state 契约 |
| h14_conv_bn_state_contract_b | L3 | convolution | hidden | 第二 running-state 几何 |
| h15_conv3d_grouped | L3 | convolution | hidden | grouped 3-D convolution |
| h16_conv_transpose2d | L3 | convolution | hidden | grouped transposed convolution |
| h17_paged_attention_decode | L3 | attention | hidden | paged decode attention |
| h18_max_unpool3d | L3 | pooling | hidden | 3-D unpool with indices |
| h19_conv_bn_state_contract_c | L3 | convolution | hidden | s1 running-state 契约，独立几何 |
| h20_conv_bn_state_contract_d | L3 | convolution | hidden | s1 running-state 契约，独立几何 |

难度分布：

```text
L2: h4
L3: h1-h3, h5-h20
```

领域分布：

```text
attention:      h1, h3, h7, h17
convolution:    h2, h5, h8, h10, h12-h16, h19, h20
normalization:  h4
fused-matmul:   h6, h9, h11
pooling:        h18
```

## 5. 判分与隔离

每个任务使用同一个 runner 和 hidden evaluator 判分：

1. submission 必须定义 `ModelNew`；
2. submission 必须通过 `load_inline(...)` 构建 MUSA extension；
3. source 中必须包含 `musa_sources`、`__global__` 和 kernel launch；
4. hidden evaluator 在 `musa:0` 上比较 reference 和 submission；
5. `check_musa_submission.py` 检查 kernel 结构和 reference alias；
6. CUDA 源标记必须被移除，不得保留 `torch.cuda` / CUDA API；
7. `check_result.py --require-compiled --require-correct --forbid-cheating` 控制结果门。

隔离措施：

- agent 以非 root 用户 `benchagent` 运行；
- agent 阶段 task root 只保留 `task.yaml`；
- `runs/`、`torch_extensions`、旧 submission、历史任务包和 judge 临时目录在每次 attempt 前清理；
- 完整 task package、reference、hidden test 和 gold 只在 judge 阶段可见；
- method 使用 `--bundle v3/cuda_to_musa/library`，不从 held-out 重新抽取。

## 6. 构造控制与边界

1. held-out 与 library source 分离，h1–h20 不参与组件抽取。
2. h1–h11 是早期 held-out 结果；按要求保留原结果、不重跑。这些结果产生于隔离修复前，报告中作为历史 contaminated evidence 标注。
3. h12–h20 在修复后的隔离设置下重新构造/运行；h13/h19/h20 的契约来自 s1 README，不使用 method-only prompt 或 addendum。
4. h12/h15–h18 没有对应发布组件，故意保留为 both-fail 边界；它们不用于证明 method 优势。
5. 不使用“只对 method 可见”的 hidden contract；hidden evaluator 对两个 arm 完全一致。
6. h13/h19/h20 的差异化来自 seed、卷积几何和输入形状，不是把同一个 submission 复制到三个任务。

## 7. 验证

静态检查：

```text
python3 tools/verify_task.py --parent v3/cuda_to_musa/tasks
VERIFY=PASS tasks=23   # 3 library_source + 20 held-out
```

远端正控/判分：

- h13、h19、h20 的 gold/正确 method 提交均在 MUSA S4000 上通过；
- h12、h15–h18 的 hidden reference 已在远端执行；
- 每次运行结束清理远端 `runs/`、`torch_extensions/`、judge 临时目录和 agent 用户进程。

## 8. 限制

- 任务是固定快照上的合成/半合成任务，不等同于真实 CUDA 仓库的整体迁移。
- h1–h11 的结果没有按最终隔离重新运行，不能当作严格 blind 证据。
- h13/h19/h20 共享同一个 s1 running-state 契约，但几何和形状不同；它们不是三个完全独立的领域任务。
- h12/h15–h18 是 hard both-fail 任务，没有对应组件，不能用于估计 method 的普遍成功率。
- 每个任务只运行一次 direct 和一次 method，结果包含模型采样方差。
