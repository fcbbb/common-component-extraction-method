/* Matched-filter replica setup (IPP backend). */
#include "radar_pipeline_internal.h"

#include <string.h>

int rpc_set_replica(rpc_state *st, const float *re, const float *im, int n)
{
    int i;

    if (!st || !re || !im || n != st->npulse) return -1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));
    /* h[t] = conj(replica[n-1-t]); this turns the circular convolution into
     * the lag-ordered correlation contract. */
    for (i = 0; i < n; ++i) {
        st->plan.time_re[i] = re[n - 1 - i];
        st->plan.time_im[i] = -im[n - 1 - i];
    }
    if (rpc_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;
    memcpy(st->rep_spec_re, st->plan.freq_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->rep_spec_im, st->plan.freq_im,
           (size_t)st->plan.nfft * sizeof(float));
    return 0;
}