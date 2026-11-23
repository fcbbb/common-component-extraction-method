/* Case table shared by the golden generator and the hidden test.
 *
 * The table is built at run time so that each group of cases is written once,
 * in the same order on both sides.  Everything here is pure bookkeeping: the
 * values are derived from the case fields, so golden_gen and hidden_test can
 * never disagree about a payload or comparison length.
 */
#ifndef SAF_CASES_H
#define SAF_CASES_H

#include <stdint.h>
#include <string.h>

#include "saf_utility_fft.h"

enum {
    SAF_OP_RFFT_FWD      = 0,
    SAF_OP_RFFT_BWD      = 1,
    SAF_OP_RFFT_ROUND    = 2,
    SAF_OP_CFFT_FWD      = 3,
    SAF_OP_CFFT_BWD      = 4,
    SAF_OP_CFFT_ROUND    = 5,
    SAF_OP_STFT_FWD      = 6,
    SAF_OP_STFT_BWD      = 7,
    SAF_OP_STFT_ROUND    = 8,
    SAF_OP_STFT_STATEFUL = 9,   /* forward, backward, backward */
    SAF_OP_STFT_FLUSH    = 10,  /* forward, backward, flush, backward */
    SAF_OP_STFT_CHCHANGE = 11,  /* 2ch round trip, channelChange, 1ch round trip */
    SAF_OP_FFTCONV       = 12,
    SAF_OP_FFTFILT       = 13,
    SAF_OP_HILBERT       = 14,
    SAF_OP_FREQVEC       = 15
};

typedef struct {
    int op;
    int n;        /* FFT size, or the signal length for conv/filt/hilbert */
    int win, hop; /* STFT window and hop */
    int nchin, nchout;
    int fmt;      /* SAF_STFT_FDDATA_FORMAT */
    int aux;      /* filter length (conv/filt) or sampling rate (freqvec) */
} saf_case;

/* Real transforms: even powers of two take the ippsFFT path, 6/100/1000 take
 * the ippsDFT path. */
#define SAF_RFFT_SIZES 6
static const int saf_rfft_sizes[SAF_RFFT_SIZES] = { 8, 64, 1024, 6, 100, 1000 };

/* Complex transforms, same split. */
#define SAF_CFFT_SIZES 6
static const int saf_cfft_sizes[SAF_CFFT_SIZES] = { 4, 8, 32, 100, 1000, 1024 };

/* STFT configurations: the first two entries of each pair are winsize/hopsize.
 * win == hop is the rectangular, stateless branch; the others exercise the
 * Hann window and the previous-hop history.  win=100 makes the internal FFT
 * length 200, i.e. the ippsDFT path. */
#define SAF_STFT_CFGS 5
static const saf_case saf_stft_cfgs[SAF_STFT_CFGS] = {
    { 0, 0, 256, 256, 1, 1, SAF_STFT_TIME_CH_BANDS, 0 },
    { 0, 0, 128,  64, 2, 2, SAF_STFT_BANDS_CH_TIME, 0 },
    { 0, 0,  64,  16, 2, 1, SAF_STFT_TIME_CH_BANDS, 0 },
    { 0, 0,  32,  32, 2, 2, SAF_STFT_BANDS_CH_TIME, 0 },
    { 0, 0, 100,  50, 1, 1, SAF_STFT_TIME_CH_BANDS, 0 }
};

#define SAF_NCASES 66

static saf_case saf_cases[SAF_NCASES];

