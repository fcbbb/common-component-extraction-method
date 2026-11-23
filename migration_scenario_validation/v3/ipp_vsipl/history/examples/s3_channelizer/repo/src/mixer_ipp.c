/* NCO mixer (IPP backend). */
#include "channelizer_internal.h"

#include <ipp.h>

int wc_mix_block(wc_state *st, const float *in_re, const float *in_im, int nin)
{
    int done = 0;

    if (!st || !in_re || !in_im || nin <= 0) return -1;
    if (wc_reserve_history(st, st->hfill + nin) != 0) return -1;
    if (wc_reserve_mix(st, nin) != 0) return -1;

    while (done < nin) {
        int seg = st->nco_len - st->ph;
        Ipp32fc *iq = (Ipp32fc *)st->iq;
        Ipp32fc *nco = (Ipp32fc *)st->nco_iq;

        if (seg > nin - done) seg = nin - done;
        ippsRealToCplx_32f(in_re + done, in_im + done, iq, seg);
        ippsMul_32fc(iq, nco + st->ph, iq, seg);
        ippsCplxToReal_32fc(iq, st->mix_re, st->mix_im, seg);
        {
            int i;
            for (i = 0; i < seg; ++i) {
                st->hist_re[st->hfill + done + i] = st->mix_re[i];
                st->hist_im[st->hfill + done + i] = st->mix_im[i];
            }
        }
        st->ph += seg;
        if (st->ph >= st->nco_len) st->ph -= st->nco_len;
        done += seg;
    }
    st->hfill += nin;
    st->gtotal += nin;
    return 0;
}