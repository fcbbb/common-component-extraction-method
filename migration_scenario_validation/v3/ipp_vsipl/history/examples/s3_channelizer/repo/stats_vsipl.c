/* Output statistics (VSIPL backend). */
#include "channelizer_internal.h"

#include <vsip.h>

#include <math.h>

void wc_fill_report(const float *re, const float *im, int n, wc_report *rep)
{
    vsip_cvview_f *cv;
    vsip_vview_f *mag;
    vsip_index idx = 0;
    float power = 0.0f;
    int i;

    if (!rep) return;
    if (!re || !im || n <= 0) {
        rep->mean_power = 0.0f;
        rep->peak = 0.0f;
        rep->peak_index = 0;
        return;
    }
    cv = vsip_cvcreate_f((vsip_length)n, VSIP_MEM_NONE);
    mag = vsip_vcreate_f((vsip_length)n, VSIP_MEM_NONE);
    if (cv && mag) {
        for (i = 0; i < n; ++i)
            vsip_cvput_f(cv, (vsip_index)i, vsip_cmplx_f(re[i], im[i]));
        vsip_cvmag_f(cv, mag);
        for (i = 0; i < n; ++i)
            power += re[i] * re[i] + im[i] * im[i];
        rep->peak = vsip_vmaxval_f(mag, &idx);
        rep->peak_index = (int)idx;
    }
    rep->mean_power = power / (float)n;
    if (mag) vsip_valldestroy_f(mag);
    if (cv) vsip_cvalldestroy_f(cv);
}