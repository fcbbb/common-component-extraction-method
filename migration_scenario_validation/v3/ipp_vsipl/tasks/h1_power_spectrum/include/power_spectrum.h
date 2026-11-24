/* One-frame real power spectrum. */
#ifndef POWER_SPECTRUM_H
#define POWER_SPECTRUM_H

#ifdef __cplusplus
extern "C" {
#endif

/* input has nfft real samples; power has nfft/2+1 bins.
 * peak, peak_bin and total_power may be NULL. */
int power_spectrum(const float *input, int nfft, float *power,
                   float *peak, int *peak_bin, float *total_power);

#ifdef __cplusplus
}
#endif

#endif /* POWER_SPECTRUM_H */
