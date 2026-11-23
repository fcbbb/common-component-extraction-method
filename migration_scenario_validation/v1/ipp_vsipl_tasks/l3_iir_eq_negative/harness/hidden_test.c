/* Hidden evaluation: filters the stored inputs and compares with the
 * IPP-generated outputs.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "iir_eq.h"

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
        int nsections, block, nblocks, total, i, b, ok = 1;
        float *sos = NULL, *in = NULL, *exp = NULL, *got = NULL;
        iir_eq *eq = NULL;
        FILE *f;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "IIR1", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!get_i32(f, &nsections) || !get_i32(f, &block) || !get_i32(f, &nblocks)) {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }
        total = block * nblocks;

        sos = (float *)malloc(sizeof(float) * (size_t)nsections * 5);
        in  = (float *)malloc(sizeof(float) * (size_t)total);
        exp = (float *)malloc(sizeof(float) * (size_t)total);
        got = (float *)calloc((size_t)total, sizeof(float));
        if (!sos || !in || !exp || !got) return 2;
        if (fread(sos, sizeof(float), (size_t)nsections * 5, f) != (size_t)nsections * 5 ||
            fread(in, sizeof(float), (size_t)total, f) != (size_t)total ||
            fread(exp, sizeof(float), (size_t)total, f) != (size_t)total) {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        eq = iir_eq_create(sos, nsections, block);
        if (!eq) { printf("case %d: create failed\n", ci); ++failures; goto next; }
        for (b = 0; b < nblocks; ++b) {
            if (iir_eq_process(eq, in + b * block, got + b * block, block) != 0) {
                printf("case %d: process failed\n", ci);
                ok = 0;
                break;
            }
        }
        iir_eq_destroy(eq);

        if (ok) {
            for (i = 0; i < total; ++i) {
                double e = fabs((double)got[i] - (double)exp[i]);
                double scale = fabs((double)exp[i]);
                double rel = (scale > 1.0) ? e / scale : e;
                if (rel > maxerr) maxerr = rel;
                if (rel > 1e-4 && e > 1e-5) ok = 0;
            }
        }
        printf("case %d (nsections=%d block=%d nblocks=%d): %s maxrel=%.3e\n",
               ci, nsections, block, nblocks, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
next:
        free(sos); free(in); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}