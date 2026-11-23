/* Spectrum sensing frontend (Intel IPP backend).
 *
 * A cognitive-radio style occupant detector: a Welch periodogram over a
 * capture, then a per-bin energy comparison against a multiple of the mean
 * power.
 *
 *   stage          IPP
 *   window         ippsWinHann_32f over an all-ones vector
 *   frame copy     ippsCopy_32f
 *   windowing      ippsMul_32f
 *   FFT            ippsFFTGetSize_R_32f / ippsFFTInit_R_32f,
 *                  ippsFFTFwd_RToCCS_32f
 *   |X|^2          ippsMagnitude_32fc + ippsSqr_32f on the packed bins
 *   accumulation   ippsAdd_32f, then ippsMulC_32f by 1/nframes
 *   noise floor    ippsMean_32f
 *   peak           ippsMaxIndx_32f
 *   occupancy      plain C (IPP has no float count-in-range)
 *   buffers        ippsMalloc_8u / ippFree
 *
 * The CCS block of a real FFT of length N is N+2 floats long here:
 *
 *   p[0]     = Re X[0]
 *   p[1]     = Im X[0]   (always 0 for a real input)
 *   p[2k]    = Re X[k]   k = 1 .. N/2-1
 *   p[2k+1]  = Im X[k]   k = 1 .. N/2-1
 *   p[N]     = Re X[N/2]
 *   p[N+1]   = 0
 *
 * That is not the compact Perm layout (where Re X[N/2] lives in p[1] and the
 * block is N floats); handing this call an N-float destination writes two
 * floats past the end.  So the interior bins are one ippsMagnitude_32fc over
 * the pairs starting at p[2], and the two real bins are squared by hand.
 */
#include "spectrum_sense.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

struct sens_state {
    int N;
    int step;
    int nbin;
    float thr_scale;

    IppsFFTSpec_R_32f *spec;
    Ipp8u *specbuf;
    Ipp8u *initbuf;
    Ipp8u *workbuf;

    float *win;     /* N, Hann */
    float *frame;   /* N, windowed input */
    float *ccs;     /* N+2, CCS spectrum */
    float *pw;      /* nbin, instantaneous density */
    float *acc;     /* nbin, running sum */
};

static void *sens_alloc(size_t bytes)
{
    if (bytes == 0) bytes = 1;
    return ippsMalloc_8u((int)bytes);
}

sens_state *sens_create(const sens_config *cfg)
{
    sens_state *st;
    Ipp32f *ones;
    int order = 0;
    int sizeSpec = 0, sizeInit = 0, sizeBuffer = 0;
    const int flags = IPP_FFT_NODIV_BY_ANY;
    const IppHintAlgorithm hint = ippAlgHintNone;

    if (!cfg) return 0;

    if (cfg->fft_len < 8 || (cfg->fft_len & (cfg->fft_len - 1)) != 0) return 0;
    if (cfg->frame_step <= 0) return 0;
    if (!(cfg->thr_scale > 0.0f)) return 0;

    st = (sens_state *)calloc(1, sizeof(*st));
    if (!st) return 0;

    st->N = cfg->fft_len;
    st->step = cfg->frame_step;
    st->nbin = st->N / 2 + 1;
    st->thr_scale = cfg->thr_scale;

    while ((1 << order) < st->N) ++order;

    if (ippsFFTGetSize_R_32f(order, flags, hint,
                             &sizeSpec, &sizeInit, &sizeBuffer) != ippStsNoErr) {
        sens_destroy(st);
        return 0;
    }

    st->specbuf = (Ipp8u *)sens_alloc((size_t)sizeSpec);
    if (sizeInit > 0) st->initbuf = (Ipp8u *)sens_alloc((size_t)sizeInit);
    if (sizeBuffer > 0) st->workbuf = (Ipp8u *)sens_alloc((size_t)sizeBuffer);

    st->win = (float *)sens_alloc((size_t)st->N * sizeof(float));
    st->frame = (float *)sens_alloc((size_t)st->N * sizeof(float));
    st->ccs = (float *)sens_alloc((size_t)(st->N + 2) * sizeof(float));
    st->pw = (float *)sens_alloc((size_t)st->nbin * sizeof(float));
    st->acc = (float *)sens_alloc((size_t)st->nbin * sizeof(float));
    ones = (Ipp32f *)sens_alloc((size_t)st->N * sizeof(Ipp32f));

    if (!st->specbuf || !st->win || !st->frame || !st->ccs || !st->pw ||
        !st->acc || !ones) {
        if (ones) ippFree(ones);
        sens_destroy(st);
        return 0;
    }

    if (ippsFFTInit_R_32f(&st->spec, order, flags, hint,
                          st->specbuf, st->initbuf) != ippStsNoErr) {
        ippFree(ones);
        sens_destroy(st);
        return 0;
    }

    ippsSet_32f(1.0f, ones, st->N);
    ippsWinHann_32f(ones, st->win, st->N);
    ippFree(ones);

    return st;
}

void sens_destroy(sens_state *st)
{
    if (!st) return;

    if (st->specbuf) ippFree(st->specbuf);
    if (st->initbuf) ippFree(st->initbuf);
    if (st->workbuf) ippFree(st->workbuf);
    if (st->win) ippFree(st->win);
    if (st->frame) ippFree(st->frame);
    if (st->ccs) ippFree(st->ccs);
    if (st->pw) ippFree(st->pw);
    if (st->acc) ippFree(st->acc);
    free(st);
}

int sens_nbin(const sens_state *st)
{
    return st ? st->nbin : 0;
}

int sens_analyze(sens_state *st, const float *x, int n,
                 float *psd, sens_report *rep)
{
    int nframes;
    int f;
    int occ = 0;
    int k;
    Ipp32f peak = 0.0f;
    int peak_bin = 0;

    if (!st || !x || !psd || !rep) return -1;

    nframes = (n >= st->N) ? 1 + (n - st->N) / st->step : 0;
    if (nframes == 0) return 0;

    memset(st->acc, 0, (size_t)st->nbin * sizeof(float));

    for (f = 0; f < nframes; ++f) {
        ippsCopy_32f(x + (long)f * st->step, st->frame, st->N);
        ippsMul_32f(st->frame, st->win, st->frame, st->N);

        ippsFFTFwd_RToCCS_32f(st->frame, st->ccs, st->spec, st->workbuf);

        st->pw[0] = st->ccs[0] * st->ccs[0];
        st->pw[st->N / 2] = st->ccs[st->N] * st->ccs[st->N];
        if (st->N / 2 > 1) {
            ippsMagnitude_32fc((const Ipp32fc *)(st->ccs + 2), st->pw + 1,
                               st->N / 2 - 1);
            ippsSqr_32f(st->pw + 1, st->pw + 1, st->N / 2 - 1);
        }

        ippsAdd_32f(st->acc, st->pw, st->acc, st->nbin);
    }

    ippsMulC_32f(st->acc, 1.0f / (float)nframes, st->acc, st->nbin);
    memcpy(psd, st->acc, (size_t)st->nbin * sizeof(float));

    ippsMean_32f(psd, st->nbin, &rep->noise_floor, ippAlgHintFast);
    ippsMaxIndx_32f(psd, st->nbin, &peak, &peak_bin);

    rep->peak_power = peak;
    rep->peak_bin = peak_bin;

    {
        const float thr = st->thr_scale * rep->noise_floor;

        for (k = 0; k < st->nbin; ++k) {
            if (psd[k] >= thr) ++occ;
        }
    }

    rep->occ_bins = occ;
    rep->occupancy = (float)occ / (float)st->nbin;

    return nframes;
}