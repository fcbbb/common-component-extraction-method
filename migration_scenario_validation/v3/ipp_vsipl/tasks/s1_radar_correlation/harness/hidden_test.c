#include "radar_pipeline.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int failures = 0;
static int checks = 0;

static void ref_corr(const float *xr, const float *xi,
                     const float *hr, const float *hi,
                     int n, int k, double *or_, double *oi)
{
    double sr = 0.0, si = 0.0;
    int j;
    for (j = 0; j < n; ++j) {
        const int q = j - k;
        if (q < 0 || q >= n) continue;
        sr += (double)xr[j] * hr[q] + (double)xi[j] * hi[q];
        si += (double)xi[j] * hr[q] - (double)xr[j] * hi[q];
    }
    *or_ = sr;
    *oi = si;
}

static void check_case(int n)
{
    int nfft = 2;
    int lags = 2 * n - 1;
    float *xr = (float *)malloc((size_t)n * sizeof(float));
    float *xi = (float *)malloc((size_t)n * sizeof(float));
    float *hr = (float *)malloc((size_t)n * sizeof(float));
    float *hi = (float *)malloc((size_t)n * sizeof(float));
    float *yr = (float *)malloc((size_t)lags * sizeof(float));
    float *yi = (float *)malloc((size_t)lags * sizeof(float));
    rpc_config cfg;
    rpc_state *st;
    rpc_report rep;
    int i;
    double peak = 0.0;

    while (nfft < lags) nfft <<= 1;
    for (i = 0; i < n; ++i) {
        xr[i] = (float)(sin(0.31 * i + 0.2) + 0.25 * cos(0.17 * i));
        xi[i] = (float)(0.6 * cos(0.23 * i + 0.4));
        hr[i] = (float)(cos(0.41 * i) - 0.2 * sin(0.13 * i));
        hi[i] = (float)(0.5 * sin(0.19 * i + 0.3));
    }
    cfg.nfft = nfft;
    cfg.npulse = n;
    st = rpc_create(&cfg);
    ++checks;
    if (!st) { printf("FAIL create n=%d\n", n); ++failures; goto out; }
    if (rpc_set_replica(st, hr, hi, n) != 0) {
        printf("FAIL replica n=%d\n", n); ++failures; goto out_st;
    }
    if (rpc_process(st, xr, xi, n, yr, yi, &rep) != 0) {
        printf("FAIL process n=%d\n", n); ++failures; goto out_st;
    }
    for (i = 0; i < lags; ++i) {
        double rr, ri;
        ref_corr(xr, xi, hr, hi, n, i - (n - 1), &rr, &ri);
        if (fabs((double)yr[i] - rr) > 2e-4 ||
            fabs((double)yi[i] - ri) > 2e-4) {
            printf("FAIL n=%d lag=%d got=(%g,%g) want=(%g,%g)\n",
                   n, i, yr[i], yi[i], rr, ri);
            ++failures;
            break;
        }
        if (hypot(rr, ri) > peak) peak = hypot(rr, ri);
    }
    ++checks;
    if (fabs((double)rep.peak - peak) > 3e-4 * (peak > 1.0 ? peak : 1.0)) {
        printf("FAIL n=%d peak=%g want=%g\n", n, rep.peak, peak);
        ++failures;
    }
    {
        double energy = 0.0;
        for (i = 0; i < lags; ++i)
            energy += (double)yr[i] * yr[i] + (double)yi[i] * yi[i];
        ++checks;
        if (fabs((double)rep.energy - energy) > 3e-4 * (energy > 1.0 ? energy : 1.0)) {
            printf("FAIL n=%d energy=%g want=%g\n", n, rep.energy, energy);
            ++failures;
        }
    }
out_st:
    rpc_destroy(st);
out:
    free(xr); free(xi); free(hr); free(hi); free(yr); free(yi);
}

int main(void)
{
    const int sizes[] = {1, 2, 3, 4, 5, 8, 13, 16, 31, 32};
    int i;
    rpc_config bad = {8, 5};
    rpc_state *st;

    for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); ++i)
        check_case(sizes[i]);

    st = rpc_create(NULL);
    ++checks;
    if (st) { printf("FAIL null config\n"); ++failures; rpc_destroy(st); }
    st = rpc_create(&bad);
    ++checks;
    if (st) { printf("FAIL undersized nfft\n"); ++failures; rpc_destroy(st); }

    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}