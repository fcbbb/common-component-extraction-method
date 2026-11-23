"""Project-authored MUSA positive control for ``b_l3_gqa``.

Evaluator-only.  Matches the reference grouped-query attention exactly:
four ``nn.Linear`` projections, attention over shared K/V heads with
``1/sqrt(head_dim)`` scaling, then the output projection.  Projections use a
naive MUSA kernel; attention uses one block per (batch, query head), one
thread per query position.  Must never be copied into ``work/``.
"""

import math

import torch
import torch.nn as nn
import torch_musa  # noqa: F401 - importing registers torch.musa
from torch_musa.utils.musa_extension import load_inline

gqa_source = r"""
#include <torch/extension.h>
#include <musa_runtime.h>

__global__ void linear_nt_kernel(const float* __restrict__ x,
                                 const float* __restrict__ weight,
                                 const float* __restrict__ bias,
                                 float* __restrict__ out,
                                 long long M, int N, int K) {
    const long long gid = static_cast<long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const long long total = M * N;
    if (gid >= total) {
        return;
    }
    const long long m = gid / N;
    const int n = static_cast<int>(gid - m * N);
    const float* xr = x + m * K;
    const float* wr = weight + static_cast<long long>(n) * K;
    float acc = bias[n];
    for (int k = 0; k < K; ++k) {
        acc += xr[k] * wr[k];
    }
    out[gid] = acc;
}

__global__ void gqa_attention_kernel(const float* __restrict__ q,
                                     const float* __restrict__ k,
                                     const float* __restrict__ v,
                                     float* __restrict__ out,
                                     int B, int L, int H, int H_kv,
                                     int head_dim, float scale) {
    const int bh = blockIdx.x;
    const int b = bh / H;
    const int h = bh - b * H;
    const int kvh = h / (H / H_kv);
    const int l = threadIdx.x;
    if (l >= L) {
        return;
    }

    const float* qv = q + ((static_cast<long long>(b) * L + l) * H + h) * head_dim;
    float scores[128];
    float m = -INFINITY;
    for (int j = 0; j < L; ++j) {
        const float* kv =
            k + ((static_cast<long long>(b) * L + j) * H_kv + kvh) * head_dim;
        float dot = 0.0f;
        for (int d = 0; d < head_dim; ++d) {
            dot += qv[d] * kv[d];
        }
        dot *= scale;
        scores[j] = dot;
        m = fmaxf(m, dot);
    }
    float sum = 0.0f;
    for (int j = 0; j < L; ++j) {
        scores[j] = expf(scores[j] - m);
        sum += scores[j];
    }
    const float inv = 1.0f / sum;
    for (int j = 0; j < L; ++j) {
        scores[j] *= inv;
    }

    float* ov = out + ((static_cast<long long>(b) * L + l) * H + h) * head_dim;
    for (int d = 0; d < head_dim; ++d) {
        float acc = 0.0f;
        for (int j = 0; j < L; ++j) {
            const float* vv =
                v + ((static_cast<long long>(b) * L + j) * H_kv + kvh) * head_dim;
            acc += scores[j] * vv[d];
        }
        ov[d] = acc;
    }
}

torch::Tensor gqa_musa(torch::Tensor x,
                       torch::Tensor qw, torch::Tensor qb,
                       torch::Tensor kw, torch::Tensor kb,
                       torch::Tensor vw, torch::Tensor vb,
                       torch::Tensor ow, torch::Tensor ob,
                       int64_t num_heads, int64_t num_kv_heads,
                       double scale) {
    auto xc = x.contiguous();
    TORCH_CHECK(xc.scalar_type() == torch::kFloat32, "gqa_musa expects float32");
    TORCH_CHECK(xc.dim() == 3, "gqa_musa expects (B, L, D)");
    const int B = static_cast<int>(xc.size(0));
    const int L = static_cast<int>(xc.size(1));
    const int D = static_cast<int>(xc.size(2));
    TORCH_CHECK(L <= 128, "gqa_musa control supports L <= 128");
    const int H = static_cast<int>(num_heads);
    const int H_kv = static_cast<int>(num_kv_heads);
    TORCH_CHECK(H % H_kv == 0 && D % H == 0, "invalid head configuration");
    const int head_dim = D / H;
    const int kv_dim = D * H_kv / H;
    const long long M = static_cast<long long>(B) * L;
    const int block = 256;

    auto q = torch::empty({M, static_cast<long long>(D)}, xc.options());
    auto k = torch::empty({M, static_cast<long long>(kv_dim)}, xc.options());
    auto v = torch::empty({M, static_cast<long long>(kv_dim)}, xc.options());
    auto attn = torch::empty({M, static_cast<long long>(D)}, xc.options());
    auto out = torch::empty({M, static_cast<long long>(D)}, xc.options());

    auto qwc = qw.contiguous();
    auto qbc = qb.contiguous();
    auto kwc = kw.contiguous();
    auto kbc = kb.contiguous();
    auto vwc = vw.contiguous();
    auto vbc = vb.contiguous();
    auto owc = ow.contiguous();
    auto obc = ob.contiguous();

    auto launch_linear = [&](float* dst, const float* w, const float* b, int n) {
        const long long total = M * n;
        const long long blocks = (total + block - 1) / block;
        linear_nt_kernel<<<static_cast<int>(blocks), block>>>(
            xc.data_ptr<float>(), w, b, dst, M, n, D);
    };

    launch_linear(q.data_ptr<float>(), qwc.data_ptr<float>(), qbc.data_ptr<float>(), D);
    launch_linear(k.data_ptr<float>(), kwc.data_ptr<float>(), kbc.data_ptr<float>(), kv_dim);
    launch_linear(v.data_ptr<float>(), vwc.data_ptr<float>(), vbc.data_ptr<float>(), kv_dim);

    gqa_attention_kernel<<<B * H, L>>>(
        q.data_ptr<float>(), k.data_ptr<float>(), v.data_ptr<float>(),
        attn.data_ptr<float>(), B, L, H, H_kv, head_dim,
        static_cast<float>(scale));

    {
        const long long total = M * D;
        const long long blocks = (total + block - 1) / block;
        linear_nt_kernel<<<static_cast<int>(blocks), block>>>(
            attn.data_ptr<float>(), owc.data_ptr<float>(), obc.data_ptr<float>(),
            out.data_ptr<float>(), M, D, D);
    }
    return out.view({B, L, D});
}
"""

