# Scenario B — NVIDIA CUDA → 摩尔线程 MUSA

## 1. 这个场景在测什么

给 agent 一个**上游算子评测仓库的固定快照**和一个算子契约，要求它用 MUSA C
写出能在摩尔线程 MTT S4000 上编译、运行、数值正确的实现。源侧语义来自上游
PyTorch `reference/` 的 `Model` / `get_inputs` / `get_init_inputs`，以及
MultiKernelBench 自带的 `prompts/cuda_model_*.py`。

判分不靠“看代码像不像”，而是调用**上游自己的 evaluator**：
`eval_single_runner.py --language musa` 在 `musa:0` 上导入提交、构建 MUSA
扩展、跑参考与 `ModelNew` 的五次数值比对，再做 100 次计时。我们只在其上补
统一的 API 清除门、kernel 结构门和结果解析。

- 源：CUDA/PyTorch 算子语义（MKBench 的 CUDA model + PyTorch reference）。
- 目标：MTT S4000，MUSA SDK 5.2.0，`mcc` 编译器，`torch_musa`。
- gold：MKBench 上游自带的 6 份 MUSA 样例（`prompts/musa_new_model_*.py`）。
  其中只有 2 份（`leaky_relu`、`mse_loss`）与本仓库的算子契约对得上，可作为
  上游正控；`layer_norm` 样例写的是 CUDA prompt 的二维契约，与 evaluator
  使用的四维 reference 不一致，已在 S4000 上实测 `compiled=True,
  correct=False`，不能当正控。该题与其余 15 道没有可用上游样例的题各有一份
  项目自写的正控（`gold_authored/`，见 §4 第 7 条）。20 题**全部已在真机
  验证**。原 slate 的 `b_l2_rms_norm`、`b_l3_group_norm` 因判卷器
  `allclose` 在 48 GB 卡上 OOM，已于 2026-11-16 连同证据移入
  `archive/cuda_to_musa_blocked_oom/`，由 `b_l2_cosine_similarity_loss`、
  `b_l3_conv2d_batch_norm_scaling` 补位并实测通过（§9）。
  其余样例作为目标语言参考 **全部**从 agent 可见树移除，详见 §5。
- 判分：上游 compile / correctness / anti-cheat + CUDA API 残留门 +
  MUSA kernel 结构门。

与已归档的 `cuda_to_ascend` 场景相比，这个场景的真正难点不是“换一套编程
模型”，而是**在同一套 CUDA-like 编程模型内做 API 与运行时替换**：MUSA
保留了 `__global__`、`threadIdx`、`__shared__`、`<<<...>>>`，所以迁移的
核心是 `cuda*` → `musa*`、`torch.cuda` → `torch.musa`、`nvcc` → `mcc`、
以及 `torch_musa.utils.musa_extension.load_inline` 的构建路径。

## 2. 任务包结构

与场景 A 相同，是 recipe：

```text
cuda_to_musa/tasks/<task_id>/
├── task.yaml          # 题目、提交路径、上游 judge 命令、门禁
├── provenance.json    # repo / commit / license / 可见文件 / gold 文件
├── prepare.sh         # 克隆固定 commit → work/，隔离全部 MUSA 样例
├── gold/              # evaluator-only 上游样例（仅 leaky_relu / mse_loss）
├── gold_authored/     # 项目自写正控（18 题，evaluator-only）
├── upstream_nonconforming/  # 契约不符的上游 layer_norm 样例（仅作证据）
├── harness/           # run_task.py / check_result.py /
│                      # check_api_removal.sh / check_musa_submission.py
└── README.md
```

`layout: repo`：`work/` 是完整的 pinned 上游快照。evaluator、测试数据和
反作弊器都在原位；隐藏测试在 `{build}` 下的独立目录运行，且 `work/` 会在
每次 `prepare.sh` 时重置。

## 3. 题目清单（20 题）

全部来自 MultiKernelBench 的 `reference/` 算子契约；提交物统一是
`work/submission/<op>_submission.py`，判分入口统一是
`eval_single_runner.py --language musa --op <op>`。

