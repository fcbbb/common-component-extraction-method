#include "spectral_gate.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef SG_PI
#define SG_PI 3.14159265358979323846
#endif

static int failures = 0;
static int checks = 0;

static void ref_case(int n)
{
    const int nbin = n / 2 + 1;
    float *x = (float *)malloc((size_t)n * sizeof(float));
    float *win = (float *)malloc((size_t)n * sizeof(float));
    float *mag = (float *)malloc((size_t)nbin * sizeof(float));
    float *want = (float *)malloc((size_t)nbin * sizeof(float));
    unsigned char *flags = (unsigned char *)malloc((size_t)nbin);
    unsigned char *wflags = (unsigned char *)malloc((size_t)nbin);
    sg_config cfg;
    sg_state *st;
    sg_report rep;
    int i, k;

    for (i = 0; i < n; ++i) {
        x[i] = (float)(sin(0.37 * i + 0.2) + 0.35 * cos(0.11 * i + 0.7));
        win[i] = (float)(0.5 * (1.0 - cos(2.0 * SG_PI * (double)i /
                                          (double)(n - 1))));
    }

    for (k = 0; k < nbin; ++k) {
        double re = 0.0, im = 0.0;
        for (i = 0; i < n; ++i) {
            const double ang = -2.0 * SG_PI * (double)k * (double)i / (double)n;
            const double v = (double)x[i] * win[i];
            re += v * cos(ang);
            im += v * sin(ang);
        }
        want[k] = (float)hypot(re, im);
    }
    for (k = 0; k < nbin; ++k) {
        int lo = k - 3;
        double sum = 0.0;
        int cnt;
        if (lo < 0) lo = 0;
        cnt = k - lo;
        for (i = lo; i < k; ++i) sum += want[i];
        if (cnt > 0 && sum > 0.0)
            wflags[k] = (want[k] > 2.0f * (float)(sum / (double)cnt)) ? 1 : 0;
        else
            wflags[k] = 0;
    }

    cfg.nfft = n;
    cfg.ntrain = 3;
    cfg.alpha = 2.0f;
    st = sg_create(&cfg);
    ++checks;
    if (!st) { printf("FAIL create n=%d\n", n); ++failures; goto out; }
    if (sg_process(st, x, n, mag, flags, &rep) != 0) {
        printf("FAIL process n=%d\n", n); ++failures; goto out_st;
    }
    for (k = 0; k < nbin; ++k) {
        const double tol = 2e-4 * (want[k] > 1.0 ? want[k] : 1.0);
        if (fabs((double)mag[k] - want[k]) > tol) {
            printf("FAIL n=%d bin=%d got=%g want=%g\n", n, k, mag[k], want[k]);
            ++failures;
            break;
        }
    }
    ++checks;
    for (k = 0; k < nbin; ++k) {
        if (flags[k] != wflags[k]) {
            printf("FAIL n=%d flag[%d]=%d want=%d\n", n, k, flags[k], wflags[k]);
            ++failures;
            break;
        }
    }
    ++checks;
    if (rep.detections < 0 || rep.detections > nbin) {
        printf("FAIL n=%d detections=%d\n", n, rep.detections);
        ++failures;
    }
out_st:
    sg_destroy(st);
out:
    free(x); free(win); free(mag); free(want); free(flags); free(wflags);
}

int main(void)
{
    const int sizes[] = {8, 16, 32, 64};
    int i;
    sg_config bad = {12, 3, 2.0f};
    sg_state *st;

    for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); ++i)
        ref_case(sizes[i]);

    st = sg_create(&bad);
    ++checks;
    if (st) { printf("FAIL non-power-of-two accepted\n"); ++failures; sg_destroy(st); }
    st = sg_create(NULL);
    ++checks;
    if (st) { printf("FAIL null config accepted\n"); ++failures; sg_destroy(st); }

    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}