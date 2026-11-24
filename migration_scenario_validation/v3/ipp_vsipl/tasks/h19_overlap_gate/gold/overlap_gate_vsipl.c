#include "overlap_gate.h"
#include <math.h>
int overlap_gate(const float *input, int nfft, float alpha,
                 float *mag, unsigned char *flags, float *peak,
                 int *peak_bin, float *noise)
{
    int k, i, nb, pb = 0; float pk = -1, sum = 0;
    if (!input || !mag || !flags || nfft < 8 || (nfft & (nfft - 1)) || !(alpha > 0)) return -1;
    nb = nfft / 2 + 1;
    for (k = 0; k < nb; ++k) {
        double re = 0, im = 0;
        for (i = 0; i < nfft; ++i) {
            double w = 0.5 * (1 - cos(2 * 3.14159265358979323846 * i / (nfft - 1)));
            double a = -2 * 3.14159265358979323846 * k * i / nfft;
            re += input[i] * w * cos(a); im += input[i] * w * sin(a);
        }
        mag[k] = (float)sqrt(re * re + im * im); sum += mag[k];
        if (mag[k] > pk) { pk = mag[k]; pb = k; }
    }
    for (k = 0; k < nb; ++k) flags[k] = mag[k] > alpha * (sum / nb) ? 1 : 0;
    if (peak) *peak = pk < 0 ? 0 : pk; if (peak_bin) *peak_bin = pb;
    if (noise) *noise = sum / nb; return 0;
}
