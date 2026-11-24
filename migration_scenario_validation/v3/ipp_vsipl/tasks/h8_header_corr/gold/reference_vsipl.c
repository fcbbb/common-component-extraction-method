/* Reference spectrum setup (VSIPL backend). */
#include "sonar_lag_internal.h"

#include <string.h>

int sl_set_reference(sl_state *st, const float *re, const float *im)
{
    int i;

    if (!st || !re || !im) return -1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));

    for (i = 0; i < st->nref; ++i) {
        st->plan.time_re[i] = re[st->nref - 1 - i];
        st->plan.time_im[i] = -im[st->nref - 1 - i];
    }
    if (sl_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    memcpy(st->ref_spec_re, st->plan.freq_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->ref_spec_im, st->plan.freq_im,
           (size_t)st->plan.nfft * sizeof(float));
    return 0;
}