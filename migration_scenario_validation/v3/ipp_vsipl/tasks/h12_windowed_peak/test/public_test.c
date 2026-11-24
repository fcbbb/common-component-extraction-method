#include "window_spectrum.h"
#include <math.h>
#include <stdio.h>
int main(void)
{
    const int n = 16, nbin = 9;
    float x[16], mag[9], peak, total;
    int bin, i;
    for (i = 0; i < n; ++i) x[i] = 1.0f;
    if (window_spectrum(x, n, mag, &peak, &bin, &total) != 0) return 1;
    for (i = 0; i < nbin; ++i)
        if (!(mag[i] >= 0.0f)) return 2;
    if (bin < 0 || bin >= nbin) return 3;
    if (!(peak >= 0.0f) || !(total >= 0.0f)) return 4;
    puts("public_test: PASS");
    return 0;
}
