"""Project-authored MUSA positive control for ``b_l3_standard_matmul``.

Evaluator-only.  ``C = A @ B`` for the reference contract (2048 x 8192) @
(8192 x 4096), using a 16x16 shared-memory tiled kernel.  Must never be copied
into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

matmul_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

#define TILE 16

__global__ void matmul_nn_kernel(const float* __restrict__ A,
                                 const float* __restrict__ B,
                                 float* __restrict__ C,
                                 int M, int N, int K) {
    __shared__ float As[TILE][TILE];
    __shared__ float Bs[TILE][TILE];

    const int row = blockIdx.y * TILE + threadIdx.y;
    const int col = blockIdx.x * TILE + threadIdx.x;

    float acc = 0.0f;
    for (int k0 = 0; k0 < K; k0 += TILE) {
        const int ak = k0 + threadIdx.x;
        const int bk = k0 + threadIdx.y;
        As[threadIdx.y][threadIdx.x] =
            (row < M && ak < K) ? A[row * K + ak] : 0.0f;
        Bs[threadIdx.y][threadIdx.x] =
            (bk < K && col < N) ? B[bk * N + col] : 0.0f;
        __syncthreads();
        #pragma unroll
        for (int k = 0; k < TILE; ++k) {
            acc += As[threadIdx.y][k] * Bs[k][threadIdx.x];
        }
        __syncthreads();
    }
    if (row < M && col < N) {
        C[row * N + col] = acc;
    }
}

torch::Tensor matmul_musa(torch::Tensor A, torch::Tensor B) {
    auto ac = A.contiguous();
    auto bc = B.contiguous();
    TORCH_CHECK(ac.scalar_type() == torch::kFloat32, "matmul_musa expects float32");
    TORCH_CHECK(bc.scalar_type() == torch::kFloat32, "matmul_musa expects float32");
    TORCH_CHECK(ac.dim() == 2 && bc.dim() == 2, "matmul_musa expects 2-D inputs");
    TORCH_CHECK(ac.size(1) == bc.size(0), "matmul_musa shape mismatch");
    const int M = static_cast<int>(ac.size(0));
    const int K = static_cast<int>(ac.size(1));
    const int N = static_cast<int>(bc.size(1));
    auto C = torch::empty({M, N}, ac.options());
    dim3 block(TILE, TILE);
    dim3 grid((N + TILE - 1) / TILE, (M + TILE - 1) / TILE);
    matmul_nn_kernel<<<grid, block>>>(
        ac.data_ptr<float>(), bc.data_ptr<float>(), C.data_ptr<float>(), M, N, K);
    return C;
}
"""

matmul_cpp_source = "torch::Tensor matmul_musa(torch::Tensor A, torch::Tensor B);"

_matmul_ext = load_inline(
    name="matmul_control",
    cpp_sources=matmul_cpp_source,
    musa_sources=matmul_source,
    functions=["matmul_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.matmul = _matmul_ext

    def forward(self, A: torch.Tensor, B: torch.Tensor) -> torch.Tensor:
        return self.matmul.matmul_musa(A, B)