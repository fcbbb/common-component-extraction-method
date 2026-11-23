/* Radar pulse compression frontend (Intel IPP backend).
 *
 * The component is a small end-to-end radar chain:
 *
 *   stage          IPP
 *   replica        definition from pulse_comp.h, built in double
 *   FFT            ippsFFTGetSize_R_32f / ippsFFTInit_R_32f (NODIV_BY_ANY),
 *                  ippsFFTFwd_RToCCS_32f, ippsFFTInv_CCSToR_32f
 *   match filter   the precomputed conj(FFT(replica)) in natural complex
 *                  order, ippsMul_32fc
 *   magnitude      ippsAbs_32f on the real inverse transform
 *   integration    ippsAdd_32f, then ippsMulC_32f by 1/(npulses*N)
 *   smoothing      ippsConvolve_32f (direct) with the moving-average taps
 *   noise floor    ippsMean_32f
 *   peak           ippsMaxIndx_32f
 *   detections     plain C (threshold + strict-left local maximum)
 *   buffers        ippsMalloc_8u / ippFree
 *
 * The CCS block of a length-N real FFT is N+2 floats here:
 *   p[0] = Re X[0], p[1] = Im X[0],
 *   p[2k]/p[2k+1] = Re/Im X[k] for k = 1 .. N/2-1,
 *   p[N] = Re X[N/2], p[N+1] = 0.
 * The match filter multiplies natural complex bins, so the code converts the
 * CCS endpoints into Ipp32fc once (replica at create, pulse at run time) and
 * repacks the product before the inverse transform.
 */
#include "pulse_comp.h"

#include <ipp.h>

#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef PC_PI
#define PC_PI 3.14159265358979324
#endif

struct pc_state {
    int N;
    int npulses;
    int L;
    int nbin;
    float threshold_scale;

    IppsFFTSpec_R_32f *spec;
    Ipp8u *specbuf;
    Ipp8u *initbuf;
    Ipp8u *workbuf;

    float *replica;   /* N */
    float *rccs;      /* N+2, FFT(replica) */
    float *ccs;       /* N+2, FFT(pulse) */
    float *yccs;      /* N+2, product before the inverse */
    float *z;         /* N, real correlation */
    float *mag;       /* nbin, |z[0..nbin-1]| */
    float *acc;       /* nbin */
    float *taps;      /* L */
    float *conv;      /* nbin + L - 1 */
    Ipp8u *convbuf;
    int convbufsize;

    Ipp32fc *conj_r;  /* nbin, natural complex conj(R) */
    Ipp32fc *xc;      /* nbin, natural complex X */
    Ipp32fc *yc;      /* nbin, product */
};

static void *pc_alloc(size_t bytes)
{
    if (bytes == 0) bytes = 1;
    return ippsMalloc_8u((int)bytes);
}

static void pc_css_to_complex(const float *ccs, int N, Ipp32fc *out)
{
    const int nbin = N / 2 + 1;
    int k;

    out[0].re = ccs[0];
    out[0].im = 0.0f;
    for (k = 1; k < N / 2; ++k) {
        out[k].re = ccs[2 * k];
        out[k].im = ccs[2 * k + 1];
    }
    out[N / 2].re = ccs[N];
    out[N / 2].im = 0.0f;
    (void)nbin;
}

static void pc_complex_to_ccs(const Ipp32fc *in, int N, float *ccs)
{
    int k;

    ccs[0] = in[0].re;
    ccs[1] = 0.0f;
    for (k = 1; k < N / 2; ++k) {
        ccs[2 * k] = in[k].re;
        ccs[2 * k + 1] = in[k].im;
    }
    ccs[N] = in[N / 2].re;
    ccs[N + 1] = 0.0f;
}

static int pc_valid_config(const pc_config *cfg)
{
    if (!cfg) return 0;
    if (cfg->fft_len < 32) return 0;
    if ((cfg->fft_len & (cfg->fft_len - 1)) != 0) return 0;
    if (cfg->npulses < 1) return 0;
    if (cfg->fir_len < 1 || cfg->fir_len > 15) return 0;
    if ((cfg->fir_len & 1) == 0) return 0;
    if (!(cfg->chirp_rate > 0.0f) || !isfinite(cfg->chirp_rate)) return 0;
    if (!(cfg->threshold_scale > 0.0f) || !isfinite(cfg->threshold_scale)) {
        return 0;
    }
    return 1;
}

