/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "WIND"
 *   int32   type
 *   float32 param
 *   int32   n
 *   float32 in[n]
 *   float32 expected[n]
 *
 * Usage: golden_gen <out-dir>
 */
#include "win_gen.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *type_name(int t)
{
    switch (t) {
    case WIN_HANN: return "hann";
    case WIN_HAMMING: return "hamming";
    case WIN_BLACKMAN: return "blackman";
    default: return "kaiser";
    }
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0x5EA50A11ULL;
    int ci;

    for (ci = 0; ci < WIN_NCASES; ++ci) {
        const win_case *c = &win_cases[ci];
        float *in = (float *)malloc(sizeof(float) * (size_t)c->n);
        float *out = (float *)malloc(sizeof(float) * (size_t)c->n);
        FILE *f;

        if (!in || !out) return 2;
        win_make_input(c, in, seed + (unsigned long long)ci * 7919ULL);

        if (win_apply((win_type)c->type, c->param, in, out, c->n) != 0) {
            fprintf(stderr, "case %d: win_apply failed\n", ci);
            return 2;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        fwrite("WIND", 1, 4, f);
        fwrite(&c->type, sizeof(int), 1, f);
        fwrite(&c->param, sizeof(float), 1, f);
        fwrite(&c->n, sizeof(int), 1, f);
        fwrite(in, sizeof(float), (size_t)c->n, f);
        fwrite(out, sizeof(float), (size_t)c->n, f);
        fclose(f);

        printf("case %d (%s param=%g n=%d): out[0]=%.6f out[mid]=%.6f out[last]=%.6f\n",
               ci, type_name(c->type), (double)c->param, c->n,
               (double)out[0], (double)out[c->n / 2], (double)out[c->n - 1]);
        free(in); free(out);
    }
    return 0;
}