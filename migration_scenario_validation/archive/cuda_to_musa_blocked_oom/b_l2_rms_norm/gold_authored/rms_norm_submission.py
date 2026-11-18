"""Project-authored MUSA positive control for ``b_l2_rms_norm``.

Evaluator-only.  The reference normalises a 4-D tensor over dim 1 with no
affine parameters.  One thread per (outer, inner) column, reducing over the
strided feature axis.  Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

rms_norm_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void rms_norm_dim1_kernel(const float* __restrict__ x,
                                     float* __restrict__ out,
                                     long long outer,
                                     long long inner,
                                     int reduce,
                                     float eps) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const long long total = outer * inner;
    if (gid >= total) {
        return;
    }
    const long long o = gid / inner;
    const long long i = gid - o * inner;
    const long long stride = inner;
    const float* base = x + o * static_cast<long long>(reduce) * inner + i;
    float* obase = out + o * static_cast<long long>(reduce) * inner + i;

    float acc = 0.0f;
    for (int j = 0; j < reduce; ++j) {
        const float v = base[static_cast<long long>(j) * stride];
        acc += v * v;
    }
    const float inv = rsqrtf(acc / static_cast<float>(reduce) + eps);
    for (int j = 0; j < reduce; ++j) {
        const long long off = static_cast<long long>(j) * stride;
        obase[off] = base[off] * inv;
    }
}

torch::Tensor rms_norm_musa(torch::Tensor x, double eps) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "rms_norm_musa expects float32");
    TORCH_CHECK(xc.dim() >= 2, "rms_norm_musa expects at least 2 dims");
    const long long outer = xc.size(0);
    const long long reduce64 = xc.size(1);
    TORCH_CHECK(reduce64 <= 2147483647LL, "feature count does not fit in int");
    TORCH_CHECK(reduce64 > 0, "empty feature dimension");
    const long long inner = xc.numel() / (outer * reduce64);
    auto out = torch::empty_like(xc);
    const long long total = outer * inner;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    rms_norm_dim1_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), out.data_ptr<float>(), outer, inner,
        static_cast<int>(reduce64), static_cast<float>(eps));
    return out;
}
"""

rms_norm_cpp_source = "torch::Tensor rms_norm_musa(torch::Tensor x, double eps);"

_rms_norm_ext = load_inline(
    name="rms_norm_control",
    cpp_sources=rms_norm_cpp_source,
    musa_sources=rms_norm_source,
    functions=["rms_norm_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, num_features: int, eps: float = 1e-5):
        super().__init__()
        self.num_features = num_features
        self.eps = eps
        self.rms_norm = _rms_norm_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.rms_norm.rms_norm_musa(x, float(self.eps))