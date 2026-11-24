/* Mixer, decimating FIR and frame scheduling (VSIPL backend). */
#include "burst_acq_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static int ba_grow_dec(ba_state *st, int need)
{
    float *nre, *nim;
    int cap;

    if (need <= st->dec_cap) return 0;
    cap = st->dec_cap > 0 ? st->dec_cap : 32;
    while (cap < need) cap *= 2;
    nre = (float *)malloc((size_t)cap * sizeof(float));
    nim = (float *)malloc((size_t)cap * sizeof(float));
    if (!nre || !nim) {
        free(nre);
        free(nim);
        return -1;
    }
    if (st->dec_n > 0) {
        memcpy(nre, st->dec_re, (size_t)st->dec_n * sizeof(float));
        memcpy(nim, st->dec_im, (size_t)st->dec_n * sizeof(float));
    }
    free(st->dec_re);
    free(st->dec_im);
    st->dec_re = nre;
    st->dec_im = nim;
    st->dec_cap = cap;
    return 0;
}

static int ba_new_center_count(long start, int nin, int decim, int M)
{
    int i, count = 0;
    for (i = 0; i < nin; ++i) {
        const long idx = start + i;
        if (idx >= M && idx % decim == 0) ++count;
    }
    return count;
}

static void ba_append_hist(ba_state *st, float re, float im)
{
    if (st->hfill < st->M) {
        st->hist_re[st->hfill] = re;
        st->hist_im[st->hfill] = im;
        ++st->hfill;
    } else {
        if (st->M > 1) {
            memmove(st->hist_re, st->hist_re + 1,
                    (size_t)(st->M - 1) * sizeof(float));
            memmove(st->hist_im, st->hist_im + 1,
                    (size_t)(st->M - 1) * sizeof(float));
        }
        st->hist_re[st->M - 1] = re;
        st->hist_im[st->M - 1] = im;
    }
}

static void ba_filter_center(const ba_state *st, float *out_re,
                             float *out_im)
{
    float rr = 0.0f, ri = 0.0f;
    int t;

    for (t = 0; t < st->M; ++t) {
        const float hr = st->taps_re[t];
        const float hi = st->taps_im[t];
        const float xr = st->hist_re[st->M - 1 - t];
        const float xi = st->hist_im[st->M - 1 - t];
        rr += hr * xr - hi * xi;
        ri += hr * xi + hi * xr;
    }
    *out_re = rr;
    *out_im = ri;
}

int ba_push(ba_state *st,
            const float *in_re, const float *in_im, int nin,
            float *out_re, float *out_im, int out_cap,
            int *nout, ba_report *rep)
{
    int new_dec, total_dec, frames, leftover, i, f, lags;
    double energy = 0.0;
    float peak = -1.0f;
    int peak_index = 0;

    if (!st || !st->ready || !nout || nin < 0 || out_cap < 0)
        return -1;
    if (nin > 0 && (!in_re || !in_im)) return -1;
    if (out_cap > 0 && (!out_re || !out_im)) return -1;

    new_dec = ba_new_center_count(st->input_seen, nin,
                                  st->cfg.decim, st->M);
    total_dec = st->dec_n + new_dec;
    frames = total_dec / st->cfg.nref;
    if (frames > out_cap) return -1;
    if (ba_grow_dec(st, total_dec) != 0) return -1;

    for (i = 0; i < nin; ++i) {
        const long idx = st->input_seen + i;
        const int tap = st->nco_phase;
        const float xr = in_re[i], xi = in_im[i];
        const float nr = st->nco_re[tap], ni = st->nco_im[tap];
        const float mr = xr * nr - xi * ni;
        const float mi = xr * ni + xi * nr;
        float yr, yi;

        st->nco_phase = (st->nco_phase + 1) % st->cfg.nco_len;
        ba_append_hist(st, mr, mi);
        if (idx >= st->M && idx % st->cfg.decim == 0) {
            ba_filter_center(st, &yr, &yi);
            st->dec_re[st->dec_n] = yr;
            st->dec_im[st->dec_n] = yi;
            ++st->dec_n;
        }
    }
    st->input_seen += nin;

    lags = 2 * st->cfg.nref - 1;
    for (f = 0; f < frames; ++f) {
        const int off = f * st->cfg.nref;
        if (ba_correlate_frame(st, st->dec_re + off, st->dec_im + off,
                               out_re + f * lags,
                               out_im + f * lags) != 0)
            return -1;
        for (i = 0; i < lags; ++i) {
            const float or_ = out_re[f * lags + i];
            const float oi = out_im[f * lags + i];
            const float m2 = or_ * or_ + oi * oi;
            const float m = sqrtf(m2);
            energy += (double)m2;
            if (m > peak) {
                peak = m;
                peak_index = f * lags + i;
            }
        }
    }

    leftover = st->dec_n - frames * st->cfg.nref;
    if (leftover > 0) {
        memmove(st->dec_re, st->dec_re + frames * st->cfg.nref,
                (size_t)leftover * sizeof(float));
        memmove(st->dec_im, st->dec_im + frames * st->cfg.nref,
                (size_t)leftover * sizeof(float));
    }
    st->dec_n = leftover;

    *nout = frames;
    if (rep) {
        rep->peak = (peak < 0.0f) ? 0.0f : peak;
        rep->peak_index = peak_index;
        rep->energy = (float)energy;
        rep->frames = frames;
    }
    return 0;
}