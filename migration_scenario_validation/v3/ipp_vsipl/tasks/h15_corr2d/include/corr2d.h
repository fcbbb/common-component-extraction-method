#ifndef CORR2D_H
#define CORR2D_H
#ifdef __cplusplus
extern "C" {
#endif
int corr2d(const float *x_re, const float *x_im, int rows, int cols,
           const float *ref_re, const float *ref_im,
           float *out_re, float *out_im);
#ifdef __cplusplus
}
#endif
#endif
