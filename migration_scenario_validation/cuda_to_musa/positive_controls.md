# CUDA → MUSA：正控覆盖审计

**日期**：2026-11-16  
**范围**：[cuda_to_musa/tasks/](tasks/) 的 20 个任务包  
**结论**：**20/20 正控已在真机验证通过**——2 份来自上游 MultiKernelBench
（`leaky_relu`、`mse_loss`），18 份是项目自写（evaluator-only）。
原 slate 的 `b_l2_rms_norm`、`b_l3_group_norm` 不是实现问题，而是被判卷器的
`torch.allclose` 内存需求挡住：8.59 GB 的 fp32 张量在 48 GB 卡上无法完成
`atol=rtol=1e-4` 比较（实测与复现脚本见
[reports/gold_sanity/musa_allclose_oom/](../reports/gold_sanity/musa_allclose_oom/README.md)）。
2026-11-16 这两题连同证据移入
[archive/cuda_to_musa_blocked_oom/](../archive/cuda_to_musa_blocked_oom/README.md)，
由 `b_l2_cosine_similarity_loss`、`b_l3_conv2d_batch_norm_scaling` 补位并实测
通过；**归档题不计入任何统计**。因此当前 20 题里没有 `judge-only,
unverified`，也没有 BLOCKED。

> 术语：**正控** = 把标准答案提交进去，整条链路（编译 → 数值 → 反作弊 →
> API 门 → kernel 结构门）必须通过。  
> **上游 gold** = pinned 上游仓库自带的 MUSA 样例，可直接当标准答案。  
> **项目自写正控** = 上游没有可用样例时，由本项目按 reference 契约实现的
> evaluator-only 提交；它可以证明判卷器可用，但**不能算作上游 gold**。  
> **BLOCKED** = 正控存在、且能编译并通过结构门，但判卷器在该硬件上无法
> 完成数值比较；不是“通过”，也不是“未验证”。

---

## 1. 为什么必须先做正控

20 个包的判分入口都是上游 MultiKernelBench 的
`eval_single_runner.py --language musa`，提交是单个 Python 文件。这个
evaluator 不是我们写的。如果不先用标准答案跑通，可能出现：

1. evaluator 在当前镜像/驱动上起不来（MUSA SDK 版本、S4000 架构、
   `torch_musa` 与 `torch` 不配套）；
2. evaluator 能跑，但反作弊器或 `check_musa_submission.py` 把正确实现拒了；
3. 题目声明的 op 名、dtype、shape、提交路径与 evaluator 实际期望不一致。

这三种情况都会让 agent 的通过率失去意义。**先证明标准答案能过，再谈 agent。**

---

## 2. 执行环境（实测）

| 项目 | 值 |
|---|---|
| 主机 | `autodl-container-p5m4fn65fq-5452d775`（租用实例，SSH 执行） |
| OS | Ubuntu 22.04.5 LTS |
| GPU | MTT S4000，47.90 GB，compute capability 2.2，56 SMs |
| 驱动 / runtime | 5.2.0-server / 5.2 |
| 编译器 | `mcc` 5.2.0（clang 14.0.0） |
| Python | 3.10.12 |
| PyTorch | `2.11.0.post1` |
| torch_musa | `2.11.0.post1+b431668` |
| `torch.musa.is_available()` | `True` |
| `torch.backends.musa.matmul.allow_tf32` | `False`（默认） |
| `torch.backends.mudnn.allow_tf32` | `True`（默认，见 §5.3） |

环境快照：`reports/gold_sanity/musa_environment.txt`。

---

## 3. 逐题覆盖与执行结果