| 级别 | 任务 | 上游算子目录 | 难度 | gold |
|---|---|---|---|---|
| L1 | `b_l1_leaky_relu` | `activation/leaky_relu.py` | easy | **上游 MUSA 样例** |
| L1 | `b_l1_mse_loss` | `loss/mse_loss.py` | easy | **上游 MUSA 样例** |
| L1 | `b_l1_relu` | `activation/relu.py` | easy | 自写正控 ✅ |
| L1 | `b_l1_sigmoid` | `activation/sigmoid.py` | easy | 自写正控 ✅ |
| L1 | `b_l1_softmax` | `activation/softmax.py` | easy | 自写正控 ✅ |
| L1 | `b_l1_swish` | `activation/swish.py` | easy | 自写正控 ✅ |
| L2 | `b_l2_layer_norm` | `normalization/layer_norm.py` | medium | 自写正控 ✅（上游样例无效，见 §5.1） |
| L2 | `b_l2_cosine_similarity_loss` | `loss/cosine_similarity_loss.py` | medium | 自写正控 ✅ |
| L2 | `b_l2_sum_reduce` | `reduce/sum_reduction_over_a_dimension.py` | medium | 自写正控 ✅ |
| L2 | `b_l2_argmax` | `index/argmax_over_a_dimension.py` | medium | 自写正控 ✅ |
| L2 | `b_l2_gather` | `index/gather.py` | medium | 自写正控 ✅ |
| L2 | `b_l2_cross_entropy_loss` | `loss/cross_entropy_loss.py` | medium | 自写正控 ✅ |
| L2 | `b_l2_cumsum` | `math/cumsum.py` | medium | 自写正控 ✅ |
| L3 | `b_l3_standard_matmul` | `matmul/standard_matrix_multiplication.py` | hard | 自写正控 ✅ |
| L3 | `b_l3_conv2d` | `convolution/conv_standard_2d_square_input_square_kernel.py` | hard | 自写正控 ✅（muDNN TF32，见 §4 第 7 条） |
| L3 | `b_l3_gqa` | `attention/group_query_attention.py` | hard | 自写正控 ✅ |
| L3 | `b_l3_sdpa` | `attention/scaled_dot_product_attention.py` | hard | 自写正控 ✅ |
| L3 | `b_l3_matmul_gelu_softmax` | `fuse/matmul_gelu_softmax.py` | hard | 自写正控 ✅ |
| L3 | `b_l3_conv2d_batch_norm_scaling` | `fuse/conv2d_batch_norm_scaling.py` | hard | 自写正控 ✅ |
| L3 | `b_l3_kv_cached_attention` | `attention/kv_cached_attention_inference.py` | hard | 自写正控 ✅ |

L1/L2/L3 是本仓库的课程难度标定，不是上游目录结构。

## 4. 判分设计

1. **编译门**：上游 evaluator 执行提交里的
   `torch_musa.utils.musa_extension.load_inline(..., musa_sources=...)`，
   调用 `mcc` 构建扩展。`check_result.py --require-compiled` 再判一次
   `result.json` 的编译状态。
2. **正确性门**：上游对每个算子跑 PyTorch reference，用
   `torch.allclose(atol=1e-4, rtol=1e-4)` 比对 5 次试验；
   `--require-correct` 要求全部通过。
3. **反作弊门（在 MUSA 上实际为空）**：上游有
   `utils/cheating_detection.py`，`check_result.py --forbid-cheating`
   要求结果中 `cheating` 为假。但 pinned commit 的
   `backends/musa_backend.py` 没有覆写 `Backend.detect_cheating`，基类
   直接返回 `(False, None)`，所以 MUSA 提交的 `cheating` 永远为假，
   这条门**无法**区分“真 kernel”和“PyTorch 实现”。已在
   S4000 上实测：上游 `mse_loss` gold 的 `torch.mean(...)` 若直接调用
   检测器会被判 `cheating=True`，但 evaluator 报告 `cheating=False`。
   因此本场景把“实现必须真的是 MUSA kernel”的责任交给第 5 条门；
   报告里不得把上游反作弊门当作有效证据。
