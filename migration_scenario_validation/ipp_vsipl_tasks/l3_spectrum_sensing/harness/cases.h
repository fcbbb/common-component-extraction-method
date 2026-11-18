/* Case table and shared arithmetic for the spectrum-sensing package.
 *
 * A case is one capture: the configuration, the number of samples, and a
 * deterministic multi-tone-plus-noise signal that gives the detector something
 * to find.
 */
#ifndef SENS_CASES_H
#define SENS_CASES_H

#include <math.h>
#include <stdint.h>

#define SENS_PI 3.14159265358979324

typedef struct {
    int fft_len;
    int frame_step;
    double thr_scale;
    int nin;
} sens_case;

static const sens_case sens_cases[] = {
    /* fft_len  step  thr_scale   nin */
    {      32,   16,       3.0,   512 },
    {      64,   32,       4.0,  2048 },
    {      64,   64,       6.0,  1024 },
    {     128,   32,       5.0,  4096 },
    {     256,  100,       8.0,  3000 },
    {     512,  512,      10.0,  4096 },
    {    1024,  256,      12.0,  8192 },
    {     128,  127,       6.0,  1000 }
};

static const int SENS_NCASES = (int)(sizeof(sens_cases) / sizeof(sens_cases[0]));

/* Frames that fit in `nin` samples: frame f starts at f*step. */
static inline int sens_nframes(int fft_len, int frame_step, int nin)
{
    if (nin < fft_len) return 0;
    return 1 + (nin - fft_len) / frame_step;
}

static inline uint64_t sens_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline double sens_rand(uint64_t *s)
{
    return ((double)(sens_next(s) >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* Three tones on well-separated bins over a noisy floor, scaled so the peak
 * sample is just below 1.  Every case gets a different seed and different bin
 * placement so a candidate cannot special-case the signal. */
static inline void sens_make_signal(const sens_case *c, double *x)
{
    uint64_t s = 0x5EED0000ULL + (uint64_t)c->fft_len * 31ULL +
                 (uint64_t)c->nin;
    const int N = c->fft_len;
    const int b[3] = { N / 8 + 1, N / 3 + 1, N / 2 - 2 };
    const double amp[3] = { 0.55, 0.32, 0.18 };
    const double ph[3] = { 0.3, 1.1, 2.4 };
    double peak = 0.0;
    int n, t;

    for (n = 0; n < c->nin; ++n) {
        x[n] = 0.08 * sens_rand(&s);
    }

    for (t = 0; t < 3; ++t) {
        for (n = 0; n < c->nin; ++n) {
            x[n] += amp[t] * sin(2.0 * SENS_PI * (double)b[t] * (double)n /
                                 (double)N + ph[t]);
        }
    }

    for (n = 0; n < c->nin; ++n) {
        if (fabs(x[n]) > peak) peak = fabs(x[n]);
    }
    if (peak > 0.0) {
        for (n = 0; n < c->nin; ++n) x[n] *= 0.9 / peak;
    }
}

#endif /* SENS_CASES_H */