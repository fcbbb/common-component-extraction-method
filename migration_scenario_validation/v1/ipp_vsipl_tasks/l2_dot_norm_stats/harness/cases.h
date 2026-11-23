/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef STATS_CASES_H
#define STATS_CASES_H

#include <math.h>
#include <stdint.h>

typedef struct {
    int n;          /* number of samples in the window          */
    int astride;    /* element stride of a                      */
    int bstride;    /* element stride of b                      */
    int offset;     /* first window index in both base arrays   */
    int nan_index;  /* sample index to poison with NaN, -1 none */
} stats_case;

static const stats_case stats_cases[] = {
    { 512, 1, 1, 0, -1 },   /* contiguous                          */
    { 513, 3, 1, 2, -1 },   /* decimated a, odd length             */
    {   1, 1, 1, 5, -1 },   /* single sample: stddev is 0          */
    { 257, 2, 4, 1, -1 },   /* both vectors decimated              */
    { 300, 1, 1, 0, 100 },  /* NaN sample in the middle (not first)*/
    {  64, 4, 2, 3, -1 }    /* short fully decimated window        */
};

#define STATS_NCASES ((int)(sizeof(stats_cases) / sizeof(stats_cases[0])))

#define STATS_NFIELDS 6  /* dot, norm, mean, stddev, vmax, vmin */

static uint64_t stats_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static double stats_uniform(uint64_t *st)
{
    return ((double)(stats_splitmix64(st) >> 11) + 1.0) / 9007199254740992.0;
}

static int stats_base_len(int n, int stride, int offset)
{
    return offset + (n - 1) * stride + 1;
}

/* Fill both base arrays (unknown elements included, so the window selection is
 * exercised), correlate b with a inside the window so `dot` is well scaled,
 * add a few spikes, and optionally poison one sample with NaN. */
static void stats_make_inputs(const stats_case *c, uint64_t seed,
                              float *a, int alen, float *b, int blen)
{
    uint64_t st = seed;
    int i;

    for (i = 0; i < alen; ++i)
        a[i] = (float)(2.0 * stats_uniform(&st) - 1.0);
    for (i = 0; i < blen; ++i)
        b[i] = (float)(2.0 * stats_uniform(&st) - 1.0);

    for (i = 0; i < c->n; ++i) {
        int ai = c->offset + i * c->astride;
        int bi = c->offset + i * c->bstride;
        b[bi] = 0.5f * a[ai] + 0.5f * b[bi];
    }
    for (i = 0; i < c->n; i += 37) {
        int ai = c->offset + i * c->astride;
        a[ai] += 3.0f;
    }
    if (c->nan_index >= 0 && c->nan_index < c->n)
        a[c->offset + c->nan_index * c->astride] = (float)NAN;
}

#endif /* STATS_CASES_H */