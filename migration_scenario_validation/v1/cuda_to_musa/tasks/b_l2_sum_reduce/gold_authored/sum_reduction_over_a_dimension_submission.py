"""Project-authored MUSA positive control for ``b_l2_sum_reduce``.

Evaluator-only.  Sum over dim 1 with ``keepdim=True``.  One thread per output
element, double accumulator to stay well inside ``atol=rtol=1e-4``.
Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

sum_reduce_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void sum_dim1_kernel(const float* __restrict__ x,
                                float* __restrict__ out,
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

    double acc = 0.0;
    for (long long j = 0; j < reduce; ++j) {
        acc += static_cast<double>(base[j * inner]);
    }
    out[gid] = static_cast<float>(acc);
}

torch::Tensor sum_reduce_musa(torch::Tensor x) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "sum_reduce_musa expects float32");
    TORCH_CHECK(xc.dim() >= 2, "sum_reduce_musa expects at least 2 dims");
    const long long outer = xc.size(0);
    const long long reduce = xc.size(1);
    TORCH_CHECK(reduce > 0, "empty reduction dimension");
    const long long inner = xc.numel() / (outer * reduce);

    std::vector<int64_t> sizes;
    sizes.push_back(outer);
    sizes.push_back(1);
    for (int64_t d = 2; d < xc.dim(); ++d) {
        sizes.push_back(xc.size(d));
    }
    auto out = torch::empty(sizes, xc.options());

    const long long total = outer * inner;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    sum_dim1_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), out.data_ptr<float>(), outer, inner, reduce);
    return out;
}
"""

sum_reduce_cpp_source = "torch::Tensor sum_reduce_musa(torch::Tensor x);"

_sum_reduce_ext = load_inline(
    name="sum_reduce_control",
    cpp_sources=sum_reduce_cpp_source,
    musa_sources=sum_reduce_source,
    functions=["sum_reduce_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim
        self.sum_reduce = _sum_reduce_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.dim != 1:
            raise ValueError("this control implements dim=1 (the reference contract)")
        return self.sum_reduce.sum_reduce_musa(x)