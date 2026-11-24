#include "sonar_lag.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int failures = 0;
static int checks = 0;

static void ref_corr(const float *xr, const float *xi,
                     const float *hr, const float *hi,
                     int n, int k, double *out_r, double *out_i)
{
    double sr = 0.0, si = 0.0;
    int j;

    for (j = 0; j < n; ++j) {
        const int q = j - k;
        if (q < 0 || q >= n) continue;
        sr += (double)xr[j] * hr[q] + (double)xi[j] * hi[q];
        si += (double)xi[j] * hr[q] - (double)xr[j] * hi[q];
    }
    *out_r = sr;
    *out_i = si;
}

static int make_pow2(int need)
{
    int n = 2;
    while (n < need) n <<= 1;
    return n;
}

static void fill_case(int n, float *xr, float *xi, float *hr, float *hi)
{
    int i;
    for (i = 0; i < n; ++i) {
        xr[i] = (float)(sin(0.31 * i + 0.2) + 0.25 * cos(0.17 * i));
        xi[i] = (float)(0.6 * cos(0.23 * i + 0.4));
        hr[i] = (float)(cos(0.41 * i) - 0.2 * sin(0.13 * i));
        hi[i] = (float)(0.5 * sin(0.19 * i + 0.3));
    }
}

static void check_complex_case(int n)
{
    const int nfft = make_pow2(2 * n - 1);
    const int lags = 2 * n - 1;
    float *xr = (float *)malloc((size_t)n * sizeof(float));
    float *xi = (float *)malloc((size_t)n * sizeof(float));
    float *hr = (float *)malloc((size_t)n * sizeof(float));
    float *hi = (float *)malloc((size_t)n * sizeof(float));
    float *yr = (float *)malloc((size_t)lags * sizeof(float));
    float *yi = (float *)malloc((size_t)lags * sizeof(float));
    sl_config cfg;
    sl_state *st;
    sl_report rep;
    double peak = 0.0, energy = 0.0;
    int i;

    fill_case(n, xr, xi, hr, hi);
    cfg.nfft = nfft;
    cfg.nref = n;
    st = sl_create(&cfg);
    ++checks;
    if (!st) {
        printf("FAIL create n=%d nfft=%d\n", n, nfft);
        ++failures;
        goto out;
    }
    if (sl_set_reference(st, hr, hi) != 0) {
        printf("FAIL set_reference n=%d\n", n);
        ++failures;
        goto out_st;
    }
    if (sl_process(st, xr, xi, yr, yi, &rep) != 0) {
        printf("FAIL process n=%d\n", n);
        ++failures;
        goto out_st;
    }

    for (i = 0; i < lags; ++i) {
        double rr, ri, m;
        ref_corr(xr, xi, hr, hi, n, i - (n - 1), &rr, &ri);
        m = hypot(rr, ri);
        if (m > peak) peak = m;
        energy += rr * rr + ri * ri;
        ++checks;
        if (fabs((double)yr[i] - rr) > 2e-4 * (fabs(rr) > 1.0 ? fabs(rr) : 1.0) ||
            fabs((double)yi[i] - ri) > 2e-4 * (fabs(ri) > 1.0 ? fabs(ri) : 1.0)) {
            printf("FAIL n=%d lag=%d got=(%g,%g) want=(%g,%g)\n",
                   n, i, yr[i], yi[i], rr, ri);
            ++failures;
            break;
        }
    }

    ++checks;
    if (fabs((double)rep.peak - peak) > 3e-4 * (peak > 1.0 ? peak : 1.0)) {
        printf("FAIL n=%d peak=%g want=%g\n", n, rep.peak, peak);
        ++failures;
    }
    ++checks;
    if (fabs((double)rep.energy - energy) >
        3e-4 * (energy > 1.0 ? energy : 1.0)) {
        printf("FAIL n=%d energy=%g want=%g\n", n, rep.energy, energy);
        ++failures;
    }

out_st:
    sl_destroy(st);
out:
    free(xr); free(xi); free(hr); free(hi); free(yr); free(yi);
}