pc_state *pc_create(const pc_config *cfg)
{
    pc_state *st;
    int order = 0;
    int sizeSpec = 0, sizeInit = 0, sizeBuffer = 0;
    const int flags = IPP_FFT_NODIV_BY_ANY;
    const IppHintAlgorithm hint = ippAlgHintNone;
    int i;

    if (!pc_valid_config(cfg)) return 0;

    st = (pc_state *)calloc(1, sizeof(*st));
    if (!st) return 0;

    st->N = cfg->fft_len;
    st->npulses = cfg->npulses;
    st->L = cfg->fir_len;
    st->nbin = st->N / 2 + 1;
    st->threshold_scale = cfg->threshold_scale;

    while ((1 << order) < st->N) ++order;

    if (ippsFFTGetSize_R_32f(order, flags, hint,
                             &sizeSpec, &sizeInit, &sizeBuffer) != ippStsNoErr) {
        pc_destroy(st);
        return 0;
    }

    st->specbuf = (Ipp8u *)pc_alloc((size_t)sizeSpec);
    st->initbuf = (Ipp8u *)pc_alloc((size_t)sizeInit);
    st->workbuf = (Ipp8u *)pc_alloc((size_t)sizeBuffer);
    if (!st->specbuf || !st->initbuf || !st->workbuf) {
        pc_destroy(st);
        return 0;
    }
    if (ippsFFTInit_R_32f(&st->spec, order, flags, hint,
                          st->specbuf, st->initbuf) != ippStsNoErr) {
        pc_destroy(st);
        return 0;
    }

    st->replica = (float *)pc_alloc((size_t)st->N * sizeof(float));
    st->rccs = (float *)pc_alloc((size_t)(st->N + 2) * sizeof(float));
    st->ccs = (float *)pc_alloc((size_t)(st->N + 2) * sizeof(float));
    st->yccs = (float *)pc_alloc((size_t)(st->N + 2) * sizeof(float));
    st->z = (float *)pc_alloc((size_t)st->N * sizeof(float));
    st->mag = (float *)pc_alloc((size_t)st->nbin * sizeof(float));
    st->acc = (float *)pc_alloc((size_t)st->nbin * sizeof(float));
    st->taps = (float *)pc_alloc((size_t)st->L * sizeof(float));
    st->conv = (float *)pc_alloc((size_t)(st->nbin + st->L - 1) * sizeof(float));
    st->conj_r = (Ipp32fc *)pc_alloc((size_t)st->nbin * sizeof(Ipp32fc));
    st->xc = (Ipp32fc *)pc_alloc((size_t)st->nbin * sizeof(Ipp32fc));
    st->yc = (Ipp32fc *)pc_alloc((size_t)st->nbin * sizeof(Ipp32fc));
    if (!st->replica || !st->rccs || !st->ccs || !st->yccs || !st->z ||
        !st->mag || !st->acc || !st->taps || !st->conv || !st->conj_r ||
        !st->xc || !st->yc) {
        pc_destroy(st);
        return 0;
    }

    if (ippsConvolveGetBufferSize(st->nbin, st->L, ipp32f, ippAlgDirect,
                                  &st->convbufsize) != ippStsNoErr) {
        pc_destroy(st);
        return 0;
    }
    st->convbuf = (Ipp8u *)pc_alloc((size_t)st->convbufsize);
    if (!st->convbuf) {
        pc_destroy(st);
        return 0;
    }

    /* Replica waveform, double arithmetic so both backends build the same
     * float samples. */
    for (i = 0; i < st->N; ++i) {
        const double w = 0.5 * (1.0 - cos(2.0 * PC_PI * (double)i /
                                          (double)(st->N - 1)));
        const double u = (double)i - 0.5 * (double)(st->N - 1);
        const double ph = PC_PI * (double)cfg->chirp_rate * u * u /
                          (double)st->N;

        st->replica[i] = (float)(w * cos(ph));
    }

    if (ippsFFTFwd_RToCCS_32f(st->replica, st->rccs, st->spec,
                              st->workbuf) != ippStsNoErr) {
        pc_destroy(st);
        return 0;
    }
    pc_css_to_complex(st->rccs, st->N, st->conj_r);
    for (i = 0; i < st->nbin; ++i) {
        st->conj_r[i].im = -st->conj_r[i].im;
    }

    for (i = 0; i < st->L; ++i) {
        st->taps[i] = 1.0f / (float)st->L;
    }

    return st;
}

