/* FFT plan for the burst-correlation stage (VSIPL backend). */
#include "burst_acq_internal.h"

#include <vsip.h>

#include <stdlib.h>
#include <string.h>

int ba_plan_build(ba_plan *p, int nfft)
{
    if (!p || nfft < 2 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    p->fwd = vsip_ccfftop_create_f((vsip_length)nfft, 1.0f,
                                   VSIP_FFT_FWD, 0, VSIP_ALG_SPACE);
    p->inv = vsip_ccfftop_create_f((vsip_length)nfft, 1.0f,
                                   VSIP_FFT_INV, 0, VSIP_ALG_SPACE);
    p->scratch = vsip_cvcreate_f((vsip_length)nfft, VSIP_MEM_NONE);
    p->time_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->time_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_im = (float *)calloc((size_t)nfft, sizeof(float));
    if (!p->fwd || !p->inv || !p->scratch || !p->time_re || !p->time_im ||
        !p->freq_re || !p->freq_im) {
        ba_plan_destroy(p);
        return -1;
    }
    return 0;
}

void ba_plan_destroy(ba_plan *p)
{
    if (!p) return;
    if (p->fwd) vsip_fft_destroy_f((vsip_fft_f *)p->fwd);
    if (p->inv) vsip_fft_destroy_f((vsip_fft_f *)p->inv);
    if (p->scratch) vsip_cvalldestroy_f((vsip_cvview_f *)p->scratch);
    free(p->time_re);
    free(p->time_im);
    free(p->freq_re);
    free(p->freq_im);
    memset(p, 0, sizeof(*p));
}

int ba_plan_forward(ba_plan *p, const float *re, const float *im)
{
    vsip_cvview_f *v;
    int i;

    if (!p || !re || !im || !p->fwd) return -1;
    v = (vsip_cvview_f *)p->scratch;
    for (i = 0; i < p->nfft; ++i)
        vsip_cvput_f(v, (vsip_index)i, vsip_cmplx_f(re[i], im[i]));
    vsip_ccfftop_f((vsip_fft_f *)p->fwd, v, v);
    for (i = 0; i < p->nfft; ++i) {
        const vsip_cscalar_f z = vsip_cvget_f(v, (vsip_index)i);
        p->freq_re[i] = z.r;
        p->freq_im[i] = z.i;
    }
    return 0;
}

int ba_plan_inverse(ba_plan *p, float *re, float *im)
{
    vsip_cvview_f *v;
    const float scale = 1.0f / (float)p->nfft;
    int i;

    if (!p || !re || !im || !p->inv) return -1;
    v = (vsip_cvview_f *)p->scratch;
    for (i = 0; i < p->nfft; ++i)
        vsip_cvput_f(v, (vsip_index)i,
                     vsip_cmplx_f(p->freq_re[i], p->freq_im[i]));
    vsip_ccfftop_f((vsip_fft_f *)p->inv, v, v);
    for (i = 0; i < p->nfft; ++i) {
        const vsip_cscalar_f z = vsip_cvget_f(v, (vsip_index)i);
        re[i] = z.r * scale;
        im[i] = z.i * scale;
    }
    return 0;
}

int ba_correlate_frame(ba_state *st,
                       const float *frame_re, const float *frame_im,
                       float *out_re, float *out_im)
{
    int i, lags;

    if (!st || !frame_re || !frame_im || !out_re || !out_im) return -1;
    lags = 2 * st->cfg.nref - 1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.time_re, frame_re,
           (size_t)st->cfg.nref * sizeof(float));
    memcpy(st->plan.time_im, frame_im,
           (size_t)st->cfg.nref * sizeof(float));
    if (ba_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
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
    if (ba_plan_inverse(&st->plan, st->plan.time_re,
                        st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < lags; ++i) {
        out_re[i] = st->plan.time_re[i];
        out_im[i] = st->plan.time_im[i];
    }
    return 0;
}