/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "PCPS"
 *   int32  fft_len, npulses, fir_len, nin, nbin
 *   float64 chirp_rate, threshold_scale
 *   float64 x[nin]
 *   float64 profile[nbin]
 *   float64 noise_floor, threshold, peak_value, peak_bin,
 *           n_detections, first_bin, last_bin
 *
 * The generator refuses to emit a case whose profile has a bin within 1e-3
 * (peak-relative) of the threshold -- the detection count would then be
 * decided by rounding -- whose peak is not clearly above the runner-up, or
 * whose profile has an exact tie among the bins at or above the threshold
 * (the strict-left/non-strict-right local-maximum rule would depend on a tie).
 *
 * Usage: golden_gen <out-dir>
 */
#include "pulse_comp.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    for (ci = 0; ci < PC_NCASES; ++ci) {
        const pc_case *c = &pc_cases[ci];
        const int N = c->fft_len;
        const int np = c->npulses;
        const int nin = N * np;
        const int nb = pc_nrange_of(N);
        double *x = (double *)calloc((size_t)nin, sizeof(double));
        double *prof = (double *)calloc((size_t)nb, sizeof(double));
        double stats[7];
        float *fx = (float *)calloc((size_t)nin, sizeof(float));
        float *fprof = (float *)calloc((size_t)nb, sizeof(float));
        pc_config cfg;
        pc_state *st;
        pc_report rep;
        int got, i;
        double peak, thr, minmargin = 1e9;
        int ties = 0;

        if (!x || !prof || !fx || !fprof) {
            fprintf(stderr, "out of memory\n");
            return 2;
        }

        pc_make_signal(c, x);
        for (i = 0; i < nin; ++i) fx[i] = (float)x[i];

        cfg.fft_len = N;
        cfg.npulses = np;
        cfg.fir_len = c->fir_len;
        cfg.chirp_rate = (float)c->chirp_rate;
        cfg.threshold_scale = (float)c->thr_scale;

        st = pc_create(&cfg);
        if (!st) {
            fprintf(stderr, "case %d: pc_create failed\n", ci);
            return 2;
        }

        got = pc_process(st, fx, nin, fprof, &rep);
        pc_destroy(st);
        if (got != np) {
            fprintf(stderr, "case %d: processed %d pulses, expected %d\n",
                    ci, got, np);
            return 2;
        }

        for (i = 0; i < nb; ++i) prof[i] = (double)fprof[i];

        peak = (double)rep.peak_value;
        thr = (double)rep.threshold;
        if (!(peak > 0.0)) {
            fprintf(stderr, "case %d: non-positive peak\n", ci);
            return 2;
        }

        /* The detection count must not depend on a rounding accident. */
        for (i = 0; i < nb; ++i) {
            const double d = fabs(prof[i] - thr);

            if (d / peak < minmargin) minmargin = d / peak;
        }
        if (minmargin < 1e-3) {
            fprintf(stderr,
                    "case %d: a bin sits %.3e (peak-relative) from the "
                    "threshold; change thr_scale\n", ci, minmargin);
            return 2;
        }

        /* Exact ties inside the detection region would make the local-maximum
         * rule depend on the tie-breaking detail. */
        for (i = 0; i + 1 < nb; ++i) {
            if (prof[i] >= thr && prof[i] == prof[i + 1]) ++ties;
        }
        if (ties) {
            fprintf(stderr, "case %d: %d exact tie(s) at/above the threshold\n",
                    ci, ties);
            return 2;
        }

        {
            double second = 0.0;

            for (i = 0; i < nb; ++i) {
                if (i == rep.peak_bin) continue;
                if (prof[i] > second) second = prof[i];
            }
            if (second > 0.9999 * peak) {
                fprintf(stderr,
                        "case %d: peak is not separated from the runner-up\n",
                        ci);
                return 2;
            }
        }

        if (rep.n_detections < 1) {
            fprintf(stderr,
                    "case %d: nothing detected (floor=%.6g peak=%.6g "
                    "thr=%.6g peak/thr=%.3f)\n", ci,
                    (double)rep.noise_floor, (double)rep.peak_value,
                    (double)rep.threshold,
                    (double)rep.peak_value / (double)rep.threshold);
            return 2;
        }

        {
            char path[1024];
            int hdr[5] = { N, np, c->fir_len, nin, nb };
            FILE *fp;

            snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
            fp = fopen(path, "wb");
            if (!fp) {
                fprintf(stderr, "cannot write %s\n", path);
                return 2;
            }

            stats[0] = (double)rep.noise_floor;
            stats[1] = thr;
            stats[2] = (double)rep.peak_value;
            stats[3] = (double)rep.peak_bin;
            stats[4] = (double)rep.n_detections;
            stats[5] = (double)rep.first_bin;
            stats[6] = (double)rep.last_bin;

            fwrite("PCPS", 1, 4, fp);
            fwrite(hdr, sizeof(int), 5, fp);
            fwrite(&c->chirp_rate, sizeof(double), 1, fp);
            fwrite(&c->thr_scale, sizeof(double), 1, fp);
            fwrite(x, sizeof(double), (size_t)nin, fp);
            fwrite(prof, sizeof(double), (size_t)nb, fp);
            fwrite(stats, sizeof(double), 7, fp);
            fclose(fp);
        }

        printf("case %d: N=%4d np=%2d L=%2d chirp=%.2f thr=%5.1f -> "
               "%4d bins, floor=%.5f peak=%.5f bin=%4d det=%2d [%d..%d], "
               "margin=%.2e\n",
               ci, N, np, c->fir_len, c->chirp_rate, c->thr_scale, nb,
               (double)rep.noise_floor, (double)rep.peak_value, rep.peak_bin,
               rep.n_detections, rep.first_bin, rep.last_bin, minmargin);

        free(x); free(prof); free(fx); free(fprof);
    }

    return 0;
}