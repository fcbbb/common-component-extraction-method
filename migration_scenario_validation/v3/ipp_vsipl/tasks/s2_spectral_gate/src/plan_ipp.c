/* Real-FFT plan and CCS deinterleave (IPP backend). */
#include "spectral_gate_internal.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

typedef struct {
    IppsFFTSpec_R_32f *spec;
    Ipp8u *mem;
    Ipp8u *init;
    Ipp8u *work;
} sg_ipp_plan;

static void drop_plan(sg_plan *p)
{
    sg_ipp_plan *box;
    if (!p || !p->plan) return;
    box = (sg_ipp_plan *)p->plan;
    ippsFree(box->mem);
    ippsFree(box->init);
    ippsFree(box->work);
    free(box);
    p->plan = NULL;
}

int sg_plan_build(sg_plan *p, int nfft)
{
    int order = 0, spec_size = 0, init_size = 0, work_size = 0;
    sg_ipp_plan *box;

    if (!p || nfft < 8 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    p->nbin = nfft / 2 + 1;
    while ((1 << order) < nfft) ++order;

    box = (sg_ipp_plan *)calloc(1, sizeof(*box));
    if (!box) return -1;
    if (ippsFFTGetSize_R_32f(order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone,
                             &spec_size, &init_size, &work_size) != ippStsNoErr) {
        free(box);
        return -1;
    }
    box->mem = ippsMalloc_8u(spec_size);
    box->init = ippsMalloc_8u(init_size > 0 ? init_size : 1);
    box->work = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    p->frame = (float *)calloc((size_t)nfft, sizeof(float));
    p->bin_re = (float *)calloc((size_t)p->nbin, sizeof(float));
    p->bin_im = (float *)calloc((size_t)p->nbin, sizeof(float));
    p->scratch = (float *)calloc((size_t)nfft + 2, sizeof(float));
    if (!box->mem || !box->init || !box->work || !p->frame || !p->bin_re ||
        !p->bin_im || !p->scratch) {
        ippsFree(box->mem); ippsFree(box->init); ippsFree(box->work);
        free(box);
        free(p->frame); free(p->bin_re); free(p->bin_im); free(p->scratch);
        memset(p, 0, sizeof(*p));
        return -1;
    }
    if (ippsFFTInit_R_32f(&box->spec, order, IPP_FFT_NODIV_BY_ANY,
                          ippAlgHintNone, box->mem, box->init) != ippStsNoErr) {
        ippsFree(box->mem); ippsFree(box->init); ippsFree(box->work);
        free(box);
        free(p->frame); free(p->bin_re); free(p->bin_im); free(p->scratch);
        memset(p, 0, sizeof(*p));
        return -1;
    }
    p->plan = box;
    return 0;
}

void sg_plan_destroy(sg_plan *p)
{
    if (!p) return;
    drop_plan(p);
    free(p->frame);
    free(p->bin_re);
    free(p->bin_im);
    free(p->scratch);
    memset(p, 0, sizeof(*p));
}

int sg_plan_forward(sg_plan *p, const float *input)
{
    sg_ipp_plan *box;
    float *packed;
    int k, n;

    if (!p || !input || !p->plan) return -1;
    box = (sg_ipp_plan *)p->plan;
    packed = (float *)p->scratch;
    n = p->nfft;

    if (ippsFFTFwd_RToCCS_32f(input, packed, box->spec, box->work) != ippStsNoErr)
        return -1;

    /* IPP CCS is [R0, R1, ..., R(n/2), I(n/2-1), ..., I1, 0, 0].
     * The public contract is natural complex bins. */
    p->bin_re[0] = packed[0];
    p->bin_im[0] = 0.0f;
    for (k = 1; k < n / 2; ++k) {
        p->bin_re[k] = packed[k];
        p->bin_im[k] = packed[n - k];
    }
    p->bin_re[n / 2] = packed[n / 2];
    p->bin_im[n / 2] = 0.0f;
    return 0;
}