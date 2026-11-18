/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "DBMG"
 *   int32   n
 *   float32 floor_mag, offset
 *   float32 re[n], im[n]
 *   float32 expected[n]
 *
 * Usage: golden_gen <out-dir>
 */
#include "dbmag.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0xD1B0A6ULL;
    int ci;

    for (ci = 0; ci < DBMAG_NCASES; ++ci) {
        const dbmag_case *c = &dbmag_cases[ci];
        float *re = (float *)malloc(sizeof(float) * (size_t)c->n);
        float *im = (float *)malloc(sizeof(float) * (size_t)c->n);
        float *out = (float *)malloc(sizeof(float) * (size_t)c->n);
        FILE *f;

        if (!re || !im || !out) return 2;
        dbmag_make_inputs(c, seed + (unsigned long long)ci * 7919ULL, re, im);

        if (vec_db_mag(re, im, c->n, c->floor_mag, c->offset, out) != 0) {
            fprintf(stderr, "case %d: vec_db_mag failed\n", ci);
            return 2;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        fwrite("DBMG", 1, 4, f);
        fwrite(&c->n, sizeof(int), 1, f);
        fwrite(&c->floor_mag, sizeof(float), 1, f);
        fwrite(&c->offset, sizeof(float), 1, f);
        fwrite(re, sizeof(float), (size_t)c->n, f);
        fwrite(im, sizeof(float), (size_t)c->n, f);
        fwrite(out, sizeof(float), (size_t)c->n, f);
        fclose(f);

        printf("case %d (n=%d floor=%.0e offset=%g): out[0]=%.6f out[last]=%.6f\n",
               ci, c->n, (double)c->floor_mag, (double)c->offset,
               (double)out[0], (double)out[c->n - 1]);
        free(re); free(im); free(out);
    }
    return 0;
}