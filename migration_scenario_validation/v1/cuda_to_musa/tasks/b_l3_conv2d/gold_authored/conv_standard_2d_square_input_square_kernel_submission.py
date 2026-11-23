"""Project-authored MUSA positive control for ``b_l3_conv2d``.

Evaluator-only.  Direct convolution matching the reference ``nn.Conv2d(3, 96,
kernel_size=11, stride=4, padding=2)`` applied to a (256, 3, 224, 224) input.
The kernel walks every (batch, out-channel, out-row, out-col) once.
Must never be copied into ``work/``.

Precision note: torch_musa 2.11 runs ``nn.Conv2d`` through muDNN with TF32
enabled by default (``torch.backends.mudnn.allow_tf32 is True``), while
``torch.backends.musa.matmul.allow_tf32`` is already False.  A true-fp32
kernel then differs from that TF32 reference by up to 5.0e-4, past the
harness's atol=rtol=1e-4.  Measured on the S4000 against a float64 CPU
ground truth, this kernel is exact to 1.0e-6 while the TF32 reference is
4.1e-4 off, so the fp32 side is the accurate one.  muDNN is therefore pinned
to fp32 here (module level, so it also covers the reference evaluation that
``utils/correctness.py`` runs); the two then agree to 1.6e-6.
"""

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

# Compare against true fp32 conv, not muDNN's default TF32 path (see above).
torch.backends.mudnn.allow_tf32 = False

conv2d_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void conv2d_kernel(const float* __restrict__ x,
                              const float* __restrict__ weight,
                              const float* __restrict__ bias,
                              float* __restrict__ out,
                              int N, int C, int H, int W,
                              int O, int KH, int KW,
                              int stride, int pad, int OH, int OW) {
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
            const int ih = oh * stride - pad + kh;
            if (ih < 0 || ih >= H) {
                continue;
            }
            for (int kw = 0; kw < KW; ++kw) {
                const int iw = ow * stride - pad + kw;
                if (iw < 0 || iw >= W) {
                    continue;
                }
                const float xv = x[((static_cast<long long>(n) * C + ic) * H + ih) * W + iw];
                const float wv =
                    weight[((static_cast<long long>(oc) * C + ic) * KH + kh) * KW + kw];
                acc += xv * wv;
            }
        }
    }
    out[gid] = acc;
}

torch::Tensor conv2d_musa(torch::Tensor x, torch::Tensor weight, torch::Tensor bias,
                          int64_t stride, int64_t pad) {
    auto xc = x.contiguous();
    auto wc = weight.contiguous();
    auto bc = bias.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "conv2d_musa expects float32");
    TORCH_CHECK(xc.dim() == 4 && wc.dim() == 4, "conv2d_musa expects NCHW input and OIHW weight");
    const int N = static_cast<int>(xc.size(0));
    const int C = static_cast<int>(xc.size(1));
    const int H = static_cast<int>(xc.size(2));
    const int W = static_cast<int>(xc.size(3));
    const int O = static_cast<int>(wc.size(0));
    const int KH = static_cast<int>(wc.size(2));
    const int KW = static_cast<int>(wc.size(3));
    TORCH_CHECK(wc.size(1) == C, "conv2d_musa channel mismatch");
    const int OH = static_cast<int>((H + 2 * pad - KH) / stride + 1);
    const int OW = static_cast<int>((W + 2 * pad - KW) / stride + 1);
    TORCH_CHECK(OH > 0 && OW > 0, "conv2d_musa empty output");
    auto out = torch::empty({N, O, OH, OW}, xc.options());
    const long long total = static_cast<long long>(N) * O * OH * OW;
    const int block = 256;
    const long long blocks = (total + block - 1) / block;
    TORCH_CHECK(blocks <= 2147483647LL, "grid too large");
    conv2d_kernel<<<static_cast<int>(blocks), block>>>(
        xc.data_ptr<float>(), wc.data_ptr<float>(), bc.data_ptr<float>(),
        out.data_ptr<float>(), N, C, H, W, O, KH, KW,
        static_cast<int>(stride), static_cast<int>(pad), OH, OW);
    return out;
}
"""

conv2d_cpp_source = (
    "torch::Tensor conv2d_musa(torch::Tensor x, torch::Tensor weight, torch::Tensor bias, "
    "int64_t stride, int64_t pad);"
)

_conv2d_ext = load_inline(
    name="conv2d_control",
    cpp_sources=conv2d_cpp_source,
    musa_sources=conv2d_source,
    functions=["conv2d_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, num_classes=1000):
        super().__init__()
        # Parameter container only; the convolution itself runs in MUSA.
        self.conv1 = nn.Conv2d(
            in_channels=3, out_channels=96, kernel_size=11, stride=4, padding=2
        )
        self.conv2d = _conv2d_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv2d.conv2d_musa(
            x, self.conv1.weight, self.conv1.bias, 4, 2
        )