| 题目 | 级别 | 正控来源 | 状态 | 证据 / 备注 |
|---|---|---|---|---|
| `b_l1_leaky_relu` | L1 | 上游 `prompts/musa_new_model_leaky_relu.py` | **PASS** | `musa_gold_final/` 98.2s；首跑 166.8s（`musa_smoke/`） |
| `b_l1_mse_loss` | L1 | 上游 `prompts/musa_new_model_mse_loss.py` | **PASS** | `musa_gold_final/` 121.2s；首跑 185.8s（`musa_gold2/`） |
| `b_l1_relu` | L1 | 自写 `relu_submission.py` | **PASS** | `musa_batch1/` 159.8s |
| `b_l1_sigmoid` | L1 | 自写 `sigmoid_submission.py` | **PASS** | `musa_batch1/` 161.1s |
| `b_l1_swish` | L1 | 自写 `swish_submission.py` | **PASS** | `musa_batch1/` 169.6s |
| `b_l1_softmax` | L1 | 自写 `softmax_submission.py` | **PASS** | `musa_batch2/` 99.8s |
| `b_l2_layer_norm` | L2 | 自写 `layer_norm_submission.py` | **PASS** | `musa_gold_final/` 25.0s；首跑 90.9s（`musa_authored/`） |
| ↳ 同题上游样例 | L2 | `prompts/musa_new_model_layer_norm.py` | **FAIL（不可用）** | 85.8s，`compiled=True, correct=False`；二维样例 vs 四维 reference，见 §4 |
| `b_l2_cumsum` | L2 | 自写 `cumsum_submission.py` | **PASS** | `musa_batch2/` 166.0s |
| `b_l2_cosine_similarity_loss` | L2 | 自写 `cosine_similarity_loss_submission.py` | **PASS** | `musa_batch6/` 79.1s（2026-11-16 补位；原 `b_l2_rms_norm` 已归档，见 §6） |
| `b_l2_sum_reduce` | L2 | 自写 `sum_reduction_over_a_dimension_submission.py` | **PASS** | `musa_batch4/` 178.7s（batch2 因文件名不匹配 0.2s 失败） |
| `b_l2_argmax` | L2 | 自写 `argmax_over_a_dimension_submission.py` | **PASS** | `musa_batch4/` 180.6s（batch2 因文件名 0.1s 失败） |
| `b_l2_gather` | L2 | 自写 `gather_submission.py` | **PASS** | `musa_batch4/` 73.7s（batch2 编译错：`long*` vs `long long*`） |
| `b_l2_cross_entropy_loss` | L2 | 自写 `cross_entropy_loss_submission.py` | **PASS** | `musa_batch4/` 80.7s（同上编译错） |
| `b_l3_standard_matmul` | L3 | 自写 `standard_matrix_multiplication_submission.py` | **PASS** | `musa_batch4/` 94.3s（batch3 因文件名 0.2s 失败） |
| `b_l3_conv2d` | L3 | 自写 `conv_standard_2d_square_input_square_kernel_submission.py` | **PASS** | `musa_batch5/` 42.6s；batch4 的 84.8s 失败是 muDNN 默认 TF32，见 §5.3 |
| `b_l3_gqa` | L3 | 自写 `group_query_attention_submission.py` | **PASS** | `musa_batch4/` 103.4s（batch3 因文件名 0.1s 失败） |
| `b_l3_sdpa` | L3 | 自写 `scaled_dot_product_attention_submission.py` | **PASS** | `musa_batch4/` 251.0s（batch3 文件名 + NT tile 修复） |
| `b_l3_conv2d_batch_norm_scaling` | L3 | 自写 `conv2d_batch_norm_scaling_submission.py` | **PASS** | `musa_batch6/` 105.9s（2026-11-16 补位；原 `b_l3_group_norm` 已归档，见 §6） |
| `b_l3_matmul_gelu_softmax` | L3 | 自写 `matmul_gelu_softmax_submission.py` | **PASS** | `musa_batch4/` 99.7s（batch3 的 86.7s 失败是 NT tile 行索引 bug） |
| `b_l3_kv_cached_attention` | L3 | 自写 `kv_cached_attention_inference_submission.py` | **PASS** | `musa_batch4/` 77.1s（batch3 因文件名 0.1s 失败） |

汇总：

