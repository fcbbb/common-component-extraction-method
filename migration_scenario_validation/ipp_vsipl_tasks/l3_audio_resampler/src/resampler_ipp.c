/* Streaming rational resampler + output spectrum (Intel IPP backend).
 *
 *   stage             IPP
 *   prototype filter  plain C windowed sinc (see include/resampler.h)
 *   push history      memmove
 *   branch filter     ippsDotProd_32f, one call per output sample
 *   frame copy        ippsCopy_32f
 *   FFT               ippsFFTGetSize_R_32f / ippsFFTInit_R_32f,
 *                     ippsFFTFwd_RToCCS_32f
 *   |X|^2             ippsMagnitude_32fc + ippsSqr_32f on the packed bins
 *   accumulation      ippsAdd_32f, then ippsMulC_32f by 1/nframes
 *   peak              ippsMaxIndx_32f
 *   total             ippsSum_32f
 *   centroid          ippsDotProd_32f with a ramp
 *   buffers           ippsMalloc_8u / ippFree
 *
 * Two details of the contract drive the code:
 *
 *  - each branch is stored time-reversed, so that one ascending dot product
 *    over the history window is y[m] = sum_k hp[p][k] * x[i-k];
 *  - the output index m maps to the input index i = (m*down)/up with phase
 *    p = (m*down)%up, so the whole stream is a function of the total input
 *    consumed, and the state only has to remember the last ntaps-1 samples
 *    plus m itself.
 *
 * The CCS block of a length-N real FFT is N+2 floats: p[0] = Re X[0],
 * p[1] = Im X[0], p[2k]/p[2k+1] = Re/Im X[k] for k = 1..N/2-1, and
 * Re X[N/2] at p[N].  Writing N floats into it is a two-float overflow and
 * puts the Nyquist bin in the wrong slot.
 */
#include "resampler.h"

#include <ipp.h>

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define RES_PI 3.14159265358979323846

struct res_state {
    int up;
    int down;
    int ntaps;
    int fft_len;
    int nbin;
    int L;

    float *hpr;     /* up*ntaps, branch-major, time-reversed */

    float *hist;    /* input samples [base, total) */
    int hcap;
    long base;
    long total;
    long mnext;

    /* spectrum */
    IppsFFTSpec_R_32f *spec;
    Ipp8u *specbuf;
    Ipp8u *initbuf;
    Ipp8u *workbuf;
    float *frame;
    float *ccs;     /* fft_len + 2 */
    float *pw;
    float *acc;
    float *ramp;
};

static void *res_alloc(size_t bytes)
{
    if (bytes == 0) bytes = 1;
    return ippsMalloc_8u((int)bytes);
}

static int res_is_pow2(int v)
{
    return v >= 8 && (v & (v - 1)) == 0;
}

/* Builds the normalized polyphase branches, stored time-reversed. */
static int res_build_taps(res_state *st, float cutoff)
{
    const int L = st->up * st->ntaps;
    double *h;
    int p, k, j;
    const double c = 0.5 * (double)(L - 1);
    const double fc = (double)cutoff;

    h = (double *)calloc((size_t)L, sizeof(double));
    if (!h) return -1;

    for (j = 0; j < L; ++j) {
        const double d = (double)j - c;
        const double u = 2.0 * fc * d;
        const double s = (d == 0.0) ? 1.0 : sin(RES_PI * u) / (RES_PI * u);
        const double w = 0.5 * (1.0 - cos(2.0 * RES_PI * (double)j /
                                          (double)(L - 1)));

        h[j] = 2.0 * fc * s * w;
    }

    for (p = 0; p < st->up; ++p) {
        double sum = 0.0;

        for (k = 0; k < st->ntaps; ++k) sum += h[p + k * st->up];
        if (sum == 0.0) {
            free(h);
            return -1;
        }
        /* reversed: hpr[p][k] = hp[p][ntaps-1-k] */
        for (k = 0; k < st->ntaps; ++k) {
            st->hpr[p * st->ntaps + k] =
                (float)(h[p + (st->ntaps - 1 - k) * st->up] / sum);
        }
    }

    free(h);
    return 0;
}