4. **API 清除门**：在 `work/submission/` 上扫 CUDA API 残留：
   `torch.cuda`、`.cuda()`、`cudaXxx(`、`#include <cuda...>`、
   `<cublas...>`/`<cudnn...>`/`<cufft...>`、`nvcc`、
   `cublasXxx(`/`cudnnXxx(`/`cufftXxx(`、`device='cuda'`、
   `CUDA_*` 宏、`__CUDACC__`。
   **刻意不扫** `__global__`、`threadIdx`、`__shared__`、`<<<...>>>`：
   MUSA 与 CUDA 源级兼容，把这些当“CUDA 残留”会误杀正确实现。
5. **MUSA kernel 结构门**：`shared/harness/check_musa_submission.py`
   用 AST 检查提交是否真的定义了自定义 kernel：
   - 源码中必须出现 `load_inline` + `musa_sources`、`__global__`、`<<<`；
   - `class ModelNew.forward` 必须调用由 `load_inline(...)` 赋值得到的扩展；
   - 返回值必须派生自该调用结果；
   - `ModelNew` 内不得引用 reference 的 `Model`。
   这条门弥补“反作弊器只判结果、不管实现”的缺口。它不是语义证明：
   上游 `mse_loss` 的 gold 本身就在 kernel 输出外套了 `torch.mean`，
   所以这道门只要求 kernel 存在且被调用，不禁止少量后处理。
6. **gold 隔离**：`leaky_relu`、`mse_loss` 有契约匹配的上游 MUSA 样例，
   分别复制到各自题包的 `gold/`。`layer_norm` 的上游样例与本题契约不符
   （见 §5.1），不进入 `gold/`，原文件保留在
   `tasks/b_l2_layer_norm/upstream_nonconforming/` 作为证据。关键修正：
   **每个题包的 `prepare.sh` 都删除 `work/prompts/musa_new_model_*.py`
   全量 6 个文件**，而不仅是本题那一个。原因见 §5。
7. **项目自写正控**：18 道没有可用上游样例的题各写了一份
   `gold_authored/<op_name>_submission.py`，由 `gold_sanity.py` 在无上游
   gold 时自动还原（`layer_norm` 是其中第一份）。它们只用于证明“判卷器会
   接受正确实现”，报告里必须标成 `project-authored`，不能算作上游 gold。
   三条从真机失败中总结出的约定：
   - **文件名必须等于 `op_name`**（`<op_name>_submission.py`）：evaluator
     按 op 名找文件，而 `gold_sanity.py` 会复制 `gold_authored/` 里所有
     `*.py`，所以改名后要删掉旧文件；
   - MUSA 的 `data_ptr<int64_t>()` 是 `long*`，kernel 形参必须写
     `const int64_t*`；
   - 参考端可能默认启用 TF32：`b_l3_conv2d` 的 `nn.Conv2d` 走 muDNN，
     而 `torch.backends.mudnn.allow_tf32` 默认为 True，参考值因此偏离真
     fp32 约 5e-4，超过 `atol=rtol=1e-4`。该题正控在 import 时把它关掉，
     使比较对的是 fp32 卷积；复现数据见
     `reports/gold_sanity/conv2d_tf32/`。

## 5. gold 隔离与“目标语言泄漏”

MKBench 的 6 份 MUSA 样例是同一套 API 的完整示范：

```text
prompts/musa_new_model_add.py
prompts/musa_new_model_layer_norm.py
prompts/musa_new_model_leaky_relu.py
prompts/musa_new_model_matmul_add.py
prompts/musa_new_model_mse_loss.py
prompts/musa_new_model_reduce_sum.py
```

如果只删除本题对应的样例，其余 5 份仍留在 `work/prompts/`，agent 就能
直接照抄 `load_inline(musa_sources=...)` 的构建方式和 `__global__` 写法。
对本 benchmark 来说，这等于把“目标平台适配”这一半工作送掉。

因此 `cuda_to_musa/slate.yaml` 的默认 `prepare.remove_globs` 是：

```yaml
prepare:
  remove_globs:
    - prompts/musa_new_model_*.py
```

