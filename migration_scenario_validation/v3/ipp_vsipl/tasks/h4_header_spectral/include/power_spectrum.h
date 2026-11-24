/* Header-only real spectral probe ABI.  The implementation is absent from
 * this snapshot; the reference after state is gold/. */
#ifndef POWER_SPECTRUM_H
#define POWER_SPECTRUM_H
#ifdef __cplusplus
extern "C" {
#endif
int power_spectrum(const float *input, int nfft, float *power,
                   float *peak, int *peak_bin, float *total_power);
#ifdef __cplusplus
}
#endif
#endif
