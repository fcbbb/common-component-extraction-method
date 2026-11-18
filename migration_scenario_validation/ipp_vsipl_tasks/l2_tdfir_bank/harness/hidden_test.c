/* Hidden evaluation: runs the library under test on the stored inputs and
 * compares against the IPP-generated golden outputs.
 *
 * Usage: hidden_test <hidden-dir>
 * Prints one line per case plus a summary; exits non-zero on any failure.
 */
#include "tdfir.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int get_i32(FILE *f, int *v) { return fread(v, sizeof(*v), 1, f) == 1; }

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci) {
        char magic[4];
        int ntaps, nfilters, total, block;
        float *taps = NULL, *in = NULL, *exp = NULL, *got = NULL;
        tdfir_bank *b = NULL;
        FILE *f;
        int i, nblocks, blk, ok = 1;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break; /* no more cases */
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "TDF1", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!get_i32(f, &ntaps) || !get_i32(f, &nfilters) ||
            !get_i32(f, &total) || !get_i32(f, &block)) {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }
        nblocks = total / block;

        taps = (float *)malloc(sizeof(float) * ntaps * nfilters);
        in   = (float *)malloc(sizeof(float) * total);
        exp  = (float *)malloc(sizeof(float) * total * nfilters);
        got  = (float *)calloc((size_t)total * nfilters, sizeof(float));
        if (!taps || !in || !exp || !got) return 2;
        if (fread(taps, sizeof(float), (size_t)ntaps * nfilters, f) != (size_t)ntaps * nfilters ||
            fread(in, sizeof(float), (size_t)total, f) != (size_t)total ||
            fread(exp, sizeof(float), (size_t)total * nfilters, f) != (size_t)total * nfilters) {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        b = tdfir_create(taps, ntaps, nfilters, block);
        if (!b) { printf("case %d: create failed\n", ci); ++failures; continue; }
        for (blk = 0; blk < nblocks; ++blk) {
            if (tdfir_process(b, in + (size_t)blk * block,
                              got + (size_t)blk * block * nfilters, block) != 0) {
                printf("case %d: process failed\n", ci);
                ok = 0;
                break;
            }
        }
        tdfir_destroy(b);

        if (ok) {
            /* rtol 1e-4 / atol 1e-6: structural errors (wrong tap, wrong
             * filter, dropped state) are O(1), while summation-order
             * differences at float32 stay below 3e-6 on the 101-tap case. */
            for (i = 0; i < total * nfilters; ++i) {
                double e = fabs((double)got[i] - (double)exp[i]);
                double scale = fabs((double)exp[i]);
                double rel = (scale > 1.0) ? e / scale : e;
                if (rel > maxerr) maxerr = rel;
                if (rel > 1e-4 && e > 1e-6) ok = 0;
            }
        }
        printf("case %d (ntaps=%d nfilters=%d block=%d nblocks=%d): %s maxrel=%.3e\n",
               ci, ntaps, nfilters, block, nblocks, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;

        free(taps); free(in); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}