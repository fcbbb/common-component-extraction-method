#include "channelizer.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
static int checks = 0;

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

static void run_case(int n, const int *chunks, int nchunks)
{
    const int L = 7, M = 3, T = 12;
    float nr[7], ni[7], hr[12], hi[12];
    float *xr = (float *)malloc((size_t)n * sizeof(float));
    float *xi = (float *)malloc((size_t)n * sizeof(float));
    float *yr = (float *)malloc((size_t)(n / M + 2) * sizeof(float));
    float *yi = (float *)malloc((size_t)(n / M + 2) * sizeof(float));
    float *wr = (float *)malloc((size_t)(n / M + 2) * sizeof(float));
    float *wi = (float *)malloc((size_t)(n / M + 2) * sizeof(float));
    wc_config cfg = {L, M, T / M};
    wc_state *st;
    int i, pos = 0, produced = 0, nwant = 0;

    for (i = 0; i < L; ++i) {
        nr[i] = (float)cos(0.4 * i);
        ni[i] = (float)sin(0.4 * i);
    }
    for (i = 0; i < T; ++i) {
        hr[i] = (float)(0.5 * cos(0.2 * i) / (1.0 + 0.1 * i));
        hi[i] = (float)(0.3 * sin(0.15 * i) / (1.0 + 0.1 * i));
    }
    for (i = 0; i < n; ++i) {
        xr[i] = (float)(sin(0.31 * i) + 0.2 * cos(0.07 * i));
        xi[i] = (float)(0.6 * cos(0.23 * i + 0.4));
    }
    ref(xr, xi, nr, ni, hr, hi, n, L, M, T, wr, wi, &nwant);

    st = wc_create(&cfg, nr, ni, hr, hi);
    ++checks;
    if (!st) { printf("FAIL create n=%d\n", n); ++failures; goto out; }

    for (i = 0; i < nchunks; ++i) {
        const int take = chunks[i];
        wc_report rep;
        int got;
        if (pos + take > n) break;
        got = wc_process(st, xr + pos, xi + pos, take, yr + produced,
                         yi + produced, &rep);
        if (got < 0) { printf("FAIL process n=%d chunk=%d\n", n, take); ++failures; goto out_st; }
        produced += got;
        pos += take;
    }
    if (pos != n) produced = -1;
    ++checks;
    if (produced != nwant) {
        printf("FAIL count n=%d got=%d want=%d\n", n, produced, nwant);
        ++failures;
        goto out_st;
    }
    for (i = 0; i < nwant; ++i) {
        if (fabs((double)yr[i] - wr[i]) > 2e-4 ||
            fabs((double)yi[i] - wi[i]) > 2e-4) {
            printf("FAIL n=%d out=%d got=(%g,%g) want=(%g,%g)\n",
                   n, i, yr[i], yi[i], wr[i], wi[i]);
            ++failures;
            break;
        }
    }
out_st:
    wc_destroy(st);
out:
    free(xr); free(xi); free(yr); free(yi); free(wr); free(wi);
}

int main(void)
{
    const int whole[] = {97};
    const int ones[97] = {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                          1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                          1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                          1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
                          1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1};
    const int mixed[] = {3, 1, 7, 2, 9, 4, 6, 8, 5, 11, 13, 17, 11};
    int i, sum = 0;
    run_case(97, whole, 1);
    run_case(97, ones, 97);
    for (i = 0; i < (int)(sizeof(mixed) / sizeof(mixed[0])); ++i)
        sum += mixed[i];
    run_case(sum, mixed, (int)(sizeof(mixed) / sizeof(mixed[0])));

    {
        wc_config bad = {4, 0, 1};
        wc_state *st = wc_create(&bad, NULL, NULL, NULL, NULL);
        ++checks;
        if (st) { printf("FAIL bad config\n"); ++failures; wc_destroy(st); }
    }
    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}