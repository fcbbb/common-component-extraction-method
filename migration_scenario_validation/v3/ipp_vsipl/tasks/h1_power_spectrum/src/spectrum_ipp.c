/* Real power spectrum, Intel IPP backend (migration source). */
#include "power_spectrum.h"

#include <ipp.h>

#include <stdlib.h>

int power_spectrum(const float *input, int nfft, float *power,
                   float *peak, int *peak_bin, float *total_power)
{
    IppsFFTSpec_R_32f *spec = NULL;
    Ipp8u *mem = NULL, *init = NULL, *work = NULL;
    Ipp32f *packed = NULL;
    int order = 0, spec_size = 0, init_size = 0, work_size = 0;
    int nbin, k, rc = -1;
    float p = -1.0f, total = 0.0f;
    int pbin = 0;

    if (!input || !power || nfft < 8 || (nfft & (nfft - 1)) != 0) return -1;
    nbin = nfft / 2 + 1;
    while ((1 << order) < nfft) ++order;

    if (ippsFFTGetSize_R_32f(order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone,
                             &spec_size, &init_size, &work_size) != ippStsNoErr)
        goto done;
    mem = ippsMalloc_8u(spec_size);
    init = ippsMalloc_8u(init_size > 0 ? init_size : 1);
    work = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    packed = (Ipp32f *)ippsMalloc_32f(nfft + 2);
    if (!mem || !init || !work || !packed) goto done;
    if (ippsFFTInit_R_32f(&spec, order, IPP_FFT_NODIV_BY_ANY,
                          ippAlgHintNone, mem, init) != ippStsNoErr)
        goto done;
    if (ippsFFTFwd_RToCCS_32f((Ipp32f *)input, packed, spec, work) != ippStsNoErr)
        goto done;

    for (k = 0; k < nbin; ++k) {
        float re, im;
        if (k == 0 || k == nfft / 2) {
            re = packed[k];
            im = 0.0f;
        } else {
            re = packed[k];
            im = packed[nfft - k];
        }
        power[k] = re * re + im * im;
        total += power[k];
        if (power[k] > p) { p = power[k]; pbin = k; }
    }
    if (peak) *peak = p;
    if (peak_bin) *peak_bin = pbin;
    if (total_power) *total_power = total;
    rc = 0;

done:
    ippsFree(mem);
    ippsFree(init);
    ippsFree(work);
    ippsFree(packed);
    return rc;
}
