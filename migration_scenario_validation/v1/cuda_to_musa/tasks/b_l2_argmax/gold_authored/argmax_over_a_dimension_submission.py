"""Project-authored MUSA positive control for ``b_l2_argmax``.

Evaluator-only.  Argmax over dim 1 with the dim removed, matching
``torch.argmax(x, dim=1)``; ties keep the first index.  One thread per output
element.  Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

argmax_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void argmax_dim1_kernel(const float* __restrict__ x,
                                   long long* __restrict__ out,
                                   long long outer,
                                   long long inner,
                                   long long reduce) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const long long total = outer * inner;
    if (gid >= total) {
        return;
    }
    const long long o = gid / inner;
    const long long i = gid - o * inner;
    const float* base = x + o * reduce * inner + i;

    float best = base[0];
    long long best_idx = 0;
    for (long long j = 1; j < reduce; ++j) {
        const float v = base[j * inner];
        if (v > best) {
            best = v;
            best_idx = j;
        }
    }
    out[gid] = best_idx;
}

torch::Tensor argmax_musa(torch::Tensor x) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "argmax_musa expects float32");
    TORCH_CHECK(xc.dim() >= 2, "argmax_musa expects at least 2 dims");
    const long long outer = xc.size(0);
    const long long reduce = xc.size(1);
    TORCH_CHECK(reduce > 0, "empty reduction dimension");
    const long long inner = xc.numel() / (outer * reduce);

    std::vector<int64_t> sizes;
    sizes.push_back(outer);
    for (int64_t d = 2; d < xc.dim(); ++d) {
        sizes.push_back(xc.size(d));
    }
    auto out = torch::empty(sizes, xc.options().dtype(torch::kInt64));

    const long long total = outer * inner;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    argmax_dim1_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(),
        reinterpret_cast<long long*>(out.data_ptr<int64_t>()),
        outer, inner, reduce);
    return out;
}
"""

argmax_cpp_source = "torch::Tensor argmax_musa(torch::Tensor x);"

_argmax_ext = load_inline(
    name="argmax_control",
    cpp_sources=argmax_cpp_source,
    musa_sources=argmax_source,
    functions=["argmax_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim
        self.argmax = _argmax_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.dim != 1:
            raise ValueError("this control implements dim=1 (the reference contract)")
        return self.argmax.argmax_musa(x)