static void saf_build_cases(void)
{
    int k = 0, i;

    /* 0..17: real forward / inverse / round trip */
    for (i = 0; i < SAF_RFFT_SIZES; ++i) {
        int op;
        for (op = 0; op < 3; ++op) {
            saf_case *c = &saf_cases[k++];
            memset(c, 0, sizeof(*c));
            c->op = SAF_OP_RFFT_FWD + op;
            c->n = saf_rfft_sizes[i];
        }
    }

    /* 18..35: complex forward / inverse / round trip */
    for (i = 0; i < SAF_CFFT_SIZES; ++i) {
        int op;
        for (op = 0; op < 3; ++op) {
            saf_case *c = &saf_cases[k++];
            memset(c, 0, sizeof(*c));
            c->op = SAF_OP_CFFT_FWD + op;
            c->n = saf_cfft_sizes[i];
        }
    }

    /* 36..50: STFT forward / backward / round trip over five configurations */
    for (i = 0; i < SAF_STFT_CFGS; ++i) {
        int op;
        for (op = 0; op < 3; ++op) {
            saf_cases[k] = saf_stft_cfgs[i];
            saf_cases[k].op = SAF_OP_STFT_FWD + op;
            ++k;
        }
    }

    /* 51..55: stateful overlap-add, flush, channel change */
    saf_cases[k] = saf_stft_cfgs[1]; saf_cases[k].op = SAF_OP_STFT_STATEFUL; ++k;
    saf_cases[k] = saf_stft_cfgs[1]; saf_cases[k].op = SAF_OP_STFT_FLUSH;    ++k;
    saf_cases[k] = saf_stft_cfgs[2]; saf_cases[k].op = SAF_OP_STFT_STATEFUL; ++k;
    saf_cases[k] = saf_stft_cfgs[2]; saf_cases[k].op = SAF_OP_STFT_FLUSH;    ++k;
    saf_cases[k] = saf_stft_cfgs[1]; saf_cases[k].op = SAF_OP_STFT_CHCHANGE; ++k;

    /* 56..58: fftconv */
    memset(&saf_cases[k], 0, sizeof(saf_case));
    saf_cases[k].op = SAF_OP_FFTCONV; saf_cases[k].n = 100; saf_cases[k].nchin = 2;
    saf_cases[k].aux = 32; ++k;
    saf_cases[k].op = SAF_OP_FFTCONV; saf_cases[k].n = 64; saf_cases[k].nchin = 1;
    saf_cases[k].aux = 64; ++k;
    saf_cases[k].op = SAF_OP_FFTCONV; saf_cases[k].n = 200; saf_cases[k].nchin = 1;
    saf_cases[k].aux = 100; ++k;

    /* 59..60: fftfilt */
    memset(&saf_cases[k], 0, sizeof(saf_case));
    saf_cases[k].op = SAF_OP_FFTFILT; saf_cases[k].n = 100; saf_cases[k].nchin = 2;
    saf_cases[k].aux = 32; ++k;
    saf_cases[k].op = SAF_OP_FFTFILT; saf_cases[k].n = 200; saf_cases[k].nchin = 1;
    saf_cases[k].aux = 100; ++k;

    /* 61..63: hilbert */
    memset(&saf_cases[k], 0, sizeof(saf_case));
    saf_cases[k].op = SAF_OP_HILBERT; saf_cases[k].n = 64;  ++k;
    saf_cases[k].op = SAF_OP_HILBERT; saf_cases[k].n = 100; ++k;
    saf_cases[k].op = SAF_OP_HILBERT; saf_cases[k].n = 256; ++k;

    /* 64..65: frequency vector */
    memset(&saf_cases[k], 0, sizeof(saf_case));
    saf_cases[k].op = SAF_OP_FREQVEC; saf_cases[k].n = 256;  saf_cases[k].aux = 48000; ++k;
    saf_cases[k].op = SAF_OP_FREQVEC; saf_cases[k].n = 1000; saf_cases[k].aux = 44100; ++k;
}

/* ------------------------------------------------------------------------- */
/*                            Derived lengths                                */
/* ------------------------------------------------------------------------- */

static int saf_framesize(const saf_case *c) { return 4 * c->hop; }
static int saf_nhops(const saf_case *c)     { return saf_framesize(c) / c->hop; }
static int saf_nbands(const saf_case *c)    { return c->win + 1; }

/* The oversampled forward path reads a full window starting at the last hop
 * of the frame, so the caller's buffer must be longer than the frame. */
static int saf_inlen(const saf_case *c) { return saf_framesize(c) + c->win; }

static void saf_fd_dims(const saf_case *c, int nch, int *d0, int *d1, int *d2)
{
    if (c->fmt == SAF_STFT_TIME_CH_BANDS) {
        *d0 = saf_nhops(c); *d1 = nch; *d2 = saf_nbands(c);
    } else {
        *d0 = saf_nbands(c); *d1 = nch; *d2 = saf_nhops(c);
    }
}

static int saf_fd_count(const saf_case *c, int nch)
{
    return saf_nhops(c) * nch * saf_nbands(c);
}

static int saf_payload_len(const saf_case *c)
{
    switch (c->op) {
    case SAF_OP_RFFT_FWD:
    case SAF_OP_RFFT_ROUND:
        return c->n;
    case SAF_OP_RFFT_BWD:
        return c->n + 2;
    case SAF_OP_CFFT_FWD:
    case SAF_OP_CFFT_BWD:
    case SAF_OP_CFFT_ROUND:
        return 2 * c->n;
    case SAF_OP_STFT_FWD:
    case SAF_OP_STFT_ROUND:
    case SAF_OP_STFT_STATEFUL:
    case SAF_OP_STFT_FLUSH:
        return c->nchin * saf_inlen(c);
    case SAF_OP_STFT_BWD:
        return 2 * saf_fd_count(c, c->nchout);
    case SAF_OP_STFT_CHCHANGE:
        return 3 * saf_inlen(c);
    case SAF_OP_FFTCONV:
    case SAF_OP_FFTFILT:
        return c->nchin * (c->n + c->aux);
    case SAF_OP_HILBERT:
        return 2 * c->n;
    case SAF_OP_FREQVEC:
    default:
        return 0;
    }
}

