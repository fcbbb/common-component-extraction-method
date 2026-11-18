/* IPP baseline for the TDFIR filter bank.  This is the migration *source*:
 * the agent's job is to replace every ipps* call with VSIPL while keeping
 * include/tdfir.h and the observable behaviour unchanged.
 */
#include "tdfir.h"

#include <ipp.h>
#include <string.h>

struct tdfir_bank {
    int ntaps;
    int nfilters;
    int block;
    IppsFIRSpec_32f **spec;  /* one spec per filter */
    Ipp32f **delay;          /* one delay line of ntaps-1 per filter */
    Ipp8u *buf;              /* shared scratch buffer */
    int bufsize;
};

static void free_bank(tdfir_bank *b)
{
    int m;
    if (!b) return;
    if (b->spec) {
        for (m = 0; m < b->nfilters; ++m) {
            if (b->spec[m]) ippsFree(b->spec[m]);
        }
        ippsFree(b->spec);
    }
    if (b->delay) {
        for (m = 0; m < b->nfilters; ++m) {
            if (b->delay[m]) ippsFree(b->delay[m]);
        }
        ippsFree(b->delay);
    }
    if (b->buf) ippsFree(b->buf);
    ippsFree(b);
}

tdfir_bank *tdfir_create(const float *taps, int ntaps, int nfilters, int block)
{
    tdfir_bank *b;
    int specSize = 0, bufSize = 0, m;

    if (!taps || ntaps <= 0 || nfilters <= 0 || block <= 0) return NULL;
    if (ippsFIRSRGetSize(ntaps, ipp32f, &specSize, &bufSize) != ippStsNoErr)
        return NULL;

    b = (tdfir_bank *)ippsMalloc_8u(sizeof(*b));
    if (!b) return NULL;
    memset(b, 0, sizeof(*b));
    b->ntaps = ntaps;
    b->nfilters = nfilters;
    b->block = block;
    b->bufsize = bufSize;

    b->spec = (IppsFIRSpec_32f **)ippsMalloc_8u(sizeof(*b->spec) * nfilters);
    b->delay = (Ipp32f **)ippsMalloc_8u(sizeof(*b->delay) * nfilters);
    b->buf = (Ipp8u *)ippsMalloc_8u(bufSize);
    if (!b->spec || !b->delay || !b->buf) { free_bank(b); return NULL; }

    memset(b->spec, 0, sizeof(*b->spec) * nfilters);
    memset(b->delay, 0, sizeof(*b->delay) * nfilters);

    for (m = 0; m < nfilters; ++m) {
        b->spec[m] = (IppsFIRSpec_32f *)ippsMalloc_8u(specSize);
        if (!b->spec[m]) { free_bank(b); return NULL; }
        if (ippsFIRSRInit_32f(taps + (size_t)m * ntaps, ntaps, ippAlgDirect,
                              b->spec[m]) != ippStsNoErr) {
            free_bank(b);
            return NULL;
        }
        if (ntaps > 1) {
            b->delay[m] = (Ipp32f *)ippsMalloc_32f(ntaps - 1);
            if (!b->delay[m]) { free_bank(b); return NULL; }
            ippsZero_32f(b->delay[m], ntaps - 1);
        }
    }
    return b;
}

void tdfir_destroy(tdfir_bank *b)
{
    free_bank(b);
}

int tdfir_process(tdfir_bank *b, const float *in, float *out, int n)
{
    int m;

    if (!b || !in || !out || n != b->block) return -1;

    for (m = 0; m < b->nfilters; ++m) {
        /* Delay lines are passed in and out so the stream continues across
         * calls; with no previous data the delay is all zeros. */
        if (ippsFIRSR_32f(in, out + (size_t)m * n, n, b->spec[m],
                          b->delay[m], b->delay[m], b->buf) != ippStsNoErr)
            return -1;
    }
    return 0;
}