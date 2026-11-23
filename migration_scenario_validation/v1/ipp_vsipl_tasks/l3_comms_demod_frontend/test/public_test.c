/* Public test: the frontend against brute-force references.
 *
 * The reference is the defining sum, not a second implementation of the
 * polyphase structure: mix with the wrapping NCO, then
 *     y[j] = sum_t h[t] * x[j*M - t]
 * evaluated directly in double.  Streaming is checked by replaying the same
 * session with different block sizes and requiring identical output.
 */
#include "demod_frontend.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

static void check(const char *name, double err, double tol)
{
    const int ok = (err <= tol);

    if (!ok) ++failures;
    printf("%-52s %-4s err=%.3e tol=%.1e\n", name, ok ? "ok" : "FAIL", err, tol);
}

static unsigned long long rng = 0x243F6A8885A308D3ULL;

static double rnd(void)
{
    unsigned long long z = (rng += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z ^= z >> 31;
    return ((double)(z >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

typedef struct {
    int nco_len, decim, ntaps;
    float *nco_re, *nco_im, *tap_re, *tap_im;
} ref_cfg;

/* Reference: mix the whole stream, then the raw decimating convolution. */
static int ref_session(const ref_cfg *c,
                       const float *in_re, const float *in_im, int nin,
                       double *out_re, double *out_im)
{
    const int T = c->decim * c->ntaps;
    double *xr;
    double *xi;
    int n, j, t;
    int produced = 0;

    xr = (double *)malloc((size_t)nin * sizeof(double));
    xi = (double *)malloc((size_t)nin * sizeof(double));
    if (!xr || !xi) { free(xr); free(xi); return -1; }

    for (n = 0; n < nin; ++n) {
        const int ph = n % c->nco_len;
        xr[n] = (double)in_re[n] * c->nco_re[ph] - (double)in_im[n] * c->nco_im[ph];
        xi[n] = (double)in_re[n] * c->nco_im[ph] + (double)in_im[n] * c->nco_re[ph];
    }

    for (j = 0; (long)j * c->decim <= (long)nin - 1; ++j) {
        double yr = 0.0, yi = 0.0;

        if ((long)j * c->decim < (long)(T - 1)) continue;

        for (t = 0; t < T; ++t) {
            const int idx = j * c->decim - t;

            yr += (double)c->tap_re[t] * xr[idx] - (double)c->tap_im[t] * xi[idx];
            yi += (double)c->tap_re[t] * xi[idx] + (double)c->tap_im[t] * xr[idx];
        }

        out_re[produced] = yr;
        out_im[produced] = yi;
        ++produced;
    }

    free(xr);
    free(xi);
    return produced;
}

/* Runs the candidate in chunks of `block`. */
static int run_chunks(const ref_cfg *c,
                      const float *in_re, const float *in_im, int nin, int block,
                      float *out_re, float *out_im)
{
    dem_config cfg;
    dem_state *st;
    int off = 0;
    int total = 0;

    cfg.nco_len = c->nco_len;
    cfg.decim = c->decim;
    cfg.ntaps = c->ntaps;

    st = dem_create(&cfg, c->nco_re, c->nco_im, c->tap_re, c->tap_im);
    if (!st) return -1;

    while (off < nin) {
        int n = nin - off;
        if (n > block) n = block;
        total += dem_process(st, in_re + off, in_im + off, n,
                             out_re + total, out_im + total);
        off += n;
    }

    dem_destroy(st);
    return total;
}

static void fill_cfg(ref_cfg *c, int nco_len, int decim, int ntaps)
{
    const int T = decim * ntaps;
    int i;

    c->nco_len = nco_len;
    c->decim = decim;
    c->ntaps = ntaps;
    c->nco_re = (float *)malloc((size_t)nco_len * sizeof(float));
    c->nco_im = (float *)malloc((size_t)nco_len * sizeof(float));
    c->tap_re = (float *)malloc((size_t)T * sizeof(float));
    c->tap_im = (float *)malloc((size_t)T * sizeof(float));

    for (i = 0; i < nco_len; ++i) {
        const double a = 6.28318530717958648 * 0.25 * (double)i / (double)nco_len;
        c->nco_re[i] = (float)cos(a);
        c->nco_im[i] = (float)(-sin(a));
    }
    for (i = 0; i < T; ++i) {
        c->tap_re[i] = (float)(1.0 / (double)(1 + i));
        c->tap_im[i] = (float)(0.3 / (double)(1 + i));
    }
}

static void free_cfg(ref_cfg *c)
{
    free(c->nco_re); free(c->nco_im); free(c->tap_re); free(c->tap_im);
}

static void check_pipeline(int nco_len, int decim, int ntaps, int nin, int block)
{
    ref_cfg c;
    const int T = decim * ntaps;
    float *in_re, *in_im, *ore, *oim;
    double *rre, *rim;
    char name[96];
    int i, j0;
    long jmax;
    int nref, ncand;
    double err = 0.0;

    fill_cfg(&c, nco_len, decim, ntaps);
    in_re = (float *)malloc((size_t)nin * sizeof(float));
    in_im = (float *)malloc((size_t)nin * sizeof(float));
    rre = (double *)malloc((size_t)nin * sizeof(double));
    rim = (double *)malloc((size_t)nin * sizeof(double));
    ore = (float *)calloc((size_t)nin + 1, sizeof(float));
    oim = (float *)calloc((size_t)nin + 1, sizeof(float));

    for (i = 0; i < nin; ++i) { in_re[i] = (float)rnd(); in_im[i] = (float)rnd(); }

    nref = ref_session(&c, in_re, in_im, nin, rre, rim);
    ncand = run_chunks(&c, in_re, in_im, nin, block, ore, oim);

    if (nref != ncand) {
        err = 1.0;
    } else {
        for (i = 0; i < nref; ++i) {
            if (fabs((double)ore[i] - rre[i]) > err) err = fabs((double)ore[i] - rre[i]);
            if (fabs((double)oim[i] - rim[i]) > err) err = fabs((double)oim[i] - rim[i]);
        }
    }

    j0 = (T - 1 + decim - 1) / decim;
    jmax = ((long)nin - 1) / decim;

    snprintf(name, sizeof(name), "pipeline vs brute force (M=%d T=%d blk=%d)",
             decim, T, block);
    check(name, err, 2e-5);

    if (nref != ncand) {
        printf("  produced %d, reference %d\n", ncand, nref);
    }
    (void)j0; (void)jmax;

    free(in_re); free(in_im); free(rre); free(rim); free(ore); free(oim);
    free_cfg(&c);
}

static void check_streaming_invariance(void)
{
    ref_cfg c;
    const int nin = 400;
    float *in_re, *in_im;
    float *a_re, *a_im, *b_re, *b_im, *d_re, *d_im;
    int na, nb, nd;
    int i;
    int same = 1;

    fill_cfg(&c, 5, 3, 4);
    in_re = (float *)malloc((size_t)nin * sizeof(float));
    in_im = (float *)malloc((size_t)nin * sizeof(float));
    a_re = (float *)calloc((size_t)nin, sizeof(float));
    a_im = (float *)calloc((size_t)nin, sizeof(float));
    b_re = (float *)calloc((size_t)nin, sizeof(float));
    b_im = (float *)calloc((size_t)nin, sizeof(float));
    d_re = (float *)calloc((size_t)nin, sizeof(float));
    d_im = (float *)calloc((size_t)nin, sizeof(float));

    for (i = 0; i < nin; ++i) { in_re[i] = (float)rnd(); in_im[i] = (float)rnd(); }

    na = run_chunks(&c, in_re, in_im, nin, nin, a_re, a_im);
    nb = run_chunks(&c, in_re, in_im, nin, 1, b_re, b_im);
    nd = run_chunks(&c, in_re, in_im, nin, 7, d_re, d_im);

    if (na != nb || na != nd) same = 0;
    for (i = 0; same && i < na; ++i) {
        if (a_re[i] != b_re[i] || a_im[i] != b_im[i]) same = 0;
        if (a_re[i] != d_re[i] || a_im[i] != d_im[i]) same = 0;
    }

    check("output independent of block splitting", same ? 0.0 : 1.0, 0.0);

    free(in_re); free(in_im);
    free(a_re); free(a_im); free(b_re); free(b_im); free(d_re); free(d_im);
    free_cfg(&c);
}

static void check_state_isolation(void)
{
    ref_cfg c;
    const int nin = 64;
    float in_re[64], in_im[64];
    float a_re[64], a_im[64], b_re[64], b_im[64];
    dem_config cfg;
    dem_state *s1;
    dem_state *s2;
    int i;
    int same;

    fill_cfg(&c, 4, 2, 4);
    cfg.nco_len = c.nco_len;
    cfg.decim = c.decim;
    cfg.ntaps = c.ntaps;

    for (i = 0; i < nin; ++i) { in_re[i] = (float)rnd(); in_im[i] = (float)rnd(); }

    s1 = dem_create(&cfg, c.nco_re, c.nco_im, c.tap_re, c.tap_im);
    s2 = dem_create(&cfg, c.nco_re, c.nco_im, c.tap_re, c.tap_im);

    memset(a_re, 0, sizeof(a_re));
    memset(a_im, 0, sizeof(a_im));
    memset(b_re, 0, sizeof(b_re));
    memset(b_im, 0, sizeof(b_im));

    /* interleave the two sessions: each must behave as if alone */
    dem_process(s1, in_re, in_im, 32, a_re, a_im);
    dem_process(s2, in_re, in_im, 32, b_re, b_im);
    dem_process(s1, in_re + 32, in_im + 32, 32, a_re + 16, a_im + 16);
    dem_process(s2, in_re + 32, in_im + 32, 32, b_re + 16, b_im + 16);

    same = 1;
    for (i = 0; i < 32; ++i) {
        if (a_re[i] != b_re[i] || a_im[i] != b_im[i]) same = 0;
    }

    check("independent states do not share history", same ? 0.0 : 1.0, 0.0);

    dem_destroy(s1);
    dem_destroy(s2);
    free_cfg(&c);
}

static void check_stats(void)
{
    const float re[4] = { 3.0f, 0.0f, -1.0f, 0.5f };
    const float im[4] = { 4.0f, 0.0f, 2.0f, -0.5f };
    float mag[4];
    float mean_power = 0.0f, peak = 0.0f;
    int idx = -1;
    double want = (25.0 + 0.0 + 5.0 + 0.5) / 4.0;

    dem_stats(re, im, 4, mag, &mean_power, &peak, &idx);

    check("magnitude", fabs(mag[0] - 5.0) + fabs(mag[2] - 2.2360679), 1e-5);
    check("mean power", fabs((double)mean_power - want), 1e-6);
    check("peak magnitude", fabs((double)peak - 5.0), 1e-6);
    check("peak index", (idx == 0) ? 0.0 : 1.0, 0.0);
}

static void check_edge_cases(void)
{
    ref_cfg c;
    dem_config cfg;
    dem_state *st;
    float in_re[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };
    float in_im[8] = { 0 };
    float out_re[8] = { 0 };
    float out_im[8] = { 0 };
    int got;
    double err = 0.0;

    fill_cfg(&c, 8, 4, 8);          /* T = 32, so no output from 8 samples */
    cfg.nco_len = c.nco_len;
    cfg.decim = c.decim;
    cfg.ntaps = c.ntaps;

    check("dem_create rejects a NULL config",
          (dem_create(NULL, c.nco_re, c.nco_im, c.tap_re, c.tap_im) == NULL)
              ? 0.0 : 1.0, 0.0);

    {
        dem_config bad = cfg;
        bad.decim = 0;
        if (dem_create(&bad, c.nco_re, c.nco_im, c.tap_re, c.tap_im) != NULL) err = 1.0;
        bad = cfg;
        bad.ntaps = 0;
        if (dem_create(&bad, c.nco_re, c.nco_im, c.tap_re, c.tap_im) != NULL) err = 1.0;
        bad = cfg;
        bad.nco_len = 0;
        if (dem_create(&bad, c.nco_re, c.nco_im, c.tap_re, c.tap_im) != NULL) err = 1.0;
    }
    check("dem_create rejects a zero dimension", err, 0.0);

    st = dem_create(&cfg, c.nco_re, c.nco_im, c.tap_re, c.tap_im);
    got = dem_process(st, in_re, in_im, 0, out_re, out_im);
    check("dem_process with nin=0 writes nothing", (got == 0) ? 0.0 : 1.0, 0.0);
    got = dem_process(st, in_re, in_im, 8, out_re, out_im);
    check("warm-up block produces no output", (got == 0) ? 0.0 : 1.0, 0.0);
    dem_destroy(st);

    free_cfg(&c);
}

int main(void)
{
    check_pipeline(8, 4, 8, 512, 512);
    check_pipeline(8, 4, 8, 512, 37);
    check_pipeline(5, 3, 5, 301, 100);
    check_pipeline(7, 1, 16, 256, 64);
    check_pipeline(3, 2, 32, 200, 200);
    check_streaming_invariance();
    check_state_isolation();
    check_stats();
    check_edge_cases();

    if (failures == 0) {
        printf("PASS: 0 failure(s)\n");
        return 0;
    }

    printf("FAIL: %d failure(s)\n", failures);
    return 1;
}