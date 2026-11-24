#include "cross_coherence.h"
#include <ipp.h>
#include <math.h>
#include <stdlib.h>
int cross_coherence(const float *a, const float *b, int nfft,
                    float *mag, float *phase, float *peak, int *bin,
                    float *coherence)
{
    IppsFFTSpec_R_32f *sa = NULL, *sb = NULL; Ipp8u *ma = NULL, *ia = NULL, *wa = NULL, *mb = NULL, *ib = NULL, *wb = NULL;
    Ipp32f *pa = NULL, *pb = NULL; int order = 0, ssz = 0, isz = 0, wsz = 0, nb, k, rc = -1; float pk = -1, csum = 0, asum = 0, bsum = 0; int pbin = 0;
    if (!a || !b || !mag || nfft < 8 || (nfft & (nfft - 1))) return -1;
    nb = nfft / 2 + 1; while ((1 << order) < nfft) ++order;
    if (ippsFFTGetSize_R_32f(order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone, &ssz, &isz, &wsz) != ippStsNoErr) goto done;
    ma = ippsMalloc_8u(ssz); ia = ippsMalloc_8u(isz ? isz : 1); wa = ippsMalloc_8u(wsz ? wsz : 1);
    mb = ippsMalloc_8u(ssz); ib = ippsMalloc_8u(isz ? isz : 1); wb = ippsMalloc_8u(wsz ? wsz : 1);
    pa = ippsMalloc_32f(nfft + 2); pb = ippsMalloc_32f(nfft + 2);
    if (!ma || !ia || !wa || !mb || !ib || !wb || !pa || !pb) goto done;
    if (ippsFFTInit_R_32f(&sa, order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone, ma, ia) != ippStsNoErr) goto done;
    if (ippsFFTInit_R_32f(&sb, order, IPP_FFT_NODIV_BY_ANY, ippAlgHintNone, mb, ib) != ippStsNoErr) goto done;
    if (ippsFFTFwd_RToCCS_32f((Ipp32f *)a, pa, sa, wa) != ippStsNoErr) goto done;
    if (ippsFFTFwd_RToCCS_32f((Ipp32f *)b, pb, sb, wb) != ippStsNoErr) goto done;
    for (k = 0; k < nb; ++k) {
        float ar = pa[k], ai = (k == 0 || k == nfft / 2) ? 0 : pa[nfft - k];
        float br = pb[k], bi = (k == 0 || k == nfft / 2) ? 0 : pb[nfft - k];
        float cr = ar * br + ai * bi, ci = ai * br - ar * bi;
        float m = sqrtf(cr * cr + ci * ci);
        mag[k] = m; phase[k] = atan2f(ci, cr); csum += m;
        asum += ar * ar + ai * ai; bsum += br * br + bi * bi;
        if (m > pk) { pk = m; pbin = k; }
    }
    if (peak) *peak = pk; if (bin) *bin = pbin;
    if (coherence) { float den = sqrtf(asum * bsum); *coherence = den > 0 ? csum / den : 0; }
    rc = 0;
done: ippsFree(ma); ippsFree(ia); ippsFree(wa); ippsFree(mb); ippsFree(ib); ippsFree(wb); ippsFree(pa); ippsFree(pb); return rc;
}
