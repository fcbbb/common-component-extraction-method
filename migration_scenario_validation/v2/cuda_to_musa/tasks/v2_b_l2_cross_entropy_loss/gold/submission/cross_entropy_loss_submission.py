"""Project-authored MUSA positive control for ``b_l2_cross_entropy_loss``.

Evaluator-only.  Matches ``F.cross_entropy(predictions, targets)`` with the
default ``reduction='mean'``: per-row stable log-sum-exp, then a mean over the
batch.  Two kernels (row losses, then the batch mean).  Must never be copied
into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

cross_entropy_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void ce_row_losses_kernel(const float* __restrict__ predictions,
                                     const int64_t* __restrict__ targets,
                                     float* __restrict__ losses,
                                     long long classes) {
    const long long row = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];

    const float* pr = predictions + row * classes;

    float m = -INFINITY;
    for (long long i = tid; i < classes; i += nthreads) {
        m = fmaxf(m, pr[i]);
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
    for (long long i = tid; i < classes; i += nthreads) {
        sum += expf(pr[i] - mx);
    }
    scratch[tid] = sum;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    const float log_sum_exp = mx + logf(scratch[0]);
    losses[row] = log_sum_exp - pr[targets[row]];
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

torch::Tensor cross_entropy_musa(torch::Tensor predictions, torch::Tensor targets) {
    auto pc = predictions.contiguous();
    auto tc = targets.contiguous();
    TORCH_CHECK(pc.scalar_type() == torch::kFloat32, "cross_entropy_musa expects float32 logits");
    TORCH_CHECK(tc.scalar_type() == torch::kInt64, "cross_entropy_musa expects int64 targets");
    TORCH_CHECK(pc.dim() == 2, "cross_entropy_musa expects 2-D logits");
    TORCH_CHECK(tc.numel() == pc.size(0), "cross_entropy_musa target count mismatch");

    const long long rows = pc.size(0);
    const long long classes = pc.size(1);
    auto losses = torch::empty({rows}, pc.options());
    auto out = torch::empty({}, pc.options());

    ce_row_losses_kernel<<<static_cast<int>(rows), 256>>>(
        pc.data_ptr<float>(),
        tc.data_ptr<int64_t>(),
        losses.data_ptr<float>(),
        classes);
    mean_kernel<<<1, 256>>>(losses.data_ptr<float>(), out.data_ptr<float>(), rows);
    return out;
}
"""

cross_entropy_cpp_source = (
    "torch::Tensor cross_entropy_musa(torch::Tensor predictions, torch::Tensor targets);"
)

_cross_entropy_ext = load_inline(
    name="cross_entropy_control",
    cpp_sources=cross_entropy_cpp_source,
    musa_sources=cross_entropy_source,
    functions=["cross_entropy_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.cross_entropy = _cross_entropy_ext

    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return self.cross_entropy.cross_entropy_musa(predictions, targets)