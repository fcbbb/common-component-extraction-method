#include "stream_lag.h"

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

static void fill_stream(int total, float *xr, float *xi,
                        float *hr, float *hi, int n)
{
    int i;
    for (i = 0; i < total; ++i) {
        xr[i] = (float)(sin(0.31 * i + 0.2) + 0.25 * cos(0.17 * i));
        xi[i] = (float)(0.6 * cos(0.23 * i + 0.4));
    }
    for (i = 0; i < n; ++i) {
        hr[i] = (float)(cos(0.41 * i) - 0.2 * sin(0.13 * i));
        hi[i] = (float)(0.5 * sin(0.19 * i + 0.3));
    }
}

static int run_split(const float *xr, const float *xi,
                     const float *hr, const float *hi,
                     int nref, int nfft, int total,
                     const int *chunks, int nchunks,
                     float *out_re, float *out_im, int *nout)
{
    sc_config cfg;
    sc_state *st;
    int off = 0, produced = 0, i;

    cfg.nfft = nfft;
    cfg.nref = nref;
    st = sc_create(&cfg);
    if (!st) return -1;
    if (sc_set_reference(st, hr, hi) != 0) {
        sc_destroy(st);
        return -1;
    }
    for (i = 0; i < nchunks; ++i) {
        int got = 0;
        const int cap = (total - off) / nref;
        if (sc_process(st, xr + off, xi + off, chunks[i],
                       out_re + produced * (2 * nref - 1),
                       out_im + produced * (2 * nref - 1),
                       cap, &got, NULL) != 0) {
            sc_destroy(st);
            return -1;
        }
        produced += got;
        off += chunks[i];
    }
    sc_destroy(st);
    *nout = produced;
    return 0;
}

static void check_splits(void)
{
    const int nref = 8, nfft = 32, total = 46, lags = 15;
    const int chunks_a[] = {46};
    const int chunks_b[] = {1, 2, 3, 4, 5, 6, 7, 8, 10};
    const int chunks_c[] = {5, 5, 5, 5, 5, 5, 5, 5, 5, 1};
    const int *splits[] = {chunks_a, chunks_b, chunks_c};
    const int counts[] = {1, 9, 10};
    float *xr = (float *)malloc((size_t)total * sizeof(float));
    float *xi = (float *)malloc((size_t)total * sizeof(float));
    float *hr = (float *)malloc((size_t)nref * sizeof(float));
    float *hi = (float *)malloc((size_t)nref * sizeof(float));
    float *ar = (float *)malloc((size_t)(total / nref) * lags * sizeof(float));
    float *ai = (float *)malloc((size_t)(total / nref) * lags * sizeof(float));
    float *br = (float *)malloc((size_t)(total / nref) * lags * sizeof(float));
    float *bi = (float *)malloc((size_t)(total / nref) * lags * sizeof(float));
    int i, j, s;

    fill_stream(total, xr, xi, hr, hi, nref);
    for (s = 0; s < 3; ++s) {
        int nout = 0;
        ++checks;
        if (run_split(xr, xi, hr, hi, nref, nfft, total, splits[s],
                      counts[s], ar, ai, &nout) != 0) {
            printf("FAIL split=%d run\n", s);
            ++failures;
            continue;
        }
        ++checks;
        if (nout != total / nref) {
            printf("FAIL split=%d nout=%d want=%d\n", s, nout, total / nref);
            ++failures;
            continue;
        }
        for (i = 0; i < nout; ++i) {
            for (j = 0; j < lags; ++j) {
                double rr, ri;
                ref_corr(xr + i * nref, xi + i * nref, hr, hi,
                         nref, j - (nref - 1), &rr, &ri);
                ++checks;
                if (fabs((double)ar[i * lags + j] - rr) >
                        2e-4 * (fabs(rr) > 1.0 ? fabs(rr) : 1.0) ||
                    fabs((double)ai[i * lags + j] - ri) >
                        2e-4 * (fabs(ri) > 1.0 ? fabs(ri) : 1.0)) {
                    printf("FAIL split=%d block=%d lag=%d got=(%g,%g) want=(%g,%g)\n",
                           s, i, j, ar[i * lags + j], ai[i * lags + j], rr, ri);
                    ++failures;
                    goto next_split;
                }
            }
        }
next_split:
        if (s == 0) {
            for (i = 0; i < nout * lags; ++i) {
                br[i] = ar[i];
                bi[i] = ai[i];
            }
        } else {
            ++checks;
            if (nout != total / nref) {
                printf("FAIL split=%d count mismatch\n", s);
                ++failures;
            } else {
                for (i = 0; i < nout * lags; ++i) {
                    if (fabs((double)ar[i] - br[i]) > 2e-4 ||
                        fabs((double)ai[i] - bi[i]) > 2e-4) {
                        printf("FAIL split=%d differs at %d\n", s, i);
                        ++failures;
                        break;
                    }
                }
            }
        }
    }
    free(xr); free(xi); free(hr); free(hi);
    free(ar); free(ai); free(br); free(bi);
}


