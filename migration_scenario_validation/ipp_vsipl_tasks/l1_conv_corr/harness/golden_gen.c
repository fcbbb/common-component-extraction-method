/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "CCOR"
 *   int32   op, region, bias, nh, nx, xstride, offset, ny, xlen
 *   float32 h[nh]
 *   float32 x[xlen]
 *   float32 expected[ny]
 *
 * Usage: golden_gen <out-dir>
 */
#include "conv_corr.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int run_case(const cc_case *c, const float *h, const float *x, float *y)
{
    switch (c->op) {
    case 0:
        return dsp_convolve(h, c->nh, x, c->nx, (dsp_region)c->region, y);
    case 1:
        return dsp_convolve_strided(h, c->nh, x, c->xstride, c->offset, c->nx,
                                    (dsp_region)c->region, y);
    default:
        return dsp_correlate(h, c->nh, x, c->nx, (dsp_corr_bias)c->bias, y);
    }
}

static const char *op_name(int op)
{
    switch (op) {
    case 0: return "conv";
    case 1: return "conv_strided";
    default: return "corr";
    }
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0xC0FFEE1234ULL;
    int ci;

    for (ci = 0; ci < CC_NCASES; ++ci) {
        const cc_case *c = &cc_cases[ci];
        int ny = cc_ylen(c), xlen = cc_xlen(c);
        int hdr[9];
        float *h = (float *)malloc(sizeof(float) * (size_t)c->nh);
        float *x = (float *)malloc(sizeof(float) * (size_t)xlen);
        float *y = (float *)malloc(sizeof(float) * (size_t)ny);
        FILE *f;

        if (!h || !x || !y) return 2;
        cc_make_input(c, h, x, seed + (unsigned long long)ci * 7919ULL);

        if (run_case(c, h, x, y) != 0) {
            fprintf(stderr, "case %d: call failed\n", ci);
            return 2;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        hdr[0] = c->op;     hdr[1] = c->region; hdr[2] = c->bias;
        hdr[3] = c->nh;     hdr[4] = c->nx;     hdr[5] = c->xstride;
        hdr[6] = c->offset; hdr[7] = ny;        hdr[8] = xlen;
        fwrite("CCOR", 1, 4, f);
        fwrite(hdr, sizeof(int), 9, f);
        fwrite(h, sizeof(float), (size_t)c->nh, f);
        fwrite(x, sizeof(float), (size_t)xlen, f);
        fwrite(y, sizeof(float), (size_t)ny, f);
        fclose(f);

        printf("case %2d (%s nh=%d nx=%d region=%d bias=%d stride=%d): "
               "y[0]=%.6f y[mid]=%.6f y[last]=%.6f\n",
               ci, op_name(c->op), c->nh, c->nx, c->region, c->bias, c->xstride,
               (double)y[0], (double)y[ny / 2], (double)y[ny - 1]);
        free(h); free(x); free(y);
    }
    return 0;
}