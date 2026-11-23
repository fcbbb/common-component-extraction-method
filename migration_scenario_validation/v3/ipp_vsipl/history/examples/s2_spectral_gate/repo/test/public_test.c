#include "spectral_gate.h"

#include <math.h>
#include <stdio.h>

int main(void)
{
    const int n = 16, nbin = n / 2 + 1;
    float input[16] = {0};
    float mag[9];
    unsigned char flags[9];
    sg_config cfg = {n, 3, 2.0f};
    sg_state *st;
    sg_report rep;
    int k;
    const double w = 0.5 * (1.0 - cos(2.0 * 3.14159265358979323846 * 8.0 / 15.0));

    input[8] = 1.0f;
    st = sg_create(&cfg);
    if (!st) return 1;
    if (sg_process(st, input, n, mag, flags, &rep) != 0) return 2;
    for (k = 0; k < nbin; ++k) {
        if (fabs((double)mag[k] - w) > 1e-4) {
            printf("FAIL bin %d mag %g\n", k, mag[k]);
            return 3;
        }
    }
    if (rep.peak_bin < 0 || rep.peak_bin >= nbin) return 4;
    sg_destroy(st);
    puts("public_test: PASS");
    return 0;
}