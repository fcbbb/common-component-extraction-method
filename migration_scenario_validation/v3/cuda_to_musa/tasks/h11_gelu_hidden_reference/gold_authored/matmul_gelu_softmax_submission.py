"""Project-authored MUSA positive control for ``b_l3_matmul_gelu_softmax``.

Evaluator-only.  Matches ``Linear(8192, 8192) -> F.gelu (exact erf) ->
softmax(dim=1)`` on a (1024, 8192) input.  The tiled kernel computes
``x @ W^T + b``; the second kernel applies GELU and the row softmax.
Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

fused_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

#define TILE 16

__device__ __forceinline__ float gelu_exact(float v) {
    return 0.5f * v * (1.0f + erff(v * 0.7071067811865476f));
}

__global__ void matmul_nt_bias_kernel(const float* __restrict__ A,
                                      const float* __restrict__ W,
                                      const float* __restrict__ bias,
                                      float* __restrict__ C,
                                      int M, int N, int K) {
    __shared__ float As[TILE][TILE];
    __shared__ float Bs[TILE][TILE];

    const int row = blockIdx.y * TILE + threadIdx.y;
    const int col = blockIdx.x * TILE + threadIdx.x;

    float acc = 0.0f;
    for (int k0 = 0; k0 < K; k0 += TILE) {
        As[threadIdx.y][threadIdx.x] =
            (row < M && k0 + threadIdx.x < K) ? A[row * K + k0 + threadIdx.x] : 0.0f;
        Bs[threadIdx.y][threadIdx.x] =
            (static_cast<int>(blockIdx.x) * TILE + threadIdx.y < N &&
             k0 + threadIdx.x < K)
                ? W[(static_cast<int>(blockIdx.x) * TILE + threadIdx.y) * K +
                    k0 + threadIdx.x]
                : 0.0f;
        __syncthreads();
        #pragma unroll
        for (int k = 0; k < TILE; ++k) {
            acc += As[threadIdx.y][k] * Bs[threadIdx.x][k];
        }
        __syncthreads();
    }
    if (row < M && col < N) {
        C[row * N + col] = acc + bias[col];
    }
}

__global__ void gelu_softmax_kernel(const float* __restrict__ x,
                                    float* __restrict__ out,
                                    int cols) {
    const int row = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];
    const float* xr = x + static_cast<long long>(row) * cols;
    float* orow = out + static_cast<long long>(row) * cols;

    float m = -INFINITY;
    for (int i = tid; i < cols; i += nthreads) {
        m = fmaxf(m, gelu_exact(xr[i]));
    }
    scratch[tid] = m;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] = fmaxf(scratch[tid], scratch[tid + stride]);
        }
        __syncthreads();
    }
    const float mx = scratch[0];
    __syncthreads();

    float sum = 0.0f;
    for (int i = tid; i < cols; i += nthreads) {
        sum += expf(gelu_exact(xr[i]) - mx);
    }
    scratch[tid] = sum;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    const float inv = 1.0f / scratch[0];

    for (int i = tid; i < cols; i += nthreads) {
        orow[i] = expf(gelu_exact(xr[i]) - mx) * inv;
    }
}

torch::Tensor matmul_gelu_softmax_musa(torch::Tensor x, torch::Tensor weight,
                                       torch::Tensor bias) {
    auto xc = x.contiguous();
    auto wc = weight.contiguous();
    auto bc = bias.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "expected float32");
    TORCH_CHECK(xc.dim() == 2 && wc.dim() == 2, "expected 2-D input and weight");
    TORCH_CHECK(xc.size(1) == wc.size(1), "feature mismatch");
    const int M = static_cast<int>(xc.size(0));
    const int K = static_cast<int>(xc.size(1));
    const int N = static_cast<int>(wc.size(0));
    TORCH_CHECK(bc.numel() == N, "bias size mismatch");

    auto y = torch::empty({M, N}, xc.options());
    dim3 block(TILE, TILE);
    dim3 grid((N + TILE - 1) / TILE, (M + TILE - 1) / TILE);
    matmul_nt_bias_kernel<<<grid, block>>>(
        xc.data_ptr<float>(), wc.data_ptr<float>(), bc.data_ptr<float>(),
        y.data_ptr<float>(), M, N, K);

    auto out = torch::empty({M, N}, xc.options());
    gelu_softmax_kernel<<<M, 256>>>(
        y.data_ptr<float>(), out.data_ptr<float>(), N);
    return out;
}
"""

fused_cpp_source = (
    "torch::Tensor matmul_gelu_softmax_musa(torch::Tensor x, torch::Tensor weight, "
    "torch::Tensor bias);"
)

_fused_ext = load_inline(
    name="matmul_gelu_softmax_control",
    cpp_sources=fused_cpp_source,
    musa_sources=fused_source,
    functions=["matmul_gelu_softmax_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, in_features, out_features):
        super().__init__()
        # Parameter container only; all compute runs in MUSA.
        self.linear = nn.Linear(in_features, out_features)
        self.fused = _fused_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fused.matmul_gelu_softmax_musa(
            x, self.linear.weight, self.linear.bias
        )