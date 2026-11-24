#include "spectral_centroid.h"
#include <ipp.h>
#include <math.h>
#include <stdlib.h>
#ifndef SC_PI
#define SC_PI 3.14159265358979323846
#endif
int spectral_centroid(const float *input, int nfft,
                      float *centroid, float *peak, int *peak_bin,
                      float *total)
{
    IppsFFTSpec_R_32f *spec = NULL;
    Ipp8u *mem = NULL, *init = NULL, *work = NULL;
    Ipp32f *packed = NULL;
    Ipp32f *frame = NULL;
    int order = 0, ss = 0, is = 0, ws = 0, nbin, k, rc = -1;
    float sum = 0.0f, weighted = 0.0f, pk = -1.0f;
    int pb = 0;
    if (!input || !centroid || nfft < 8 || (nfft & (nfft - 1)) != 0)
        return -1;
    nbin = nfft / 2 + 1;
    while ((1 << order) < nfft) ++order;
    if (ippsFFTGetSize_R_32f(order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone,
                             &ss, &is, &ws) != ippStsNoErr) goto done;
    mem = ippsMalloc_8u(ss);
    init = ippsMalloc_8u(is > 0 ? is : 1);
    work = ippsMalloc_8u(ws > 0 ? ws : 1);
    packed = (Ipp32f *)ippsMalloc_32f(nfft + 2);
    frame = (Ipp32f *)ippsMalloc_32f(nfft);
    if (!mem || !init || !work || !packed || !frame) goto done;
    if (ippsFFTInit_R_32f(&spec, order, IPP_FFT_NODIV_BY_ANY,
                          ippAlgHintNone, mem, init) != ippStsNoErr) goto done;
    for (k = 0; k < nfft; ++k) {
        const double w = 0.5 * (1.0 - cos(2.0 * SC_PI * k / (nfft - 1)));
        frame[k] = input[k] * (float)w;
    }
    if (ippsFFTFwd_RToCCS_32f(frame, packed, spec, work) != ippStsNoErr)
        goto done;
    for (k = 0; k < nbin; ++k) {
        float re, im, m;
        if (k == 0 || k == nfft / 2) { re = packed[k]; im = 0.0f; }
        else { re = packed[k]; im = packed[nfft - k]; }
        m = sqrtf(re * re + im * im);
        sum += m; weighted += (float)k * m;
        if (m > pk) { pk = m; pb = k; }
    }
    *centroid = sum > 0.0f ? weighted / sum : 0.0f;
    if (peak) *peak = pk;
    if (peak_bin) *peak_bin = pb;
    if (total) *total = sum;
    rc = 0;
done:
    ippsFree(mem); ippsFree(init); ippsFree(work); ippsFree(packed); ippsFree(frame);
    return rc;
}
