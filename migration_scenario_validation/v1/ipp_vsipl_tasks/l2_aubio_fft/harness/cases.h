/* Hidden case table and deterministic input generator (included by
 * golden_gen.c only).
 *
 * op:
 *   0 FFT_DO_COMPLEX         in: nframes real frames -> out: nframes compspec
 *   1 FFT_GET_SPECTRUM       in: nframes real frames -> out: nframes norm+phas
 *   2 FFT_ROUNDTRIP_NORMPHAS in: nframes real frames -> out: nframes real
 *   3 FFT_ROUNDTRIP_COMPLEX  in: nframes real frames -> out: nframes real
 *   4 FFT_GET_REALIMAG       in: norm[m] + phas[m]   -> out: compspec
 *   5 FFT_INVALID            new_aubio_fft(winsize) must return NULL
 *
 * Phase outputs are compared modulo 2*pi (circ = 1).
 */
#ifndef AUBIO_FFT_CASES_H
#define AUBIO_FFT_CASES_H

#include <stdint.h>

#define FFT_DO_COMPLEX         0
#define FFT_GET_SPECTRUM       1
#define FFT_ROUNDTRIP_NORMPHAS 2
#define FFT_ROUNDTRIP_COMPLEX  3
#define FFT_GET_REALIMAG       4
#define FFT_INVALID            5

typedef struct {
    int winsize;
    int op;
    int nframes;
} aubio_fft_case;

static const aubio_fft_case aubio_fft_cases[] = {
    {    8, FFT_DO_COMPLEX,         1 },
    {    8, FFT_GET_SPECTRUM,       1 },
    {    8, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {    8, FFT_ROUNDTRIP_COMPLEX,  1 },
    {    8, FFT_GET_REALIMAG,       1 },

    {   16, FFT_DO_COMPLEX,         1 },
    {   16, FFT_GET_SPECTRUM,       1 },
    {   16, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {   16, FFT_ROUNDTRIP_COMPLEX,  1 },
    {   16, FFT_GET_REALIMAG,       1 },

    {   32, FFT_DO_COMPLEX,         1 },
    {   32, FFT_GET_SPECTRUM,       1 },
    {   32, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {   32, FFT_ROUNDTRIP_COMPLEX,  1 },
    {   32, FFT_GET_REALIMAG,       1 },

    {   64, FFT_DO_COMPLEX,         3 },   /* same object, three frames */
    {   64, FFT_GET_SPECTRUM,       3 },
    {   64, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {   64, FFT_ROUNDTRIP_COMPLEX,  1 },
    {   64, FFT_GET_REALIMAG,       1 },

    {  128, FFT_DO_COMPLEX,         1 },
    {  128, FFT_GET_SPECTRUM,       1 },
    {  128, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {  128, FFT_ROUNDTRIP_COMPLEX,  1 },
    {  128, FFT_GET_REALIMAG,       1 },

    {  256, FFT_DO_COMPLEX,         1 },
    {  256, FFT_GET_SPECTRUM,       1 },
    {  256, FFT_ROUNDTRIP_NORMPHAS, 1 },
    {  256, FFT_ROUNDTRIP_COMPLEX,  1 },
    {  256, FFT_GET_REALIMAG,       1 },

    { 1024, FFT_DO_COMPLEX,         1 },
    { 1024, FFT_GET_SPECTRUM,       1 },
    { 1024, FFT_ROUNDTRIP_NORMPHAS, 1 },
    { 1024, FFT_ROUNDTRIP_COMPLEX,  1 },
    { 1024, FFT_GET_REALIMAG,       1 },

    {    2, FFT_INVALID,            0 },
    {    4, FFT_INVALID,            0 },
    {    5, FFT_INVALID,            0 },
    {    6, FFT_INVALID,            0 },
    {   12, FFT_INVALID,            0 },
    { 1000, FFT_INVALID,            0 }
};

#define AUBIO_FFT_NCASES ((int)(sizeof(aubio_fft_cases) / sizeof(aubio_fft_cases[0])))

static uint64_t aubio_fft_splitmix64(uint64_t *state)
{
    uint64_t z = (*state += UINT64_C(0x9E3779B97F4A7C15));
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}

static float aubio_fft_rand(uint64_t *state)
{
    const uint64_t v = aubio_fft_splitmix64(state);
    return (float)(2.0 * ((double)(v >> 11) / 9007199254740992.0) - 1.0);
}

static int aubio_fft_ncompare(int op, int winsize, int nframes)
{
    switch (op) {
        case FFT_GET_SPECTRUM:       return nframes * 2 * (winsize / 2 + 1);
        case FFT_INVALID:            return 0;
        default:                     return nframes * winsize;
    }
}

static int aubio_fft_circular(int op)
{
    return op == FFT_GET_SPECTRUM;
}

#endif /* AUBIO_FFT_CASES_H */