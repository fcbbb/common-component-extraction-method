/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "AUBD"
 *   int32   size, op        (op 0 = forward DCT-II, 1 = inverse DCT-III)
 *   float32 in[size]
 *   float32 expected[size]
 *
 * Usage: golden_gen <out-dir>
 */
#include "aubio_dct.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0xA0B10D7CULL;
    int ci;

    for (ci = 0; ci < DCT_NCASES; ++ci) {
        const dct_case *c = &dct_cases[ci];
        int hdr[2];
        float *in = (float *)malloc(sizeof(float) * (size_t)c->size);
        float *out = (float *)malloc(sizeof(float) * (size_t)c->size);
        fvec_t fi, fo;
        aubio_dct_t *s;
        FILE *f;

        if (!in || !out) return 2;
        dct_make_input(c, in, seed + (unsigned long long)ci * 7919ULL);

        s = new_aubio_dct((unsigned int)c->size);
        if (!s) { fprintf(stderr, "case %d: new_aubio_dct failed\n", ci); return 2; }

        fi.length = (unsigned int)c->size; fi.data = in;
        fo.length = (unsigned int)c->size; fo.data = out;
        if (c->op == DCT_FWD) aubio_dct_do(s, &fi, &fo);
        else                  aubio_dct_rdo(s, &fi, &fo);
        del_aubio_dct(s);

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        hdr[0] = c->size; hdr[1] = c->op;
        fwrite("AUBD", 1, 4, f);
        fwrite(hdr, sizeof(int), 2, f);
        fwrite(in, sizeof(float), (size_t)c->size, f);
        fwrite(out, sizeof(float), (size_t)c->size, f);
        fclose(f);

        printf("case %2d (%s n=%3d): out[0]=%.6f out[mid]=%.6f out[last]=%.6f\n",
               ci, c->op == DCT_FWD ? "fwd" : "inv", c->size,
               (double)out[0], (double)out[c->size / 2], (double)out[c->size - 1]);
        free(in); free(out);
    }
    return 0;
}