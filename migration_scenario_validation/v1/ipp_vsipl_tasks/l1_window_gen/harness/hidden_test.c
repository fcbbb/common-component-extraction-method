/* Hidden evaluation: applies the windows over the stored inputs and compares
 * with the IPP-generated outputs.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "win_gen.h"

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
        int type, n, i, ok = 1;
        float param;
        float *in = NULL, *exp = NULL, *got = NULL;
        FILE *f;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "WIND", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!get_i32(f, &type) ||
            fread(&param, sizeof(float), 1, f) != 1 ||
            !get_i32(f, &n)) {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }
        in  = (float *)malloc(sizeof(float) * (size_t)n);
        exp = (float *)malloc(sizeof(float) * (size_t)n);
        got = (float *)calloc((size_t)n, sizeof(float));
        if (!in || !exp || !got) return 2;
        if (fread(in, sizeof(float), (size_t)n, f) != (size_t)n ||
            fread(exp, sizeof(float), (size_t)n, f) != (size_t)n) {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        if (win_apply((win_type)type, param, in, got, n) != 0) {
            printf("case %d (type=%d n=%d): win_apply returned non-zero\n", ci, type, n);
            ++failures;
            free(in); free(exp); free(got);
            continue;
        }

        for (i = 0; i < n; ++i) {
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
        printf("case %d (type=%d param=%g n=%d): %s maxrel=%.3e\n",
               ci, type, (double)param, n, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
        free(in); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}