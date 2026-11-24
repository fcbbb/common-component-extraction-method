/* State lifecycle for the burst acquirer (IPP backend). */
#include "burst_acq_internal.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

static void *ba_alloc(size_t n)
{
    return calloc(1, n ? n : 1);
}

ba_state *ba_create(const ba_config *cfg)
{
    ba_state *st;

    if (!cfg || cfg->nco_len <= 0 || cfg->decim <= 0 ||
        cfg->ntaps <= 0 || cfg->nref < 1)
        return NULL;
    if (cfg->nfft < 2 * cfg->nref - 1 ||
        (cfg->nfft & (cfg->nfft - 1)) != 0)
        return NULL;

    st = (ba_state *)ba_alloc(sizeof(*st));
    if (!st) return NULL;
    st->cfg = *cfg;
    st->M = cfg->decim * cfg->ntaps;

    st->nco_re = (float *)ba_alloc((size_t)cfg->nco_len * sizeof(float));
    st->nco_im = (float *)ba_alloc((size_t)cfg->nco_len * sizeof(float));
    st->taps_re = (float *)ba_alloc((size_t)st->M * sizeof(float));
    st->taps_im = (float *)ba_alloc((size_t)st->M * sizeof(float));
    st->ref_re = (float *)ba_alloc((size_t)cfg->nref * sizeof(float));
    st->ref_im = (float *)ba_alloc((size_t)cfg->nref * sizeof(float));
    st->hist_re = (float *)ba_alloc((size_t)st->M * sizeof(float));
    st->hist_im = (float *)ba_alloc((size_t)st->M * sizeof(float));
    if (!st->nco_re || !st->nco_im || !st->taps_re || !st->taps_im ||
        !st->ref_re || !st->ref_im || !st->hist_re || !st->hist_im) {
        ba_destroy(st);
        return NULL;
    }
    return st;
}

void ba_destroy(ba_state *st)
{
    if (!st) return;
    if (st->ipp_fir) ippsFIRFree_32fc((IppsFIRState_32fc *)st->ipp_fir);
    free(st->nco_re);
    free(st->nco_im);
    free(st->taps_re);
    free(st->taps_im);
    free(st->ref_re);
    free(st->ref_im);
    free(st->hist_re);
    free(st->hist_im);
    free(st->ref_spec_re);
    free(st->ref_spec_im);
    free(st->prod_re);
    free(st->prod_im);
    free(st->dec_re);
    free(st->dec_im);
    free(st);
}

int ba_set_waveform(ba_state *st,
                    const float *nco_re, const float *nco_im,
                    const float *taps_re, const float *taps_im,
                    const float *ref_re, const float *ref_im)
{
    Ipp32fc *taps = NULL;
    int i;

    if (!st || !nco_re || !nco_im || !taps_re || !taps_im ||
        !ref_re || !ref_im)
        return -1;
    if (st->input_seen != 0 || st->dec_n != 0) return -1;
    if (st->ipp_fir) {
        ippsFIRFree_32fc((IppsFIRState_32fc *)st->ipp_fir);
        st->ipp_fir = NULL;
    }

    memcpy(st->nco_re, nco_re,
           (size_t)st->cfg.nco_len * sizeof(float));
    memcpy(st->nco_im, nco_im,
           (size_t)st->cfg.nco_len * sizeof(float));
    memcpy(st->taps_re, taps_re, (size_t)st->M * sizeof(float));
    memcpy(st->taps_im, taps_im, (size_t)st->M * sizeof(float));
    memcpy(st->ref_re, ref_re, (size_t)st->cfg.nref * sizeof(float));
    memcpy(st->ref_im, ref_im, (size_t)st->cfg.nref * sizeof(float));

    taps = (Ipp32fc *)ippsMalloc_8u(
        (int)((size_t)st->M * sizeof(Ipp32fc)));
    if (!taps) return -1;
    for (i = 0; i < st->M; ++i) {
        taps[i].re = st->taps_re[i];
        taps[i].im = st->taps_im[i];
    }
    if (ippsFIRInitAlloc_32fc((IppsFIRState_32fc **)&st->ipp_fir,
                              taps, st->M, NULL) != ippStsNoErr) {
        ippsFree(taps);
        st->ipp_fir = NULL;
        return -1;
    }
    ippsFree(taps);

    st->ready = 1;
    st->nco_phase = 0;
    st->input_seen = 0;
    st->hfill = 0;
    st->dec_n = 0;
    return 0;
}