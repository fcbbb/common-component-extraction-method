/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 *
 * op = 0: forward DCT-II, op = 1: inverse DCT-III.
 */
#ifndef AUBIO_DCT_CASES_H
#define AUBIO_DCT_CASES_H

#include <stdint.h>

typedef struct {
    int size;
    int op;
} dct_case;

#define DCT_FWD 0
#define DCT_INV 1

static const dct_case dct_cases[] = {
    {  1, DCT_FWD }, {  1, DCT_INV },
    {  2, DCT_FWD }, {  2, DCT_INV },
    {  3, DCT_FWD }, {  3, DCT_INV },
    {  4, DCT_FWD }, {  4, DCT_INV },
    {  5, DCT_FWD }, {  5, DCT_INV },
    {  6, DCT_FWD }, {  6, DCT_INV },
    {  7, DCT_FWD }, {  7, DCT_INV },
    {  8, DCT_FWD }, {  8, DCT_INV },
    {  9, DCT_FWD }, {  9, DCT_INV },
    { 10, DCT_FWD }, { 10, DCT_INV },
    { 11, DCT_FWD }, { 11, DCT_INV },
    { 12, DCT_FWD }, { 12, DCT_INV },
    { 13, DCT_FWD }, { 13, DCT_INV },
    { 14, DCT_FWD }, { 14, DCT_INV },
    { 15, DCT_FWD }, { 15, DCT_INV },
    { 16, DCT_FWD }, { 16, DCT_INV },
    { 17, DCT_FWD }, { 17, DCT_INV },
    { 32, DCT_FWD }, { 32, DCT_INV },
    { 64, DCT_FWD }, { 64, DCT_INV },
    { 100, DCT_FWD }, { 100, DCT_INV },   /* not a power of two */
    { 257, DCT_FWD }, { 257, DCT_INV },   /* odd and prime      */
    { 1024, DCT_FWD }, { 1024, DCT_INV }
};

#define DCT_NCASES ((int)(sizeof(dct_cases) / sizeof(dct_cases[0])))

static uint64_t dct_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static void dct_make_input(const dct_case *c, float *in, uint64_t seed)
{
    uint64_t st = seed;
    int i;

    for (i = 0; i < c->size; ++i) {
        double u = ((double)(dct_splitmix64(&st) >> 11) + 1.0) / 9007199254740992.0;
        in[i] = (float)(2.0 * u - 1.0);
    }
}

#endif /* AUBIO_DCT_CASES_H */