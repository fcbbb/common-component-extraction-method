/* Hidden/public case table for the r8brain real-FFT package.
 *
 * A case is one call sequence into the CDSPRealFFT API.  The payload is a
 * flat array of doubles; for the cases whose input must be a valid Perm FFT
 * block (inverse, block products) the golden generator builds it with the
 * baseline's own forward transform and stores the result, so the candidate
 * receives exactly the block the baseline consumed.
 */
#ifndef R8B_CASES_H
#define R8B_CASES_H

#include <cstdint>

enum {
    R8_OP_FWD = 0,      /* payload: Len real samples        -> Len Perm bins */
    R8_OP_INV,          /* payload: Len Perm bins           -> Len real samples */
    R8_OP_ROUNDTRIP,    /* payload: Len real samples        -> Len real samples */
    R8_OP_MUL,          /* payload: 2 x Len real samples    -> Len Perm product */
    R8_OP_MUL_I,        /* payload: 2 x Len real samples    -> Len Perm product */
    R8_OP_MUL_ZP,       /* payload: Len products + Len ZP   -> Len Perm product */
    R8_OP_ZP,           /* payload: Len real samples        -> Len ZP bins */
    R8_OP_NYQ,          /* payload: Len real samples + v    -> Len Perm bins */
    R8_OP_MINPHASE,     /* payload: KernelLen kernel        -> KernelLen + delay */
    R8_OP_KEEPER        /* payload: Len real samples        -> 2 x Len Perm bins */
};

struct r8b_case {
    int op;
    int LenBits;
    int KernelLen;      /* R8_OP_MINPHASE only */
    int LenMult;        /* calcMinPhaseTransform: LenMult */
    int DoFinalMul;     /* calcMinPhaseTransform: DoFinalMul */
};

static inline int r8b_len(const int LenBits) { return 1 << LenBits; }

static inline int r8b_plen(const int op, const int LenBits, const int KernelLen)
{
    const int Len = r8b_len(LenBits);
    switch (op) {
    case R8_OP_MUL:
    case R8_OP_MUL_I:
    case R8_OP_MUL_ZP:     return 2 * Len;
    case R8_OP_NYQ:        return Len + 1;
    case R8_OP_MINPHASE:   return KernelLen;
    default:               return Len;
    }
}

static inline int r8b_nout(const int op, const int LenBits, const int KernelLen)
{
    if (op == R8_OP_MINPHASE) return KernelLen + 1;
    if (op == R8_OP_KEEPER)   return 2 * r8b_len(LenBits);
    return r8b_len(LenBits);
}

static const r8b_case r8b_cases[] = {
    /* op                bits  kernel  mult  final */
    { R8_OP_FWD,            4,     0,     2,     1 },
    { R8_OP_FWD,           10,     0,     2,     1 },
    { R8_OP_INV,            4,     0,     2,     1 },
    { R8_OP_INV,            8,     0,     2,     1 },
    { R8_OP_INV,           12,     0,     2,     1 },
    { R8_OP_ROUNDTRIP,      6,     0,     2,     1 },
    { R8_OP_ROUNDTRIP,     12,     0,     2,     1 },
    { R8_OP_MUL,            8,     0,     2,     1 },
    { R8_OP_MUL,            3,     0,     2,     1 },
    { R8_OP_MUL_I,          5,     0,     2,     1 },
    { R8_OP_MUL_ZP,         8,     0,     2,     1 },
    { R8_OP_ZP,             6,     0,     2,     1 },
    { R8_OP_NYQ,            6,     0,     2,     1 },
    { R8_OP_MINPHASE,       5,    24,     2,     1 },
    { R8_OP_MINPHASE,       6,    40,     4,     0 },
    { R8_OP_KEEPER,         6,     0,     2,     1 }
};

static const int R8B_NCASES =
    (int)(sizeof(r8b_cases) / sizeof(r8b_cases[0]));

/* Deterministic value source: splitmix64, mapped to [-1, 1). */
static inline uint64_t r8b_mix(uint64_t &s)
{
    uint64_t z = (s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline double r8b_rand(uint64_t &s)
{
    return ((double)(r8b_mix(s) >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* A minimum-phase-friendly kernel: |X(w)| stays well away from zero, so the
 * log-magnitude step of calcMinPhaseTransform is not ill-conditioned. */
static inline void r8b_fill_kernel(double *k, const int n, uint64_t &s)
{
    int i;
    k[0] = 1.0;
    for (i = 1; i < n; ++i) {
        const double env = 0.55 * (1.0 - (double)i / (double)(n + 1));
        k[i] = env * (double)((i & 1) ? 1 : -1) * 0.5
             + 0.05 * r8b_rand(s);
    }
    /* keep the DC gain at 1 so the final scale is well defined */
    double sum = 0.0;
    for (i = 0; i < n; ++i) sum += k[i];
    for (i = 0; i < n; ++i) k[i] /= sum;
}

#endif /* R8B_CASES_H */