/* Analysis windows, Intel IPP backend (migration source).
 *
 * IPP 2021 exposes the windows as "apply to a signal" calls, not as standalone
 * generators:  ippsWinHann_32f(in, out, n), ippsWinHamming_32f(in, out, n),
 * ippsWinBlackman_32f(in, out, n, alpha), ippsWinKaiser_32f(in, out, n, alpha).
 *
 * Two IPP conventions are part of the observable behaviour:
 *   - Hann/Hamming/Blackman are symmetric (2*pi*i/(n-1)) and reject n < 3 with
 *     ippStsSizeErr;
 *   - Blackman's alpha and Kaiser's alpha are IPP-specific parameterisations
 *     (see win_gen.h).
 */
#include "win_gen.h"

#include <ipp.h>

int win_apply(win_type type, float param, const float *in, float *out, int n)
{
    IppStatus st;

    if (!in || !out || n < 1) return -1;

    switch (type) {
    case WIN_HANN:
        if (n < 3) return -1;
        st = ippsWinHann_32f(in, out, n);
        break;
    case WIN_HAMMING:
        if (n < 3) return -1;
        st = ippsWinHamming_32f(in, out, n);
        break;
    case WIN_BLACKMAN:
        if (n < 3) return -1;
        st = ippsWinBlackman_32f(in, out, n, param);
        break;
    case WIN_KAISER:
        if (!(param >= 0.0f)) return -1;
        /* IPP itself rejects beta = param*(n-1)/2 > 38 with
         * ippStsHugeWinErr; the status check below turns that into -1. */
        st = ippsWinKaiser_32f(in, out, n, param);
        break;
    default:
        return -1;
    }
    return (st == ippStsNoErr) ? 0 : -1;
}