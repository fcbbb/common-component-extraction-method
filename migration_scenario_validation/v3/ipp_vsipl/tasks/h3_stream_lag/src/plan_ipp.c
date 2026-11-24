/* FFT plan lifecycle for the streaming lag profile (IPP backend). */
#include "stream_lag_internal.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

typedef struct {
    IppsFFTSpec_C_32fc *spec;
    Ipp8u *mem;
    Ipp8u *work;
} sc_spec;

static void sc_drop_spec(void **slot)
{
    sc_spec *box;

    if (!slot || !*slot) return;
    box = (sc_spec *)*slot;
    ippsFree(box->mem);
    ippsFree(box->work);
    free(box);
    *slot = NULL;
}

static int sc_make_spec(void **slot, int order, int flag)
{
    int spec_size = 0, init_size = 0, work_size = 0;
    Ipp8u *init = NULL;
    sc_spec *box;

    if (ippsFFTGetSize_C_32fc(order, flag, ippAlgHintNone,
                              &spec_size, &init_size, &work_size) != ippStsNoErr)
        return -1;

    box = (sc_spec *)calloc(1, sizeof(*box));
    if (!box) return -1;
    box->mem = ippsMalloc_8u(spec_size);
    init = ippsMalloc_8u(init_size > 0 ? init_size : 1);
    box->work = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    if (!box->mem || !init || !box->work) {
        ippsFree(init);
        sc_drop_spec((void **)&box);
        return -1;
    }
    if (ippsFFTInit_C_32fc(&box->spec, order, flag, ippAlgHintNone,
                           box->mem, init) != ippStsNoErr) {
        ippsFree(init);
        sc_drop_spec((void **)&box);
        return -1;
    }
    ippsFree(init);
    *slot = box;
    return 0;
}

static void sc_free_buffers(sc_plan *p)
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

int sc_plan_build(sc_plan *p, int nfft)
{
    int order = 0;

    if (!p || nfft < 2 || (nfft & (nfft - 1)) != 0) return -1;
    memset(p, 0, sizeof(*p));
    p->nfft = nfft;
    while ((1 << order) < nfft) ++order;

    if (sc_make_spec(&p->fwd, order, IPP_FFT_NODIV_BY_ANY) != 0 ||
        sc_make_spec(&p->inv, order, IPP_FFT_DIV_INV_BY_N) != 0) {
        sc_plan_destroy(p);
        return -1;
    }

    p->time_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->time_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_re = (float *)calloc((size_t)nfft, sizeof(float));
    p->freq_im = (float *)calloc((size_t)nfft, sizeof(float));
    p->scratch = ippsMalloc_8u((int)((size_t)nfft * sizeof(Ipp32fc)));
    if (!p->time_re || !p->time_im || !p->freq_re || !p->freq_im ||
        !p->scratch) {
        sc_plan_destroy(p);
        return -1;
    }
    return 0;
}

void sc_plan_destroy(sc_plan *p)
{
    if (!p) return;
    sc_drop_spec(&p->fwd);
    sc_drop_spec(&p->inv);
    sc_free_buffers(p);
}

int sc_plan_forward(sc_plan *p, const float *re, const float *im)
{
    sc_spec *box;
    Ipp32fc *work;
    int i;

    if (!p || !re || !im || !p->fwd) return -1;
    box = (sc_spec *)p->fwd;
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

int sc_plan_inverse(sc_plan *p, float *re, float *im)
{
    sc_spec *box;
    Ipp32fc *work;
    int i;

    if (!p || !re || !im || !p->inv) return -1;
    box = (sc_spec *)p->inv;
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

sc_state *sc_create(const sc_config *cfg)
{
    sc_state *st;

    if (!cfg || cfg->nref < 1 || cfg->nfft < 2 * cfg->nref - 1)
        return NULL;
    if ((cfg->nfft & (cfg->nfft - 1)) != 0) return NULL;

    st = (sc_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->nref = cfg->nref;
    if (sc_plan_build(&st->plan, cfg->nfft) != 0) {
        sc_destroy(st);
        return NULL;
    }
    st->ref_spec_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->ref_spec_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_re = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    st->prod_im = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    if (!st->ref_spec_re || !st->ref_spec_im || !st->prod_re ||
        !st->prod_im) {
        sc_destroy(st);
        return NULL;
    }
    return st;
}

void sc_destroy(sc_state *st)
{
    if (!st) return;
    sc_plan_destroy(&st->plan);
    free(st->ref_spec_re);
    free(st->ref_spec_im);
    free(st->prod_re);
    free(st->prod_im);
    free(st->pending_re);
    free(st->pending_im);
    free(st);
}