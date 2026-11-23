"""Project-authored MUSA positive control for ``b_l2_cumsum``.

Evaluator-only.  Row-wise prefix sum along dim 1.  One thread per row with a
contiguous sequential scan; the reference input is (32768, 32768).
Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

cumsum_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void cumsum_dim1_kernel(const float* __restrict__ x,
                                   float* __restrict__ out,
                                   long long rows,
                                   long long cols) {
    const long long row = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (row >= rows) {
        return;
    }
    const float* xr = x + row * cols;
    float* orow = out + row * cols;
    float acc = 0.0f;
    for (long long i = 0; i < cols; ++i) {
        acc += xr[i];
        orow[i] = acc;
    }
}

torch::Tensor cumsum_musa(torch::Tensor x) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "cumsum_musa expects float32");
    TORCH_CHECK(xc.dim() == 2, "cumsum_musa expects a 2-D tensor");
    const long long rows = xc.size(0);
    const long long cols = xc.size(1);
    auto out = torch::empty_like(xc);
    const int block = 256;
    const long long blocks = (rows + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    cumsum_dim1_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), out.data_ptr<float>(), rows, cols);
    return out;
}
"""

cumsum_cpp_source = "torch::Tensor cumsum_musa(torch::Tensor x);"

_cumsum_ext = load_inline(
    name="cumsum_control",
    cpp_sources=cumsum_cpp_source,
    musa_sources=cumsum_source,
    functions=["cumsum_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim
        self.cumsum = _cumsum_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.dim != 1:
            raise ValueError("this control implements dim=1 (the reference contract)")
        return self.cumsum.cumsum_musa(x)