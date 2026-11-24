#include "mc_fir.h"
#include <ipp.h>
#include <math.h>
int mc_fir(const float *x0, const float *x1, const float *taps, int n,
           int ntaps, float *y0, float *y1, float *peak, float *energy)
{
    int i, outn = n - ntaps + 1; float pk = -1, en = 0;
    if (!x0 || !x1 || !taps || !y0 || !y1 || n < 1 || ntaps < 1 || ntaps > n) return -1;
    for (i = 0; i < outn; ++i) {
        float a = 0, b = 0;
        ippsDotProd_32f(x0 + i, taps, ntaps, &a);
        ippsDotProd_32f(x1 + i, taps, ntaps, &b);
        y0[i] = a; y1[i] = b; en += a * a + b * b;
        if (sqrtf(a * a + b * b) > pk) pk = sqrtf(a * a + b * b);
    }
    if (peak) *peak = pk < 0 ? 0 : pk; if (energy) *energy = en; return 0;
}