static void check_copy(void)
{
    const int n = 9, nfft = 32, lags = 17;
    float xr[9], xi[9], hr[9], hi[9];
    float yr[17], yi[17], wr[17], wi[17];
    sl_config cfg = {32, 9};
    sl_state *st, *st2;
    int i;

    fill_case(n, xr, xi, hr, hi);
    st = sl_create(&cfg);
    st2 = sl_create(&cfg);
    ++checks;
    if (!st || !st2) {
        printf("FAIL copy create\n");
        ++failures;
        if (st) sl_destroy(st);
        if (st2) sl_destroy(st2);
        return;
    }
    if (sl_set_reference(st, hr, hi) != 0 ||
        sl_set_reference(st2, hr, hi) != 0) {
        ++checks;
        printf("FAIL copy set\n");
        ++failures;
        sl_destroy(st);
        sl_destroy(st2);
        return;
    }
    /* Control result before the caller's arrays are overwritten. */
    if (sl_process(st2, xr, xi, wr, wi, NULL) != 0) {
        ++checks;
        printf("FAIL copy control process\n");
        ++failures;
        sl_destroy(st);
        sl_destroy(st2);
        return;
    }
    for (i = 0; i < n; ++i) {
        hr[i] = 0.0f;
        hi[i] = 0.0f;
    }
    if (sl_process(st, xr, xi, yr, yi, NULL) != 0) {
        ++checks;
        printf("FAIL copy process\n");
        ++failures;
        sl_destroy(st);
        sl_destroy(st2);
        return;
    }
    for (i = 0; i < lags; ++i) {
        ++checks;
        if (fabs((double)yr[i] - wr[i]) > 1e-5 ||
            fabs((double)yi[i] - wi[i]) > 1e-5) {
            printf("FAIL copy lag=%d\n", i);
            ++failures;
            break;
        }
    }
    sl_destroy(st);
    sl_destroy(st2);
}

static void check_scale(void)
{
    const int n = 9, nfft = 32, lags = 17;
    float xr[9], xi[9] = {0}, hr[9], hi[9] = {0};
    float yr[17], yi[17];
    sl_config cfg = {32, 9};
    sl_state *st;
    int i;

    for (i = 0; i < n; ++i) {
        xr[i] = 1.0f;
        hr[i] = 1.0f;
    }
    st = sl_create(&cfg);
    ++checks;
    if (!st) {
        printf("FAIL scale create\n");
        ++failures;
        return;
    }
    if (sl_set_reference(st, hr, hi) != 0 ||
        sl_process(st, xr, xi, yr, yi, NULL) != 0) {
        ++checks;
        printf("FAIL scale process\n");
        ++failures;
        sl_destroy(st);
        return;
    }
    for (i = 0; i < lags; ++i) {
        const int k = i - (n - 1);
        const double want = (double)(n - abs(k));
        ++checks;
        if (fabs((double)yr[i] - want) > 2e-4 ||
            fabs((double)yi[i]) > 2e-4) {
            printf("FAIL scale lag=%d got=(%g,%g) want=%g\n",
                   i, yr[i], yi[i], want);
            ++failures;
            break;
        }
    }
    sl_destroy(st);
}

static void check_oversized(void)
{
    const int n = 13, lags = 25;
    const int nfft_a = 32, nfft_b = 128;
    float xr[13], xi[13], hr[13], hi[13];
    float ar[25], ai[25], br[25], bi[25];
    sl_config ca = {32, 13}, cb = {128, 13};
    sl_state *sa, *sb;
    int i;

    fill_case(n, xr, xi, hr, hi);
    sa = sl_create(&ca);
    sb = sl_create(&cb);
    ++checks;
    if (!sa || !sb) {
        printf("FAIL oversized create\n");
        ++failures;
        if (sa) sl_destroy(sa);
        if (sb) sl_destroy(sb);
        return;
    }
    if (sl_set_reference(sa, hr, hi) != 0 ||
        sl_set_reference(sb, hr, hi) != 0 ||
        sl_process(sa, xr, xi, ar, ai, NULL) != 0 ||
        sl_process(sb, xr, xi, br, bi, NULL) != 0) {
        ++checks;
        printf("FAIL oversized process\n");
        ++failures;
        sl_destroy(sa);
        sl_destroy(sb);
        return;
    }
    for (i = 0; i < lags; ++i) {
        ++checks;
        if (fabs((double)ar[i] - br[i]) > 2e-4 ||
            fabs((double)ai[i] - bi[i]) > 2e-4) {
            printf("FAIL oversized lag=%d a=(%g,%g) b=(%g,%g)\n",
                   i, ar[i], ai[i], br[i], bi[i]);
            ++failures;
            break;
        }
    }
    sl_destroy(sa);
    sl_destroy(sb);
}

