/* State allocation and history management (IPP backend). */
#include "channelizer_internal.h"

#include <ipp.h>

#include <string.h>

static void *wc_alloc(size_t bytes)
{
    if (bytes == 0) bytes = 1;
    return ippsMalloc_8u((int)bytes);
}

int wc_reserve_history(wc_state *st, int need)
{
    int ncap;
    float *nre, *nim;

    if (!st || need <= st->hcap) return 0;
    ncap = st->hcap > 0 ? st->hcap : 64;
    while (ncap < need) ncap *= 2;

    nre = (float *)wc_alloc((size_t)ncap * sizeof(float));
    nim = (float *)wc_alloc((size_t)ncap * sizeof(float));
    if (!nre || !nim) {
        if (nre) ippsFree(nre);
        if (nim) ippsFree(nim);
        return -1;
    }
    if (st->hfill > 0) {
        memcpy(nre, st->hist_re, (size_t)st->hfill * sizeof(float));
        memcpy(nim, st->hist_im, (size_t)st->hfill * sizeof(float));
    }
    if (st->hist_re) ippsFree(st->hist_re);
    if (st->hist_im) ippsFree(st->hist_im);
    st->hist_re = nre;
    st->hist_im = nim;
    st->hcap = ncap;
    return 0;
}

int wc_reserve_mix(wc_state *st, int need)
{
    Ipp32fc *iq;
    float *re, *im;

    if (!st || need <= st->mixcap) return 0;
    iq = (Ipp32fc *)wc_alloc((size_t)need * sizeof(Ipp32fc));
    re = (float *)wc_alloc((size_t)need * sizeof(float));
    im = (float *)wc_alloc((size_t)need * sizeof(float));
    if (!iq || !re || !im) {
        if (iq) ippsFree(iq);
        if (re) ippsFree(re);
        if (im) ippsFree(im);
        return -1;
    }
    if (st->iq) ippsFree(st->iq);
    if (st->mix_re) ippsFree(st->mix_re);
    if (st->mix_im) ippsFree(st->mix_im);
    st->iq = iq;
    st->mix_re = re;
    st->mix_im = im;
    st->mixcap = need;
    return 0;
}

wc_state *wc_create(const wc_config *cfg,
                    const float *nco_re, const float *nco_im,
                    const float *taps_re, const float *taps_im)
{
    wc_state *st;
    int i;

    if (!cfg || !nco_re || !nco_im || !taps_re || !taps_im) return NULL;
    if (cfg->nco_len <= 0 || cfg->decim <= 0 || cfg->ntaps <= 0) return NULL;

    st = (wc_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->nco_len = cfg->nco_len;
    st->decim = cfg->decim;
    st->ntaps = cfg->ntaps;
    st->T = cfg->decim * cfg->ntaps;

    st->nco_re = (float *)wc_alloc((size_t)st->nco_len * sizeof(float));
    st->nco_im = (float *)wc_alloc((size_t)st->nco_len * sizeof(float));
    st->nco_iq = wc_alloc((size_t)st->nco_len * sizeof(Ipp32fc));
    st->taps_re = (float *)wc_alloc((size_t)st->T * sizeof(float));
    st->taps_im = (float *)wc_alloc((size_t)st->T * sizeof(float));
    if (!st->nco_re || !st->nco_im || !st->nco_iq || !st->taps_re ||
        !st->taps_im) {
        wc_destroy(st);
        return NULL;
    }
    memcpy(st->nco_re, nco_re, (size_t)st->nco_len * sizeof(float));
    memcpy(st->nco_im, nco_im, (size_t)st->nco_len * sizeof(float));
    /* The dot product walks the history in increasing time; store the taps
     * time-reversed so that coefficient k multiplies x[center-(T-1)+k]. */
    for (i = 0; i < st->T; ++i) {
        st->taps_re[i] = taps_re[st->T - 1 - i];
        st->taps_im[i] = taps_im[st->T - 1 - i];
    }
    for (i = 0; i < st->nco_len; ++i) {
        Ipp32fc *iq = (Ipp32fc *)st->nco_iq;
        iq[i].re = nco_re[i];
        iq[i].im = nco_im[i];
    }
    return st;
}

void wc_destroy(wc_state *st)
{
    if (!st) return;
    if (st->nco_re) ippsFree(st->nco_re);
    if (st->nco_im) ippsFree(st->nco_im);
    if (st->nco_iq) ippsFree(st->nco_iq);
    if (st->taps_re) ippsFree(st->taps_re);
    if (st->taps_im) ippsFree(st->taps_im);
    if (st->hist_re) ippsFree(st->hist_re);
    if (st->hist_im) ippsFree(st->hist_im);
    if (st->mix_re) ippsFree(st->mix_re);
    if (st->mix_im) ippsFree(st->mix_im);
    if (st->iq) ippsFree(st->iq);
    free(st);
}