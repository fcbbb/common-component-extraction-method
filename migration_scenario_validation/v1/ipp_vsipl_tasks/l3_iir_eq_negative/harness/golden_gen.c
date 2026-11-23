/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout:
 *   "IIR1"
 *   int32 nsections, int32 block, int32 nblocks
 *   float32 sos[nsections * 5]
 *   float32 in[block * nblocks]
 *   float32 out[block * nblocks]
 *
 * Usage: golden_gen <out-dir>
 */
#include "iir_eq.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci;

    for (ci = 0; ci < IIR_NCASES; ++ci) {
        const iir_case *c = &iir_cases[ci];
        int total = c->block * c->nblocks;
        float *in = (float *)malloc(sizeof(float) * (size_t)total);
        float *out = (float *)malloc(sizeof(float) * (size_t)total);
        iir_eq *eq;
        FILE *f;
        int b;
        double peak = 0.0;

        if (!in || !out) return 2;
        iir_make_input(c, in, c->seed);

        eq = iir_eq_create(c->sos, c->nsections, c->block);
        if (!eq) { fprintf(stderr, "case %d: create failed\n", ci); return 2; }
        for (b = 0; b < c->nblocks; ++b) {
            if (iir_eq_process(eq, in + b * c->block, out + b * c->block, c->block) != 0) {
                fprintf(stderr, "case %d: process failed\n", ci); return 2;
            }
        }
        iir_eq_destroy(eq);

        for (b = 0; b < total; ++b) {
            double a = out[b] < 0 ? -(double)out[b] : (double)out[b];
            if (a > peak) peak = a;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        fwrite("IIR1", 1, 4, f);
        fwrite(&c->nsections, sizeof(int), 1, f);
        fwrite(&c->block, sizeof(int), 1, f);
        fwrite(&c->nblocks, sizeof(int), 1, f);
        fwrite(c->sos, sizeof(float), (size_t)c->nsections * 5, f);
        fwrite(in, sizeof(float), (size_t)total, f);
        fwrite(out, sizeof(float), (size_t)total, f);
        fclose(f);

        printf("case %d (nsections=%d block=%d nblocks=%d): peak=%.3f\n",
               ci, c->nsections, c->block, c->nblocks, peak);
        free(in); free(out);
    }
    return 0;
}