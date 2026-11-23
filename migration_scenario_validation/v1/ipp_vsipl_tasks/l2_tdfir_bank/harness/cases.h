/* Shared hidden-test case table.  Golden and evaluation use the same table.
 *
 * The bank processes fixed-size blocks: total samples = block * nblocks, and
 * every tdfir_process() call consumes exactly `block` samples.
 */
#ifndef TDFIR_CASES_H
#define TDFIR_CASES_H

typedef struct {
    int ntaps;
    int nfilters;
    int block;
    int nblocks;
    unsigned long long seed;
} tdfir_case;

static const tdfir_case tdfir_cases[] = {
    /* ntaps nfilters block nblocks seed */
    {  10,  4,  1024,  1, 0x9e3779b97f4a7c15ULL },
    { 101,  2,  1024,  4, 0xbf58476d1ce4e5b9ULL },
    {   1,  1,     7,  1, 0x94d049bb133111ebULL },
    {  64,  8,     1,  5, 0x2545f4914f6cdd1dULL },
    {  33,  3,   200,  5, 0x9e3779b97f4a7c15ULL ^ 0x5555ULL },
};

#define TDFIR_NUM_CASES ((int)(sizeof(tdfir_cases) / sizeof(tdfir_cases[0])))

static int tdfir_total(const tdfir_case *c)
{
    return c->block * c->nblocks;
}

/* Deterministic PRNG (splitmix64) -> uniform float in [-1, 1). */
static unsigned long long tdfir_next_u64(unsigned long long *s)
{
    unsigned long long z = (*s += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

static float tdfir_next_f32(unsigned long long *s)
{
    unsigned int u = (unsigned int)(tdfir_next_u64(s) >> 40); /* 24 bits */
    return (float)u * (2.0f / 16777216.0f) - 1.0f;
}

#endif /* TDFIR_CASES_H */