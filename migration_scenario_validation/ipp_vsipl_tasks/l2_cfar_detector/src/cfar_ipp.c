/* IPP baseline for the CA-CFAR detector.  This is the migration *source*:
 * the agent's job is to replace every ipps* call with VSIPL while keeping
 * include/cfar.h and the observable behaviour unchanged.
 */
#include "cfar.h"

#include <ipp.h>
#include <math.h>
#include <stdlib.h>

struct cfar_state {
    int nguard;
    int ntrain;
    float alpha;
};

cfar_state *cfar_create(int nguard, int ntrain, float pfa)
{
    cfar_state *s;
    Ipp32f p, t;
    int n0;

    if (nguard < 0 || ntrain < 1 || !(pfa > 0.0f) || !(pfa < 1.0f)) return NULL;

    s = (cfar_state *)ippsMalloc_8u(sizeof(*s));
    if (!s) return NULL;
    s->nguard = nguard;
    s->ntrain = ntrain;

    /* alpha = N0 * (pfa^(-1/N0) - 1), evaluated with the IPP vector math
     * library on a single element. */
    n0 = 2 * ntrain;
    p = pfa;
    ippsLn_32f(&p, &t, 1);          /* ln(pfa)                     */
    ippsDivC_32f(&t, (Ipp32f)(-n0), &t, 1);  /* -ln(pfa)/N0       */
    ippsExp_32f(&t, &t, 1);         /* pfa^(-1/N0)                 */
    ippsSubC_32f(&t, 1.0f, &t, 1);
    ippsMulC_32f(&t, (Ipp32f)n0, &t, 1);
    s->alpha = t;
    return s;
}

void cfar_destroy(cfar_state *s)
{
    if (s) ippsFree(s);
}

int cfar_detect(cfar_state *s, const float *mag2, int n, unsigned char *flags)
{
    Ipp32f *thr;
    int i, det = 0;

    if (!s || !mag2 || !flags || n <= 0) return -1;

    thr = (Ipp32f *)ippsMalloc_32f(n);
    if (!thr) return -1;

    for (i = 0; i < n; ++i) {
        int l0 = i - s->nguard - s->ntrain, l1 = i - s->nguard - 1;
        int r0 = i + s->nguard + 1, r1 = i + s->nguard + s->ntrain;
        Ipp32f sl = 0.0f, sr = 0.0f;
        int cnt = 0;

        if (l0 < 0) l0 = 0;
        if (r1 > n - 1) r1 = n - 1;
        if (l1 >= l0 && l0 < n) {
            ippsSum_32f(mag2 + l0, l1 - l0 + 1, &sl, ippAlgHintNone);
            cnt += l1 - l0 + 1;
        }
        if (r1 >= r0 && r0 < n) {
            ippsSum_32f(mag2 + r0, r1 - r0 + 1, &sr, ippAlgHintNone);
            cnt += r1 - r0 + 1;
        }

        if (cnt > 0) {
            Ipp32f mean;
            ippsAddC_32f(&sl, sr, &mean, 1);
            ippsDivC_32f(&mean, (Ipp32f)cnt, &mean, 1);
            ippsMulC_32f(&mean, s->alpha, &thr[i], 1);
        } else {
            thr[i] = -1.0f;   /* no training data: never flag (mag2 >= 0) */
        }
    }

    for (i = 0; i < n; ++i) {
        flags[i] = (mag2[i] > thr[i]) ? 1 : 0;
        det += flags[i];
    }

    ippsFree(thr);
    return det;
}