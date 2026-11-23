/* -*- c-basic-offset: 4 indent-tabs-mode: nil -*-  vi:set ts=8 sts=4 sw=4: */

/*
    Trimmed subset of Rubber Band Library's common/ support code.

    The full library spreads these helpers over sysutils.h, Allocators.h and
    VectorOpsComplex.h; the extracted component only needs the allocation
    wrappers and the polar/cartesian helpers used by the built-in DFT
    fallback, so they are collected here unchanged in behaviour.
*/

#ifndef RUBBERBAND_SUPPORT_H
#define RUBBERBAND_SUPPORT_H

#include <cmath>
#include <cstddef>

/* Restrict qualifier (as in sysutils.h) */
#if defined(__GNUC__) || defined(__clang__)
#  define R__ __restrict__
#elif defined(_MSC_VER)
#  define R__ __restrict
#else
#  define R__
#endif

#define BQ_R__ R__

template <typename T>
T *allocate(size_t count)
{
    return new T[count];
}

template <typename T>
T *allocate_and_zero(size_t count)
{
    T *ptr = new T[count];
    for (size_t i = 0; i < count; ++i) ptr[i] = T(0);
    return ptr;
}

template <typename T>
void deallocate(T *ptr)
{
    delete[] ptr;
}

template <typename T>
T **allocate_channels(size_t channels, size_t count)
{
    T **ptr = new T *[channels];
    for (size_t c = 0; c < channels; ++c) {
        ptr[c] = allocate<T>(count);
    }
    return ptr;
}

template <typename T>
void deallocate_channels(T **ptr, size_t channels)
{
    for (size_t c = 0; c < channels; ++c) {
        deallocate(ptr[c]);
    }
    delete[] ptr;
}

template <typename T>
inline void c_magphase(T *mag, T *phase, T real, T imag)
{
    *mag = std::sqrt(real * real + imag * imag);
    *phase = std::atan2(imag, real);
}

template <typename T>
inline void c_phasor(T *real, T *imag, T phase)
{
    *real = std::cos(phase);
    *imag = std::sin(phase);
}

template <typename S, typename T> // S source, T target
void v_polar_to_cartesian_interleaved(T *const BQ_R__ dst,
                                      const S *const BQ_R__ mag,
                                      const S *const BQ_R__ phase,
                                      const int count)
{
    T real, imag;
    for (int i = 0; i < count; ++i) {
        c_phasor<T>(&real, &imag, phase[i]);
        real *= mag[i];
        imag *= mag[i];
        dst[i * 2] = real;
        dst[i * 2 + 1] = imag;
    }
}

#endif