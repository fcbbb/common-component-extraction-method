/* IPP plan lifecycle for the radar correlation layer. */
#include "radar_pipeline_internal.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

typedef struct {
    IppsFFTSpec_C_32fc *spec;
    Ipp8u *mem;
    Ipp8u *work;
} rpc_spec;

static void rpc_drop_spec(void **slot)
{
    rpc_spec *box;
    if (!slot || !*slot) return;
    box = (rpc_spec *)*slot;
    ippsFree(box->mem);
    ippsFree(box->work);
    free(box);
    *slot = NULL;
}

static int rpc_make_spec(void **slot, int order, int flag)
{
    int spec_size = 0, init_size = 0, work_size = 0;
    Ipp8u *init = NULL;
    rpc_spec *box;

    if (ippsFFTGetSize_C_32fc(order, flag, ippAlgHintNone,
                              &spec_size, &init_size, &work_size) != ippStsNoErr)
        return -1;

    box = (rpc_spec *)calloc(1, sizeof(*box));
    if (!box) return -1;
    box->mem = ippsMalloc_8u(spec_size);
    init = ippsMalloc_8u(init_size > 0 ? init_size : 1);
    box->work = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    if (!box->mem || !init || !box->work) {
        ippsFree(init);
        rpc_drop_spec((void **)&box);
        return -1;
    }

    if (ippsFFTInit_C_32fc(&box->spec, order, flag, ippAlgHintNone,
                           box->mem, init) != ippStsNoErr) {
        ippsFree(init);
        rpc_drop_spec((void **)&box);
        return -1;
    }
    ippsFree(init);
    *slot = box;
    return 0;
}

static void rpc_plan_free_buffers(rpc_plan *p)
{
    if (!p) return;
    if (p->scratch) ippsFree(p->scratch);
    free(p->time_re);
    free(p->time_im);
    free(p->freq_re);
    free(p->freq_im);
    p->scratch = NULL;
    p->time_re = p->time_im = NULL;
    p->freq_re = p->freq_im = NULL;
}

int rpc_plan_build(rpc_plan *p, int nfft)
{
    int order = 0;

    if (!p || nfft < 2 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    while ((1 << order) < nfft) ++order;

    if (rpc_make_spec(&p->fwd, order, IPP_FFT_NODIV_BY_ANY) != 0) {
        rpc_plan_destroy(p);
        return -1;
    }
    if (rpc_make_spec(&p->inv, order, IPP_FFT_DIV_INV_BY_N) != 0) {
        rpc_plan_destroy(p);
        return -1;
    }

    p->time_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->time_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->scratch = ippsMalloc_8u((int)((size_t)nfft * sizeof(Ipp32fc)));
    if (!p->time_re || !p->time_im || !p->freq_re || !p->freq_im ||
        !p->scratch) {
        rpc_plan_destroy(p);
        return -1;
    }
    return 0;
}

void rpc_plan_destroy(rpc_plan *p)
{
    if (!p) return;
    rpc_drop_spec(&p->fwd);
    rpc_drop_spec(&p->inv);
    rpc_plan_free_buffers(p);
}

int rpc_plan_forward(rpc_plan *p, const float *re, const float *im)
{
    rpc_spec *box;
    Ipp32fc *work;
    int i;

    if (!p || !re || !im || !p->fwd) return -1;
    box = (rpc_spec *)p->fwd;
    work = (Ipp32fc *)p->scratch;
    for (i = 0; i < p->nfft; ++i) {
        work[i].re = re[i];
        work[i].im = im[i];
    }
    if (ippsFFTFwd_CToC_32fc(work, work, box->spec, box->work) != ippStsNoErr)
        return -1;
    for (i = 0; i < p->nfft; ++i) {
        p->freq_re[i] = work[i].re;
        p->freq_im[i] = work[i].im;
    }
    return 0;
}

int rpc_plan_inverse(rpc_plan *p, float *re, float *im)
{
    rpc_spec *box;
    Ipp32fc *work;
    int i;

    if (!p || !re || !im || !p->inv) return -1;
    box = (rpc_spec *)p->inv;
    work = (Ipp32fc *)p->scratch;
    for (i = 0; i < p->nfft; ++i) {
        work[i].re = p->freq_re[i];
        work[i].im = p->freq_im[i];
    }
    if (ippsFFTInv_CToC_32fc(work, work, box->spec, box->work) != ippStsNoErr)
        return -1;
    for (i = 0; i < p->nfft; ++i) {
        re[i] = work[i].re;
        im[i] = work[i].im;
    }
    return 0;
}

rpc_state *rpc_create(const rpc_config *cfg)
{
    rpc_state *st;

    if (!cfg || cfg->npulse < 1 || cfg->nfft < 2 * cfg->npulse - 1)
        return NULL;
    if ((cfg->nfft & (cfg->nfft - 1)) != 0) return NULL;

    st = (rpc_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->npulse = cfg->npulse;
    if (rpc_plan_build(&st->plan, cfg->nfft) != 0) {
        rpc_destroy(st);
        return NULL;
    }
    st->rep_spec_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->rep_spec_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    if (!st->rep_spec_re || !st->rep_spec_im || !st->prod_re || !st->prod_im) {
        rpc_destroy(st);
        return NULL;
    }
    return st;
}

void rpc_destroy(rpc_state *st)
{
    if (!st) return;
    rpc_plan_destroy(&st->plan);
    free(st->rep_spec_re);
    free(st->rep_spec_im);
    free(st->prod_re);
    free(st->prod_im);
    free(st);
}