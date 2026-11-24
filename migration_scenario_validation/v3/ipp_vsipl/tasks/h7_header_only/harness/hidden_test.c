#include "burst_acq.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static int failures = 0;
static int checks = 0;

static void fill_input(int total, float *xr, float *xi,
                       float *nco_r, float *nco_i,
                       float *tap_r, float *tap_i,
                       float *ref_r, float *ref_i,
                       int nco_len, int M, int nref)
{
    int i;
    for (i = 0; i < total; ++i) {
        xr[i] = (float)(sin(0.31 * i + 0.2) + 0.25 * cos(0.17 * i));
        xi[i] = (float)(0.6 * cos(0.23 * i + 0.4));
    }
    for (i = 0; i < nco_len; ++i) {
        nco_r[i] = (float)cos(0.37 * i + 0.1);
        nco_i[i] = (float)sin(0.37 * i + 0.1);
    }
    for (i = 0; i < M; ++i) {
        tap_r[i] = (float)(cos(0.21 * i) - 0.3 * sin(0.11 * i));
        tap_i[i] = (float)(0.4 * sin(0.17 * i + 0.2));
    }
    for (i = 0; i < nref; ++i) {
        ref_r[i] = (float)(cos(0.43 * i) + 0.2 * sin(0.19 * i));
        ref_i[i] = (float)(0.5 * sin(0.29 * i + 0.3));
    }
}

static void ref_corr(const float *zr, const float *zi,
                     const float *hr, const float *hi,
                     int n, int k, double *out_r, double *out_i)
{
    double sr = 0.0, si = 0.0;
    int j;
    for (j = 0; j < n; ++j) {
        const int q = j - k;
        if (q < 0 || q >= n) continue;
        sr += (double)zr[j] * hr[q] + (double)zi[j] * hi[q];
        si += (double)zi[j] * hr[q] - (double)zr[j] * hi[q];
    }
    *out_r = sr;
    *out_i = si;
}

static int make_expected(int total, int nco_len, int decim, int ntaps,
                         int nref, const float *xr, const float *xi,
                         const float *nco_r, const float *nco_i,
                         const float *tap_r, const float *tap_i,
                         const float *ref_r, const float *ref_i,
                         float *out_r, float *out_i,
                         int *dec_count_out, int *frames_out)
{
    const int M = decim * ntaps;
    const int lags = 2 * nref - 1;
    float *mr = (float *)malloc((size_t)total * sizeof(float));
    float *mi = (float *)malloc((size_t)total * sizeof(float));
    float *dec_r = (float *)malloc((size_t)total / 2 * sizeof(float) + sizeof(float));
    float *dec_i = (float *)malloc((size_t)total / 2 * sizeof(float) + sizeof(float));
    int idx, dec_n = 0, frames, f, i;

    if (!mr || !mi || !dec_r || !dec_i) {
        free(mr); free(mi); free(dec_r); free(dec_i);
        return -1;
    }
    for (idx = 0; idx < total; ++idx) {
        const int tap = idx % nco_len;
        mr[idx] = xr[idx] * nco_r[tap] - xi[idx] * nco_i[tap];
        mi[idx] = xr[idx] * nco_i[tap] + xi[idx] * nco_r[tap];
    }
    for (idx = M; idx < total; ++idx) {
        if (idx % decim != 0) continue;
        {
            float yr = 0.0f, yi = 0.0f;
            int t;
            for (t = 0; t < M; ++t) {
                const float hr = tap_r[t], hi = tap_i[t];
                const float xr_ = mr[idx - t], xi_ = mi[idx - t];
                yr += hr * xr_ - hi * xi_;
                yi += hr * xi_ + hi * xr_;
            }
            dec_r[dec_n] = yr;
            dec_i[dec_n] = yi;
            ++dec_n;
        }
    }
    frames = dec_n / nref;
    for (f = 0; f < frames; ++f) {
        for (i = 0; i < lags; ++i) {
            double rr, ri;
            ref_corr(dec_r + f * nref, dec_i + f * nref, ref_r, ref_i,
                     nref, i - (nref - 1), &rr, &ri);
            out_r[f * lags + i] = (float)rr;
            out_i[f * lags + i] = (float)ri;
        }
    }
    free(mr);
    free(mi);
    free(dec_r);
    free(dec_i);
    *dec_count_out = dec_n;
    *frames_out = frames;
    return 0;
}

