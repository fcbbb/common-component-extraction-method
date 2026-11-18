/* Public test: the radar pulse-compression frontend against the defining sums.
 *
 * Nothing here calls into IPP and nothing uses a golden container.  The
 * reference is the contract in include/pulse_comp.h evaluated directly in
 * double:
 *
 *   r[i]      = w[i]*cos(pi*chirp_rate*u[i]^2/N),  w/u as defined
 *   z_p[l]    = sum_n x_p[n] * r[(n-l) mod N]              (l = 0 .. N/2)
 *   g[l]      = (1/(npulses*N)) * sum_p |z_p[l]|
 *   profile   = causal moving average of g with 1/L taps
 *
 * plus the report derived from the profile (mean, threshold, first maximum,
 * strict-left local maxima).
 */
#include "pulse_comp.h"

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
    printf("%-58s %-4s err=%.3e tol=%.1e\n", name, ok ? "ok" : "FAIL", err,
           tol);
}

static unsigned long long rng = 0x2B7E151628AED2A6ULL;

static double rnd(void)
{
    unsigned long long z = (rng += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z ^= z >> 31;
    return ((double)(z >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

static int nbin_of(int N)
{
    return N / 2 + 1;
}

static void ref_replica(const pc_config *cfg, double *r)
{
    const int N = cfg->fft_len;
    int i;

    for (i = 0; i < N; ++i) {
        const double w = 0.5 * (1.0 - cos(2.0 * PI * (double)i /
                                          (double)(N - 1)));
        const double u = (double)i - 0.5 * (double)(N - 1);
        const double ph = PI * (double)cfg->chirp_rate * u * u / (double)N;

        r[i] = w * cos(ph);
    }
}

/* Builds a capture of `cfg->npulses` pulses, each a sum of `nt` shifted
 * replicas plus a little noise. */
static void make_signal(const pc_config *cfg, const int *delay,
                        const double *amp, int nt, double noise, double *x)
{
    const int N = cfg->fft_len;
    double *r = (double *)calloc((size_t)N, sizeof(double));
    int p, n, t;

    ref_replica(cfg, r);

    for (p = 0; p < cfg->npulses; ++p) {
        double *xp = x + (size_t)p * (size_t)N;

        for (n = 0; n < N; ++n) xp[n] = noise * rnd();
        for (t = 0; t < nt; ++t) {
            for (n = 0; n < N; ++n) {
                const int m = ((n - delay[t]) % N + N) % N;

                xp[n] += amp[t] * r[m];
            }
        }
    }
    free(r);
}

/* Direct evaluation of the contract, in double. */
static void ref_profile(const pc_config *cfg, const float *x, double *prof)
{
    const int N = cfg->fft_len;
    const int nb = nbin_of(N);
    const int L = cfg->fir_len;
    double *r = (double *)calloc((size_t)N, sizeof(double));
    double *g = (double *)calloc((size_t)nb, sizeof(double));
    int p, l, n;

    ref_replica(cfg, r);

    for (p = 0; p < cfg->npulses; ++p) {
        const float *xp = x + (size_t)p * (size_t)N;

        for (l = 0; l < nb; ++l) {
            double zr = 0.0, zi = 0.0;

            for (n = 0; n < N; ++n) {
                const int m = ((n - l) % N + N) % N;

                zr += (double)xp[n] * r[m];
            }
            (void)zi;
            /* zr is the normalized correlation (1/N)*sum_k X*conj(R)*e^{+..};
             * the header's g uses the *unscaled* inner sum, i.e. N*zr. */
            g[l] += (double)N * fabs(zr);
        }
    }

    for (l = 0; l < nb; ++l) {
        double acc = 0.0;
        int j;

        for (j = 0; j < L; ++j) {
            const int m = l - j;

            if (m >= 0) acc += g[m];
        }
        prof[l] = acc / ((double)cfg->npulses * (double)N * (double)L);
    }

    free(g);
    free(r);
}

/* The report's detection fields, recomputed from a profile. */
static void ref_report(const float *prof, int nb, double thr_scale,
                       int *count, int *first, int *last, double *floor_val,
                       double *thr, int *peak_bin, double *peak_val)
{
    int k;
    double sum = 0.0;

    for (k = 0; k < nb; ++k) sum += (double)prof[k];
    *floor_val = sum / (double)nb;
    *thr = thr_scale * *floor_val;

    *peak_bin = 0;
    *peak_val = (double)prof[0];
    for (k = 1; k < nb; ++k) {
        if ((double)prof[k] > *peak_val) {
            *peak_val = (double)prof[k];
            *peak_bin = k;
        }
    }

    *count = 0;
    *first = -1;
    *last = -1;
    for (k = 0; k < nb; ++k) {
        const int left_ok = (k == 0) || (prof[k] > prof[k - 1]);
        const int right_ok = (k == nb - 1) || (prof[k] >= prof[k + 1]);

        if ((double)prof[k] >= *thr && left_ok && right_ok) {
            if (*count == 0) *first = k;
            *last = k;
            ++*count;
        }
    }
}

static double worst_rel(const float *got, const double *want, int n,
                        double peak)
{
    double w = 0.0;
    int i;

    for (i = 0; i < n; ++i) {
        const double d = fabs((double)got[i] - want[i]) / peak;
        if (d > w) w = d;
    }
    return w;
}

static void check_profile(int N, int npulses, int L, float chirp, float thr,
                          int nt, const char *what)
{
    pc_config cfg;
    pc_state *st;
    pc_report rep;
    double *x, *want;
    float *fx, *got;
    int delay[3] = { N / 8, N / 3, N / 2 - N / 8 };
    double amp[3] = { 1.0, 0.62, 0.37 };
    int nb = nbin_of(N);
    int i;
    double peak = 0.0;
    char name[128];

    if (nt > 3) nt = 3;

    x = (double *)calloc((size_t)npulses * (size_t)N, sizeof(double));
    want = (double *)calloc((size_t)nb, sizeof(double));
    fx = (float *)calloc((size_t)npulses * (size_t)N, sizeof(float));
    got = (float *)calloc((size_t)nb, sizeof(float));

    cfg.fft_len = N;
    cfg.npulses = npulses;
    cfg.fir_len = L;
    cfg.chirp_rate = chirp;
    cfg.threshold_scale = thr;

    make_signal(&cfg, delay, amp, nt, 0.01, x);
    for (i = 0; i < npulses * N; ++i) fx[i] = (float)x[i];

    ref_profile(&cfg, fx, want);
    for (i = 0; i < nb; ++i) if (want[i] > peak) peak = want[i];
    if (peak <= 0.0) peak = 1.0;

    st = pc_create(&cfg);
    if (!st) {
        printf("%s: pc_create failed\n", what);
        ++failures;
        free(x); free(want); free(fx); free(got);
        return;
    }

    snprintf(name, sizeof(name), "%s: pc_nrange", what);
    check(name, (pc_nrange(st) == nb) ? 0.0 : 1.0, 0.0);

    snprintf(name, sizeof(name), "%s: return value", what);
    check(name, (pc_process(st, fx, npulses * N, got, &rep) == npulses) ? 0.0
                                                                        : 1.0,
          0.0);
    pc_destroy(st);

    snprintf(name, sizeof(name), "%s: profile vs direct correlation", what);
    check(name, worst_rel(got, want, nb, peak), 3e-5);

    {
        double floor_val, thr_want, peak_want;
        int peak_bin, count, first, last;

        ref_report(got, nb, thr, &count, &first, &last, &floor_val, &thr_want,
                   &peak_bin, &peak_want);

        snprintf(name, sizeof(name), "%s: noise floor is the mean", what);
        check(name, fabs((double)rep.noise_floor - floor_val) / peak, 1e-6);

        snprintf(name, sizeof(name), "%s: threshold is scale*floor", what);
        check(name, fabs((double)rep.threshold - thr_want) /
                    (thr_want > 0.0 ? thr_want : 1.0), 1e-6);

        snprintf(name, sizeof(name), "%s: peak value and bin", what);
        check(name, fabs((double)rep.peak_value - peak_want) / peak, 1e-6);
        if (rep.peak_bin != peak_bin) ++failures;

        snprintf(name, sizeof(name), "%s: detection count", what);
        check(name, (rep.n_detections == count) ? 0.0 : 1.0, 0.0);

        snprintf(name, sizeof(name), "%s: at least one detection", what);
        check(name, (count >= 1 && rep.n_detections >= 1) ? 0.0 : 1.0, 0.0);

        snprintf(name, sizeof(name), "%s: first/last detection", what);
        check(name, (rep.first_bin == first && rep.last_bin == last) ? 0.0
                                                                     : 1.0,
              0.0);
    }

    free(x); free(want); free(fx); free(got);
}

/* One strong target, no smoothing: the correlation peak must sit on the
 * target's delay, which pins the lag sign, the inverse-transform convention
 * and the 1/N scaling together. */
static void check_delay(void)
{
    const int N = 128;
    const int d = 29;
    pc_config cfg;
    pc_state *st;
    pc_report rep;
    double x[128];
    float fx[128], prof[65];
    double amp[1] = { 1.0 };
    int delay[1] = { d };
    int i;
    double top = -1.0;
    int argmax = -1;

    cfg.fft_len = N;
    cfg.npulses = 1;
    cfg.fir_len = 1;
    cfg.chirp_rate = 0.5f;
    cfg.threshold_scale = 5.0f;

    make_signal(&cfg, delay, amp, 1, 0.0, x);
    for (i = 0; i < N; ++i) fx[i] = (float)x[i];

    st = pc_create(&cfg);
    pc_process(st, fx, N, prof, &rep);
    pc_destroy(st);

    for (i = 0; i <= N / 2; ++i) {
        if ((double)prof[i] > top) { top = (double)prof[i]; argmax = i; }
    }

    check("single target peaks on its delay", (argmax == d) ? 0.0 : 1.0, 0.0);
    check("peak_bin is that delay", (rep.peak_bin == d) ? 0.0 : 1.0, 0.0);
    check("the target is detected",
          (rep.n_detections >= 1 && rep.first_bin == d) ? 0.0 : 1.0, 0.0);

    /* For a unit-amplitude target the unscaled correlation peak is
     * sum(r^2), and g carries the 1/(npulses*N) factor, so the profile peak
     * is sum(r^2) exactly (L = 1 here). */
    {
        double r2 = 0.0;

        for (i = 0; i < N; ++i) {
            const double wi = 0.5 * (1.0 - cos(2.0 * PI * (double)i /
                                               (double)(N - 1)));
            const double u = (double)i - 0.5 * (double)(N - 1);
            const double ph = PI * 0.5 * u * u / (double)N;
            const double ri = wi * cos(ph);

            r2 += ri * ri;
        }
        check("peak level matches the autocorrelation energy",
              fabs(top / r2 - 1.0), 5e-3);
    }
}

static void check_determinism(void)
{
    const int N = 64;
    const int np = 3;
    pc_config cfg;
    pc_state *st;
    pc_report rep1, rep2;
    double x[192];
    float fx[192], p1[33], p2[33];
    int delay[1] = { 11 };
    double amp[1] = { 1.0 };
    int i, bad = 0;

    cfg.fft_len = N;
    cfg.npulses = np;
    cfg.fir_len = 3;
    cfg.chirp_rate = 0.4f;
    cfg.threshold_scale = 6.0f;

    make_signal(&cfg, delay, amp, 1, 0.02, x);
    for (i = 0; i < np * N; ++i) fx[i] = (float)x[i];

    st = pc_create(&cfg);
    pc_process(st, fx, np * N, p1, &rep1);
    pc_process(st, fx, np * N, p2, &rep2);
    pc_destroy(st);

    for (i = 0; i < N / 2 + 1; ++i) if (p1[i] != p2[i]) ++bad;
    check("repeated calls are bit-identical", (double)bad, 0.0);
    check("repeated calls give the same report",
          (memcmp(&rep1, &rep2, sizeof(rep1)) == 0) ? 0.0 : 1.0, 0.0);
}

static void check_edges(void)
{
    pc_config cfg;
    pc_state *st;
    float x[64];
    float prof[17];
    pc_report rep;
    int i;

    for (i = 0; i < 64; ++i) x[i] = 1.0f;
    for (i = 0; i < 17; ++i) prof[i] = -12345.0f;

    cfg.fft_len = 32;
    cfg.npulses = 2;
    cfg.fir_len = 1;
    cfg.chirp_rate = 0.5f;
    cfg.threshold_scale = 3.0f;
    st = pc_create(&cfg);

    check("a short capture is rejected",
          (pc_process(st, x, 32, prof, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("a long capture is rejected",
          (pc_process(st, x, 96, prof, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("a rejected call leaves the profile alone",
          (prof[0] == -12345.0f && prof[16] == -12345.0f) ? 0.0 : 1.0, 0.0);
    check("NULL signal is rejected",
          (pc_process(st, NULL, 64, prof, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL profile is rejected",
          (pc_process(st, x, 64, NULL, &rep) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL report is rejected",
          (pc_process(st, x, 64, prof, NULL) == -1) ? 0.0 : 1.0, 0.0);
    check("pc_nrange(NULL) is 0", (pc_nrange(NULL) == 0) ? 0.0 : 1.0, 0.0);
    pc_destroy(st);

    check("pc_create rejects a NULL config",
          (pc_create(NULL) == NULL) ? 0.0 : 1.0, 0.0);

    {
        int bad = 0;
        pc_state *s;

        cfg.fft_len = 24; cfg.npulses = 1; cfg.fir_len = 1;
        cfg.chirp_rate = 0.5f; cfg.threshold_scale = 3.0f;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.fft_len = 16;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.fft_len = 32; cfg.npulses = 0;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.npulses = 1; cfg.fir_len = 0;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.fir_len = 4;                    /* even */
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.fir_len = 16;                   /* too long */
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.fir_len = 3; cfg.chirp_rate = 0.0f;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        cfg.chirp_rate = 0.5f; cfg.threshold_scale = 0.0f;
        if ((s = pc_create(&cfg)) != NULL) { ++bad; pc_destroy(s); }

        check("pc_create rejects a bad configuration", (double)bad, 0.0);
    }
}

int main(void)
{
    check_profile(64, 4, 1, 0.80f, 3.0f, 3, "N=64 np=4 L=1");
    check_profile(128, 3, 3, 0.75f, 4.0f, 3, "N=128 np=3 L=3");
    check_profile(256, 2, 5, 0.80f, 4.0f, 2, "N=256 np=2 L=5");
    check_delay();
    check_determinism();
    check_edges();

    if (failures == 0) {
        printf("PASS: 0 failure(s)\n");
        return 0;
    }

    printf("FAIL: %d failure(s)\n", failures);
    return 1;
}