res_state *res_create(const res_config *cfg)
{
    res_state *st;
    int order = 0;              /* log2(fft_len) for the IPP spec */

    if (!cfg) return 0;
    if (cfg->up < 1 || cfg->up > 256) return 0;
    if (cfg->down < 1 || cfg->down > 256) return 0;
    if (cfg->ntaps < 2) return 0;
    if (!(cfg->cutoff > 0.0f && cfg->cutoff < 0.5f)) return 0;
    if (!res_is_pow2(cfg->fft_len)) return 0;

    st = (res_state *)calloc(1, sizeof(*st));
    if (!st) return 0;

    st->up = cfg->up;
    st->down = cfg->down;
    st->ntaps = cfg->ntaps;
    st->fft_len = cfg->fft_len;
    st->nbin = st->fft_len / 2 + 1;
    st->L = st->up * st->ntaps;

    st->hpr = (float *)res_alloc((size_t)st->L * sizeof(float));
    if (!st->hpr || res_build_taps(st, cfg->cutoff) != 0) {
        res_destroy(st);
        return 0;
    }

    /* The history grows with the input, so it lives in ordinary heap memory:
     * ippMalloc pointers cannot be handed to realloc. */
    st->hcap = st->ntaps * 2;
    st->hist = (float *)malloc((size_t)st->hcap * sizeof(float));
    if (!st->hist) {
        res_destroy(st);
        return 0;
    }

    while ((1 << order) < st->fft_len) ++order;

    {
        int sizeSpec = 0, sizeInit = 0, sizeBuffer = 0;

        if (ippsFFTGetSize_R_32f(order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone,
                                 &sizeSpec, &sizeInit, &sizeBuffer) !=
            ippStsNoErr) {
            res_destroy(st);
            return 0;
        }
        st->specbuf = (Ipp8u *)res_alloc((size_t)sizeSpec);
        if (sizeInit > 0) st->initbuf = (Ipp8u *)res_alloc((size_t)sizeInit);
        if (sizeBuffer > 0) st->workbuf = (Ipp8u *)res_alloc((size_t)sizeBuffer);
    }

    st->frame = (float *)res_alloc((size_t)st->fft_len * sizeof(float));
    st->ccs = (float *)res_alloc((size_t)(st->fft_len + 2) * sizeof(float));
    st->pw = (float *)res_alloc((size_t)st->nbin * sizeof(float));
    st->acc = (float *)res_alloc((size_t)st->nbin * sizeof(float));
    st->ramp = (float *)res_alloc((size_t)st->nbin * sizeof(float));

    if (!st->specbuf || !st->frame || !st->ccs || !st->pw || !st->acc ||
        !st->ramp) {
        res_destroy(st);
        return 0;
    }

    if (ippsFFTInit_R_32f(&st->spec, order, IPP_FFT_NODIV_BY_ANY,
                          ippAlgHintNone, st->specbuf, st->initbuf) !=
        ippStsNoErr) {
        res_destroy(st);
        return 0;
    }

    {
        int q;

        for (q = 0; q < st->nbin; ++q) st->ramp[q] = (float)q;
    }

    return st;
}

void res_destroy(res_state *st)
{
    if (!st) return;

    if (st->specbuf) ippFree(st->specbuf);
    if (st->initbuf) ippFree(st->initbuf);
    if (st->workbuf) ippFree(st->workbuf);
    if (st->frame) ippFree(st->frame);
    if (st->ccs) ippFree(st->ccs);
    if (st->pw) ippFree(st->pw);
    if (st->acc) ippFree(st->acc);
    if (st->ramp) ippFree(st->ramp);
    if (st->hpr) ippFree(st->hpr);
    if (st->hist) free(st->hist);
    free(st);
}

int res_max_out(const res_state *st, int nin)
{
    long long bound;

    if (!st || nin <= 0) return 0;

    bound = ((long long)nin * st->up) / st->down + 2;
    if (bound > 0x7fffffffLL) bound = 0x7fffffffLL;
    return (int)bound;
}