| 来源 | 题数 | 已验证 | 受阻 | 说明 |
|---|---:|---:|---:|---|
| 上游 gold | 2 | **2** | 0 | `leaky_relu`、`mse_loss` |
| 项目自写正控 | 18 | **18** | 0 | 含 2026-11-16 补位的 2 题 |
| 合计 | 20 | **20** | 0 | 无 `judge-only` 题，无 BLOCKED 题 |

`check_pins.py --offline` 的 `judge_only=18` 是**按“是否声明上游 gold 文件”
统计的**：18 道自写正控题没有 `source.gold_files`，所以仍计入。它与本表的
“正控已验证”不是一个口径，不要混用。

每题的 `status=pass` 都要求 `runner` 里 `tests=pass` 且 `api_removal=pass`，
且本地 `check_musa_submission.py` 对 20 份正控全部 `MUSA_SUBMISSION=PASS`
（结构门）。逐题 JSON 在对应 `reports/gold_sanity/musa_*/<task>.json`。

**最终合并运行**：2026-11-16 21:09–21:30（UTC 13:09–13:30）在上述主机上
用 §11 的一条命令跑完原 18 题，`musa_all18` 返回
`SUMMARY pass=18 fail=0 skip=0 error=0`、`GOLD_SANITY_RC=0`（20.7 分钟）。
同日换题后补跑 `musa_batch6` 覆盖两道新题：
`SUMMARY pass=2 fail=0 skip=0 error=0`（cosine 79.1s、conv+BN 105.9s）。
每一题都是 `tests=pass`、`api_removal=pass`，并含
`MUSA_SUBMISSION=PASS`。这两次运行是最终题包上的权威证据；批次目录保留为
失败与修复过程记录。

---

## 4. `layer_norm`：上游样例为什么无效

pinned commit 里 `layer_norm` 存在两套契约：

| 文件 | 输入契约 |
|---|---|
| `prompts/cuda_model_layer_norm.py` | `x = (16384, 1024)`，`normalized_shape = 1024` |
| `reference/normalization/layer_norm.py`（evaluator 使用） | `x = (64, 64, 256, 256)`，`normalized_shape = (64, 256, 256)` |

上游 MUSA 样例按二维写（`rows = x.size(0)`, `cols = x.size(1)`），在四维
reference 下只写入 `64 x 64` 个值，其余保持 `zeros_like`。真机结果是
`compiled=True, correct=False, cheating=False`——不是环境问题，而是样例
与 evaluator 契约不一致。

因此：

- 上游样例移到 `tasks/b_l2_layer_norm/upstream_nonconforming/`，不参与
  任何正控统计；
- 题包改为 judge-only（无上游 gold 声明）；
- 另写 `tasks/b_l2_layer_norm/gold_authored/layer_norm_submission.py`，
  按四维 reference 实现 mean/variance/rsqrt/affine，`gold_sanity.py` 在
  无上游 gold 时自动还原，并在报告里标 `(project-authored)`。

---

## 5. 批次历史与修掉的题目包缺陷

四批实测的通过数：batch1 3/3、batch2 2/7、batch3 0/7、batch4 9/10、
batch5 1/1（conv2d 重跑）。失败都不是环境问题，逐条记录如下。

### 5.1 正控文件名必须等于 `op_name`（batch2/batch3，共 7 题）

`gold_sanity.py` 把 `gold_authored/*.py` **按原文件名**还原到
`work/submission/`，而 evaluator 按 `op_name` 找
`<op_name>_submission.py`。首版自写正控用了短名（`argmax_submission.py`、
`conv2d_submission.py`……），batch2/batch3 里表现为 0.1–0.2s 的
`FileNotFoundError`。已全部改名为 `<op_name>_submission.py`：

- `sum_reduction_over_a_dimension_submission.py`
- `argmax_over_a_dimension_submission.py`
- `standard_matrix_multiplication_submission.py`
- `conv_standard_2d_square_input_square_kernel_submission.py`
- `group_query_attention_submission.py`
- `scaled_dot_product_attention_submission.py`
- `kv_cached_attention_inference_submission.py`

