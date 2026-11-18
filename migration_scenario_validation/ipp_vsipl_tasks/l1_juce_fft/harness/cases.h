// Hidden case table and deterministic input generator (included by
// golden_gen.cpp only).  The hidden_test reads everything it needs from the
// case containers.
#pragma once

#include <cstdint>

enum juce_op
{
    OP_COMPLEX_FWD = 0,       // perform(in, out, false)
    OP_COMPLEX_INV = 1,       // perform(in, out, true)
    OP_REAL_FWD = 2,          // performRealOnlyForwardTransform(d, false)
    OP_REAL_FWD_HALF = 3,     // performRealOnlyForwardTransform(d, true)
    OP_REAL_INV = 4,          // performRealOnlyInverseTransform(d)
    OP_FREQ_ONLY = 5,         // performFrequencyOnlyForwardTransform(d, false)
    OP_FREQ_ONLY_HALF = 6     // performFrequencyOnlyForwardTransform(d, true)
};

struct juce_case
{
    int order;
    int op;
};

// Orders span the degenerate sizes (1, 2, 4, 8 points, all below jvsip's
// minimum plan length of 4) up to 1024 points.
static const juce_case juce_cases[] = {
    { 0, OP_COMPLEX_FWD }, { 0, OP_COMPLEX_INV },
    { 0, OP_REAL_FWD },    { 0, OP_REAL_FWD_HALF }, { 0, OP_REAL_INV },
    { 0, OP_FREQ_ONLY },   { 0, OP_FREQ_ONLY_HALF },

    { 1, OP_COMPLEX_FWD }, { 1, OP_COMPLEX_INV },
    { 1, OP_REAL_FWD },    { 1, OP_REAL_FWD_HALF }, { 1, OP_REAL_INV },
    { 1, OP_FREQ_ONLY },   { 1, OP_FREQ_ONLY_HALF },

    { 2, OP_COMPLEX_FWD }, { 2, OP_COMPLEX_INV },
    { 2, OP_REAL_FWD },    { 2, OP_REAL_FWD_HALF }, { 2, OP_REAL_INV },
    { 2, OP_FREQ_ONLY },   { 2, OP_FREQ_ONLY_HALF },

    { 3, OP_COMPLEX_FWD }, { 3, OP_COMPLEX_INV },
    { 3, OP_REAL_FWD },    { 3, OP_REAL_FWD_HALF }, { 3, OP_REAL_INV },
    { 3, OP_FREQ_ONLY },   { 3, OP_FREQ_ONLY_HALF },

    { 4, OP_COMPLEX_FWD }, { 4, OP_COMPLEX_INV },
    { 4, OP_REAL_FWD },    { 4, OP_REAL_FWD_HALF }, { 4, OP_REAL_INV },
    { 4, OP_FREQ_ONLY },   { 4, OP_FREQ_ONLY_HALF },

    { 5, OP_COMPLEX_FWD }, { 5, OP_COMPLEX_INV },
    { 5, OP_REAL_FWD },    { 5, OP_REAL_FWD_HALF }, { 5, OP_REAL_INV },
    { 5, OP_FREQ_ONLY },   { 5, OP_FREQ_ONLY_HALF },

    { 6, OP_COMPLEX_FWD }, { 6, OP_COMPLEX_INV },
    { 6, OP_REAL_FWD },    { 6, OP_REAL_FWD_HALF }, { 6, OP_REAL_INV },
    { 6, OP_FREQ_ONLY },   { 6, OP_FREQ_ONLY_HALF },

    { 8, OP_COMPLEX_FWD }, { 8, OP_COMPLEX_INV },
    { 8, OP_REAL_FWD },    { 8, OP_REAL_FWD_HALF }, { 8, OP_REAL_INV },
    { 8, OP_FREQ_ONLY },   { 8, OP_FREQ_ONLY_HALF },

    { 10, OP_COMPLEX_FWD }, { 10, OP_COMPLEX_INV },
    { 10, OP_REAL_FWD },    { 10, OP_REAL_FWD_HALF }, { 10, OP_REAL_INV },
    { 10, OP_FREQ_ONLY },   { 10, OP_FREQ_ONLY_HALF }
};

#define JUCE_NCASES (static_cast<int>(sizeof(juce_cases) / sizeof(juce_cases[0])))

inline std::uint64_t juce_splitmix64(std::uint64_t* state)
{
    std::uint64_t z = (*state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

// Uniform in [-1, 1).
inline float juce_rand(std::uint64_t* state)
{
    const std::uint64_t v = juce_splitmix64(state);
    return static_cast<float>((v >> 11) * (2.0 / 9007199254740992.0) - 1.0);
}

// Number of leading floats that are part of the observable result.
inline int juce_ncompare(int op, int n)
{
    switch (op)
    {
        case OP_REAL_FWD_HALF:   return (n + 2 <= 2 * n) ? n + 2 : 2 * n;
        case OP_REAL_INV:        return n;
        default:                 return 2 * n;
    }
}