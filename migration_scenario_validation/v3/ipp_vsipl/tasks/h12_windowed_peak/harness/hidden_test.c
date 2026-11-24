#include "window_spectrum.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef HP_PI
#define HP_PI 3.14159265358979323846
#endif
int main(void)
{
    const int sizes[] = {8, 16, 32, 64};
    int s, failures = 0, checks = 0;
    for (s = 0; s < 4; ++s) {
        const int n = sizes[s], nbin = n / 2 + 1;
        float *x = malloc((size_t)n * sizeof(float));
        float *got = malloc((size_t)nbin * sizeof(float));
        float *want = malloc((size_t)nbin * sizeof(float));
        float peak, total;
        int pb, i, k;
        for (i = 0; i < n; ++i)
            x[i] = (float)(sin(0.31 * i + 0.2) + 0.25 * cos(0.17 * i));
        for (k = 0; k < nbin; ++k) {
            double re = 0.0, im = 0.0;
            for (i = 0; i < n; ++i) {
                const double w = 0.5 * (1.0 - cos(2.0 * HP_PI * i / (n - 1)));
                const double a = -2.0 * HP_PI * k * i / n;
                re += x[i] * w * cos(a);
                im += x[i] * w * sin(a);
            }
            want[k] = (float)sqrt(re * re + im * im);
        }
        ++checks;
        if (window_spectrum(x, n, got, &peak, &pb, &total) != 0) {
            printf("FAIL process n=%d\n", n); ++failures; goto out;
        }
        ++checks;
        for (k = 0; k < nbin; ++k)
            if (fabs((double)got[k] - want[k]) > 2e-4 * (want[k] > 1 ? want[k] : 1)) {
                printf("FAIL n=%d bin=%d got=%g want=%g\n", n, k, got[k], want[k]);
                ++failures; break;
            }
        {
            double wt = 0.0, wp = 0.0; int wb = 0;
            for (k = 0; k < nbin; ++k) { wt += want[k]; if (want[k] > wp) { wp = want[k]; wb = k; } }
            ++checks;
            if (fabs((double)total - wt) > 3e-4 * (wt > 1 ? wt : 1)) ++failures;
            ++checks;
            if (pb != wb || fabs((double)peak - wp) > 3e-4 * (wp > 1 ? wp : 1)) ++failures;
        }
out:    free(x); free(got); free(want);
    }
    ++checks;
    if (window_spectrum(NULL, 8, NULL, NULL, NULL, NULL) != -1) ++failures;
    ++checks;
    if (window_spectrum((const float *)&s, 12, (float *)&s, NULL, NULL, NULL) != -1) ++failures;
    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}
