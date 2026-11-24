#ifndef STREAM_MIX_FIR_H
#define STREAM_MIX_FIR_H
#ifdef __cplusplus
extern "C" {
#endif
int stream_mix_fir(const float *in_re, const float *in_im, int nin,
                   const float *nco_re, const float *nco_im, int nco_len,
                   int *phase, const float *taps, int ntaps, int decim,
                   float *out_re, float *out_im, int out_cap, int *nout,
                   float *peak, float *energy);
#ifdef __cplusplus
}
#endif
#endif