static void check_small_frames(void)
{
    const int ns[] = {1, 2, 3, 4, 5, 16};
    int si;

    for (si = 0; si < (int)(sizeof(ns) / sizeof(ns[0])); ++si) {
        const int nref = ns[si];
        const int lags = 2 * nref - 1;
        int nfft = 2;
        const int total = 3 * nref + nref / 2;
        float *xr = (float *)malloc((size_t)total * sizeof(float));
        float *xi = (float *)malloc((size_t)total * sizeof(float));
        float *hr = (float *)malloc((size_t)nref * sizeof(float));
        float *hi = (float *)malloc((size_t)nref * sizeof(float));
        float *or_ = (float *)malloc((size_t)3 * lags * sizeof(float));
        float *oi = (float *)malloc((size_t)3 * lags * sizeof(float));
        sc_config cfg;
        while (nfft < 2 * nref - 1) nfft <<= 1;
        sc_state *st;
        int nout = 0, i, j;

        fill_stream(total, xr, xi, hr, hi, nref);
        cfg.nfft = nfft;
        cfg.nref = nref;
        st = sc_create(&cfg);
        ++checks;
        if (!st) {
            printf("FAIL small nref=%d create\n", nref);
            ++failures;
            goto next_small;
        }
        if (sc_set_reference(st, hr, hi) != 0 ||
            sc_process(st, xr, xi, total, or_, oi, 3, &nout, NULL) != 0) {
            ++checks;
            printf("FAIL small nref=%d process\n", nref);
            ++failures;
            sc_destroy(st);
            goto next_small;
        }
        ++checks;
        if (nout != total / nref) {
            printf("FAIL small nref=%d nout=%d want=%d\n",
                   nref, nout, total / nref);
            ++failures;
        } else {
            for (i = 0; i < nout; ++i) {
                for (j = 0; j < lags; ++j) {
                    double rr, ri;
                    ref_corr(xr + i * nref, xi + i * nref, hr, hi,
                             nref, j - (nref - 1), &rr, &ri);
                    ++checks;
                    if (fabs((double)or_[i * lags + j] - rr) > 2e-4 ||
                        fabs((double)oi[i * lags + j] - ri) > 2e-4) {
                        printf("FAIL small nref=%d block=%d lag=%d\n",
                               nref, i, j);
                        ++failures;
                        goto small_done;
                    }
                }
            }
        }
small_done:
        sc_destroy(st);
next_small:
        free(xr); free(xi); free(hr); free(hi); free(or_); free(oi);
    }
}

