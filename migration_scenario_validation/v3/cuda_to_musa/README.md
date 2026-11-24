# CUDA -> MUSA V3

当前只构建了 **library_source** 阶段，用于后续抽取冻结组件库；还没有 held-out
任务，也没有开始 direct/method 配对。

## 任务

| task | level | domain | 覆盖面 |
|---|---|---|---|
| `s1_conv2d_batch_norm` | L3 | convolution | conv2d tiling、BatchNorm 均值/方差、affine scaling、输出布局 |
| `s2_matmul_gelu_softmax` | L3 | fused-matmul | GEMM tiling、GELU、行 softmax、数值稳定 |
| `s3_kv_cached_attention` | L3 | attention | QKV、KV cache、scale、mask、softmax |

三个任务都来自 pinned MultiKernelBench 算子契约，`work/` 是固定上游快照，
`gold/submission/` 是评测侧目标实现，不会进入 agent 可见目录。

## 状态

```text
verify_task: PASS tasks=3
lint_dataset: PASS
```

三个 library_source 的 remote gold 正控均已通过：

```text
s1_conv2d_batch_norm       tests=pass  api_removal=pass
s2_matmul_gelu_softmax     tests=pass  api_removal=pass
s3_kv_cached_attention     tests=pass  api_removal=pass
```

已生成组件抽取语料：

```text
v3/cuda_to_musa/history/
  spec.yaml
  examples/s1_conv2d_batch_norm/
  examples/s2_matmul_gelu_softmax/
  examples/s3_kv_cached_attention/
  lock.json
```

语料校验：

```text
build_history_corpus --verify: status=ok
examples=3 focus_files=3 context_files=33 focus_units=12 context_units=262
```

组件库已生成：

```text
v3/cuda_to_musa/library_generated/
  manifest.json
  INDEX.md
  SELECTION.md
  components/<bundle_id>/
v3/cuda_to_musa/library -> library_generated   # symlink used by task.yaml
```

当前为 3 个组件，`extract_transformation --stage verify` 返回 `status=ok`。

## 后续

1. 构造与 library_source 独立的 held-out 任务；
2. 用 `cuda_to_musa_v3` scenario 跑 direct/method 配对；
3. 汇总结果并写 CUDA → MUSA V3 报告。
