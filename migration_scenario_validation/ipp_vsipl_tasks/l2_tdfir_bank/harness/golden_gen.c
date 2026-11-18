/* Golden generator: builds hidden inputs and the expected output with the
 * IPP baseline. Must be compiled against the IPP build of the library.
 *
 * Usage: golden_gen <output-dir>
 */
#include "tdfir.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void put_i32(FILE *f, int v) { fwrite(&v, sizeof(v), 1, f); }
static void put_f32(FILE *f, const float *p, int n) { fwrite(p, sizeof(float), (size_t)n, f); }

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci;

    for (ci = 0; ci < TDFIR_NUM_CASES; ++ci) {
        const tdfir_case *c = &tdfir_cases[ci];
        unsigned long long seed = c->seed;
        int total = tdfir_total(c);
        float *taps = (float *)malloc(sizeof(float) * c->ntaps * c->nfilters);
        float *in = (float *)malloc(sizeof(float) * total);
        float *out = (float *)malloc(sizeof(float) * total * c->nfilters);
        tdfir_bank *b;
        int i, blk;

        if (!taps || !in || !out) return 1;
        for (i = 0; i < c->ntaps * c->nfilters; ++i) taps[i] = tdfir_next_f32(&seed);
        for (i = 0; i < total; ++i) in[i] = tdfir_next_f32(&seed);

        b = tdfir_create(taps, c->ntaps, c->nfilters, c->block);
        if (!b) { fprintf(stderr, "case %d: create failed\n", ci); return 1; }
        for (blk = 0; blk < c->nblocks; ++blk) {
            if (tdfir_process(b, in + (size_t)blk * c->block,
                              out + (size_t)blk * c->block * c->nfilters,
                              c->block) != 0) {
                fprintf(stderr, "case %d: process failed\n", ci);
                return 1;
            }
        }
        tdfir_destroy(b);

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        {
            FILE *f = fopen(path, "wb");
            if (!f) { perror(path); return 1; }
            fwrite("TDF1", 1, 4, f);
            put_i32(f, c->ntaps);
            put_i32(f, c->nfilters);
            put_i32(f, total);
            put_i32(f, c->block);
            put_f32(f, taps, c->ntaps * c->nfilters);
            put_f32(f, in, total);
            put_f32(f, out, total * c->nfilters);
            fclose(f);
        }
        printf("wrote %s\n", path);
        free(taps); free(in); free(out);
    }
    return 0;
}