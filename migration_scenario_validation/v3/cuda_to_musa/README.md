# CUDA -> MUSA V3

V3 当前包含 3 个 **library_source**、1 个独立 held-out 任务，以及从 library_source
抽取、审核、发布的冻结组件库。

## Library sources

| task | level | domain | 覆盖内容 |
|---|---|---|---|
| `s1_conv2d_batch_norm` | L3 | convolution | conv2d tiling、per-channel 统计、BatchNorm affine、输出 scaling |
| `s2_matmul_gelu_softmax` | L3 | fused-matmul | GEMM tiling、exact GELU、行 softmax、数值稳定 |
| `s3_kv_cached_attention` | L3 | attention | QKV/cache 布局、scale、mask、decode attention |

三个任务都使用固定 MultiKernelBench `work/`，只在 `gold/submission/` 保留本题的
evaluator-only 目标实现。`shared/harness/agent_view.py` 会隐藏目标后端、替代目标
prompt 和 evaluator 基础设施；`build_history_corpus.py` 也使用同一过滤视图选取
context，因此抽取语料不含目标/NPU/backends 材料。

## 组件库

```text
v3/cuda_to_musa/library_generated/
v3/cuda_to_musa/library -> library_generated
```

当前 3 个组件：

```text
fused-convolution-training-mode-batch-normalization-1f26f93f
fused-affine-projection-exact-activation-row-11f387ee
decode-step-cached-key-attention-rebuilt-as-custom-01481b2e
```

`extract_transformation --stage verify` 返回 `status=ok`。

## 语料与模型调用

```text
history digest: edb8f59edfe73ac0c396111eb557fb78ff8718240a8b864bec21f363030fdf26
extract: 3/3
review: 3/3，均经过一次 rework
rework: 3/3 revised
finalize: 3/3 publish
model calls: 176
```

## Held-out

```text
h1_grouped_query_attention    L3   grouped-query attention
```

held-out 与 library_source 使用不同算子契约；`gold/submission/` 只在 evaluator 侧。
`task.yaml` 的提交路径已改为工作区根目录下的 `submission/`，避免嵌套 `work/`。

## Direct / Method 配对

```text
direct  h1_direct_v2   pass  414.9s  33 model calls
method  h1_method      pass  349.9s  31 model calls  components=1
```

`bench.py compare`：

```text
TASKS 1  default_pass=1  method_pass=1  both=1
BUNDLES attempts=1 usable=1 components=1
```

method 使用冻结库 `v3/cuda_to_musa/library`，远端 bundle 已同步到
`outputs/full_library`，没有重新抽取组件。

## 下一步

扩展 held-out 任务并做多题统计。
