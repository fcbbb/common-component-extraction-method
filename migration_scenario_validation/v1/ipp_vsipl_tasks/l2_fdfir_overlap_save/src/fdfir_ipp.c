/* Frequency-domain FIR filter, Intel IPP backend (migration source).
 *
 * Overlap-save with an nfft-point complex FFT:
 *   - H = FFT([taps, 0 ... 0]) is computed once in fdfir_create;
 *   - each block copies x[pos-(ntaps-1) .. pos+block-1] into an nfft window,
 *     transforms it, multiplies the spectrum by H and transforms back;
 *   - the last `block` samples of the circular result are the linear
 *     convolution outputs y[pos .. pos+block-1].
 *
 * IPP's division flag is part of the setup: the forward transform is
 * IPP_FFT_NODIV_BY_ANY and the inverse is IPP_FFT_DIV_INV_BY_N, so the
 * round trip is unscaled.  The spectra are complex, so the per-bin product is
 * written out by hand (ippsMul_32f only multiplies reals).
 */
#include "fdfir.h"

#include <ipp.h>

#include <stdlib.h>
#include <string.h>

struct fdfir {
    int ntaps;
    int nfft;
    int block;
    IppsFFTSpec_C_32fc *fwd;
    IppsFFTSpec_C_32fc *inv;
    Ipp8u *fwd_spec, *fwd_init, *fwd_work;
    Ipp8u *inv_spec, *inv_init, *inv_work;
    Ipp32fc *H;    /* spectrum of the zero-padded kernel */
    Ipp32fc *time; /* transform work area                       */
    Ipp32fc *freq; /* spectrum work area                        */
};

static int fft_spec_make(IppsFFTSpec_C_32fc **spec, Ipp8u **mem, Ipp8u **init,
                         Ipp8u **work, int order, int flag)
{
    int spec_size = 0, init_size = 0, work_size = 0;

    if (ippsFFTGetSize_C_32fc(order, flag, ippAlgHintNone,
                              &spec_size, &init_size, &work_size) != ippStsNoErr)
        return -1;
    *mem  = ippsMalloc_8u(spec_size);
    *init = ippsMalloc_8u(init_size > 0 ? init_size : 1);
    *work = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    if (!*mem || !*init || !*work) return -1;
    return (ippsFFTInit_C_32fc(spec, order, flag, ippAlgHintNone, *mem, *init)
            == ippStsNoErr) ? 0 : -1;
}

fdfir *fdfir_create(const float *taps, int ntaps, int nfft)
{
    fdfir *f;
    int order = 0, i;

    if (!taps || ntaps < 1 || nfft < ntaps) return NULL;
    if (nfft < 2 || (nfft & (nfft - 1)) != 0) return NULL;

    f = (fdfir *)calloc(1, sizeof(*f));
    if (!f) return NULL;
    f->ntaps = ntaps;
    f->nfft = nfft;
    f->block = nfft - ntaps + 1;

    while ((1 << order) < nfft) ++order;

    if (fft_spec_make(&f->fwd, &f->fwd_spec, &f->fwd_init, &f->fwd_work,
                      order, IPP_FFT_NODIV_BY_ANY) != 0 ||
        fft_spec_make(&f->inv, &f->inv_spec, &f->inv_init, &f->inv_work,
                      order, IPP_FFT_DIV_INV_BY_N) != 0)
        goto fail;

    f->H    = (Ipp32fc *)ippsMalloc_8u((int)sizeof(Ipp32fc) * nfft);
    f->time = (Ipp32fc *)ippsMalloc_8u((int)sizeof(Ipp32fc) * nfft);
    f->freq = (Ipp32fc *)ippsMalloc_8u((int)sizeof(Ipp32fc) * nfft);
    if (!f->H || !f->time || !f->freq) goto fail;

    for (i = 0; i < nfft; ++i) {
        f->time[i].re = (i < ntaps) ? taps[i] : 0.0f;
        f->time[i].im = 0.0f;
    }
    if (ippsFFTFwd_CToC_32fc(f->time, f->H, f->fwd, f->fwd_work) != ippStsNoErr)
        goto fail;
    return f;

fail:
    fdfir_destroy(f);
    return NULL;
}

int fdfir_apply(fdfir *f, const float *x, int nx, float *y)
{
    int pos, k;

    if (!f || !x || !y || nx < 1) return -1;

    for (pos = 0; pos < nx; pos += f->block) {
        int m = nx - pos;
        if (m > f->block) m = f->block;

        for (k = 0; k < f->nfft; ++k) {
            int idx = pos - (f->ntaps - 1) + k;
            f->time[k].re = (idx >= 0 && idx < nx) ? x[idx] : 0.0f;
            f->time[k].im = 0.0f;
        }

        if (ippsFFTFwd_CToC_32fc(f->time, f->freq, f->fwd, f->fwd_work) != ippStsNoErr)
            return -1;
        for (k = 0; k < f->nfft; ++k) {
            float ar = f->freq[k].re, ai = f->freq[k].im;
            float br = f->H[k].re,    bi = f->H[k].im;
            f->freq[k].re = ar * br - ai * bi;
            f->freq[k].im = ar * bi + ai * br;
        }
        if (ippsFFTInv_CToC_32fc(f->freq, f->time, f->inv, f->inv_work) != ippStsNoErr)
            return -1;

        for (k = 0; k < m; ++k)
            y[pos + k] = f->time[f->ntaps - 1 + k].re;
    }
    return 0;
}

void fdfir_destroy(fdfir *f)
{
    if (!f) return;
    ippsFree(f->H);
    ippsFree(f->time);
    ippsFree(f->freq);
    ippsFree(f->fwd_spec); ippsFree(f->fwd_init); ippsFree(f->fwd_work);
    ippsFree(f->inv_spec); ippsFree(f->inv_init); ippsFree(f->inv_work);
    free(f);
}