**注意**：改名后必须删除主机上旧文件名的残留，因为 `gold_sanity.py` 会复制
`gold_authored/` 里**所有** `*.py`。

### 5.2 MUSA 的 `data_ptr<int64_t>()` 是 `long*`（batch2，2 题）

`gather`、`cross_entropy_loss` 首版 kernel 形参写成 `const long long*`，
`mcc` 报
`cannot initialize a parameter of type 'const long long *' with an rvalue of type 'long *'`。
在 MUSA（Linux x86_64）上 `int64_t` 是 `long`，改为 `const int64_t*` 后编译通过。

### 5.3 muDNN 默认 TF32 让精确 fp32 实现“不匹配”（batch4 → batch5）

`b_l3_conv2d` 的参考 `nn.Conv2d` 走 muDNN，而
`torch.backends.mudnn.allow_tf32` 在这套 torch_musa 上默认 **True**。
TF32 参考结果与真 fp32 差到 5.0e-4，超过 `atol=rtol=1e-4`；实测对 float64
CPU 真值，自写 kernel 误差 1.0e-6，参考端反而偏差 4.1e-4。正控模块现在在
import 时执行 `torch.backends.mudnn.allow_tf32 = False`（evaluator-only），
两者差 1.6e-6，74,342,400 个元素 0 超差。复现脚本与完整输出：
[reports/gold_sanity/conv2d_tf32/](../reports/gold_sanity/conv2d_tf32/README.md)。

`nn.Linear` / matmul 路径不受影响：它由
`torch.backends.musa.matmul.allow_tf32` 控制，本来就是 `False`。

### 5.4 NT 分块 kernel 的 B 块行索引（batch3，2 题）

`matmul_gelu_softmax` 和 `sdpa` 的 `bmm_nt` 类 kernel 首版用
`threadIdx.x` 同时索引 B 的行和 k，实际行应来自 `threadIdx.y`
（`blockIdx.x * TILE + threadIdx.y`）。表现是普通 `Output mismatch`
（`matmul_gelu_softmax` 86.7s），修复后 batch4 通过。

---

## 6. 两题受阻并归档：`allclose` 在 48 GB 卡上放不下 8.59 GB 张量

`b_l2_rms_norm` 与 `b_l3_group_norm` 的输入都是
`(128, 64, 512, 512)` fp32 = 2.1e9 元素 = 8.59 GB。判卷器
（`utils/correctness.py`）同时持有输入、参考输出、提交输出，并用
`torch.allclose(ref, new, atol=1e-4, rtol=1e-4)` 比较；在这套
torch/MUSA 上 `allclose` 会额外物化数个同尺寸临时量
（`(a-b).abs()`、`rtol*|b|`、`atol+...`、bool mask），约 30 GiB。

实测：

- 复现 evaluator 循环：24 GiB 有效张量时 `allclose` 内 OOM
  （`Tried to allocate 8.00 GiB`，`42.00 GiB is allocated`）；
- 即使提交端原地写回、别名输入（最小常驻 16 GiB），仍在
  `allclose` 内 OOM（`44.00 GiB allocated`，请求 2.00 GiB）；
  `PYTORCH_MUSA_ALLOC_CONF=expandable_segments:True` 结果相同。

所以**任何提交端实现都无法**让比较在 47.90 GB 上完成。两条正控 kernel
本身是好的：缩小形状的补充数值检查（非 evaluator 契约、不计入验证）显示
`allclose=True`，最大绝对误差 3.6e-7–6.0e-7。证据：

- [reports/gold_sanity/musa_allclose_oom/README.md](../reports/gold_sanity/musa_allclose_oom/README.md)
- [probe_reference_loop.py](../reports/gold_sanity/musa_allclose_oom/probe_reference_loop.py)、
  [probe_alias_allclose.py](../reports/gold_sanity/musa_allclose_oom/probe_alias_allclose.py)
- [small_shape_check.txt](../reports/gold_sanity/musa_allclose_oom/small_shape_check.txt)

