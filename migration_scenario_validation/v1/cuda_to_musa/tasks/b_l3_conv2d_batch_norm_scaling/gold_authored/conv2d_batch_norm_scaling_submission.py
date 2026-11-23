"""Project-authored MUSA positive control for ``b_l3_conv2d_batch_norm_scaling``.

Evaluator-only.  Matches ``nn.Conv2d(8, 64, 3)`` -> ``nn.BatchNorm2d(64)`` in
training mode -> multiply by 2.0 on a (128, 8, 128, 128) float32 input.
Three kernels: direct convolution, per-channel batch statistics (double
accumulation), and the normalize + affine + scale epilogue.  Must never be
copied into ``work/``.

Precision note: torch_musa 2.11 runs ``nn.Conv2d`` through muDNN with TF32
enabled by default, while a true-fp32 kernel differs from that reference by
~5e-4, past atol=rtol=1e-4.  This control pins muDNN to fp32 at module level
(the same fix as ``b_l3_conv2d``), which also covers the reference forward
that ``utils/correctness.py`` runs in this process.

Memory: the convolution output is 128*64*126*126 = 130,056,192 floats
(520 MB); the input is 67 MB, so kernel buffers plus the evaluator's
``torch.allclose`` temporaries stay far below the 47.90 GB card.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

# Compare against true fp32 conv, not muDNN's default TF32 path (see above).
torch.backends.mudnn.allow_tf32 = False

fused_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void conv2d_kernel(const float* __restrict__ x,
                              const float* __restrict__ weight,
                              const float* __restrict__ bias,
                              float* __restrict__ out,
                              int N, int C, int H, int W,
                              int O, int KH, int KW, int OH, int OW) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const long long total = static_cast<long long>(N) * O * OH * OW;
    if (gid >= total) {
        return;
    }
    int ow = static_cast<int>(gid % OW);
    long long t = gid / OW;
    int oh = static_cast<int>(t % OH);
    t /= OH;
    int oc = static_cast<int>(t % O);
    int n = static_cast<int>(t / O);

    float acc = bias[oc];
    for (int ic = 0; ic < C; ++ic) {
        for (int kh = 0; kh < KH; ++kh) {
            const int ih = oh + kh;
            for (int kw = 0; kw < KW; ++kw) {
                const int iw = ow + kw;
                const float xv = x[((static_cast<long long>(n) * C + ic) * H + ih) * W + iw];
                const float wv =
                    weight[((static_cast<long long>(oc) * C + ic) * KH + kh) * KW + kw];
                acc += xv * wv;
            }
        }
    }
    out[gid] = acc;
}

// Per-channel batch mean / biased variance for BatchNorm2d in training mode.
__global__ void bn_stats_kernel(const float* __restrict__ y,
                                float* __restrict__ mean,
                                float* __restrict__ invstd,
                                int N, int O, int OH, int OW,
                                float eps) {
    const int oc = blockIdx.x;
    const int tid = threadIdx.x;
    const int nthreads = blockDim.x;
    __shared__ double s_sum[256];
    __shared__ double s_sq[256];

    const long long plane = static_cast<long long>(OH) * OW;
    const long long per_channel = static_cast<long long>(N) * plane;

    double sum = 0.0;
    double sq = 0.0;
    for (long long n = 0; n < N; ++n) {
        const float* base = y + (static_cast<long long>(n) * O + oc) * plane;
        for (long long i = tid; i < plane; i += nthreads) {
            const double v = static_cast<double>(base[i]);
            sum += v;
            sq += v * v;
        }
    }
    s_sum[tid] = sum;
    s_sq[tid] = sq;
    __syncthreads();
    for (int stride = nthreads >> 1; stride > 0; stride >>= 1) {
        if (tid < stride) {
            s_sum[tid] += s_sum[tid + stride];
            s_sq[tid] += s_sq[tid + stride];
        }
        __syncthreads();
    }
    if (tid == 0) {
        const double m = s_sum[0] / static_cast<double>(per_channel);
        double var = s_sq[0] / static_cast<double>(per_channel) - m * m;
        if (var < 0.0) {
            var = 0.0;
        }
        mean[oc] = static_cast<float>(m);
        invstd[oc] = static_cast<float>(1.0 / sqrt(var + static_cast<double>(eps)));
    }
}

// out = ((y - mean[c]) * invstd[c] * gamma[c] + beta[c]) * scale
__global__ void bn_scale_kernel(const float* __restrict__ y,
                                const float* __restrict__ mean,
                                const float* __restrict__ invstd,
                                const float* __restrict__ gamma,
                                const float* __restrict__ beta,
                                float* __restrict__ out,
                                long long total, int O, long long plane,
                                float scale) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (gid >= total) {
        return;
    }
    const int oc = static_cast<int>((gid / plane) % O);
    const float v = (y[gid] - mean[oc]) * invstd[oc] * gamma[oc] + beta[oc];
    out[gid] = v * scale;
}

torch::Tensor conv2d_bn_scale_musa(torch::Tensor x, torch::Tensor weight, torch::Tensor bias,
                                   torch::Tensor gamma, torch::Tensor beta, double scale) {
    auto xc = x.contiguous();
    auto wc = weight.contiguous();
    auto bc = bias.contiguous();
    auto gc = gamma.contiguous();
    auto betac = beta.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "conv2d_bn_scale_musa expects float32");
    TORCH_CHECK(xc.dim() == 4 && wc.dim() == 4, "conv2d_bn_scale_musa expects NCHW input and OIHW weight");
    const int N = static_cast<int>(xc.size(0));
    const int C = static_cast<int>(xc.size(1));
    const int H = static_cast<int>(xc.size(2));
    const int W = static_cast<int>(xc.size(3));
    const int O = static_cast<int>(wc.size(0));
    const int KH = static_cast<int>(wc.size(2));
    const int KW = static_cast<int>(wc.size(3));
    TORCH_CHECK(wc.size(1) == C, "conv2d_bn_scale_musa channel mismatch");
    const int OH = H - KH + 1;
    const int OW = W - KW + 1;
    TORCH_CHECK(OH > 0 && OW > 0, "conv2d_bn_scale_musa empty output");

    auto y = torch::empty({N, O, OH, OW}, xc.options());
    const long long total = static_cast<long long>(N) * O * OH * OW;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    conv2d_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), wc.data_ptr<float>(), bc.data_ptr<float>(),
        y.data_ptr<float>(), N, C, H, W, O, KH, KW, OH, OW);

    auto mean = torch::empty({O}, xc.options());
    auto invstd = torch::empty({O}, xc.options());
    bn_stats_kernel<<<O, 256>>>(
        y.data_ptr<float>(), mean.data_ptr<float>(), invstd.data_ptr<float>(),
        N, O, OH, OW, 1e-5f);

    auto out = torch::empty({N, O, OH, OW}, xc.options());
    bn_scale_kernel<<<static_cast<int>(blocks), block>>>(
        y.data_ptr<float>(), mean.data_ptr<float>(), invstd.data_ptr<float>(),
        gc.data_ptr<float>(), betac.data_ptr<float>(), out.data_ptr<float>(),
        total, O, static_cast<long long>(OH) * OW, static_cast<float>(scale));
    return out;
}
"""

fused_cpp_source = (
    "torch::Tensor conv2d_bn_scale_musa(torch::Tensor x, torch::Tensor weight, torch::Tensor bias, "
    "torch::Tensor gamma, torch::Tensor beta, double scale);"
)

_fused_ext = load_inline(
    name="conv2d_batch_norm_scaling_control",
    cpp_sources=fused_cpp_source,
    musa_sources=fused_source,
    functions=["conv2d_bn_scale_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, scaling_factor):
        super().__init__()
        # Parameter containers only; the arithmetic runs in the MUSA kernels.
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size)
        self.bn = nn.BatchNorm2d(out_channels)
        self.scaling_factor = float(scaling_factor)
        self.fused = _fused_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fused.conv2d_bn_scale_musa(
            x,
            self.conv.weight,
            self.conv.bias,
            self.bn.weight,
            self.bn.bias,
            self.scaling_factor,
        )