static int run_split(int total, int nco_len, int decim, int ntaps, int nref,
                     int nfft, const float *xr, const float *xi,
                     const float *nco_r, const float *nco_i,
                     const float *tap_r, const float *tap_i,
                     const float *ref_r, const float *ref_i,
                     const int *chunks, int nchunks,
                     float *out_r, float *out_i, int *frames_out)
{
    ba_config cfg;
    ba_state *st;
    int off = 0, produced = 0, i;

    cfg.nco_len = nco_len;
    cfg.decim = decim;
    cfg.ntaps = ntaps;
    cfg.nref = nref;
    cfg.nfft = nfft;
    st = ba_create(&cfg);
    if (!st) return -1;
    if (ba_set_waveform(st, nco_r, nco_i, tap_r, tap_i,
                        ref_r, ref_i) != 0) {
        ba_destroy(st);
        return -1;
    }
    for (i = 0; i < nchunks; ++i) {
        int got = 0;
        const int cap = 64;
        if (ba_push(st, xr + off, xi + off, chunks[i],
                    out_r + produced * (2 * nref - 1),
                    out_i + produced * (2 * nref - 1),
                    cap, &got, NULL) != 0) {
            ba_destroy(st);
            return -1;
        }
        produced += got;
        off += chunks[i];
    }
    ba_destroy(st);
    *frames_out = produced;
    return 0;
}

static void check_splits(void)
{
    const int nco_len = 5, decim = 2, ntaps = 4, nref = 5, nfft = 32;
    const int total = 96, lags = 2 * 5 - 1;
    const int chunks_a[] = {96};
    const int chunks_b[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 30};
    const int chunks_c[] = {7, 9, 13, 17, 21, 29};
    const int *splits[] = {chunks_a, chunks_b, chunks_c};
    const int counts[] = {1, 12, 6};
    float *xr = (float *)malloc((size_t)total * sizeof(float));
    float *xi = (float *)malloc((size_t)total * sizeof(float));
    float *nco_r = (float *)malloc((size_t)nco_len * sizeof(float));
    float *nco_i = (float *)malloc((size_t)nco_len * sizeof(float));
    float *tap_r = (float *)malloc((size_t)(decim * ntaps) * sizeof(float));
    float *tap_i = (float *)malloc((size_t)(decim * ntaps) * sizeof(float));
    float *ref_r = (float *)malloc((size_t)nref * sizeof(float));
    float *ref_i = (float *)malloc((size_t)nref * sizeof(float));
    float *want_r = (float *)malloc((size_t)total * lags * sizeof(float));
    float *want_i = (float *)malloc((size_t)total * lags * sizeof(float));
    float *got_r = (float *)malloc((size_t)total * lags * sizeof(float));
    float *got_i = (float *)malloc((size_t)total * lags * sizeof(float));
    int exp_frames = 0, exp_dec = 0, s;

    fill_input(total, xr, xi, nco_r, nco_i, tap_r, tap_i, ref_r, ref_i,
               nco_len, decim * ntaps, nref);
    ++checks;
    if (make_expected(total, nco_len, decim, ntaps, nref, xr, xi,
                      nco_r, nco_i, tap_r, tap_i, ref_r, ref_i,
                      want_r, want_i, &exp_dec, &exp_frames) != 0) {
        printf("FAIL expected setup\n");
        ++failures;
        goto out;
    }
    for (s = 0; s < 3; ++s) {
        int frames = 0;
        ++checks;
        if (run_split(total, nco_len, decim, ntaps, nref, nfft,
                      xr, xi, nco_r, nco_i, tap_r, tap_i, ref_r, ref_i,
                      splits[s], counts[s], got_r, got_i, &frames) != 0) {
            printf("FAIL split=%d run\n", s);
            ++failures;
            continue;
        }
        ++checks;
        if (frames != exp_frames) {
            printf("FAIL split=%d frames=%d want=%d dec=%d\n",
                   s, frames, exp_frames, exp_dec);
            ++failures;
            continue;
        }
        ++checks;
        for (int i = 0; i < frames * lags; ++i) {
            if (fabs((double)got_r[i] - want_r[i]) >
                    3e-4 * (fabs((double)want_r[i]) > 1.0 ?
                            fabs((double)want_r[i]) : 1.0) ||
                fabs((double)got_i[i] - want_i[i]) >
                    3e-4 * (fabs((double)want_i[i]) > 1.0 ?
                            fabs((double)want_i[i]) : 1.0)) {
                printf("FAIL split=%d lag=%d got=(%g,%g) want=(%g,%g)\n",
                       s, i, got_r[i], got_i[i], want_r[i], want_i[i]);
                ++failures;
                break;
            }
        }
    }
out:
    free(xr); free(xi); free(nco_r); free(nco_i);
    free(tap_r); free(tap_i); free(ref_r); free(ref_i);
    free(want_r); free(want_i); free(got_r); free(got_i);
}

