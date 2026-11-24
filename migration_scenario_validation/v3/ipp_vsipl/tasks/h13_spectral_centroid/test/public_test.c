#include "spectral_centroid.h"
#include <stdio.h>
int main(void) {
    float x[16], c, p, t; int b, i;
    for (i = 0; i < 16; ++i) x[i] = 1.0f;
    if (spectral_centroid(x, 16, &c, &p, &b, &t) != 0) return 1;
    if (!(c >= 0.0f) || !(p >= 0.0f) || !(t >= 0.0f)) return 2;
    if (b < 0 || b > 8) return 3;
    puts("public_test: PASS");
    return 0;
}
