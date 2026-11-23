/* Output statistics (IPP backend). */
#include "channelizer_internal.h"

#include <math.h>

void wc_fill_report(const float *re, const float *im, int n, wc_report *rep)
{
    float power = 0.0f;
    float peak = 0.0f;
    int peak_index = 0;
    int i;

    if (!rep) return;
    if (!re || !im || n <= 0) {
        rep->mean_power = 0.0f;
        rep->peak = 0.0f;
        rep->peak_index = 0;
        return;
    }
    for (i = 0; i < n; ++i) {
        const float p = re[i] * re[i] + im[i] * im[i];
        const float m = sqrtf(p);
        power += p;
        if (m > peak) {
            peak = m;
            peak_index = i;
        }
    }
    rep->mean_power = power / (float)n;
    rep->peak = peak;
    rep->peak_index = peak_index;
}