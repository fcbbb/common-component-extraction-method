# Task slate: cuda_to_ascend

| # | Task ID | Level | Fit | Counted | Source kind | Task | Upstream |
|---:|---|---|---|---|---|---|---|
| 1 | `b_l1_exp` | L1 | B | yes | upstream-kernel-benchmark | Exp: CUDA elementwise kernel -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 2 | `b_l1_swi_glu` | L1 | B | yes | upstream-kernel-benchmark | SwiGLU: CUDA fused activation -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 3 | `b_l1_mk_leaky_relu` | L1 | B | yes | upstream-kernel-benchmark | MultiKernelBench leaky_relu: CUDA model -> AscendC submission | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 4 | `b_l1_mk_mse_loss` | L1 | B | yes | upstream-kernel-benchmark | MultiKernelBench mse_loss: CUDA model -> AscendC submission | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 5 | `b_l1_mk_sum_reduction` | L1 | B | yes | upstream-kernel-benchmark | MultiKernelBench sum reduction over a dimension | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 6 | `b_l1_softmax` | L1 | B | yes | upstream-kernel-benchmark | Softmax: CUDA row softmax -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 7 | `b_l2_mk_layer_norm` | L2 | B | yes | upstream-kernel-benchmark | MultiKernelBench layer_norm: CUDA model -> AscendC submission | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 8 | `b_l2_rms_norm` | L2 | B | yes | upstream-kernel-benchmark | RMSNorm: CUDA kernel -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 9 | `b_l2_gather` | L2 | B | yes | upstream-kernel-benchmark | Gather: CUDA index kernel -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 10 | `b_l2_cross_entropy_loss` | L2 | B | yes | upstream-kernel-benchmark | CrossEntropyLoss: CUDA fused loss -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 11 | `b_l2_arg_max` | L2 | B | yes | upstream-kernel-benchmark | ArgMax: CUDA arg-reduction -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 12 | `b_l2_top_k` | L2 | B | yes | upstream-kernel-benchmark | TopK: CUDA selection kernel -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 13 | `b_l2_mk_standard_matmul` | L2 | B | yes | upstream-kernel-benchmark | MultiKernelBench standard matrix multiplication | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 14 | `b_l2_mk_cumsum` | L2 | B | yes | upstream-kernel-benchmark | MultiKernelBench cumsum: CUDA scan -> AscendC submission | https://github.com/wzzll123/MultiKernelBench.git @ `460a972c9be7` |
| 15 | `b_l3_conv_2d` | L3 | C | yes | upstream-kernel-benchmark | Conv2D: cuDNN-style convolution -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 16 | `b_l3_nms` | L3 | C | yes | upstream-kernel-benchmark | NMS: CUDA non-max suppression -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 17 | `b_l3_grouped_matmul` | L3 | C | yes | upstream-kernel-benchmark | GroupedMatmul: MoE grouped GEMM -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 18 | `b_l3_gqa` | L3 | C | yes | upstream-kernel-benchmark | GQA: grouped-query attention decode -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 19 | `b_l3_lstm` | L3 | C | yes | upstream-kernel-benchmark | LSTM: cuDNN RNN cell -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |
| 20 | `b_l3_selective_scan` | L3 | C | yes | upstream-kernel-benchmark | Selective scan: Mamba S6 -> Ascend C | https://gitcode.com/cann/cann-bench.git @ `53ea611a1b88` |

Core tasks: **20**; total packages: **20**.

