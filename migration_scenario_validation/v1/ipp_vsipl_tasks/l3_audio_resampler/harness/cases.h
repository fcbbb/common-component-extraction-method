/* Case table and shared arithmetic for the resampler package.
 *
 * A case is one conversion session: the ratio, the filter size, the analysis
 * frame length, the capture and the block size the driver feeds it in.  The
 * data are deterministic tones below the passband plus a little noise, so the
 * output is a clean resampled waveform and the periodogram has an
 * unambiguous peak.
 */
#ifndef RES_CASES_H
#define RES_CASES_H

#include <math.h>
#include <stdint.h>

#define RES_CASE_PI 3.14159265358979324

typedef struct {
    int up;
    int down;
    int ntaps;
    double cutoff;
    int fft_len;
    int nin;
    int block;
} res_case;

static const res_case res_cases[] = {
    /* up  down  taps  cutoff  fft    nin  block */
    {  2,    1,    8,   0.45,  256,   600,  600 },
    {  1,    2,    8,   0.45,  256,   600,   37 },
    {160,  147,   12,   0.45,  512,  1470,  147 },
    {  3,    2,    6,   0.40,  128,   300,    1 },
    {  5,    4,   16,   0.35,  256,   400,   64 },
    {  1,    1,    4,   0.49,   64,   500,   13 },
    {  7,    3,   10,   0.30,  128,   700,  700 },
    {  2,    3,    9,   0.42,   64,   333,   50 }
};

static const int RES_NCASES = (int)(sizeof(res_cases) / sizeof(res_cases[0]));

/* Largest output index that exists for `nin` input samples: the last m with
 * (m*down)/up <= nin-1, i.e. m*down < nin*up.  -1 when there is none. */
static inline long res_last_out(int up, int down, int nin)
{
    if (nin <= 0) return -1;
    return ((long)nin * up - 1) / down;
}

/* First output index whose window is complete: the smallest m with
 * (m*down)/up >= ntaps-1. */
static inline long res_first_out(int up, int down, int ntaps)
{
    return ((long)(ntaps - 1) * up + down - 1) / down;
}

static inline long res_nout(int up, int down, int ntaps, int nin)
{
    const long m0 = res_first_out(up, down, ntaps);
    const long m1 = res_last_out(up, down, nin);

    return (m1 >= m0) ? m1 - m0 + 1 : 0;
}

static inline uint64_t res_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline double res_rand(uint64_t *s)
{
    return ((double)(res_next(s) >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* Three tones inside the passband over a little broadband noise, scaled so the
 * peak sample is just below 1.  Each case gets its own seed and phase set. */
static inline void res_make_signal(const res_case *c, double *x)
{
    uint64_t s = 0x51DE0000ULL + (uint64_t)c->up * 131ULL +
                 (uint64_t)c->down * 17ULL + (uint64_t)c->ntaps;
    const double f[3] = { 0.055, 0.113, 0.201 };
    const double amp[3] = { 0.60, 0.33, 0.21 };
    const double ph[3] = { 0.7, 2.1, 4.4 };
    double peak = 0.0;
    int n, t;

    for (n = 0; n < c->nin; ++n) x[n] = 0.05 * res_rand(&s);

    for (t = 0; t < 3; ++t) {
        for (n = 0; n < c->nin; ++n) {
            x[n] += amp[t] * sin(2.0 * RES_CASE_PI * f[t] * (double)n + ph[t]);
        }
    }

    for (n = 0; n < c->nin; ++n) {
        if (fabs(x[n]) > peak) peak = fabs(x[n]);
    }
    if (peak > 0.0) {
        for (n = 0; n < c->nin; ++n) x[n] *= 0.9 / peak;
    }
}

#endif /* RES_CASES_H */