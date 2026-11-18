/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "CFAR"
 *   int32 nguard, int32 ntrain, int32 n, float32 pfa
 *   float32 mag2[n]
 *   uint8   flags[n]        golden decisions from the IPP implementation
 *   uint8   ambiguous[n]    1 where a last-bit threshold shift could flip the
 *                           decision; hidden_test ignores those cells
 *
 * Usage: golden_gen <out-dir>
 */
#include "cfar.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Double-precision reference used only to widen ties. */
static double dpdf_ref_alpha(int ntrain, double pfa)
{
    double n0 = 2.0 * ntrain;
    return n0 * (pow(pfa, -1.0 / n0) - 1.0);
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0x5EED1234ULL;
    int ci;

    for (ci = 0; ci < CFAR_NCASES; ++ci) {
        const cfar_case *c = &cfar_cases[ci];
        float *mag2 = (float *)malloc(sizeof(float) * (size_t)c->n);
        unsigned char *flags = (unsigned char *)calloc((size_t)c->n, 1);
        unsigned char *amb = (unsigned char *)calloc((size_t)c->n, 1);
        double alpha_d = dpdf_ref_alpha(c->ntrain, (double)c->pfa);
        cfar_state *s;
        FILE *f;
        int i, det;

        if (!mag2 || !flags || !amb) return 2;
        cfar_make_input(c, mag2, seed + (unsigned long long)ci * 7919ULL);

        s = cfar_create(c->nguard, c->ntrain, c->pfa);
        if (!s) { fprintf(stderr, "case %d: create failed\n", ci); return 2; }
        det = cfar_detect(s, mag2, c->n, flags);
        cfar_destroy(s);
        if (det < 0) { fprintf(stderr, "case %d: detect failed\n", ci); return 2; }

        /* Ambiguity band: a cell whose double-precision threshold is within
         * 1e-3 relative of the sample may legitimately flip. */
        for (i = 0; i < c->n; ++i) {
            int l0 = i - c->nguard - c->ntrain, l1 = i - c->nguard - 1;
            int r0 = i + c->nguard + 1, r1 = i + c->nguard + c->ntrain;
            double sum = 0.0, mean, thr;
            int cnt = 0, k;
            if (l0 < 0) l0 = 0;
            if (r1 > c->n - 1) r1 = c->n - 1;
            for (k = l0; k <= l1 && k < c->n; ++k) { sum += mag2[k]; ++cnt; }
            for (k = r0; k <= r1 && k < c->n; ++k) { sum += mag2[k]; ++cnt; }
            if (cnt == 0) continue;
            mean = sum / (double)cnt;
            thr = alpha_d * mean;
            if (fabs((double)mag2[i] - thr) <= 1e-3 * fabs(thr) + 1e-9)
                amb[i] = 1;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        fwrite("CFAR", 1, 4, f);
        fwrite(&c->nguard, sizeof(int), 1, f);
        fwrite(&c->ntrain, sizeof(int), 1, f);
        fwrite(&c->n, sizeof(int), 1, f);
        fwrite(&c->pfa, sizeof(float), 1, f);
        fwrite(mag2, sizeof(float), (size_t)c->n, f);
        fwrite(flags, 1, (size_t)c->n, f);
        fwrite(amb, 1, (size_t)c->n, f);
        fclose(f);

        printf("case %d (nguard=%d ntrain=%d n=%d pfa=%.0e): detections=%d\n",
               ci, c->nguard, c->ntrain, c->n, (double)c->pfa, det);
        free(mag2); free(flags); free(amb);
    }
    return 0;
}