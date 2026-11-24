#ifndef MC_FIR_H
#define MC_FIR_H
#ifdef __cplusplus
extern "C" {
#endif
int mc_fir(const float *x0, const float *x1, const float *taps, int n,
           int ntaps, float *y0, float *y1, float *peak, float *energy);
#ifdef __cplusplus
}
#endif
#endif
