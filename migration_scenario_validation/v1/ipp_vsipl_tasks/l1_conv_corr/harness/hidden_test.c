/* Hidden evaluation: replays every stored case through the candidate
 * implementation and compares with the IPP-generated outputs.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "conv_corr.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci) {
        char magic[4];
        int hdr[9];
        int op, region, bias, nh, nx, xstride, offset, ny, xlen, i, ok = 1;
        float *h = NULL, *x = NULL, *exp = NULL, *got = NULL;
        FILE *f;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "CCOR", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 9, f) != 9) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        op = hdr[0]; region = hdr[1]; bias = hdr[2];
        nh = hdr[3]; nx = hdr[4]; xstride = hdr[5];
        offset = hdr[6]; ny = hdr[7]; xlen = hdr[8];

        h   = (float *)malloc(sizeof(float) * (size_t)nh);
        x   = (float *)malloc(sizeof(float) * (size_t)xlen);
        exp = (float *)malloc(sizeof(float) * (size_t)ny);
        got = (float *)calloc((size_t)ny, sizeof(float));
        if (!h || !x || !exp || !got) return 2;
        if (fread(h, sizeof(float), (size_t)nh, f) != (size_t)nh ||
            fread(x, sizeof(float), (size_t)xlen, f) != (size_t)xlen ||
            fread(exp, sizeof(float), (size_t)ny, f) != (size_t)ny) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(f);

        {
            int rc;
            if (op == 0)
                rc = dsp_convolve(h, nh, x, nx, (dsp_region)region, got);
            else if (op == 1)
                rc = dsp_convolve_strided(h, nh, x, xstride, offset, nx,
                                          (dsp_region)region, got);
            else
                rc = dsp_correlate(h, nh, x, nx, (dsp_corr_bias)bias, got);
            if (rc != 0) {
                printf("case %d (op=%d nh=%d nx=%d): call returned %d\n",
                       ci, op, nh, nx, rc);
                ++failures;
                free(h); free(x); free(exp); free(got);
                continue;
            }
        }

        for (i = 0; i < ny; ++i) {
            double e = fabs((double)got[i] - (double)exp[i]);
            double rel = (fabs((double)exp[i]) > 1.0) ? e / fabs((double)exp[i]) : e;
            if (rel > maxerr) maxerr = rel;
            if (rel > 1e-4 && e > 1e-5) {
                if (ok)
                    printf("case %d: first mismatch at %d: got %.9g want %.9g\n",
                           ci, i, (double)got[i], (double)exp[i]);
                ok = 0;
            }
        }
        printf("case %2d (op=%d nh=%d nx=%d region=%d bias=%d stride=%d): %s maxrel=%.3e\n",
               ci, op, nh, nx, region, bias, xstride, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
        free(h); free(x); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}