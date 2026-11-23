#ifndef CHANNELIZER_INTERNAL_H
#define CHANNELIZER_INTERNAL_H

#include "channelizer.h"

struct wc_state {
    int nco_len;
    int decim;
    int ntaps;
    int T;

    float *nco_re;
    float *nco_im;
    void *nco_iq;
    float *taps_re;
    float *taps_im;

    int ph;
    long gtotal;
    long jnext;
    long base;

    float *hist_re;
    float *hist_im;
    int hcap;
    int hfill;

    float *mix_re;
    float *mix_im;
    int mixcap;
    void *iq;
};

int wc_mix_block(wc_state *st, const float *in_re, const float *in_im, int nin);
int wc_reserve_history(wc_state *st, int need);
int wc_reserve_mix(wc_state *st, int need);
void wc_fill_report(const float *re, const float *im, int n, wc_report *rep);

#endif /* CHANNELIZER_INTERNAL_H */