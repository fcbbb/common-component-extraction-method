/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef DBMAG_CASES_H
#define DBMAG_CASES_H

#include <math.h>
#include <stdint.h>

typedef struct {
    int n;
    float floor_mag;
    float offset;
} dbmag_case;

static const dbmag_case dbmag_cases[] = {
    {   64, 1.0e-9f,   0.0f },   /* ordinary, floor far below the data   */
    {    1, 1.0e-9f, -10.0f },   /* single element, 3+4i -> 13.979 dB    */
    { 1024, 1.0e-6f,   0.0f },   /* long, zeros every 40 samples         */
    {  257, 1.0e-3f, 100.0f },   /* high floor, large offset             */
    {   33, 1.0e-12f,  -3.5f }   /* near-zero values, fractional offset  */
};

#define DBMAG_NCASES ((int)(sizeof(dbmag_cases) / sizeof(dbmag_cases[0])))

static uint64_t dbmag_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static double dbmag_uniform(uint64_t *st)
{
    return ((double)(dbmag_splitmix64(st) >> 11) + 1.0) / 9007199254740992.0;
}

/* Broadband complex data with exact zeros and near-zeros sprinkled in. */
static void dbmag_make_inputs(const dbmag_case *c, uint64_t seed, float *re, float *im)
{
    uint64_t st = seed;
    int i;

    for (i = 0; i < c->n; ++i) {
        re[i] = (float)(4.0 * dbmag_uniform(&st) - 2.0);
        im[i] = (float)(4.0 * dbmag_uniform(&st) - 2.0);
    }
    for (i = 0; i < c->n; i += 40) { re[i] = 0.0f; im[i] = 0.0f; }
    for (i = 0; i < c->n; i += 97) { re[i] = 1.0e-12f; im[i] = 0.0f; }

    /* exact 3+4i: the dB value is known analytically (13.979400...) */
    if (c->n > 0) { re[0] = 3.0f; im[0] = 4.0f; }
}

#endif /* DBMAG_CASES_H */