static void check_atomic_capacity(void)
{
    const int nref = 8, nfft = 16, total = 20, lags = 15;
    float xr[20], xi[20], hr[8], hi[8], or_[30], oi[30];
    sc_config cfg = {16, 8};
    sc_state *st;
    int nout = -1;
    int i;

    fill_stream(total, xr, xi, hr, hi, nref);
    st = sc_create(&cfg);
    ++checks;
    if (!st) { printf("FAIL capacity create\n"); ++failures; return; }
    if (sc_set_reference(st, hr, hi) != 0) {
        ++checks; printf("FAIL capacity ref\n"); ++failures; sc_destroy(st); return;
    }
    ++checks;
    if (sc_process(st, xr, xi, total, or_, oi, 1, &nout, NULL) != -1) {
        printf("FAIL capacity should reject out_cap=1\n");
        ++failures;
    }
    /* The rejected call must not consume input. */
    ++checks;
    if (sc_process(st, xr, xi, total, or_, oi, 2, &nout, NULL) != 0 ||
        nout != 2) {
        printf("FAIL capacity retry nout=%d\n", nout);
        ++failures;
    }
    for (i = 0; i < nout * lags; ++i) {
        double rr, ri;
        const int block = i / lags, lag = i % lags;
        ref_corr(xr + block * nref, xi + block * nref, hr, hi,
                 nref, lag - (nref - 1), &rr, &ri);
        ++checks;
        if (fabs((double)or_[i] - rr) > 2e-4 ||
            fabs((double)oi[i] - ri) > 2e-4) {
            printf("FAIL capacity value %d\n", i);
            ++failures;
            break;
        }
    }
    sc_destroy(st);
}

static void check_carry_and_reference(void)
{
    const int nref = 8, nfft = 16, lags = 15;
    float xr[16], xi[16], hr[8], hi[8], or_[30], oi[30];
    sc_config cfg = {16, 8};
    sc_state *st;
    int nout = 0, got = 0;

    fill_stream(16, xr, xi, hr, hi, nref);
    st = sc_create(&cfg);
    ++checks;
    if (!st) { printf("FAIL carry create\n"); ++failures; return; }
    if (sc_set_reference(st, hr, hi) != 0) {
        ++checks; printf("FAIL carry ref\n"); ++failures; sc_destroy(st); return;
    }
    /* Five samples are not a frame; replacing the reference is invalid. */
    ++checks;
    if (sc_process(st, xr, xi, 5, NULL, NULL, 0, &got, NULL) != 0 || got != 0) {
        printf("FAIL carry pending\n"); ++failures;
    }
    ++checks;
    if (sc_set_reference(st, hr, hi) != -1) {
        printf("FAIL carry ref replacement\n"); ++failures;
    }
    /* Complete the first frame with three more samples; then process 8. */
    ++checks;
    if (sc_process(st, xr + 5, xi + 5, 3, or_, oi, 1, &got, NULL) != 0 ||
        got != 1) {
        printf("FAIL carry first frame got=%d\n", got); ++failures;
    }
    ++checks;
    if (sc_process(st, xr + 8, xi + 8, 8, or_ + lags, oi + lags,
                   1, &got, NULL) != 0 || got != 1) {
        printf("FAIL carry second frame got=%d\n", got); ++failures;
    }
    ++checks;
    if (sc_process(st, NULL, NULL, 0, NULL, NULL, 0, &nout, NULL) != 0 ||
        nout != 0) {
        printf("FAIL empty call\n"); ++failures;
    }
    sc_destroy(st);
}

static void check_invalid(void)
{
    sc_config bad_a = {4, 3};
    sc_config bad_b = {12, 4};
    sc_config bad_c = {8, 0};
    sc_state *st;
    int nout = 0;
    int dummy = 0;
    float f = 0.0f;

    st = sc_create(NULL);
    ++checks;
    if (st) { printf("FAIL null config\n"); ++failures; sc_destroy(st); }
    st = sc_create(&bad_a);
    ++checks;
    if (st) { printf("FAIL undersized nfft\n"); ++failures; sc_destroy(st); }
    st = sc_create(&bad_b);
    ++checks;
    if (st) { printf("FAIL non-power nfft\n"); ++failures; sc_destroy(st); }
    st = sc_create(&bad_c);
    ++checks;
    if (st) { printf("FAIL zero nref\n"); ++failures; sc_destroy(st); }

    ++checks;
    if (sc_set_reference(NULL, &f, &f) != -1) ++failures;
    ++checks;
    if (sc_process(NULL, &f, &f, 1, &f, &f, 1, &nout, NULL) != -1)
        ++failures;
    ++checks;
    if (sc_process(NULL, NULL, NULL, 0, NULL, NULL, 0, NULL, NULL) != -1)
        ++failures;
    (void)dummy;
}

int main(void)
{
    check_splits();
    check_small_frames();
    check_atomic_capacity();
    check_carry_and_reference();
    check_invalid();
    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}