"""Project-authored MUSA positive control for ``b_l2_cosine_similarity_loss``.

Evaluator-only.  Matches
``mean(1 - F.cosine_similarity(predictions, targets, dim=1))`` for two
(128, 4096) float32 inputs, including the default ``eps=1e-8`` clamp on each
row norm.  Two kernels: per-row cosine similarity (one block per row), then a
mean over the batch.  Reductions accumulate in double so the scalar is not
dominated by float rounding.  Must never be copied into ``work/``.

Input size is 128*4096 = 524,288 elements per tensor (2 MB each), so the
evaluator's ``torch.allclose`` has ample memory at 47.90 GB.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

cosine_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void cosine_row_kernel(const float* __restrict__ pred,
                                  const float* __restrict__ target,
                                  float* __restrict__ losses,
                                  long long dim,
                                  float eps) {
    const long long row = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ double s_dot[256];
    __shared__ double s_na[256];
    __shared__ double s_nb[256];

    const float* pa = pred + row * dim;
    const float* pb = target + row * dim;

    double dot = 0.0;
    double na = 0.0;
    double nb = 0.0;
    for (long long i = tid; i < dim; i += nthreads) {
        const double a = static_cast<double>(pa[i]);
        const double b = static_cast<double>(pb[i]);
        dot += a * b;
        na += a * a;
        nb += b * b;
    }
    s_dot[tid] = dot;
    s_na[tid] = na;
    s_nb[tid] = nb;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            s_dot[tid] += s_dot[tid + stride];
            s_na[tid] += s_na[tid + stride];
            s_nb[tid] += s_nb[tid + stride];
        }
        __syncthreads();
    }
    if (tid == 0) {
        // torch's cosine_similarity clamps each norm at eps before dividing.
        double norm_a = sqrt(s_na[0]);
        double norm_b = sqrt(s_nb[0]);
        if (norm_a < eps) {
            norm_a = eps;
        }
        if (norm_b < eps) {
            norm_b = eps;
        }
        losses[row] = static_cast<float>(1.0 - s_dot[0] / (norm_a * norm_b));
    }
}

__global__ void mean_kernel(const float* __restrict__ losses,
                            float* __restrict__ out,
                            long long n) {
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ double scratch[256];

    double acc = 0.0;
    for (long long i = tid; i < n; i += nthreads) {
        acc += static_cast<double>(losses[i]);
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
        out[0] = static_cast<float>(scratch[0] / static_cast<double>(n));
    }
}

torch::Tensor cosine_similarity_loss_musa(torch::Tensor predictions, torch::Tensor targets) {
    auto pc = predictions.contiguous();
    auto tc = targets.contiguous();
    TORCH_CHECK(pc.scalar_type() == torch::kFloat32, "cosine_similarity_loss_musa expects float32");
    TORCH_CHECK(tc.scalar_type() == torch::kFloat32, "cosine_similarity_loss_musa expects float32");
    TORCH_CHECK(pc.dim() == 2 && tc.dim() == 2, "cosine_similarity_loss_musa expects 2-D inputs");
    TORCH_CHECK(pc.sizes() == tc.sizes(), "cosine_similarity_loss_musa shape mismatch");

    const long long rows = pc.size(0);
    const long long dim = pc.size(1);
    auto losses = torch::empty({rows}, pc.options());
    auto out = torch::empty({}, pc.options());

    cosine_row_kernel<<<static_cast<int>(rows), 256>>>(
        pc.data_ptr<float>(),
        tc.data_ptr<float>(),
        losses.data_ptr<float>(),
        dim,
        1e-8f);
    mean_kernel<<<1, 256>>>(losses.data_ptr<float>(), out.data_ptr<float>(), rows);
    return out;
}
"""

cosine_cpp_source = (
    "torch::Tensor cosine_similarity_loss_musa(torch::Tensor predictions, torch::Tensor targets);"
)

_cosine_ext = load_inline(
    name="cosine_similarity_loss_control",
    cpp_sources=cosine_cpp_source,
    musa_sources=cosine_source,
    functions=["cosine_similarity_loss_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.cosine = _cosine_ext

    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return self.cosine.cosine_similarity_loss_musa(predictions, targets)