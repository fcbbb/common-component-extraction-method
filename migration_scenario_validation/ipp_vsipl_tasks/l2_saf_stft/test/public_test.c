/* Public tests: the visible half of the evaluation.
 *
 * These exercise the published SAF FFT API against a double-precision direct
 * DFT and against hand-computable identities.  They are deliberately small
 * and slow-path (no large FFTs), so a broken layout, a missing 1/N on the
 * inverse, or a wrong window all show up immediately.
 */
#include "saf_utility_fft.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL %s\n", msg); ++failures; } \
    else         { printf("ok   %s\n", msg); } \
} while (0)

static int failures = 0;

/* Direct DFT of a real sequence, half spectrum, in the natural interleaved
 * layout the component exchanges: out[2k] = Re, out[2k+1] = Im. */
static void ref_rfft(const double *x, int n, double *out)
{
    int k, i;
    for (k = 0; k <= n / 2; ++k) {
        double re = 0.0, im = 0.0;
        for (i = 0; i < n; ++i) {
            double a = -2.0 * M_PI * (double)k * (double)i / (double)n;
            re += x[i] * cos(a);
            im += x[i] * sin(a);
        }
        out[2 * k] = re;
        out[2 * k + 1] = im;
    }
}

static void ref_cfft(const double *xr, const double *xi, int n,
                     double *orr, double *oi)
{
    int k, i;
    for (k = 0; k < n; ++k) {
        double re = 0.0, im = 0.0;
        for (i = 0; i < n; ++i) {
            double a = -2.0 * M_PI * (double)k * (double)i / (double)n;
            double c = cos(a), s = sin(a);
            re += xr[i] * c - xi[i] * s;
            im += xr[i] * s + xi[i] * c;
        }
        orr[k] = re;
        oi[k] = im;
    }
}

static double peak(const double *v, int n)
{
    int i;
    double p = 0.0;
    for (i = 0; i < n; ++i) if (fabs(v[i]) > p) p = fabs(v[i]);
    return p > 1.0 ? p : 1.0;
}

static void fill(double *x, int n, unsigned seed)
{
    int i;
    srand(seed);
    for (i = 0; i < n; ++i) x[i] = (double)rand() / (double)RAND_MAX * 2.0 - 1.0;
}

static void check_rfft(int n)
{
    char msg[128];
    double *x = (double*)malloc(sizeof(double) * n);
    double *ref = (double*)malloc(sizeof(double) * (n + 2));
    double *got = (double*)malloc(sizeof(double) * (n + 2));
    float *in = (float*)malloc(sizeof(float) * n);
    float *back = (float*)malloc(sizeof(float) * n);
    float_complex *X = (float_complex*)malloc(sizeof(float_complex) * (n / 2 + 1));
    void *h;
    int i, bad = 0;
    double scale;

    fill(x, n, 1234u + (unsigned)n);
    for (i = 0; i < n; ++i) in[i] = (float)x[i];
    ref_rfft(x, n, ref);

    saf_rfft_create(&h, n);
    saf_rfft_forward(h, in, X);
    for (i = 0; i < n + 2; ++i) got[i] = (double)((float*)X)[i];
    saf_rfft_backward(h, X, back);
    saf_rfft_destroy(&h);

    scale = peak(ref, n + 2);
    for (i = 0; i < n + 2; ++i)
        if (fabs(got[i] - ref[i]) > 2.0e-4 * scale) ++bad;
    snprintf(msg, sizeof(msg), "rfft forward (n=%d) matches direct DFT", n);
    CHECK(bad == 0, msg);

    bad = 0;
    for (i = 0; i < n; ++i)
        if (fabs((double)back[i] - x[i]) > 2.0e-4 * peak(x, n)) ++bad;
    snprintf(msg, sizeof(msg), "rfft round trip (n=%d) recovers the input", n);
    CHECK(bad == 0, msg);

    free(x); free(ref); free(got); free(in); free(back); free(X);
}

static void check_cfft(int n)
{
    char msg[128];
    double *xr = (double*)malloc(sizeof(double) * n);
    double *xi = (double*)malloc(sizeof(double) * n);
    double *rr = (double*)malloc(sizeof(double) * n);
    double *ri = (double*)malloc(sizeof(double) * n);
    float_complex *x = (float_complex*)malloc(sizeof(float_complex) * n);
    float_complex *X = (float_complex*)malloc(sizeof(float_complex) * n);
    float_complex *y = (float_complex*)malloc(sizeof(float_complex) * n);
    void *h;
    int i, bad = 0;
    double scale;

    fill(xr, n, 77u + (unsigned)n);
    fill(xi, n, 99u + (unsigned)n);
    for (i = 0; i < n; ++i) x[i] = cmplxf((float)xr[i], (float)xi[i]);
    ref_cfft(xr, xi, n, rr, ri);

    saf_fft_create(&h, n);
    saf_fft_forward(h, x, X);
    saf_fft_backward(h, X, y);
    saf_fft_destroy(&h);

    scale = peak(rr, n);
    if (peak(ri, n) > scale) scale = peak(ri, n);
    for (i = 0; i < n; ++i) {
        if (fabs((double)crealf(X[i]) - rr[i]) > 2.0e-4 * scale) ++bad;
        if (fabs((double)cimagf(X[i]) - ri[i]) > 2.0e-4 * scale) ++bad;
    }
    snprintf(msg, sizeof(msg), "cfft forward (n=%d) matches direct DFT", n);
    CHECK(bad == 0, msg);

    bad = 0;
    for (i = 0; i < n; ++i) {
        if (fabs((double)crealf(y[i]) - xr[i]) > 2.0e-4 * peak(xr, n)) ++bad;
        if (fabs((double)cimagf(y[i]) - xi[i]) > 2.0e-4 * peak(xr, n)) ++bad;
    }
    snprintf(msg, sizeof(msg), "cfft round trip (n=%d) recovers the input", n);
    CHECK(bad == 0, msg);

    free(xr); free(xi); free(rr); free(ri); free(x); free(X); free(y);
}