`prepare.sh` 在把本题 gold 复制到 `gold/` 之后，用一条 glob 删除
`work/prompts/musa_new_model_*.py`。`leaky_relu`、`mse_loss` 两题验证过：
`work/` 中无任何 `musa_new_model_*`，`gold/` 中只有本题那份；
`layer_norm` 的 `work/` 同样为零样例，其上游样例因契约不符不进入 `gold/`。

### 5.1 上游 `layer_norm` 样例为什么不能当 gold

pinned commit 里 `layer_norm` 存在两套契约：

| 文件 | 输入契约 |
|---|---|
| `prompts/cuda_model_layer_norm.py` | `x = (16384, 1024)`，`normalized_shape = 1024` |
| `reference/normalization/layer_norm.py`（evaluator 使用） | `x = (64, 64, 256, 256)`，`normalized_shape = (64, 256, 256)` |

上游 MUSA 样例按二维写（`rows = x.size(0)`, `cols = x.size(1)`），在四维
reference 下只写入 `64 x 64` 个值，其余保持 `zeros_like`。S4000 实测为
`compiled=True, correct=False, cheating=False`，因此它不是“环境问题”，
而是样例本身与 evaluator 契约不一致。该样例已移到
`tasks/b_l2_layer_norm/upstream_nonconforming/`，不参与任何正控统计。

## 6. 为什么选 MultiKernelBench

