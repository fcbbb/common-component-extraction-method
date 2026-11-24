/* Reference spectrum setup (IPP backend). */
#include "stream_lag_internal.h"

#include <string.h>

int sc_set_reference(sc_state *st, const float *re, const float *im)
{
    int i;

    if (!st || !re || !im) return -1;
    if (st->pending_n != 0) return -1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));

    /* Store conj(reverse(ref)) so the inverse FFT produces the lag-ordered
     * correlation rather than a forward convolution. */
    for (i = 0; i < st->nref; ++i) {
        st->plan.time_re[i] = re[st->nref - 1 - i];
        st->plan.time_im[i] = -im[st->nref - 1 - i];
    }
    if (sc_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    memcpy(st->ref_spec_re, st->plan.freq_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->ref_spec_im, st->plan.freq_im,
           (size_t)st->plan.nfft * sizeof(float));
    return 0;
}