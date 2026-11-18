/* Public self-check: the frequency-domain filter against a direct causal
 * convolution in double precision, for several transform/block combinations,
 * plus the constructor and argument contracts.
 */
#include "fdfir.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static void make_taps(int ntaps, float *taps)
{
    int i;
    for (i = 0; i < ntaps; ++i)
        taps[i] = (float)(0.6 * sin(0.9 * i + 0.4) / (1.0 + 0.2 * i));
}

static void make_input(int n, float *x)
{
    int i;
    for (i = 0; i < n; ++i)
        x[i] = (float)(cos(0.37 * i) + 0.3 * sin(0.11 * i));
}

static int check_case(const char *tag, int ntaps, int nfft, int nx)
{
    float taps[64], *x = malloc(sizeof(float) * (size_t)nx);
    float *y = malloc(sizeof(float) * (size_t)nx);
    fdfir *f;
    int i, j, fail = 0;
    double worst = 0.0;

    if (!x || !y) return 1;
    make_taps(ntaps, taps);
    make_input(nx, x);

    f = fdfir_create(taps, ntaps, nfft);
    if (!f) {
        printf("FAIL %s: create returned NULL\n", tag);
        free(x); free(y);
        return 1;
    }
    if (fdfir_apply(f, x, nx, y) != 0) {
        printf("FAIL %s: apply returned non-zero\n", tag);
        fdfir_destroy(f);
        free(x); free(y);
        return 1;
    }
    fdfir_destroy(f);

    for (i = 0; i < nx; ++i) {
        double want = 0.0;
        for (j = 0; j < ntaps; ++j)
            if (i - j >= 0) want += (double)taps[j] * (double)x[i - j];
        {
            double e = fabs((double)y[i] - want);
            double rel = (fabs(want) > 1.0) ? e / fabs(want) : e;
            if (rel > worst) worst = rel;
            if (rel > 1e-5 && e > 1e-6) {
                if (!fail)
                    printf("FAIL %s: index %d got %.9g want %.9g\n",
                           tag, i, (double)y[i], want);
                fail = 1;
            }
        }
    }
    printf("  %-26s %s maxrel=%.3e\n", tag, fail ? "FAIL" : "PASS", worst);
    free(x); free(y);
    return fail;
}

int main(void)
{
    float taps[8] = { 1, -1, 1, -1, 1, -1, 1, -1 };
    float x[16] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    float y[16];
    int fail = 0;

    printf("public_test:\n");
    fail |= check_case("ntaps=4 nfft=8 nx=5",    4,   8,   5);   /* one block      */
    fail |= check_case("ntaps=4 nfft=8 nx=3",    4,   8,   3);   /* short input    */
    fail |= check_case("ntaps=4 nfft=8 nx=40",   4,   8,  40);   /* exact blocks   */
    fail |= check_case("ntaps=16 nfft=32 nx=100", 16, 32, 100);  /* partial tail   */
    fail |= check_case("ntaps=32 nfft=32 nx=20", 32,  32,  20);  /* block == 1     */
    fail |= check_case("ntaps=1 nfft=8 nx=32",   1,   8,  32);   /* pure gain      */
    fail |= check_case("ntaps=63 nfft=64 nx=64", 63,  64, 64);   /* block == 2     */

    /* a single tap scales the signal */
    {
        float one[1] = { 0.5f };
        fdfir *f = fdfir_create(one, 1, 8);
        if (!f || fdfir_apply(f, x, 16, y) != 0 ||
            fabs((double)y[0] - 0.5) > 1e-6 || fabs((double)y[15] - 8.0) > 1e-6) {
            printf("FAIL: single-tap gain\n");
            fail = 1;
        }
        fdfir_destroy(f);
    }

    /* invalid arguments */
    if (fdfir_create(NULL, 4, 8) != NULL ||
        fdfir_create(taps, 0, 8) != NULL ||
        fdfir_create(taps, 8, 4) != NULL ||      /* nfft < ntaps        */
        fdfir_create(taps, 4, 12) != NULL ||     /* not a power of two  */
        fdfir_create(taps, 4, 0) != NULL) {
        printf("FAIL: fdfir_create accepted invalid arguments\n");
        fail = 1;
    }
    {
        fdfir *f = fdfir_create(taps, 4, 8);
        if (!f || fdfir_apply(NULL, x, 16, y) != -1 ||
            fdfir_apply(f, NULL, 16, y) != -1 ||
            fdfir_apply(f, x, 16, NULL) != -1 ||
            fdfir_apply(f, x, 0, y) != -1) {
            printf("FAIL: fdfir_apply accepted invalid arguments\n");
            fail = 1;
        }
        fdfir_destroy(f);
        fdfir_destroy(NULL);   /* must be a no-op */
    }

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}