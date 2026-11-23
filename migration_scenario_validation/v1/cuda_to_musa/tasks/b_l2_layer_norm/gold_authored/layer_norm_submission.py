"""Project-authored MUSA positive control for ``b_l2_layer_norm``.

This is **not** an upstream MultiKernelBench sample.  The upstream
``prompts/musa_new_model_layer_norm.py`` was written for the 2-D
``(16384, 1024)`` contract in ``prompts/cuda_model_layer_norm.py``, while the
evaluator's numerical contract is ``reference/normalization/layer_norm.py``,
which feeds a 4-D ``(64, 64, 256, 256)`` tensor with
``normalized_shape=(64, 256, 256)``.  The upstream sample compiles on MUSA but
is numerically wrong for that contract (verified on 2026-11-16), so it cannot
serve as a positive control.

This file exists to prove that the evaluator accepts a correct 4-D
implementation.  It is evaluator-only and must never be copied into ``work/``.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

layer_norm_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void layer_norm_kernel(const float* __restrict__ x,
                                  const float* __restrict__ weight,
                                  const float* __restrict__ bias,
                                  float* __restrict__ out,
                                  int rows,
                                  int cols,
                                  float eps) {
    const int row = blockIdx.x;
    if (row >= rows) {
        return;
    }
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;

    const long long base = static_cast<long long>(row) * static_cast<long long>(cols);
    const float* x_row = x + base;
    float* out_row = out + base;

    // One block per row; 256 threads, power-of-two tree reduction.
    __shared__ float scratch[256];

    float acc = 0.0f;
    for (int i = tid; i < cols; i += nthreads) {
        acc += x_row[i];
    }
    scratch[tid] = acc;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    const float mean = scratch[0] / static_cast<float>(cols);

    acc = 0.0f;
    for (int i = tid; i < cols; i += nthreads) {
        const float diff = x_row[i] - mean;
        acc += diff * diff;
    }
    scratch[tid] = acc;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            scratch[tid] += scratch[tid + stride];
        }
        __syncthreads();
    }
    const float inv_std = rsqrtf(scratch[0] / static_cast<float>(cols) + eps);

    for (int i = tid; i < cols; i += nthreads) {
        out_row[i] = (x_row[i] - mean) * inv_std * weight[i] + bias[i];
    }
}

torch::Tensor layer_norm_musa(torch::Tensor x,
                              torch::Tensor weight,
                              torch::Tensor bias,
                              double eps) {
    auto xc = x.contiguous();
    auto wc = weight.contiguous();
    auto bc = bias.contiguous();
    const long long cols64 = static_cast<long long>(wc.numel());
    const long long rows64 = cols64 > 0
        ? static_cast<long long>(xc.numel()) / cols64
        : 0;
    TORCH_CHECK(cols64 > 0 && rows64 * cols64 == static_cast<long long>(xc.numel()),
                "input size is not divisible by the normalized size");
    TORCH_CHECK(cols64 <= 2147483647LL, "normalized size does not fit in int");

    auto out = torch::empty_like(xc);
    const int block = 256;
    layer_norm_kernel<<<static_cast<int>(rows64), block>>>(
        xc.data_ptr<float>(),
        wc.data_ptr<float>(),
        bc.data_ptr<float>(),
        out.data_ptr<float>(),
        static_cast<int>(rows64),
        static_cast<int>(cols64),
        static_cast<float>(eps));
    return out;
}
"""

layer_norm_cpp_source = (
    "torch::Tensor layer_norm_musa(torch::Tensor x, torch::Tensor weight, "
    "torch::Tensor bias, double eps);"
)

# A distinct extension name avoids reusing a stale build from another
# layer_norm submission with the same name.
_layer_norm_ext = load_inline(
    name="layer_norm_control",
    cpp_sources=layer_norm_cpp_source,
    musa_sources=layer_norm_source,
    functions=["layer_norm_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, normalized_shape):
        super().__init__()
        self.ln = nn.LayerNorm(normalized_shape=normalized_shape)
        if isinstance(normalized_shape, int):
            normalized_shape = (normalized_shape,)
        cols = 1
        for dim in normalized_shape:
            cols *= int(dim)
        self.cols = cols
        self.layer_norm = _layer_norm_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x_rows = x.contiguous().view(-1, self.cols)
        return self.layer_norm.layer_norm_musa(
            x_rows,
            self.ln.weight.view(-1),
            self.ln.bias.view(-1),
            float(self.ln.eps),
        ).view_as(x)