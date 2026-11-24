#ifndef NORM_CORR_H
#define NORM_CORR_H
#ifdef __cplusplus
extern "C" {
#endif
int norm_corr(const float *x, const float *ref, int n,
              int lag_min, int lag_max, float *out,
              float *peak, int *peak_lag);
#ifdef __cplusplus
}
#endif
#endif
