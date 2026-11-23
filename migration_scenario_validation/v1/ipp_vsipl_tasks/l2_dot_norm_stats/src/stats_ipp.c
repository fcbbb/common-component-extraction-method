/* Stream summary statistics, Intel IPP backend (migration source).
 *
 * ippsDotProd_32f / ippsNorm_L2_32f / ippsMean_32f / ippsStdDev_32f /
 * ippsMax_32f / ippsMin_32f cover the contiguous case in one call each.  IPP
 * has no strided vector primitives, so a decimated window is gathered into
 * two scratch buffers first.
 *
 * Two behaviours of the IPP kernels are part of the contract (both verified
 * against IPP 2021):
 *   - ippsStdDev_32f uses the sample (n-1) denominator; it rejects n == 1
 *     with ippStsSizeErr, and this wrapper defines that case as 0;
 *   - ippsMax_32f / ippsMin_32f ignore NaN samples (SIMD compare semantics),
 *     while mean/norm/dot propagate NaN.
 */
#include "stats.h"

#include <ipp.h>
#include <stddef.h>

static int summary_raw(const Ipp32f *a, const Ipp32f *b, int n,
                       dsp_summary *out)
{
    if (ippsDotProd_32f(a, b, n, &out->dot) != ippStsNoErr) return -1;
    if (ippsNorm_L2_32f(a, n, &out->norm) != ippStsNoErr) return -1;
    if (ippsMean_32f(a, n, &out->mean, ippAlgHintNone) != ippStsNoErr) return -1;
    /* ippsStdDev_32f rejects n == 1 with ippStsSizeErr (and does not touch the
     * destination), so the wrapper defines the single-sample case as 0. */
    if (n > 1) {
        if (ippsStdDev_32f(a, n, &out->stddev, ippAlgHintNone) != ippStsNoErr)
            return -1;
    } else {
        out->stddev = 0.0f;
    }
    if (ippsMax_32f(a, n, &out->vmax) != ippStsNoErr) return -1;
    if (ippsMin_32f(a, n, &out->vmin) != ippStsNoErr) return -1;
    return 0;
}

int dsp_summary_compute(const float *a, const float *b, int n, dsp_summary *out)
{
    if (!a || !b || !out || n < 1) return -1;
    return summary_raw(a, b, n, out);
}

int dsp_summary_compute_strided(const float *a, int astride,
                                const float *b, int bstride,
                                int offset, int n, dsp_summary *out)
{
    Ipp32f *ta, *tb;
    int i, rc;

    if (!a || !b || !out || n < 1) return -1;
    if (astride < 1 || bstride < 1 || offset < 0) return -1;

    if (astride == 1 && bstride == 1 && offset == 0)
        return summary_raw(a, b, n, out);

    /* The buffers are raw pointers, so the size contract in stats.h is the
     * caller's responsibility; the gather below assumes it holds. */
    ta = ippsMalloc_32f(n);
    tb = ippsMalloc_32f(n);
    if (!ta || !tb) {
        ippsFree(ta);
        ippsFree(tb);
        return -1;
    }
    for (i = 0; i < n; ++i) {
        ta[i] = a[offset + (size_t)i * (size_t)astride];
        tb[i] = b[offset + (size_t)i * (size_t)bstride];
    }

    rc = summary_raw(ta, tb, n, out);

    ippsFree(ta);
    ippsFree(tb);
    return rc;
}