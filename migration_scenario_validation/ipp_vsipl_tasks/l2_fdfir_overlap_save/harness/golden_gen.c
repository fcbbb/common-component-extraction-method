/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "FDFI"
 *   int32   ntaps, nfft, nx
 *   float32 taps[ntaps]
 *   float32 x[nx]
 *   float32 expected[nx]
 *
 * Usage: golden_gen <out-dir>
 */
#include "fdfir.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0x0FDF1A55ULL;
    int ci;

    for (ci = 0; ci < FDFIR_NCASES; ++ci) {
        const fdfir_case *c = &fdfir_cases[ci];
        int hdr[3];
        float *taps = (float *)malloc(sizeof(float) * (size_t)c->ntaps);
        float *x = (float *)malloc(sizeof(float) * (size_t)c->nx);
        float *y = (float *)malloc(sizeof(float) * (size_t)c->nx);
        fdfir *f;
        FILE *fp;

        if (!taps || !x || !y) return 2;
        fdfir_make_input(c, taps, x, seed + (unsigned long long)ci * 7919ULL);

        f = fdfir_create(taps, c->ntaps, c->nfft);
        if (!f) {
            fprintf(stderr, "case %d: fdfir_create failed\n", ci);
            return 2;
        }
        if (fdfir_apply(f, x, c->nx, y) != 0) {
            fprintf(stderr, "case %d: fdfir_apply failed\n", ci);
            return 2;
        }
        fdfir_destroy(f);

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "wb");
        if (!fp) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        hdr[0] = c->ntaps; hdr[1] = c->nfft; hdr[2] = c->nx;
        fwrite("FDFI", 1, 4, fp);
        fwrite(hdr, sizeof(int), 3, fp);
        fwrite(taps, sizeof(float), (size_t)c->ntaps, fp);
        fwrite(x, sizeof(float), (size_t)c->nx, fp);
        fwrite(y, sizeof(float), (size_t)c->nx, fp);
        fclose(fp);

        printf("case %2d (ntaps=%d nfft=%d nx=%d block=%d): "
               "y[0]=%.6f y[mid]=%.6f y[last]=%.6f\n",
               ci, c->ntaps, c->nfft, c->nx, c->nfft - c->ntaps + 1,
               (double)y[0], (double)y[c->nx / 2], (double)y[c->nx - 1]);
        free(taps); free(x); free(y);
    }
    return 0;
}