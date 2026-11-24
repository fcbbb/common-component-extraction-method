"""Project-authored MUSA positive control for ``b_l1_sigmoid``.

Evaluator-only.  MultiKernelBench has no upstream MUSA sample for this op at
the pinned commit, so this file exists to prove that the evaluator accepts a
correct MUSA implementation.  It must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

sigmoid_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void sigmoid_kernel(const float* __restrict__ x,
                               float* __restrict__ out,
                               long long n) {
    const long long idx = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (idx < n) {
        out[idx] = 1.0f / (1.0f + expf(-x[idx]));
    }
}

torch::Tensor sigmoid_musa(torch::Tensor x) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "sigmoid_musa expects float32");
    auto out = torch::empty_like(xc);
    const long long n = static_cast<long long>(xc.numel());
    const int block = 256;
    const long long blocks = (n + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    sigmoid_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), out.data_ptr<float>(), n);
    return out;
}
"""

sigmoid_cpp_source = "torch::Tensor sigmoid_musa(torch::Tensor x);"

_sigmoid_ext = load_inline(
    name="sigmoid_control",
    cpp_sources=sigmoid_cpp_source,
    musa_sources=sigmoid_source,
    functions=["sigmoid_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.sigmoid = _sigmoid_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.sigmoid.sigmoid_musa(x)