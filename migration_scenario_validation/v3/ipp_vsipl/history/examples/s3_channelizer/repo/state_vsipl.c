/* State allocation and history management (VSIPL backend). */
#include "channelizer_internal.h"

#include <stdlib.h>
#include <string.h>

int wc_reserve_history(wc_state *st, int need)
{
    int ncap;
    float *nre, *nim;

    if (!st || need <= st->hcap) return 0;
    ncap = st->hcap > 0 ? st->hcap : 64;
    while (ncap < need) ncap *= 2;
    nre = (float *)malloc((size_t)ncap * sizeof(float));
    nim = (float *)malloc((size_t)ncap * sizeof(float));
    if (!nre || !nim) {
        free(nre);
        free(nim);
        return -1;
    }
    if (st->hfill > 0) {
        memcpy(nre, st->hist_re, (size_t)st->hfill * sizeof(float));
        memcpy(nim, st->hist_im, (size_t)st->hfill * sizeof(float));
    }
    free(st->hist_re);
    free(st->hist_im);
    st->hist_re = nre;
    st->hist_im = nim;
    st->hcap = ncap;
    return 0;
}

int wc_reserve_mix(wc_state *st, int need)
{
    float *re, *im;

    if (!st || need <= st->mixcap) return 0;
    re = (float *)malloc((size_t)need * sizeof(float));
    im = (float *)malloc((size_t)need * sizeof(float));
    if (!re || !im) {
        free(re);
        free(im);
        return -1;
    }
    free(st->mix_re);
    free(st->mix_im);
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

    if (!cfg || !nco_re || !nco_im || !taps_re || !taps_im) return NULL;
    if (cfg->nco_len <= 0 || cfg->decim <= 0 || cfg->ntaps <= 0) return NULL;

    st = (wc_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->nco_len = cfg->nco_len;
    st->decim = cfg->decim;
    st->ntaps = cfg->ntaps;
    st->T = cfg->decim * cfg->ntaps;

    st->nco_re = (float *)malloc((size_t)st->nco_len * sizeof(float));
    st->nco_im = (float *)malloc((size_t)st->nco_len * sizeof(float));
    st->taps_re = (float *)malloc((size_t)st->T * sizeof(float));
    st->taps_im = (float *)malloc((size_t)st->T * sizeof(float));
    if (!st->nco_re || !st->nco_im || !st->taps_re || !st->taps_im) {
        wc_destroy(st);
        return NULL;
    }
    memcpy(st->nco_re, nco_re, (size_t)st->nco_len * sizeof(float));
    memcpy(st->nco_im, nco_im, (size_t)st->nco_len * sizeof(float));
    memcpy(st->taps_re, taps_re, (size_t)st->T * sizeof(float));
    memcpy(st->taps_im, taps_im, (size_t)st->T * sizeof(float));
    return st;
}

void wc_destroy(wc_state *st)
{
    if (!st) return;
    free(st->nco_re);
    free(st->nco_im);
    free(st->nco_iq);
    free(st->taps_re);
    free(st->taps_im);
    free(st->hist_re);
    free(st->hist_im);
    free(st->mix_re);
    free(st->mix_im);
    free(st->iq);
    free(st);
}