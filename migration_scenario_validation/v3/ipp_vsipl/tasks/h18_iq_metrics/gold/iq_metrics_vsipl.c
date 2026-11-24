#include "iq_metrics.h"
#include <math.h>
int iq_metrics(const float *i, const float *q, int n,
               float *gain, float *phase, float *peak, float *energy)
{
    double ai2 = 0, aq2 = 0, cross = 0; float pk = -1, en = 0; int k;
    if (!i || !q || n < 1) return -1;
    for (k = 0; k < n; ++k) {
        const float m2 = i[k] * i[k] + q[k] * q[k];
        ai2 += i[k] * i[k]; aq2 += q[k] * q[k]; cross += i[k] * q[k];
        en += m2; if (sqrtf(m2) > pk) pk = sqrtf(m2);
    }
    if (gain) *gain = ai2 > 0 ? (float)sqrt(aq2 / ai2) : 0;
    if (phase) *phase = (ai2 > 0 && aq2 > 0) ? (float)asin(cross / sqrt(ai2 * aq2)) : 0;
    if (peak) *peak = pk < 0 ? 0 : pk;
    if (energy) *energy = en;
    return 0;
}
