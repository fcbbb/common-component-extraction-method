/* Public test: the resampler against the defining sums.
 *
 * Nothing here calls into IPP and nothing uses a golden container.  The
 * reference is the contract in include/resampler.h evaluated directly in
 * double: the windowed-sinc prototype, its per-branch normalization, the
 * polyphase sum, and the periodogram definition.
 */
#include "resampler.h"

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

static unsigned long long rng = 0x2F1C6A9B4D3E5071ULL;

static double rnd(void)
{
    unsigned long long z = (rng += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z ^= z >> 31;
    return ((double)(z >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

static void make_signal(double *x, int nin)
{
    int n;

    for (n = 0; n < nin; ++n) {
        x[n] = 0.04 * rnd()
             + 0.6 * sin(2.0 * PI * 0.061 * (double)n + 0.3)
             + 0.3 * sin(2.0 * PI * 0.147 * (double)n + 1.9);
    }
}

static double sinc(double u)
{
    return (u == 0.0) ? 1.0 : sin(PI * u) / (PI * u);
}

/* Natural-order, normalized branches: hp[p*ntaps + k]. */
static void ref_branches(int up, int ntaps, double cutoff, double *hp)
{
    const int L = up * ntaps;
    const double c = 0.5 * (double)(L - 1);
    double *h = (double *)calloc((size_t)L, sizeof(double));
    int j, k, p;

    for (j = 0; j < L; ++j) {
        const double d = (double)j - c;
        const double w = 0.5 * (1.0 - cos(2.0 * PI * (double)j /
                                          (double)(L - 1)));

        h[j] = 2.0 * cutoff * sinc(2.0 * cutoff * d) * w;
    }

    for (p = 0; p < up; ++p) {
        double sum = 0.0;

        for (k = 0; k < ntaps; ++k) sum += h[p + k * up];
        for (k = 0; k < ntaps; ++k) hp[p * ntaps + k] = h[p + k * up] / sum;
    }

    free(h);
}

static long ref_first(int up, int down, int ntaps)
{
    return ((long)(ntaps - 1) * up + down - 1) / down;
}

static long ref_last(int up, int down, int nin)
{
    return (nin <= 0) ? -1 : ((long)nin * up - 1) / down;
}

static long ref_resample(int up, int down, int ntaps, double cutoff,
                         const double *x, int nin, double *y)
{
    const long m0 = ref_first(up, down, ntaps);
    const long m1 = ref_last(up, down, nin);
    double *hp;
    long m;
    int k;

    if (m1 < m0) return 0;

    hp = (double *)calloc((size_t)(up * ntaps), sizeof(double));
    ref_branches(up, ntaps, cutoff, hp);

    for (m = m0; m <= m1; ++m) {
        const long num = m * down;
        const long i = num / up;
        const int p = (int)(num % up);
        double acc = 0.0;

        for (k = 0; k < ntaps; ++k) acc += hp[p * ntaps + k] * x[i - k];
        y[m - m0] = acc;
    }

    free(hp);
    return m1 - m0 + 1;
}

/* Direct periodogram, rectangular window, non-overlapping frames. */
static int ref_spectrum(const double *x, int n, int fft_len, double *mag2)
{
    const int nbin = fft_len / 2 + 1;
    const int frames = (n >= fft_len) ? 1 + (n - fft_len) / fft_len : 0;
    int k, f, s;

    if (frames == 0) return 0;

    for (k = 0; k < nbin; ++k) {
        double acc = 0.0;

        for (f = 0; f < frames; ++f) {
            double re = 0.0, im = 0.0;

            for (s = 0; s < fft_len; ++s) {
                const double a = x[f * fft_len + s];
                const double th = -2.0 * PI * (double)k * (double)s /
                                  (double)fft_len;

                re += a * cos(th);
                im += a * sin(th);
            }
            acc += re * re + im * im;
        }
        mag2[k] = acc / (double)frames;
    }

    return frames;
}

static double worst_rel_f(const float *got, const double *want, int n,
                          double peak)
{
    double w = 0.0;
    int i;

    for (i = 0; i < n; ++i) {
        const double d = fabs((double)got[i] - want[i]) / peak;
        if (!(d <= w)) w = d;
    }
    return w;
}

static void check_resample(int up, int down, int ntaps, double cutoff, int nin,
                           const char *what)
{
    res_config cfg;
    res_state *st;
    double *x, *want, peak = 1.0;
    float *fx, *got, *out;
    long nout, gotn;
    int i;
    char name[96];

    x = (double *)calloc((size_t)nin, sizeof(double));
    make_signal(x, nin);

    want = (double *)calloc((size_t)((long)nin * up / down) + 8,
                            sizeof(double));
    nout = ref_resample(up, down, ntaps, cutoff, x, nin, want);
    for (i = 0; i < nout; ++i) {
        if (fabs(want[i]) > peak) peak = fabs(want[i]);
    }

    cfg.up = up;
    cfg.down = down;
    cfg.ntaps = ntaps;
    cfg.cutoff = (float)cutoff;
    cfg.fft_len = 64;
    st = res_create(&cfg);
    if (!st) {
        printf("%s: res_create failed\n", what);
        ++failures;
        return;
    }

    fx = (float *)calloc((size_t)nin, sizeof(float));
    out = (float *)calloc((size_t)res_max_out(st, nin) + 8, sizeof(float));
    got = (float *)calloc((size_t)(nout > 0 ? nout : 1) + 8, sizeof(float));
    for (i = 0; i < nin; ++i) fx[i] = (float)x[i];

    gotn = res_process(st, fx, nin, out, res_max_out(st, nin));
    snprintf(name, sizeof(name), "%s: output count", what);
    check(name, (gotn == nout) ? 0.0 : 1.0, 0.0);

    for (i = 0; i < nout; ++i) got[i] = out[i];
    snprintf(name, sizeof(name), "%s: stream vs direct sum", what);
    check(name, worst_rel_f(got, want, (int)nout, peak), 2e-5);

    res_destroy(st);
    free(x); free(want); free(fx); free(got); free(out);
}

/* The same stream fed whole, sample by sample and in 7-sample blocks must
 * produce the identical output. */
static void check_blocking(void)
{
    const int up = 5, down = 4, ntaps = 6, nin = 240;
    const double cutoff = 0.4;
    res_config cfg;
    double *x, *want;
    float *fx, *whole, *one, *seven, *tmp;
    long nout;
    int i, pos;
    char name[96];

    x = (double *)calloc((size_t)nin, sizeof(double));
    make_signal(x, nin);
    want = (double *)calloc((size_t)((long)nin * up / down) + 8,
                            sizeof(double));
    nout = ref_resample(up, down, ntaps, cutoff, x, nin, want);

    fx = (float *)calloc((size_t)nin, sizeof(float));
    whole = (float *)calloc((size_t)nout + 8, sizeof(float));
    one = (float *)calloc((size_t)nout + 8, sizeof(float));
    seven = (float *)calloc((size_t)nout + 8, sizeof(float));
    tmp = (float *)calloc((size_t)nout + 8, sizeof(float));
    for (i = 0; i < nin; ++i) fx[i] = (float)x[i];

    cfg.up = up; cfg.down = down; cfg.ntaps = ntaps;
    cfg.cutoff = (float)cutoff; cfg.fft_len = 64;

    {
        res_state *st = res_create(&cfg);
        res_process(st, fx, nin, whole, res_max_out(st, nin));
        res_destroy(st);
    }
    {
        res_state *st = res_create(&cfg);
        int w = 0;

        for (pos = 0; pos < nin; ++pos) {
            int got = res_process(st, fx + pos, 1, tmp, res_max_out(st, 1));

            memcpy(one + w, tmp, (size_t)got * sizeof(float));
            w += got;
        }
        snprintf(name, sizeof(name), "block 1 output count");
        check(name, (w == nout) ? 0.0 : 1.0, 0.0);
        res_destroy(st);
    }
    {
        res_state *st = res_create(&cfg);
        int w = 0;

        for (pos = 0; pos < nin; pos += 7) {
            const int n = (pos + 7 > nin) ? nin - pos : 7;
            int got = res_process(st, fx + pos, n, tmp, res_max_out(st, n));

            memcpy(seven + w, tmp, (size_t)got * sizeof(float));
            w += got;
        }
        snprintf(name, sizeof(name), "block 7 output count");
        check(name, (w == nout) ? 0.0 : 1.0, 0.0);
        res_destroy(st);
    }

    {
        int bad = 0;

        for (i = 0; i < nout; ++i) {
            if (whole[i] != one[i] || whole[i] != seven[i]) ++bad;
        }
        check("blocking does not change the stream", (double)bad, 0.0);
    }

    free(x); free(want); free(fx); free(whole); free(one); free(seven);
    free(tmp);
}

/* Two states in use at the same time must not share history: the first
 * stream's output must not change when the second is interleaved with it. */
static void check_isolation(void)
{
    const int up = 2, down = 1, ntaps = 8, nin = 80;
    const size_t cap = (size_t)(nin * up / down + 16);
    res_config cfg;
    double *xa, *ya;
    float *fa, *fb, *outa, *outb, *ref;
    res_state *sa, *sb;
    int i, pos, w, w2;
    char name[96];

    xa = (double *)calloc((size_t)nin, sizeof(double));
    ya = (double *)calloc(cap, sizeof(double));
    for (i = 0; i < nin; ++i) xa[i] = sin(2.0 * PI * 0.05 * (double)i);
    ref_resample(up, down, ntaps, 0.45, xa, nin, ya);

    fa = (float *)calloc((size_t)nin, sizeof(float));
    fb = (float *)calloc((size_t)nin, sizeof(float));
    outa = (float *)calloc(cap, sizeof(float));
    outb = (float *)calloc(cap, sizeof(float));
    ref = (float *)calloc(cap, sizeof(float));
    for (i = 0; i < nin; ++i) {
        fa[i] = (float)xa[i];
        fb[i] = (float)cos(2.0 * PI * 0.11 * (double)i) * 0.5f;
    }

    cfg.up = up; cfg.down = down; cfg.ntaps = ntaps;
    cfg.cutoff = 0.45f; cfg.fft_len = 64;

    /* alone */
    sa = res_create(&cfg);
    w = res_process(sa, fa, nin, ref, res_max_out(sa, nin));
    res_destroy(sa);

    /* interleaved with a second, different stream */
    sa = res_create(&cfg);
    sb = res_create(&cfg);
    w2 = 0;
    for (pos = 0; pos < nin; pos += 5) {
        const int n = (pos + 5 > nin) ? nin - pos : 5;

        w2 += res_process(sa, fa + pos, n, outa + w2, res_max_out(sa, n));
        res_process(sb, fb + pos, n, outb, res_max_out(sb, n));
    }
    res_destroy(sa);
    res_destroy(sb);

    snprintf(name, sizeof(name), "interleaved states: output count");
    check(name, (w2 == w) ? 0.0 : 1.0, 0.0);

    {
        int bad = 0;

        for (i = 0; i < w; ++i) if (outa[i] != ref[i]) ++bad;
        snprintf(name, sizeof(name), "interleaved states: stream unchanged");
        check(name, (double)bad, 0.0);
    }

    snprintf(name, sizeof(name), "interleaved states: stream A vs direct sum");
    check(name, worst_rel_f(outa, ya, w, 1.0), 2e-5);

    free(xa); free(ya); free(fa); free(fb);
    free(outa); free(outb); free(ref);
}

static void check_spectrum(void)
{
    const int up = 2, down = 1, ntaps = 8;
    const double cutoff = 0.45;
    const int nin = 512;
    const int fft_len = 128;
    const int nbin = fft_len / 2 + 1;
    res_config cfg;
    res_state *st;
    double *x, *y, *want, peak = 1.0, total = 0.0, weighted = 0.0;
    float *fx, *fy;
    float *mag2;
    res_report rep;
    int nout, i, frames;
    int argmax = -1;
    double top = -1.0;
    char name[96];

    x = (double *)calloc((size_t)nin, sizeof(double));
    make_signal(x, nin);
    y = (double *)calloc((size_t)nin * 2 + 8, sizeof(double));
    want = (double *)calloc((size_t)nbin, sizeof(double));
    mag2 = (float *)calloc((size_t)nbin, sizeof(float));
    fx = (float *)calloc((size_t)nin, sizeof(float));
    fy = (float *)calloc((size_t)nin * 2 + 8, sizeof(float));
    for (i = 0; i < nin; ++i) fx[i] = (float)x[i];

    cfg.up = up; cfg.down = down; cfg.ntaps = ntaps;
    cfg.cutoff = (float)cutoff; cfg.fft_len = fft_len;
    st = res_create(&cfg);
    nout = (int)res_process(st, fx, nin, fy, res_max_out(st, nin));
    for (i = 0; i < nout; ++i) y[i] = (double)fy[i];

    frames = ref_spectrum(y, nout, fft_len, want);
    for (i = 0; i < nbin; ++i) {
        if (want[i] > peak) peak = want[i];
        total += want[i];
        weighted += (double)i * want[i];
        if (want[i] > top) { top = want[i]; argmax = i; }
    }

    {
        const int got = res_spectrum(st, fy, nout, mag2, &rep);

        snprintf(name, sizeof(name), "spectrum frame count");
        check(name, (got == frames) ? 0.0 : 1.0, 0.0);
        snprintf(name, sizeof(name), "mag2 vs direct DFT");
        check(name, worst_rel_f(mag2, want, nbin, peak), 2e-5);
        snprintf(name, sizeof(name), "peak bin");
        check(name, (rep.power_bin == argmax) ? 0.0 : 1.0, 0.0);
        snprintf(name, sizeof(name), "peak value");
        check(name, fabs((double)rep.power - top) / peak, 1e-6);
        snprintf(name, sizeof(name), "total power");
        check(name, fabs((double)rep.total - total) / peak, 1e-6);
        snprintf(name, sizeof(name), "centroid");
        check(name, fabs((double)rep.centroid - weighted / total) / nbin, 1e-6);
        snprintf(name, sizeof(name), "nbins");
        check(name, (rep.nbins == nbin) ? 0.0 : 1.0, 0.0);
    }

    res_destroy(st);
    free(x); free(y); free(want); free(mag2); free(fx); free(fy);
}

static void check_edges(void)
{
    res_config cfg;
    res_state *st;
    float x[64];
    float y[128];
    float mag2[33];
    res_report rep;
    int i;

    for (i = 0; i < 64; ++i) x[i] = 1.0f;
    for (i = 0; i < 33; ++i) mag2[i] = -12345.0f;

    cfg.up = 2; cfg.down = 1; cfg.ntaps = 8;
    cfg.cutoff = 0.45f; cfg.fft_len = 64;
    st = res_create(&cfg);

    check("nin == 0 emits nothing",
          (res_process(st, x, 0, y, res_max_out(st, 0)) == 0) ? 0.0 : 1.0, 0.0);
    check("n < fft_len analyses nothing",
          (res_spectrum(st, x, 32, mag2, &rep) == 0) ? 0.0 : 1.0, 0.0);
    check("n < fft_len leaves mag2 alone",
          (mag2[0] == -12345.0f && mag2[32] == -12345.0f) ? 0.0 : 1.0, 0.0);
    check("a too-small capacity is rejected",
          (res_process(st, x, 8, y, 1) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL state is rejected",
          (res_process(NULL, x, 8, y, 100) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL input is rejected",
          (res_process(st, NULL, 8, y, 100) == -1) ? 0.0 : 1.0, 0.0);
    check("NULL output is rejected",
          (res_process(st, x, 8, NULL, 100) == -1) ? 0.0 : 1.0, 0.0);
    check("res_max_out(NULL) is 0", (res_max_out(NULL, 10) == 0) ? 0.0 : 1.0,
          0.0);
    res_destroy(st);

    check("res_create rejects a NULL config",
          (res_create(NULL) == NULL) ? 0.0 : 1.0, 0.0);

    {
        int bad = 0;
        res_state *s;

        cfg.up = 0;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        cfg.up = 2; cfg.down = 0;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        cfg.down = 1; cfg.ntaps = 1;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        cfg.ntaps = 8; cfg.cutoff = 0.0f;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        cfg.cutoff = 0.5f;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        cfg.cutoff = 0.45f; cfg.fft_len = 96;
        if ((s = res_create(&cfg)) != NULL) { ++bad; res_destroy(s); }
        check("res_create rejects a bad configuration", (double)bad, 0.0);
    }
}

/* The advertised capacity bound must actually bound the output. */
static void check_max_out(void)
{
    res_config cfg;
    res_state *st;
    float in[200];
    float out[512];
    int bad = 0;
    int nin;

    for (nin = 0; nin < 200; ++nin) in[nin] = (float)sin(0.1 * (double)nin);

    cfg.up = 3; cfg.down = 7; cfg.ntaps = 9;
    cfg.cutoff = 0.4f; cfg.fft_len = 64;
    st = res_create(&cfg);

    for (nin = 1; nin <= 200; ++nin) {
        const int bound = res_max_out(st, nin);
        const long m0 = ref_first(3, 7, 9);
        const long m1 = ref_last(3, 7, nin);
        const long want = (m1 >= m0) ? m1 - m0 + 1 : 0;

        if (want > bound) ++bad;
    }
    /* feed the whole thing and check the bound really holds */
    {
        const int got = res_process(st, in, 200, out, res_max_out(st, 200));

        if (got < 0 || got > res_max_out(st, 200)) ++bad;
    }

    check("res_max_out bounds the output", (double)bad, 0.0);
    res_destroy(st);
}

int main(void)
{
    check_resample(2, 1, 8, 0.45, 400, "2/1 taps 8");
    check_resample(1, 2, 8, 0.45, 400, "1/2 taps 8");
    check_resample(5, 4, 6, 0.40, 300, "5/4 taps 6");
    check_resample(3, 2, 12, 0.30, 250, "3/2 taps 12");
    check_resample(1, 1, 4, 0.49, 200, "1/1 taps 4");
    check_blocking();
    check_isolation();
    check_spectrum();
    check_edges();
    check_max_out();

    if (failures == 0) {
        printf("PASS: 0 failure(s)\n");
        return 0;
    }

    printf("FAIL: %d failure(s)\n", failures);
    return 1;
}