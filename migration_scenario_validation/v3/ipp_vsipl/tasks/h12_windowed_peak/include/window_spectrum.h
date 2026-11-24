/* Header-only windowed spectral probe ABI.  Implementation absent; gold/ is
 * the reference after state. */
#ifndef WINDOW_SPECTRUM_H
#define WINDOW_SPECTRUM_H
#ifdef __cplusplus
extern "C" {
#endif
int window_spectrum(const float *input, int nfft,
                    float *mag, float *peak, int *peak_bin, float *total);
#ifdef __cplusplus
}
#endif
#endif
