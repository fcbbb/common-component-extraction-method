/* Streaming frame assembly, FFT correlation and output scheduling
 * (VSIPL backend). */
#include "stream_lag_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

int sc_process_frame(sc_state *st,
                     const float *frame_re, const float *frame_im,
                     float *out_re, float *out_im)
{
    int i, lags;

    if (!st || !frame_re || !frame_im || !out_re || !out_im) return -1;
    lags = 2 * st->nref - 1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.time_re, frame_re, (size_t)st->nref * sizeof(float));
    memcpy(st->plan.time_im, frame_im, (size_t)st->nref * sizeof(float));

    if (sc_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < st->plan.nfft; ++i) {
        const float ar = st->plan.freq_re[i], ai = st->plan.freq_im[i];
        const float br = st->ref_spec_re[i], bi = st->ref_spec_im[i];
        st->prod_re[i] = ar * br - ai * bi;
        st->prod_im[i] = ar * bi + ai * br;
    }
    memcpy(st->plan.freq_re, st->prod_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.freq_im, st->prod_im,
           (size_t)st->plan.nfft * sizeof(float));

    if (sc_plan_inverse(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < lags; ++i) {
        out_re[i] = st->plan.time_re[i];
        out_im[i] = st->plan.time_im[i];
    }
    return 0;
}

static int sc_grow_pending(sc_state *st, int need)
{
    float *nre, *nim;
    int cap;

    if (need <= st->pending_cap) return 0;
    cap = st->pending_cap > 0 ? st->pending_cap : 32;
    while (cap < need) cap *= 2;

    nre = (float *)malloc((size_t)cap * sizeof(float));
    nim = (float *)malloc((size_t)cap * sizeof(float));
    if (!nre || !nim) {
        free(nre);
        free(nim);
        return -1;
    }
    if (st->pending_n > 0) {
        memcpy(nre, st->pending_re,
               (size_t)st->pending_n * sizeof(float));
        memcpy(nim, st->pending_im,
               (size_t)st->pending_n * sizeof(float));
    }
    free(st->pending_re);
    free(st->pending_im);
    st->pending_re = nre;
    st->pending_im = nim;
    st->pending_cap = cap;
    return 0;
}

int sc_process(sc_state *st,
               const float *in_re, const float *in_im, int nin,
               float *out_re, float *out_im, int out_cap,
               int *nout, sc_report *rep)
{
    int total, blocks, leftover, b, i, lags;
    double energy = 0.0;
    float peak = -1.0f;
    int peak_index = 0;

    if (!st || !nout || nin < 0 || out_cap < 0) return -1;
    if (nin > 0 && (!in_re || !in_im)) return -1;
    if (out_cap > 0 && (!out_re || !out_im)) return -1;
    if (nin > 0x7fffffff - st->pending_n) return -1;

    total = st->pending_n + nin;
    blocks = total / st->nref;
    if (blocks > out_cap) return -1;

    if (sc_grow_pending(st, total) != 0) return -1;
    if (nin > 0) {
        memcpy(st->pending_re + st->pending_n, in_re,
               (size_t)nin * sizeof(float));
        memcpy(st->pending_im + st->pending_n, in_im,
               (size_t)nin * sizeof(float));
    }
    st->pending_n = total;
    lags = 2 * st->nref - 1;

    for (b = 0; b < blocks; ++b) {
        const int off = b * st->nref;
        if (sc_process_frame(st, st->pending_re + off,
                             st->pending_im + off,
                             out_re + b * lags, out_im + b * lags) != 0)
            return -1;
        for (i = 0; i < lags; ++i) {
            const float or_ = out_re[b * lags + i];
            const float oi = out_im[b * lags + i];
            const float m2 = or_ * or_ + oi * oi;
            const float m = sqrtf(m2);
            energy += (double)m2;
            if (m > peak) {
                peak = m;
                peak_index = b * lags + i;
            }
        }
    }

    leftover = total - blocks * st->nref;
    if (leftover > 0)
        memmove(st->pending_re, st->pending_re + blocks * st->nref,
                (size_t)leftover * sizeof(float));
    if (leftover > 0)
        memmove(st->pending_im, st->pending_im + blocks * st->nref,
                (size_t)leftover * sizeof(float));
    st->pending_n = leftover;

    *nout = blocks;
    if (rep) {
        rep->peak = (peak < 0.0f) ? 0.0f : peak;
        rep->peak_index = peak_index;
        rep->energy = (float)energy;
    }
    return 0;
}