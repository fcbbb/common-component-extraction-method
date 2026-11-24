#include "power_spectrum.h"

#include <math.h>
#include <stdio.h>

int main(void)
{
    const int n = 16, nbin = n / 2 + 1;
    float input[16] = {0}, power[9], peak, total;
    int peak_bin, k;

    input[0] = 1.0f;
    if (power_spectrum(input, n, power, &peak, &peak_bin, &total) != 0) return 1;
    for (k = 0; k < nbin; ++k)
        if (fabs((double)power[k] - 1.0) > 1e-4) return 2;
    if (peak_bin != 0 || fabs((double)total - nbin) > 1e-4) return 3;
    puts("public_test: PASS");
    return 0;
}
