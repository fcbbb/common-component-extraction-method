/* Decimating FIR and output scheduling (IPP backend). */
#include "channelizer_internal.h"

#include <ipp.h>

#include <string.h>

int wc_process(wc_state *st,
               const float *in_re, const float *in_im, int nin,
               float *out_re, float *out_im, wc_report *rep)
{
    long j;
    int produced = 0;

    if (!st || !in_re || !in_im || !out_re || !out_im || nin < 1) return -1;
    if (wc_mix_block(st, in_re, in_im, nin) != 0) return -1;

    j = st->jnext;
    for (;;) {
        const long center = j * (long)st->decim;
        const long li = center - st->base;
        Ipp32f rr, ri, ir, ii;

        if (li > (long)st->hfill - 1) break;
        if (center < (long)(st->T - 1)) { ++j; continue; }
        if (li < (long)st->T - 1) { ++j; continue; }

        ippsDotProd_32f(st->taps_re, st->hist_re + li - st->T + 1,
                        st->T, &rr);
        ippsDotProd_32f(st->taps_im, st->hist_im + li - st->T + 1,
                        st->T, &ri);
        ippsDotProd_32f(st->taps_re, st->hist_im + li - st->T + 1,
                        st->T, &ir);
        ippsDotProd_32f(st->taps_im, st->hist_re + li - st->T + 1,
                        st->T, &ii);

        out_re[produced] = rr - ri;
        out_im[produced] = ir + ii;
        ++produced;
        ++j;
    }
    st->jnext = j;

    if (st->T > 1 && st->hfill > st->T - 1) {
        const int drop = st->hfill - (st->T - 1);
        memmove(st->hist_re, st->hist_re + drop,
                (size_t)(st->T - 1) * sizeof(float));
        memmove(st->hist_im, st->hist_im + drop,
                (size_t)(st->T - 1) * sizeof(float));
        st->base += drop;
        st->hfill = st->T - 1;
    }

    if (rep) wc_fill_report(out_re, out_im, produced, rep);
    return produced;
}