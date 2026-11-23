/* Real-FFT plan (VSIPL backend). */
#include "spectral_gate_internal.h"

#include <vsip.h>

#include <stdlib.h>
#include <string.h>

int sg_plan_build(sg_plan *p, int nfft)
{
    if (!p || nfft < 8 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    p->nbin = nfft / 2 + 1;
    p->plan = vsip_rcfftop_create_f((vsip_length)nfft, 1.0f, 0,
                                    VSIP_ALG_SPACE);
    p->frame = (float *)calloc((size_t)nfft, sizeof(float));
    p->bin_re = (float *)calloc((size_t)p->nbin, sizeof(float));
    p->bin_im = (float *)calloc((size_t)p->nbin, sizeof(float));
    p->scratch = vsip_cvcreate_f((vsip_length)p->nbin, VSIP_MEM_NONE);
    if (!p->plan || !p->frame || !p->bin_re || !p->bin_im || !p->scratch) {
        sg_plan_destroy(p);
        return -1;
    }
    return 0;
}

void sg_plan_destroy(sg_plan *p)
{
    if (!p) return;
    if (p->plan) vsip_fft_destroy_f((vsip_fft_f *)p->plan);
    if (p->scratch) vsip_cvalldestroy_f((vsip_cvview_f *)p->scratch);
    free(p->frame);
    free(p->bin_re);
    free(p->bin_im);
    memset(p, 0, sizeof(*p));
}

int sg_plan_forward(sg_plan *p, const float *input)
{
    vsip_vview_f *real;
    vsip_cvview_f *spec;
    int i;

    if (!p || !input || !p->plan) return -1;
    real = vsip_vcreate_f((vsip_length)p->nfft, VSIP_MEM_NONE);
    spec = (vsip_cvview_f *)p->scratch;
    if (!real) return -1;

    for (i = 0; i < p->nfft; ++i)
        vsip_vput_f(real, (vsip_index)i, input[i]);
    vsip_rcfftop_f((vsip_fft_f *)p->plan, real, spec);
    for (i = 0; i < p->nbin; ++i) {
        vsip_cscalar_f z = vsip_cvget_f(spec, (vsip_index)i);
        p->bin_re[i] = z.r;
        p->bin_im[i] = z.i;
    }
    vsip_valldestroy_f(real);
    return 0;
}