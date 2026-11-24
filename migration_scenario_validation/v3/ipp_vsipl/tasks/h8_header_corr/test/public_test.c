#include "sonar_lag.h"

#include <math.h>
#include <stdio.h>

int main(void)
{
    const int nref = 8, nfft = 16, lags = 2 * nref - 1;
    float ref_re[8] = {0}, ref_im[8] = {0};
    float in_re[8], in_im[8] = {0};
    float out_re[15], out_im[15];
    sl_config cfg;
    sl_state *st;
    sl_report rep;
    int i;

    ref_re[3] = 1.0f;
    for (i = 0; i < nref; ++i)
        in_re[i] = (float)(0.4 * sin(0.3 * i) + 0.1 * i);

    cfg.nfft = nfft;
    cfg.nref = nref;
    st = sl_create(&cfg);
    if (!st) return 1;
    if (sl_set_reference(st, ref_re, ref_im) != 0) return 2;
    if (sl_process(st, in_re, in_im, out_re, out_im, &rep) != 0) return 3;

    /* ref[3] = 1, so out[i] = in[i-4] for i = 4..11. */
    for (i = 4; i < 12; ++i) {
        if (fabs((double)out_re[i] - in_re[i - 4]) > 1e-4) return 4;
        if (fabs((double)out_im[i]) > 1e-4) return 5;
    }
    if (rep.peak_index < 0 || rep.peak_index >= lags) return 6;
    if (!(rep.energy >= 0.0f) || !(rep.peak >= 0.0f)) return 7;

    sl_destroy(st);
    puts("public_test: PASS");
    return 0;
}