/**
 * @file saf_support.h
 * @brief Trimmed stand-ins for the Spatial_Audio_Framework internals that the
 *        FFT utilities rely on.
 *
 * The extracted component (saf_utility_fft.c) uses saf_externals.h
 * (malloc1d/calloc1d/calloc2d/calloc3d/realloc2d_r/realloc3d_r/FLATTEN*D),
 * saf_utilities.h (SAF_PI, ISEVEN, saf_assert), saf_utility_complex.h
 * (float_complex and friends), saf_utility_filters.h (getWindowingFunction)
 * and saf_utility_veclib.h (utility_cvvmul/utility_svvmul).  Only the pieces
 * the component actually calls are reproduced here, with the same names and
 * the same semantics; cblas_saxpy is provided as saf_saxpy so that the task
 * package does not need a BLAS dependency.
 */

#ifndef SAF_SUPPORT_H_INCLUDED
#define SAF_SUPPORT_H_INCLUDED

#include <complex.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SAF_PI ( 3.14159265358979323846264338327950288f )
#define ISEVEN(x) ( (x) % 2 == 0 )

/** C99 complex, the representation SAF uses when SAF_USE_C99_COMPLEX is set. */
typedef float _Complex float_complex;

static inline float_complex cmplxf(float re, float im)
{
    return re + im * I;
}

static inline void saf_assert_fail(const char* msg)
{
    fprintf(stderr, "SAF assertion failed: %s\n", msg);
    abort();
}

#define saf_assert(cond, msg) do { if (!(cond)) saf_assert_fail(msg); } while (0)

/* ------------------------------------------------------------------------- */
/*                          Allocation helpers                               */
/* ------------------------------------------------------------------------- */

/** Allocates 'size' bytes; aborts when the allocator refuses. */
static inline void* malloc1d(size_t size)
{
    void* p = malloc(size);
    saf_assert(p != NULL || size == 0, "out of memory");
    return p;
}

/** Allocates 'n' zeroed records of 'size' bytes each. */
static inline void* calloc1d(int n, size_t size)
{
    void* p = calloc((size_t)n, size);
    saf_assert(p != NULL || n == 0 || size == 0, "out of memory");
    return p;
}

/** Row-major 2D array: nRows pointers into one contiguous zeroed block. */
static inline void** calloc2d(int nRows, int nCols, size_t elemSize)
{
    int i;
    void** rows = (void**)calloc1d(nRows, sizeof(void*));
    void* block;
    if (nRows <= 0) return rows;
    block = calloc1d(nRows * nCols, elemSize);
    for (i = 0; i < nRows; ++i)
        rows[i] = (char*)block + (size_t)i * (size_t)nCols * elemSize;
    return rows;
}

/** 3D array: [nA][nB] pointers into one contiguous zeroed block. */
static inline void*** calloc3d(int nA, int nB, int nC, size_t elemSize)
{
    int i, j;
    void*** rows = (void***)calloc1d(nA, sizeof(void**));
    void* block;
    if (nA <= 0) return rows;
    block = calloc1d(nA * nB * nC, elemSize);
    for (i = 0; i < nA; ++i) {
        rows[i] = (void**)calloc1d(nB, sizeof(void*));
        for (j = 0; j < nB; ++j)
            rows[i][j] = (char*)block +
                ((size_t)i * (size_t)nB + (size_t)j) * (size_t)nC * elemSize;
    }
    return rows;
}

/** Reallocates a 2D array, retaining the overlapping region. */
static inline void** realloc2d_r(void** ptr, int newRows, int newCols,
                                 int oldRows, int oldCols, size_t elemSize)
{
    int i, n;
    void** out = calloc2d(newRows, newCols, elemSize);
    n = (newRows < oldRows) ? newRows : oldRows;
    for (i = 0; i < n; ++i) {
        int m = (newCols < oldCols) ? newCols : oldCols;
        memcpy(out[i], ptr[i], (size_t)m * elemSize);
    }
    return out;
}

/** Reallocates a 3D array, retaining the overlapping region. */
static inline void*** realloc3d_r(void*** ptr, int newA, int newB, int newC,
                                  int oldA, int oldB, int oldC, size_t elemSize)
{
    int i, j, na, nb;
    void*** out = calloc3d(newA, newB, newC, elemSize);
    na = (newA < oldA) ? newA : oldA;
    nb = (newB < oldB) ? newB : oldB;
    for (i = 0; i < na; ++i) {
        for (j = 0; j < nb; ++j) {
            int nc = (newC < oldC) ? newC : oldC;
            memcpy(out[i][j], ptr[i][j], (size_t)nc * elemSize);
        }
    }
    return out;
}

/* The blocks above are contiguous, so flattening is the address of the first
 * element -- the same property the upstream macros rely on. */
#define FLATTEN2D(x) ((void*)(x)[0])
#define FLATTEN3D(x) ((void*)(x)[0][0])

/* ------------------------------------------------------------------------- */
/*                            Vector helpers                                 */
/* ------------------------------------------------------------------------- */

