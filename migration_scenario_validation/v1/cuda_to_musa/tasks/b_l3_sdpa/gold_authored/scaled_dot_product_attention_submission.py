"""Project-authored MUSA positive control for ``b_l3_sdpa``.

Evaluator-only.  Matches ``F.scaled_dot_product_attention`` for the reference
contract (32, 32, 512, 1024): batched QK^T (16x16 tiled, transposed-B
variant), row softmax, then P @ V (16x16 tiled).  Must never be copied into
``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

sdpa_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

#define TILE 16

__global__ void bmm_nt_kernel(const float* __restrict__ A,
                              const float* __restrict__ B,
                              float* __restrict__ C,
                              int M, int N, int K,
                              long long a_stride, long long b_stride, long long c_stride,
                              float scale) {
    __shared__ float As[TILE][TILE];
    __shared__ float Bs[TILE][TILE];
    const int i = blockIdx.y * TILE + threadIdx.y;
    const int j = blockIdx.x * TILE + threadIdx.x;
    const long long z = blockIdx.z;
    const float* Ab = A + z * a_stride;
    const float* Bb = B + z * b_stride;
    float acc = 0.0f;
    for (int k0 = 0; k0 < K; k0 += TILE) {
        As[threadIdx.y][threadIdx.x] =
            (i < M && k0 + threadIdx.x < K) ? Ab[i * K + k0 + threadIdx.x] : 0.0f;
        Bs[threadIdx.y][threadIdx.x] =
            (static_cast<int>(blockIdx.x) * TILE + threadIdx.y < N &&
             k0 + threadIdx.x < K)
                ? Bb[(static_cast<int>(blockIdx.x) * TILE + threadIdx.y) * K +
                     k0 + threadIdx.x]
                : 0.0f;
        __syncthreads();
        #pragma unroll
        for (int k = 0; k < TILE; ++k) {
            acc += As[threadIdx.y][k] * Bs[threadIdx.x][k];
        }
        __syncthreads();
    }
    if (i < M && j < N) {
        C[z * c_stride + i * N + j] = acc * scale;
    }
}

__global__ void bmm_nn_kernel(const float* __restrict__ A,
                              const float* __restrict__ B,
                              float* __restrict__ C,
                              int M, int N, int K,
                              long long a_stride, long long b_stride, long long c_stride) {
    __shared__ float As[TILE][TILE];
    __shared__ float Bs[TILE][TILE];
    const int i = blockIdx.y * TILE + threadIdx.y;
    const int j = blockIdx.x * TILE + threadIdx.x;
    const long long z = blockIdx.z;
    const float* Ab = A + z * a_stride;
    const float* Bb = B + z * b_stride;
    float acc = 0.0f;
    for (int k0 = 0; k0 < K; k0 += TILE) {
        As[threadIdx.y][threadIdx.x] =
            (i < M && k0 + threadIdx.x < K) ? Ab[i * K + k0 + threadIdx.x] : 0.0f;
        Bs[threadIdx.y][threadIdx.x] =
            (k0 + threadIdx.y < K && j < N)
                ? Bb[(k0 + threadIdx.y) * N + j]
                : 0.0f;
        __syncthreads();
        #pragma unroll
        for (int k = 0; k < TILE; ++k) {
            acc += As[threadIdx.y][k] * Bs[k][threadIdx.x];
        }
        __syncthreads();
    }
    if (i < M && j < N) {
        C[z * c_stride + i * N + j] = acc;
    }
}

__global__ void softmax_lastdim_kernel(float* __restrict__ x, int cols) {
    const long long row = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];
    float* xr = x + row * static_cast<long long>(cols);

    float m = -INFINITY;
    for (int i = tid; i < cols; i += nthreads) {
        m = fmaxf(m, xr[i]);
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
        const float e = expf(xr[i] - mx);
        xr[i] = e;
        sum += e;
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
        xr[i] *= inv;
    }
}

torch::Tensor sdpa_musa(torch::Tensor q, torch::Tensor k, torch::Tensor v) {
    auto qc = q.contiguous();
    auto kc = k.contiguous();
    auto vc = v.contiguous();
    TORCH_CHECK(qc.scalar_type() == torch::kFloat32, "sdpa_musa expects float32");
    TORCH_CHECK(qc.dim() == 4 && kc.dim() == 4 && vc.dim() == 4,
                "sdpa_musa expects (B, H, L, E)");
    const int B = static_cast<int>(qc.size(0));
    const int H = static_cast<int>(qc.size(1));
    const int L = static_cast<int>(qc.size(2));
    const int E = static_cast<int>(qc.size(3));
    TORCH_CHECK(kc.size(2) == L && vc.size(2) == L, "sdpa_musa sequence mismatch");
    TORCH_CHECK(vc.size(3) == E && kc.size(3) == E, "sdpa_musa head-dim mismatch");
    const long long BH = static_cast<long long>(B) * H;

    auto scores = torch::empty({BH, static_cast<long long>(L), static_cast<long long>(L)},
                               qc.options());
    auto out = torch::empty({BH, static_cast<long long>(L), static_cast<long long>(E)},
                            qc.options());

    const float scale = 1.0f / sqrtf(static_cast<float>(E));
    dim3 block(TILE, TILE);
    dim3 grid_qk((L + TILE - 1) / TILE, (L + TILE - 1) / TILE, static_cast<unsigned>(BH));
    const long long q_stride = static_cast<long long>(L) * E;
    const long long s_stride = static_cast<long long>(L) * L;

    bmm_nt_kernel<<<grid_qk, block>>>(
        qc.data_ptr<float>(), kc.data_ptr<float>(), scores.data_ptr<float>(),
        L, L, E, q_stride, q_stride, s_stride, scale);

    softmax_lastdim_kernel<<<static_cast<int>(BH * L), 256>>>(
        scores.data_ptr<float>(), L);

    dim3 grid_pv((E + TILE - 1) / TILE, (L + TILE - 1) / TILE, static_cast<unsigned>(BH));
    const long long v_stride = static_cast<long long>(L) * E;
    const long long o_stride = static_cast<long long>(L) * E;
    bmm_nn_kernel<<<grid_pv, block>>>(
        scores.data_ptr<float>(), vc.data_ptr<float>(), out.data_ptr<float>(),
        L, E, L, s_stride, v_stride, o_stride);

    return out.view({B, H, L, E});
}
"""

sdpa_cpp_source = "torch::Tensor sdpa_musa(torch::Tensor q, torch::Tensor k, torch::Tensor v);"

_sdpa_ext = load_inline(
    name="sdpa_control",
    cpp_sources=sdpa_cpp_source,
    musa_sources=sdpa_source,
    functions=["sdpa_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.sdpa = _sdpa_ext

    def forward(self, Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor) -> torch.Tensor:
        return self.sdpa.sdpa_musa(Q, K, V)