static void check_reuse(void)
{
    const int n = 10, nfft = 32, lags = 19;
    float xr[10], xi[10], hr[10], hi[10];
    float ar[10], ai[10];
    float yr[19], yi[19], wr[19], wi[19];
    sl_config cfg = {32, 10};
    sl_state *st;
    int i;

    fill_case(n, xr, xi, hr, hi);
    for (i = 0; i < n; ++i) {
        ar[i] = (float)(0.3 * cos(0.7 * i) - 0.2);
        ai[i] = (float)(0.4 * sin(0.5 * i + 0.1));
    }
    st = sl_create(&cfg);
    ++checks;
    if (!st) {
        printf("FAIL reuse create\n");
        ++failures;
        return;
    }
    /* Process a different non-zero frame first, then the checked frame.  A
     * missing tail clear leaves the first frame's padded samples behind. */
    if (sl_set_reference(st, hr, hi) != 0 ||
        sl_process(st, ar, ai, wr, wi, NULL) != 0 ||
        sl_process(st, xr, xi, yr, yi, NULL) != 0) {
        ++checks;
        printf("FAIL reuse process\n");
        ++failures;
        sl_destroy(st);
        return;
    }
    for (i = 0; i < lags; ++i) {
        double rr, ri;
        ref_corr(xr, xi, hr, hi, n, i - (n - 1), &rr, &ri);
        ++checks;
        if (fabs((double)yr[i] - rr) > 2e-4 * (fabs(rr) > 1.0 ? fabs(rr) : 1.0) ||
            fabs((double)yi[i] - ri) > 2e-4 * (fabs(ri) > 1.0 ? fabs(ri) : 1.0)) {
            printf("FAIL reuse lag=%d got=(%g,%g) want=(%g,%g)\n",
                   i, yr[i], yi[i], rr, ri);
            ++failures;
            break;
        }
    }
    sl_destroy(st);
}

static void check_tie(void)
{
    const int n = 8, lags = 15;
    float xr[8] = {1, 2, 3, 4, 4, 3, 2, 1};
    float xi[8] = {0};
    float hr[8] = {1, 0, 0, 0, 0, 0, 0, 0};
    float hi[8] = {0};
    float yr[15], yi[15];
    sl_config cfg = {16, 8};
    sl_state *st;
    sl_report rep;

    st = sl_create(&cfg);
    ++checks;
    if (!st) {
        printf("FAIL tie create\n");
        ++failures;
        return;
    }
    if (sl_set_reference(st, hr, hi) != 0 ||
        sl_process(st, xr, xi, yr, yi, &rep) != 0) {
        ++checks;
        printf("FAIL tie process\n");
        ++failures;
        sl_destroy(st);
        return;
    }
    /* ref[0]=1, so the two equal peaks are out[10] and out[11]. */
    ++checks;
    if (rep.peak_index != 10) {
        printf("FAIL tie peak_index=%d want=10\n", rep.peak_index);
        ++failures;
    }
    sl_destroy(st);
}

int main(void)
{
    const int sizes[] = {1, 2, 3, 4, 5, 8, 13, 16, 31, 32};
    int i;
    sl_config bad_a = {4, 3};   /* nfft < 2*nref-1 */
    sl_config bad_b = {12, 4};  /* not a power of two */
    sl_config bad_c = {8, 0};
    sl_state *st;

    for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); ++i)
        check_complex_case(sizes[i]);
    check_copy();
    check_scale();
    check_oversized();
    check_reuse();
    check_tie();

    st = sl_create(NULL);
    ++checks;
    if (st) { printf("FAIL null config\n"); ++failures; sl_destroy(st); }
    st = sl_create(&bad_a);
    ++checks;
    if (st) { printf("FAIL undersized nfft\n"); ++failures; sl_destroy(st); }
    st = sl_create(&bad_b);
    ++checks;
    if (st) { printf("FAIL non-power nfft\n"); ++failures; sl_destroy(st); }
    st = sl_create(&bad_c);
    ++checks;
    if (st) { printf("FAIL zero nref\n"); ++failures; sl_destroy(st); }
    ++checks;
    if (sl_set_reference(NULL, (const float *)&i, (const float *)&i) != -1)
        ++failures;
    ++checks;
    if (sl_process(NULL, (const float *)&i, (const float *)&i,
                   (float *)&i, (float *)&i, NULL) != -1)
        ++failures;

    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}