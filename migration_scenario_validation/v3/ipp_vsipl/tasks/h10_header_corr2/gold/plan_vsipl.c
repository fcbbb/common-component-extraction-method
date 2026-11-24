/* FFT plan lifecycle for the sonar lag profile (VSIPL backend). */
#include "sonar_lag_internal.h"

#include <vsip.h>

#include <stdlib.h>
#include <string.h>

int sl_plan_build(sl_plan *p, int nfft)
{
    if (!p || nfft < 2 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    p->fwd = vsip_ccfftop_create_f((vsip_length)nfft, 1.0f, VSIP_FFT_FWD,
                                   0, VSIP_ALG_SPACE);
    p->inv = vsip_ccfftop_create_f((vsip_length)nfft, 1.0f, VSIP_FFT_INV,
                                   0, VSIP_ALG_SPACE);
    p->scratch = vsip_cvcreate_f((vsip_length)nfft, VSIP_MEM_NONE);
    p->time_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->time_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_im = (float *)calloc((size_t)nfft, sizeof(float));
    if (!p->fwd || !p->inv || !p->scratch || !p->time_re || !p->time_im ||
        !p->freq_re || !p->freq_im) {
        sl_plan_destroy(p);
        return -1;
    }
    return 0;
}

void sl_plan_destroy(sl_plan *p)
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

int sl_plan_forward(sl_plan *p, const float *re, const float *im)
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

int sl_plan_inverse(sl_plan *p, float *re, float *im)
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

sl_state *sl_create(const sl_config *cfg)
{
    sl_state *st;

    if (!cfg || cfg->nref < 1 || cfg->nfft < 2 * cfg->nref - 1)
        return NULL;
    if ((cfg->nfft & (cfg->nfft - 1)) != 0) return NULL;

    st = (sl_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->nref = cfg->nref;
    if (sl_plan_build(&st->plan, cfg->nfft) != 0) {
        sl_destroy(st);
        return NULL;
    }
    st->ref_spec_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->ref_spec_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    if (!st->ref_spec_re || !st->ref_spec_im || !st->prod_re ||
        !st->prod_im) {
        sl_destroy(st);
        return NULL;
    }
    return st;
}

void sl_destroy(sl_state *st)
{
    if (!st) return;
    sl_plan_destroy(&st->plan);
    free(st->ref_spec_re);
    free(st->ref_spec_im);
    free(st->prod_re);
    free(st->prod_im);
    free(st);
}