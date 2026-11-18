/* Hidden case table, section coefficients and deterministic input generator.
 * Included by golden_gen.c only.
 */
#ifndef IIR_CASES_H
#define IIR_CASES_H

#include <stdint.h>

typedef struct {
    const float *sos;   /* nsections * 5 */
    int nsections;
    int block;
    int nblocks;
    uint64_t seed;
} iir_case;

/* Stable biquads: |a1| < 1 + a2 and |a2| < 1 for every section. */
static const float iir_lp[5] = { 0.0201f,  0.0402f,  0.0201f, -1.5610f, 0.6414f };
static const float iir_hp[5] = { 0.9500f, -1.9000f,  0.9500f, -1.8000f, 0.9000f };
static const float iir_peq[5] = { 1.0000f, -0.4000f,  0.2500f, -0.9000f, 0.5000f };
static const float iir_shelf[5] = { 0.8000f,  0.3000f, -0.1000f, -0.6000f, 0.4000f };
static const float iir_notch[5] = { 0.9000f, -0.6000f,  0.9000f, -1.2000f, 0.8100f };

/* Cascade used by the multi-section cases: peq -> shelf -> notch. */
static const float iir_cascade3[15] = {
     1.0000f, -0.4000f,  0.2500f, -0.9000f, 0.5000f,
     0.8000f,  0.3000f, -0.1000f, -0.6000f, 0.4000f,
     0.9000f, -0.6000f,  0.9000f, -1.2000f, 0.8100f
};

static const float iir_pair2[10] = {
     0.0201f,  0.0402f,  0.0201f, -1.5610f, 0.6414f,
     0.9500f, -1.9000f,  0.9500f, -1.8000f, 0.9000f
};

static const iir_case iir_cases[] = {
    { iir_lp,      1, 256, 4, 0x1111ULL },
    { iir_hp,      1,   1, 8, 0x2222ULL },   /* block of one sample */
    { iir_cascade3, 3, 128, 3, 0x3333ULL },
    { iir_pair2,   2,  64, 5, 0x4444ULL },
    { iir_notch,   1, 512, 2, 0x5555ULL }
};

#define IIR_NCASES ((int)(sizeof(iir_cases) / sizeof(iir_cases[0])))

static uint64_t iir_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

/* Uniform noise in [-1, 1) plus a slow ramp, so the filters see both
 * broadband and low-frequency content. */
static void iir_make_input(const iir_case *c, float *in, uint64_t seed)
{
    uint64_t st = seed;
    int i, total = c->block * c->nblocks;
    for (i = 0; i < total; ++i) {
        double u = (double)(iir_splitmix64(&st) >> 11) / 9007199254740992.0;
        double ramp = 2.0 * (double)i / (double)total - 1.0;
        in[i] = (float)(0.6 * (2.0 * u - 1.0) + 0.3 * ramp);
    }
}

#endif /* IIR_CASES_H */