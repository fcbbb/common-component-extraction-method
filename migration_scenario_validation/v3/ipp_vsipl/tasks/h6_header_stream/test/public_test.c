#include "stream_lag.h"

#include <math.h>
#include <stdio.h>

int main(void)
{
    const int nref = 8, nfft = 16, lags = 2 * nref - 1;
    float ref_re[8] = {0}, ref_im[8] = {0};
    float in_re[16], in_im[16] = {0};
    float out_re[2 * 15], out_im[2 * 15];
    sc_config cfg;
    sc_state *st;
    sc_report rep;
    int i, nout;

    ref_re[3] = 1.0f;
    for (i = 0; i < 16; ++i)
        in_re[i] = (float)(0.4 * sin(0.3 * i) + 0.1 * i);

    cfg.nfft = nfft;
    cfg.nref = nref;
    st = sc_create(&cfg);
    if (!st) return 1;
    if (sc_set_reference(st, ref_re, ref_im) != 0) return 2;
    if (sc_process(st, in_re, in_im, 16, out_re, out_im, 2, &nout, &rep) != 0)
        return 3;
    if (nout != 2) return 4;
    /* ref[3] = 1: in each frame, out[i] = frame[i-4] for i = 4..11. */
    for (i = 4; i < 12; ++i) {
        if (fabs((double)out_re[i] - in_re[i - 4]) > 1e-4) return 5;
        if (fabs((double)out_im[i]) > 1e-4) return 6;
        if (fabs((double)out_re[15 + i] - in_re[8 + i - 4]) > 1e-4)
            return 7;
    }
    if (rep.peak_index < 0 || rep.peak_index >= 2 * lags) return 8;
    if (!(rep.energy >= 0.0f) || !(rep.peak >= 0.0f)) return 9;

    sc_destroy(st);
    puts("public_test: PASS");
    return 0;
}