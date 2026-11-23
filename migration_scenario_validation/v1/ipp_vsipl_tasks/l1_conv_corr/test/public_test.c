/* Public self-check: every entry point against a direct double-precision
 * reference, plus the length conventions and the argument contract.
 */
#include "conv_corr.h"

#include <math.h>
#include <stdio.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static void h_of(int nh, float *h)
{
    int i;
    for (i = 0; i < nh; ++i) h[i] = (float)(0.3 + 0.7 * sin(1.7 * i + 0.2));
}

static void x_of(int n, float *x)
{
    int i;
    for (i = 0; i < n; ++i) x[i] = (float)(cos(0.31 * i) - 0.2 * sin(0.07 * i));
}

/* full convolution in double, length nh+nx-1 */
static void ref_conv(const float *h, int nh, const float *x, int nx, double *full)
{
    int i, j;
    for (i = 0; i < nh + nx - 1; ++i) {
        double s = 0.0;
        for (j = 0; j < nh; ++j) {
            int k = i - j;
            if (k >= 0 && k < nx) s += (double)h[j] * (double)x[k];
        }
        full[i] = s;
    }
}

static int close_enough(const char *tag, const double *got, const double *want, int n)
{
    int i, fail = 0;
    double worst = 0.0;

    for (i = 0; i < n; ++i) {
        double e = fabs(got[i] - want[i]);
        double rel = (fabs(want[i]) > 1.0) ? e / fabs(want[i]) : e;
        if (rel > worst) worst = rel;
        if (rel > 1e-5 && e > 1e-6) {
            if (!fail)
                printf("FAIL %s: index %d got %.9g want %.9g\n", tag, i, got[i], want[i]);
            fail = 1;
        }
    }
    printf("  %-26s %s maxrel=%.3e\n", tag, fail ? "FAIL" : "PASS", worst);
    return fail;
}

static int test_conv_full(void)
{
    const int nh = 3, nx = 5, ny = nh + nx - 1;
    float h[3], x[5], y[7];
    double full[7];
    int i, fail = 0;

    h_of(nh, h); x_of(nx, x);
    if (dsp_convolve(h, nh, x, nx, DSP_REGION_FULL, y) != 0) return 1;
    ref_conv(h, nh, x, nx, full);
    { double got[7]; for (i = 0; i < ny; ++i) got[i] = (double)y[i];
      fail |= close_enough("conv full 3x5", got, full, ny); }
    return fail;
}

static int test_conv_same(void)
{
    const int nh = 5, nx = 9, ny = nx;
    float h[5], x[9], y[9];
    double full[13], want[9];
    int i, fail = 0;

    h_of(nh, h); x_of(nx, x);
    if (dsp_convolve(h, nh, x, nx, DSP_REGION_SAME, y) != 0) return 1;
    ref_conv(h, nh, x, nx, full);
    for (i = 0; i < ny; ++i) want[i] = full[i + nh / 2];
    { double got[9]; for (i = 0; i < ny; ++i) got[i] = (double)y[i];
      fail |= close_enough("conv same 5x9", got, want, ny); }

    /* even kernel: the same region starts at nh/2 = 2, not (nh-1)/2 = 1 */
    { const int nh2 = 4, nx2 = 8;
      float h2[4], x2[8], y2[8];
      double full2[11], want2[8];
      h_of(nh2, h2); x_of(nx2, x2);
      if (dsp_convolve(h2, nh2, x2, nx2, DSP_REGION_SAME, y2) != 0) return 1;
      ref_conv(h2, nh2, x2, nx2, full2);
      for (i = 0; i < nx2; ++i) want2[i] = full2[i + nh2 / 2];
      { double got[8]; for (i = 0; i < nx2; ++i) got[i] = (double)y2[i];
        fail |= close_enough("conv same 4x8 (even)", got, want2, nx2); } }
    return fail;
}

static int test_conv_strided(void)
{
    const int nh = 5, nx = 12, stride = 3, offset = 2;
    const int xlen = offset + (nx - 1) * stride + 1;
    float h[5], buf[64], x[12], y[16];
    double full[16], want[16];
    int i, fail = 0;

    h_of(nh, h); x_of(xlen, buf);
    for (i = 0; i < nx; ++i) x[i] = buf[offset + i * stride];

    if (dsp_convolve_strided(h, nh, buf, stride, offset, nx, DSP_REGION_FULL, y) != 0)
        return 1;
    ref_conv(h, nh, x, nx, full);
    for (i = 0; i < nh + nx - 1; ++i) want[i] = full[i];
    { double got[16]; for (i = 0; i < nh + nx - 1; ++i) got[i] = (double)y[i];
      fail |= close_enough("conv strided 5x12 s3", got, want, nh + nx - 1); }
    return fail;
}

