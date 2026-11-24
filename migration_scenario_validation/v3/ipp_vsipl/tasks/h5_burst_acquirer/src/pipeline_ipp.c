/* Mixer, decimating FIR and frame scheduling (IPP backend). */
#include "burst_acq_internal.h"

#include <ipp.h>

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

int ba_push(ba_state *st,
            const float *in_re, const float *in_im, int nin,
            float *out_re, float *out_im, int out_cap,
            int *nout, ba_report *rep)
{
    Ipp32fc *in_iq = NULL, *nco_iq = NULL;
    Ipp32fc *mixed = NULL, *filtered = NULL;
    int new_dec, total_dec, frames, leftover, i, f, lags, done;
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

    if (nin > 0) {
        const int bytes = (int)((size_t)nin * sizeof(Ipp32fc));
        in_iq = (Ipp32fc *)ippsMalloc_8u(bytes);
        mixed = (Ipp32fc *)ippsMalloc_8u(bytes);
        filtered = (Ipp32fc *)ippsMalloc_8u(bytes);
        nco_iq = (Ipp32fc *)ippsMalloc_8u(
            (int)((size_t)st->cfg.nco_len * sizeof(Ipp32fc)));
        if (!in_iq || !mixed || !filtered || !nco_iq) {
            ippsFree(in_iq);
            ippsFree(mixed);
            ippsFree(filtered);
            ippsFree(nco_iq);
            return -1;
        }
        for (i = 0; i < st->cfg.nco_len; ++i) {
            nco_iq[i].re = st->nco_re[i];
            nco_iq[i].im = st->nco_im[i];
        }
        for (i = 0; i < nin; ++i) {
            in_iq[i].re = in_re[i];
            in_iq[i].im = in_im[i];
        }

        done = 0;
        while (done < nin) {
            int seg = st->cfg.nco_len - st->nco_phase;
            if (seg > nin - done) seg = nin - done;
            ippsMul_32fc(in_iq + done, nco_iq + st->nco_phase,
                         mixed + done, seg);
            st->nco_phase += seg;
            if (st->nco_phase >= st->cfg.nco_len)
                st->nco_phase -= st->cfg.nco_len;
            done += seg;
        }

        ippsFIR_32fc(mixed, filtered, nin,
                     (IppsFIRState_32fc *)st->ipp_fir);
        for (i = 0; i < nin; ++i) {
            const long idx = st->input_seen + i;
            if (idx >= st->M && idx % st->cfg.decim == 0) {
                st->dec_re[st->dec_n] = filtered[i].re;
                st->dec_im[st->dec_n] = filtered[i].im;
                ++st->dec_n;
            }
        }
        ippsFree(in_iq);
        ippsFree(mixed);
        ippsFree(filtered);
        ippsFree(nco_iq);
    }
    st->input_seen += nin;

    lags = 2 * st->cfg.nref - 1;
    for (f = 0; f < frames; ++f) {
        Ipp32fc *win = NULL, *ref = NULL, *dst = NULL;
        const int off = f * st->cfg.nref;
        win = (Ipp32fc *)ippsMalloc_8u(
            (int)((size_t)st->cfg.nref * sizeof(Ipp32fc)));
        ref = (Ipp32fc *)ippsMalloc_8u(
            (int)((size_t)st->cfg.nref * sizeof(Ipp32fc)));
        dst = (Ipp32fc *)ippsMalloc_8u(
            (int)((size_t)lags * sizeof(Ipp32fc)));
        if (!win || !ref || !dst) {
            ippsFree(win); ippsFree(ref); ippsFree(dst);
            return -1;
        }
        for (i = 0; i < st->cfg.nref; ++i) {
            win[i].re = st->dec_re[off + i];
            win[i].im = st->dec_im[off + i];
            ref[i].re = st->ref_re[i];
            ref[i].im = st->ref_im[i];
        }
        if (ippsCrossCorr_32fc(win, st->cfg.nref, ref, st->cfg.nref,
                               dst, lags, ippAlgAuto) != ippStsNoErr) {
            ippsFree(win); ippsFree(ref); ippsFree(dst);
            return -1;
        }
        for (i = 0; i < lags; ++i) {
            const float or_ = dst[i].re, oi = dst[i].im;
            const float m2 = or_ * or_ + oi * oi;
            const float m = sqrtf(m2);
            out_re[f * lags + i] = or_;
            out_im[f * lags + i] = oi;
            energy += (double)m2;
            if (m > peak) {
                peak = m;
                peak_index = f * lags + i;
            }
        }
        ippsFree(win);
        ippsFree(ref);
        ippsFree(dst);
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