解除受阻需要 >48 GB 可用显存的卡（判卷器不改），或上游 evaluator 改成
分块比较（超出本场景范围）。因此在 2026-11-16 把两题整体移到
`archive/cuda_to_musa_blocked_oom/`（包、探针、日志一起），slate 的 20 题
用 `b_l2_cosine_similarity_loss`、`b_l3_conv2d_batch_norm_scaling` 补位；
两题的证据继续保留，但**不计入通过数、也不出现在分母里**。

---

## 7. 剩余工作与已知限制

1. **两题已归档**：`b_l2_rms_norm`、`b_l3_group_norm` 在 `archive/`
   下，等有 >48 GB 卡或 evaluator 改为分块比较时再恢复；当前 slate 不含
   它们，任何通过率都不应把它们计入分母。
2. **conv2d 的 1e-4 容差与 muDNN TF32**：agent 若保持 muDNN 默认 TF32，
   精确 fp32 kernel 无法落在 1e-4 内；只有改用 muDNN 本身才可能复现
   TF32 舍入，而题目禁止。这是题面/容差的属性，需要在 harness 层决定是否
   在评测前统一关闭 mudnn TF32。
3. **反作弊在 MUSA 上恒过**：`check_result.py --forbid-cheating` 不构成
   证据——上游 `musa_backend` 没有实现 `detect_cheating`，基类直接返回
   `False`。对“实现里真的有 MUSA kernel”的检查来自
   `check_musa_submission.py`（AST 存在性门，不是语义证明）。详见
   [design.md](design.md) §4 第 3 条与 §10。
4. **运行后清理**：gold 还原会往 `work/submission/` 写标准答案。2026-11-16
   已清空远端 20 个 `work/submission/`；给 agent 用之前仍需重跑
   `prepare.sh`。

---

## 8. 正控完成标准（逐题核对）

每道题只有满足下面全部条件，才算“正控已验证”：

- [x] 参考提交在 MUSA SDK 5.2.0 + MTT S4000 + driver 5.2.0-server 上编译通过；
- [x] 5 次数值试验全部通过（`atol=rtol=1e-4`）——当前 slate 20 题全部通过；
- [x] `check_result.py --forbid-cheating` 通过（**注意：MUSA 后端恒返回
      `cheating=False`，这一项不构成证据**）；
- [x] CUDA API 门通过（`check_api_removal.sh`，报告里 `api_removal=pass`）；
- [x] MUSA kernel 结构门通过（`check_musa_submission.py`，20 份正控均 PASS）；
- [x] 报告中记录驱动、SDK、torch/torch_musa 版本、日期和提交 hash；
- [x] 本文件表格已更新（20 PASS，0 BLOCKED；归档 2 题另记）。

---

## 9. 报告规则

- 当前 slate 的 20 题全部写 **PASS**（正控已验证）。
- 归档的两题（`b_l2_rms_norm`、`b_l3_group_norm`）只在归档说明里写
  **BLOCKED (evaluator allclose OOM on 48 GB)**，不进入任何通过率分母。
- 通过率分母就是当前 slate 的 20 题；不要再维护“含受阻题”的旧口径。
- 项目自写正控通过的题，最多写成“判卷器已验证”；不能写成“上游 gold 通过”。
- 不允许把受阻题或未跑题写成“判分链路已验证”。
- 正控失败时先修题目/环境，不要改 agent 或模型参数。
- 本机 WSL 没有 MUSA 环境；所有 MUSA 通过结论均来自 §2 的租用 S4000 主机。

---

## 10. 参考实现来源

### 10.1 MKBench 自带的 MUSA 样例（上游 gold）

- 路径：`cuda_to_musa/tasks/<task>/gold/prompts/musa_new_model_*.py`
  （`leaky_relu`、`mse_loss` 两题）。
- 用途：确认 `torch_musa.utils.musa_extension.load_inline` 的参数、
  `__global__` 写法、`ModelNew` 的接口。
- **不能**把其他题的样例放进 agent 可见的 `work/`；`prepare.sh` 已用
  `remove_globs: prompts/musa_new_model_*.py` 全量删除 6 份样例。

