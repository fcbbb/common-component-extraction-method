#include "channelizer.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static void ref(const float *xr, const float *xi,
                const float *nr, const float *ni,
                const float *hr, const float *hi,
                int n, int L, int M, int T,
                float *yr, float *yi, int *nout)
{
    float *mr = (float *)malloc((size_t)n * sizeof(float));
    float *mi = (float *)malloc((size_t)n * sizeof(float));
    int i, j, count = 0;

    for (i = 0; i < n; ++i) {
        const int p = i % L;
        mr[i] = xr[i] * nr[p] - xi[i] * ni[p];
        mi[i] = xr[i] * ni[p] + xi[i] * nr[p];
    }
    for (j = 0; ; ++j) {
        const int c = j * M;
        float rr = 0.0f, ri = 0.0f;
        int t;
        if (c >= n) break;
        if (c < T - 1) continue;
        for (t = 0; t < T; ++t) {
            rr += hr[t] * mr[c - t] - hi[t] * mi[c - t];
            ri += hr[t] * mi[c - t] + hi[t] * mr[c - t];
        }
        yr[count] = rr;
        yi[count] = ri;
        ++count;
    }
    *nout = count;
    free(mr);
    free(mi);
}

int main(void)
{
    const int L = 4, M = 2, T = 4, n = 12;
    float nr[4] = {1, 0, -1, 0};
    float ni[4] = {0, 1, 0, -1};
    float hr[4] = {0.25f, 0.5f, 0.25f, 0.0f};
    float hi[4] = {0.0f, 0.125f, 0.0f, -0.125f};
    float xr[12], xi[12], yr[16], yi[16], wr[16], wi[16];
    wc_config cfg = {L, M, 1};
    wc_state *st;
    int i, nout, nwant;
    wc_report rep;

    cfg.ntaps = T / M;
    for (i = 0; i < n; ++i) {
        xr[i] = (float)sin(0.2 * i);
        xi[i] = (float)cos(0.3 * i);
    }
    st = wc_create(&cfg, nr, ni, hr, hi);
    if (!st) return 1;
    nout = wc_process(st, xr, xi, n, yr, yi, &rep);
    if (nout < 0) return 2;
    ref(xr, xi, nr, ni, hr, hi, n, L, M, T, wr, wi, &nwant);
    if (nout != nwant) { printf("FAIL count %d want %d\n", nout, nwant); return 3; }
    for (i = 0; i < nout; ++i) {
        if (fabs((double)yr[i] - wr[i]) > 1e-4 ||
            fabs((double)yi[i] - wi[i]) > 1e-4) {
            printf("FAIL output %d got (%g,%g) want (%g,%g)\n",
                   i, yr[i], yi[i], wr[i], wi[i]);
            return 4;
        }
    }
    if (rep.peak < 0.0f) return 5;
    wc_destroy(st);
    puts("public_test: PASS");
    return 0;
}