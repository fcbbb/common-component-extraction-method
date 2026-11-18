/* Hidden evaluation: replays every stored case through the candidate DCT and
 * compares with the IPP-generated outputs.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "aubio_dct.h"

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
        int hdr[2];
        int size, op, i, ok = 1;
        float *in = NULL, *exp = NULL, *got = NULL;
        fvec_t fi, fo;
        aubio_dct_t *s;
        FILE *f;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "AUBD", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 2, f) != 2) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        size = hdr[0]; op = hdr[1];

        in  = (float *)malloc(sizeof(float) * (size_t)size);
        exp = (float *)malloc(sizeof(float) * (size_t)size);
        got = (float *)calloc((size_t)size, sizeof(float));
        if (!in || !exp || !got) return 2;
        if (fread(in, sizeof(float), (size_t)size, f) != (size_t)size ||
            fread(exp, sizeof(float), (size_t)size, f) != (size_t)size) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(f);

        s = new_aubio_dct((unsigned int)size);
        if (!s) {
            printf("case %d (n=%d op=%d): new_aubio_dct returned NULL\n", ci, size, op);
            ++failures;
            free(in); free(exp); free(got);
            continue;
        }
        fi.length = (unsigned int)size; fi.data = in;
        fo.length = (unsigned int)size; fo.data = got;
        if (op == 0) aubio_dct_do(s, &fi, &fo);
        else         aubio_dct_rdo(s, &fi, &fo);
        del_aubio_dct(s);

        for (i = 0; i < size; ++i) {
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
        printf("case %2d (n=%4d %s): %s maxrel=%.3e\n",
               ci, size, op == 0 ? "fwd" : "inv", ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
        free(in); free(exp); free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}