### 10.2 MKBench 的 CUDA 样例（源侧，agent 可见）

- `work/prompts/cuda_model_*.py`：`add`、`layer_norm`、`leaky_relu`、
  `matmul_add`、`matmul_gelu`、`mse_loss`、`reduce_sum`。
- 用途：给 agent 看源侧语义和 CUDA 实现；迁移时按 MUSA API 改写。

### 10.3 `torch_musa` 官方文档与仓库

- 仓库：`https://github.com/MooreThreads/torch_musa`
- 用途：`torch.musa`、`torch_musa.utils.musa_extension` 的 API 语义；
  版本配套以 release notes 为准。

### 10.4 MUSA SDK 样例

- 摩尔线程开发者站 / MUSA SDK 镜像内的 samples：用于确认 `mcc` 编译选项、
  `musaMalloc`/`musaMemcpy`、`musaStream` 等 runtime API。
- 这些样例通常不是 MKBench 的提交格式，需要适配，不能直接当 gold。

---

## 11. 当前可执行的命令

```bash
# 1. 检查 pin 是否仍然有效（不联网时用 --offline）
python3 tools/check_pins.py --offline

# 2. 只做静态校验（无需 MUSA）
python3 tools/verify_task.py --parent cuda_to_musa/tasks

# 3. 确认 gold 没泄漏
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
find cuda_to_musa/tasks/b_l1_leaky_relu/work -name 'musa_new_model_*'
# 期望：无输出

# 4. 跑当前 slate 的全部 20 道已验证正控（需要 S4000 + torch_musa）
#    历史拆分：2026-11-16 的 musa_all18（前 18 题）+ musa_batch6（换题补位的 2 题）
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks \
  --only b_l1_leaky_relu --only b_l1_mse_loss --only b_l2_layer_norm \
  --only b_l1_relu --only b_l1_sigmoid --only b_l1_swish --only b_l1_softmax \
  --only b_l2_cumsum --only b_l2_sum_reduce --only b_l2_argmax \
  --only b_l2_gather --only b_l2_cross_entropy_loss \
  --only b_l2_cosine_similarity_loss \
  --only b_l3_standard_matmul --only b_l3_conv2d --only b_l3_gqa \
  --only b_l3_sdpa --only b_l3_matmul_gelu_softmax --only b_l3_kv_cached_attention \
  --only b_l3_conv2d_batch_norm_scaling \
  --label musa_all20 --report-dir reports/gold_sanity/musa_all20

# 5. 单独跑 kernel 结构与 API 门（可在任何有 Python 的机器上）
python3 shared/harness/check_musa_submission.py \
  cuda_to_musa/tasks/b_l1_leaky_relu/gold/prompts/musa_new_model_leaky_relu.py
python3 shared/harness/api_removal.py \
  --source-dir cuda_to_musa/tasks/b_l1_leaky_relu/gold/prompts/musa_new_model_leaky_relu.py \
  --source-regex 'torch\.cuda|\.cuda\(\)|cuda[A-Z]\w*\s*\(|#include\s*[<"]cuda|#include\s*[<"]cublas|#include\s*[<"]cudnn|#include\s*[<"]cufft|\bnvcc\b|\bcublas[A-Za-z0-9_]*\s*\(|\bcudnn[A-Za-z0-9_]*\s*\(|\bcufft[A-Za-z0-9_]*\s*\(|device\s*=\s*['\''"]cuda|\bCUDA_[A-Z0-9_]+|__CUDACC__'
# 期望：MUSA_SUBMISSION=PASS / API_REMOVAL=PASS
# 注意扫源码用 --source-regex；--symbol-regex 只用于二进制符号表。
# 题包自带的 harness/check_api_removal.sh 扫的是 work/submission/，
# 没有还原 gold 时会因目录不存在返回 ERROR，这是预期行为。
```

更多环境准备和负控步骤见 [RUNBOOK.md](../RUNBOOK.md)。