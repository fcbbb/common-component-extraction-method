// Hidden case table and deterministic input generator (included by
// golden_gen.cpp only).
#pragma once

#include <cstdint>
#include <cmath>
#include "fft.h"

struct fft_case
{
    int size;
    ipl::FFTDomain domain;
};

static const fft_case fft_cases[] = {
    {   64, ipl::FFTDomain::Real    },  // power of two
    {  100, ipl::FFTDomain::Real    },  // rounds up to 128
    {    7, ipl::FFTDomain::Real    },  // rounds up to 8
    {  300, ipl::FFTDomain::Real    },  // rounds up to 512
    {    4, ipl::FFTDomain::Real    },  // smallest size jvsip handles (N=2 SIGFPEs)
    {   32, ipl::FFTDomain::Complex },
    { 1000, ipl::FFTDomain::Complex }   // rounds up to 1024
};

#define FFT_NCASES (static_cast<int>(sizeof(fft_cases) / sizeof(fft_cases[0])))

inline std::uint64_t fft_splitmix64(std::uint64_t* state)
{
    std::uint64_t z = (*state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

// Uniform in [-1, 1).
inline float fft_rand(std::uint64_t* state)
{
    const std::uint64_t v = fft_splitmix64(state);
    return static_cast<float>((v >> 11) * (2.0 / 9007199254740992.0) - 1.0);
}