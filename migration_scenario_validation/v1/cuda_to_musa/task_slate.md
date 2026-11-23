# Task slate: cuda_to_musa

| # | Task ID | Level | Fit | Counted | Source kind | Task | Upstream |
|---:|---|---|---|---|---|---|---|
| 1 | `b_l1_leaky_relu` | L1 | B | yes | upstream-kernel-benchmark | MultiKernelBench leaky_relu: CUDA model -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 2 | `b_l1_mse_loss` | L1 | B | yes | upstream-kernel-benchmark | MultiKernelBench mse_loss: CUDA model -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 3 | `b_l1_relu` | L1 | B | yes | upstream-kernel-benchmark | ReLU: CUDA elementwise semantics -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 4 | `b_l1_sigmoid` | L1 | B | yes | upstream-kernel-benchmark | Sigmoid: CUDA elementwise semantics -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 5 | `b_l1_softmax` | L1 | B | yes | upstream-kernel-benchmark | Softmax: CUDA row softmax -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 6 | `b_l1_swish` | L1 | B | yes | upstream-kernel-benchmark | Swish: CUDA elementwise semantics -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 7 | `b_l2_layer_norm` | L2 | B | yes | upstream-kernel-benchmark | MultiKernelBench layer_norm: CUDA model -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 8 | `b_l2_cosine_similarity_loss` | L2 | B | yes | upstream-kernel-benchmark | Cosine similarity loss: CUDA norms + dot + mean -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 9 | `b_l2_sum_reduce` | L2 | B | yes | upstream-kernel-benchmark | Sum reduction over a dimension: CUDA reduce -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 10 | `b_l2_argmax` | L2 | B | yes | upstream-kernel-benchmark | ArgMax over a dimension: CUDA arg-reduction -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 11 | `b_l2_gather` | L2 | B | yes | upstream-kernel-benchmark | Gather: CUDA index kernel -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 12 | `b_l2_cross_entropy_loss` | L2 | B | yes | upstream-kernel-benchmark | CrossEntropyLoss: CUDA fused loss -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 13 | `b_l2_cumsum` | L2 | B | yes | upstream-kernel-benchmark | Cumsum: CUDA scan -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 14 | `b_l3_standard_matmul` | L3 | B | yes | upstream-kernel-benchmark | Standard matmul: CUDA GEMM -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 15 | `b_l3_conv2d` | L3 | B | yes | upstream-kernel-benchmark | Conv2D: cuDNN-style convolution -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 16 | `b_l3_gqa` | L3 | B | yes | upstream-kernel-benchmark | GQA: grouped-query attention -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 17 | `b_l3_sdpa` | L3 | B | yes | upstream-kernel-benchmark | Scaled dot-product attention -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 18 | `b_l3_matmul_gelu_softmax` | L3 | B | yes | upstream-kernel-benchmark | Fused matmul + GELU + softmax -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 19 | `b_l3_conv2d_batch_norm_scaling` | L3 | B | yes | upstream-kernel-benchmark | Conv2d + BatchNorm2d (batch stats) + scale: fused CUDA model -> MUSA kernels | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 20 | `b_l3_kv_cached_attention` | L3 | B | yes | upstream-kernel-benchmark | KV-cached attention inference -> MUSA kernel | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |

Core tasks: **20**; total packages: **20**.

