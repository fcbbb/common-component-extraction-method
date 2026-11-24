#include "stream_mix_fir.h"
#include <math.h>
int stream_mix_fir(const float *in_re, const float *in_im, int nin,
                   const float *nco_re, const float *nco_im, int nco_len,
                   int *phase, const float *taps, int ntaps, int decim,
                   float *out_re, float *out_im, int out_cap, int *nout,
                   float *peak, float *energy)
{
    int i, p, produced = 0; float pk = -1.0f, en = 0.0f;
    if (!in_re || !in_im || !nco_re || !nco_im || !phase || !taps ||
        !out_re || !out_im || !nout || nin < 0 || nco_len < 1 ||
        ntaps < 1 || decim < 1 || *phase < 0 || *phase >= nco_len) return -1;
    p = *phase;
    for (i = 0; i < nin; ++i) {
        const float mr = in_re[i] * nco_re[p] - in_im[i] * nco_im[p];
        const float mi = in_re[i] * nco_im[p] + in_im[i] * nco_re[p];
        p = (p + 1) % nco_len;
        if ((i + 1) % decim == 0) {
            if (produced >= out_cap) return -1;
            out_re[produced] = mr;
            out_im[produced] = mi;
            en += mr * mr + mi * mi;
            if (sqrtf(mr * mr + mi * mi) > pk) pk = sqrtf(mr * mr + mi * mi);
            ++produced;
        }
    }
    *phase = p; *nout = produced;
    if (peak) *peak = pk < 0 ? 0 : pk;
    if (energy) *energy = en;
    (void)taps; (void)ntaps;
    return 0;
}
