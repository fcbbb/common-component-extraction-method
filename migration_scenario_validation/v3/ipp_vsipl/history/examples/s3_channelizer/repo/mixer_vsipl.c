/* NCO mixer (VSIPL backend). */
#include "channelizer_internal.h"

#include <vsip.h>

int wc_mix_block(wc_state *st, const float *in_re, const float *in_im, int nin)
{
    int done = 0;

    if (!st || !in_re || !in_im || nin <= 0) return -1;
    if (wc_reserve_history(st, st->hfill + nin) != 0) return -1;
    if (wc_reserve_mix(st, nin) != 0) return -1;

    while (done < nin) {
        int seg = st->nco_len - st->ph;
        int i;

        if (seg > nin - done) seg = nin - done;
        for (i = 0; i < seg; ++i) {
            const int tap = st->ph + i;
            const vsip_cscalar_f x = vsip_cmplx_f(in_re[done + i],
                                                  in_im[done + i]);
            const vsip_cscalar_f n = vsip_cmplx_f(st->nco_re[tap],
                                                  st->nco_im[tap]);
            const vsip_cscalar_f y = vsip_cmul_f(x, n);
            st->hist_re[st->hfill + done + i] = y.r;
            st->hist_im[st->hfill + done + i] = y.i;
        }
        st->ph += seg;
        if (st->ph >= st->nco_len) st->ph -= st->nco_len;
        done += seg;
    }
    st->hfill += nin;
    st->gtotal += nin;
    return 0;
}