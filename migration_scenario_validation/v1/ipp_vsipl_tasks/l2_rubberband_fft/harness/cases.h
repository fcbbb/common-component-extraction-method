/* Hidden case table and deterministic input generator.
 *
 * op:
 *   0 RB_FWD              in: n real             -> re[n/2+1] + im[n/2+1]
 *   1 RB_FWD_INTERLEAVED  in: n real             -> n+2 interleaved floats
 *   2 RB_FWD_POLAR        in: n real             -> mag[n/2+1] + ph[n/2+1]
 *   3 RB_FWD_MAG          in: n real             -> mag[n/2+1]
 *   4 RB_INV              in: re,im half spectra -> n real
 *   5 RB_INV_INTERLEAVED  in: n+2 interleaved    -> n real
 *   6 RB_INV_POLAR        in: mag, ph            -> n real
 *   7 RB_INV_CEPSTRAL     in: mag                -> n real
 *   8 RB_NULL_ARG         no payload; FFT::forward(NULL,...) must throw
 *
 * prec: 0 = float entry points, 1 = double entry points.
 * Phase slots (the second half of an RB_FWD_POLAR expectation) are compared
 * modulo 2*pi.
 */
#ifndef RUBBERBAND_FFT_CASES_H
#define RUBBERBAND_FFT_CASES_H

#include <stdint.h>

#define RB_FWD             0
#define RB_FWD_INTERLEAVED 1
#define RB_FWD_POLAR       2
#define RB_FWD_MAG         3
#define RB_INV             4
#define RB_INV_INTERLEAVED 5
#define RB_INV_POLAR       6
#define RB_INV_CEPSTRAL    7
#define RB_NULL_ARG        8

typedef struct {
    int size;
    int op;
    int prec;
} rb_case;

