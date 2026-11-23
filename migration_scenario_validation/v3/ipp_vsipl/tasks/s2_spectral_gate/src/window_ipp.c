/* Symmetric Hann analysis window (IPP backend). */
#include "spectral_gate_internal.h"

#include <math.h>

#ifndef SG_PI
#define SG_PI 3.14159265358979323846
#endif

void sg_fill_window(float *window, int n)
{
    int i;
    if (!window || n < 2) return;
    for (i = 0; i < n; ++i)
        window[i] = (float)(0.5 * (1.0 - cos(2.0 * SG_PI * (double)i /
                                             (double)(n - 1))));
}