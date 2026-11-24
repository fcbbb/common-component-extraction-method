#include "cross_coherence.h"
#include <math.h>
int cross_coherence(const float *a, const float *b, int nfft,
                    float *mag, float *phase, float *peak, int *bin,
                    float *coherence)
{
    int k, i, nb, pb = 0; float pk = -1, csum = 0, asum = 0, bsum = 0;
    if (!a || !b || !mag || nfft < 8 || (nfft & (nfft - 1))) return -1;
    nb = nfft / 2 + 1;
    for (k = 0; k < nb; ++k) {
        double ar = 0, ai = 0, br = 0, bi = 0;
        for (i = 0; i < nfft; ++i) {
            double w = -2.0 * 3.14159265358979323846 * k * i / nfft;
            ar += a[i] * cos(w); ai += a[i] * sin(w);
            br += b[i] * cos(w); bi += b[i] * sin(w);
        }
        {
            double cr = ar * br + ai * bi, ci = ai * br - ar * bi;
            float m = (float)sqrt(cr * cr + ci * ci);
            float p = (float)atan2(ci, cr);
            float da = (float)(ar * ar + ai * ai), db = (float)(br * br + bi * bi);
            mag[k] = m; phase[k] = p; csum += m; asum += da; bsum += db;
            if (m > pk) { pk = m; pb = k; }
        }
    }
    if (peak) *peak = pk < 0 ? 0 : pk;
    if (bin) *bin = pb;
    if (coherence) {
        float den = sqrtf(asum * bsum);
        *coherence = den > 0 ? csum / den : 0;
    }
    return 0;
}
