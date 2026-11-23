/* Hidden evaluation: replays every stored case through the candidate filter
 * and compares with the IPP-generated outputs.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "fdfir.h"

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
        int hdr[3];
        int ntaps, nfft, nx, i, ok = 1;
        float *taps = NULL, *x = NULL, *exp = NULL, *got = NULL;
        FILE *f;
        fdfir *flt;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "FDFI", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 3, f) != 3) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        ntaps = hdr[0]; nfft = hdr[1]; nx = hdr[2];

        taps = (float *)malloc(sizeof(float) * (size_t)ntaps);
        x    = (float *)malloc(sizeof(float) * (size_t)nx);
        exp  = (float *)malloc(sizeof(float) * (size_t)nx);
        got  = (float *)calloc((size_t)nx, sizeof(float));
        if (!taps || !x || !exp || !got) return 2;
        if (fread(taps, sizeof(float), (size_t)ntaps, f) != (size_t)ntaps ||
            fread(x, sizeof(float), (size_t)nx, f) != (size_t)nx ||
            fread(exp, sizeof(float), (size_t)nx, f) != (size_t)nx) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(f);

        flt = fdfir_create(taps, ntaps, nfft);
        if (!flt) {
            printf("case %d (ntaps=%d nfft=%d nx=%d): fdfir_create returned NULL\n",
                   ci, ntaps, nfft, nx);
            ++failures;
            free(taps); free(x); free(exp); free(got);
            continue;
        }
        if (fdfir_apply(flt, x, nx, got) != 0) {
            printf("case %d (ntaps=%d nfft=%d nx=%d): fdfir_apply returned non-zero\n",
                   ci, ntaps, nfft, nx);
            ++failures;
            fdfir_destroy(flt);
            free(taps); free(x); free(exp); free(got);
            continue;
        }
        fdfir_destroy(flt);

        for (i = 0; i < nx; ++i) {
            double e = fabs((double)got[i] - (double)exp[i]);
            double rel = (fabs((double)exp[i]) > 1.0) ? e / fabs((double)exp[i]) : e;
            if (rel > maxerr) maxerr = rel;
            if (rel > 1e-4 && e > 1e-6) {
                if (ok)
                    printf("case %d: first mismatch at %d: got %.9g want %.9g\n",
                           ci, i, (double)got[i], (double)exp[i]);
                ok = 0;
            }
        }
        printf("case %2d (ntaps=%d nfft=%d nx=%d block=%d): %s maxrel=%.3e\n",
               ci, ntaps, nfft, nx, nfft - ntaps + 1, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
        free(taps); free(x); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}