static const rb_case rb_cases[] = {
    {    2, RB_FWD,             0 }, {    2, RB_FWD,             1 },
    {    2, RB_FWD_INTERLEAVED, 0 }, {    2, RB_FWD_INTERLEAVED, 1 },
    {    2, RB_FWD_POLAR,       0 }, {    2, RB_FWD_POLAR,       1 },
    {    2, RB_FWD_MAG,         0 }, {    2, RB_FWD_MAG,         1 },
    {    2, RB_INV,             0 }, {    2, RB_INV,             1 },
    {    2, RB_INV_INTERLEAVED, 0 }, {    2, RB_INV_INTERLEAVED, 1 },
    {    2, RB_INV_POLAR,       0 }, {    2, RB_INV_POLAR,       1 },
    {    2, RB_INV_CEPSTRAL,    0 }, {    2, RB_INV_CEPSTRAL,    1 },

    {    3, RB_FWD,             0 }, {    3, RB_FWD,             1 },
    {    3, RB_FWD_INTERLEAVED, 0 }, {    3, RB_FWD_INTERLEAVED, 1 },
    {    3, RB_FWD_POLAR,       0 }, {    3, RB_FWD_POLAR,       1 },
    {    3, RB_FWD_MAG,         0 }, {    3, RB_FWD_MAG,         1 },
    {    3, RB_INV,             0 }, {    3, RB_INV,             1 },
    {    3, RB_INV_INTERLEAVED, 0 }, {    3, RB_INV_INTERLEAVED, 1 },
    {    3, RB_INV_POLAR,       0 }, {    3, RB_INV_POLAR,       1 },
    {    3, RB_INV_CEPSTRAL,    0 }, {    3, RB_INV_CEPSTRAL,    1 },

    {    4, RB_FWD,             0 }, {    4, RB_FWD,             1 },
    {    4, RB_FWD_INTERLEAVED, 0 }, {    4, RB_FWD_INTERLEAVED, 1 },
    {    4, RB_FWD_POLAR,       0 }, {    4, RB_FWD_POLAR,       1 },
    {    4, RB_FWD_MAG,         0 }, {    4, RB_FWD_MAG,         1 },
    {    4, RB_INV,             0 }, {    4, RB_INV,             1 },
    {    4, RB_INV_INTERLEAVED, 0 }, {    4, RB_INV_INTERLEAVED, 1 },
    {    4, RB_INV_POLAR,       0 }, {    4, RB_INV_POLAR,       1 },
    {    4, RB_INV_CEPSTRAL,    0 }, {    4, RB_INV_CEPSTRAL,    1 },

    {    5, RB_FWD,             0 }, {    5, RB_FWD,             1 },
    {    5, RB_FWD_INTERLEAVED, 0 }, {    5, RB_FWD_INTERLEAVED, 1 },
    {    5, RB_FWD_POLAR,       0 }, {    5, RB_FWD_POLAR,       1 },
    {    5, RB_FWD_MAG,         0 }, {    5, RB_FWD_MAG,         1 },
    {    5, RB_INV,             0 }, {    5, RB_INV,             1 },
    {    5, RB_INV_INTERLEAVED, 0 }, {    5, RB_INV_INTERLEAVED, 1 },
    {    5, RB_INV_POLAR,       0 }, {    5, RB_INV_POLAR,       1 },
    {    5, RB_INV_CEPSTRAL,    0 }, {    5, RB_INV_CEPSTRAL,    1 },

    {    6, RB_FWD,             0 }, {    6, RB_FWD,             1 },
    {    6, RB_FWD_INTERLEAVED, 0 }, {    6, RB_FWD_INTERLEAVED, 1 },
    {    6, RB_FWD_POLAR,       0 }, {    6, RB_FWD_POLAR,       1 },
    {    6, RB_FWD_MAG,         0 }, {    6, RB_FWD_MAG,         1 },
    {    6, RB_INV,             0 }, {    6, RB_INV,             1 },
    {    6, RB_INV_INTERLEAVED, 0 }, {    6, RB_INV_INTERLEAVED, 1 },
    {    6, RB_INV_POLAR,       0 }, {    6, RB_INV_POLAR,       1 },
    {    6, RB_INV_CEPSTRAL,    0 }, {    6, RB_INV_CEPSTRAL,    1 },

    {    8, RB_FWD,             0 }, {    8, RB_FWD,             1 },
    {    8, RB_FWD_INTERLEAVED, 0 }, {    8, RB_FWD_INTERLEAVED, 1 },
    {    8, RB_FWD_POLAR,       0 }, {    8, RB_FWD_POLAR,       1 },
    {    8, RB_FWD_MAG,         0 }, {    8, RB_FWD_MAG,         1 },
    {    8, RB_INV,             0 }, {    8, RB_INV,             1 },
    {    8, RB_INV_INTERLEAVED, 0 }, {    8, RB_INV_INTERLEAVED, 1 },
    {    8, RB_INV_POLAR,       0 }, {    8, RB_INV_POLAR,       1 },
    {    8, RB_INV_CEPSTRAL,    0 }, {    8, RB_INV_CEPSTRAL,    1 },

    {   16, RB_FWD,             0 }, {   16, RB_FWD,             1 },
    {   16, RB_FWD_INTERLEAVED, 0 }, {   16, RB_FWD_INTERLEAVED, 1 },
    {   16, RB_FWD_POLAR,       0 }, {   16, RB_FWD_POLAR,       1 },
    {   16, RB_FWD_MAG,         0 }, {   16, RB_FWD_MAG,         1 },
    {   16, RB_INV,             0 }, {   16, RB_INV,             1 },
    {   16, RB_INV_INTERLEAVED, 0 }, {   16, RB_INV_INTERLEAVED, 1 },
    {   16, RB_INV_POLAR,       0 }, {   16, RB_INV_POLAR,       1 },
    {   16, RB_INV_CEPSTRAL,    0 }, {   16, RB_INV_CEPSTRAL,    1 },

    {   32, RB_FWD,             0 }, {   32, RB_FWD,             1 },
    {   32, RB_FWD_INTERLEAVED, 0 }, {   32, RB_FWD_INTERLEAVED, 1 },
    {   32, RB_FWD_POLAR,       0 }, {   32, RB_FWD_POLAR,       1 },
    {   32, RB_FWD_MAG,         0 }, {   32, RB_FWD_MAG,         1 },
    {   32, RB_INV,             0 }, {   32, RB_INV,             1 },
    {   32, RB_INV_INTERLEAVED, 0 }, {   32, RB_INV_INTERLEAVED, 1 },
    {   32, RB_INV_POLAR,       0 }, {   32, RB_INV_POLAR,       1 },
    {   32, RB_INV_CEPSTRAL,    0 }, {   32, RB_INV_CEPSTRAL,    1 },

    {  100, RB_FWD,             0 }, {  100, RB_FWD,             1 },
    {  100, RB_FWD_INTERLEAVED, 0 }, {  100, RB_FWD_INTERLEAVED, 1 },
    {  100, RB_FWD_POLAR,       0 }, {  100, RB_FWD_POLAR,       1 },
    {  100, RB_FWD_MAG,         0 }, {  100, RB_FWD_MAG,         1 },
    {  100, RB_INV,             0 }, {  100, RB_INV,             1 },
    {  100, RB_INV_INTERLEAVED, 0 }, {  100, RB_INV_INTERLEAVED, 1 },
    {  100, RB_INV_POLAR,       0 }, {  100, RB_INV_POLAR,       1 },
    {  100, RB_INV_CEPSTRAL,    0 }, {  100, RB_INV_CEPSTRAL,    1 },

    { 1024, RB_FWD,             0 }, { 1024, RB_FWD,             1 },
    { 1024, RB_FWD_INTERLEAVED, 0 }, { 1024, RB_FWD_INTERLEAVED, 1 },
    { 1024, RB_FWD_POLAR,       0 }, { 1024, RB_FWD_POLAR,       1 },
    { 1024, RB_FWD_MAG,         0 }, { 1024, RB_FWD_MAG,         1 },
    { 1024, RB_INV,             0 }, { 1024, RB_INV,             1 },
    { 1024, RB_INV_INTERLEAVED, 0 }, { 1024, RB_INV_INTERLEAVED, 1 },
    { 1024, RB_INV_POLAR,       0 }, { 1024, RB_INV_POLAR,       1 },
    { 1024, RB_INV_CEPSTRAL,    0 }, { 1024, RB_INV_CEPSTRAL,    1 },

    {    8, RB_NULL_ARG,        0 },
    {    8, RB_NULL_ARG,        1 }
};

