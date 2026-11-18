/* Case table and shared arithmetic for the comms demod frontend package.
 *
 * A case is one streaming session: the input is fed to dem_process() in
 * chunks of `block` samples, and the concatenated output plus the statistics
 * of the whole output block are compared.
 */
#ifndef DEM_CASES_H
#define DEM_CASES_H

#include <math.h>
#include <stdint.h>

#define DEM_PI 3.14159265358979324

typedef struct {
    int nco_len;
    int decim;
    int ntaps;
    int nin;
    int block;
} dem_case;

static const dem_case dem_cases[] = {
    /* nco  decim  taps    nin  block */
    {  64,     4,     8,   512,   512 },
    {  64,     4,     8,   512,     1 },
    {  64,     4,     8,   512,    37 },
    {   7,     1,    16,   256,    64 },
    {   5,     3,     5,   301,   100 },
    {  16,     8,    12,  1024,   128 },
    {   3,     2,    32,   200,   200 },
    {  64,     4,     8,   100,    13 }
};

static const int DEM_NCASES = (int)(sizeof(dem_cases) / sizeof(dem_cases[0]));

/* Number of decimation instants produced by a complete stream of `nin`
 * samples: j*M >= T-1 and j*M <= nin-1. */
static inline int dem_nout(int decim, int T, int nin)
{
    long j0, jmax;

    if (nin <= 0 || decim <= 0 || T <= 0) return 0;
    j0 = ((long)T - 1 + decim - 1) / decim;
    jmax = ((long)nin - 1) / decim;

    return (jmax < j0) ? 0 : (int)(jmax - j0 + 1);
}

static inline uint64_t dem_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static inline double dem_rand(uint64_t *s)
{
    return ((double)(dem_next(s) >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* Deterministic NCO table: a complex exponential of `cycles` turns. */
static inline void dem_make_nco(int nco_len, double *re, double *im,
                                double cycles)
{
    int i;

    for (i = 0; i < nco_len; ++i) {
        const double a = 2.0 * DEM_PI * cycles * (double)i / (double)nco_len;
        re[i] = cos(a);
        im[i] = -sin(a);
    }
}

/* Deterministic complex low-pass taps: windowed sinc with a small quadrature
 * component, normalised to unit DC gain. */
static inline void dem_make_taps(int T, double *re, double *im, double cutoff)
{
    double sum = 0.0;
    int i;

    for (i = 0; i < T; ++i) {
        const double n = (double)i - (double)(T - 1) / 2.0;
        double s;

        if (fabs(n) < 1e-12) s = 2.0 * cutoff;
        else s = sin(2.0 * DEM_PI * cutoff * n) / (DEM_PI * n);

        if (T > 1) {
            const double w = 0.54 - 0.46 * cos(2.0 * DEM_PI * (double)i /
                                               (double)(T - 1));
            s *= w;
        }

        re[i] = s;
        im[i] = 0.05 * s * sin(0.7 * (double)i);
    }

    for (i = 0; i < T; ++i) sum += re[i];
    if (fabs(sum) > 1e-12) {
        for (i = 0; i < T; ++i) { re[i] /= sum; im[i] /= sum; }
    }
}

#endif /* DEM_CASES_H */