static void check_stft_lti(void)
{
    const int win = 64, hop = 64, framesize = 128, nHops = framesize / hop;
    const int nBands = win + 1;
    float *data = (float*)malloc(sizeof(float) * framesize);
    float *out = (float*)malloc(sizeof(float) * framesize);
    float_complex ***fd = (float_complex***)calloc3d(nHops, 1, nBands, sizeof(float_complex));
    float *dataTD[1];
    float *outTD[1];
    double ref[65 * 2];
    void *h;
    int t, i, bad = 0;
    double scale;

    for (i = 0; i < framesize; ++i) data[i] = (float)(sin(0.1 * i) + 0.3 * cos(0.7 * i));
    dataTD[0] = data;
    outTD[0] = out;

    saf_stft_create(&h, win, hop, 1, 1, SAF_STFT_TIME_CH_BANDS);
    saf_stft_forward(h, dataTD, framesize, fd);
    saf_stft_backward(h, fd, framesize, outTD);
    saf_stft_destroy(&h);

    /* Every hop is an independent rectangular frame of length `win`, zero
     * padded to the 2*win FFT, so bin k of hop t is the direct DFT of that
     * frame.  Check hop 1 and the round trip of hop 0 against the input. */
    {
        double x[2 * win];
        for (i = 0; i < win; ++i) x[i] = (double)data[hop + i];
        for (i = win; i < 2 * win; ++i) x[i] = 0.0;
        ref_rfft(x, 2 * win, ref);
        scale = peak(ref, 2 * nBands);
        for (i = 0; i < nBands; ++i) {
            if (fabs((double)crealf(fd[1][0][i]) - ref[2 * i]) > 2.0e-4 * scale) ++bad;
            if (fabs((double)cimagf(fd[1][0][i]) - ref[2 * i + 1]) > 2.0e-4 * scale) ++bad;
        }
        CHECK(bad == 0, "stft forward (rectangular) matches direct DFT of the hop");
    }

    bad = 0;
    for (i = 0; i < win; ++i)
        if (fabs((double)out[i] - (double)data[i]) > 2.0e-4) ++bad;
    CHECK(bad == 0, "stft backward (rectangular, 1 block) recovers the frame");

    free(data);
    free(out);
}

static void check_conv(void)
{
    const int x_len = 16, h_len = 5;
    float x[16], hh[5], y[20];
    double ref[20];
    int i, j, bad = 0;

    for (i = 0; i < x_len; ++i) x[i] = (float)(sin(0.3 * i) + 0.1 * i);
    for (i = 0; i < h_len; ++i) hh[i] = (float)(1.0 - 0.2 * i);
    for (i = 0; i < x_len + h_len - 1; ++i) ref[i] = 0.0;
    for (i = 0; i < x_len; ++i)
        for (j = 0; j < h_len; ++j)
            ref[i + j] += (double)x[i] * (double)hh[j];

    fftconv(x, hh, x_len, h_len, 1, y);
    for (i = 0; i < x_len + h_len - 1; ++i)
        if (fabs((double)y[i] - ref[i]) > 2.0e-4 * peak(ref, x_len + h_len - 1)) ++bad;
    CHECK(bad == 0, "fftconv matches the direct time-domain convolution");
}

static void check_hilbert(void)
{
    const int n = 128;
    float_complex x[128], y[128];
    int i, bad = 0;

    for (i = 0; i < n; ++i)
        x[i] = cmplxf((float)cos(2.0 * M_PI * 8.0 * i / n), 0.0f);
    hilbert(x, n, y);
    /* The envelope of a pure tone is 1 (except at the end points, which the
     * FFT-based Hilbert transform handles differently). */
    for (i = 1; i < n - 1; ++i)
        if (fabs((double)cabsf(y[i]) - 1.0) > 2.0e-3) ++bad;
    CHECK(bad == 0, "hilbert envelope of a pure tone is unity");
}

static void check_freqvec(void)
{
    float fv[513];
    int i, bad = 0;
    getUniformFreqVector(1024, 48000.0f, fv);
    if (fv[0] != 0.0f) ++bad;
    for (i = 1; i <= 512; ++i)
        if (fabs((double)fv[i] - 48000.0 * (double)i / 1024.0) > 1.0e-2) ++bad;
    CHECK(bad == 0, "getUniformFreqVector spans 0..fs/2");
}

int main(void)
{
    check_rfft(64);
    check_rfft(100);
    check_cfft(32);
    check_cfft(100);
    check_stft_lti();
    check_conv();
    check_hilbert();
    check_freqvec();

    printf("%s: %d failure(s)\n", failures ? "FAIL" : "PASS", failures);
    return failures == 0 ? 0 : 1;
}