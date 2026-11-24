#include "power_spectrum.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef H1_PI
#define H1_PI 3.14159265358979323846
#endif

static int failures = 0;
static int checks = 0;

static void check_case(int n)
{
    const int nbin = n / 2 + 1;
    float *x = (float *)malloc((size_t)n * sizeof(float));
    float *got = (float *)malloc((size_t)nbin * sizeof(float));
    float *want = (float *)malloc((size_t)nbin * sizeof(float));
    float peak, total;
    int peak_bin, i, k;

    for (i = 0; i < n; ++i)
        x[i] = (float)(sin(0.27 * i + 0.3) + 0.3 * cos(0.11 * i));
    for (k = 0; k < nbin; ++k) {
        double re = 0.0, im = 0.0;
        for (i = 0; i < n; ++i) {
            const double a = -2.0 * H1_PI * (double)k * (double)i / (double)n;
            re += (double)x[i] * cos(a);
            im += (double)x[i] * sin(a);
        }
        want[k] = (float)(re * re + im * im);
    }

    ++checks;
    if (power_spectrum(x, n, got, &peak, &peak_bin, &total) != 0) {
        printf("FAIL process n=%d\n", n); ++failures; goto out;
    }
    for (k = 0; k < nbin; ++k) {
        const double tol = 2e-4 * (want[k] > 1.0 ? want[k] : 1.0);
        if (fabs((double)got[k] - want[k]) > tol) {
            printf("FAIL n=%d bin=%d got=%g want=%g\n", n, k, got[k], want[k]);
            ++failures; break;
        }
    }
    {
        double wt = 0.0, wp = 0.0;
        int wb = 0;
        for (k = 0; k < nbin; ++k) {
            wt += want[k];
            if (want[k] > wp) { wp = want[k]; wb = k; }
        }
        ++checks;
        if (fabs((double)total - wt) > 2e-4 * (wt > 1.0 ? wt : 1.0)) ++failures;
        ++checks;
        if (peak_bin != wb || fabs((double)peak - wp) > 2e-4 * (wp > 1.0 ? wp : 1.0))
            ++failures;
    }
out:
    free(x); free(got); free(want);
}

int main(void)
{
    const int sizes[] = {8, 16, 32, 64};
    int i;
    for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); ++i)
        check_case(sizes[i]);
    ++checks;
    if (power_spectrum(NULL, 8, NULL, NULL, NULL, NULL) != -1) ++failures;
    ++checks;
    if (power_spectrum((const float *)&i, 12, (float *)&i, NULL, NULL, NULL) != -1) ++failures;
    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}
