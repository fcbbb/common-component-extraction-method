/* Case table and shared signal synthesis for the pulse-compression package.
 *
 * A case is one capture: the configuration plus the delays and amplitudes of
 * the targets that were laid into it.  Each pulse is a sum of circularly
 * shifted replicas (a target at delay d puts the correlation peak on lag d)
 * over a small deterministic noise floor.
 */
#ifndef PC_CASES_H
#define PC_CASES_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#ifndef PC_PI
#define PC_PI 3.14159265358979324
#endif

typedef struct {
    int fft_len;
    int npulses;
    int fir_len;
    double chirp_rate;
    double thr_scale;
    double noise;
    int ntargets;
    int delay[3];
    double amp[3];
} pc_case;

static const pc_case pc_cases[] = {
    /*    N  np  L  chirp   thr  noise  nt  delays             amps */
    {   64, 32,  1, 0.80,  3.0, 0.010,  3, {   6,  18,  26}, {1.0, 0.60, 0.35} },
    {  128, 16,  3, 0.75,  4.0, 0.010,  3, {  12,  35,  52}, {1.0, 0.70, 0.40} },
    {  256, 16,  3, 0.80,  4.0, 0.010,  3, {  20,  70, 110}, {1.0, 0.70, 0.45} },
    {  512,  8,  5, 0.85,  5.0, 0.010,  3, {  40, 150, 220}, {1.0, 0.75, 0.50} },
    { 1024,  4,  7, 0.90,  6.0, 0.008,  3, {  80, 300, 460}, {1.0, 0.80, 0.55} },
    { 2048,  8,  5, 0.85,  6.0, 0.008,  3, { 150, 600, 900}, {1.0, 0.80, 0.50} },
    { 4096,  4,  9, 0.90, 10.0, 0.006,  3, { 300,1200,1800}, {1.0, 0.75, 0.50} },
    {  256,  3, 15, 0.80,  3.0, 0.008,  1, {  40,   0,   0}, {1.0, 0.00, 0.00} }
};

static const int PC_NCASES = (int)(sizeof(pc_cases) / sizeof(pc_cases[0]));

static inline int pc_nrange_of(int fft_len)
{
    return fft_len / 2 + 1;
}

static inline uint64_t pc_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);

    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline double pc_rand(uint64_t *s)
{
    return ((double)(pc_next(s) >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* The header's replica definition, in double. */
static inline void pc_replica(double chirp_rate, int N, double *r)
{
    int i;

    for (i = 0; i < N; ++i) {
        const double w = 0.5 * (1.0 - cos(2.0 * PC_PI * (double)i /
                                          (double)(N - 1)));
        const double u = (double)i - 0.5 * (double)(N - 1);
        const double ph = PC_PI * chirp_rate * u * u / (double)N;

        r[i] = w * cos(ph);
    }
}

/* Fills x with c->npulses pulses of c->fft_len samples. */
static inline void pc_make_signal(const pc_case *c, double *x)
{
    const int N = c->fft_len;
    uint64_t s = 0x9AD00000ULL + (uint64_t)N * 131ULL +
                 (uint64_t)c->npulses * 17ULL + (uint64_t)c->fir_len;
    double *r = (double *)0;
    double rbuf[4096];
    int p, n, t;

    if (N <= (int)(sizeof(rbuf) / sizeof(rbuf[0]))) {
        r = rbuf;
    } else {
        return;                 /* every case fits the static buffer */
    }
    pc_replica(c->chirp_rate, N, r);

    for (p = 0; p < c->npulses; ++p) {
        double *xp = x + (size_t)p * (size_t)N;

        for (n = 0; n < N; ++n) xp[n] = c->noise * pc_rand(&s);

        for (t = 0; t < c->ntargets; ++t) {
            for (n = 0; n < N; ++n) {
                const int m = ((n - c->delay[t]) % N + N) % N;

                xp[n] += c->amp[t] * r[m];
            }
        }
    }
}

#endif /* PC_CASES_H */