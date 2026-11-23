/* Public self-check: impulse response of a single biquad against the
 * difference equation written out here, plus a state carry-over check.
 */
#include "iir_eq.h"

#include <math.h>
#include <stdio.h>

#define BLOCK 16

int main(void)
{
    const float sos[5] = { 0.2f, 0.4f, 0.2f, -0.6f, 0.25f };
    float in[BLOCK * 2], got[BLOCK * 2];
    float w1 = 0.0f, w2 = 0.0f;
    iir_eq *eq;
    int i, fail = 0;
    double worst = 0.0;

    for (i = 0; i < BLOCK * 2; ++i) in[i] = (i == 0) ? 1.0f : 0.0f;

    eq = iir_eq_create(sos, 1, BLOCK);
    if (!eq) { printf("FAIL: iir_eq_create returned NULL\n"); return 1; }
    for (i = 0; i < 2; ++i) {
        if (iir_eq_process(eq, in + i * BLOCK, got + i * BLOCK, BLOCK) != 0) {
            printf("FAIL: iir_eq_process returned non-zero\n");
            iir_eq_destroy(eq);
            return 1;
        }
    }
    iir_eq_destroy(eq);

    for (i = 0; i < BLOCK * 2; ++i) {
        const float x = in[i];
        const float w = x - sos[3] * w1 - sos[4] * w2;
        const float y = sos[0] * w + sos[1] * w1 + sos[2] * w2;
        w2 = w1;
        w1 = w;
        {
            double e = fabs((double)got[i] - (double)y);
            if (e > worst) worst = e;
            if (e > 1e-5) {
                if (!fail) printf("first mismatch at %d: got %g ref %g\n",
                                  i, (double)got[i], (double)y);
                fail = 1;
            }
        }
    }

    printf("public_test: %s maxerr=%.3e\n", fail ? "FAIL" : "PASS", worst);
    return fail;
}