#define RB_NCASES ((int)(sizeof(rb_cases) / sizeof(rb_cases[0])))

static inline int rb_bins(int size) { return size / 2 + 1; }

static inline int rb_payload_len(int op, int size)
{
    const int hs1 = rb_bins(size);
    switch (op) {
        case RB_FWD: case RB_FWD_INTERLEAVED:
        case RB_FWD_POLAR: case RB_FWD_MAG:     return size;
        case RB_INV: case RB_INV_INTERLEAVED:
        case RB_INV_POLAR:                      return 2 * hs1;
        case RB_INV_CEPSTRAL:                   return hs1;
        default:                                return 0;
    }
}

static inline int rb_ncompare(int op, int size)
{
    const int hs1 = rb_bins(size);
    switch (op) {
        case RB_FWD: case RB_FWD_POLAR:         return 2 * hs1;
        case RB_FWD_INTERLEAVED:                return size + 2;
        case RB_FWD_MAG:                        return hs1;
        case RB_INV: case RB_INV_INTERLEAVED:
        case RB_INV_POLAR: case RB_INV_CEPSTRAL: return size;
        default:                                return 0;
    }
}

static inline int rb_is_phase_slot(int op, int size, int idx)
{
    return op == RB_FWD_POLAR && idx >= rb_bins(size);
}

static inline uint64_t rb_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static inline double rb_rand(uint64_t *state)
{
    const uint64_t v = rb_splitmix64(state);
    return 2.0 * ((double)(v >> 11) / 9007199254740992.0) - 1.0;
}

#endif /* RUBBERBAND_FFT_CASES_H */