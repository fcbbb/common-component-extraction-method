#include "norm_corr.h"
#include <ipp.h>
#include <math.h>
int norm_corr(const float *x, const float *ref, int n,
              int lag_min, int lag_max, float *out,
              float *peak, int *peak_lag)
{
    float ex = 0.0f, er = 0.0f, pk = -1.0f;
    int i, lag, pl = lag_min;
    if (!x || !ref || !out || n < 1 || lag_min > lag_max ||
        lag_min <= -n || lag_max >= n) return -1;
    for (i = 0; i < n; ++i) { ex += x[i] * x[i]; er += ref[i] * ref[i]; }
    for (lag = lag_min; lag <= lag_max; ++lag) {
        int j0 = lag < 0 ? -lag : 0;
        int j1 = lag > 0 ? n - lag : n;
        int len = j1 - j0;
        float dot = 0.0f, den;
        if (len <= 0) { out[lag - lag_min] = 0.0f; continue; }
        ippsDotProd_32f(x + j0, ref + j0 + lag, len, &dot);
        den = sqrtf(ex * er);
        out[lag - lag_min] = den > 0.0f ? dot / den : 0.0f;
        if (out[lag - lag_min] > pk) { pk = out[lag - lag_min]; pl = lag; }
    }
    if (peak) *peak = pk < 0.0f ? 0.0f : pk;
    if (peak_lag) *peak_lag = pl;
    return 0;
}