gqa_cpp_source = (
    "torch::Tensor gqa_musa(torch::Tensor x, "
    "torch::Tensor qw, torch::Tensor qb, torch::Tensor kw, torch::Tensor kb, "
    "torch::Tensor vw, torch::Tensor vb, torch::Tensor ow, torch::Tensor ob, "
    "int64_t num_heads, int64_t num_kv_heads, double scale);"
)

_gqa_ext = load_inline(
    name="gqa_control",
    cpp_sources=gqa_cpp_source,
    musa_sources=gqa_source,
    functions=["gqa_musa"],
    verbose=True,
    extra_cflags=[""],
    extra_ldflags=[""],
)


class ModelNew(nn.Module):
    def __init__(self, d_model=1024, num_heads=16, num_kv_heads=4):
        super().__init__()
        assert num_heads % num_kv_heads == 0, "num_heads must be divisible by num_kv_heads"
        self.num_heads = num_heads
        self.num_kv_heads = num_kv_heads
        self.group_size = num_heads // num_kv_heads
        self.head_dim = d_model // num_heads
        # Parameter containers only; all compute runs in MUSA.  Construction
        # order matches the reference so seeded initialization is identical.
        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model * num_kv_heads // num_heads)
        self.v_proj = nn.Linear(d_model, d_model * num_kv_heads // num_heads)
        self.out_proj = nn.Linear(d_model, d_model)
        self.scale = 1.0 / math.sqrt(self.head_dim)
        self.gqa = _gqa_ext

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.gqa.gqa_musa(
            x,
            self.q_proj.weight, self.q_proj.bias,
            self.k_proj.weight, self.k_proj.bias,
            self.v_proj.weight, self.v_proj.bias,
            self.out_proj.weight, self.out_proj.bias,
            self.num_heads, self.num_kv_heads, self.scale,
        )