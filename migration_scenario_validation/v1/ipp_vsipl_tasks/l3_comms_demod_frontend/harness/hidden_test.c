/* Hidden evaluation: replays every stored case through the candidate frontend
 * and compares with the buffers produced by the IPP baseline.
 *
 * The baseband output and the block statistics are compared relative to their
 * own peak (floored at 1.0); the peak index is compared exactly unless the
 * generator marked it ambiguous (-1).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "demod_frontend.h"
#include "cases.h"
#include "dem_run.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const double RTOL = 1.0e-5;

static double rel_err(double got, double want, double peak)
{
    return fabs(got - want) / peak;
}

int main(int argc, char **argv)
{
    const char *dir;
    int failures = 0;
    int ci;
    double worst = 0.0;

    if (argc < 2) {
        fprintf(stderr, "usage: hidden_test <hidden-dir>\n");
        return 2;
    }
    dir = argv[1];

    for (ci = 0; ci < DEM_NCASES; ++ci) {
        char path[1024];
        int hdr[7];
        int nco_len, decim, ntaps, nin, block, nout, T;
        double *d_nco_re, *d_nco_im, *d_tap_re, *d_tap_im;
        double *d_in_re, *d_in_im, *d_out_re, *d_out_im;
        double stats[3];
        float *nco_re_f, *nco_im_f, *tap_re_f, *tap_im_f;
        float *in_re_f, *in_im_f, *out_re_f, *out_im_f, *mag;
        float mean_power = 0.0f, peak = 0.0f;
        int peak_index = 0;
        int got;
        int bad = 0;
        double cworst = 0.0;
        int i;
        FILE *fp;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "rb");
        if (!fp) {
            fprintf(stderr, "case %d: cannot open %s\n", ci, path);
            ++failures;
            continue;
        }

        {
            char magic[4];
            if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "DMFE", 4) != 0 ||
                fread(hdr, sizeof(int), 7, fp) != 7) {
                fprintf(stderr, "case %d: bad header\n", ci);
                fclose(fp);
                ++failures;
                continue;
            }
        }

        nco_len = hdr[0];
        decim = hdr[1];
        ntaps = hdr[2];
        nin = hdr[3];
        block = hdr[4];
        nout = hdr[5];
        T = hdr[6];

        d_nco_re = (double *)calloc((size_t)nco_len * 2 + 2, sizeof(double));
        d_nco_im = d_nco_re + nco_len;
        d_tap_re = (double *)calloc((size_t)T * 2 + 2, sizeof(double));
        d_tap_im = d_tap_re + T;
        d_in_re = (double *)calloc((size_t)nin * 2 + 2, sizeof(double));
        d_in_im = d_in_re + nin;
        d_out_re = (double *)calloc((size_t)(nout > 0 ? nout : 1) * 2, sizeof(double));
        d_out_im = d_out_re + (nout > 0 ? nout : 1);

        nco_re_f = (float *)calloc((size_t)nco_len + 2, sizeof(float));
        nco_im_f = (float *)calloc((size_t)nco_len + 2, sizeof(float));
        tap_re_f = (float *)calloc((size_t)T + 2, sizeof(float));
        tap_im_f = (float *)calloc((size_t)T + 2, sizeof(float));
        in_re_f = (float *)calloc((size_t)nin + 2, sizeof(float));
        in_im_f = (float *)calloc((size_t)nin + 2, sizeof(float));
        out_re_f = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        out_im_f = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        mag = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));

        if (!d_nco_re || !d_tap_re || !d_in_re || !d_out_re || !nco_re_f ||
            !nco_im_f || !tap_re_f || !tap_im_f || !in_re_f || !in_im_f ||
            !out_re_f || !out_im_f || !mag) {
            fprintf(stderr, "case %d: out of memory\n", ci);
            return 2;
        }

        if (fread(d_nco_re, sizeof(double), (size_t)nco_len, fp) != (size_t)nco_len ||
            fread(d_nco_im, sizeof(double), (size_t)nco_len, fp) != (size_t)nco_len ||
            fread(d_tap_re, sizeof(double), (size_t)T, fp) != (size_t)T ||
            fread(d_tap_im, sizeof(double), (size_t)T, fp) != (size_t)T ||
            fread(d_in_re, sizeof(double), (size_t)nin, fp) != (size_t)nin ||
            fread(d_in_im, sizeof(double), (size_t)nin, fp) != (size_t)nin ||
            fread(d_out_re, sizeof(double), (size_t)nout, fp) != (size_t)nout ||
            fread(d_out_im, sizeof(double), (size_t)nout, fp) != (size_t)nout ||
            fread(stats, sizeof(double), 3, fp) != 3) {
            fprintf(stderr, "case %d: short read\n", ci);
            fclose(fp);
            ++failures;
            continue;
        }
        fclose(fp);

        for (i = 0; i < nco_len; ++i) {
            nco_re_f[i] = (float)d_nco_re[i];
            nco_im_f[i] = (float)d_nco_im[i];
        }
        for (i = 0; i < T; ++i) {
            tap_re_f[i] = (float)d_tap_re[i];
            tap_im_f[i] = (float)d_tap_im[i];
        }
        for (i = 0; i < nin; ++i) {
            in_re_f[i] = (float)d_in_re[i];
            in_im_f[i] = (float)d_in_im[i];
        }

        got = dem_run_session(nco_len, decim, ntaps, nin, block,
                              nco_re_f, nco_im_f, tap_re_f, tap_im_f,
                              in_re_f, in_im_f, out_re_f, out_im_f, nout, mag,
                              &mean_power, &peak, &peak_index);

        if (got != nout) {
            printf("case %d: produced %d complex samples, expected %d\n",
                   ci, got, nout);
            ++failures;
            continue;
        }

        {
            double peakv = 0.0;
            for (i = 0; i < nout; ++i) {
                double a = fabs(d_out_re[i]);
                if (fabs(d_out_im[i]) > a) a = fabs(d_out_im[i]);
                if (a > peakv) peakv = a;
            }
            if (peakv < 1.0) peakv = 1.0;

            for (i = 0; i < nout; ++i) {
                double r = rel_err((double)out_re_f[i], d_out_re[i], peakv);
                double m;
                if (r > cworst) cworst = r;
                if (r > RTOL) { if (bad < 3) printf("  re[%d] rel %.3e\n", i, r); ++bad; }
                m = rel_err((double)out_im_f[i], d_out_im[i], peakv);
                if (m > cworst) cworst = m;
                if (m > RTOL) { if (bad < 3) printf("  im[%d] rel %.3e\n", i, m); ++bad; }
            }

            {
                const double sp = (fabs(stats[1]) > 1.0) ? fabs(stats[1]) : 1.0;
                double r = rel_err((double)mean_power, stats[0], sp);
                if (r > cworst) cworst = r;
                if (r > RTOL) { if (bad < 3) printf("  mean_power rel %.3e\n", r); ++bad; }

                r = rel_err((double)peak, stats[1], sp);
                if (r > cworst) cworst = r;
                if (r > RTOL) { if (bad < 3) printf("  peak rel %.3e\n", r); ++bad; }

                if (stats[2] >= 0.0 && peak_index != (int)stats[2]) {
                    if (bad < 3)
                        printf("  peak_index got %d want %d\n",
                               peak_index, (int)stats[2]);
                    ++bad;
                }
            }
        }

        if (cworst > worst) worst = cworst;
        if (bad) ++failures;

        printf("case %d: nco=%3d decim=%d taps=%2d nin=%4d block=%3d out=%4d  "
               "worst_rel=%.3e  %s\n",
               ci, nco_len, decim, ntaps, nin, block, nout, cworst,
               bad ? "FAIL" : "ok");

        free(d_nco_re); free(d_tap_re); free(d_in_re); free(d_out_re);
        free(nco_re_f); free(nco_im_f); free(tap_re_f); free(tap_im_f);
        free(in_re_f); free(in_im_f); free(out_re_f); free(out_im_f); free(mag);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n",
           DEM_NCASES, failures, worst);

    return failures ? 1 : 0;
}