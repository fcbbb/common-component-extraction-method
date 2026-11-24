#ifndef SPECTRAL_CENTROID_H
#define SPECTRAL_CENTROID_H
#ifdef __cplusplus
extern "C" {
#endif
int spectral_centroid(const float *input, int nfft,
                      float *centroid, float *peak, int *peak_bin,
                      float *total);
#ifdef __cplusplus
}
#endif
#endif
