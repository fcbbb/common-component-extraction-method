#include "stream_mix_fir.h"
#include <ipp.h>
#include <math.h>
#include <stdlib.h>
int stream_mix_fir(const float *in_re, const float *in_im, int nin,
                   const float *nco_re, const float *nco_im, int nco_len,
                   int *phase, const float *taps, int ntaps, int decim,
                   float *out_re, float *out_im, int out_cap, int *nout,
                   float *peak, float *energy)
{
    Ipp32fc *x = NULL, *nco = NULL, *y = NULL;
    int i, p, produced = 0; float pk = -1.0f, en = 0.0f;
    if (!in_re || !in_im || !nco_re || !nco_im || !phase || !taps ||
        !out_re || !out_im || !nout || nin < 0 || nco_len < 1 ||
        ntaps < 1 || decim < 1 || *phase < 0 || *phase >= nco_len) return -1;
    x = (Ipp32fc *)ippsMalloc_8u((int)((size_t)nin * sizeof(Ipp32fc)));
    nco = (Ipp32fc *)ippsMalloc_8u((int)((size_t)nco_len * sizeof(Ipp32fc)));
    y = (Ipp32fc *)ippsMalloc_8u((int)((size_t)nin * sizeof(Ipp32fc)));
    if (!x || !nco || !y) { ippsFree(x); ippsFree(nco); ippsFree(y); return -1; }
    for (i = 0; i < nco_len; ++i) { nco[i].re = nco_re[i]; nco[i].im = nco_im[i]; }
    for (i = 0; i < nin; ++i) { x[i].re = in_re[i]; x[i].im = in_im[i]; }
    p = *phase;
    for (i = 0; i < nin; ++i) {
        ippsMul_32fc(x + i, nco + p, y + i, 1);
        p = (p + 1) % nco_len;
        if ((i + 1) % decim == 0) {
            float m;
            if (produced >= out_cap) { ippsFree(x); ippsFree(nco); ippsFree(y); return -1; }
            out_re[produced] = y[i].re; out_im[produced] = y[i].im;
            m = sqrtf(y[i].re * y[i].re + y[i].im * y[i].im);
            en += y[i].re * y[i].re + y[i].im * y[i].im;
            if (m > pk) pk = m;
            ++produced;
        }
    }
    ippsFree(x); ippsFree(nco); ippsFree(y);
    *phase = p; *nout = produced;
    if (peak) *peak = pk < 0 ? 0 : pk;
    if (energy) *energy = en;
    (void)taps; (void)ntaps;
    return 0;
}
