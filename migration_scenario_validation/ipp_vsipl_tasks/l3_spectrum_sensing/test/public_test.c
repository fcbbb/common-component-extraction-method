/* Public test: the spectrum sensor against the defining sums.
 *
 * Nothing here calls into IPP and nothing uses a golden container.  The
 * reference is the periodogram definition evaluated directly in double,
 *     w[i]   = 0.5*(1 - cos(2*pi*i/(N-1)))
 *     psd[k] = (1/nframes) * sum_f |sum_n w[n]*x[f*step+n]*exp(-2*pi*i*k*n/N)|^2
 * for k = 0 .. N/2, plus the detector report derived from it.
 */
#include "spectrum_sense.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const double PI = 3.14159265358979324;
static int failures = 0;

static void check(const char *name, double err, double tol)
{
    const int ok = (err <= tol);

    if (!ok) ++failures;
    printf("%-56s %-4s err=%.3e tol=%.1e\n", name, ok ? "ok" : "FAIL", err, tol);
}

static unsigned long long rng = 0x105A3F2C4B5D6E7FULL;

static double rnd(void)
{
    unsigned long long z = (rng += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z ^= z >> 31;
    return ((double)(z >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

static void make_signal(double *x, int nin, int N)
{
    int n;

    for (n = 0; n < nin; ++n) {
        x[n] = 0.05 * rnd()
             + 0.7 * sin(2.0 * PI * 5.0 * (double)n / (double)N + 0.4)
             + 0.3 * sin(2.0 * PI * (double)(N / 3) * (double)n / (double)N);
    }
}

static double hann(int i, int N)
{
    return 0.5 * (1.0 - cos(2.0 * PI * (double)i / (double)(N - 1)));
}

/* Direct periodogram.  psd has room for N/2+1 bins. */
static int ref_psd(const double *x, int nin, int N, int step, double *psd)
{
    int nframes = (nin >= N) ? 1 + (nin - N) / step : 0;
    int k, f, n;

    if (nframes == 0) return 0;

    for (k = 0; k <= N / 2; ++k) {
        double acc = 0.0;

        for (f = 0; f < nframes; ++f) {
            double re = 0.0, im = 0.0;

            for (n = 0; n < N; ++n) {
                const double a = hann(n, N) * x[f * step + n];
                const double th = -2.0 * PI * (double)k * (double)n / (double)N;

                re += a * cos(th);
                im += a * sin(th);
            }
            acc += re * re + im * im;
        }

        psd[k] = acc / (double)nframes;
    }

    return nframes;
}

static double worst_rel(const float *got, const double *want, int n, double peak)
{
    double w = 0.0;
    int i;

    for (i = 0; i < n; ++i) {
        const double d = fabs((double)got[i] - want[i]) / peak;
        if (d > w) w = d;
    }
    return w;
}

static void check_periodogram(int N, int step, int nin, const char *what)
{
    sens_config cfg;
    sens_state *st;
    sens_report rep;
    double *x, *want;
    float *got;
    int nbin = N / 2 + 1;
    int nframes, i;
    double peak = 0.0;
    char name[96];

    x = (double *)calloc((size_t)nin, sizeof(double));
    want = (double *)calloc((size_t)nbin, sizeof(double));
    got = (float *)calloc((size_t)nbin, sizeof(float));

    make_signal(x, nin, N);
    nframes = ref_psd(x, nin, N, step, want);
    for (i = 0; i < nbin; ++i) if (want[i] > peak) peak = want[i];

    cfg.fft_len = N;
    cfg.frame_step = step;
    cfg.thr_scale = 4.0f;
    st = sens_create(&cfg);

    if (!st) {
        printf("%s: sens_create failed\n", what);
        ++failures;
        free(x); free(want); free(got);
        return;
    }

    if (sens_nbin(st) != nbin) {
        printf("%s: sens_nbin %d, expected %d\n", what, sens_nbin(st), nbin);
        ++failures;
    }

    {
        float *fx = (float *)calloc((size_t)nin, sizeof(float));
        int gotframes;
        double r;

        for (i = 0; i < nin; ++i) fx[i] = (float)x[i];
        gotframes = sens_analyze(st, fx, nin, got, &rep);

        snprintf(name, sizeof(name), "%s: frame count", what);
        check(name, (gotframes == nframes) ? 0.0 : 1.0, 0.0);

        snprintf(name, sizeof(name), "%s: density vs direct DFT", what);
        check(name, worst_rel(got, want, nbin, peak), 2e-5);

        /* The report must be consistent with the density the same call
         * returned, whatever the floating-point details. */
        r = fabs((double)rep.peak_power - (double)got[rep.peak_bin]) / peak;
        snprintf(name, sizeof(name), "%s: peak matches its bin", what);
        check(name, r, 1e-6);

        {
            double sum = 0.0;
            double thr = 4.0 * (double)rep.noise_floor;
            int occ = 0;

            for (i = 0; i < nbin; ++i) {
                sum += (double)got[i];
                if ((double)got[i] >= thr) ++occ;
            }
            snprintf(name, sizeof(name), "%s: noise floor is the mean", what);
            check(name, fabs((double)rep.noise_floor - sum / (double)nbin) / peak,
                  1e-6);
            snprintf(name, sizeof(name), "%s: occupancy count", what);
            check(name, (rep.occ_bins == occ) ? 0.0 : 1.0, 0.0);
        }

        free(fx);
    }

    sens_destroy(st);
    free(x); free(want); free(got);
}

/* A single tone must land on its bin: this pins the unscaled transform and the
 * window's amplitude convention as well as the bin ordering. */
static void check_tone(void)
{
    const int N = 128;
    const int bin = 17;
    const int nin = N * 4;
    sens_config cfg;
    sens_state *st;
    sens_report rep;
    float *x, *psd;
    int n, i;
    int argmax = -1;
    double top = -1.0;
    double sumw = 0.0;

    x = (float *)calloc((size_t)nin, sizeof(float));
    psd = (float *)calloc((size_t)(N / 2 + 1), sizeof(float));

    for (n = 0; n < nin; ++n) {
        x[n] = (float)cos(2.0 * PI * (double)bin * (double)n / (double)N);
    }
    for (i = 0; i < N; ++i) sumw += hann(i, N);

    cfg.fft_len = N;
    cfg.frame_step = N;
    cfg.thr_scale = 4.0f;
    st = sens_create(&cfg);
    sens_analyze(st, x, nin, psd, &rep);
    sens_destroy(st);

    for (i = 0; i <= N / 2; ++i) {
        if ((double)psd[i] > top) { top = (double)psd[i]; argmax = i; }
    }

    check("pure tone peaks on its bin", (argmax == bin) ? 0.0 : 1.0, 0.0);

    /* A full-scale cosine puts |X[bin]| = sum(w)/2 (the window transforms at
     * 2*bin leak about 0.1% into that), so the density is (sum(w)/2)^2. */
    check("pure tone energy matches the window DC gain",
          fabs(top / (0.25 * sumw * sumw) - 1.0), 0.02);

    free(x);
    free(psd);
}

static void check_edges(void)
{
    sens_config cfg;
    sens_state *st;
    float x[64];
    float psd[32];
    sens_report rep;
    int i;

    for (i = 0; i < 64; ++i) x[i] = 1.0f;
    for (i = 0; i < 32; ++i) psd[i] = -12345.0f;

    cfg.fft_len = 32;
    cfg.frame_step = 8;
    cfg.thr_scale = 3.0f;
    st = sens_create(&cfg);

    check("n < fft_len analyses nothing",
          (sens_analyze(st, x, 16, psd, &rep) == 0) ? 0.0 : 1.0, 0.0);
    check("n < fft_len leaves the density alone",
          (psd[0] == -12345.0f && psd[16] == -12345.0f) ? 0.0 : 1.0, 0.0);
    check("NULL input is rejected",
          (sens_analyze(st, NULL, 32, psd, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL density is rejected",
          (sens_analyze(st, x, 32, NULL, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL report is rejected",
          (sens_analyze(st, x, 32, psd, NULL) == -1) ? 0.0 : 1.0, 0.0);
    check("sens_nbin(NULL) is 0", (sens_nbin(NULL) == 0) ? 0.0 : 1.0, 0.0);
    sens_destroy(st);

    check("sens_create rejects a NULL config",
          (sens_create(NULL) == NULL) ? 0.0 : 1.0, 0.0);

    {
        int bad = 0;
        sens_state *s;

        cfg.fft_len = 24; cfg.frame_step = 8; cfg.thr_scale = 3.0f;
        if ((s = sens_create(&cfg)) != NULL) { ++bad; sens_destroy(s); }
        cfg.fft_len = 4;
        if ((s = sens_create(&cfg)) != NULL) { ++bad; sens_destroy(s); }
        cfg.fft_len = 32; cfg.frame_step = 0;
        if ((s = sens_create(&cfg)) != NULL) { ++bad; sens_destroy(s); }
        cfg.frame_step = 8; cfg.thr_scale = 0.0f;
        if ((s = sens_create(&cfg)) != NULL) { ++bad; sens_destroy(s); }
        check("sens_create rejects a bad configuration", (double)bad, 0.0);
    }
}

static void check_frame_count(void)
{
    sens_config cfg;
    sens_state *st;
    sens_report rep;
    float x[300];
    float psd[33];
    int i;
    int bad = 0;

    for (i = 0; i < 300; ++i) x[i] = (float)rnd();

    cfg.fft_len = 64;
    cfg.frame_step = 10;
    cfg.thr_scale = 3.0f;
    st = sens_create(&cfg);

    for (i = 0; i < 300; ++i) {
        const int want = (i < 64) ? 0 : 1 + (i - 64) / 10;

        if (sens_analyze(st, x, i, psd, &rep) != want) ++bad;
    }

    check("frame count follows ceil((n-N)/step)+1", (double)bad, 0.0);
    sens_destroy(st);
}

int main(void)
{
    check_periodogram(32, 16, 160, "N=32 step=16");
    check_periodogram(64, 64, 192, "N=64 step=64");
    check_periodogram(128, 32, 320, "N=128 step=32");
    check_tone();
    check_frame_count();
    check_edges();

    if (failures == 0) {
        printf("PASS: 0 failure(s)\n");
        return 0;
    }

    printf("FAIL: %d failure(s)\n", failures);
    return 1;
}