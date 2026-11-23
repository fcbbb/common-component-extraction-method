/* Streaming session driver shared by the golden generator and the hidden
 * test: feeds the input in chunks of `block` samples and collects the
 * concatenated output plus the block statistics. */
#ifndef DEM_RUN_H
#define DEM_RUN_H

#include "demod_frontend.h"

#include <stdlib.h>
#include <string.h>

static int dem_run_session(int nco_len, int decim, int ntaps,
                           int nin, int block,
                           const float *nco_re, const float *nco_im,
                           const float *taps_re, const float *taps_im,
                           const float *in_re, const float *in_im,
                           float *out_re, float *out_im, int out_cap,
                           float *mag,
                           float *mean_power, float *peak, int *peak_index)
{
    dem_config cfg;
    dem_state *st;
    int off = 0;
    int total = 0;

    if (nco_len <= 0 || decim <= 0 || ntaps <= 0 || nin <= 0 || block <= 0)
        return -1;

    cfg.nco_len = nco_len;
    cfg.decim = decim;
    cfg.ntaps = ntaps;

    st = dem_create(&cfg, nco_re, nco_im, taps_re, taps_im);
    if (!st) return -1;

    while (off < nin) {
        int n = nin - off;
        int got;

        if (n > block) n = block;
        if (total >= out_cap) break;

        got = dem_process(st, in_re + off, in_im + off, n,
                          out_re + total, out_im + total);
        if (got < 0) got = 0;
        total += got;
        off += n;
    }

    dem_destroy(st);

    dem_stats(out_re, out_im, total, mag, mean_power, peak, peak_index);

    return total;
}

#endif /* DEM_RUN_H */