/* IPP baseline for the cascaded biquad equaliser.  This is the migration
 * source: the agent's job is to remove every ipps* call while keeping
 * include/iir_eq.h and the observable behaviour unchanged.
 *
 * Note that ippsIIRInit_BiQuad_32f wants SIX coefficients per section
 * (b0, b1, b2, a0, a1, a2) even though the public API in iir_eq.h uses five,
 * so create() expands the layout.
 */
#include "iir_eq.h"

#include <ipp.h>
#include <stdlib.h>
#include <string.h>

struct iir_eq {
    int nsections;
    int block;
    IppsIIRState_32f *state;
    Ipp8u *buf;
};

iir_eq *iir_eq_create(const float *sos, int nsections, int block)
{
    iir_eq *eq;
    Ipp32f *taps;
    int specSize = 0, m;

    if (!sos || nsections < 1 || block < 1) return NULL;
    if (ippsIIRGetStateSize_BiQuad_32f(nsections, &specSize) != ippStsNoErr)
        return NULL;

    eq = (iir_eq *)ippsMalloc_8u(sizeof(*eq));
    if (!eq) return NULL;
    memset(eq, 0, sizeof(*eq));
    eq->nsections = nsections;
    eq->block = block;

    eq->buf = (Ipp8u *)ippsMalloc_8u(specSize);
    taps = (Ipp32f *)ippsMalloc_32f(nsections * 6);
    if (!eq->buf || !taps) {
        if (taps) ippsFree(taps);
        iir_eq_destroy(eq);
        return NULL;
    }

    for (m = 0; m < nsections; ++m) {
        taps[m * 6 + 0] = sos[m * 5 + 0];
        taps[m * 6 + 1] = sos[m * 5 + 1];
        taps[m * 6 + 2] = sos[m * 5 + 2];
        taps[m * 6 + 3] = 1.0f;             /* a0 */
        taps[m * 6 + 4] = sos[m * 5 + 3];   /* a1 */
        taps[m * 6 + 5] = sos[m * 5 + 4];   /* a2 */
    }

    if (ippsIIRInit_BiQuad_32f(&eq->state, taps, nsections, NULL, eq->buf) != ippStsNoErr) {
        ippsFree(taps);
        iir_eq_destroy(eq);
        return NULL;
    }
    ippsFree(taps);
    return eq;
}

void iir_eq_destroy(iir_eq *eq)
{
    if (!eq) return;
    if (eq->buf) ippsFree(eq->buf);
    ippsFree(eq);
}

int iir_eq_process(iir_eq *eq, const float *in, float *out, int n)
{
    if (!eq || !in || !out || n != eq->block) return -1;
    if (ippsIIR_32f(in, out, n, eq->state) != ippStsNoErr) return -1;
    return 0;
}