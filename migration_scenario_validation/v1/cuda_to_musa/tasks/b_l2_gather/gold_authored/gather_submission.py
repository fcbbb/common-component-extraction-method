"""Project-authored MUSA positive control for ``b_l2_gather``.

Evaluator-only.  ``out[b, j] = x[b, idx[b, j]]`` with ``dim=1`` and int64
indices, matching ``torch.gather``.  Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

gather_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void gather_dim1_kernel(const float* __restrict__ x,
                                   const int64_t* __restrict__ idx,
                                   float* __restrict__ out,
                                   long long rows,
                                   long long cols,
                                   long long index_cols,
                                   long long x_cols) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const long long total = rows * index_cols;
    if (gid >= total) {
        return;
    }
    const long long r = gid / index_cols;
    const long long j = gid - r * index_cols;
    const long long i = idx[r * cols + j];
    out[gid] = x[r * x_cols + i];
}

torch::Tensor gather_musa(torch::Tensor x, torch::Tensor idx) {
    auto xc = x.contiguous();
    auto ic = idx.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "gather_musa expects float32 input");
    TORCH_CHECK(ic.scalar_type() == torch::kInt64, "gather_musa expects int64 indices");
    TORCH_CHECK(xc.dim() == 2 && ic.dim() == 2, "gather_musa expects 2-D input and index");
    TORCH_CHECK(ic.size(0) == xc.size(0), "gather_musa batch mismatch");
    TORCH_CHECK(ic.size(1) <= xc.size(1), "gather_musa index too wide");

    auto out = torch::empty(ic.sizes(), xc.options());
    const long long rows = xc.size(0);
    const long long cols = ic.size(1);
    const long long total = rows * cols;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    gather_dim1_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(),
        ic.data_ptr<int64_t>(),
        out.data_ptr<float>(),
        rows, cols, cols, xc.size(1));
    return out;
}
"""

gather_cpp_source = "torch::Tensor gather_musa(torch::Tensor x, torch::Tensor idx);"

_gather_ext = load_inline(
    name="gather_control",
    cpp_sources=gather_cpp_source,
    musa_sources=gather_source,
    functions=["gather_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.gather = _gather_ext

    def forward(self, x: torch.Tensor, idx: torch.Tensor) -> torch.Tensor:
        return self.gather.gather_musa(x, idx)