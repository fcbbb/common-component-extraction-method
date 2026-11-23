/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef FDFIR_CASES_H
#define FDFIR_CASES_H

#include "fdfir.h"

#include <stdint.h>

typedef struct {
    int ntaps;
    int nfft;
    int nx;
} fdfir_case;

static const fdfir_case fdfir_cases[] = {
    {  4,   8,    5 },   /* one full block              */
    {  4,   8,    3 },   /* shorter than one block      */
    {  4,   8,   17 },   /* block + partial tail        */
    {  4,   8,   40 },   /* exact multiple of the block */
    { 16,  32,  100 },
    {  1,   8,   32 },   /* single tap: pure gain       */
    { 32,  32,   20 },   /* block == 1                  */
    {  7, 256, 1000 },
    { 63,  64,   64 },   /* block == 2                  */
    {  5,  16,    1 },   /* single sample               */
    {  2,   4,   50 }
};

#define FDFIR_NCASES ((int)(sizeof(fdfir_cases) / sizeof(fdfir_cases[0])))

static uint64_t fdfir_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static void fdfir_make_input(const fdfir_case *c, float *taps, float *x, uint64_t seed)
{
    uint64_t st = seed;
    int i;

    for (i = 0; i < c->ntaps; ++i) {
        double u = ((double)(fdfir_splitmix64(&st) >> 11) + 1.0) / 9007199254740992.0;
        /* asymmetric kernel, decaying so a misaligned block stands out */
        taps[i] = (float)((2.0 * u - 1.0) / (1.0 + 0.1 * i));
    }
    for (i = 0; i < c->nx; ++i) {
        double u = ((double)(fdfir_splitmix64(&st) >> 11) + 1.0) / 9007199254740992.0;
        x[i] = (float)(2.0 * u - 1.0);
    }
}

#endif /* FDFIR_CASES_H */