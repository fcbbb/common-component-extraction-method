/* Public self-check for the TDFIR filter bank.
 *
 * Deliberately tiny: one configuration, reference computed in direct form
 * right here, so the agent can sanity-check the migration without seeing the
 * hidden cases or the golden data.
 */
#include "tdfir.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#define NTAPS 5
#define NFILT 2
#define BLOCK 16
#define NBLK  3
#define TOTAL (BLOCK * NBLK)

int main(void)
{
    float taps[NTAPS * NFILT];
    float in[TOTAL];
    float got[TOTAL * NFILT];
    double ref[TOTAL * NFILT];
    tdfir_bank *b;
    int m, k, i, fail = 0;
    double worst = 0.0;

    for (m = 0; m < NFILT; ++m)
        for (k = 0; k < NTAPS; ++k)
            taps[m * NTAPS + k] = (float)(0.25 * (m + 1) - 0.1 * k);

    for (i = 0; i < TOTAL; ++i)
        in[i] = (float)(0.5 * sin(0.3 * i) + 0.2 * cos(0.11 * i * i));

    /* direct-form reference: zero history before sample 0 */
    for (m = 0; m < NFILT; ++m) {
        for (i = 0; i < TOTAL; ++i) {
            double acc = 0.0;
            for (k = 0; k < NTAPS; ++k) {
                int idx = i - k;
                if (idx >= 0) acc += (double)taps[m * NTAPS + k] * in[idx];
            }
            ref[m * TOTAL + i] = acc;
        }
    }

    b = tdfir_create(taps, NTAPS, NFILT, BLOCK);
    if (!b) { printf("FAIL: tdfir_create returned NULL\n"); return 1; }
    for (i = 0; i < NBLK; ++i) {
        if (tdfir_process(b, in + i * BLOCK, got + i * BLOCK * NFILT, BLOCK) != 0) {
            printf("FAIL: tdfir_process returned non-zero\n");
            tdfir_destroy(b);
            return 1;
        }
    }
    tdfir_destroy(b);

    /* tdfir_process writes block-major: got[blk * BLOCK * NFILT + m * BLOCK + i] */
    for (m = 0; m < NFILT; ++m) {
        for (i = 0; i < TOTAL; ++i) {
            int gi = (i / BLOCK) * BLOCK * NFILT + m * BLOCK + (i % BLOCK);
            double e = fabs((double)got[gi] - ref[m * TOTAL + i]);
            double scale = fabs(ref[m * TOTAL + i]) > 1.0 ? fabs(ref[m * TOTAL + i]) : 1.0;
            double rel = e / scale;
            if (rel > worst) worst = rel;
            if (rel > 1e-5 && e > 1e-6) {
                if (!fail)
                    printf("first mismatch at m=%d i=%d: got %g ref %g\n",
                           m, i, got[gi], ref[m * TOTAL + i]);
                fail = 1;
            }
        }
    }
    printf("public_test: %s worst_rel=%.3e\n", fail ? "FAIL" : "PASS", worst);
    return fail;
}