/* Drops history samples that no future output can reach. */
static void res_compact(res_state *st)
{
    long keep_from = (st->mnext * st->down) / st->up - (st->ntaps - 1);

    if (keep_from < st->base) keep_from = st->base;
    /* A decimating ratio can push the next output past the samples we hold. */
    if (keep_from > st->total) keep_from = st->total;
    if (keep_from <= st->base) return;

    memmove(st->hist, st->hist + (size_t)(keep_from - st->base),
            (size_t)(st->total - keep_from) * sizeof(float));
    st->base = keep_from;
}

static int res_reserve(res_state *st, long need)
{
    float *n;

    if (need <= st->hcap) return 0;

    n = (float *)realloc(st->hist, (size_t)need * sizeof(float));
    if (!n) return -1;
    st->hist = n;
    st->hcap = (int)need;
    return 0;
}

int res_process(res_state *st, const float *in, int nin, float *out, int cap)
{
    int nout = 0;
    long hlen;

    if (!st || !out) return -1;
    if (nin < 0) return -1;
    if (nin == 0) return 0;
    if (!in) return -1;
    if (cap < res_max_out(st, nin)) return -1;

    res_compact(st);
    hlen = st->total - st->base;

    if (res_reserve(st, hlen + nin) != 0) return -1;
    memcpy(st->hist + hlen, in, (size_t)nin * sizeof(float));
    st->total += nin;

    for (;;) {
        const long num = st->mnext * st->down;
        const long i = num / st->up;
        const int p = (int)(num % st->up);
        Ipp32f acc = 0.0f;

        if (i < st->ntaps - 1) {
            /* Before the first complete window: nothing to emit. */
            ++st->mnext;
            continue;
        }
        if (i > st->total - 1) break;

        ippsDotProd_32f(st->hpr + (size_t)p * st->ntaps,
                        st->hist + (size_t)(i - (st->ntaps - 1) - st->base),
                        st->ntaps, &acc);
        out[nout++] = acc;
        ++st->mnext;
    }

    return nout;
}

int res_spectrum(res_state *st, const float *x, int n, float *mag2,
                 res_report *rep)
{
    int nframes;
    int f;
    Ipp32f peak = 0.0f;
    int peak_bin = 0;
    Ipp32f total = 0.0f;
    Ipp32f weighted = 0.0f;

    if (!st || !mag2 || !rep) return -1;
    if (!x) return -1;

    nframes = (n >= st->fft_len) ? 1 + (n - st->fft_len) / st->fft_len : 0;
    if (nframes == 0) return 0;

    memset(st->acc, 0, (size_t)st->nbin * sizeof(float));

    for (f = 0; f < nframes; ++f) {
        ippsCopy_32f(x + (long)f * st->fft_len, st->frame, st->fft_len);
        ippsFFTFwd_RToCCS_32f(st->frame, st->ccs, st->spec, st->workbuf);

        st->pw[0] = st->ccs[0] * st->ccs[0];
        st->pw[st->fft_len / 2] = st->ccs[st->fft_len] * st->ccs[st->fft_len];
        if (st->fft_len / 2 > 1) {
            ippsMagnitude_32fc((const Ipp32fc *)(st->ccs + 2), st->pw + 1,
                               st->fft_len / 2 - 1);
            ippsSqr_32f(st->pw + 1, st->pw + 1, st->fft_len / 2 - 1);
        }

        ippsAdd_32f(st->acc, st->pw, st->acc, st->nbin);
    }

    ippsMulC_32f(st->acc, 1.0f / (float)nframes, st->acc, st->nbin);
    memcpy(mag2, st->acc, (size_t)st->nbin * sizeof(float));

    ippsMaxIndx_32f(mag2, st->nbin, &peak, &peak_bin);
    /* ippAlgHintFast vectorises the accumulation and splits the tail by
     * buffer alignment, which made the sum differ by ~30 ulp between the
     * generator and the replay.  ippAlgHintNone keeps it sequential, so the
     * stored total is reproducible. */
    ippsSum_32f(mag2, st->nbin, &total, ippAlgHintNone);
    ippsDotProd_32f(st->ramp, mag2, st->nbin, &weighted);

    rep->power = peak;
    rep->power_bin = peak_bin;
    rep->total = total;
    rep->centroid = (total > 0.0f) ? weighted / total : 0.0f;
    rep->nbins = st->nbin;

    return nframes;
}