| 仓库 | 作用 | 为什么适合 |
|---|---|---|
| [MultiKernelBench](https://github.com/wzzll123/MultiKernelBench)（MIT） | 20 题 | 固定 commit 下同时提供 CUDA model、PyTorch reference、MUSA 样例、反作弊器和 `--language musa` evaluator；提交格式统一为一个 Python 文件，判分可复现 |

固定 commit：`460a972c9be7ce18035984321d38b910e27df95f`（MIT）。

## 7. 评估过但未入选

| 候选 | 未入选原因 |
|---|---|
| CANN Bench | 已随 `archive/cuda_to_ascend/` 归档；当前没有 Ascend 环境，且与 MUSA 目标无关 |
| MKBench `add` / `matmul_add` / `reduce_sum` | 有 MUSA 样例，但 pinned commit 的 `reference/` 下没有同名算子契约，evaluator 无法给出可信正确性结论 |
| 自己写 CUDA kernel 再要求迁移 | 违反“用已有 benchmark/repo”，会变成自造 gold |
| Triton 源 | 上游 MUSA 侧没有对应的 Triton→MUSA 判分入口；本题集只覆盖 CUDA-like 源 |

## 8. 环境

见 [`../env/version_matrix.yaml`](../env/version_matrix.yaml) 与
[`../env/Dockerfile.musa`](../env/Dockerfile.musa)。要点：

- 基础镜像用摩尔线程公开的 MUSA SDK 5.2.0 镜像（`mthreads/musa`，
  由构建者传入具体 tag；仓库不 vendored 厂商镜像）。
- Python 侧固定 `torch==2.11.0.post1` + `torch_musa==2.11.0.post1`
  （该 release 声明兼容 MUSA SDK 5.1/5.2），Python 3.10 / Ubuntu 22.04，
  与 MultiKernelBench 的上游建议一致。实测主机上的 torch_musa 构建号为
  `2.11.0.post1+b431668`。
  如果目标镜像使用 PyTorch 2.9 线，可换 `torch==2.9.1` +
  `torch_musa==2.9.1.post1`，但必须重新 smoke。
- 需要真实 MTT S4000；`torch_musa` 无 CPU 等价路径。
- `musaInfo` 应能列出 S4000 与 SDK 5.2.0；驱动版本必须与 SDK 配套。

## 9. 验证到什么程度（2026-11-16 实测）

开发机是 WSL，**没有 MUSA 工具链、没有 `torch_musa`、没有 S4000**。所有
MUSA 执行结论来自一台租用的 MTT S4000 主机，经 SSH 在仓库副本上运行；
详细环境见 [`positive_controls.md`](positive_controls.md) §2 和
`reports/gold_sanity/musa_environment.txt`。

已做：

- 20 个 MUSA 包静态校验 `verify_task.py` PASS；`check_pins.py --offline`
  `RESULT=PASS`（`judge_only=18`，`layer_norm` 无上游 gold 声明）；
- 所有 `prepare.sh` 实际物化，并通过 glob 删除 6 份上游 MUSA 样例；
- 真机正控（首跑，逐题）：
  - `b_l1_leaky_relu`（上游 gold）**PASS** 166.8s；
  - `b_l1_mse_loss`（上游 gold）**PASS** 185.8s；
  - `b_l2_layer_norm`（项目自写正控）**PASS** 90.9s；
  - `b_l2_layer_norm` 的上游样例 **FAIL**（`compiled=True,
    correct=False`，契约不符，见 §5.1）；
- 真机正控（最终题包，三题合并）：`musa_gold_final` **PASS 3/3**——
  leaky_relu 98.2s、mse_loss 121.2s、layer_norm 25.0s，
  `SUMMARY pass=3 fail=0 skip=0 error=0`，`GOLD_SANITY_RC=0`。
  这次运行对应“所有隐藏测试命令改用 `python3`”之后的题包；耗时低于首跑
  是因为 `torch_extensions` 编译缓存已热；
- 真机正控（全量）：在最终题包上分四批补完其余 15 题，`b_l3_conv2d` 另在
  修掉 TF32 问题后单独重跑：

  | 批次 | 范围 | 结果 |
  |---|---|---|
  | `musa_batch1` | relu / sigmoid / swish | **3/3 PASS** |
  | `musa_batch2` | softmax、cumsum、argmax、gather、CE、sum_reduce、rms_norm | 2/7（4 个正控缺陷已修，1 个 OOM） |
  | `musa_batch3` | conv2d、gqa、group_norm、kv、mulf、sdpa、std_matmul | 0/7（6 个缺陷已修，1 个 OOM） |
  | `musa_batch4` | 上述 L2 四题 + 六个 L3 题 | **9/10**（conv2d 因 muDNN TF32 失败） |
  | `musa_batch5` | conv2d（关闭 mudnn TF32 后重跑） | **1/1 PASS** 42.6s |

  合计 **18/18 已验证**（这批覆盖当时 slate 的全部 18 题：2 上游 gold +
  16 项目自写）。逐题状态与每批修掉的题目包缺陷见
  [`positive_controls.md`](positive_controls.md) §3/§5；
- 真机正控（换题后补位两题）：`musa_batch6` **2/2 PASS**——cosine 79.1s、
  conv2d+BN 105.9s，`SUMMARY pass=2 fail=0 skip=0 error=0`。原
  `b_l2_rms_norm`、`b_l3_group_norm` 已归档，不计入；当前 slate
  合计 **20/20 已验证**（2 上游 gold + 18 项目自写）；
- 真机正控（最终合并运行）：2026-11-16 用一条命令跑全部 18 题，
  `musa_all18` 返回 `SUMMARY pass=18 fail=0 skip=0 error=0`、
  `GOLD_SANITY_RC=0`（20.7 分钟），逐题 `tests=pass`、`api_removal=pass`、
  `MUSA_SUBMISSION=PASS`（20 题的最终拆分是这一批 18 题 + `musa_batch6`
  的 2 题）；
- 所有 PASS 都经过 `mcc` 编译、上游 5 次数值比对、反作弊、
  `check_result.py`、CUDA API 门和 `check_musa_submission.py`；
- 报告：`reports/gold_sanity/{musa_all18,musa_batch6,musa_gold_final,musa_smoke,musa_gold2,musa_authored,musa_batch1,musa_batch2,musa_batch3,musa_batch4,musa_batch5}/`。

未做 / 受阻：

- `b_l2_rms_norm`、`b_l3_group_norm` 的 8.59 GB fp32 张量使判卷器
  `torch.allclose` 在 47.90 GB 卡上 OOM（42 GiB allocated 仍要 8 GiB；
  原地别名提交也要 44 GiB）。这两题已归档到
  `archive/cuda_to_musa_blocked_oom/`，**不在当前 slate 里、不计入通过率**；
  证据与复现脚本仍在 `reports/gold_sanity/musa_allclose_oom/`；
- MUSA 侧 P2 agent 小样本（4 题 × 3 次）未开始；
- 性能测量（本场景不进 pass/fail）；
- `env/Dockerfile.musa` 尚未实际构建；上述执行是直接在租用主机上做的。

目标环境推荐顺序：

```bash
# 1. 物化
bash cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh

# 2. 静态校验（gold 未泄漏、schema 完整）
python3 tools/verify_task.py --parent cuda_to_musa/tasks
python3 tools/check_pins.py --offline

# 3. 在 MUSA 主机上跑当前 20 道已验证正控（完整 --only 列表见 RUNBOOK §4.1）
python3 tools/gold_sanity.py --parent cuda_to_musa/tasks \
  --only b_l1_leaky_relu --only b_l1_mse_loss --only b_l2_layer_norm \
  --only b_l1_relu --only b_l1_sigmoid --only b_l1_swish --only b_l1_softmax \
  --only b_l2_cumsum --only b_l2_sum_reduce --only b_l2_argmax \
  --only b_l2_gather --only b_l2_cross_entropy_loss \
  --only b_l2_cosine_similarity_loss \
  --only b_l3_standard_matmul --only b_l3_conv2d --only b_l3_gqa \
  --only b_l3_sdpa --only b_l3_matmul_gelu_softmax --only b_l3_kv_cached_attention \
  --only b_l3_conv2d_batch_norm_scaling \
  --label musa_all20

# 4. 再跑 agent / 负控
```

## 10. 已知风险

- **硬件依赖强**：S4000 + MUSA SDK 5.2.0 + 配套驱动的组合是固定的；
  换卡或换 SDK 需要重新跑 smoke。
- **torch_musa 版本跟随 PyTorch**：`torch` 与 `torch_musa` 的 minor 版本
  必须配套；镜像里不要用 `pip install -U` 漂移。
- **判卷器内存上限决定选题**：`b_l2_rms_norm`、`b_l3_group_norm` 的
  `torch.allclose` 在 48 GB 卡上放不下 8.59 GB 张量（详见
  `reports/gold_sanity/musa_allclose_oom/`），两题已归档，不再出现在
  slate 里。新增题目时先估算 evaluator 的比较内存；大于约 40 GB 的
  张量在这类卡上不可判。当前 20 题的分母就是 20，没有 BLOCKED 项。
- **conv2d 的 TF32 容差**：`b_l3_conv2d` 的参考 `nn.Conv2d` 默认走 muDNN
  TF32，与真 fp32 差约 5e-4，超过 1e-4 容差。正控通过关闭
  `torch.backends.mudnn.allow_tf32` 解决；agent 若不关，即使 kernel 精确
  也会数值失败。这不影响 `nn.Linear`（`torch.backends.musa.matmul`
  默认已是 TF32-off），但换 SDK 版本后需要重新确认默认值。
- **kernel 结构门不是语义反作弊**：它检查 kernel 存在并被调用，但不禁止
  在 kernel 输出上做 PyTorch 后处理（上游 `mse_loss` gold 自己就这么写）。
  更严格的做法是补一个针对“算子主体是否在 kernel 内完成”的检测器，
  目前没有做，不应在报告里声称已有。
- **上游反作弊门在 MUSA 上不起作用**：`musa_backend` 未实现
  `detect_cheating`，所以 `check_result.py --forbid-cheating` 恒过。
  当前真正拦“没有 kernel”的只有 `check_musa_submission.py` 的 AST 存在性
  检查；它也不是语义证明（见上一条）。报告里不能把“cheating=False”
  写成反作弊已验证。
- **性能不进 pass/fail**：上游会做 100 次计时，但本场景只判编译与数值；
  若要加性能门，必须固定硬件、SDK 和驱动后单独设计。
- **CUDA API 正则的边界**：`cuda[A-Z]\w*\s*\(` 会匹配 `cudaMalloc(` 等
  runtime API，但不会匹配 `musaMalloc(`；若上游样例里出现合法的
  “CUDA 兼容层”包装，应按实际代码调整正则，而不是关掉整条门。