void pc_destroy(pc_state *st)
{
    if (!st) return;

    if (st->replica) ippFree(st->replica);
    if (st->rccs) ippFree(st->rccs);
    if (st->ccs) ippFree(st->ccs);
    if (st->yccs) ippFree(st->yccs);
    if (st->z) ippFree(st->z);
    if (st->mag) ippFree(st->mag);
    if (st->acc) ippFree(st->acc);
    if (st->taps) ippFree(st->taps);
    if (st->conv) ippFree(st->conv);
    if (st->conj_r) ippFree(st->conj_r);
    if (st->xc) ippFree(st->xc);
    if (st->yc) ippFree(st->yc);
    if (st->convbuf) ippFree(st->convbuf);
    if (st->specbuf) ippFree(st->specbuf);
    if (st->initbuf) ippFree(st->initbuf);
    if (st->workbuf) ippFree(st->workbuf);
    free(st);
}

int pc_nrange(const pc_state *st)
{
    return st ? st->nbin : 0;
}

int pc_process(pc_state *st, const float *signal, int n,
               float *profile, pc_report *rep)
{
    int p, k;
    float floor_val = 0.0f;
    float peak_val = 0.0f;
    int peak_bin = 0;
    int count = 0, first = -1, last = -1;
    float thr;

    if (!st || !signal || !profile || !rep) return -1;
    if (n != st->npulses * st->N) return -1;

    ippsZero_32f(st->acc, st->nbin);

    for (p = 0; p < st->npulses; ++p) {
        const float *pulse = signal + (size_t)p * (size_t)st->N;

        if (ippsFFTFwd_RToCCS_32f(pulse, st->ccs, st->spec,
                                  st->workbuf) != ippStsNoErr) {
            return -1;
        }
        pc_css_to_complex(st->ccs, st->N, st->xc);
        ippsMul_32fc(st->xc, st->conj_r, st->yc, st->nbin);
        pc_complex_to_ccs(st->yc, st->N, st->yccs);
        if (ippsFFTInv_CCSToR_32f(st->yccs, st->z, st->spec,
                                  st->workbuf) != ippStsNoErr) {
            return -1;
        }
        ippsAbs_32f(st->z, st->mag, st->nbin);
        ippsAdd_32f(st->acc, st->mag, st->acc, st->nbin);
    }

    ippsMulC_32f(st->acc, 1.0f / ((float)st->npulses * (float)st->N),
                 st->acc, st->nbin);

    if (ippsConvolve_32f(st->acc, st->nbin, st->taps, st->L, st->conv,
                         ippAlgDirect, st->convbuf) != ippStsNoErr) {
        return -1;
    }
    memcpy(profile, st->conv, (size_t)st->nbin * sizeof(float));

    ippsMean_32f(profile, st->nbin, &floor_val, ippAlgHintNone);
    ippsMaxIndx_32f(profile, st->nbin, &peak_val, &peak_bin);

    thr = st->threshold_scale * floor_val;

    for (k = 0; k < st->nbin; ++k) {
        const int left_ok = (k == 0) || (profile[k] > profile[k - 1]);
        const int right_ok = (k == st->nbin - 1) || (profile[k] >= profile[k + 1]);

        if (profile[k] >= thr && left_ok && right_ok) {
            if (count == 0) first = k;
            last = k;
            ++count;
        }
    }

    rep->noise_floor = floor_val;
    rep->threshold = thr;
    rep->peak_value = peak_val;
    rep->peak_bin = peak_bin;
    rep->n_detections = count;
    rep->first_bin = first;
    rep->last_bin = last;

    return st->npulses;
}