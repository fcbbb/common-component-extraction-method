/* Public self-check for the aubio fft module.
 *
 * Deliberately small: compares the complex spectrum, the polar spectrum, the
 * accessors and the inverse against a direct double-precision DFT computed
 * here, so the agent can sanity-check the migration without seeing the hidden
 * cases or the golden data.
 *
 * Expected layout (identical to aubio 0.4.9):
 *   compspec = [ r0, r1, ..., r_{n/2}, i_{n/2-1}, ..., i1 ]           (n floats)
 *   spectrum = norm[0..n/2], phas[0..n/2]                            (n/2+1 each)
 */
#include "aubio_fft.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static void dft_ref(const float *x, int n, double *re, double *im)
{
    int k, t;
    for (k = 0; k <= n / 2; ++k) {
        double sr = 0.0, si = 0.0;
        for (t = 0; t < n; ++t) {
            double ang = -2.0 * M_PI * (double)k * (double)t / (double)n;
            sr += (double)x[t] * cos(ang);
            si += (double)x[t] * sin(ang);
        }
        re[k] = sr;
        im[k] = si;
    }
}

static double relerr(double got, double want)
{
    double e = fabs(got - want);
    double s = fabs(want);
    return (s > 1.0) ? e / s : e;
}

static int check_size(int n)
{
    float x[1024];
    float comp[1024];
    float comp2[1024];
    float out[1024];
    float *norm, *phas;
    double re[513], im[513];
    fvec_t fin, fcomp, fcomp2, fout;
    cvec_t spec;
    aubio_fft_t *s;
    int i, k, m = n / 2 + 1;
    int fail = 0;
    double worst = 0.0;

    for (i = 0; i < n; ++i)
        x[i] = (float)(0.7 * sin(0.31 * i) + 0.4 * cos(0.07 * i * i) - 0.1);
    x[0] -= 2.5f;   /* make sure the DC term is negative somewhere */

    dft_ref(x, n, re, im);

    s = new_aubio_fft((uint_t)n);
    if (!s) { printf("  n=%d: FAIL new_aubio_fft returned NULL\n", n); return 1; }

    fin.length = (uint_t)n;  fin.data = x;
    fcomp.length = (uint_t)n; fcomp.data = comp;
    fcomp2.length = (uint_t)n; fcomp2.data = comp2;
    fout.length = (uint_t)n; fout.data = out;

    /* 1. complex spectrum layout */
    memset(comp, 0, sizeof(float) * (size_t)n);
    aubio_fft_do_complex(s, &fin, &fcomp);
    for (k = 0; k <= n / 2; ++k)
        worst = fmax(worst, relerr(comp[k], re[k]));
    for (k = 1; k < n / 2; ++k)
        worst = fmax(worst, relerr(comp[n - k], im[k]));
    if (worst > 1e-4) { printf("  n=%d: FAIL do_complex rel=%.3e\n", n, worst); fail = 1; }

    /* 2. polar spectrum */
    norm = (float *)malloc(sizeof(float) * (size_t)m);
    phas = (float *)malloc(sizeof(float) * (size_t)m);
    if (!norm || !phas) return 1;
    spec.length = (uint_t)m; spec.norm = norm; spec.phas = phas;
    aubio_fft_do(s, &fin, &spec);
    {
        double w2 = 0.0;
        w2 = fmax(w2, relerr(norm[0], fabs(re[0])));
        w2 = fmax(w2, relerr(norm[m - 1], fabs(re[n / 2])));
        for (k = 1; k < m - 1; ++k)
            w2 = fmax(w2, relerr(norm[k], hypot(re[k], im[k])));
        /* phases: index 0 and n/2 use the +pi convention, the rest atan2 */
        if (re[0] < 0) w2 = fmax(w2, relerr(phas[0] - M_PI, 0.0));
        else           w2 = fmax(w2, relerr(phas[0], 0.0));
        if (re[n / 2] < 0) w2 = fmax(w2, relerr(phas[m - 1] - M_PI, 0.0));
        else               w2 = fmax(w2, relerr(phas[m - 1], 0.0));
        for (k = 1; k < m - 1; ++k) {
            double d = (double)phas[k] - atan2(im[k], re[k]);
            d -= 2.0 * M_PI * floor(d / (2.0 * M_PI) + 0.5);
            w2 = fmax(w2, fabs(d));
        }
        if (w2 > 1e-4) { printf("  n=%d: FAIL do rel=%.3e\n", n, w2); fail = 1; }
        worst = fmax(worst, w2);
    }

    /* 3. norm/phas -> compspec accessors must round-trip the spectrum */
    memset(comp2, 0x7f, sizeof(float) * (size_t)n);
    aubio_fft_get_realimag(&spec, &fcomp2);
    {
        double w3 = 0.0;
        for (i = 0; i < n; ++i)
            w3 = fmax(w3, relerr(comp2[i], comp[i]));
        if (w3 > 1e-4) { printf("  n=%d: FAIL get_realimag rel=%.3e\n", n, w3); fail = 1; }
        worst = fmax(worst, w3);
    }

    /* 4. complex inverse restores the frame */
    aubio_fft_rdo_complex(s, &fcomp, &fout);
    {
        double w4 = 0.0;
        for (i = 0; i < n; ++i)
            w4 = fmax(w4, relerr(out[i], x[i]));
        if (w4 > 1e-4) { printf("  n=%d: FAIL rdo_complex rel=%.3e\n", n, w4); fail = 1; }
        worst = fmax(worst, w4);
    }

    /* 5. polar inverse restores the frame */
    aubio_fft_rdo(s, &spec, &fout);
    {
        double w5 = 0.0;
        for (i = 0; i < n; ++i)
            w5 = fmax(w5, relerr(out[i], x[i]));
        if (w5 > 1e-4) { printf("  n=%d: FAIL rdo rel=%.3e\n", n, w5); fail = 1; }
        worst = fmax(worst, w5);
    }

    free(norm);
    free(phas);
    del_aubio_fft(s);

    printf("  n=%4d: %s worst=%.3e\n", n, fail ? "FAIL" : "PASS", worst);
    return fail;
}

int main(void)
{
    static const int sizes[] = { 8, 16, 32, 64, 256 };
    static const uint_t bad[] = { 1, 2, 3, 4, 5, 6, 12, 1000 };
    int i, fail = 0;

    printf("constructor rejects unsupported sizes\n");
    for (i = 0; i < (int)(sizeof(bad) / sizeof(bad[0])); ++i) {
        aubio_fft_t *s = new_aubio_fft(bad[i]);
        if (s != NULL) {
            printf("  n=%4u: FAIL expected NULL\n", (unsigned)bad[i]);
            del_aubio_fft(s);
            fail = 1;
        } else {
            printf("  n=%4u: PASS (NULL)\n", (unsigned)bad[i]);
        }
    }

    printf("transform round trips against a direct DFT\n");
    for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); ++i)
        fail |= check_size(sizes[i]);

    printf(fail ? "PUBLIC_TEST=FAIL\n" : "PUBLIC_TEST=PASS\n");
    return fail ? 1 : 0;
}