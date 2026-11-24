/* Forward transform, spectral product and inverse (VSIPL backend). */
#include "sonar_lag_internal.h"

#include <string.h>

int sl_process(sl_state *st,
               const float *in_re, const float *in_im,
               float *out_re, float *out_im, sl_report *rep)
{
    int i, lags;

    if (!st || !in_re || !in_im || !out_re || !out_im) return -1;
    lags = 2 * st->nref - 1;

    memset(st->plan.time_re, 0, (size_t)st->plan.nfft * sizeof(float));
    memset(st->plan.time_im, 0, (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.time_re, in_re, (size_t)st->nref * sizeof(float));
    memcpy(st->plan.time_im, in_im, (size_t)st->nref * sizeof(float));

    if (sl_plan_forward(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < st->plan.nfft; ++i) {
        const float ar = st->plan.freq_re[i], ai = st->plan.freq_im[i];
        const float br = st->ref_spec_re[i], bi = st->ref_spec_im[i];
        st->prod_re[i] = ar * br - ai * bi;
        st->prod_im[i] = ar * bi + ai * br;
    }
    memcpy(st->plan.freq_re, st->prod_re,
           (size_t)st->plan.nfft * sizeof(float));
    memcpy(st->plan.freq_im, st->prod_im,
           (size_t)st->plan.nfft * sizeof(float));

    if (sl_plan_inverse(&st->plan, st->plan.time_re, st->plan.time_im) != 0)
        return -1;

    for (i = 0; i < lags; ++i) {
        out_re[i] = st->plan.time_re[i];
        out_im[i] = st->plan.time_im[i];
    }
    if (rep) sl_report_fill(out_re, out_im, lags, rep);
    return 0;
}