/* Hidden evaluation: replays every stored capture through the candidate pulse
 * compressor and compares the range profile and the detector report with the
 * buffers produced by the IPP baseline.
 *
 * The profile, the noise floor, the threshold and the peak value are compared
 * peak-relative; the peak bin and all three detection fields are compared
 * exactly (the generator only emits cases where they are unambiguous).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "pulse_comp.h"
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

    for (ci = 0; ci < PC_NCASES; ++ci) {
        char path[1024];
        int hdr[5];
        int N, np, L, nin, nb;
        double chirp_rate, thr_scale;
        double *dx, *dprof, *dstats;
        float *fx, *fprof;
        pc_config cfg;
        pc_state *st;
        pc_report rep;
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

            if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "PCPS", 4) != 0 ||
                fread(hdr, sizeof(int), 5, fp) != 5 ||
                fread(&chirp_rate, sizeof(double), 1, fp) != 1 ||
                fread(&thr_scale, sizeof(double), 1, fp) != 1) {
                fprintf(stderr, "case %d: bad header\n", ci);
                fclose(fp);
                ++failures;
                continue;
            }
        }

        N = hdr[0];
        np = hdr[1];
        L = hdr[2];
        nin = hdr[3];
        nb = hdr[4];

        if (nb != pc_nrange_of(N) || nin != N * np) {
            fprintf(stderr, "case %d: inconsistent header\n", ci);
            fclose(fp);
            ++failures;
            continue;
        }

        dx = (double *)calloc((size_t)nin, sizeof(double));
        dprof = (double *)calloc((size_t)nb, sizeof(double));
        dstats = (double *)calloc(7, sizeof(double));
        fx = (float *)calloc((size_t)nin, sizeof(float));
        fprof = (float *)calloc((size_t)nb, sizeof(float));

        if (!dx || !dprof || !dstats || !fx || !fprof) {
            fprintf(stderr, "case %d: out of memory\n", ci);
            return 2;
        }

        if (fread(dx, sizeof(double), (size_t)nin, fp) != (size_t)nin ||
            fread(dprof, sizeof(double), (size_t)nb, fp) != (size_t)nb ||
            fread(dstats, sizeof(double), 7, fp) != 7) {
            fprintf(stderr, "case %d: short read\n", ci);
            fclose(fp);
            ++failures;
            continue;
        }
        fclose(fp);

        for (i = 0; i < nin; ++i) fx[i] = (float)dx[i];

        cfg.fft_len = N;
        cfg.npulses = np;
        cfg.fir_len = L;
        cfg.chirp_rate = (float)chirp_rate;
        cfg.threshold_scale = (float)thr_scale;

        st = pc_create(&cfg);
        if (!st) {
            printf("case %d: pc_create failed\n", ci);
            ++failures;
            continue;
        }

        got = pc_process(st, fx, nin, fprof, &rep);
        pc_destroy(st);

        if (got != np) {
            printf("case %d: processed %d pulses, expected %d\n", ci, got, np);
            ++failures;
            continue;
        }

        {
            const double peak = (fabs(dstats[2]) > 1.0) ? fabs(dstats[2]) : 1.0;
            double r;

            for (i = 0; i < nb; ++i) {
                r = fabs((double)fprof[i] - dprof[i]) / peak;
                if (!(r <= cworst)) cworst = r;   /* NaN must show up here */
                /* `!(r <= RTOL)` rather than `r > RTOL`: a NaN must count as
                 * a failure, not slip through the comparison. */
                if (!(r <= RTOL)) {
                    if (bad < 3) printf("  profile[%d] rel %.3e\n", i, r);
                    ++bad;
                }
            }

            r = fabs((double)rep.noise_floor - dstats[0]) / peak;
            if (!(r <= cworst)) cworst = r;
            if (!(r <= RTOL)) {
                if (bad < 3) printf("  noise_floor rel %.3e\n", r);
                ++bad;
            }

            r = fabs((double)rep.threshold - dstats[1]) /
                ((fabs(dstats[1]) > 0.0) ? fabs(dstats[1]) : 1.0);
            if (!(r <= cworst)) cworst = r;
            if (!(r <= RTOL)) {
                if (bad < 3) printf("  threshold rel %.3e\n", r);
                ++bad;
            }

            r = fabs((double)rep.peak_value - dstats[2]) / peak;
            if (!(r <= cworst)) cworst = r;
            if (!(r <= RTOL)) {
                if (bad < 3) printf("  peak_value rel %.3e\n", r);
                ++bad;
            }
        }

        if (rep.peak_bin != (int)dstats[3]) {
            if (bad < 3)
                printf("  peak_bin got %d want %d\n",
                       rep.peak_bin, (int)dstats[3]);
            ++bad;
        }

        if (rep.n_detections != (int)dstats[4]) {
            if (bad < 3)
                printf("  n_detections got %d want %d\n",
                       rep.n_detections, (int)dstats[4]);
            ++bad;
        }

        if (rep.first_bin != (int)dstats[5] || rep.last_bin != (int)dstats[6]) {
            if (bad < 3)
                printf("  detection span got [%d..%d] want [%d..%d]\n",
                       rep.first_bin, rep.last_bin,
                       (int)dstats[5], (int)dstats[6]);
            ++bad;
        }

        /* The returned fields must also agree with the returned profile, so a
         * candidate cannot pass by hard-coding report numbers. */
        {
            double sum = 0.0;
            int count = 0, first = -1, last = -1;
            double floor_val, peak_val;
            int peak_bin = 0;

            for (i = 0; i < nb; ++i) sum += (double)fprof[i];
            floor_val = sum / (double)nb;
            peak_val = (double)fprof[0];
            for (i = 1; i < nb; ++i) {
                if ((double)fprof[i] > peak_val) {
                    peak_val = (double)fprof[i];
                    peak_bin = i;
                }
            }
            for (i = 0; i < nb; ++i) {
                const int left_ok = (i == 0) || fprof[i] > fprof[i - 1];
                const int right_ok = (i == nb - 1) || fprof[i] >= fprof[i + 1];

                if ((double)fprof[i] >= (double)rep.threshold && left_ok &&
                    right_ok) {
                    if (count == 0) first = i;
                    last = i;
                    ++count;
                }
            }

            if (fabs((double)rep.noise_floor - floor_val) > 1e-6 * peak_val) {
                if (bad < 3) printf("  noise_floor inconsistent with profile\n");
                ++bad;
            }
            if (rep.peak_bin != peak_bin ||
                fabs((double)rep.peak_value - peak_val) > 1e-6 * peak_val) {
                if (bad < 3) printf("  peak inconsistent with profile\n");
                ++bad;
            }
            if (rep.n_detections != count || rep.first_bin != first ||
                rep.last_bin != last) {
                if (bad < 3)
                    printf("  detections inconsistent with profile\n");
                ++bad;
            }
        }

        if (cworst > worst) worst = cworst;
        if (bad) ++failures;

        printf("case %d: N=%4d np=%2d L=%2d nin=%5d bins=%4d  "
               "worst_rel=%.3e  %s\n",
               ci, N, np, L, nin, nb, cworst, bad ? "FAIL" : "ok");

        free(dx); free(dprof); free(dstats); free(fx); free(fprof);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n",
           PC_NCASES, failures, worst);

    return failures ? 1 : 0;
}