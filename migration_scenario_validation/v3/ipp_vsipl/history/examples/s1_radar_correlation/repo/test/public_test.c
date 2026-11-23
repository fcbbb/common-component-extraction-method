#include "radar_pipeline.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static double ref_corr(const float *xr, const float *xi,
                       const float *hr, const float *hi,
                       int n, int k, int which)
{
    double sum = 0.0;
    int j;
    for (j = 0; j < n; ++j) {
        const int q = j - k;
        if (q < 0 || q >= n) continue;
        if (which == 0) sum += (double)xr[j] * hr[q] + (double)xi[j] * hi[q];
        else            sum += (double)xi[j] * hr[q] - (double)xr[j] * hi[q];
    }
    return sum;
}

int main(void)
{
    const int n = 8, nfft = 16, lags = 2 * n - 1;
    float xr[8], xi[8], hr[8], hi[8];
    float yr[15], yi[15];
    rpc_config cfg = {nfft, n};
    rpc_report rep;
    rpc_state *st;
    int i;

    for (i = 0; i < n; ++i) {
        xr[i] = (float)(sin(0.3 * i) + 0.2 * cos(0.7 * i));
        xi[i] = (float)(0.4 * sin(0.11 * i));
        hr[i] = (float)(cos(0.2 * i) - 0.1 * sin(0.5 * i));
        hi[i] = (float)(0.3 * cos(0.13 * i + 0.2));
    }

    st = rpc_create(&cfg);
    if (!st) return 1;
    if (rpc_set_replica(st, hr, hi, n) != 0) return 2;
    if (rpc_process(st, xr, xi, n, yr, yi, &rep) != 0) return 3;

    for (i = 0; i < lags; ++i) {
        const double rr = ref_corr(xr, xi, hr, hi, n, i - (n - 1), 0);
        const double ri = ref_corr(xr, xi, hr, hi, n, i - (n - 1), 1);
        if (fabs((double)yr[i] - rr) > 1e-4 ||
            fabs((double)yi[i] - ri) > 1e-4) {
            printf("FAIL lag %d got (%g,%g) want (%g,%g)\n",
                   i, yr[i], yi[i], rr, ri);
            return 4;
        }
    }
    if (!(rep.peak > 0.0f) || rep.peak_index < 0 || rep.peak_index >= lags)
        return 5;
    rpc_destroy(st);
    puts("public_test: PASS");
    return 0;
}