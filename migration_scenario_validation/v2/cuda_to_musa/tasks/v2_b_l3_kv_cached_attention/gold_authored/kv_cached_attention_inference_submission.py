"""Project-authored MUSA positive control for ``b_l3_kv_cached_attention``.

Evaluator-only.  Matches ``F.scaled_dot_product_attention`` on the 3-D
reference contract: Q (1, 1, 4096), K/V (1, 2048, 4096), so batch=1, one query
position, 2048 cached keys, scale ``1/sqrt(4096)``.  Three kernels: scores,
softmax, weighted sum.  Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

kv_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void kv_scores_kernel(const float* __restrict__ q,
                                 const float* __restrict__ k,
                                 float* __restrict__ scores,
                                 int E, float scale) {
    const int key = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];

    const float* qv = q;
    const float* kv = k + static_cast<long long>(key) * E;
    float acc = 0.0f;
    for (int d = tid; d < E; d += nthreads) {
        acc += qv[d] * kv[d];
    }
    scratch[tid] = acc;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    if (tid == 0) {
        scores[key] = scratch[0] * scale;
    }
}

__global__ void kv_softmax_kernel(float* __restrict__ scores, int n) {
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];

    float m = -INFINITY;
    for (int i = tid; i < n; i += nthreads) {
        m = fmaxf(m, scores[i]);
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
    for (int i = tid; i < n; i += nthreads) {
        const float e = expf(scores[i] - mx);
        scores[i] = e;
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
    for (int i = tid; i < n; i += nthreads) {
        scores[i] *= inv;
    }
}

__global__ void kv_out_kernel(const float* __restrict__ scores,
                              const float* __restrict__ v,
                              float* __restrict__ out,
                              int Lk, int E) {
    const int dim = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];

    float acc = 0.0f;
    for (int j = tid; j < Lk; j += nthreads) {
        acc += scores[j] * v[static_cast<long long>(j) * E + dim];
    }
    scratch[tid] = acc;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    if (tid == 0) {
        out[dim] = scratch[0];
    }
}

torch::Tensor kv_cached_attention_musa(torch::Tensor q,
                                       torch::Tensor k,
                                       torch::Tensor v) {
    auto qc = q.contiguous();
    auto kc = k.contiguous();
    auto vc = v.contiguous();
    TORCH_CHECK(qc.scalar_type() == torch::kFloat32, "expected float32");
    TORCH_CHECK(qc.dim() == 3 && kc.dim() == 3 && vc.dim() == 3,
                "expected 3-D (batch, seq, embed) tensors");
    TORCH_CHECK(qc.size(0) == 1 && qc.size(1) == 1,
                "kv_cached_attention_musa control supports the reference contract B=1, q_len=1");
    const int E = static_cast<int>(qc.size(2));
    const int Lk = static_cast<int>(kc.size(1));
    TORCH_CHECK(kc.size(0) == 1 && vc.size(0) == 1, "batch mismatch");
    TORCH_CHECK(kc.size(2) == E && vc.size(2) == E, "embed mismatch");
    TORCH_CHECK(vc.size(1) == Lk, "kv length mismatch");

    auto scores = torch::empty({Lk}, qc.options());
    auto out = torch::empty({1, 1, E}, qc.options());
    const float scale = 1.0f / sqrtf(static_cast<float>(E));

    kv_scores_kernel<<<Lk, 256>>>(
        qc.data_ptr<float>(), kc.data_ptr<float>(), scores.data_ptr<float>(), E, scale);
    kv_softmax_kernel<<<1, 256>>>(scores.data_ptr<float>(), Lk);
    kv_out_kernel<<<E, 256>>>(
        scores.data_ptr<float>(), vc.data_ptr<float>(), out.data_ptr<float>(), Lk, E);
    return out;
}
"""

kv_cpp_source = (
    "torch::Tensor kv_cached_attention_musa(torch::Tensor q, torch::Tensor k, "
    "torch::Tensor v);"
)

_kv_ext = load_inline(
    name="kv_cached_attention_control",
    cpp_sources=kv_cpp_source,
    musa_sources=kv_source,
    functions=["kv_cached_attention_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.kv_attention = _kv_ext

    def forward(self, Q: torch.Tensor, K_cache: torch.Tensor, V_cache: torch.Tensor) -> torch.Tensor:
        return self.kv_attention.kv_cached_attention_musa(Q, K_cache, V_cache)