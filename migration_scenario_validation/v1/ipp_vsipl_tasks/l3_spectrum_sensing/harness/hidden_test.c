/* Hidden evaluation: replays every stored capture through the candidate
 * spectrum sensor and compares the density and the detector report with the
 * buffers produced by the IPP baseline.
 *
 * The density and the two power statistics are compared peak-relative; the
 * peak bin and the occupancy count are compared exactly (the generator only
 * emits cases where both are unambiguous).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "spectrum_sense.h"
#include "cases.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const double RTOL = 1.0e-5;

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

    for (ci = 0; ci < SENS_NCASES; ++ci) {
        char path[1024];
        int hdr[5];
        int fft_len, frame_step, nin, nbin, nframes;
        double thr_scale;
        double *dx, *dpsd, *dstats;
        float *fx, *fpsd;
        sens_config cfg;
        sens_state *st;
        sens_report rep;
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
            if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "SPSE", 4) != 0 ||
                fread(hdr, sizeof(int), 5, fp) != 5 ||
                fread(&thr_scale, sizeof(double), 1, fp) != 1) {
                fprintf(stderr, "case %d: bad header\n", ci);
                fclose(fp);
                ++failures;
                continue;
            }
        }

        fft_len = hdr[0];
        frame_step = hdr[1];
        nin = hdr[2];
        nbin = hdr[3];
        nframes = hdr[4];

        dx = (double *)calloc((size_t)nin, sizeof(double));
        dpsd = (double *)calloc((size_t)nbin, sizeof(double));
        dstats = (double *)calloc(4, sizeof(double));
        fx = (float *)calloc((size_t)nin, sizeof(float));
        fpsd = (float *)calloc((size_t)nbin, sizeof(float));

        if (!dx || !dpsd || !dstats || !fx || !fpsd) {
            fprintf(stderr, "case %d: out of memory\n", ci);
            return 2;
        }

        if (fread(dx, sizeof(double), (size_t)nin, fp) != (size_t)nin ||
            fread(dpsd, sizeof(double), (size_t)nbin, fp) != (size_t)nbin ||
            fread(dstats, sizeof(double), 4, fp) != 4) {
            fprintf(stderr, "case %d: short read\n", ci);
            fclose(fp);
            ++failures;
            continue;
        }
        fclose(fp);

        for (i = 0; i < nin; ++i) fx[i] = (float)dx[i];

        cfg.fft_len = fft_len;
        cfg.frame_step = frame_step;
        cfg.thr_scale = (float)thr_scale;

        st = sens_create(&cfg);
        if (!st) {
            printf("case %d: sens_create failed\n", ci);
            ++failures;
            continue;
        }

        got = sens_analyze(st, fx, nin, fpsd, &rep);
        sens_destroy(st);

        if (got != nframes) {
            printf("case %d: analysed %d frames, expected %d\n",
                   ci, got, nframes);
            ++failures;
            continue;
        }

        {
            const double peak = (fabs(dstats[1]) > 1.0) ? fabs(dstats[1]) : 1.0;
            double r;

            for (i = 0; i < nbin; ++i) {
                r = fabs((double)fpsd[i] - dpsd[i]) / peak;
                if (!(r <= cworst)) cworst = r;   /* NaN must show up here */
                /* `!(r <= RTOL)` rather than `r > RTOL`: a NaN must count
                 * as a failure, not slip through the comparison. */
                if (!(r <= RTOL)) {
                    if (bad < 3) printf("  psd[%d] rel %.3e\n", i, r);
                    ++bad;
                }
            }

            r = fabs((double)rep.noise_floor - dstats[0]) / peak;
            if (!(r <= cworst)) cworst = r;
            if (!(r <= RTOL)) {
                if (bad < 3) printf("  noise_floor rel %.3e\n", r);
                ++bad;
            }

            r = fabs((double)rep.peak_power - dstats[1]) / peak;
            if (!(r <= cworst)) cworst = r;
            if (!(r <= RTOL)) {
                if (bad < 3) printf("  peak_power rel %.3e\n", r);
                ++bad;
            }
        }

        if (rep.peak_bin != (int)dstats[2]) {
            if (bad < 3)
                printf("  peak_bin got %d want %d\n",
                       rep.peak_bin, (int)dstats[2]);
            ++bad;
        }

        if (rep.occ_bins != (int)dstats[3]) {
            if (bad < 3)
                printf("  occ_bins got %d want %d\n",
                       rep.occ_bins, (int)dstats[3]);
            ++bad;
        }

        {
            double want_occ = (double)rep.occ_bins / (double)nbin;

            if (!(fabs((double)rep.occupancy - want_occ) <= 1e-6)) {
                if (bad < 3)
                    printf("  occupancy %.6f inconsistent with count\n",
                           (double)rep.occupancy);
                ++bad;
            }
        }

        if (cworst > worst) worst = cworst;
        if (bad) ++failures;

        printf("case %d: N=%4d step=%3d nin=%5d frames=%4d bins=%3d  "
               "worst_rel=%.3e  %s\n",
               ci, fft_len, frame_step, nin, nframes, nbin, cworst,
               bad ? "FAIL" : "ok");

        free(dx); free(dpsd); free(dstats); free(fx); free(fpsd);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n",
           SENS_NCASES, failures, worst);

    return failures ? 1 : 0;
}