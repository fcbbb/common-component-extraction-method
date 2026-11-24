"""Project-authored MUSA positive control for ``b_l1_softmax``.

Evaluator-only.  The reference contracts a 2-D tensor and applies softmax over
dim 1.  One block per row, three passes (max, sum of exp, normalised write).
Must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

softmax_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void softmax_dim1_kernel(const float* __restrict__ x,
                                    float* __restrict__ out,
                                    long long rows,
                                    int cols) {
    const long long row = blockIdx.x;
    if (row >= rows) {
        return;
    }
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ float scratch[256];

    const float* xr = x + row * static_cast<long long>(cols);
    float* orow = out + row * static_cast<long long>(cols);

    float m = -INFINITY;
    for (int i = tid; i < cols; i += nthreads) {
        m = fmaxf(m, xr[i]);
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
    for (int i = tid; i < cols; i += nthreads) {
        sum += expf(xr[i] - mx);
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

    for (int i = tid; i < cols; i += nthreads) {
        orow[i] = expf(xr[i] - mx) * inv;
    }
}

torch::Tensor softmax_musa(torch::Tensor x) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "softmax_musa expects float32");
    TORCH_CHECK(xc.dim() == 2, "softmax_musa expects a 2-D tensor");
    const long long rows = xc.size(0);
    const long long cols64 = xc.size(1);
    TORCH_CHECK(cols64 <= 2147483647LL, "column count does not fit in int");
    auto out = torch::empty_like(xc);
    const int block = 256;
    softmax_dim1_kernel<<<static_cast<int>(rows), block>>>(
        xc.data_ptr<float>(), out.data_ptr<float>(), rows, static_cast<int>(cols64));
    return out;
}
"""

softmax_cpp_source = "torch::Tensor softmax_musa(torch::Tensor x);"

_softmax_ext = load_inline(
    name="softmax_control",
    cpp_sources=softmax_cpp_source,
    musa_sources=softmax_source,
    functions=["softmax_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self):
        super().__init__()
        self.softmax = _softmax_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.softmax.softmax_musa(x)