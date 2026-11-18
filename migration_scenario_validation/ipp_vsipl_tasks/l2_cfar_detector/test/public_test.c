/* Public self-check for the CA-CFAR detector.
 *
 * One small configuration with its reference computed here in double
 * precision.  Cells whose decision is a near tie (within 1e-3 relative of the
 * threshold) are skipped, matching the evaluator's rule.
 */
#include "cfar.h"

#include <math.h>
#include <stdio.h>

#define NGUARD 1
#define NTRAIN 4
#define NCELLS 48

int main(void)
{
    float mag2[NCELLS];
    unsigned char got[NCELLS];
    double alpha, thr[NCELLS];
    cfar_state *s;
    int i, k, det, fail = 0, scored = 0, skipped = 0;

    /* deterministic clutter plus two targets */
    for (i = 0; i < NCELLS; ++i)
        mag2[i] = (float)(0.2 + 1.7 * fabs(sin(0.7 * i + 0.3)));
    mag2[11] += 12.0f;
    mag2[35] += 9.0f;

    /* alpha and thresholds in double */
    {
        double n0 = 2.0 * NTRAIN;
        alpha = n0 * (pow(0.01, -1.0 / n0) - 1.0);
    }
    for (i = 0; i < NCELLS; ++i) {
        int l0 = i - NGUARD - NTRAIN, l1 = i - NGUARD - 1;
        int r0 = i + NGUARD + 1, r1 = i + NGUARD + NTRAIN;
        double sum = 0.0;
        int cnt = 0;
        if (l0 < 0) l0 = 0;
        if (r1 > NCELLS - 1) r1 = NCELLS - 1;
        for (k = l0; k <= l1; ++k) { sum += mag2[k]; ++cnt; }
        for (k = r0; k <= r1; ++k) { sum += mag2[k]; ++cnt; }
        thr[i] = (cnt > 0) ? alpha * sum / cnt : -1.0;
    }

    s = cfar_create(NGUARD, NTRAIN, 0.01f);
    if (!s) { printf("FAIL: cfar_create returned NULL\n"); return 1; }
    det = cfar_detect(s, mag2, NCELLS, got);
    cfar_destroy(s);
    if (det < 0) { printf("FAIL: cfar_detect returned %d\n", det); return 1; }

    for (i = 0; i < NCELLS; ++i) {
        double d = fabs((double)mag2[i] - thr[i]);
        if (thr[i] > 0.0 && d <= 1e-3 * thr[i]) { ++skipped; continue; }
        ++scored;
        if ((got[i] != 0) != (mag2[i] > thr[i])) {
            if (!fail) printf("first mismatch at %d: mag2=%g thr=%g got=%d\n",
                              i, (double)mag2[i], thr[i], got[i]);
            fail = 1;
        }
    }
    if (det != (int)0 && det < 2) {
        printf("note: only %d detections for 2 strong targets\n", det);
        fail = 1;
    }

    printf("public_test: %s detections=%d scored=%d skipped=%d\n",
           fail ? "FAIL" : "PASS", det, scored, skipped);
    return fail;
}