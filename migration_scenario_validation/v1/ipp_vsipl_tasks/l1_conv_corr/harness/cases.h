/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef CC_CASES_H
#define CC_CASES_H

#include "conv_corr.h"

#include <math.h>
#include <stdint.h>

typedef struct {
    int op;       /* 0 = dsp_convolve, 1 = dsp_convolve_strided, 2 = dsp_correlate */
    int region;   /* dsp_region, convolutions only                        */
    int bias;     /* dsp_corr_bias, correlations only                     */
    int nh;
    int nx;
    int xstride;  /* strided convolutions only                            */
    int offset;
} cc_case;

static const cc_case cc_cases[] = {
    /* convolutions */
    { 0, DSP_REGION_FULL, 0,  2,    3, 1, 0 },  /* smallest full result        */
    { 0, DSP_REGION_FULL, 0,  5,   11, 1, 0 },
    { 0, DSP_REGION_FULL, 0, 17,    6, 1, 0 },  /* kernel longer than data     */
    { 0, DSP_REGION_SAME, 0,  4,   20, 1, 0 },  /* even kernel: offset nh/2=2  */
    { 0, DSP_REGION_SAME, 0,  5,   32, 1, 0 },  /* odd kernel: offset 2        */
    { 0, DSP_REGION_FULL, 0,  4, 1000, 1, 0 },  /* long input                  */
    /* strided convolutions */
    { 1, DSP_REGION_FULL, 0,  7,   40, 3, 2 },
    { 1, DSP_REGION_SAME, 0,  6,   64, 2, 1 },
    /* correlations */
    { 2, DSP_REGION_FULL, DSP_CORR_BIASED,    3,   5, 1, 0 },
    { 2, DSP_REGION_FULL, DSP_CORR_BIASED,    7,  40, 1, 0 },
    { 2, DSP_REGION_FULL, DSP_CORR_UNBIASED,  7,  40, 1, 0 },
    { 2, DSP_REGION_FULL, DSP_CORR_UNBIASED,  8,   6, 1, 0 },  /* kernel longer  */
    { 2, DSP_REGION_FULL, DSP_CORR_BIASED,   40,   7, 1, 0 },  /* kernel longer  */
    { 2, DSP_REGION_FULL, DSP_CORR_UNBIASED,  1,   9, 1, 0 },  /* single tap     */
    { 2, DSP_REGION_FULL, DSP_CORR_UNBIASED, 16, 200, 1, 0 }
};

#define CC_NCASES ((int)(sizeof(cc_cases) / sizeof(cc_cases[0])))

static uint64_t cc_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static double cc_unit(uint64_t *state)
{
    return ((double)(cc_splitmix64(state) >> 11) + 1.0) / 9007199254740992.0;
}

/* h is deliberately asymmetric, so a lag that runs the wrong way shows up as
 * an O(1) error instead of hiding behind a symmetric kernel. */
static void cc_make_input(const cc_case *c, float *h, float *x, uint64_t seed)
{
    uint64_t st = seed;
    int i, xlen;

    for (i = 0; i < c->nh; ++i)
        h[i] = (float)((2.0 * cc_unit(&st) - 1.0) * (1.0 + 0.05 * i));

    xlen = (c->op == 1) ? c->offset + (c->nx - 1) * c->xstride + 1 : c->nx;
    for (i = 0; i < xlen; ++i)
        x[i] = (float)(2.0 * cc_unit(&st) - 1.0);
}

static int cc_xlen(const cc_case *c)
{
    return (c->op == 1) ? c->offset + (c->nx - 1) * c->xstride + 1 : c->nx;
}

static int cc_ylen(const cc_case *c)
{
    if (c->op == 2) return c->nh + c->nx - 1;
    return (c->region == DSP_REGION_FULL) ? c->nh + c->nx - 1 : c->nx;
}

#endif /* CC_CASES_H */