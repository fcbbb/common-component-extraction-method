/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "RSPL"
 *   int32  up, down, ntaps, fft_len, nin, nout, block, nbin
 *   float64 cutoff
 *   float64 x[nin]
 *   float64 y[nout]          the converted stream, baseline
 *   float64 mag2[nbin]       periodogram of y
 *   float64 power, power_bin, total, centroid
 *
 * The generator refuses to emit a case whose spectral peak is not clearly
 * above the runner-up (power_bin would then be a coin toss).
 *
 * Usage: golden_gen <out-dir>
 */
#include "resampler.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    for (ci = 0; ci < RES_NCASES; ++ci) {
        const res_case *c = &res_cases[ci];
        const int nbin = c->fft_len / 2 + 1;
        const long nout = res_nout(c->up, c->down, c->ntaps, c->nin);
        const size_t yout = (size_t)(nout > 0 ? nout : 1);
        double *x = (double *)calloc((size_t)c->nin, sizeof(double));
        double *y = (double *)calloc(yout, sizeof(double));
        double *mag2 = (double *)calloc((size_t)nbin, sizeof(double));
        double stats[4];
        float *fx = (float *)calloc((size_t)c->nin, sizeof(float));
        float *fy = (float *)calloc(yout, sizeof(float));
        float *fout = (float *)calloc(yout, sizeof(float));
        float *fmag2 = (float *)calloc((size_t)nbin, sizeof(float));
        res_config cfg;
        res_state *st;
        res_report rep;
        int pos, i, frames, wpos = 0;
        double second = 0.0, peak;

        if (!x || !y || !mag2 || !fx || !fy || !fout || !fmag2) {
            fprintf(stderr, "out of memory\n");
            return 2;
        }

        res_make_signal(c, x);
        for (i = 0; i < c->nin; ++i) fx[i] = (float)x[i];

        cfg.up = c->up;
        cfg.down = c->down;
        cfg.ntaps = c->ntaps;
        cfg.cutoff = (float)c->cutoff;
        cfg.fft_len = c->fft_len;

        st = res_create(&cfg);
        if (!st) {
            fprintf(stderr, "case %d: res_create failed\n", ci);
            return 2;
        }

        for (pos = 0; pos < c->nin; pos += c->block) {
            int n = c->block;
            int got;

            if (pos + n > c->nin) n = c->nin - pos;
            if (wpos > (int)nout) {
                fprintf(stderr, "case %d: output overrun\n", ci);
                return 2;
            }
            got = res_process(st, fx + pos, n, fout, res_max_out(st, n));
            if (got < 0) {
                fprintf(stderr, "case %d: res_process failed\n", ci);
                return 2;
            }
            if (wpos + got > (int)nout) {
                fprintf(stderr, "case %d: more output than the case predicts\n",
                        ci);
                return 2;
            }
            memcpy(fy + wpos, fout, (size_t)got * sizeof(float));
            wpos += got;
        }

        if (wpos != (int)nout) {
            fprintf(stderr, "case %d: produced %d outputs, expected %ld\n",
                    ci, wpos, nout);
            return 2;
        }
        for (i = 0; i < nout; ++i) y[i] = (double)fy[i];

        frames = res_spectrum(st, fy, (int)nout, fmag2, &rep);
        if (frames <= 0) {
            fprintf(stderr, "case %d: spectrum needs nout >= fft_len\n", ci);
            return 2;
        }

        for (i = 0; i < nbin; ++i) mag2[i] = (double)fmag2[i];

        peak = (double)rep.power;
        for (i = 0; i < nbin; ++i) {
            if (i == rep.power_bin) continue;
            if (mag2[i] > second) second = mag2[i];
        }
        if (peak <= 0.0 || second > 0.9999 * peak) {
            fprintf(stderr, "case %d: peak is not separated from the runner-up\n",
                    ci);
            return 2;
        }

        {
            char path[1024];
            int hdr[8] = { c->up, c->down, c->ntaps, c->fft_len, c->nin,
                           (int)nout, c->block, nbin };
            FILE *fp;

            snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
            fp = fopen(path, "wb");
            if (!fp) {
                fprintf(stderr, "cannot write %s\n", path);
                return 2;
            }

            stats[0] = (double)rep.power;
            stats[1] = (double)rep.power_bin;
            stats[2] = (double)rep.total;
            stats[3] = (double)rep.centroid;

            fwrite("RSPL", 1, 4, fp);
            fwrite(hdr, sizeof(int), 8, fp);
            fwrite(&c->cutoff, sizeof(double), 1, fp);
            fwrite(x, sizeof(double), (size_t)c->nin, fp);
            fwrite(y, sizeof(double), (size_t)nout, fp);
            fwrite(mag2, sizeof(double), (size_t)nbin, fp);
            fwrite(stats, sizeof(double), 4, fp);
            fclose(fp);
        }

        printf("case %d: %3d/%3d taps=%2d fft=%4d nin=%4d block=%3d -> %4ld out, "
               "%3d bins, peak=%.4f bin=%2d centroid=%.3f\n",
               ci, c->up, c->down, c->ntaps, c->fft_len, c->nin, c->block,
               nout, nbin, (double)rep.power, rep.power_bin,
               (double)rep.centroid);

        res_destroy(st);
        free(x); free(y); free(mag2); free(fx); free(fy); free(fout);
        free(fmag2);
    }

    return 0;
}