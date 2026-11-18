/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef CFAR_CASES_H
#define CFAR_CASES_H

#include <math.h>
#include <stdint.h>

typedef struct {
    int nguard;
    int ntrain;
    int n;
    float pfa;
} cfar_case;

static const cfar_case cfar_cases[] = {
    { 2,  8,  512, 1.0e-3f },   /* typical window */
    { 0,  4,  257, 1.0e-2f },   /* no guard cells, odd length */
    { 1,  1,   64, 5.0e-1f },   /* minimal training set, very high pfa */
    { 4, 16,   33, 1.0e-4f },   /* window wider than the line */
    { 0, 64, 1024, 1.0e-6f }    /* long training set, edges mostly empty */
};

#define CFAR_NCASES ((int)(sizeof(cfar_cases) / sizeof(cfar_cases[0])))

static uint64_t cfar_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

/* Exponential (mean 1) clutter plus a few strong targets. */
static void cfar_make_input(const cfar_case *c, float *mag2, uint64_t seed)
{
    uint64_t st = seed;
    int i, nt = 3;

    for (i = 0; i < c->n; ++i) {
        double u = ((double)(cfar_splitmix64(&st) >> 11) + 1.0) / 9007199254740992.0;
        mag2[i] = (float)(-log(u));
    }
    for (i = 0; i < nt; ++i) {
        int idx = (int)((double)c->n * (0.2 + 0.3 * i));
        if (idx < c->n) mag2[idx] += 20.0f + 5.0f * (float)i;
    }
}

#endif /* CFAR_CASES_H */