static void check_capacity_and_ref(void)
{
    const int nco_len = 4, decim = 2, ntaps = 3, nref = 4, nfft = 16;
    const int total = 30, lags = 7, M = 6;
    float xr[30], xi[30], nco_r[4], nco_i[4], tap_r[6], tap_i[6];
    float ref_r[4], ref_i[4], out_r[120], out_i[120];
    ba_config cfg;
    ba_state *st;
    int nout = -1, i;

    fill_input(total, xr, xi, nco_r, nco_i, tap_r, tap_i, ref_r, ref_i,
               nco_len, M, nref);
    cfg.nco_len = nco_len;
    cfg.decim = decim;
    cfg.ntaps = ntaps;
    cfg.nref = nref;
    cfg.nfft = nfft;
    st = ba_create(&cfg);
    ++checks;
    if (!st) { printf("FAIL cap create\n"); ++failures; return; }
    if (ba_set_waveform(st, nco_r, nco_i, tap_r, tap_i,
                        ref_r, ref_i) != 0) {
        ++checks; printf("FAIL cap ref\n"); ++failures; ba_destroy(st); return;
    }
    ++checks;
    if (ba_push(st, xr, xi, total, out_r, out_i, 3, &nout, NULL) != 0 ||
        nout != 3) {
        printf("FAIL full push nout=%d\n", nout); ++failures;
    }
    (void)lags; (void)i;
    ba_destroy(st);
}

static void check_invalid(void)
{
    ba_config bad_a = {4, 2, 3, 4, 4};  /* nfft too small */
    ba_config bad_b = {4, 2, 3, 4, 12}; /* not power of two */
    ba_config bad_c = {0, 2, 3, 4, 16};
    ba_state *st;
    float f = 0.0f;

    st = ba_create(NULL);
    ++checks;
    if (st) { printf("FAIL null config\n"); ++failures; ba_destroy(st); }
    st = ba_create(&bad_a);
    ++checks;
    if (st) { printf("FAIL small nfft\n"); ++failures; ba_destroy(st); }
    st = ba_create(&bad_b);
    ++checks;
    if (st) { printf("FAIL non-power nfft\n"); ++failures; ba_destroy(st); }
    st = ba_create(&bad_c);
    ++checks;
    if (st) { printf("FAIL zero nco\n"); ++failures; ba_destroy(st); }
    ++checks;
    if (ba_set_waveform(NULL, &f, &f, &f, &f, &f, &f) != -1) ++failures;
    ++checks;
    if (ba_push(NULL, &f, &f, 1, &f, &f, 1, NULL, NULL) != -1) ++failures;
}

int main(void)
{
    check_splits();
    check_capacity_and_ref();
    check_invalid();
    printf("SUMMARY checks=%d failures=%d\n", checks, failures);
    return failures ? 1 : 0;
}