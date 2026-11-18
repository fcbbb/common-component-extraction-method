/* Hidden evaluation: runs the library under test on the stored inputs and
 * compares decisions against the IPP-generated golden.
 *
 * Cells flagged ambiguous at generation time (threshold tie at float
 * precision) are not scored.  The returned detection count must also match the
 * number of flags the candidate itself set.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "cfar.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int get_i32(FILE *f, int *v) { return fread(v, sizeof(*v), 1, f) == 1; }

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;

    for (ci = 0; ; ++ci) {
        char magic[4];
        int nguard, ntrain, n, i, det, scored = 0, mism = 0, amb_n = 0;
        float pfa;
        float *mag2 = NULL;
        unsigned char *exp_flags = NULL, *amb = NULL, *got = NULL;
        cfar_state *s = NULL;
        FILE *f;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "CFAR", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!get_i32(f, &nguard) || !get_i32(f, &ntrain) || !get_i32(f, &n) ||
            fread(&pfa, sizeof(float), 1, f) != 1) {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }

        mag2      = (float *)malloc(sizeof(float) * (size_t)n);
        exp_flags = (unsigned char *)malloc((size_t)n);
        amb       = (unsigned char *)malloc((size_t)n);
        got       = (unsigned char *)calloc((size_t)n, 1);
        if (!mag2 || !exp_flags || !amb || !got) return 2;
        if (fread(mag2, sizeof(float), (size_t)n, f) != (size_t)n ||
            fread(exp_flags, 1, (size_t)n, f) != (size_t)n ||
            fread(amb, 1, (size_t)n, f) != (size_t)n) {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        s = cfar_create(nguard, ntrain, pfa);
        if (!s) { printf("case %d: create failed\n", ci); ++failures; goto next; }
        det = cfar_detect(s, mag2, n, got);
        cfar_destroy(s);
        if (det < 0) { printf("case %d: detect failed\n", ci); ++failures; goto next; }

        {
            int count = 0;
            for (i = 0; i < n; ++i) {
                count += got[i] ? 1 : 0;
                if (amb[i]) { ++amb_n; continue; }
                ++scored;
                if ((got[i] != 0) != (exp_flags[i] != 0)) ++mism;
            }
            if (count != det) {
                printf("case %d: returned %d but set %d flags\n", ci, det, count);
                ++failures;
                goto next;
            }
        }

        printf("case %d (nguard=%d ntrain=%d n=%d pfa=%.0e): %s "
               "scored=%d mismatch=%d ambiguous=%d\n",
               ci, nguard, ntrain, n, (double)pfa,
               mism == 0 ? "PASS" : "FAIL", scored, mism, amb_n);
        if (mism != 0) ++failures;
next:
        free(mag2); free(exp_flags); free(amb); free(got);
    }

    printf("SUMMARY cases=%d failures=%d\n", ci, failures);
    return failures == 0 ? 0 : 1;
}