static int saf_ncompare(const saf_case *c)
{
    switch (c->op) {
    case SAF_OP_RFFT_FWD:
        return c->n + 2;
    case SAF_OP_RFFT_BWD:
    case SAF_OP_RFFT_ROUND:
        return c->n;
    case SAF_OP_CFFT_FWD:
    case SAF_OP_CFFT_BWD:
    case SAF_OP_CFFT_ROUND:
        return 2 * c->n;
    case SAF_OP_STFT_FWD:
        return 2 * saf_fd_count(c, c->nchin);
    case SAF_OP_STFT_BWD:
    case SAF_OP_STFT_ROUND:
        return c->nchout * saf_framesize(c);
    case SAF_OP_STFT_STATEFUL:
    case SAF_OP_STFT_FLUSH:
        return 2 * c->nchout * saf_framesize(c);
    case SAF_OP_STFT_CHCHANGE:
        return saf_framesize(c);
    case SAF_OP_FFTCONV:
        return c->nchin * (c->n + c->aux - 1);
    case SAF_OP_FFTFILT:
        return c->nchin * c->n;
    case SAF_OP_HILBERT:
        return 2 * c->n;
    case SAF_OP_FREQVEC:
        return c->n / 2 + 1;
    default:
        return 0;
    }
}

/* ------------------------------------------------------------------------- */
/*                        Frequency-domain (de)serialisation                 */
/* ------------------------------------------------------------------------- */

/* The payload is stored as the forward transform leaves it: the nested loops
 * below walk [i][j][k] in the same order for either FD layout. */
static void saf_fd_to_linear(const saf_case *c, float_complex*** fd, int nch,
                             double *out)
{
    int d0, d1, d2, i, j, k, n = 0;
    saf_fd_dims(c, nch, &d0, &d1, &d2);
    for (i = 0; i < d0; ++i)
        for (j = 0; j < d1; ++j)
            for (k = 0; k < d2; ++k) {
                out[2 * n]     = (double)crealf(fd[i][j][k]);
                out[2 * n + 1] = (double)cimagf(fd[i][j][k]);
                ++n;
            }
}

static void saf_fd_from_linear(const saf_case *c, const double *in,
                               float_complex*** fd, int nch)
{
    int d0, d1, d2, i, j, k, n = 0;
    saf_fd_dims(c, nch, &d0, &d1, &d2);
    for (i = 0; i < d0; ++i)
        for (j = 0; j < d1; ++j)
            for (k = 0; k < d2; ++k) {
                fd[i][j][k] = cmplxf((float)in[2 * n], (float)in[2 * n + 1]);
                ++n;
            }
}

/* ------------------------------------------------------------------------- */
/*                            Input generation                              */
/* ------------------------------------------------------------------------- */

static inline double saf_rand(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return ((double)((z ^ (z >> 31)) >> 11) / 9007199254740992.0) * 2.0 - 1.0;
}

static void saf_gen_payload(const saf_case *c, uint64_t seed, double *p)
{
    int len = saf_payload_len(c), i;
    for (i = 0; i < len; ++i) p[i] = saf_rand(&seed);

    /* The real inverse transform is only defined for a Hermitian spectrum:
     * bins 0 and N/2 must be real.  The forward transform always produces
     * them that way, so a stored spectrum for the standalone inverse cases is
     * built the same way instead of leaving an arbitrary imaginary part that
     * different libraries are free to interpret differently. */
    if (c->op == SAF_OP_RFFT_BWD) {
        p[1] = 0.0;
        p[c->n + 1] = 0.0;
    }

    if (c->op == SAF_OP_STFT_BWD) {
        int nH = saf_nhops(c), nB = saf_nbands(c), nch = c->nchout, a;
        if (c->fmt == SAF_STFT_TIME_CH_BANDS) {
            for (a = 0; a < nH * nch; ++a) {
                p[2 * (a * nB) + 1] = 0.0;
                p[2 * (a * nB + nB - 1) + 1] = 0.0;
            }
        } else {
            for (a = 0; a < nch * nH; ++a) {
                p[2 * a + 1] = 0.0;
                p[2 * ((nB - 1) * nch * nH + a) + 1] = 0.0;
            }
        }
    }
}

#endif /* SAF_CASES_H */