/* Public self-check: the DCT against its definition in double precision (both
 * directions), the orthonormality round trip, and the constructor contract.
 */
#include "aubio_dct.h"

#include <math.h>
#include <stdio.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static void make_input(int n, float *x)
{
    int i;
    for (i = 0; i < n; ++i)
        x[i] = (float)(sin(0.7 * i + 0.2) + 0.3 * cos(0.13 * i * i));
}

static double coef(int k, int n)
{
    return (k == 0) ? sqrt(1.0 / (double)n) : sqrt(2.0 / (double)n);
}

static int check_forward(int n)
{
    float in[32], out[32];
    fvec_t fi, fo;
    aubio_dct_t *s;
    int i, k, fail = 0;
    double worst = 0.0;

    make_input(n, in);
    s = new_aubio_dct((unsigned int)n);
    if (!s) return 1;
    fi.length = (unsigned int)n; fi.data = in;
    fo.length = (unsigned int)n; fo.data = out;
    aubio_dct_do(s, &fi, &fo);
    del_aubio_dct(s);

    for (k = 0; k < n; ++k) {
        double want = 0.0;
        for (i = 0; i < n; ++i)
            want += (double)in[i] * cos(M_PI * k * (2 * i + 1) / (2.0 * n));
        want *= coef(k, n);
        {
            double e = fabs((double)out[k] - want);
            double rel = (fabs(want) > 1.0) ? e / fabs(want) : e;
            if (rel > worst) worst = rel;
            if (rel > 1e-5 && e > 1e-6) {
                if (!fail) printf("FAIL fwd n=%d: k=%d got %.9g want %.9g\n",
                                  n, k, (double)out[k], want);
                fail = 1;
            }
        }
    }
    printf("  %-22s %s maxrel=%.3e\n", "forward vs definition", fail ? "FAIL" : "PASS", worst);
    return fail;
}

static int check_inverse(int n)
{
    float in[32], out[32];
    fvec_t fi, fo;
    aubio_dct_t *s;
    int i, k, fail = 0;
    double worst = 0.0;

    make_input(n, in);
    s = new_aubio_dct((unsigned int)n);
    if (!s) return 1;
    fi.length = (unsigned int)n; fi.data = in;
    fo.length = (unsigned int)n; fo.data = out;
    aubio_dct_rdo(s, &fi, &fo);
    del_aubio_dct(s);

    for (i = 0; i < n; ++i) {
        double want = 0.0;
        for (k = 0; k < n; ++k)
            want += coef(k, n) * (double)in[k] * cos(M_PI * k * (2 * i + 1) / (2.0 * n));
        {
            double e = fabs((double)out[i] - want);
            double rel = (fabs(want) > 1.0) ? e / fabs(want) : e;
            if (rel > worst) worst = rel;
            if (rel > 1e-5 && e > 1e-6) {
                if (!fail) printf("FAIL inv n=%d: i=%d got %.9g want %.9g\n",
                                  n, i, (double)out[i], want);
                fail = 1;
            }
        }
    }
    printf("  %-22s %s maxrel=%.3e\n", "inverse vs definition", fail ? "FAIL" : "PASS", worst);
    return fail;
}

static int check_roundtrip(int n)
{
    float x[128], y[128], z[128];
    fvec_t fx, fy, fz;
    aubio_dct_t *s;
    int i, fail = 0;
    double worst = 0.0;

    make_input(n, x);
    s = new_aubio_dct((unsigned int)n);
    if (!s) return 1;
    fx.length = fy.length = fz.length = (unsigned int)n;
    fx.data = x; fy.data = y; fz.data = z;
    aubio_dct_do(s, &fx, &fy);
    aubio_dct_rdo(s, &fy, &fz);
    del_aubio_dct(s);

    for (i = 0; i < n; ++i) {
        double e = fabs((double)z[i] - (double)x[i]);
        if (e > worst) worst = e;
        if (e > 1e-5) fail = 1;
    }
    printf("  %-22s %s maxerr=%.3e\n", "roundtrip", fail ? "FAIL" : "PASS", worst);
    return fail;
}

int main(void)
{
    int n, fail = 0;

    printf("public_test:\n");
    for (n = 2; n <= 8; ++n) {
        fail |= check_forward(n);
        fail |= check_inverse(n);
    }
    fail |= check_roundtrip(16);
    fail |= check_roundtrip(100);

    /* size 1 is a valid (degenerate) DCT */
    {
        float in[1] = { 3.5f }, out[1] = { 0.0f };
        fvec_t fi, fo;
        aubio_dct_t *s = new_aubio_dct(1);
        fi.length = 1; fi.data = in;
        fo.length = 1; fo.data = out;
        if (!s) {
            printf("FAIL: new_aubio_dct(1) returned NULL\n");
            fail = 1;
        } else {
            aubio_dct_do(s, &fi, &fo);
            if (fabs((double)out[0] - 3.5) > 1e-6) {
                printf("FAIL: n=1 forward is not the identity\n");
                fail = 1;
            }
            aubio_dct_rdo(s, &fi, &fo);
            if (fabs((double)out[0] - 3.5) > 1e-6) {
                printf("FAIL: n=1 inverse is not the identity\n");
                fail = 1;
            }
            del_aubio_dct(s);
        }
    }

    if (new_aubio_dct(0) != NULL) {
        printf("FAIL: new_aubio_dct(0) did not return NULL\n");
        fail = 1;
    }
    del_aubio_dct(NULL);   /* must be a no-op */

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}