/* Public self-check: the dB magnitude kernel against a double-precision
 * reference written out here, including the floor clamp and the argument
 * contract.
 */
#include "dbmag.h"

#include <math.h>
#include <stdio.h>

#define N 96

int main(void)
{
    float re[N], im[N], out[N];
    double expect[N];
    const float floor_mag = 1.0e-6f;
    const float offset = -3.5f;
    int i, fail = 0;
    double worst = 0.0;

    for (i = 0; i < N; ++i) {
        re[i] = (float)(1.5 * sin(0.31 * i));
        im[i] = (float)(1.2 * cos(0.17 * i));
        if (i % 24 == 0) { re[i] = 0.0f; im[i] = 0.0f; }   /* exact zero */
        if (i % 31 == 0) { re[i] = 1.0e-9f; im[i] = 0.0f; } /* below floor */
        {
            double m = sqrt((double)re[i] * re[i] + (double)im[i] * im[i]);
            if (m < (double)floor_mag) m = (double)floor_mag;
            expect[i] = 20.0 * log10(m) + (double)offset;
        }
    }

    if (vec_db_mag(re, im, N, floor_mag, offset, out) != 0) {
        printf("FAIL: vec_db_mag returned non-zero\n");
        return 1;
    }

    for (i = 0; i < N; ++i) {
        double e = fabs((double)out[i] - expect[i]);
        double rel = (fabs(expect[i]) > 1.0) ? e / fabs(expect[i]) : e;
        if (rel > worst) worst = rel;
        if (rel > 1e-4 && e > 1e-5) {
            if (!fail)
                printf("first mismatch at %d: got %.9g want %.9g\n",
                       i, (double)out[i], expect[i]);
            fail = 1;
        }
    }

    /* exact 3+4i -> 20*log10(5) */
    {
        float r1[1] = { 3.0f }, i1[1] = { 4.0f }, o1[1];
        if (vec_db_mag(r1, i1, 1, 1.0e-9f, 0.0f, o1) != 0 ||
            fabs((double)o1[0] - 20.0 * log10(5.0)) > 1e-4) {
            printf("FAIL: 3+4i -> %.9g, want %.9g\n",
                   (double)o1[0], 20.0 * log10(5.0));
            fail = 1;
        }
    }

    /* argument contract */
    if (vec_db_mag(NULL, im, N, floor_mag, offset, out) != -1 ||
        vec_db_mag(re, NULL, N, floor_mag, offset, out) != -1 ||
        vec_db_mag(re, im, N, floor_mag, offset, NULL) != -1 ||
        vec_db_mag(re, im, 0, floor_mag, offset, out) != -1 ||
        vec_db_mag(re, im, N, 0.0f, offset, out) != -1 ||
        vec_db_mag(re, im, N, -1.0f, offset, out) != -1) {
        printf("FAIL: invalid arguments were not rejected\n");
        fail = 1;
    }

    printf("public_test: %s maxrel=%.3e\n", fail ? "FAIL" : "PASS", worst);
    return fail;
}