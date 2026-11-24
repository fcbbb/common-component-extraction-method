#include "iq_metrics.h"
#include <ipp.h>
#include <math.h>
int iq_metrics(const float *i, const float *q, int n,
               float *gain, float *phase, float *peak, float *energy)
{
    float ai2, aq2, cross, pk, en; int k;
    if (!i || !q || n < 1) return -1;
    ippsDotProd_32f(i, i, n, &ai2); ippsDotProd_32f(q, q, n, &aq2);
    ippsDotProd_32f(i, q, n, &cross);
    pk = -1; en = 0;
    for (k = 0; k < n; ++k) { float m2 = i[k]*i[k]+q[k]*q[k]; en += m2; if (sqrtf(m2) > pk) pk = sqrtf(m2); }
    if (gain) *gain = ai2 > 0 ? sqrtf(aq2 / ai2) : 0;
    if (phase) *phase = (ai2 > 0 && aq2 > 0) ? asinf(cross / sqrtf(ai2 * aq2)) : 0;
    if (peak) *peak = pk < 0 ? 0 : pk;
    if (energy) *energy = en;
    return 0;
}
