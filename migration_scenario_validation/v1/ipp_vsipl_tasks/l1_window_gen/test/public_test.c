/* Public self-check: all four windows against the definitions written out
 * here in double precision, plus symmetry, the length contract and the error
 * codes.
 */
#include "win_gen.h"

#include <math.h>
#include <stdio.h>

#define N 33

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static double i0(double x)
{
    double sum = 1.0, term = 1.0, y = x * x * 0.25;
    int k = 1;
    while (1) {
        term *= y / ((double)k * (double)k);
        sum += term;
        if (term < 1e-16 * sum) break;
        ++k;
    }
    return sum;
}

static double ref_window(int type, double param, int i, int n)
{
    double t = 2.0 * M_PI * (double)i / (double)(n - 1);
    if (n == 1) return 1.0;
    switch (type) {
    case WIN_HANN:     return 0.5 - 0.5 * cos(t);
    case WIN_HAMMING:  return 0.54 - 0.46 * cos(t);
    case WIN_BLACKMAN: return (0.5 + param / 2.0) - 0.5 * cos(t)
                            - (param / 2.0) * cos(2.0 * t);
    default: {
        double beta = param * (double)(n - 1) / 2.0;
        double x = 2.0 * (double)i / (double)(n - 1) - 1.0;
        return i0(beta * sqrt(fmax(0.0, 1.0 - x * x))) / i0(beta);
    }
    }
}

static int check(int type, float param, const char *tag)
{
    float in[N], out[N];
    int i, fail = 0;
    double worst = 0.0;

    for (i = 0; i < N; ++i) in[i] = (float)(0.3 * sin(0.7 * i) + 0.6);

    if (win_apply((win_type)type, param, in, out, N) != 0) {
        printf("FAIL %s: win_apply returned non-zero\n", tag);
        return 1;
    }
    for (i = 0; i < N; ++i) {
        double want = (double)in[i] * ref_window(type, (double)param, i, N);
        double e = fabs((double)out[i] - want);
        double rel = (fabs(want) > 1.0) ? e / fabs(want) : e;
        if (rel > worst) worst = rel;
        if (rel > 1e-4 && e > 1e-5) {
            if (!fail)
                printf("FAIL %s: index %d got %.9g want %.9g\n",
                       tag, i, (double)out[i], want);
            fail = 1;
        }
    }

    /* all four windows are symmetric: w[i] == w[n-1-i] */
    {
        char wtag[64];
        float win[N], one[N];
        snprintf(wtag, sizeof(wtag), "%s/symmetry", tag);
        for (i = 0; i < N; ++i) one[i] = 1.0f;
        if (win_apply((win_type)type, param, one, win, N) != 0) {
            printf("FAIL %s: win_apply returned non-zero\n", wtag);
            return 1;
        }
        for (i = 0; i < N / 2; ++i) {
            if (fabs((double)win[i] - (double)win[N - 1 - i]) > 1e-6) {
                printf("FAIL %s: w[%d]=%.9g != w[%d]=%.9g\n",
                       wtag, i, (double)win[i], N - 1 - i, (double)win[N - 1 - i]);
                fail = 1;
                break;
            }
        }
    }

    printf("  %-22s %s maxrel=%.3e\n", tag, fail ? "FAIL" : "PASS", worst);
    return fail;
}

int main(void)
{
    float in[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
    float out[8];
    int fail = 0;

    printf("public_test:\n");
    fail |= check(WIN_HANN,     0.00f, "hann");
    fail |= check(WIN_HAMMING,  0.00f, "hamming");
    fail |= check(WIN_BLACKMAN, 0.16f, "blackman a=0.16");
    fail |= check(WIN_BLACKMAN, 0.30f, "blackman a=0.30");
    fail |= check(WIN_KAISER,   2.00f, "kaiser a=2 n=33");
    fail |= check(WIN_KAISER,   0.50f, "kaiser a=0.5");

    /* ending values: the symmetric cosine windows are zero at both ends */
    if (win_apply(WIN_HANN, 0.0f, in, out, 8) != 0 ||
        fabs((double)out[0]) > 1e-6 || fabs((double)out[7]) > 1e-6) {
        printf("FAIL: Hann endpoints are not zero\n");
        fail = 1;
    }
    /* Hamming endpoints are 0.08*x */
    if (win_apply(WIN_HAMMING, 0.0f, in, out, 8) != 0 ||
        fabs((double)out[0] - 0.08 * (double)in[0]) > 1e-6) {
        printf("FAIL: Hamming endpoint is not 0.54-0.46\n");
        fail = 1;
    }

    /* argument contract */
    if (win_apply(WIN_HANN, 0.0f, in, out, 2) != -1 ||
        win_apply(WIN_HAMMING, 0.0f, in, out, 1) != -1 ||
        win_apply(WIN_BLACKMAN, 0.16f, in, out, 0) != -1 ||
        win_apply(WIN_KAISER, -1.0f, in, out, 8) != -1 ||
        win_apply(WIN_KAISER, 5.0f, in, out, 128) != -1 ||   /* beta = 317.5 */
        win_apply((win_type)99, 0.0f, in, out, 8) != -1 ||
        win_apply(WIN_HANN, 0.0f, NULL, out, 8) != -1) {
        printf("FAIL: invalid arguments were not rejected\n");
        fail = 1;
    }
    /* Kaiser accepts n == 1 and the window is 1 */
    if (win_apply(WIN_KAISER, 7.0f, in, out, 1) != 0 ||
        fabs((double)out[0] - (double)in[0]) > 1e-6) {
        printf("FAIL: Kaiser n=1 is not the identity\n");
        fail = 1;
    }

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}