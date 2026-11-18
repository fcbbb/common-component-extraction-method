/* Hidden case table and deterministic input generator.
 * Included by golden_gen.c only; hidden_test.c reads everything it needs from
 * the case containers.
 */
#ifndef WIN_CASES_H
#define WIN_CASES_H

#include "win_gen.h"

#include <math.h>
#include <stdint.h>

typedef struct {
    int type;
    float param;
    int n;
} win_case;

static const win_case win_cases[] = {
    { WIN_HANN,     0.00f, 1024 },
    { WIN_HAMMING,  0.00f,   64 },
    { WIN_BLACKMAN, 0.16f,  257 },
    { WIN_BLACKMAN, 0.30f,    8 },   /* alpha > 0.16 pushes the peak over 1 */
    { WIN_KAISER,   5.00f,   16 },   /* beta = 37.5, just inside the limit  */
    { WIN_KAISER,   0.50f,   16 },
    { WIN_HANN,     0.00f,    3 },   /* smallest length IPP accepts        */
    { WIN_KAISER,   1.00f,   77 },   /* beta = 38.0 exactly (largest ok)   */
    { WIN_KAISER,   7.00f,    1 }    /* single sample                      */
};

#define WIN_NCASES ((int)(sizeof(win_cases) / sizeof(win_cases[0])))

static uint64_t win_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static void win_make_input(const win_case *c, float *in, uint64_t seed)
{
    uint64_t st = seed;
    int i;

    for (i = 0; i < c->n; ++i) {
        double u = ((double)(win_splitmix64(&st) >> 11) + 1.0) / 9007199254740992.0;
        in[i] = (float)(2.0 * u - 1.0);
    }
}

#endif /* WIN_CASES_H */