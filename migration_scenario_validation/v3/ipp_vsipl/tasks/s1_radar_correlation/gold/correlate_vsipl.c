/* Forward, matched-filter product and inverse (VSIPL backend). */
#include "radar_pipeline_internal.h"

#include <string.h>

int rpc_process(rpc_state *st,
                const float *in_re, const float *in_im, int n,
                float *out_re, float *out_im, rpc_report *rep)
{
    int i, lags;

    if (!st || !in_re || !in_im || !out_re || !out_im) return -1;
    if (n != st->npulse) return -1;
    lags = 2 * n - 1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.time_re, in_re, (size_t)n * sizeof(float));
    memcpy(st->plan.time_im, in_im, (size_t)n * sizeof(float));

    if (rpc_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < st->plan.nfft; ++i) {
        const float ar = st->plan.freq_re[i], ai = st->plan.freq_im[i];
        const float br = st->rep_spec_re[i], bi = st->rep_spec_im[i];
        st->prod_re[i] = ar * br - ai * bi;
        st->prod_im[i] = ar * bi + ai * br;
    }
    memcpy(st->plan.freq_re, st->prod_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.freq_im, st->prod_im,
           (size_t)st->plan.nfft * sizeof(float));

    if (rpc_plan_inverse(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < lags; ++i) {
        out_re[i] = st->plan.time_re[i];
        out_im[i] = st->plan.time_im[i];
    }
    if (rep) rpc_profile_fill(out_re, out_im, lags, rep);
    return 0;
}