/* dB magnitude kernel, Intel IPP backend (migration source).
 *
 *   ippsMagnitude_32f       split complex -> magnitude
 *   ippsThreshold_LTVal_32f clamp to the floor (protects the log)
 *   ippsLog10_32f_A21       log10 (ippvm, low-accuracy variant)
 *   ippsMulC_32f            20 * log10
 *   ippsAddC_32f            + offset
 */
#include "dbmag.h"

#include <ipp.h>
#include <ippvm.h>

int vec_db_mag(const float *re, const float *im, int n,
               float floor_mag, float offset, float *out)
{
    Ipp32f *mag;

    if (!re || !im || !out || n < 1) return -1;
    if (!(floor_mag > 0.0f)) return -1;

    mag = ippsMalloc_32f(n);
    if (!mag) return -1;

    if (ippsMagnitude_32f(re, im, mag, n) != ippStsNoErr) goto fail;
    if (ippsThreshold_LTVal_32f(mag, mag, n, floor_mag, floor_mag) != ippStsNoErr) goto fail;
    if (ippsLog10_32f_A21(mag, out, n) != ippStsNoErr) goto fail;
    if (ippsMulC_32f(out, 20.0f, out, n) != ippStsNoErr) goto fail;
    if (ippsAddC_32f(out, offset, out, n) != ippStsNoErr) goto fail;

    ippsFree(mag);
    return 0;

fail:
    ippsFree(mag);
    return -1;
}