/** c = a .* b, elementwise, complex. */
static inline void utility_cvvmul(const float_complex* a,
                                  const float_complex* b,
                                  const int len,
                                  float_complex* c)
{
    int i;
    for (i = 0; i < len; ++i) c[i] = a[i] * b[i];
}

/** c = a .* b, elementwise, real. */
static inline void utility_svvmul(const float* a,
                                  const float* b,
                                  const int len,
                                  float* c)
{
    int i;
    for (i = 0; i < len; ++i) c[i] = a[i] * b[i];
}

/** y(a:b) += alpha * x(a:b); the slice the STFT overlap-add needs. */
static inline void saf_saxpy(int n, float alpha, const float* x, int incx,
                             float* y, int incy)
{
    int i;
    for (i = 0; i < n; ++i) y[i * incy] += alpha * x[i * incx];
}

/* ------------------------------------------------------------------------- */
/*                          Windowing functions                              */
/* ------------------------------------------------------------------------- */

typedef enum {
    WINDOWING_FUNCTION_RECTANGULAR = 0,
    WINDOWING_FUNCTION_HAMMING,
    WINDOWING_FUNCTION_HANN,
    WINDOWING_FUNCTION_BARTLETT,
    WINDOWING_FUNCTION_BLACKMAN,
    WINDOWING_FUNCTION_NUTTALL,
    WINDOWING_FUNCTION_BLACKMAN_NUTTALL,
    WINDOWING_FUNCTION_BLACKMAN_HARRIS

} WINDOWING_FUNCTION_TYPES;

/** Applies a windowing function of length 'winlength' to vector 'x'. */
static inline void applyWindowingFunction(WINDOWING_FUNCTION_TYPES type,
                                          int winlength,
                                          float* x)
{
    int i, N;

    /* if winlength is odd -> symmetric window (mid index has value=1) */
    if (!(winlength % 2 == 0))
        N = winlength - 1;
    /* otherwise, if winlength is even (index: winlength/2+1 = 1.0, but first
     * value != last value) */
    else
        N = winlength;

    switch (type) {
    case WINDOWING_FUNCTION_RECTANGULAR:
        break;
    case WINDOWING_FUNCTION_HAMMING:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.54f - 0.46f * (cosf(2.0f * SAF_PI * (float)i / (float)N));
        break;
    case WINDOWING_FUNCTION_HANN:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.5f - 0.5f * (cosf(2.0f * SAF_PI * (float)i / (float)N));
        break;
    case WINDOWING_FUNCTION_BARTLETT:
        for (i = 0; i < winlength; i++)
            x[i] *= 1.0f - 2.0f * (fabsf((float)i - ((float)N / 2.0f)) / (float)N);
        break;
    case WINDOWING_FUNCTION_BLACKMAN:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.42659f -
                    0.49656f * cosf(2.0f * SAF_PI * (float)i / (float)N) +
                    0.076849f * cosf(4.0f * SAF_PI * (float)i / (float)N);
        break;
    case WINDOWING_FUNCTION_NUTTALL:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.355768f -
                    0.487396f * cosf(2.0f * SAF_PI * (float)i / (float)N) +
                    0.144232f * cosf(4.0f * SAF_PI * (float)i / (float)N) -
                    0.012604f * cosf(6.0f * SAF_PI * (float)i / (float)N);
        break;
    case WINDOWING_FUNCTION_BLACKMAN_NUTTALL:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.3635819f -
                    0.4891775f * cosf(2.0f * SAF_PI * (float)i / (float)N) +
                    0.1365995f * cosf(4.0f * SAF_PI * (float)i / (float)N) +
                    0.0106411f * cosf(4.0f * SAF_PI * (float)i / (float)N);
        break;
    case WINDOWING_FUNCTION_BLACKMAN_HARRIS:
        for (i = 0; i < winlength; i++)
            x[i] *= 0.35875f -
                    0.48829f * cosf(2.0f * SAF_PI * (float)i / (float)N) +
                    0.14128f * cosf(4.0f * SAF_PI * (float)i / (float)N) +
                    0.01168f * cosf(4.0f * SAF_PI * (float)i / (float)N);
        break;
    }
}

/* ------------------------------------------------------------------------- */
/*                              Misc. helpers                                */
/* ------------------------------------------------------------------------- */

/** Smallest power of two greater than or equal to 'numsamp' (>= 2). */
static inline int nextpow2(int numsamp)
{
    int npts_max = 1;
    while (1) {
        npts_max *= 2;
        if (npts_max >= numsamp)
            return npts_max;
    }
}

/** Fills 'win' with unity and applies the requested window. */
static inline void getWindowingFunction(WINDOWING_FUNCTION_TYPES type,
                                        int winlength,
                                        float* win)
{
    int i;
    for (i = 0; i < winlength; i++)
        win[i] = 1.0f;
    applyWindowingFunction(type, winlength, win);
}

#endif /* SAF_SUPPORT_H_INCLUDED */