static int test_correlate(void)
{
    int i, j, fail = 0;

    /* biased, kernel shorter than data */
    { const int nh = 3, nx = 5, ny = nh + nx - 1;
      float h[3], x[5], y[7];
      double want[7], got[7];
      h_of(nh, h); x_of(nx, x);
      if (dsp_correlate(h, nh, x, nx, DSP_CORR_BIASED, y) != 0) return 1;
      for (i = 0; i < ny; ++i) {
          int lag = i - (nh - 1);
          double s = 0.0;
          for (j = 0; j < nh; ++j) { int k = j + lag; if (k >= 0 && k < nx) s += (double)h[j] * (double)x[k]; }
          want[i] = s;
      }
      for (i = 0; i < ny; ++i) got[i] = (double)y[i];
      fail |= close_enough("corr biased 3x5", got, want, ny); }

    /* unbiased with a kernel longer than the data: overlap counts 1,2,3,3,2,1,... */
    { const int nh = 7, nx = 5, ny = nh + nx - 1;
      float h[7], x[5], y[11];
      double want[11], got[11];
      h_of(nh, h); x_of(nx, x);
      if (dsp_correlate(h, nh, x, nx, DSP_CORR_UNBIASED, y) != 0) return 1;
      for (i = 0; i < ny; ++i) {
          int lag = i - (nh - 1);
          int j0 = lag < 0 ? -lag : 0;
          int j1 = (nx - lag < nh) ? (nx - lag) : nh;
          int cnt = j1 - j0;
          double s = 0.0;
          for (j = j0; j < j1; ++j) s += (double)h[j] * (double)x[j + lag];
          want[i] = cnt > 0 ? s / cnt : 0.0;
      }
      for (i = 0; i < ny; ++i) got[i] = (double)y[i];
      fail |= close_enough("corr unbiased 7x5", got, want, ny); }

    /* single-tap kernel: the correlation is a scaled copy of the data */
    { const int nh = 1, nx = 9, ny = nx;
      float h[1], x[9], y[9];
      double want[9], got[9];
      h_of(nh, h); x_of(nx, x);
      if (dsp_correlate(h, nh, x, nx, DSP_CORR_UNBIASED, y) != 0) return 1;
      for (i = 0; i < ny; ++i) want[i] = (double)h[0] * (double)x[i];
      for (i = 0; i < ny; ++i) got[i] = (double)y[i];
      fail |= close_enough("corr unbiased 1x9", got, want, ny); }

    return fail;
}

int main(void)
{
    float h[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
    float x[8] = { 1, 1, 1, 1, 1, 1, 1, 1 };
    float y[16];
    int fail = 0;

    printf("public_test:\n");
    fail |= test_conv_full();
    fail |= test_conv_same();
    fail |= test_conv_strided();
    fail |= test_correlate();

    /* nh = 1 with SAME is the identity region (offset 0) */
    if (dsp_convolve(h, 1, x, 8, DSP_REGION_SAME, y) != 0 ||
        fabs((double)y[0] - 1.0) > 1e-6 || fabs((double)y[7] - 1.0) > 1e-6) {
        printf("FAIL: nh=1 SAME is not the identity\n");
        fail = 1;
    }

    /* argument contract */
    if (dsp_convolve(NULL, 3, x, 8, DSP_REGION_FULL, y) != -1 ||
        dsp_convolve(h, 3, NULL, 8, DSP_REGION_FULL, y) != -1 ||
        dsp_convolve(h, 3, x, 8, DSP_REGION_FULL, NULL) != -1 ||
        dsp_convolve(h, 0, x, 8, DSP_REGION_FULL, y) != -1 ||
        dsp_convolve(h, 3, x, 0, DSP_REGION_FULL, y) != -1 ||
        dsp_convolve(h, 3, x, 8, (dsp_region)7, y) != -1 ||
        dsp_convolve_strided(h, 3, x, 0, 0, 8, DSP_REGION_FULL, y) != -1 ||
        dsp_convolve_strided(h, 3, x, 2, -1, 8, DSP_REGION_FULL, y) != -1 ||
        dsp_correlate(NULL, 3, x, 8, DSP_CORR_BIASED, y) != -1 ||
        dsp_correlate(h, 0, x, 8, DSP_CORR_BIASED, y) != -1 ||
        dsp_correlate(h, 3, x, 8, (dsp_corr_bias)5, y) != -1) {
        printf("FAIL: invalid arguments were not rejected\n");
        fail = 1;
    }

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}