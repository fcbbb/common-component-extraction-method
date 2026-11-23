/* Profile metrics for the correlation output (IPP backend). */
#include "radar_pipeline_internal.h"

#include <math.h>

void rpc_profile_fill(const float *re, const float *im, int n, rpc_report *rep)
{
    double energy = 0.0;
    float peak = -1.0f;
    int peak_index = 0;
    int i;

    if (!rep) return;
    for (i = 0; i < n; ++i) {
        const float m2 = re[i] * re[i] + im[i] * im[i];
        const float m = sqrtf(m2);
        energy += (double)m2;
        if (m > peak) {
            peak = m;
            peak_index = i;
        }
    }
    rep->peak = (peak < 0.0f) ? 0.0f : peak;
    rep->peak_index = peak_index;
    rep->energy = (float)energy;
}