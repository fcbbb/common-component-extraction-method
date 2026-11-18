/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "DMFE"
 *   int32 nco_len, decim, ntaps, nin, block, nout, T
 *   float64 nco_re[nco_len], nco_im[nco_len]
 *   float64 taps_re[T], taps_im[T]
 *   float64 in_re[nin], in_im[nin]
 *   float64 out_re[nout], out_im[nout]
 *   float64 mean_power, peak, peak_index
 *
 * peak_index is stored as -1 when the two largest magnitudes are too close to
 * separate the winner reliably; the hidden test then skips the index check.
 *
 * Usage: golden_gen <out-dir>
 */
#include "demod_frontend.h"
#include "cases.h"
#include "dem_run.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    for (ci = 0; ci < DEM_NCASES; ++ci) {
        const dem_case *c = &dem_cases[ci];
        const int T = c->decim * c->ntaps;
        const int nout = dem_nout(c->decim, T, c->nin);
        uint64_t seed = 0xC0FFEE00ULL + (uint64_t)ci * 7717ULL;

        double *nco_re = (double *)calloc((size_t)c->nco_len * 2 + 1, sizeof(double));
        double *nco_im = nco_re + c->nco_len;
        double *tap_re = (double *)calloc((size_t)T * 2 + 1, sizeof(double));
        double *tap_im = tap_re + T;
        double *in_re = (double *)calloc((size_t)c->nin * 2 + 1, sizeof(double));
        double *in_im = in_re + c->nin;
        double *out_re = (double *)calloc((size_t)(nout > 0 ? nout : 1) * 2, sizeof(double));
        double *out_im = out_re + (nout > 0 ? nout : 1);

        float *fin_re = (float *)calloc((size_t)c->nin + 1, sizeof(float));
        float *fin_im = (float *)calloc((size_t)c->nin + 1, sizeof(float));
        float *fout_re = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        float *fout_im = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        float *fm_re = (float *)calloc((size_t)c->nco_len + 1, sizeof(float));
        float *fm_im = (float *)calloc((size_t)c->nco_len + 1, sizeof(float));
        float *ft_re = (float *)calloc((size_t)T + 1, sizeof(float));
        float *ft_im = (float *)calloc((size_t)T + 1, sizeof(float));
        float *mag;
        float mean_power = 0.0f, peak = 0.0f;
        int peak_index = 0;
        int got, i;

        if (!nco_re || !tap_re || !in_re || !out_re || !fin_re || !fin_im ||
            !fout_re || !fout_im || !fm_re || !fm_im || !ft_re || !ft_im) {
            fprintf(stderr, "out of memory\n");
            return 2;
        }

        dem_make_nco(c->nco_len, nco_re, nco_im, 0.37 + 0.11 * (double)ci);
        dem_make_taps(T, tap_re, tap_im, 0.16 + 0.02 * (double)ci);

        for (i = 0; i < c->nin; ++i) {
            in_re[i] = dem_rand(&seed);
            in_im[i] = dem_rand(&seed);
        }

        for (i = 0; i < c->nco_len; ++i) {
            fm_re[i] = (float)nco_re[i];
            fm_im[i] = (float)nco_im[i];
        }
        for (i = 0; i < T; ++i) {
            ft_re[i] = (float)tap_re[i];
            ft_im[i] = (float)tap_im[i];
        }
        for (i = 0; i < c->nin; ++i) {
            fin_re[i] = (float)in_re[i];
            fin_im[i] = (float)in_im[i];
        }

        mag = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        if (!mag) return 2;

        got = dem_run_session(c->nco_len, c->decim, c->ntaps, c->nin, c->block,
                              fm_re, fm_im, ft_re, ft_im, fin_re, fin_im,
                              fout_re, fout_im, nout, mag,
                              &mean_power, &peak, &peak_index);

        if (got != nout) {
            fprintf(stderr, "case %d: produced %d, expected %d\n", ci, got, nout);
            return 2;
        }

        for (i = 0; i < nout; ++i) {
            out_re[i] = (double)fout_re[i];
            out_im[i] = (double)fout_im[i];
        }

        /* Suppress the index when the runner-up is too close to call. */
        if (nout > 1 && peak_index >= 0) {
            double second = 0.0;
            for (i = 0; i < nout; ++i) {
                if (i == peak_index) continue;
                if ((double)mag[i] > second) second = (double)mag[i];
            }
            if (second > 0.9999 * (double)mag[peak_index]) peak_index = -1;
        }

        {
            char path[1024];
            int hdr[7] = { c->nco_len, c->decim, c->ntaps, c->nin, c->block,
                           nout, T };
            double stats[3];
            FILE *fp;

            snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
            fp = fopen(path, "wb");
            if (!fp) {
                fprintf(stderr, "cannot write %s\n", path);
                return 2;
            }

            stats[0] = (double)mean_power;
            stats[1] = (double)peak;
            stats[2] = (double)peak_index;

            fwrite("DMFE", 1, 4, fp);
            fwrite(hdr, sizeof(int), 7, fp);
            fwrite(nco_re, sizeof(double), (size_t)c->nco_len, fp);
            fwrite(nco_im, sizeof(double), (size_t)c->nco_len, fp);
            fwrite(tap_re, sizeof(double), (size_t)T, fp);
            fwrite(tap_im, sizeof(double), (size_t)T, fp);
            fwrite(in_re, sizeof(double), (size_t)c->nin, fp);
            fwrite(in_im, sizeof(double), (size_t)c->nin, fp);
            fwrite(out_re, sizeof(double), (size_t)nout, fp);
            fwrite(out_im, sizeof(double), (size_t)nout, fp);
            fwrite(stats, sizeof(double), 3, fp);
            fclose(fp);
        }

        printf("case %d: nco=%3d decim=%d taps=%2d nin=%4d block=%3d -> %4d out, "
               "mean_power=%.6f peak=%.6f idx=%d\n",
               ci, c->nco_len, c->decim, c->ntaps, c->nin, c->block, nout,
               (double)mean_power, (double)peak, peak_index);

        free(nco_re); free(tap_re); free(in_re); free(out_re);
        free(fin_re); free(fin_im); free(fout_re); free(fout_im);
        free(fm_re); free(fm_im); free(ft_re); free(ft_im); free(mag);
    }

    return 0;
}