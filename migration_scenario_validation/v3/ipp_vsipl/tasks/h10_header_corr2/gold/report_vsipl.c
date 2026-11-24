/* Lag-profile metrics (VSIPL backend). */
#include "sonar_lag_internal.h"

#include <vsip.h>

#include <math.h>

void sl_report_fill(const float *re, const float *im, int n, sl_report *rep)
{
    vsip_cvview_f *cv = NULL;
    vsip_vview_f *mag = NULL;
    vsip_index idx = 0;
    double energy = 0.0;
    int i;

    if (!rep) return;
    if (!re || !im || n <= 0) {
        rep->peak = 0.0f;
        rep->peak_index = 0;
        rep->energy = 0.0f;
        return;
    }

    cv = vsip_cvcreate_f((vsip_length)n, VSIP_MEM_NONE);
    mag = vsip_vcreate_f((vsip_length)n, VSIP_MEM_NONE);
    if (cv && mag) {
        for (i = 0; i < n; ++i)
            vsip_cvput_f(cv, (vsip_index)i, vsip_cmplx_f(re[i], im[i]));
        vsip_cvmag_f(cv, mag);
        for (i = 0; i < n; ++i) {
            const float m2 = re[i] * re[i] + im[i] * im[i];
            energy += (double)m2;
        }
        rep->peak = vsip_vmaxval_f(mag, &idx);
        rep->peak_index = (int)idx;
        rep->energy = (float)energy;
    } else {
        rep->peak = 0.0f;
        rep->peak_index = 0;
        rep->energy = 0.0f;
        for (i = 0; i < n; ++i) {
            const float m2 = re[i] * re[i] + im[i] * im[i];
            const float m = sqrtf(m2);
            energy += (double)m2;
            if (m > rep->peak) {
                rep->peak = m;
                rep->peak_index = i;
            }
        }
        rep->energy = (float)energy;
    }
    if (mag) vsip_valldestroy_f(mag);
    if (cv) vsip_cvalldestroy_f(cv);
}