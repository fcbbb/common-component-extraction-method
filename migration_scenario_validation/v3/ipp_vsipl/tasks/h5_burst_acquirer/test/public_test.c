#include "burst_acq.h"

#include <math.h>
#include <stdio.h>

int main(void)
{
    const int nco_len = 4, decim = 2, ntaps = 3, nref = 4, nfft = 16;
    const int total = 32, lags = 2 * nref - 1;
    float nco_re[4], nco_im[4] = {0};
    float taps_re[6] = {0}, taps_im[6] = {0};
    float ref_re[4] = {0}, ref_im[4] = {0};
    float in_re[32], in_im[32] = {0};
    float out_re[3 * 7], out_im[3 * 7];
    ba_config cfg;
    ba_state *st;
    ba_report rep;
    int i, nout;

    for (i = 0; i < nco_len; ++i) nco_re[i] = 1.0f;
    taps_re[0] = 1.0f;
    ref_re[0] = 1.0f;
    for (i = 0; i < total; ++i)
        in_re[i] = (float)(0.3 * sin(0.2 * i) + 0.1 * i);

    cfg.nco_len = nco_len;
    cfg.decim = decim;
    cfg.ntaps = ntaps;
    cfg.nref = nref;
    cfg.nfft = nfft;
    st = ba_create(&cfg);
    if (!st) return 1;
    if (ba_set_waveform(st, nco_re, nco_im, taps_re, taps_im,
                        ref_re, ref_im) != 0)
        return 2;
    if (ba_push(st, in_re, in_im, total, out_re, out_im, 3,
                &nout, &rep) != 0)
        return 3;
    if (nout != 3 || rep.frames != 3) return 4;
    /* taps[0]=1, ref[0]=1: out[7+nref-1 .. 7+2*nref-2] is frame[0..nref-1]. */
    for (i = nref - 1; i < 2 * nref - 1; ++i) {
        if (fabs((double)out_re[i] - in_re[(6 + 2 * (i - (nref - 1)))]) > 1e-3)
            return 5;
        if (fabs((double)out_im[i]) > 1e-3) return 6;
    }
    if (!(rep.peak >= 0.0f) || !(rep.energy >= 0.0f)) return 7;

    ba_destroy(st);
    puts("public_test: PASS");
    return 0;
}