"""Project-authored MUSA positive control for ``b_l3_group_norm``.

Evaluator-only.  Matches ``nn.GroupNorm(num_groups=8, num_channels=64)`` on a
(128, 64, 512, 512) tensor: one block per (batch, group), double accumulators
for the biased variance, then the affine transform.  Must never be copied
into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

group_norm_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void group_norm_kernel(const float* __restrict__ x,
                                  const float* __restrict__ weight,
                                  const float* __restrict__ bias,
                                  float* __restrict__ out,
                                  int batches,
                                  int channels,
                                  int groups,
                                  long long inner,
                                  float eps) {
    const int bg = blockIdx.x;
    const int batch = bg / groups;
    const int group = bg - batch * groups;
    const int cpg = channels / groups;
    const long long n = static_cast<long long>(cpg) * inner;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;

    __shared__ double s1[256];
    __shared__ double s2[256];

    double acc1 = 0.0;
    double acc2 = 0.0;
    for (long long idx = tid; idx < n; idx += nthreads) {
        const int cl = static_cast<int>(idx / inner);
        const long long i = idx - static_cast<long long>(cl) * inner;
        const long long off =
            (static_cast<long long>(batch) * channels + group * cpg + cl) * inner + i;
        const float v = x[off];
        acc1 += static_cast<double>(v);
        acc2 += static_cast<double>(v) * static_cast<double>(v);
    }
    s1[tid] = acc1;
    s2[tid] = acc2;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            s1[tid] += s1[tid + stride];
            s2[tid] += s2[tid + stride];
        }
        __syncthreads();
    }

    const double mean = s1[0] / static_cast<double>(n);
    const double var = s2[0] / static_cast<double>(n) - mean * mean;
    const double inv = 1.0 / sqrt(var + static_cast<double>(eps));

    for (long long idx = tid; idx < n; idx += nthreads) {
        const int cl = static_cast<int>(idx / inner);
        const long long i = idx - static_cast<long long>(cl) * inner;
        const long long off =
            (static_cast<long long>(batch) * channels + group * cpg + cl) * inner + i;
        const int c = group * cpg + cl;
        out[off] = static_cast<float>(
            (static_cast<double>(x[off]) - mean) * inv *
                static_cast<double>(weight[c]) +
            static_cast<double>(bias[c]));
    }
}

torch::Tensor group_norm_musa(torch::Tensor x, torch::Tensor weight, torch::Tensor bias,
                              int64_t groups, double eps) {
    auto xc = x.contiguous();
    auto wc = weight.contiguous();
    auto bc = bias.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "group_norm_musa expects float32");
    TORCH_CHECK(xc.dim() >= 2, "group_norm_musa expects at least 2 dims");
    const int batches = static_cast<int>(xc.size(0));
    const int channels = static_cast<int>(xc.size(1));
    TORCH_CHECK(groups > 0 && channels % groups == 0, "invalid group count");
    TORCH_CHECK(wc.numel() == channels && bc.numel() == channels, "affine size mismatch");
    const long long inner = xc.numel() / (static_cast<long long>(batches) * channels);
    TORCH_CHECK(inner > 0, "empty inner size");
    auto out = torch::empty_like(xc);
    group_norm_kernel<<<batches * static_cast<int>(groups), 256>>>(
        xc.data_ptr<float>(), wc.data_ptr<float>(), bc.data_ptr<float>(),
        out.data_ptr<float>(), batches, channels, static_cast<int>(groups),
        inner, static_cast<float>(eps));
    return out;
}
"""

group_norm_cpp_source = (
    "torch::Tensor group_norm_musa(torch::Tensor x, torch::Tensor weight, "
    "torch::Tensor bias, int64_t groups, double eps);"
)

_group_norm_ext = load_inline(
    name="group_norm_control",
    cpp_sources=group_norm_cpp_source,
    musa_sources=group_norm_source,
    functions=["group_norm_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, num_features: int, num_groups: int):
        super().__init__()
        # Parameter container only; normalisation runs in MUSA.
        self.gn = nn.GroupNorm(num_groups=num_groups, num_channels=num_features)
        self.group_norm = _group_norm_ext
        self.num_groups = num_groups

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.group_norm.group_norm_musa(
            x, self.gn.weight, self.gn.bias, self.num_groups, float(self.gn.eps)
        )