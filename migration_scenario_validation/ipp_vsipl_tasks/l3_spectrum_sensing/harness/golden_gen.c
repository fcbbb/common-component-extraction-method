/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "SPSE"
 *   int32  fft_len, frame_step, nin, nbin, nframes
 *   float64 thr_scale
 *   float64 x[nin]
 *   float64 psd[nbin]
 *   float64 noise_floor, peak_power, peak_bin, occ_bins
 *
 * The generator refuses to emit a case whose threshold runs too close to a
 * bin (the occupancy count would then be decided by rounding) or whose peak is
 * not clearly above the runner-up (the peak bin would be a coin toss).
 *
 * Usage: golden_gen <out-dir>
 */
#include "spectrum_sense.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    for (ci = 0; ci < SENS_NCASES; ++ci) {
        const sens_case *c = &sens_cases[ci];
        const int nbin = c->fft_len / 2 + 1;
        const int nframes = sens_nframes(c->fft_len, c->frame_step, c->nin);
        double *x = (double *)calloc((size_t)c->nin, sizeof(double));
        double *psd = (double *)calloc((size_t)nbin, sizeof(double));
        double stats[4];
        float *fx = (float *)calloc((size_t)c->nin, sizeof(float));
        float *fpsd = (float *)calloc((size_t)nbin, sizeof(float));
        sens_config cfg;
        sens_state *st;
        sens_report rep;
        int got, i;
        double peak, thr, minmargin = 1e9;

        if (!x || !psd || !fx || !fpsd) {
            fprintf(stderr, "out of memory\n");
            return 2;
        }

        sens_make_signal(c, x);
        for (i = 0; i < c->nin; ++i) fx[i] = (float)x[i];

        cfg.fft_len = c->fft_len;
        cfg.frame_step = c->frame_step;
        cfg.thr_scale = (float)c->thr_scale;

        st = sens_create(&cfg);
        if (!st) {
            fprintf(stderr, "case %d: sens_create failed\n", ci);
            return 2;
        }

        got = sens_analyze(st, fx, c->nin, fpsd, &rep);
        if (got != nframes) {
            fprintf(stderr, "case %d: analysed %d frames, expected %d\n",
                    ci, got, nframes);
            return 2;
        }

        for (i = 0; i < nbin; ++i) psd[i] = (double)fpsd[i];

        peak = (double)rep.peak_power;
        thr = c->thr_scale * (double)rep.noise_floor;

        /* The occupancy count must not depend on a rounding accident. */
        for (i = 0; i < nbin; ++i) {
            double d = fabs(psd[i] - thr);
            if (d / peak < minmargin) minmargin = d / peak;
        }
        if (minmargin < 1e-3) {
            fprintf(stderr,
                    "case %d: a bin sits %.3e (peak-relative) from the "
                    "threshold; change thr_scale\n", ci, minmargin);
            return 2;
        }

        {
            double second = 0.0;

            for (i = 0; i < nbin; ++i) {
                if (i == rep.peak_bin) continue;
                if (psd[i] > second) second = psd[i];
            }
            if (second > 0.9999 * peak) {
                fprintf(stderr,
                        "case %d: peak is not separated from the runner-up\n",
                        ci);
                return 2;
            }
        }

        {
            char path[1024];
            int hdr[5] = { c->fft_len, c->frame_step, c->nin, nbin, nframes };
            FILE *fp;

            snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
            fp = fopen(path, "wb");
            if (!fp) {
                fprintf(stderr, "cannot write %s\n", path);
                return 2;
            }

            stats[0] = (double)rep.noise_floor;
            stats[1] = (double)rep.peak_power;
            stats[2] = (double)rep.peak_bin;
            stats[3] = (double)rep.occ_bins;

            fwrite("SPSE", 1, 4, fp);
            fwrite(hdr, sizeof(int), 5, fp);
            fwrite(&c->thr_scale, sizeof(double), 1, fp);
            fwrite(x, sizeof(double), (size_t)c->nin, fp);
            fwrite(psd, sizeof(double), (size_t)nbin, fp);
            fwrite(stats, sizeof(double), 4, fp);
            fclose(fp);
        }

        printf("case %d: N=%4d step=%3d thr=%5.1f nin=%5d -> %4d frames, "
               "%3d bins, floor=%.4f peak=%.4f bin=%3d occ=%2d, margin=%.2e\n",
               ci, c->fft_len, c->frame_step, c->thr_scale, c->nin, nframes,
               nbin, (double)rep.noise_floor, (double)rep.peak_power,
               rep.peak_bin, rep.occ_bins, minmargin);

        sens_destroy(st);
        free(x); free(psd); free(fx); free(fpsd);
    }

    return 0;
}