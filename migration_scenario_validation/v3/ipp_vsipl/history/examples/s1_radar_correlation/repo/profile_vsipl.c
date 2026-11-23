/* Profile metrics for the correlation output (VSIPL backend). */
#include "radar_pipeline_internal.h"

#include <vsip.h>

#include <math.h>

void rpc_profile_fill(const float *re, const float *im, int n, rpc_report *rep)
{
    vsip_cvview_f *cv;
    vsip_vview_f *mag;
    float peak = 0.0f;
    float energy = 0.0f;
    vsip_index idx = 0;
    int i;

    if (!rep || n <= 0) return;

    cv = vsip_cvcreate_f((vsip_length)n, VSIP_MEM_NONE);
    mag = vsip_vcreate_f((vsip_length)n, VSIP_MEM_NONE);
    if (!cv || !mag) {
        if (cv) vsip_cvalldestroy_f(cv);
        if (mag) vsip_valldestroy_f(mag);
        return;
    }

    for (i = 0; i < n; ++i)
        vsip_cvput_f(cv, (vsip_index)i, vsip_cmplx_f(re[i], im[i]));
    vsip_cvmag_f(cv, mag);
    peak = vsip_vmaxval_f(mag, &idx);
    for (i = 0; i < n; ++i)
        energy += re[i] * re[i] + im[i] * im[i];

    rep->peak = peak;
    rep->peak_index = (int)idx;
    rep->energy = energy;

    vsip_valldestroy_f(mag);
    vsip_cvalldestroy_f(cv);
}